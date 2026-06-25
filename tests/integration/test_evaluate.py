"""Integration tests for LLMEvaluator (OpenAI call seam mocked)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import evaluate_articles
import pytest
from evaluate_articles import LLMEvaluator

PROMPT = Path(__file__).resolve().parent.parent.parent / "prompts" / "relevance_evaluator.md"


def _articles() -> list[dict]:
    return [
        {"section": "us", "candidate_url": "https://apnews.com/article/a", "title": "A",
         "published_at": "2026-06-23T10:00:00+00:00", "extracted_text": "body a"},
        {"section": "us", "candidate_url": "https://apnews.com/article/b", "title": "B",
         "published_at": "2026-06-23T10:00:00+00:00", "extracted_text": "body b"},
    ]


def test_evaluate_batch_splits_selected_and_rejected(monkeypatch, evaluator_response):
    ev = LLMEvaluator(api_key="test")
    monkeypatch.setattr(ev, "_call_openai", lambda *a, **k: evaluator_response)

    out = ev.evaluate_batch(_articles(), PROMPT, {"us": 5})
    selected = [e for e in out if e.selected]
    rejected = [e for e in out if not e.selected]

    assert len(selected) == 1
    assert selected[0].candidate_id == "us_000"
    assert selected[0].relevance_score == 0.92
    assert len(rejected) == 1


def test_evaluate_batch_extracts_json_from_noisy_response(monkeypatch, evaluator_response):
    ev = LLMEvaluator(api_key="test")
    noisy = f"Here is the result:\n```json\n{evaluator_response}\n```"
    monkeypatch.setattr(ev, "_call_openai", lambda *a, **k: noisy)

    out = ev.evaluate_batch(_articles(), PROMPT, {"us": 5})
    assert any(e.selected for e in out)


def test_evaluate_batch_falls_back_to_secondary_model(monkeypatch, evaluator_response):
    ev = LLMEvaluator(api_key="test")
    calls = {"n": 0}

    def fake_call(messages, model=None):
        calls["n"] += 1
        return None if calls["n"] == 1 else evaluator_response

    monkeypatch.setattr(ev, "_call_openai", fake_call)
    out = ev.evaluate_batch(_articles(), PROMPT, {"us": 5})
    assert calls["n"] == 2
    assert any(e.selected for e in out)


def test_enforce_max_per_section(monkeypatch):
    ev = LLMEvaluator(api_key="test")
    resp = (
        '{"selected": ['
        '{"candidate_id": "us_000", "section": "us", "relevance_score": 0.5, '
        '"newsworthiness_score": 0.5, "reason": "r", "dedupe_group": "g"},'
        '{"candidate_id": "us_001", "section": "us", "relevance_score": 0.9, '
        '"newsworthiness_score": 0.9, "reason": "r", "dedupe_group": "g"}'
        '], "rejected": []}'
    )
    monkeypatch.setattr(ev, "_call_openai", lambda *a, **k: resp)

    out = ev.evaluate_batch(_articles(), PROMPT, {"us": 1})
    selected = [e for e in out if e.selected]
    # Only the highest-relevance one survives the cap of 1.
    assert len(selected) == 1
    assert selected[0].candidate_id == "us_001"


def test_constructor_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        LLMEvaluator()


def test_call_openai_uses_temperature_for_non_gpt5_models(monkeypatch):
    recorded = {}

    class FakeCompletions:
        def create(self, **kwargs):
            recorded.update(kwargs)

            class Message:
                content = json.dumps({"selected": [], "rejected": []})

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    ev = LLMEvaluator(api_key="test", model="gpt-4.1-mini", temperature=0.6)
    content = ev._call_openai([{"role": "user", "content": "hello"}])

    assert json.loads(content) == {"selected": [], "rejected": []}
    assert recorded["model"] == "gpt-4.1-mini"
    assert recorded["temperature"] == 0.6


def test_call_openai_returns_none_on_exception(monkeypatch, capsys):
    class FakeCompletions:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    ev = LLMEvaluator(api_key="test")
    assert ev._call_openai([{"role": "user", "content": "hello"}]) is None
    assert "OpenAI error (gpt-5-nano): boom" in capsys.readouterr().out


def test_evaluate_batch_raises_when_both_models_fail(monkeypatch):
    ev = LLMEvaluator(api_key="test")
    monkeypatch.setattr(ev, "_call_openai", lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="Both primary and fallback models failed"):
        ev.evaluate_batch(_articles(), PROMPT, {"us": 5})


def test_evaluate_batch_raises_for_unrecoverable_invalid_json(monkeypatch):
    ev = LLMEvaluator(api_key="test")
    monkeypatch.setattr(ev, "_call_openai", lambda *a, **k: "not json")

    with pytest.raises(RuntimeError, match="LLM returned invalid JSON"):
        ev.evaluate_batch(_articles(), PROMPT, {"us": 5})


def test_evaluate_batch_matches_selected_without_section_suffix_by_title(monkeypatch):
    ev = LLMEvaluator(api_key="test")
    resp = (
        '{"selected": ['
        '{"candidate_id": "custom-id", "title": "B", "relevance_score": 0.88, '
        '"newsworthiness_score": 0.77, "reason": "match by title", "dedupe_group": "g"}'
        '], "rejected": []}'
    )
    monkeypatch.setattr(ev, "_call_openai", lambda *a, **k: resp)

    out = ev.evaluate_batch(_articles(), PROMPT, {"us": 5})
    assert len(out) == 1
    assert out[0].candidate_id == "custom-id"
    assert out[0].section == "us"
    assert out[0].selected is True


def test_evaluate_batch_falls_back_for_unmatched_selected_candidate(monkeypatch):
    ev = LLMEvaluator(api_key="test")
    resp = (
        '{"selected": ['
        '{"candidate_id": "bad-id", "section": "world", "relevance_score": 0.51, '
        '"newsworthiness_score": 0.49, "reason": "fallback", "dedupe_group": "grp"}'
        '], "rejected": []}'
    )
    monkeypatch.setattr(ev, "_call_openai", lambda *a, **k: resp)

    out = ev.evaluate_batch(_articles(), PROMPT, {"world": 5})
    assert len(out) == 1
    assert out[0].candidate_id == "bad-id"
    assert out[0].section == "world"
    assert out[0].selected is True


def test_evaluate_batch_handles_unparseable_rejected_candidate_id(monkeypatch):
    ev = LLMEvaluator(api_key="test")
    resp = (
        '{"selected": [], "rejected": ['
        '{"candidate_id": "us_notanint", "reason": "bad id"},'
        '{"candidate_id": "plainid", "reason": "no suffix"}'
        ']}'
    )
    monkeypatch.setattr(ev, "_call_openai", lambda *a, **k: resp)

    out = ev.evaluate_batch(_articles(), PROMPT, {"us": 5})
    assert len(out) == 2
    assert all(item.selected is False for item in out)
    assert out[0].section == "us"
    assert out[1].section == "unknown"


def test_main_prints_selected_and_rejected(monkeypatch, capsys):
    fake_yaml = types.SimpleNamespace(
        safe_load=lambda text: {
            "sources": {
                "apnews": {
                    "sections": {
                        "us": {"max_stories": 2},
                    }
                }
            }
        }
    )
    monkeypatch.setitem(sys.modules, "yaml", fake_yaml)

    class FakeFile:
        def __init__(self, text):
            self._text = text

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._text

    original_open = open

    def fake_open(path, *args, **kwargs):
        if str(path).endswith("filtered_articles.json"):
            return FakeFile(json.dumps(_articles()))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    fake_response = json.dumps(
        {
            "selected": [
                {
                    "candidate_id": "us_000",
                    "section": "us",
                    "relevance_score": 0.9,
                    "newsworthiness_score": 0.8,
                    "reason": "Major story",
                    "dedupe_group": "g",
                }
            ],
            "rejected": [
                {
                    "candidate_id": "us_001",
                    "reason": "Low relevance",
                }
            ],
        }
    )

    class FakeCompletions:
        def create(self, **kwargs):
            class Message:
                content = fake_response

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    exec_globals = {"__name__": "__main__", "__file__": evaluate_articles.__file__}
    exec(Path(evaluate_articles.__file__).read_text(), exec_globals)

    out = capsys.readouterr().out
    assert "SELECTED us_000" in out
    assert "REJECTED us_001" in out

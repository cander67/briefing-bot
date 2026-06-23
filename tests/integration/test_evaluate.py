"""Integration tests for LLMEvaluator (OpenAI call seam mocked)."""

from __future__ import annotations

from pathlib import Path

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

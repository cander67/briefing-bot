"""Integration tests for LLMSummarizer (OpenAI call seam mocked)."""

from __future__ import annotations

from pathlib import Path

from summarize_articles import LLMSummarizer, SummarizedArticle

PROMPT = Path(__file__).resolve().parent.parent.parent / "prompts" / "article_summarizer.md"


def _article() -> dict:
    return {
        "candidate_id": "us_000",
        "section": "us",
        "title": "Example headline",
        "candidate_url": "https://apnews.com/article/example",
        "url_after_redirect": "https://apnews.com/article/example",
        "published_at": "2026-06-23T10:00:00+00:00",
        "extracted_text": "Full article body text here.",
    }


def test_summarize_builds_model(monkeypatch, summarizer_response):
    s = LLMSummarizer(api_key="test")
    monkeypatch.setattr(s, "_call_openai", lambda *a, **k: summarizer_response)

    out = s.summarize(_article(), PROMPT, "us_000")
    assert isinstance(out, SummarizedArticle)
    assert out.headline == "A clear headline"
    assert out.key_entities == ["Entity A", "Entity B"]
    assert out.candidate_id == "us_000"


def test_summarize_returns_none_on_failure(monkeypatch):
    s = LLMSummarizer(api_key="test")
    monkeypatch.setattr(s, "_call_openai", lambda *a, **k: None)
    assert s.summarize(_article(), PROMPT, "us_000") is None


def test_summarize_batch_filters_failures(monkeypatch, summarizer_response):
    s = LLMSummarizer(api_key="test")
    calls = {"n": 0}

    def fake_call(messages, model=None):
        calls["n"] += 1
        # First article's primary + fallback both fail; second succeeds.
        if calls["n"] <= 2:
            return None
        return summarizer_response

    monkeypatch.setattr(s, "_call_openai", fake_call)
    out = s.summarize_batch([_article(), _article()], PROMPT)
    assert len(out) == 1

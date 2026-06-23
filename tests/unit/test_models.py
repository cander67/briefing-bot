"""Unit tests for the pydantic data models."""

from __future__ import annotations

import pytest
from discover_articles import CandidateArticle
from evaluate_articles import EvaluatedArticle
from extract_articles import ExtractedArticle
from pydantic import ValidationError
from summarize_articles import SummarizedArticle


class TestCandidateArticle:
    def test_construct_and_dump(self):
        c = CandidateArticle(source="apnews", section="us", url="https://x")
        d = c.model_dump(mode="json")
        assert d["url"] == "https://x"
        assert d["title"] is None
        assert d["discovered_at"]  # auto-populated

    def test_timestamps_are_per_instance(self):
        # Regression: the old dataclass froze discovered_at at import time.
        a = CandidateArticle(source="apnews", section="us", url="https://a")
        b = CandidateArticle(source="apnews", section="us", url="https://b")
        assert a.discovered_at <= b.discovered_at

    def test_missing_required_field_fails(self):
        with pytest.raises(ValidationError):
            CandidateArticle(source="apnews", section="us")  # type: ignore[call-arg]


class TestEvaluatedArticle:
    def test_valid_scores(self):
        e = EvaluatedArticle(
            candidate_id="us_000",
            section="us",
            relevance_score=0.9,
            newsworthiness_score=0.8,
            reason="r",
            dedupe_group="g",
        )
        assert e.selected is False

    @pytest.mark.parametrize("score", [-0.1, 1.1])
    def test_rejects_out_of_range_relevance(self, score):
        with pytest.raises(ValidationError):
            EvaluatedArticle(
                candidate_id="us_000",
                section="us",
                relevance_score=score,
                newsworthiness_score=0.5,
                reason="r",
                dedupe_group="g",
            )


class TestExtractedArticle:
    def test_defaults(self):
        a = ExtractedArticle(candidate_url="https://x", source="apnews", section="us")
        assert a.extraction_success is False
        assert a.metadata == {}
        assert a.extracted_at


class TestSummarizedArticle:
    def test_roundtrip(self):
        s = SummarizedArticle(
            candidate_id="us_000",
            headline="H",
            source_title="T",
            source="AP News",
            url="https://x",
            published_at="2026-06-23T10:00:00+00:00",
            summary="s",
            why_it_matters="w",
            key_entities=["a", "b"],
            section="US",
        )
        assert s.model_dump(mode="json")["key_entities"] == ["a", "b"]

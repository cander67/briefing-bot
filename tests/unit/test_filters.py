"""Unit tests for apply_deterministic_filters."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
from run_daily_briefing import apply_deterministic_filters


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


@pytest.fixture
def article(extracted_article) -> dict:
    return extracted_article


class TestApplyDeterministicFilters:
    def test_keeps_valid_article(self, sample_config, article):
        out = apply_deterministic_filters([article], sample_config)
        assert len(out) == 1

    def test_rejects_stale_article(self, sample_config, article):
        article["published_at"] = _iso(hours_ago=100)  # older than 36h
        out = apply_deterministic_filters([article], sample_config)
        assert out == []

    def test_rejects_foreign_domain(self, sample_config, article):
        article["url_after_redirect"] = "https://example.com/article/x"
        article["candidate_url"] = "https://example.com/article/x"
        out = apply_deterministic_filters([article], sample_config)
        assert out == []

    def test_rejects_too_short(self, sample_config, article):
        article["chars_extracted"] = 0
        article["extracted_text"] = "tiny"
        out = apply_deterministic_filters([article], sample_config)
        assert out == []

    def test_rejects_missing_pubdate_when_required(self, sample_config, article):
        article["published_at"] = None
        article["metadata"] = {}
        out = apply_deterministic_filters([article], sample_config)
        assert out == []

    def test_dedupes_by_url(self, sample_config, article):
        dup = copy.deepcopy(article)
        out = apply_deterministic_filters([article, dup], sample_config)
        assert len(out) == 1

    def test_rejects_non_article_page(self, sample_config, article):
        article["url_after_redirect"] = "https://apnews.com/video/abc12345"
        article["candidate_url"] = "https://apnews.com/video/abc12345"
        out = apply_deterministic_filters([article], sample_config)
        assert out == []

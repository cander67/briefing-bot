"""Unit tests for discovery URL heuristics (pure functions)."""

from __future__ import annotations

from discover_articles import is_allowed_domain, is_likely_article, normalize_url


class TestIsAllowedDomain:
    def test_exact_match(self):
        assert is_allowed_domain("https://apnews.com/article/x", ["apnews.com"])

    def test_subdomain_match(self):
        assert is_allowed_domain("https://www.apnews.com/article/x", ["apnews.com"])

    def test_rejects_other_domain(self):
        assert not is_allowed_domain("https://example.com/article/x", ["apnews.com"])

    def test_rejects_lookalike_domain(self):
        assert not is_allowed_domain("https://notapnews.com/x", ["apnews.com"])


class TestIsLikelyArticle:
    def test_accepts_article_path(self):
        assert is_likely_article("https://apnews.com/article/foo-bar-abcdef12")

    def test_rejects_video(self):
        assert not is_likely_article("https://apnews.com/video/foo")

    def test_rejects_gallery(self):
        assert not is_likely_article("https://apnews.com/gallery/foo")

    def test_rejects_tag(self):
        assert not is_likely_article("https://apnews.com/tag/politics")

    def test_rejects_utm_tracking(self):
        assert not is_likely_article("https://apnews.com/article/x?utm_source=foo")


class TestNormalizeUrl:
    def test_resolves_relative(self):
        out = normalize_url("https://apnews.com/us-news", "/article/foo")
        assert out == "https://apnews.com/article/foo"

    def test_strips_query_and_fragment(self):
        out = normalize_url(
            "https://apnews.com", "https://apnews.com/article/foo?utm=x#comments"
        )
        assert out == "https://apnews.com/article/foo"

    def test_keeps_absolute(self):
        out = normalize_url("https://apnews.com", "https://apnews.com/article/foo")
        assert out == "https://apnews.com/article/foo"

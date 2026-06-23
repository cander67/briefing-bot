"""Integration tests for FirecrawlExtractor (the Firecrawl HTTP seam is mocked)."""

from __future__ import annotations

from extract_articles import ExtractedArticle, FirecrawlExtractor

FIRECRAWL_OK = {
    "data": {
        "url": "https://apnews.com/article/example-aaaaaaaa11112222",
        "title": "Example headline",
        "markdown": "# Example headline\n\nBody.",
        "summary": "A summary that bypasses the paywall and is long enough.",
        "metadata": {
            "og_title": "Example headline",
            "article:author": ["Jane Reporter"],
            "published_time": "2026-06-23T10:00:00+00:00",
        },
    }
}


def _candidate() -> dict:
    return {
        "url": "https://apnews.com/article/example-aaaaaaaa11112222",
        "source": "apnews",
        "section": "us",
    }


def test_extract_article_maps_fields(monkeypatch):
    ext = FirecrawlExtractor(api_key="test")
    monkeypatch.setattr(ext, "extract", lambda url: FIRECRAWL_OK)

    art = ext.extract_article(_candidate())
    assert isinstance(art, ExtractedArticle)
    assert art.extraction_success is True
    assert art.title == "Example headline"
    assert art.byline == "Jane Reporter"
    assert art.published_at == "2026-06-23T10:00:00+00:00"
    assert art.extracted_text.startswith("A summary")
    assert art.section == "us"


def test_extract_article_handles_failure(monkeypatch):
    ext = FirecrawlExtractor(api_key="test")
    monkeypatch.setattr(ext, "extract", lambda url: {"error": "rate limited"})

    art = ext.extract_article(_candidate())
    assert art.extraction_success is False
    assert art.extraction_error == "rate limited"


def test_extract_article_handles_no_response(monkeypatch):
    ext = FirecrawlExtractor(api_key="test")
    monkeypatch.setattr(ext, "extract", lambda url: None)

    art = ext.extract_article(_candidate())
    assert art.extraction_success is False


def test_dry_run_returns_mock_content():
    ext = FirecrawlExtractor(dry_run=True)
    art = ext.extract_article(_candidate())
    assert art.extraction_success is True
    assert art.chars_extracted > 0


def test_extract_batch(monkeypatch):
    ext = FirecrawlExtractor(api_key="test")
    monkeypatch.setattr(ext, "extract", lambda url: FIRECRAWL_OK)
    monkeypatch.setattr("extract_articles.time.sleep", lambda s: None)

    out = ext.extract_batch([_candidate(), _candidate()])
    assert len(out) == 2
    assert all(a.extraction_success for a in out)

"""Integration tests for FirecrawlExtractor (the Firecrawl HTTP seam is mocked)."""

from __future__ import annotations

import builtins

import httpx

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


def test_document_to_dict_prefers_metadata_dict():
    class Doc:
        metadata_dict = {
            "url": "https://apnews.com/article/doc",
            "og_title": "Doc title",
        }
        summary = "Summary"
        markdown = "# Markdown"
        html = "<p>html</p>"

    ext = FirecrawlExtractor(api_key="test")
    out = ext._document_to_dict(Doc())
    assert out["url"] == "https://apnews.com/article/doc"
    assert out["title"] == "Doc title"
    assert out["summary"] == "Summary"


def test_document_to_dict_falls_back_to_metadata_model_dump():
    class Metadata:
        def model_dump(self):
            return {"source_url": "https://apnews.com/article/fallback", "title": "Fallback title"}

    class Doc:
        metadata_dict = {}
        metadata = Metadata()
        summary = None
        markdown = None
        html = None

    ext = FirecrawlExtractor(api_key="test")
    out = ext._document_to_dict(Doc())
    assert out["url"] == "https://apnews.com/article/fallback"
    assert out["title"] == "Fallback title"
    assert out["metadata"] == {"source_url": "https://apnews.com/article/fallback", "title": "Fallback title"}


def test_extract_article_uses_gtm_author_and_truncates_markdown(monkeypatch):
    ext = FirecrawlExtractor(api_key="test", max_chars=20)
    monkeypatch.setattr(
        ext,
        "extract",
        lambda url: {
            "data": {
                "url": url,
                "title": "Example headline",
                "summary": "",
                "markdown": "M" * 50,
                "metadata": {
                    "title": "Example headline",
                    "gtm-dataLayer": '{"author":"Reporter Name"}',
                    "article:published_time": "2026-06-23T10:00:00+00:00",
                },
            }
        },
    )

    art = ext.extract_article(_candidate())
    assert art.byline == "Reporter Name"
    assert art.published_at == "2026-06-23T10:00:00+00:00"
    assert art.chars_extracted == 20
    assert art.extracted_text == "M" * 20
    assert art.extracted_markdown == "M" * 20


def test_extract_uses_sdk_retry_and_returns_document(monkeypatch):
    calls = {"count": 0}

    class Doc:
        metadata_dict = {
            "url": "https://apnews.com/article/sdk",
            "og_title": "SDK title",
        }
        summary = "SDK summary"
        markdown = "# SDK"
        html = None

    class FakeApp:
        def __init__(self, api_key):
            self.api_key = api_key

        def scrape(self, url, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("temporary")
            return Doc()

    monkeypatch.setattr("firecrawl.FirecrawlApp", FakeApp)
    monkeypatch.setattr("extract_articles.time.sleep", lambda s: None)

    ext = FirecrawlExtractor(api_key="test", retries=1)
    out = ext.extract("https://apnews.com/article/sdk")

    assert calls["count"] == 2
    assert out == {
        "data": {
            "url": "https://apnews.com/article/sdk",
            "title": "SDK title",
            "summary": "SDK summary",
            "markdown": "# SDK",
            "html": None,
            "metadata": {
                "url": "https://apnews.com/article/sdk",
                "og_title": "SDK title",
            },
        }
    }


def test_extract_http_fallback_retries_after_rate_limit(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "firecrawl":
            raise ImportError("no sdk")
        return original_import(name, *args, **kwargs)

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = "rate limited"

        def raise_for_status(self):
            if self.status_code >= 400 and self.status_code != 429:
                request = httpx.Request("POST", "https://api.firecrawl.dev/v1/scrape")
                response = httpx.Response(self.status_code, request=request, text=self.text)
                raise httpx.HTTPStatusError("bad response", request=request, response=response)

        def json(self):
            return self._payload

    class FakeClient:
        calls = 0

        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers, json):
            FakeClient.calls += 1
            if FakeClient.calls == 1:
                return FakeResponse(429)
            return FakeResponse(200, FIRECRAWL_OK)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr("extract_articles.httpx.Client", FakeClient)
    monkeypatch.setattr("extract_articles.time.sleep", lambda s: None)

    ext = FirecrawlExtractor(api_key="test", retries=1)
    out = ext.extract(_candidate()["url"])

    assert FakeClient.calls == 2
    assert out == FIRECRAWL_OK


def test_extract_http_fallback_returns_timeout_error(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "firecrawl":
            raise ImportError("no sdk")
        return original_import(name, *args, **kwargs)

    class TimeoutClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers, json):
            raise httpx.TimeoutException("slow")

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr("extract_articles.httpx.Client", TimeoutClient)
    monkeypatch.setattr("extract_articles.time.sleep", lambda s: None)

    ext = FirecrawlExtractor(api_key="test", retries=0)
    assert ext.extract(_candidate()["url"]) == {"error": "timeout"}

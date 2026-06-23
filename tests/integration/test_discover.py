"""Integration tests for discovery against a captured AP section page (HTTP mocked)."""

from __future__ import annotations

from pathlib import Path

import discover_articles
from discover_articles import extract_links_from_section

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "ap_section.html"


class FakeResponse:
    def __init__(self, text: str, url: str):
        self.text = text
        self.url = url

    def raise_for_status(self) -> None:
        pass


class FakeClient:
    def __init__(self, text: str):
        self._text = text

    def get(self, url: str, **kwargs) -> FakeResponse:
        return FakeResponse(self._text, url)


def test_extract_links_filters_and_dedupes():
    html_text = FIXTURE.read_text()
    client = FakeClient(html_text)

    candidates = extract_links_from_section(
        "https://apnews.com/us-news", ["apnews.com"], client
    )
    urls = [c.url for c in candidates]

    # Three real articles, deduped (the ?utm_ variant collapses onto the first).
    assert "https://apnews.com/article/first-story-aaaaaaaa11112222" in urls
    assert "https://apnews.com/article/second-story-bbbbbbbb33334444" in urls
    assert "https://apnews.com/article/third-story-dddddddd55556666" in urls
    # Filtered out:
    assert not any("/video/" in u for u in urls)
    assert not any("/tag/" in u for u in urls)
    assert not any("example.com" in u for u in urls)
    # Deduped:
    assert len(urls) == len(set(urls))
    assert len(urls) == 3
    # Section inferred from the section URL.
    assert all(c.section == "us" for c in candidates)


def test_network_failure_yields_no_candidates():
    class BoomClient:
        def get(self, *a, **k):
            raise RuntimeError("network down")

    out = extract_links_from_section(
        "https://apnews.com/us-news", ["apnews.com"], BoomClient()
    )
    assert out == []


def test_discover_all_sections_caps_and_dedupes(monkeypatch, sample_config):
    html_text = FIXTURE.read_text()

    class CtxClient(FakeClient):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        discover_articles.httpx, "Client", lambda *a, **k: CtxClient(html_text)
    )
    sample_config["extraction"]["max_candidate_urls_per_section"] = 2

    out = discover_articles.discover_all_sections(sample_config)
    # Two sections each capped at 2, then cross-section dedupe (same fixture) → 2 unique.
    assert len(out) == 2
    assert len({c.url for c in out}) == 2

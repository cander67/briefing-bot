#!/usr/bin/env python3
"""Firecrawl article extraction with retries and quality checks."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class ExtractedArticle(BaseModel):
    candidate_url: str
    source: str
    section: str
    title: str | None = None
    byline: str | None = None
    published_at: str | None = None
    extracted_text: str = ""
    extracted_markdown: str = ""
    chars_extracted: int = 0
    extraction_success: bool = False
    extraction_error: str | None = None
    url_after_redirect: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    extracted_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class FirecrawlExtractor:
    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: int = 45,
        retries: int = 2,
        max_chars: int = 12000,
        dry_run: bool = False,
    ):
        self.dry_run = dry_run
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        if not self.api_key and not self.dry_run:
            raise ValueError("FIRECRAWL_API_KEY not set in env or passed to constructor")
        self.timeout = timeout_seconds
        self.retries = retries
        self.max_chars = max_chars
        self.base_url = "https://api.firecrawl.dev/v1"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def extract(self, url: str) -> dict[str, Any] | None:
        """Call Firecrawl /scrape endpoint using firecrawl-py v2."""
        if self.dry_run:
            # Return mock successful extraction for dry-run
            mock_content = (
                f"# Mock Article\n\nThis is mock content extracted from {url}.\n\n"
                "It contains several paragraphs of text to simulate a real article extraction. "
                "The article discusses important topics and has sufficient length for testing. "
                "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor "
                "incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis "
                "nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. "
                "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore "
                "eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt "
                "in culpa qui officia deserunt mollit anim id est laborum.\n\n"
                "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium "
                "doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore "
                "veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim "
                "ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit, sed quia "
                "consequuntur magni dolores eos qui ratione voluptatem sequi nesciunt."
            )
            return {
                "data": {
                    "url": url,
                    "title": f"Mock Title for {url}",
                    "markdown": mock_content,
                    "text": mock_content.replace("# Mock Article\n\n", ""),
                    "metadata": {
                        "title": f"Mock Title for {url}",
                        "author": "Mock Author",
                        "publishedAt": "2026-06-17T08:30:00-07:00",
                    },
                }
            }

        # Use firecrawl-py v2 SDK
        try:
            from firecrawl import FirecrawlApp
        except ImportError:
            pass
        else:
            app = FirecrawlApp(api_key=self.api_key)
            for attempt in range(self.retries + 1):
                try:
                    # Use summary format to bypass paywall, also get markdown for reference
                    result = app.scrape(
                        url,
                        formats=["summary", "markdown"],
                        only_main_content=True,
                        wait_for=2000,
                        timeout=self.timeout * 1000,  # convert to ms
                    )
                    # Convert v2 Document to dict-like structure
                    return {"data": self._document_to_dict(result)}
                except Exception as e:
                    if attempt < self.retries:
                        wait = 2 ** attempt
                        print(f"[extract] SDK error on {url} ({e}); retry {attempt + 1}/{self.retries} in {wait}s")
                        time.sleep(wait)
                        continue
                    return {"error": str(e)}

        # Fallback to direct HTTP if SDK not available
        payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
            "waitFor": 2000,
        }
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        f"{self.base_url}/scrape",
                        headers=self._headers(),
                        json=payload,
                    )
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        print(f"[extract] Rate limited, waiting {wait}s...")
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return resp.json()
            except httpx.TimeoutException:
                if attempt < self.retries:
                    print(f"[extract] Timeout on {url}, retry {attempt + 1}/{self.retries}")
                    time.sleep(1)
                    continue
                return {"error": "timeout"}
            except httpx.HTTPStatusError as e:
                return {"error": f"http_{e.response.status_code}: {e.response.text[:200]}"}
            except Exception as e:
                if attempt < self.retries:
                    time.sleep(1)
                    continue
                return {"error": str(e)}
        return {"error": "max_retries_exceeded"}

    def _document_to_dict(self, doc) -> dict[str, Any]:
        """Convert firecrawl v2 Document to dict."""
        # Use metadata_dict property for full metadata as dict
        metadata = getattr(doc, "metadata_dict", {}) or {}
        if not metadata and hasattr(doc, "metadata"):
            metadata = doc.metadata.model_dump() if hasattr(doc.metadata, "model_dump") else {}
        return {
            "url": metadata.get("url") or metadata.get("source_url"),
            "title": metadata.get("og_title") or metadata.get("title"),
            "summary": getattr(doc, "summary", None),
            "markdown": getattr(doc, "markdown", None),
            "html": getattr(doc, "html", None),
            "metadata": metadata,
        }

    def extract_article(self, candidate: dict[str, Any]) -> ExtractedArticle:
        """Extract a single article from a candidate dict."""
        url = candidate["url"]
        source = candidate.get("source", "apnews")
        section = candidate.get("section", "unknown")

        print(f"[extract] Extracting: {url}")
        result = self.extract(url)

        if not result or result.get("error"):
            err = result.get("error", "unknown error") if result else "no response"
            return ExtractedArticle(
                candidate_url=url,
                source=source,
                section=section,
                extraction_success=False,
                extraction_error=err,
            )

        data = result.get("data", {})
        metadata = data.get("metadata", {})

        # Firecrawl v2 returns summary (bypasses paywall) and markdown
        summary = data.get("summary", "") or ""
        markdown = data.get("markdown", "") or ""

        # Prefer summary for extracted text (bypasses paywall), fallback to markdown
        text = summary if summary else markdown

        # Truncate if needed
        content = text
        if len(content) > self.max_chars:
            content = content[:self.max_chars]

        # Extract author from metadata (article:author is a list of URLs)
        author_list = metadata.get("article:author", [])
        byline = ", ".join(author_list) if author_list else None
        # Fallback to gtm-dataLayer authors field
        if not byline:
            gtm_authors = metadata.get("gtm-dataLayer", "")
            if "author" in gtm_authors:
                import re
                match = re.search(r'"author"\s*:\s*"([^"]+)"', gtm_authors)
                if match:
                    byline = match.group(1)

        # Published time
        published_at = metadata.get("published_time") or metadata.get("article:published_time")

        return ExtractedArticle(
            candidate_url=url,
            source=source,
            section=section,
            title=metadata.get("og_title") or metadata.get("title") or data.get("title"),
            byline=byline,
            published_at=published_at,
            extracted_text=text[:self.max_chars],
            extracted_markdown=markdown[:self.max_chars],
            chars_extracted=len(content),
            extraction_success=True,
            url_after_redirect=data.get("url") or url,
            metadata=metadata,
        )

    def extract_batch(self, candidates: list[dict[str, Any]]) -> list[ExtractedArticle]:
        """Extract multiple articles with polite delay."""
        results = []
        for i, cand in enumerate(candidates):
            result = self.extract_article(cand)
            results.append(result)
            if i < len(candidates) - 1:
                time.sleep(0.5)  # be nice to the API
        return results


if __name__ == "__main__":
    # Quick test with a known AP article
    import yaml
    cfg = yaml.safe_load(Path("config/daily_ap.yaml").read_text())
    ext = FirecrawlExtractor(
        timeout_seconds=cfg["extraction"]["timeout_seconds"],
        retries=cfg["extraction"]["retries"],
        max_chars=cfg["extraction"]["max_extract_chars_per_article"],
    )
    # Test with a sample URL - you'd pass real candidates from discover step
    test_candidates = [
        {"url": "https://apnews.com/article/test", "source": "apnews", "section": "us"}
    ]
    results = ext.extract_batch(test_candidates)
    for r in results:
        print(f"  Success: {r.extraction_success}, chars: {r.chars_extracted}, error: {r.extraction_error}")
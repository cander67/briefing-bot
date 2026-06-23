#!/usr/bin/env python3
"""Deterministic article URL discovery from AP News section pages."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from lxml import html
from pydantic import BaseModel, Field


class CandidateArticle(BaseModel):
    source: str
    section: str
    url: str
    title: str | None = None
    discovered_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# URL patterns to REJECT (non-article pages)
REJECT_PATTERNS = [
    r"^https?://apnews\.com/?$",  # homepage
    r"^https?://apnews\.com/hub/",  # hub/topic pages
    r"^https?://apnews\.com/(us-news|world-news|politics|business|technology|science|health|sports|entertainment)/?$",  # section landing pages
    r"^https?://apnews\.com/(us-news|world-news|politics|business|technology|science|health|sports|entertainment)/[a-z-]+/?$",  # sub-section pages like /us-news/education
    r"^https?://apnews\.com/[a-z-]+/?$",  # other top-level section pages like /education, /transportation
    r"^https?://apnews\.com/projects/",  # project/landing pages (elections, polling trackers)
    r"/video/",
    r"/gallery/",
    r"/photo-gallery",
    r"/author/",
    r"/tag/",
    r"/search",
    r"/section/",
    r"/topic/",
    r"/live/",
    r"/updates/",
    r"/newsletter",
    r"\?utm_",
    r"#comments",
]

# URL patterns that indicate article pages (positive signals)
ARTICLE_PATTERNS = [
    r"/article/",
    r"/[a-f0-9]{32}",  # AP article IDs often look like this
    r"/[a-z-]+-[a-f0-9]{8,}",
]


def is_allowed_domain(url: str, allowed_domains: list[str]) -> bool:
    """Check if URL domain matches allowlist."""
    parsed = urlparse(url)
    return any(parsed.netloc == d or parsed.netloc.endswith(f".{d}") for d in allowed_domains)


def is_likely_article(url: str) -> bool:
    """Heuristic: does this URL look like an article page?"""
    # Must NOT match reject patterns
    for pat in REJECT_PATTERNS:
        if re.search(pat, url):
            return False
    # Should match at least one positive pattern (relaxed for AP)
    return True


def normalize_url(base: str, href: str) -> str | None:
    """Resolve relative URLs and strip tracking params."""
    try:
        full = urljoin(base, href)
        parsed = urlparse(full)
        # Strip common tracking params
        clean = parsed._replace(query="", fragment="").geturl()
        return clean
    except Exception:
        return None


def extract_links_from_section(url: str, allowed_domains: list[str], client: httpx.Client) -> list[CandidateArticle]:
    """Fetch section page and extract candidate article links."""
    candidates = []
    try:
        resp = client.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        doc = html.fromstring(resp.text)
        base_url = str(resp.url)

        for link in doc.xpath("//a[@href]"):
            href = link.get("href", "").strip()
            if not href:
                continue

            full_url = normalize_url(base_url, href)
            if not full_url:
                continue

            if not is_allowed_domain(full_url, allowed_domains):
                continue

            if not is_likely_article(full_url):
                continue

            title = link.text_content().strip() if link.text_content() else None
            # Infer section from URL
            section = "us" if "us-news" in url else "world" if "world-news" in url else "unknown"

            candidates.append(CandidateArticle(
                source="apnews",
                section=section,
                url=full_url,
                title=title,
            ))

    except Exception as e:
        print(f"[discover] Failed to fetch {url}: {e}")

    # Dedupe by URL
    seen = set()
    unique = []
    for c in candidates:
        if c.url not in seen:
            seen.add(c.url)
            unique.append(c)

    return unique


def discover_all_sections(config: dict[str, Any]) -> list[CandidateArticle]:
    """Run discovery for all configured sections."""
    all_candidates = []
    allowed = config["sources"]["apnews"]["allowed_domains"]
    sections = config["sources"]["apnews"]["sections"]
    max_per_section = config["extraction"]["max_candidate_urls_per_section"]

    with httpx.Client(headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}) as client:
        for section_name, section_cfg in sections.items():
            print(f"[discover] Fetching section: {section_name}")
            for section_url in section_cfg["section_urls"]:
                candidates = extract_links_from_section(section_url, allowed, client)
                # Limit per section
                candidates = candidates[:max_per_section]
                all_candidates.extend(candidates)
                print(f"[discover]   Found {len(candidates)} candidates from {section_url}")

    # Dedupe across sections by URL (first occurrence wins, preserving section assignment).
    # A story appearing on both US and World pages should only be extracted once.
    seen: set[str] = set()
    unique: list[CandidateArticle] = []
    for c in all_candidates:
        if c.url not in seen:
            seen.add(c.url)
            unique.append(c)
    if len(unique) < len(all_candidates):
        print(f"[discover] Deduped {len(all_candidates) - len(unique)} cross-section duplicate(s)")

    return unique


if __name__ == "__main__":
    # Quick test
    import yaml
    cfg = yaml.safe_load(Path("config/daily_ap.yaml").read_text())
    results = discover_all_sections(cfg)
    for r in results[:5]:
        print(f"  {r.section}: {r.url} — {r.title[:80] if r.title else 'no title'}")
    print(f"\nTotal: {len(results)} candidates")
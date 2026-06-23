#!/usr/bin/env python3
"""Config loader with environment variable expansion."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class SectionConfig(BaseModel):
    section_urls: list[str]
    max_stories: int
    topic_description: str | None = None


class ApNewsSource(BaseModel):
    allowed_domains: list[str]
    sections: dict[str, SectionConfig]
    require_allowed_domain: bool = True
    require_publication_date: bool = True
    reject_if_older_than_hours: int = 36
    reject_non_article_pages: bool = True


class SourcesConfig(BaseModel):
    apnews: ApNewsSource


class BriefingMeta(BaseModel):
    name: str
    timezone: str = "America/Los_Angeles"
    max_total_stories: int = 10
    language: str = "en"


class ExtractionConfig(BaseModel):
    provider: str = "firecrawl"
    use_search_fallback: bool = False
    use_section_page_discovery: bool = True
    max_candidate_urls_per_section: int = 12
    max_extract_chars_per_article: int = 12000
    timeout_seconds: int = 45
    retries: int = 2


class LLMConfig(BaseModel):
    model: str
    fallback_model: str | None = None
    relevance_threshold: float = 0.70
    require_source_grounding: bool = True
    forbid_unsourced_claims: bool = True


class OutputConfig(BaseModel):
    output_dir: str
    save_raw_extracts: bool = True
    raw_extract_retention_days: int = 2
    briefing_retention_days: int = 5


class EmailConfig(BaseModel):
    enabled: bool = False
    fixed_recipient_list: bool = True
    subject_template: str = "Daily AP News Briefing — {date}"
    recipients_file: str | None = None


class BriefingConfig(BaseModel):
    """Validated shape of config/daily_ap.yaml."""

    briefing: BriefingMeta
    sources: SourcesConfig
    extraction: ExtractionConfig
    llm: LLMConfig
    output: OutputConfig
    email: EmailConfig


def expand_env_vars(value: Any) -> Any:
    """Recursively expand ${VAR:-default} in strings."""
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            var_expr = match.group(1)
            if ":-" in var_expr:
                var, default = var_expr.split(":-", 1)
                return os.getenv(var, default)
            return os.getenv(var_expr, match.group(0))
        return re.sub(r"\$\{([^}]+)\}", replace, value)
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(v) for v in value]
    return value


def load_config(path: Path) -> dict[str, Any]:
    """Load YAML config with env var expansion, validating its shape.

    Returns a plain dict (downstream code accesses it dict-style) but raises a
    clear pydantic ValidationError if the config is malformed.
    """
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    expanded = expand_env_vars(raw)
    BriefingConfig.model_validate(expanded)
    return expanded


if __name__ == "__main__":
    import sys
    cfg = load_config(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config/daily_ap.yaml"))
    import json
    print(json.dumps(cfg, indent=2))
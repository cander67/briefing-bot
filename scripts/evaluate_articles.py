#!/usr/bin/env python3
"""LLM-based article relevance evaluation using OpenAI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class EvaluatedArticle(BaseModel):
    candidate_id: str
    section: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    newsworthiness_score: float = Field(ge=0.0, le=1.0)
    reason: str
    dedupe_group: str
    selected: bool = False


class LLMEvaluator:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-5-nano",
        fallback_model: str = "gpt-5.4-nano",
        temperature: float = 0.1,
        max_retries: int = 2,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set in env or passed to constructor")
        self.model = model
        self.fallback_model = fallback_model
        self.temperature = temperature
        self.max_retries = max_retries

    def _load_prompt(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def _call_openai(self, messages: list[dict[str, str]], model: str | None = None) -> str | None:
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key)
        use_model = model or self.model
        # gpt-5 series doesn't support temperature parameter
        use_temperature = None if use_model.startswith("gpt-5") else self.temperature
        try:
            kwargs = {
                "model": use_model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "timeout": 60,
            }
            if use_temperature is not None:
                kwargs["temperature"] = use_temperature
            resp = client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
            return resp.choices[0].message.content
        except Exception as e:
            print(f"[evaluator] OpenAI error ({use_model}): {e}")
            return None

    def evaluate_batch(
        self,
        articles: list[dict[str, Any]],
        prompt_path: Path,
        max_per_section: dict[str, int],
    ) -> list[EvaluatedArticle]:
        """Evaluate articles using LLM for relevance and selection."""
        prompt_template = self._load_prompt(prompt_path)

        # Build candidate list for prompt
        candidates_text = []
        for i, a in enumerate(articles):
            cid = f"{a.get('section', 'unknown')}_{i:03d}"
            candidates_text.append(
                f"Candidate {cid}:\n"
                f"  Section: {a.get('section')}\n"
                f"  URL: {a.get('url_after_redirect') or a.get('candidate_url')}\n"
                f"  Title: {a.get('title')}\n"
                f"  Published: {a.get('published_at')}\n"
                f"  Excerpt: {(a.get('extracted_text') or '')[:2000]}..."
            )

        prompt = prompt_template.replace("{{CANDIDATES}}", "\n\n".join(candidates_text))

        # Try primary model, then fallback
        content = self._call_openai([{"role": "user", "content": prompt}])
        if content is None:
            print(f"[evaluator] Trying fallback model: {self.fallback_model}")
            content = self._call_openai([{"role": "user", "content": prompt}], model=self.fallback_model)

        if content is None:
            raise RuntimeError("Both primary and fallback models failed")

        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            # Try to extract JSON from response
            import re
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
            else:
                raise RuntimeError(f"LLM returned invalid JSON: {e}")

        selected = result.get("selected", [])
        rejected = result.get("rejected", [])

        # Map back to articles - handle various candidate_id formats
        evaluated = []
        for sel in selected:
            cid = sel["candidate_id"]
            # Try to parse as section_idx, fallback to sequential
            section = sel.get("section", "unknown")
            idx = None
            if "_" in cid:
                try:
                    section, idx_str = cid.rsplit("_", 1)
                    idx = int(idx_str)
                except (ValueError, IndexError):
                    pass
            else:
                # Try to find by matching title/url
                for i, a in enumerate(articles):
                    if a.get("title") == sel.get("title") or a.get("url_after_redirect") == sel.get("url"):
                        idx = i
                        section = a.get("section", "unknown")
                        break
            
            if idx is not None and idx < len(articles):
                a = articles[idx]
                evaluated.append(EvaluatedArticle(
                    candidate_id=cid,
                    section=sel.get("section", section),
                    relevance_score=sel.get("relevance_score", 0.0),
                    newsworthiness_score=sel.get("newsworthiness_score", 0.0),
                    reason=sel.get("reason", ""),
                    dedupe_group=sel.get("dedupe_group", ""),
                    selected=True,
                ))
            else:
                # Fallback: create entry with available info
                evaluated.append(EvaluatedArticle(
                    candidate_id=cid,
                    section=sel.get("section", "unknown"),
                    relevance_score=sel.get("relevance_score", 0.0),
                    newsworthiness_score=sel.get("newsworthiness_score", 0.0),
                    reason=sel.get("reason", ""),
                    dedupe_group=sel.get("dedupe_group", ""),
                    selected=True,
                ))

        for rej in rejected:
            cid = rej["candidate_id"]
            section = "unknown"
            idx = None
            if "_" in cid:
                try:
                    section, idx_str = cid.rsplit("_", 1)
                    idx = int(idx_str)
                except (ValueError, IndexError):
                    pass
            
            if idx is not None and idx < len(articles):
                a = articles[idx]
                evaluated.append(EvaluatedArticle(
                    candidate_id=cid,
                    section=section,
                    relevance_score=0.0,
                    newsworthiness_score=0.0,
                    reason=rej.get("reason", ""),
                    dedupe_group="",
                    selected=False,
                ))
            else:
                evaluated.append(EvaluatedArticle(
                    candidate_id=cid,
                    section=section,
                    relevance_score=0.0,
                    newsworthiness_score=0.0,
                    reason=rej.get("reason", ""),
                    dedupe_group="",
                    selected=False,
                ))

        # Enforce max per section
        evaluated = self._enforce_max_per_section(evaluated, max_per_section)

        return evaluated

    def _enforce_max_per_section(
        self,
        evaluated: list[EvaluatedArticle],
        max_per_section: dict[str, int],
    ) -> list[EvaluatedArticle]:
        """Sort by relevance and enforce max per section."""
        selected_by_section: dict[str, list[EvaluatedArticle]] = {}
        for e in evaluated:
            if e.selected:
                selected_by_section.setdefault(e.section, []).append(e)

        for section, items in selected_by_section.items():
            items.sort(key=lambda x: x.relevance_score, reverse=True)
            max_allowed = max_per_section.get(section, 5)
            for i, item in enumerate(items):
                if i >= max_allowed:
                    item.selected = False
                    item.reason = f"Exceeded section limit ({max_allowed})"

        return evaluated


if __name__ == "__main__":
    import yaml
    cfg = yaml.safe_load(Path("config/daily_ap.yaml").read_text())
    with open("outputs/2026-06-17/filtered_articles.json") as f:
        articles = json.load(f)

    evaluator = LLMEvaluator()
    prompt_path = Path("prompts/relevance_evaluator.md")
    max_per_section = {s: cfg["sources"]["apnews"]["sections"][s]["max_stories"]
                       for s in cfg["sources"]["apnews"]["sections"]}

    results = evaluator.evaluate_batch(articles, prompt_path, max_per_section)
    for r in results:
        status = "SELECTED" if r.selected else "REJECTED"
        print(f"  {status} {r.candidate_id}: rel={r.relevance_score:.2f}, news={r.newsworthiness_score:.2f}, {r.reason[:80]}")
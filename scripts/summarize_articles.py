#!/usr/bin/env python3
"""LLM-based article summarization using OpenAI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class SummarizedArticle(BaseModel):
    candidate_id: str
    headline: str
    source_title: str
    source: str
    url: str
    published_at: str
    summary: str
    why_it_matters: str
    key_entities: list[str]
    section: str


class LLMSummarizer:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-5-nano",
        fallback_model: str = "gpt-5.4-nano",
        temperature: float = 0.2,
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
            print(f"[summarizer] OpenAI error ({use_model}): {e}")
            return None

    def summarize(
        self,
        article: dict[str, Any],
        prompt_path: Path,
        candidate_id: str,
    ) -> SummarizedArticle | None:
        """Summarize a single selected article."""
        prompt_template = self._load_prompt(prompt_path)

        prompt = prompt_template.replace("{{ARTICLE_TEXT}}", article.get("extracted_text", "")[:10000])
        prompt = prompt.replace("{{TITLE}}", article.get("title", ""))
        prompt = prompt.replace("{{URL}}", article.get("url_after_redirect") or article.get("candidate_url", ""))
        prompt = prompt.replace("{{PUBLISHED_AT}}", article.get("published_at", ""))
        prompt = prompt.replace("{{SECTION}}", article.get("section", "").upper())

        content = self._call_openai([{"role": "user", "content": prompt}])
        if content is None:
            print(f"[summarizer] Trying fallback model: {self.fallback_model}")
            content = self._call_openai([{"role": "user", "content": prompt}], model=self.fallback_model)

        if content is None:
            return None

        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            import re
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
            else:
                print(f"[summarizer] Invalid JSON: {e}")
                return None

        return SummarizedArticle(
            candidate_id=candidate_id,
            headline=result.get("headline", ""),
            source_title=result.get("source_title", article.get("title", "")),
            source=result.get("source", "AP News"),
            url=result.get("url", article.get("url_after_redirect") or article.get("candidate_url", "")),
            published_at=result.get("published_at", article.get("published_at", "")),
            summary=result.get("summary", ""),
            why_it_matters=result.get("why_it_matters", ""),
            key_entities=result.get("key_entities", []),
            section=result.get("section", article.get("section", "").upper()),
        )

    def summarize_batch(
        self,
        selected_articles: list[dict[str, Any]],
        prompt_path: Path,
    ) -> list[SummarizedArticle]:
        """Summarize multiple selected articles."""
        results = []
        for i, article in enumerate(selected_articles):
            cid = article.get("candidate_id", f"article_{i}")
            print(f"[summarizer] Summarizing {cid}...")
            summary = self.summarize(article, prompt_path, cid)
            if summary:
                results.append(summary)
            else:
                print(f"[summarizer] Failed to summarize {cid}")
        return results


if __name__ == "__main__":
    import yaml
    cfg = yaml.safe_load(Path("config/daily_ap.yaml").read_text())
    with open("outputs/2026-06-17/evaluated_articles.json") as f:
        evaluated = json.load(f)

    selected = [a for a in evaluated if a.get("selected")]
    print(f"Summarizing {len(selected)} selected articles...")

    summarizer = LLMSummarizer()
    prompt_path = Path("prompts/article_summarizer.md")
    results = summarizer.summarize_batch(selected, prompt_path)

    output = [r.model_dump(mode="json") for r in results]
    with open("outputs/2026-06-17/summarized_articles.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved {len(results)} summaries to summarized_articles.json")
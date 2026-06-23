#!/usr/bin/env python3
"""Daily news briefing orchestrator — Phase 1+2: Discovery, Extraction, LLM Evaluation, Summarization, Rendering."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any

# Add scripts to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import load_config
from discover_articles import discover_all_sections
from extract_articles import FirecrawlExtractor


def load_yaml(path: Path) -> dict:
    return load_config(path)


def save_json(path: Path, data: dict | list) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def write_progress(run_dir: Path, phase_name: str, **kwargs) -> None:
    """Write a lightweight progress file for polling."""
    progress = {"phase": phase_name, "updated_at": datetime.now(timezone.utc).isoformat(), **kwargs}
    save_json(run_dir / "progress.json", progress)


def check_idempotency(run_dir: Path, force: bool) -> bool:
    """Check if briefing already exists for today. Returns True if should skip."""
    briefing_md = run_dir / "briefing.md"
    if briefing_md.exists() and not force:
        print(f"[pipeline] Briefing already exists at {briefing_md}. Use --force to re-run.")
        return True
    return False


def llm_model_kwargs(cfg: dict) -> dict:
    """Build model kwargs for LLM clients from config, omitting unset values."""
    llm_cfg = cfg.get("llm", {})
    kwargs = {}
    if llm_cfg.get("model"):
        kwargs["model"] = llm_cfg["model"]
    if llm_cfg.get("fallback_model"):
        kwargs["fallback_model"] = llm_cfg["fallback_model"]
    return kwargs


def alert_failure(cfg: dict, subject: str, body: str) -> None:
    """Best-effort failure alert; never raises (must not mask the original error)."""
    try:
        from send_briefing_email import send_failure_alert

        send_failure_alert(cfg, subject, body)
    except Exception as e:
        print(f"[pipeline] Failed to send failure alert: {e}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily AP news briefing pipeline")
    parser.add_argument("--config", required=True, help="Path to briefing config YAML")
    parser.add_argument("--dry-run", action="store_true", help="Run without LLM calls or email")
    parser.add_argument("--send", action="store_true", help="Send email (requires email config)")
    parser.add_argument("--force", action="store_true", help="Force re-run even if briefing already exists")
    parser.add_argument("--phase", choices=["discover", "extract", "evaluate", "summarize", "render", "send", "full"], default="full",
                        help="Run specific phase or full pipeline")
    parser.add_argument("--max-extractions", type=int, default=None,
                        help="Dev cap: limit Firecrawl scrape calls to N (conserves credits). "
                             "Defaults to env NEWSBOT_MAX_EXTRACTIONS if set.")
    args = parser.parse_args()

    max_extractions = args.max_extractions
    if max_extractions is None and os.getenv("NEWSBOT_MAX_EXTRACTIONS"):
        max_extractions = int(os.environ["NEWSBOT_MAX_EXTRACTIONS"])

    config_path = Path(args.config)
    cfg = load_yaml(config_path)

    # Resolve output directory
    output_root = Path(cfg["output"]["output_dir"]).expanduser().resolve()
    # Use configured timezone for the date (config has timezone: America/Los_Angeles)
    tz_name = cfg["briefing"].get("timezone", "UTC")
    tz: tzinfo
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    today = datetime.now(tz).strftime("%Y-%m-%d")
    run_dir = output_root / today
    run_dir.mkdir(parents=True, exist_ok=True)

    # Idempotency guard: skip if briefing already exists (unless --force)
    if args.phase == "full" and check_idempotency(run_dir, args.force):
        return 0

    # Initial progress
    write_progress(run_dir, "starting", phase=args.phase)

    # Initialize run log
    run_log = {
        "status": "started",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": str(config_path),
        "cwd": os.getcwd(),
        "briefing_name": cfg["briefing"]["name"],
        "email_send_requested": bool(args.send),
        "phase": args.phase,
        "steps": {},
    }

    try:
        # === PHASE 1: DISCOVERY ===
        if args.phase in ("discover", "full"):
            print("[pipeline] Running article discovery...")
            candidates = discover_all_sections(cfg)
            candidates_data = [c.model_dump(mode="json") for c in candidates]

            save_json(run_dir / "candidate_articles.json", candidates_data)
            run_log["steps"]["discovery"] = {
                "status": "success",
                "candidate_count": len(candidates),
                "output": "candidate_articles.json",
            }
            write_progress(run_dir, "discovery", candidate_count=len(candidates))
            print(f"[pipeline] Discovered {len(candidates)} candidates")
        else:
            # Load existing candidates for extract-only mode
            candidates_path = run_dir / "candidate_articles.json"
            if not candidates_path.exists():
                print(f"[pipeline] No candidate_articles.json found at {candidates_path}")
                return 1
            candidates_data = json.loads(candidates_path.read_text())
            run_log["steps"]["discovery"] = {"status": "skipped", "loaded": len(candidates_data)}

        # === PHASE 2: EXTRACTION ===
        if args.phase in ("extract", "full"):
            print("[pipeline] Running article extraction...")
            ext_cfg = cfg["extraction"]

            # Dev cap: hard-bound the number of Firecrawl scrape calls. Truncate
            # the candidate list AND disable retries so a failure can't multiply calls.
            retries = ext_cfg["retries"]
            if max_extractions is not None and not args.dry_run:
                print(f"[pipeline] DEV: capping extraction to {max_extractions} Firecrawl call(s)")
                candidates_data = candidates_data[:max_extractions]
                retries = 0

            # Load today's existing extraction results as a cache so re-runs
            # (--force or --phase extract) don't re-call Firecrawl for already-seen URLs.
            existing_path = run_dir / "extracted_articles.json"
            cached: dict[str, dict] = {}
            if existing_path.exists() and not args.dry_run:
                try:
                    for entry in json.loads(existing_path.read_text()):
                        url = entry.get("candidate_url") or entry.get("url")
                        if url:
                            cached[url] = entry
                except Exception:
                    pass
            if cached:
                print(f"[pipeline] Extraction cache: {len(cached)} URL(s) already extracted today")

            fresh_candidates = [c for c in candidates_data if c["url"] not in cached]
            skipped_count = len(candidates_data) - len(fresh_candidates)
            if skipped_count:
                print(f"[pipeline] Skipping {skipped_count} already-extracted URL(s)")

            extractor = FirecrawlExtractor(
                timeout_seconds=ext_cfg["timeout_seconds"],
                retries=retries,
                max_chars=ext_cfg["max_extract_chars_per_article"],
                dry_run=args.dry_run,
            )

            extracted = extractor.extract_batch(fresh_candidates)
            fresh_data = [e.model_dump(mode="json") for e in extracted]

            # Merge cached results with fresh, preserving candidate order.
            all_urls_ordered = [c["url"] for c in candidates_data]
            fresh_by_url = {e["candidate_url"]: e for e in fresh_data if e.get("candidate_url")}
            extracted_data: list[dict[str, Any]] = []
            for url in all_urls_ordered:
                entry = fresh_by_url.get(url) or cached.get(url)
                if entry is not None:
                    extracted_data.append(entry)

            save_json(run_dir / "extracted_articles.json", extracted_data)

            success_count = sum(1 for e in extracted_data if e.get("extraction_success"))
            run_log["steps"]["extraction"] = {
                "status": "success",
                "total": len(extracted_data),
                "successful": success_count,
                "failed": len(extracted_data) - success_count,
                "from_cache": skipped_count,
                "capped_to": max_extractions if (max_extractions is not None and not args.dry_run) else None,
                "output": "extracted_articles.json",
            }
            write_progress(run_dir, "extraction", total=len(extracted_data), successful=success_count)
            print(f"[pipeline] Extracted {success_count}/{len(extracted_data)} articles successfully")

            # Filter to successful extractions for next phases
            candidates_data = [e for e in extracted_data if e.get("extraction_success")]

        # === PHASE 3: FILTERING (deterministic) ===
        if args.phase in ("evaluate", "summarize", "render", "full") and candidates_data:
            print("[pipeline] Applying deterministic filters...")
            filtered = apply_deterministic_filters(candidates_data, cfg)
            save_json(run_dir / "filtered_articles.json", filtered)
            run_log["steps"]["filtering"] = {
                "status": "success",
                "input_count": len(candidates_data),
                "output_count": len(filtered),
                "output": "filtered_articles.json",
            }
            write_progress(run_dir, "filtering", input_count=len(candidates_data), output_count=len(filtered))
            print(f"[pipeline] Filtered to {len(filtered)} articles")
            candidates_data = filtered

        # === PHASE 4: LLM EVALUATION ===
        if args.phase in ("evaluate", "full") and candidates_data:
            if args.dry_run:
                print("[pipeline] Dry-run: skipping LLM evaluation")
                # Create dummy evaluated output
                evaluated = []
                for i, a in enumerate(candidates_data):
                    cid = f"{a.get('section', 'unknown')}_{i:03d}"
                    evaluated.append({
                        "candidate_id": cid,
                        "section": a.get("section"),
                        "relevance_score": 0.85,
                        "newsworthiness_score": 0.80,
                        "reason": "Dry-run placeholder",
                        "dedupe_group": "",
                        "selected": i < cfg["sources"]["apnews"]["sections"].get(a.get("section", ""), {}).get("max_stories", 5),
                    })
            else:
                print("[pipeline] Running LLM relevance evaluation...")
                from evaluate_articles import LLMEvaluator

                evaluator = LLMEvaluator(**llm_model_kwargs(cfg))
                prompt_path = Path("prompts/relevance_evaluator.md")
                max_per_section = {s: cfg["sources"]["apnews"]["sections"][s]["max_stories"]
                                   for s in cfg["sources"]["apnews"]["sections"]}

                evaluated_objs = evaluator.evaluate_batch(candidates_data, prompt_path, max_per_section)
                evaluated = [e.model_dump(mode="json") for e in evaluated_objs]

            save_json(run_dir / "evaluated_articles.json", evaluated)
            selected_count = sum(1 for e in evaluated if e.get("selected"))
            run_log["steps"]["evaluation"] = {
                "status": "success" if not args.dry_run else "skipped",
                "input_count": len(candidates_data),
                "selected_count": selected_count,
                "output": "evaluated_articles.json",
            }
            write_progress(run_dir, "evaluation", input_count=len(candidates_data), selected_count=selected_count)
            print(f"[pipeline] Evaluated: {selected_count} selected from {len(evaluated)}")

            # Filter to selected for next phases
            candidates_data = [e for e in evaluated if e.get("selected")]

        # === PHASE 5: LLM SUMMARIZATION ===
        if args.phase in ("summarize", "full") and candidates_data:
            if args.dry_run:
                print("[pipeline] Dry-run: skipping LLM summarization")
                # Create dummy summarized output
                summarized = []
                for e in candidates_data:
                    # Find matching filtered article
                    orig = next((a for a in filtered if f"{a.get('section', 'unknown')}_{i:03d}" == e["candidate_id"]), None)
                    if not orig:
                        orig = {}
                    summarized.append({
                        "candidate_id": e["candidate_id"],
                        "headline": f"Summary: {orig.get('title', 'Article')}",
                        "source_title": orig.get("title", ""),
                        "source": "AP News",
                        "url": orig.get("url_after_redirect") or orig.get("candidate_url", ""),
                        "published_at": orig.get("published_at", ""),
                        "summary": "Dry-run summary placeholder.",
                        "why_it_matters": "Dry-run significance placeholder.",
                        "key_entities": [],
                        "section": e.get("section", "").upper(),
                    })
            else:
                print("[pipeline] Running LLM article summarization...")
                from summarize_articles import LLMSummarizer

                summarizer = LLMSummarizer(**llm_model_kwargs(cfg))
                prompt_path = Path("prompts/article_summarizer.md")

                # We need the original filtered articles with content for summarization
                # Re-load filtered articles which have extracted_text
                with open(run_dir / "filtered_articles.json") as f:
                    filtered_articles = json.load(f)

                # Map evaluated candidates back to filtered articles
                filtered_map = {f"{a.get('section', 'unknown')}_{i:03d}": a for i, a in enumerate(filtered_articles)}
                selected_articles = []
                for e in candidates_data:
                    match = filtered_map.get(e["candidate_id"])
                    if match is not None:
                        selected_articles.append(match)

                summarized_objs = summarizer.summarize_batch(selected_articles, prompt_path)
                summarized = [s.model_dump(mode="json") for s in summarized_objs]

            save_json(run_dir / "summarized_articles.json", summarized)
            run_log["steps"]["summarization"] = {
                "status": "success" if not args.dry_run else "skipped",
                "input_count": len(candidates_data),
                "output_count": len(summarized),
                "output": "summarized_articles.json",
            }
            write_progress(run_dir, "summarization", input_count=len(candidates_data), output_count=len(summarized))
            print(f"[pipeline] Summarized {len(summarized)} articles")
            candidates_data = summarized

        # === PHASE 6: BRIEFING RENDERING ===
        if args.phase in ("render", "send", "full") and candidates_data:
            print("[pipeline] Rendering briefing...")
            from render_briefing import render_briefing

            briefing_path, email_path = render_briefing(candidates_data, cfg, run_dir, today)
            run_log["steps"]["rendering"] = {
                "status": "success",
                "output": ["briefing.md", "email_body.txt"],
            }
            write_progress(run_dir, "rendering", briefing_path=str(briefing_path))
            print("[pipeline] Rendered briefing.md and email_body.txt")

        # === PHASE 7: EMAIL SENDING ===
        if args.phase in ("send", "full") and args.send:
            if args.dry_run:
                print("[pipeline] Dry-run: skipping email send")
            else:
                print("[pipeline] Sending briefing email...")
                from send_briefing_email import send_briefing_email

                email_sent = send_briefing_email(cfg, today, dry_run=False)
                run_log["steps"]["email"] = {
                    "status": "success" if email_sent else "failed",
                }
                write_progress(run_dir, "email", sent=email_sent)
                print(f"[pipeline] Email {'sent' if email_sent else 'failed'}")
                if not email_sent:
                    # Surface to the failure handler so the run is marked failed
                    # and an alert is sent (a silent email failure is the worst case).
                    raise RuntimeError("Briefing email failed to send")

        if args.phase == "full" and not args.dry_run and not candidates_data:
            run_log["empty_run"] = True
            print("[pipeline] WARNING: run produced no articles")
            alert_failure(
                cfg,
                subject=f"[newsbot] Briefing run produced NO articles — {today}",
                body=(
                    f"The daily briefing pipeline completed on {today} but produced no articles.\n\n"
                    f"This usually means discovery, extraction, or evaluation filtered everything out.\n"
                    f"See {run_dir / 'run_log.json'} for per-phase counts."
                ),
            )

        run_log["status"] = "completed"
        run_log["completed_at"] = datetime.now(timezone.utc).isoformat()
        write_progress(run_dir, "completed")

    except Exception as e:
        run_log["status"] = "failed"
        run_log["error"] = str(e)
        run_log["completed_at"] = datetime.now(timezone.utc).isoformat()
        write_progress(run_dir, "failed", error=str(e))
        print(f"[pipeline] ERROR: {e}", file=sys.stderr)
        if not args.dry_run:
            failed_phase = next(
                (name for name, step in run_log["steps"].items() if step.get("status") not in ("success", "skipped")),
                "unknown",
            )
            alert_failure(
                cfg,
                subject=f"[newsbot] Briefing run FAILED — {today}",
                body=(
                    f"The daily briefing pipeline failed on {today}.\n\n"
                    f"Phase: {args.phase}\n"
                    f"Failed at step: {failed_phase}\n"
                    f"Error: {e}\n\n"
                    f"See {run_dir / 'run_log.json'} and logs/cron.log for details."
                ),
            )
        raise

    finally:
        save_json(run_dir / "run_log.json", run_log)
        print(f"[pipeline] Run log saved to {run_dir / 'run_log.json'}")

    return 0 if run_log["status"] == "completed" else 1


def apply_deterministic_filters(articles: list[dict], cfg: dict) -> list[dict]:
    """Apply hard filters from config: domain, date, min length, article page check, dedupe."""
    from datetime import datetime, timedelta, timezone
    from urllib.parse import urlparse

    allowed = cfg["sources"]["apnews"]["allowed_domains"]
    reject_older = cfg["sources"]["apnews"]["reject_if_older_than_hours"]
    min_chars = 500  # minimum viable article length

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=reject_older)

    filtered = []
    seen_urls = set()
    for a in articles:
        # Domain check
        url = a.get("url_after_redirect") or a.get("candidate_url") or a.get("url")
        if not url:
            continue

        # Dedupe by canonical URL (first occurrence wins)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        if not any(urlparse(url).netloc == d or urlparse(url).netloc.endswith(f".{d}") for d in allowed):
            continue

        # Date check
        pub_str = a.get("published_at") or a.get("metadata", {}).get("publishedAt")
        if pub_str:
            try:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                # Make timezone-aware if naive (assume UTC)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
            except Exception:
                if cfg["sources"]["apnews"]["require_publication_date"]:
                    continue
        elif cfg["sources"]["apnews"]["require_publication_date"]:
            continue

        # Content length check
        chars = a.get("chars_extracted", 0) or len(a.get("extracted_text", ""))
        if chars < min_chars:
            continue

        # Non-article page check (heuristic)
        if cfg["sources"]["apnews"]["reject_non_article_pages"]:
            if any(pat in url for pat in ["/video/", "/gallery/", "/author/", "/tag/", "/section/"]):
                continue

        filtered.append(a)

    return filtered


if __name__ == "__main__":
    sys.exit(main())
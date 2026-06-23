# Common Pitfalls & Fixes

## Firecrawl Extraction

| Issue | Fix |
|-------|-----|
| Paywall content returned | Use `formats=["summary", "markdown"]` — summary bypasses paywall |
| 400 Bad Request on formats | Firecrawl v2 requires specific format list; `["summary", "markdown"]` works |
| Timeout on slow pages | Increase `timeout_seconds` in config; add `wait_for=2000` |
| Rate limited | Built-in 0.5s delay + exponential backoff on 429 |

## LLM Evaluation/Summarization

| Issue | Fix |
|-------|-----|
| gpt-5-nano rejects temperature | Set `temperature=None` for gpt-5 models; use fallback gpt-4.1-nano with temperature=0.2 |
| JSON parsing fails | Use `response_format={"type": "json_object"}` + prompt must contain "json" word |
| Empty selections | Check candidate_id format matches `{section}_{idx}` |

## Date/Time Filtering

| Issue | Fix |
|-------|-----|
| Naive vs aware datetime comparison | Parse published dates, if naive assume UTC: `pub_dt.replace(tzinfo=timezone.utc)` |
| 36-hour window too narrow | Adjust `reject_if_older_than_hours` in `daily_ap.yaml` |

## Email Sending

| Issue | Fix |
|-------|-----|
| Recipients file not found | Config `recipients_file` must be absolute or relative to project root; use `${BRIEFING_OUTPUT_DIR:-./outputs}/../config/recipients.yaml` |
| SMTP auth fails | Gmail requires App Password, not login password |
| TLS error | Use port 587 with `starttls()` |

## Path Resolution

| Issue | Fix |
|-------|-----|
| Skill entrypoint can't find script | Use absolute path: `Path.home() / "hermes-newsbot"` |
| Config env vars not expanded | Use `config_loader.py` which expands `${VAR:-default}` |
| Cron runs in wrong directory | Set `cwd=project_root` in subprocess |

## Idempotency & Background Execution

| Issue | Fix |
|-------|-----|
| Accidental re-run wastes API credits | Use `--force` to override idempotency guard, or delete `outputs/{date}/briefing.md` |
| Pipeline times out in skill | Use `--background` flag in entrypoint; poll with `--status` or watch `progress.json` |
| Background process appears stuck | Check `progress.json` for current phase; check `run_log.json` for errors |
| Can't find progress file | Ensure date matches configured timezone (America/Los_Angeles); progress is in `outputs/{date}/progress.json` |

## Pipeline Debugging

```bash
# Dry run (no LLM, no email)
python scripts/run_daily_briefing.py --config config/daily_ap.yaml --dry-run

# Single phase
python scripts/run_daily_briefing.py --config config/daily_ap.yaml --phase extract

# View run log
cat outputs/2026-06-18/run_log.json | jq
```
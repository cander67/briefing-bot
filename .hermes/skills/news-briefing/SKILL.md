---
name: news-briefing
description: "Generate and email a daily AP News briefing (US & World) on demand or via cron"
category: productivity
tags: [news, briefing, email, cron, firecrawl, openai]
version: "1.1.0"
---

# News Briefing Skill

Generate a daily news briefing from AP News (US & World sections) and email it to configured recipients.

## Usage Patterns

| Pattern | Trigger | Command |
|---------|---------|---------|
| **A. Local on-demand** | Manual | `python scripts/run_daily_briefing.py --config config/daily_ap.yaml --phase full --send` |
| **B. Local cron** | Scheduled | `./run_daily_briefing_cron.sh` (installed via `./install_daily_briefing_cron.sh`) |
| **C. Hermes skill (on-demand, sync)** | User prompt | `news_briefing()` or `/news-briefing` |
| **D. Hermes cron (agent)** | Scheduled | `hermes cronjob create --name daily-briefing --schedule "0 6 * * *" --prompt "Run news briefing pipeline" --skills "news-briefing"` |
| **E. Hermes skill (background)** | User prompt | `news_briefing(background=true)` → poll with `--status` |

## Skill Invocation

```bash
# Via Hermes skill (pattern C) — synchronous, blocks until done
news_briefing()

# Background execution (pattern E) — returns immediately, poll for status
news_briefing(background=true)
# Check status:
python entrypoint.py --status
```

The skill calls the local script with full pipeline + email send.

### Entrypoint CLI Options

| Flag | Description |
|------|-------------|
| (none) | Run synchronously, blocks until pipeline completes |
| `--background` | Spawn pipeline as detached background process, return PID immediately |
| `--status` | Read `outputs/{date}/progress.json` and display current phase + metrics |
| `--force` | Override idempotency guard (re-run even if briefing already exists) |

### Idempotency Guard
Before running the full pipeline, the script checks `outputs/{date}/briefing.md`. If it exists, the run exits 0 with a message unless `--force` is passed. This prevents duplicate Firecrawl/OpenAI API credit consumption from accidental re-runs.

### Progress Tracking
A lightweight `progress.json` is written after each phase (`starting`, `discovery`, `extraction`, `filtering`, `evaluation`, `summarization`, `rendering`, `email`, `completed`, `failed`) with phase-specific metrics. Use `--status` or poll the file directly.

## Configuration

All config lives in the project:

```
~/hermes-newsbot/
├── config/
│   ├── daily_ap.yaml      # Sources, sections, limits, LLM settings
│   ├── recipients.yaml    # Email to/cc/bcc
│   └── retention.yaml     # Cleanup policy
├── .env                   # Secrets: FIRECRAWL_API_KEY, OPENAI_API_KEY, SMTP_*
├── scripts/
│   └── run_daily_briefing.py
└── prompts/
```

## Prerequisites

- Python 3.11+ with deps from `pyproject.toml` (`uv sync`) or `requirements.txt`
- `.env` populated with API keys
- Recipients configured in `config/recipients.yaml`

## Examples

**User:** "Email me a US & world news briefing"
**Agent:** Runs skill → executes pipeline → sends email

**User:** "Run the news briefing but don't send email"
**Agent:** `python scripts/run_daily_briefing.py --config config/daily_ap.yaml --phase full` (dry run)

**User:** "Set up daily automated briefings at 6 AM"
**Agent:** Creates Hermes cron job with the skill (pattern D)
```

## Requirements

See `pyproject.toml` (or `requirements.txt`):
- pyyaml, httpx, python-dotenv, lxml, firecrawl-py, openai

## Support Files (in this skill)

| File | Description |
|------|-------------|
| `scripts/entrypoint.py` | Hermes skill entry point — calls local pipeline with `--phase full --send`; supports `--background`, `--status`, `--force` |
| `references/pipeline-architecture.md` | Phase breakdown, technical decisions, context matrix, progress tracking & idempotency |
| `references/hermes-cron-setup.md` | Hermes cron job template + local cron alternative |
| `references/troubleshooting.md` | Common issues & fixes for Firecrawl, LLM, dates, email, paths, idempotency, background execution |
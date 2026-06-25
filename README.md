# Briefing Bot

[![CI](https://github.com/cander67/briefing-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/cander67/briefing-bot/actions/workflows/ci.yml)

This project is an example of a tool for creating a recurring briefing on a set of configured sources and delivering it to a fixed recipient list. Current awareness, daily digest, and other focused briefings are common in many organizations. This project implements such a briefing using Python scripts, an extraction API ([Firecrawl](https://firecrawl.dev)), an LLM for determining article relevance, ranking, and summarization ([OpenAI GPT-5 nano](https://developers.openai.com/api/docs/models/gpt-5-nano)), and email delivery. Helper scripts are included for cron scheduling, cleanup of old outputs, and running the pipeline as a Hermes skill if you wish to have your agent tailor the briefing to your needs. Strategies for tuning the briefing are included in the documentation below. The current implementation is a daily US and World news briefing, but the pipeline is designed to be source-flexible and could be adapted to other sources or topics.

Sample output from a run is included here for [markdown](https://github.com/cander67/briefing-bot/blob/main/sample_outputs/briefing.md) and here for [text](https://github.com/cander67/briefing-bot/blob/main/sample_outputs/email_body.txt).

My personal motivation for this project was to build a tool that would provide daily US and World news updates by email to keep me from scrolling the NYT. The approach was inspired by the [Hermes daily briefing bot](https://hermes-agent.nousresearch.com/docs/guides/daily-briefing-bot), but became a standalone implementation that does not require Hermes. I found that prompting the Hermes agent to focus on specific news sources was not reliable because the agent had too much information to sort through in a timely, cost-effective manner, and I wanted a more deterministic pipeline that could be tuned to my needs. This project is the result.

The current implementation is best suited for sources that have frequent updates, and a clear section structure. The pipeline is tuned for news content, but could be adapted for other types of content (e.g., blogs, forums, or social media). Sources with less frequent updates or less structured content might need additional customization or use of page monitoring. Briefings are generated in Markdown and plain text, but the pipeline could be adapted to produce other formats (e.g., HTML, PDF) if desired.

This project is a personal project for individual use.

> Version 1.0.0 (2026-06-25)

## How it works

The pipeline runs as a sequence of phases, each writing its output as JSON into a dated run directory under `outputs/<YYYY-MM-DD>/`:

1. **Discover** — collect candidate article URLs from configured section pages.
2. **Extract** — fetch and clean article content via [Firecrawl](https://firecrawl.dev).
3. **Filter** — deterministic filters (allowed domain, recency, min length, dedupe, non-article page rejection).
4. **Evaluate** — LLM scores each article for relevance/newsworthiness and selects the top stories per section.
5. **Summarize** — LLM writes a summary, "why it matters", and key entities for each selected article.
6. **Render** — produce `briefing.md` and `email_body.txt`.
7. **Send** — email the briefing to the recipient list (only when `--send` is passed).

## Layout

| Path | Purpose |
|------|---------|
| `scripts/` | Pipeline code; `run_daily_briefing.py` is the orchestrator entry point. |
| `config/` | Briefing config (`daily_ap.yaml`), recipients, and retention settings. |
| `prompts/` | LLM prompt templates for evaluation, summarization, and synthesis. |
| `outputs/` | Per-day run artifacts (candidate/extracted/evaluated/summarized JSON, briefing, run log). |
| `cache/` | Run lock and transient cache files. |
| `logs/` | Cron and run logs. |
| `.hermes/skills/news-briefing/` | Hermes skill for on-demand or scheduled execution. |

## Setup

**Python 3.11+** required. The project is uv-managed (`pyproject.toml` + `uv.lock`).

1. Clone and install dependencies:

   ```bash
   git clone <repo-url> briefing-bot && cd briefing-bot

   # With uv (recommended) — creates .venv from the lockfile
   uv sync

   # Or with conda
   conda create -n briefing-bot python=3.11 && conda activate briefing-bot && pip install -r requirements.txt

   # Or with standard venv
   python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
   ```

2. Copy the example environment file and fill in your values:

   ```bash
   cp .env.example .env
   ```

   Required keys:
   - `FIRECRAWL_API_KEY` — article extraction.
   - `OPENAI_API_KEY` — LLM evaluation and summarization.
   - `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` — email sending.

3. Set up your recipient list and review config:

   ```bash
   cp config/recipients.example.yaml config/recipients.yaml   # then edit recipients
   ```

   Review `config/daily_ap.yaml` (sources, story limits, thresholds). See
   [Configuring behavior](#configuring-behavior) below for the common tuning knobs.

> **Paths are relative.** All paths come from `--config` and the cwd-relative
> `output_dir`, so the only environment-specific step is creating the venv. The
> cron scripts auto-detect the repo root. If you run the Hermes skill from a
> clone that isn't at `~/briefing-bot`, set `BRIEFING_BOT_HOME=/path/to/repo`.

## Running

The pipeline can run locally (on-demand or cron), or as a Hermes skill (on-demand or scheduled).

### Common invocations

With uv, prefix commands with `uv run` (shown below). With conda/venv, activate the environment and drop the prefix.

```bash
# Full pipeline and send the email
uv run scripts/run_daily_briefing.py --config config/daily_ap.yaml --phase full --send

# Dry run — no LLM calls, no email, placeholder data (good for a smoke test)
uv run scripts/run_daily_briefing.py --config config/daily_ap.yaml --dry-run

# Full pipeline, no email
uv run scripts/run_daily_briefing.py --config config/daily_ap.yaml --phase full

# Single phase: discover | extract | evaluate | summarize | render | send | full
uv run scripts/run_daily_briefing.py --config config/daily_ap.yaml --phase extract
```

Each run writes its outputs and a `run_log.json` to `outputs/<today>/`. Individual phases load the prior phase's JSON from that directory, so you can re-run a single phase after a full run.

#### Conserving Firecrawl credits during development

Firecrawl is billed per extraction. Two ways to keep development cheap:

- **`--dry-run`** — makes **zero** real API calls and uses mock article content. Best for testing the pipeline plumbing end-to-end.
- **`--max-extractions N`** — runs the **real** pipeline but caps Firecrawl to at most `N` extraction calls (and disables retries so the bound is hard). Use when you need to see real extraction output cheaply:

  ```bash
  uv run scripts/run_daily_briefing.py --config config/daily_ap.yaml --phase full --max-extractions 2
  ```

  You can also set it once for your shell so every run is capped:

  ```bash
  export NEWSBOT_MAX_EXTRACTIONS=2   # the --max-extractions flag overrides this
  ```

### Pattern A: Local on-demand

Just run the commands above in your shell with the virtual environment activated.

### Pattern B: Local cron

The repo includes a cron wrapper at `run_daily_briefing_cron.sh` with locking (prevents overlapping runs) and logging to `logs/cron.log`. Install it:

```bash
./install_daily_briefing_cron.sh
```

> **Note:** Both scripts auto-detect the repo root, and the wrapper defaults its Python to the uv venv at `.venv/bin/python` (so run `uv sync` first). Override the interpreter by exporting `PYTHON` before running the wrapper. The default schedule is 6 AM daily; change `CRON_SCHEDULE` in `install_daily_briefing_cron.sh` or edit crontab after install.

The wrapper calls the pipeline with `--phase full --send`. You can test it manually:

```bash
./run_daily_briefing_cron.sh
```

> **macOS sleep caveat:** A user crontab runs even when no one is logged into the GUI — login is *not* required. But macOS does **not** run cron jobs that were missed while the machine was asleep. If your Mac is asleep at 6 AM, the job simply won't fire. To make it reliable, either schedule a wake shortly before the run:
>
> ```bash
> sudo pmset repeat wakeorpoweron MTWRFSU 05:58:00
> ```
>
> or use a LaunchDaemon with `StartCalendarInterval` (which can wake the machine). Also note cron runs with a minimal environment, and modern macOS may require granting `cron` Full Disk Access (System Settings → Privacy & Security).

### Pattern C: Hermes skill (on-demand)

A Hermes skill is included at `.hermes/skills/news-briefing/`. It calls the same pipeline with `--phase full --send`.

1. Copy or symlink the skill to your Hermes profile:

   ```bash
   # For default profile
   mkdir -p ~/.hermes/profiles/default/skills
   cp -r .hermes/skills/news-briefing ~/.hermes/profiles/default/skills/
   ```

2. Reload Hermes skills (or restart Hermes).

3. Invoke naturally:

   > "email me a US & world news briefing"

### Pattern D: Hermes cron (scheduled)

Create a Hermes cron job that uses the skill:

```bash
hermes cronjob create \
  --name daily-briefing \
  --schedule "0 6 * * *" \
  --prompt "Run news briefing pipeline" \
  --skills "news-briefing" \
  --toolsets '["terminal"]'
```

This runs daily at 6 AM using the same skill entry point as Pattern C.

## Configuring behavior

Most behavior is controlled by `config/daily_ap.yaml`. The most useful knobs:

| Goal | Setting (in `config/daily_ap.yaml`) | Default |
|------|-------------------------------------|---------|
| Stricter / looser story selection | `llm.relevance_threshold` (higher = stricter) | `0.70` |
| Total stories in the briefing | `briefing.max_total_stories` | `10` |
| Stories per section | `sources.apnews.sections.<section>.max_stories` | `5` |
| How many candidate URLs to consider per section | `extraction.max_candidate_urls_per_section` | `12` |
| Recency window (drop older articles) | `sources.apnews.reject_if_older_than_hours` | `36` |
| Allowed sites (domain allowlist) | `sources.apnews.allowed_domains` | `apnews.com` |
| Add / remove topics | add a key under `sources.apnews.sections` with `section_urls` + `topic_description` | `us`, `world` |
| LLM models | `llm.model` / `llm.fallback_model` (OpenAI only) | `gpt-5-nano` |

**Ignoring / forbidding specific URLs.** Domain-level control is config (`allowed_domains`), but the finer denylist of non-article page patterns (hubs, `/video/`, `/gallery/`, `/tag/`, etc.) is the `REJECT_PATTERNS` list near the top of `scripts/discover_articles.py`. To block more page types (e.g. opinion pages), add a regex such as `r"/opinion/"` to that list. There is no per-URL blocklist in the config today.

## Tuning the briefing (prompts)

The tone, priorities, and structure of the output are driven by the prompt templates in `prompts/`. Edit these to change *how* the LLM behaves (no code changes needed):

- **`prompts/relevance_evaluator.md`** — selection criteria and topic priorities: what counts as important, what to reject, and how to dedupe. Adjust here to shift which stories get picked.
- **`prompts/article_summarizer.md`** — per-article output: summary length (currently "2-4 sentence"), tone, the "why it matters" line, and key entities.
- **`prompts/briefing_synthesizer.md`** — the overall structure and tone of the assembled briefing.

## Development

The project uses [uv](https://docs.astral.sh/uv/) for dependency management and ships with linting, type checking, and tests. Data models are validated with [Pydantic](https://docs.pydantic.dev/) (the four pipeline stages) and config is validated on load, so a malformed `daily_ap.yaml` fails fast with a clear error.

```bash
uv sync --dev                                       # install dependencies (including dev tools)
uv run ruff check scripts/ tests/                   # lint
uv run mypy scripts/                                # type check
uv run pytest                                       # run the test suite (excludes live tests)
uv run pytest --cov=scripts --cov-report=html       # run with coverage report
```

Tests live under `tests/` (`unit/`, `integration/`, `e2e/`) and mock all external calls (Firecrawl, OpenAI, SMTP), so the suite is fast, free, and deterministic. One opt-in smoke test hits the real Firecrawl API:

```bash
RUN_LIVE_TESTS=1 uv run pytest -m live
```

CI runs lint, type check, and tests on every push and pull request (see `.github/workflows/ci.yml`).

## Maintenance

- **Outputs & retention** — `config/retention.yaml` defines how long to keep briefings (5 days), raw extracts (2 days), and logs (14 days). Use `scripts/cleanup_outputs.py` to prune old run directories.
- **Logs** — check `logs/cron.log` for scheduled-run status and `outputs/<date>/run_log.json` for per-phase results and errors.
- **Recipients** — edit `config/recipients.yaml`.
- **Sources & tuning** — edit `config/daily_ap.yaml` to change sections, per-section story limits, relevance threshold, and extraction settings.
- **LLM model** — set `llm.model` and `llm.fallback_model` in `config/daily_ap.yaml` (OpenAI models only).
- **Prompts** — adjust LLM behavior by editing the templates in `prompts/`.
- **Failure alerts** — a plain-text alert email is sent to the recipients in `config/recipients.yaml` (same SMTP settings as the briefing) in three cases: the run crashes with an unhandled error, it completes but produces no articles, or the briefing email itself fails to send.

## Disclaimer

This is a personal project for fetching and summarizing publicly available information for individual use. Respect the terms, rate limits, and copyright of your sources. Do not use this to redistribute source content publicly. Summaries are LLM-generated and may contain errors; verify against the linked source before relying on them.

## License

[MIT](LICENSE) © 2026 Cyrus Anderson
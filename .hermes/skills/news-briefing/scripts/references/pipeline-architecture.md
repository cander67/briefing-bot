# Pipeline Architecture Reference

## Phase Flow

1. **Discover** — `discover_articles.py`
   - Fetch AP News section pages (us-news, world-news)
   - Extract all links, filter to article URLs only
   - Strict reject patterns for hub/section/tag/video pages
   - Output: `candidate_articles.json`

2. **Extract** — `extract_articles.py`
   - Firecrawl v2 API with `formats=["summary", "markdown"]`
   - Summary format bypasses AP paywall
   - 0.5s delay between requests
   - Output: `extracted_articles.json`

3. **Filter** — `run_daily_briefing.py::apply_deterministic_filters()`
   - Domain allowlist (apnews.com)
   - Recency window (36 hours default)
   - Min content length (500 chars)
   - URL dedupe (first occurrence wins)
   - Non-article page rejection
   - Output: `filtered_articles.json`

4. **Evaluate** — `evaluate_articles.py::LLMEvaluator`
   - OpenAI gpt-5-nano primary, gpt-4.1-nano fallback
   - Temperature=0 for deterministic JSON
   - Respects per-section max_stories
   - Output: `evaluated_articles.json`

5. **Summarize** — `summarize_articles.py::LLMSummarizer`
   - Same model config as evaluator
   - Structured JSON output with headline, summary, why_it_matters, key_entities
   - Output: `summarized_articles.json`

6. **Render** — `render_briefing.py`
   - Groups by section (us, world)
   - Produces `briefing.md` (markdown) and `email_body.txt` (plain text)

7. **Send** — `send_briefing_email.py`
   - SMTP with STARTTLS
   - Plain text + HTML (markdown converted)
   - Fixed recipient list from `config/recipients.yaml`

## Progress Tracking & Idempotency

- **Idempotency guard**: Before running full pipeline, checks `outputs/{date}/briefing.md`. If exists, exits 0 unless `--force` flag passed. Prevents duplicate Firecrawl/OpenAI credit consumption.
- **Progress file**: Writes `outputs/{date}/progress.json` after each phase with current phase name, timestamps, and phase-specific metrics (candidate_count, successful extractions, filtered count, selected count, etc.). Can be polled via skill entrypoint `--status`.
- **Background execution**: Skill entrypoint supports `--background` flag to spawn pipeline as detached process, returning PID immediately. Check status with `--status` or poll `progress.json`.

## Key Technical Decisions

- **Firecrawl summary format**: Bypasses AP paywall; markdown returned but contains login page
- **Timezone handling**: Published dates parsed as naive UTC; filter cutoff is UTC-aware
- **Candidate ID format**: `{section}_{index:03d}` for LLM mapping
- **Dedupe strategy**: First occurrence of URL wins (us section scraped before world)
- **Model fallback**: gpt-5-nano → gpt-4.1-nano (both support JSON mode)
- **Temperature=0**: For evaluator; 0.2 for summarizer (slight creativity)

## Running in Different Contexts

| Context | Working Dir | Python | Notes |
|---------|-------------|--------|-------|
| Local | `~/hermes-newsbot` | conda env | Full deps installed |
| Skill entry point | `~/hermes-newsbot` | `sys.executable` | Calls local script via subprocess |
| Docker | `/workspace` | container python | Mounts config/ scripts/ ro, outputs/ rw |
| Hermes cron | Inherited | Agent's python | Skill must resolve absolute paths |
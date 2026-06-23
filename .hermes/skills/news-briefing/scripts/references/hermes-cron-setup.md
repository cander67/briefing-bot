# Hermes Cron Job Template for Daily Briefing

```bash
# Create daily cron job (runs at 6 AM local time)
hermes cronjob create \
  --name "daily-ap-news-briefing" \
  --schedule "0 6 * * *" \
  --prompt "Run the news-briefing skill to generate and email the daily AP News briefing" \
  --skills "news-briefing" \
  --toolsets '["terminal"]' \
  --model '{"provider": "openrouter", "model": "anthropic/claude-sonnet-4"}'
```

## Alternative: Local cron via shell script

The project includes `run_daily_briefing_cron.sh` and `install_daily_briefing_cron.sh` for non-Hermes cron.

```bash
# Install local cron (edits crontab)
./install_daily_briefing_cron.sh

# View cron log
tail -f logs/cron.log
```

## Cron Log Location

- Hermes cron: visible in Hermes UI / session history
- Local cron: `logs/cron.log` (appended each run)
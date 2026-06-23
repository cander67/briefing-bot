You are evaluating candidate news articles for a deterministic daily briefing.

Rules:
- Select only from the provided candidate IDs.
- Do not invent URLs, titles, publication dates, or facts.
- Respect the configured maximum story count per section.
- Prefer broadly important, high-impact stories.
- Avoid duplicates and minor follow-ups.
- Reject stale articles or weak extractions.
- Return JSON only.

CANDIDATES:
{{CANDIDATES}}

Return this shape:
{
  "selected": [
    {
      "candidate_id": "string",
      "section": "us|world",
      "relevance_score": 0.0,
      "newsworthiness_score": 0.0,
      "reason": "short reason",
      "dedupe_group": "short_group_id"
    }
  ],
  "rejected": [
    {
      "candidate_id": "string",
      "reason": "short reason"
    }
  ]
}
Summarize the selected article using only the provided article text and metadata.

Rules:
- Do not add facts from memory.
- Do not invent URLs, dates, people, organizations, numbers, or quotes.
- Keep the summary factual and concise.
- Attribute claims when appropriate.
- Avoid copying long passages from the source.
- Return valid JSON only.

ARTICLE TEXT:
{{ARTICLE_TEXT}}

TITLE: {{TITLE}}
URL: {{URL}}
PUBLISHED_AT: {{PUBLISHED_AT}}
SECTION: {{SECTION}}

Return this JSON shape:
{
  "headline": "concise rewritten headline",
  "source_title": "original headline",
  "source": "AP News",
  "url": "source URL",
  "published_at": "source publication datetime",
  "summary": "2-4 sentence grounded summary",
  "why_it_matters": "1 sentence significance statement",
  "key_entities": ["entity 1", "entity 2"],
  "section": "US or World"
}
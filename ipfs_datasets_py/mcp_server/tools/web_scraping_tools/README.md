# Web Scraping Tools

MCP tool for unified web scraping with automatic strategy fallback.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `unified_scraper_tool.py` | `scrape_url()`, `scrape_urls()`, `extract_structured_data()` | Scrape web pages with automatic fallback: `requests` → `playwright` → `selenium` |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.web_scraping_tools import (
    scrape_url, scrape_urls, extract_structured_data
)

# Scrape a single URL
result = await scrape_url(
    url="https://example.com/page",
    strategy="auto",           # "auto" | "requests" | "playwright" | "selenium"
    extract=["title", "text", "links", "metadata"],
    timeout=30
)
# Returns: {"url": "...", "title": "...", "text": "...", "links": [...]}

# Batch scrape
results = await scrape_urls(
    urls=["https://a.com", "https://b.com"],
    max_concurrent=5,
    respect_robots_txt=True
)

# Extract structured data (with CSS selectors or XPath)
data = await extract_structured_data(
    url="https://news.example.com",
    schema={
        "articles": {
            "selector": "article.post",
            "fields": {
                "title": "h2.title",
                "date": "time[datetime]",
                "body": "div.content"
            }
        }
    }
)
```

## Dependencies

- `requests` — simple HTTP scraping (always available)
- `beautifulsoup4` — HTML parsing
- `playwright` — JavaScript-rendered pages (optional)
- `selenium` — fallback JavaScript rendering (optional)

## Notes

For web archive/search operations, see [`web_archive_tools/`](../web_archive_tools/).

## Status

| Tool | Status |
|------|--------|
| `unified_scraper_tool` | ✅ Production ready |

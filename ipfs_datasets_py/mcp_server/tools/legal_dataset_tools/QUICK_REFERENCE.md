# Unified Legal Scraper - Quick Reference

## 30-Second Overview

Unified scraping system with:
- Content addressing (IPFS CIDs)
- Multi-source fallback (Common Crawl, Wayback, live)
- 3 interfaces (package, CLI, MCP)
- Parallel scraping
- WARC export

## Installation

```bash
pip install -e .
pip install playwright beautifulsoup4 warcio aiohttp
```

## Usage

### As Package

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_legal_url

result = await scrape_legal_url("https://library.municode.com/wa/seattle")
print(f"CID: {result['cid']}, Source: {result['source']}")
```

### As CLI

```bash
# Scrape single URL
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli \
    scrape https://library.municode.com/wa/seattle

# Scrape bulk
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli \
    scrape-bulk urls.txt --max-concurrent 10

# Search Common Crawl
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli \
    search-cc "https://library.municode.com/*"

# Check cache
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli \
    check-cache https://library.municode.com/wa/seattle

# Migrate scraper
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli \
    migrate state_scrapers/california.py
```

### As MCP Tool

```json
{
  "tool": "scrape_legal_url",
  "arguments": {
    "url": "https://library.municode.com/wa/seattle",
    "prefer_archived": true
  }
}
```

## Migration

### Quick Migration

```python
# 1. Add mixin
from .scraper_adapter import StateScraperMixin

class MyScraper(BaseStateScraper, StateScraperMixin):
    
    # 2. Convert to async
    async def scrape(self):
        
        # 3. Use unified methods
        soup = await self.get_soup(url)  # Instead of requests.get()
```

### Pattern Replacements

```python
# OLD → NEW

requests.get(url).text
→ await self.get_html(url)

BeautifulSoup(requests.get(url).text, 'html.parser')
→ await self.get_soup(url)

requests.get(url).json()
→ await self.get_json(url)

# Sequential → Parallel
for url in urls: scrape(url)
→ await self.scrape_urls_parallel(urls, max_concurrent=10)
```

## Common Crawl

Search multiple indexes:
```bash
curl "https://index.commoncrawl.org/CC-MAIN-2025-47-index?url=https://library.municode.com/*&output=json"
```

## Files

- `unified_legal_scraper.py` - Main scraper
- `scraper_adapter.py` - Compatibility layer
- `mcp_tools.py` - MCP server tools
- `legal_scraper_cli.py` - CLI interface
- `test_unified_scraper.py` - Tests

## Documentation

- `UNIFIED_SCRAPER_README.md` - Full guide
- `MIGRATION_GUIDE.md` - Migration instructions
- `LEGAL_SCRAPER_COMPLETE.md` - Implementation summary
- `california_unified.py` - Example migration

## MCP Tools (6)

1. `scrape_legal_url` - Single URL
2. `scrape_legal_urls_bulk` - Multiple URLs
3. `search_common_crawl` - Search CC
4. `check_url_cached` - Check cache
5. `export_to_warc` - Export WARC
6. `migrate_scraper_file` - Analyze migration

## CLI Commands (5)

1. `scrape <url>` - Scrape single URL
2. `scrape-bulk <file>` - Scrape from file
3. `search-cc <url>` - Search Common Crawl
4. `check-cache <url>` - Check cache
5. `migrate <file>` - Analyze migration

## Performance

| Scenario | Time |
|----------|------|
| First scrape | 2-5s |
| Cached scrape | <0.1s |
| 100 URLs (parallel) | 30-60s |
| 100 URLs (cached) | <10s |

## Testing

```bash
pytest ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/test_unified_scraper.py -v
```

## Location

```
/home/devel/ipfs_datasets_py/
└── ipfs_datasets_py/
    └── mcp_server/
        └── tools/
            └── legal_dataset_tools/
                ├── unified_legal_scraper.py
                ├── scraper_adapter.py
                ├── mcp_tools.py
                ├── legal_scraper_cli.py
                └── test_unified_scraper.py
```

## Help

```bash
# CLI help
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli --help

# Command help
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli scrape --help
```

## Example Session

```bash
# 1. Scrape URL
$ python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli \
    scrape https://library.municode.com/wa/seattle

✓ Successfully scraped https://library.municode.com/wa/seattle
  CID: QmXxx...
  Source: common_crawl:CC-MAIN-2025-47
  Size: 45123 bytes

# 2. Check cache (instant)
$ python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli \
    check-cache https://library.municode.com/wa/seattle

✓ URL is cached with 1 version(s)

Version 1:
  CID: QmXxx...
  Timestamp: 2025-12-19T19:00:00
  Source: common_crawl:CC-MAIN-2025-47
  Size: 45123 bytes

Latest CID: QmXxx...

# 3. Search Common Crawl
$ python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_scraper_cli \
    search-cc "https://library.municode.com/*"

✓ Found 152 entries

CC-MAIN-2025-47: 45 entries
CC-MAIN-2025-46: 38 entries
CC-MAIN-2025-45: 35 entries
...
```

## Troubleshooting

**IPFS multiformats not found:**
```bash
pip install ipfs-multiformats-py
```

**WARC export fails:**
```bash
pip install warcio
```

**Import errors:**
```bash
cd /home/devel/ipfs_datasets_py
pip install -e .
```

## Next Steps

1. Test with real URLs
2. Migrate pilot scrapers
3. Monitor performance
4. Roll out to all scrapers

## Quick Links

- Main README: `UNIFIED_SCRAPER_README.md`
- Migration Guide: `MIGRATION_GUIDE.md`
- Example: `california_unified.py`
- Tests: `test_unified_scraper.py`

# Unified Legal Scraper - Quick Start

## Summary

✅ **All legal scrapers migrated** from MCP tools to unified package
✅ **Multi-interface access**: Package imports, CLI, and MCP server
✅ **Content addressing**: IPFS CIDs for deduplication
✅ **7-level fallback chain**: Common Crawl → Wayback → IPWB → Archive.is → Playwright → Live
✅ **Parallel processing**: Async and multiprocessing support
✅ **50+ scrapers**: All US states, municipal codes, federal sources

## Basic Usage

```python
import asyncio
from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedLegalScraper

async def main():
    scraper = UnifiedLegalScraper()
    result = await scraper.scrape_url("https://library.municode.com/wa/seattle")
    print(f"Success: {result['success']}, CID: {result.get('cid')}")

asyncio.run(main())
```

## CLI Usage

```bash
# Scrape single URL
python -m ipfs_datasets_py.legal_scrapers.cli.legal_scraper_cli scrape "https://library.municode.com/wa/seattle"

# Scrape bulk with multiprocessing
python -m ipfs_datasets_py.legal_scrapers.cli.legal_scraper_cli scrape-bulk urls.txt --max-workers 20 --use-multiprocessing
```

## Documentation

- `LEGAL_SCRAPERS_UNIFIED_MIGRATION_COMPLETE.md` - Full migration details
- `test_unified_legal_scraper_migration.py` - Test suite
- `ipfs_datasets_py/legal_scrapers/` - Source code

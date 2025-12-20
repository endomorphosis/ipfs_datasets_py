# DEPRECATION NOTICE

## Status: This directory contains legacy code

The scrapers in this directory have been **migrated** to the main package:

```
ipfs_datasets_py/legal_scrapers/
```

## New Structure

All legal scraping functionality is now accessible via:

1. **Package Imports**:
   ```python
   from ipfs_datasets_py.legal_scrapers import (
       get_state_scraper,
       get_municipal_scraper,
       get_federal_scraper,
       get_court_scraper
   )
   ```

2. **CLI Tools**:
   ```bash
   ipfs-datasets scrape legal --url https://example.com
   ipfs-datasets scrape municode --jurisdiction seattle
   ipfs-datasets scrape us-code --title 18
   ipfs-datasets search courts --citation "410 U.S. 113"
   ```

3. **MCP Server Tools**:
   - Tools in `mcp_tools.py` now delegate to package imports
   - All MCP tools continue to work seamlessly
   - No breaking changes to MCP interface

## Migration Path

### Files Migrated:

- `federal_register_scraper.py` → `ipfs_datasets_py/legal_scrapers/scrapers/federal_register_scraper.py`
- `us_code_scraper.py` → `ipfs_datasets_py/legal_scrapers/scrapers/us_code_scraper.py`
- `recap_archive_scraper.py` → `ipfs_datasets_py/legal_scrapers/scrapers/recap_archive_scraper.py`
- `state_laws_scraper.py` → `ipfs_datasets_py/legal_scrapers/scrapers/state_scrapers/`
- `municipal_laws_scraper.py` → `ipfs_datasets_py/legal_scrapers/scrapers/municipal_scrapers/`

### New Additions:

- `courtlistener_scraper.py` - CourtListener API with fallback to direct court websites
- Unified scraper with automatic fallback chain:
  1. Check if already scraped (content-addressed cache)
  2. Search Common Crawl (multiple indexes)
  3. Try Interplanetary Wayback Machine
  4. Try Internet Archive Wayback Machine
  5. Try Archive.is
  6. Try IPWB (InterPlanetary Wayback)
  7. Fallback to Playwright for JS-heavy sites
  8. Fallback to live scraping

## What to Do

### If you're using scrapers from this directory:

**Old way** (deprecated):
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.us_code_scraper import search_us_code
```

**New way**:
```python
from ipfs_datasets_py.legal_scrapers.scrapers import get_federal_scraper

us_code_scraper = get_federal_scraper("us_code")
```

### If you're using MCP tools:

**No changes needed!** MCP tools continue to work as before, but now they delegate to the consolidated package.

## Timeline

- **Now**: Both old and new locations work (transitional period)
- **Future**: Old location files will be removed after full migration verification

## Questions?

See:
- `ipfs_datasets_py/legal_scrapers/README.md` - Main documentation
- `ipfs_datasets_py/legal_scrapers/docs/COURTLISTENER_API_GUIDE.md` - CourtListener docs
- `LEGAL_SCRAPERS_QUICK_START.md` - Quick start guide

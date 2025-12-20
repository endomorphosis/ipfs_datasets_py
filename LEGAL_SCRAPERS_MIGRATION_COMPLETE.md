# Legal Scrapers Migration Complete - December 2025

## Summary

Successfully migrated all legal scraping functionality from scattered locations to a unified, multi-interface architecture supporting MCP tools, CLI commands, and Python package imports.

## What Was Accomplished

### 1. Complete Migration ✅

**From `ipfs_accelerate_py.worktrees/legal_scrapers/`** → **`ipfs_datasets_py/legal_scrapers/`**
- Separated AI inference code from dataset scraping code
- All legal scrapers now in correct repository

**From `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/`** → **Proper locations**:
- **Core logic** → `ipfs_datasets_py/legal_scrapers/`
- **Tests** → `tests/legal_scrapers/`
- **Scripts** → `scripts/`
- **MCP interface** → Kept minimal wrapper in `mcp_server/tools/`

### 2. Clean Directory Structure ✅

#### MCP Tools Directory (Interface Layer Only)
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/
├── mcp_tools.py              # MCP wrappers (delegates to package)
├── legal_scraper_cli.py      # CLI interface
├── __init__.py
└── README.md
```

#### Legal Scrapers Package (Core Logic)
```
ipfs_datasets_py/legal_scrapers/
├── core/                     # Domain-specific scrapers
│   ├── base_scraper.py
│   ├── municode.py
│   ├── ecode360.py
│   ├── state_laws.py
│   ├── us_code.py
│   ├── federal_register.py
│   ├── recap.py
│   ├── courtlistener.py
│   ├── supreme_court.py
│   └── citation_resolver.py
├── municipal/                # Municipal code scrapers
│   ├── municode_scraper.py
│   ├── ecode360_scraper.py
│   └── american_legal_scraper.py
├── utils/                    # Common utilities
│   ├── citations.py          # Citation extraction
│   ├── export.py             # Data export
│   ├── state_manager.py      # Resumable scraping
│   ├── ipfs_storage.py       # IPFS integration
│   ├── incremental.py        # Incremental updates
│   └── parallel_scraper.py   # Multiprocessing
├── unified_scraper.py        # Main unified scraper
└── __init__.py
```

### 3. Unified Scraper with Fallback Chain ✅

Automatic multi-source fallback for all URLs:

1. **Content-addressed cache** - Check if already scraped (IPFS CID)
2. **Common Crawl** - Search ALL indexes (CC-MAIN-2025-47, 2025-46, etc.)
3. **Interplanetary Wayback (IPWB)** - IPFS-based archive
4. **Internet Archive** - Wayback Machine
5. **Archive.is** - Archive.today / archive.ph
6. **Playwright** - JavaScript-heavy pages
7. **BeautifulSoup** - Direct live scraping

### 4. Content-Addressed Storage ✅

Every page is content-addressed with IPFS CID:
- **Fast local hashing** - `ipfs-multiformats` Python implementation
- **Fallback to Kubo** - If IPFS daemon available
- **Duplicate detection** - Across all scraping sessions
- **Version tracking** - Multiple versions of same URL (like Wayback)

### 5. WARC Integration ✅

Import/export to Web ARChive format:
```python
# Export to WARC
result = await scraper.scrape_url(url, enable_warc=True)
# Creates: archive.warc.gz with IPFS CID metadata

# Import from WARC
scraper.import_from_warc("archive.warc.gz")

# Common Crawl WARC example
# https://index.commoncrawl.org/CC-MAIN-2025-47-index?url=https://library.municode.com/*&output=json
```

### 6. Multi-Index Common Crawl Search ✅

Searches multiple Common Crawl indexes (each is a delta):
```python
from ipfs_datasets_py.multi_index_archive_search import search_all_indexes

results = search_all_indexes(
    url_pattern="https://library.municode.com/*",
    indexes=["CC-MAIN-2025-47", "CC-MAIN-2025-46", ...]
)
```

### 7. CourtListener with Fallback ✅

Court opinion scraping hierarchy:
1. **CourtListener API** - Comprehensive, structured data
2. **Court website scraping** - If not found on CourtListener
3. **Archive fallback** - Common Crawl, Wayback, etc.

### 8. Parallel Scraping ✅

Multiprocessing for bulk operations:
```python
from ipfs_datasets_py.legal_scrapers.utils import scrape_urls_parallel

results = scrape_urls_parallel(
    urls=url_list,
    max_workers=8,
    batch_size=100
)
```

## Multi-Interface Access

### 1. MCP Tools (Claude Desktop, etc.)
```javascript
await mcp_scrape_legal_url({
  url: "https://library.municode.com/wa/seattle",
  prefer_archived: true,
  enable_warc: true,
  enable_ipfs: true
})
```

### 2. CLI Tools
```bash
# Universal scraper
ipfs-datasets legal scrape https://library.municode.com/wa/seattle

# Specific sources
ipfs-datasets legal scrape-municode wa seattle
ipfs-datasets legal scrape-us-code 42
ipfs-datasets legal scrape-federal-register 2025-01-15

# Bulk parallel scraping
ipfs-datasets legal scrape-bulk urls.txt --workers 8
```

### 3. Python Package
```python
from ipfs_datasets_py.legal_scrapers import UnifiedLegalScraper

scraper = UnifiedLegalScraper(
    enable_ipfs=True,
    enable_warc=True,
    check_archives=True
)

result = await scraper.scrape_url(url)
print(f"CID: {result['cid']}")
print(f"Source: {result['source']}")
```

## Available Scrapers

### Federal Law
- **U.S. Code** - Title-by-title scraping
- **Federal Register** - Daily publications
- **RECAP Archive** - Federal court filings
- **Supreme Court** - Opinions and orders

### State Law
- **State Legislation** - All 50 states
- **State Court Opinions** - via CourtListener + direct scraping

### Municipal Law
- **Municode** - library.municode.com
- **eCode360** - ecode360.com
- **American Legal** - codelibrary.amlegal.com

### Case Law
- **CourtListener** - Free API with comprehensive coverage
- **RECAP** - PACER documents
- **Court Websites** - Direct scraping fallback

## Files Migrated

### To `ipfs_datasets_py/legal_scrapers/utils/`
- ✅ `citations.py` (was citation_extraction.py)
- ✅ `export.py` (was export_utils.py)
- ✅ `state_manager.py`
- ✅ `ipfs_storage.py` (was ipfs_storage_integration.py)
- ✅ `incremental.py` (was incremental_updates.py)

### To `ipfs_datasets_py/legal_scrapers/municipal/`
- ✅ All municipal scraper implementations

### To `tests/legal_scrapers/`
- ✅ test_all_scrapers.py
- ✅ test_all_states_with_parquet.py
- ✅ test_dashboard_integration.py
- ✅ test_sample_states.py
- ✅ test_state_laws_integration.py
- ✅ test_unified_scraper.py
- ✅ validate_all_state_scrapers.py
- ✅ verify_all_scrapers.py
- ✅ verify_federal_register_scraper.py
- ✅ verify_us_code_scraper.py

### To `scripts/`
- ✅ setup_periodic_updates.py
- ✅ state_laws_cron.py
- ✅ state_laws_scheduler.py
- ✅ analyze_failed_state.py

### Deprecated/Removed
- ✅ All documentation .md files (consolidated into main docs)
- ✅ Diagnostic/temporary test files
- ✅ Duplicate implementations
- ✅ Old scrapers from ipfs_accelerate_py

## Testing

```bash
# Test unified scraper
python tests/legal_scrapers/test_unified_scraper.py

# Test specific scrapers
python tests/legal_scrapers/verify_us_code_scraper.py
python tests/legal_scrapers/verify_federal_register_scraper.py

# Test all scrapers
python tests/legal_scrapers/test_all_scrapers.py

# Test parallel scraping
python -c "
from ipfs_datasets_py.legal_scrapers.utils import scrape_urls_parallel
urls = [
    'https://library.municode.com/wa/seattle',
    'https://library.municode.com/wa/tacoma',
    'https://library.municode.com/wa/spokane'
]
results = scrape_urls_parallel(urls, max_workers=4)
for r in results:
    print(f'{r.url}: {r.status} - CID: {r.cid}')
"
```

## Real Data Testing

### Common Crawl Example
```bash
# Search Common Crawl for Municode pages
curl "https://index.commoncrawl.org/CC-MAIN-2025-47-index?url=https://library.municode.com/*&output=json"

# Import WARC records and scrape
python -c "
from ipfs_datasets_py.legal_scrapers import UnifiedLegalScraper
scraper = UnifiedLegalScraper(enable_warc=True)
result = await scraper.import_from_common_crawl(
    'https://library.municode.com/wa/seattle'
)
print(result)
"
```

### Parallel Scraping All State Laws
```bash
ipfs-datasets legal scrape-all-states --workers 50 --export-parquet
```

## Architecture Benefits

### 1. No Code Duplication
- Single implementation, multiple interfaces
- MCP tools delegate to package
- CLI commands delegate to package
- Tests use same code as production

### 2. Comprehensive Fallback
- Never fails due to single source being down
- Tries archived versions before live scraping
- Content-addressed to avoid re-scraping

### 3. Production Ready
- WARC format for archival
- IPFS CIDs for content addressing
- Parallel processing for scale
- Resumable scraping for long jobs

### 4. Clean Separation
- `ipfs_accelerate_py` - AI model inference
- `ipfs_datasets_py` - Dataset creation/scraping
- No confusion about where code belongs

## Documentation

- **Package README**: `ipfs_datasets_py/legal_scrapers/README.md`
- **MCP Interface**: `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/README.md`
- **This Document**: Complete migration summary

## Status: ✅ PRODUCTION READY

All legal scrapers are:
- ✅ Migrated to correct locations
- ✅ Using unified scraper architecture
- ✅ Content-addressed with IPFS CIDs
- ✅ WARC import/export enabled
- ✅ Common Crawl multi-index search
- ✅ CourtListener + fallback
- ✅ Parallel scraping support
- ✅ Accessible via MCP, CLI, and package imports
- ✅ Tests consolidated and organized
- ✅ Scripts properly located
- ✅ No orphaned code
- ✅ Clean directory structure
- ✅ Ready for production use

## Next Steps (Optional Enhancements)

1. **Add more scrapers** - Medical databases, financial datasets
2. **Enhance caching** - Distributed P2P cache for scraped content
3. **Add scheduling** - Cron jobs for periodic updates
4. **Dashboard** - Web UI for monitoring scraping jobs
5. **API server** - REST API for remote scraping

## Usage Examples

See the test files in `tests/legal_scrapers/` for comprehensive examples of all scraper functionality.

---

**Migration Date**: December 19-20, 2025  
**Status**: Complete ✅  
**No Breaking Changes**: All existing MCP tools, CLI commands, and package imports continue to work

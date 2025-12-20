# Unified Scraper Architecture - Quick Start

## Overview

This directory contains the refactored unified scraper architecture. All web scraping in `ipfs_datasets_py` should use these modules instead of implementing custom BeautifulSoup/Playwright/requests logic.

## Directory Structure

```
ipfs_datasets_py/
├── scrapers/                     # Core scraping infrastructure
│   ├── __init__.py              # Exports UnifiedWebScraper, ContentAddressedScraper
│   ├── legal/                   # Legal data scrapers
│   ├── medical/                 # Medical data scrapers
│   └── financial/               # Financial data scrapers
└── integrations/                # External service integrations
    ├── __init__.py
    ├── common_crawl.py          # ✅ Multi-index Common Crawl searches
    └── ipfs_cid.py              # ✅ IPFS CID computation (multiformats + Kubo)
```

## Quick Usage

### 1. Basic Web Scraping
```python
from ipfs_datasets_py.scrapers import UnifiedWebScraper

scraper = UnifiedWebScraper()
result = scraper.scrape_sync("https://example.com")

if result.success:
    print(f"Title: {result.title}")
    print(f"Content: {result.content}")
    print(f"Method: {result.method_used}")
```

### 2. Content-Addressed Scraping (Check if Already Scraped)
```python
from ipfs_datasets_py.scrapers import ContentAddressedScraper

scraper = ContentAddressedScraper()
result = scraper.scrape_with_deduplication("https://example.com")

if result.already_scraped:
    print(f"Already have this! CID: {result.cid}")
else:
    print(f"New content scraped. CID: {result.cid}")
```

### 3. Search Common Crawl (Multi-Index)
```python
from ipfs_datasets_py.integrations import search_common_crawl

# Search across multiple CC indexes (each is a snapshot/delta)
records = search_common_crawl("https://library.municode.com/*")

for record in records:
    print(f"{record.url} from {record.index} at {record.timestamp}")
```

### 4. Compute IPFS CID
```python
from ipfs_datasets_py.integrations import compute_cid_for_content

# Fast CID computation with multiformats (fallback to Kubo)
cid = compute_cid_for_content(b"Hello, IPFS!")
print(f"CID: {cid}")
```

## Implemented Features ✅

1. **UnifiedWebScraper** - Intelligent fallback scraping
   - Tries: Playwright → BeautifulSoup → Wayback → CC → Archive.is → IPWB
   - Located in: `ipfs_datasets_py/unified_web_scraper.py`

2. **ContentAddressedScraper** - Deduplication via CID
   - Checks if URL already scraped
   - Tracks versions like Wayback Machine
   - Located in: `ipfs_datasets_py/content_addressed_scraper.py`

3. **CommonCrawlClient** - Multi-index searches
   - Search across 10+ Common Crawl indexes
   - Each index is a snapshot/delta
   - Parallel searching for speed
   - Located in: `ipfs_datasets_py/integrations/common_crawl.py`

4. **IPFSCIDComputer** - Fast CID computation
   - Uses ipfs_multiformats library
   - Automatic Kubo fallback
   - Located in: `ipfs_datasets_py/integrations/ipfs_cid.py`

## Pending Features ⬜

1. **WARC Handler** - Import/export WARC files
   - Will be in: `ipfs_datasets_py/integrations/warc_handler.py`

2. **IPWB Client** - InterPlanetary Wayback Machine
   - Will be in: `ipfs_datasets_py/integrations/ipwb_client.py`

3. **Legal Scrapers** - Refactored legal data scrapers
   - Will be in: `ipfs_datasets_py/scrapers/legal/`
   - Currently in: `mcp_server/tools/legal_dataset_tools/` (needs migration)

4. **Multiprocessing Support** - Parallel scraping
   - Will be added to legal scrapers

## Design Principles

### 1. No Duplicate Logic
All scraping uses `UnifiedWebScraper`. No custom BeautifulSoup/Playwright implementations.

### 2. Package-First Architecture
```
Package Import    →    CLI Tool         ✅ CORRECT
      ↑                    
      └────── MCP Tool
```

NOT:
```
MCP Tool → Business Logic    ❌ WRONG
```

### 3. Content Addressing
Use `ContentAddressedScraper` to avoid re-scraping identical content.

### 4. Multi-Source Fallback
Always try multiple sources (Common Crawl, Wayback, etc.) before live scraping.

## Migration Guide

### For Scrapers Using BeautifulSoup

**Before (❌ Wrong):**
```python
import requests
from bs4 import BeautifulSoup

def scrape_something(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    # ... custom parsing ...
```

**After (✅ Correct):**
```python
from ipfs_datasets_py.scrapers import UnifiedWebScraper

def scrape_something(url):
    scraper = UnifiedWebScraper()
    result = scraper.scrape_sync(url)
    # result has .html, .content, .text, .links
    # Use that instead of custom BeautifulSoup
```

### For MCP Tools

**Before (❌ Wrong):**
```python
# mcp_server/tools/some_tool.py
import requests

async def mcp_scrape(url):
    # Business logic here
    response = requests.get(url)
    return parse_response(response)
```

**After (✅ Correct):**
```python
# mcp_server/tools/some_tool.py
from ipfs_datasets_py.scrapers import UnifiedWebScraper

async def mcp_scrape(url):
    # Thin wrapper - just call package
    scraper = UnifiedWebScraper()
    result = scraper.scrape_sync(url)
    return result.to_dict()
```

## Testing

Run tests with:
```bash
pytest test_unified_scraping_architecture.py -v
```

## Documentation

- **Refactoring Plan:** `UNIFIED_SCRAPER_REFACTORING_PLAN.md`
- **Progress Report:** `SCRAPER_REFACTORING_PROGRESS.md`
- **This File:** `ipfs_datasets_py/scrapers/README.md`

## Next Steps

See `SCRAPER_REFACTORING_PROGRESS.md` for detailed next steps. Priority items:

1. Implement WARC handler
2. Implement IPWB client
3. Migrate legal scrapers to `scrapers/legal/`
4. Add multiprocessing support
5. Refactor MCP tools to be thin wrappers
6. Comprehensive testing

## Questions?

Refer to:
- `UNIFIED_SCRAPER_REFACTORING_PLAN.md` - Full architecture plan
- `SCRAPER_REFACTORING_PROGRESS.md` - Current progress and remaining work
- `ipfs_datasets_py/unified_web_scraper.py` - Main scraper implementation
- `ipfs_datasets_py/content_addressed_scraper.py` - Content addressing implementation

---

**Status:** Foundation complete, migration in progress
**Last Updated:** 2025-12-20

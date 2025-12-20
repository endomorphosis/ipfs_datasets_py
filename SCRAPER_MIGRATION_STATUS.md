# Legal Scraper Migration Status Report

**Date:** 2025-12-20  
**Status:** In Progress  
**Goal:** Migrate all legal scrapers to unified scraping architecture with content-addressed storage

## Current Architecture

### ✅ Completed Components

1. **Core Infrastructure** (`ipfs_datasets_py/`)
   - `unified_web_scraper.py` - Unified scraping with fallback mechanisms
   - `content_addressed_scraper.py` - Content addressing & version tracking
   - `legal_scraper_unified_adapter.py` - Adapter for legal scrapers
   - `multi_index_archive_search.py` - Multi-index Common Crawl searches
   - `warc_integration.py` - WARC import/export

2. **Base Legal Scraper** (`ipfs_datasets_py/legal_scrapers/core/`)
   - `base_scraper.py` - Base class with unified scraping support
   - Provides content addressing, WARC support, multi-interface

3. **Legal Scraper Core** (`ipfs_datasets_py/legal_scrapers/core/`)
   - `municode.py`
   - `federal_register.py`
   - `us_code.py`
   - `state_laws.py`
   - `municipal_code.py`
   - `ecode360.py`

4. **MCP/CLI/Utils** (`ipfs_datasets_py/legal_scrapers/`)
   - `mcp/` - MCP server tools
   - `cli/` - CLI tools
   - `utils/parallel_scraper.py` - Multiprocessing support

### ⚠️ Incomplete/Duplicate Code

1. **Worktree Files** (`ipfs_accelerate_py.worktrees/worktree-2025-12-19T22-29-33/`)
   - These files were accidentally created in the AI inference repo
   - Need to be removed or consolidated
   - Contains: `legal_scraper_unified_adapter.py`, `multi_index_archive_search.py`, etc.

2. **MCP Server Tools** (`ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/`)
   - `municipal_law_database_scrapers/municode_scraper.py` - Uses direct BeautifulSoup
   - `municipal_law_database_scrapers/american_legal_scraper.py` - Uses direct BeautifulSoup
   - `municipal_law_database_scrapers/ecode360_scraper.py` - Uses direct BeautifulSoup
   - `state_scrapers/*.py` - Multiple state scrapers using various methods
   - **Issue:** These are NOT using the unified scraping system

3. **State Scrapers** (`ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/state_scrapers/`)
   - 50+ state-specific scrapers
   - Most use direct BeautifulSoup, Playwright, or requests
   - Need migration to BaseLegalScraper

## Migration Plan

### Phase 1: Consolidate & Clean Up ✅ (Partially Done)

- [x] Move unified scraping files from worktree to ipfs_datasets_py
- [x] Create base_scraper.py with unified support
- [ ] Remove duplicate files from ipfs_accelerate_py.worktrees
- [ ] Verify no orphaned code

### Phase 2: Update Scraping Methods

#### A. Update Municipal Database Scrapers

Files to update:
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/municipal_law_database_scrapers/
├── municode_scraper.py (uses aiohttp + BeautifulSoup directly)
├── american_legal_scraper.py (uses requests + BeautifulSoup directly)
└── ecode360_scraper.py (uses requests + BeautifulSoup directly)
```

**Current Pattern:**
```python
async with aiohttp.ClientSession() as session:
    async with session.get(url) as response:
        html = await response.text()
soup = BeautifulSoup(html, 'html.parser')
```

**Target Pattern:**
```python
from ipfs_datasets_py.legal_scrapers.core.base_scraper import BaseLegalScraper

class MunicodeScraper(BaseLegalScraper):
    def get_scraper_name(self) -> str:
        return "municode"
    
    async def scrape(self, jurisdiction_url, **kwargs):
        result = await self.scrape_url_unified(
            url=jurisdiction_url,
            metadata={"source": "municode"},
            check_archives=self.check_archives  # Check Common Crawl, Wayback, etc.
        )
        return result
```

#### B. Update State Scrapers

Files to update (examples):
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/state_scrapers/
├── california.py
├── delaware.py  
├── florida.py
├── texas.py
└── ... (47 more states)
```

**Current Issues:**
- Direct BeautifulSoup usage
- Manual requests/Playwright calls
- No content addressing
- No version tracking
- No Common Crawl/Wayback fallback

**Migration Steps:**
1. Inherit from `BaseLegalScraper`
2. Replace scraping logic with `self.scrape_url_unified()`
3. Add metadata for content addressing
4. Enable WARC export for archiving

### Phase 3: Add Content Addressing Features

#### A. IPFS Multiformats Integration

**Current Status:**
- `ipfs_multiformats.py` exists
- `content_addressed_scraper.py` uses it with Kubo fallback

**Enhancements Needed:**
- Ensure all scrapers track CIDs
- Store URL → CID mappings
- Track multiple versions per URL
- Deduplicate identical content

#### B. Multi-Index Common Crawl

**Current Status:**
- `multi_index_archive_search.py` exists
- Supports searching multiple CC indexes

**Integration Needed:**
- Use in `unified_web_scraper.py` fallback chain
- Search all CC indexes (not just latest)
- Example: https://index.commoncrawl.org/CC-MAIN-2025-47-index?url=https://library.municode.com/*&output=json

#### C. WARC Import/Export

**Current Status:**
- `warc_integration.py` exists
- Supports importing from Common Crawl WARCs
- Can export scrapes to WARC format

**Integration Needed:**
- Enable WARC export in all legal scrapers
- Import from WARC when available
- Store WARCs in IPFS

### Phase 4: Add Multiprocessing

**Goal:** Scrape laws in parallel for performance

**Files to Create/Update:**
```
ipfs_datasets_py/legal_scrapers/utils/parallel_scraper.py (exists)
```

**Features:**
- Process pool for CPU-bound parsing
- Async pool for I/O-bound scraping
- Progress tracking
- Error handling & retry logic
- Rate limiting per domain

**Example Usage:**
```python
from ipfs_datasets_py.legal_scrapers.utils.parallel_scraper import ParallelLegalScraper

parallel_scraper = ParallelLegalScraper(max_workers=10)
results = await parallel_scraper.scrape_jurisdictions([
    "https://library.municode.com/wa/seattle",
    "https://library.municode.com/ca/san_francisco",
    # ... thousands more
])
```

### Phase 5: Update MCP Server Tools

**Current Issue:** MCP tools contain scraping logic instead of calling package

**Target Architecture:**
```
MCP Tool → ipfs_datasets_py.legal_scrapers.core → unified_web_scraper → content_addressed_scraper
```

**Files to Update:**
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/
├── mcp_tools.py (update to call legal_scrapers package)
├── scraper_adapter.py (ensure uses unified system)
└── unified_legal_scraper.py (update if needed)
```

### Phase 6: Testing & Validation

**Test Files:**
- `test_unified_scraping_architecture.py` (exists, needs completion)
- `ipfs_datasets_py/legal_scrapers/test_legal_scrapers.py`

**Tests Needed:**
1. Content-addressed scraping
   - CID computation (ipfs_multiformats, Kubo fallback)
   - Version tracking
   - Deduplication

2. Multi-index Common Crawl
   - Search multiple indexes
   - WARC retrieval
   - Data extraction

3. Fallback mechanisms
   - Playwright → BeautifulSoup → Wayback → Common Crawl → Archive.is → IPWB
   - Each method tested independently
   - Full fallback chain tested

4. Legal scrapers
   - Municode scraping
   - State law scraping
   - Federal Register scraping
   - US Code scraping

5. Multiprocessing
   - Parallel jurisdiction scraping
   - Progress tracking
   - Error handling

6. MCP/CLI/Package interfaces
   - All three interfaces work identically
   - Same features available in each

## Key Design Principles

1. **Single Source of Truth**: All scraping logic in `ipfs_datasets_py` package
2. **Multi-Interface**: Same functionality via package import, CLI, and MCP
3. **Content Addressing**: Every scraped URL tracked by CID
4. **Version Tracking**: Multiple versions of same URL stored
5. **Fallback Chain**: Automatic fallback through multiple scraping methods
6. **Archive-First**: Check archives before live scraping
7. **WARC Everything**: Export all scrapes to WARC for preservation

## Next Steps

1. **Immediate:** Update municipal database scrapers to use BaseLegalScraper
2. **High Priority:** Migrate state scrapers to unified system
3. **High Priority:** Implement multiprocessing for parallel scraping
4. **Medium Priority:** Complete test suite
5. **Medium Priority:** Clean up worktree files
6. **Low Priority:** Documentation updates

## Files That Need Attention

### High Priority
- `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/municipal_law_database_scrapers/municode_scraper.py`
- `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/state_scrapers/*.py` (50+ files)

### Medium Priority
- `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/mcp_tools.py`
- `test_unified_scraping_architecture.py`
- `ipfs_datasets_py/legal_scrapers/utils/parallel_scraper.py`

### Low Priority (Cleanup)
- `ipfs_accelerate_py.worktrees/worktree-2025-12-19T22-29-33/legal_scraper_unified_adapter.py`
- `ipfs_accelerate_py.worktrees/worktree-2025-12-19T22-29-33/multi_index_archive_search.py`
- Other worktree files

## Success Criteria

✅ All legal scrapers inherit from BaseLegalScraper  
✅ All scrapers use unified_web_scraper for fetching  
✅ All scrapers track content by CID  
✅ All scrapers check archives before live scraping  
✅ All scrapers export to WARC  
✅ Common Crawl searches multiple indexes  
✅ Multiprocessing enables parallel scraping  
✅ Same functionality available via package/CLI/MCP  
✅ Comprehensive test suite passes  
✅ No duplicate scraping code  
✅ No orphaned files in worktree  

## References

- Unified Scraper: `ipfs_datasets_py/unified_web_scraper.py`
- Content Addressing: `ipfs_datasets_py/content_addressed_scraper.py`
- Base Scraper: `ipfs_datasets_py/legal_scrapers/core/base_scraper.py`
- WARC Integration: `ipfs_datasets_py/warc_integration.py`
- Multi-Index CC: `ipfs_datasets_py/multi_index_archive_search.py`

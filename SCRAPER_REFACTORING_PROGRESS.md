# Scraper Architecture Refactoring - Progress Report

**Date:** 2025-12-20
**Status:** In Progress - Phase 1 & 2 Partially Complete

## Summary

We are refactoring the scraper architecture to:
1. Eliminate duplicate scraping logic (BeautifulSoup, Playwright, etc.)
2. Centralize all scraping in a unified module
3. Ensure MCP tools and CLI are thin wrappers calling package imports
4. Add missing integrations (multi-index Common Crawl, IPWB, WARC, etc.)
5. Add multiprocessing for parallel scraping

## Completed Work

### 1. Module Structure Created ✅
```
ipfs_datasets_py/
├── scrapers/                          # NEW - Centralized scraping
│   ├── __init__.py                    # ✅ Created
│   ├── legal/                         # ✅ Created (empty)
│   ├── medical/                       # ✅ Created (empty)
│   └── financial/                     # ✅ Created (empty)
├── integrations/                      # NEW - External service integrations
│   ├── __init__.py                    # ✅ Created
│   ├── common_crawl.py                # ✅ Created - Multi-index CC searches
│   └── ipfs_cid.py                    # ✅ Created - Multiformats + Kubo fallback
```

### 2. Common Crawl Multi-Index Integration ✅
**File:** `ipfs_datasets_py/integrations/common_crawl.py`

**Features:**
- Search across multiple CC indexes (each index is a delta/snapshot)
- Default searches 10 most recent indexes
- Parallel searching for performance
- Deduplication of results
- WARC record fetching
- Both async and sync APIs

**Usage:**
```python
from ipfs_datasets_py.integrations import CommonCrawlClient

client = CommonCrawlClient()
records = client.search_multi_index_sync("https://library.municode.com/*")
for record in records:
    print(f"{record.url} from {record.index}")
```

### 3. IPFS CID Computation Integration ✅
**File:** `ipfs_datasets_py/integrations/ipfs_cid.py`

**Features:**
- Uses ipfs_multiformats for fast CID computation
- Automatic fallback to Kubo if multiformats unavailable
- Support for files and in-memory content
- Multiple codec/hash function support

**Usage:**
```python
from ipfs_datasets_py.integrations import compute_cid_for_content

cid = compute_cid_for_content(b"Hello, IPFS!")
# Returns: "QmZULkCELmmk5XNfCgTnCyFgAVxBRBXyDHGGMVoLFLiXEN"
```

### 4. Documentation Created ✅
- `UNIFIED_SCRAPER_REFACTORING_PLAN.md` - Complete implementation plan
- This progress report

## Remaining Work

### Phase 2: Integration Enhancements (50% Complete)

#### WARC Handler (Not Started) ⬜
**File:** `ipfs_datasets_py/integrations/warc_handler.py`

**Needs:**
- Import from WARC files
- Export to WARC format
- Integration with Common Crawl WARC fetching
- WARC record parsing

**Example API:**
```python
from ipfs_datasets_py.integrations import WARCHandler

handler = WARCHandler()
# Import from WARC
records = handler.import_from_warc("/path/to/file.warc.gz")

# Export to WARC
handler.export_to_warc(scrape_results, "/path/to/output.warc.gz")
```

#### IPWB Client (Not Started) ⬜
**File:** `ipfs_datasets_py/integrations/ipwb_client.py`

**Needs:**
- Integration with InterPlanetary Wayback Machine
- Search IPWB archives
- Retrieve archived content
- Store in IPWB format

**Example API:**
```python
from ipfs_datasets_py.integrations import IPWBClient

client = IPWBClient()
# Search IPWB
results = client.search("https://library.municode.com/*")

# Get archived content
content = client.get_archived(url, timestamp)
```

#### Wayback Machine Client (Not Started) ⬜
**File:** `ipfs_datasets_py/integrations/wayback_machine.py`

**Needs:**
- Wayback Machine API client
- CDX API integration
- Memento API support
- Retrieve historical snapshots

### Phase 3: Legal Scrapers Migration (Not Started) ⬜

**Critical:** This is the highest priority remaining work.

#### Base Legal Scraper ⬜
**File:** `ipfs_datasets_py/scrapers/legal/base.py`

**Needs:**
- Base class using UnifiedWebScraper
- Content addressing integration
- WARC export capability
- Common Crawl search integration
- Multiprocessing support

**Example structure:**
```python
class BaseLegalScraper:
    def __init__(self, enable_content_addressing=True, enable_warc=True):
        self.unified_scraper = UnifiedWebScraper()
        self.cid_computer = IPFSCIDComputer()
        self.common_crawl = CommonCrawlClient()
        self.warc_handler = WARCHandler()
    
    def scrape_with_deduplication(self, url):
        # Check if already scraped
        # Search Common Crawl first
        # Fall back to live scraping
        # Generate CID
        # Export WARC
        pass
    
    def parallel_scrape(self, urls, max_workers=10):
        # Use multiprocessing
        pass
```

#### Municipal Scrapers Migration ⬜
**Location:** `ipfs_datasets_py/scrapers/legal/municipal.py`

**Current files to migrate:**
- `mcp_server/tools/legal_dataset_tools/municipal_law_database_scrapers/municode_scraper.py`
- `mcp_server/tools/legal_dataset_tools/municipal_law_database_scrapers/ecode360_scraper.py`
- `mcp_server/tools/legal_dataset_tools/municipal_law_database_scrapers/american_legal_scraper.py`

**Action:** 
1. Move logic to `scrapers/legal/municipal.py`
2. Remove duplicate BeautifulSoup code
3. Use BaseLegalScraper
4. Add multiprocessing support

#### State Scrapers Migration ⬜
**Location:** `ipfs_datasets_py/scrapers/legal/state.py`

**Current files to migrate:**
20+ files in `mcp_server/tools/legal_dataset_tools/state_scrapers/`

**Action:**
1. Move to `scrapers/legal/states/` module
2. Create base state scraper class
3. Remove duplicate BeautifulSoup code
4. Use BaseLegalScraper
5. Add multiprocessing support

#### Federal Scrapers ⬜
**Location:** `ipfs_datasets_py/scrapers/legal/federal.py`

**Current files:**
- `mcp_server/tools/legal_dataset_tools/us_code_scraper.py`
- `mcp_server/tools/legal_dataset_tools/federal_register_scraper.py`

**Action:** Migrate and refactor similarly

### Phase 4: MCP/CLI Refactoring (Not Started) ⬜

#### MCP Tools Refactoring ⬜
**Location:** `ipfs_datasets_py/mcp_server/tools/`

**Action:**
- Make all MCP tools thin wrappers
- Should ONLY call `ipfs_datasets_py.scrapers.*`
- NO business logic in MCP tools

**Example:**
```python
# mcp_server/tools/legal_dataset_tools/legal_scraper_tools.py
from ipfs_datasets_py.scrapers.legal import LegalScraper, parallel_scrape_laws

async def mcp_scrape_legal_url(url, **kwargs):
    """MCP tool - just a thin wrapper"""
    scraper = LegalScraper()
    result = await scraper.scrape_with_deduplication(url, **kwargs)
    return result.to_dict()

async def mcp_scrape_legal_bulk(urls, **kwargs):
    """MCP tool for bulk scraping"""
    results = await parallel_scrape_laws(urls, **kwargs)
    return [r.to_dict() for r in results]
```

#### CLI Refactoring ⬜
**Location:** `ipfs_datasets_py/cli/`

**Action:**
- Move CLI to dedicated `cli/` directory
- Call package imports only
- NO business logic in CLI

### Phase 5: Testing & Validation (Not Started) ⬜

**Critical Tests Needed:**

1. **Fallback Mechanism Test** ⬜
   - Test: Playwright → BeautifulSoup → Wayback → CC → Archive.is → IPWB
   - File: `test_unified_scraping_architecture.py`

2. **Content Addressing Test** ⬜
   - Test CID computation with multiformats
   - Test Kubo fallback
   - Test deduplication

3. **Multi-Index Common Crawl Test** ⬜
   - Test searching multiple indexes
   - Test deduplication across indexes
   - Test WARC fetching

4. **WARC Import/Export Test** ⬜
   - Test WARC export
   - Test WARC import
   - Test round-trip

5. **Parallel Scraping Test** ⬜
   - Test multiprocessing
   - Test with 100+ URLs
   - Test error handling

6. **Integration Test** ⬜
   - Test full workflow: CC search → WARC fetch → CID compute → dedupe
   - Test live scraping fallback
   - Test MCP tool calls
   - Test CLI calls

## Next Steps (Priority Order)

1. **Implement WARC Handler** (HIGH)
   - Create `ipfs_datasets_py/integrations/warc_handler.py`
   - Implement import/export functionality

2. **Implement IPWB Client** (HIGH)
   - Create `ipfs_datasets_py/integrations/ipwb_client.py`
   - Integrate with IPWB

3. **Create Base Legal Scraper** (CRITICAL)
   - Create `ipfs_datasets_py/scrapers/legal/base.py`
   - Implement core functionality with multiprocessing

4. **Migrate Municipal Scrapers** (CRITICAL)
   - Move to `scrapers/legal/municipal.py`
   - Remove duplicate code

5. **Migrate State Scrapers** (CRITICAL)
   - Move to `scrapers/legal/states/`
   - Remove duplicate code

6. **Refactor MCP Tools** (HIGH)
   - Make thin wrappers
   - Remove business logic

7. **Comprehensive Testing** (HIGH)
   - Test all fallback mechanisms
   - Test parallel scraping
   - Test integrations

## Usage Examples (Target API)

### Package Import
```python
from ipfs_datasets_py.scrapers.legal import LegalScraper, parallel_scrape_laws
from ipfs_datasets_py.integrations import search_common_crawl

# Scrape with deduplication
scraper = LegalScraper()
result = scraper.scrape_with_deduplication("https://library.municode.com/wa/seattle")

# Parallel scraping
urls = [...]  # 100 URLs
results = parallel_scrape_laws(urls, max_workers=10)

# Search Common Crawl
records = search_common_crawl("https://library.municode.com/*")
```

### CLI
```bash
# Scrape single URL
ipfs-datasets legal scrape "https://library.municode.com/wa/seattle"

# Bulk scrape with multiprocessing
ipfs-datasets legal scrape-bulk urls.txt --workers 10

# Search Common Crawl
ipfs-datasets cc-search "https://library.municode.com/*" --all-indexes
```

### MCP Tool
```json
{
  "tool": "scrape_legal_bulk",
  "arguments": {
    "urls": ["url1", "url2", "url3"],
    "parallel": true,
    "max_workers": 10
  }
}
```

## Conclusion

We have completed the foundational work:
- ✅ Module structure created
- ✅ Common Crawl multi-index integration
- ✅ IPFS CID computation with multiformats + Kubo fallback
- ✅ Documentation and planning

**Critical remaining work:**
- ⬜ WARC handler
- ⬜ IPWB client
- ⬜ Base legal scraper with multiprocessing
- ⬜ Migrate all legal scrapers (20+ files)
- ⬜ Refactor MCP tools to be thin wrappers
- ⬜ Comprehensive testing

**Estimated completion:** This requires significant additional work. The migration of 20+ legal scraper files and comprehensive testing will take substantial time.

## How to Continue

The next developer should:

1. Review this document and `UNIFIED_SCRAPER_REFACTORING_PLAN.md`
2. Start with WARC handler implementation
3. Then IPWB client
4. Then create base legal scraper
5. Then systematically migrate each legal scraper
6. Finally, refactor MCP tools and add tests

All the groundwork is in place. The remaining work is implementing the pieces according to the plan.

# Legal Scraper Audit Summary

**Date:** 2025-12-20  
**Audit Tool:** `migrate_scrapers_to_unified.py`  
**Full Report:** `scraper_audit_report.json`

## Executive Summary

- **Total files audited:** 110 Python files
- **Already migrated:** 9 files (8%)
- **Needs migration:** 37 files (34%)
- **Cannot auto-migrate:** 64 files (58%)

## Scraping Patterns Detected

| Pattern | Files | Status |
|---------|-------|--------|
| BeautifulSoup | 29 | ❌ Direct usage, needs migration |
| requests | 27 | ❌ Direct usage, needs migration |
| Playwright | 13 | ❌ Direct usage, needs migration |
| aiohttp | 6 | ❌ Direct usage, needs migration |
| UnifiedWebScraper | 1 | ✅ Using unified system |
| BaseLegalScraper | 9 | ✅ Using unified system |

## Key Findings

### ✅ Already Migrated (9 files)

These files are using `BaseLegalScraper`:

```
ipfs_datasets_py/legal_scrapers/core/
├── base_scraper.py ✅
├── ecode360.py ✅
├── federal_register.py ✅
├── municode.py ✅
├── municipal_code.py ✅
├── state_laws.py ✅
└── us_code.py ✅

ipfs_datasets_py/legal_scrapers/utils/
└── parallel_scraper.py ✅
```

### ❌ High Priority Migration (37 files)

#### Municipal Database Scrapers (3 files)
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/municipal_law_database_scrapers/
├── municode_scraper.py (aiohttp + BeautifulSoup)
├── ecode360_scraper.py (aiohttp + BeautifulSoup)
└── american_legal_scraper.py (aiohttp + BeautifulSoup)
```

#### State Scrapers (11 files using old methods)
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/state_scrapers/
├── texas.py (BeautifulSoup + requests)
├── hawaii.py (Playwright)
├── delaware.py (Playwright)
├── maryland.py (Playwright)
├── louisiana.py (Playwright)
├── washington.py (Playwright)
├── district_of_columbia.py (Playwright)
├── georgia.py (Playwright)
├── wyoming.py (Playwright)
├── indiana.py (Playwright)
└── tennessee.py (Playwright)
```

#### Federal Scrapers (3 files)
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/
├── federal_register_scraper.py (requests)
├── us_code_scraper.py (BeautifulSoup + requests)
└── recap_archive_scraper.py (requests)
```

#### Aggregator Scrapers (2 files)
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/
├── state_laws_scraper.py (BeautifulSoup + requests)
└── municipal_laws_scraper.py (BeautifulSoup + requests)
```

## Migration Strategy

### Phase 1: Update Municipal Database Scrapers (Priority 1)

**Files:** 3  
**Effort:** Medium  
**Impact:** High - These are heavily used

**Current Pattern:**
```python
# municode_scraper.py
async with aiohttp.ClientSession() as session:
    async with session.get(url) as response:
        html = await response.text()
soup = BeautifulSoup(html, 'html.parser')
# ... parse HTML manually
```

**Target Pattern:**
```python
from ipfs_datasets_py.legal_scrapers.core.municode import MunicodeScraper

class MunicodeScraperMCP:
    """MCP tool wrapper for Municode scraper."""
    
    def __init__(self):
        self.scraper = MunicodeS craper(
            enable_ipfs=True,
            enable_warc=True,
            check_archives=True
        )
    
    async def search_jurisdictions(self, state=None, **kwargs):
        return await self.scraper.search_jurisdictions(state, **kwargs)
```

**Benefits:**
- Content addressing (track what's already scraped)
- Version tracking (multiple scrapes of same URL)
- Archive-first (check Common Crawl/Wayback before live scraping)
- WARC export (preserve all scrapes)
- Fallback chain (Playwright → BeautifulSoup → Wayback → Common Crawl → Archive.is)

### Phase 2: Update State Scrapers (Priority 2)

**Files:** 11  
**Effort:** High (each state is different)  
**Impact:** High - Comprehensive US law coverage

**Migration Approach:**

1. **Analyze each state's structure**
   - Some use standard HTML (BeautifulSoup sufficient)
   - Some require JavaScript (need Playwright)
   - Some have APIs (direct requests)

2. **Create state-specific scrapers inheriting BaseLegalScraper**

```python
from ipfs_datasets_py.legal_scrapers.core.base_scraper import BaseLegalScraper

class TexasLawScraper(BaseLegalScraper):
    """Scraper for Texas state laws."""
    
    def get_scraper_name(self) -> str:
        return "texas_laws"
    
    async def scrape(self, **kwargs):
        # Use unified scraping with automatic fallbacks
        result = await self.scrape_url_unified(
            url="https://statutes.capitol.texas.gov/",
            metadata={
                "source": "texas_legislature",
                "state": "TX",
                "jurisdiction": "state"
            }
        )
        
        # Parse structure (unified scraper handles fetching)
        laws = self.parse_texas_structure(result.html)
        return laws
```

3. **Update MCP tools to use new scrapers**

```python
# mcp_server/tools/legal_dataset_tools/state_scrapers/texas.py

from ipfs_datasets_py.legal_scrapers.core.state_laws import TexasLawScraper

async def scrape_texas_laws(**kwargs):
    """MCP tool for scraping Texas laws."""
    scraper = TexasLawScraper(
        enable_ipfs=True,
        check_archives=True
    )
    return await scraper.scrape(**kwargs)
```

### Phase 3: Update Federal Scrapers (Priority 3)

**Files:** 3  
**Effort:** Medium  
**Impact:** Medium - Federal data is more structured

Similar approach to state scrapers, but federal data often has better APIs.

### Phase 4: Update Aggregator Scrapers (Priority 4)

**Files:** 2  
**Effort:** Low  
**Impact:** High - These coordinate other scrapers

These should be updated to use the migrated individual scrapers.

### Phase 5: Add Multiprocessing Support (Priority 5)

**Goal:** Scrape thousands of laws in parallel

**Implementation:**
```python
# ipfs_datasets_py/legal_scrapers/utils/parallel_scraper.py (already exists!)

from ipfs_datasets_py.legal_scrapers.utils.parallel_scraper import ParallelLegalScraper

# Scrape all Texas laws in parallel
parallel_scraper = ParallelLegalScraper(
    scraper_class=TexasLawScraper,
    max_workers=20,
    enable_progress=True
)

results = await parallel_scraper.scrape_batch(texas_law_urls)
```

## Technical Considerations

### 1. Content Addressing

All scraped content should be content-addressed:

```python
# Automatic in BaseLegalScraper
result = await self.scrape_url_unified(url)
# This automatically:
# 1. Computes CID for content (uses ipfs_multiformats, falls back to Kubo)
# 2. Checks if we've scraped this CID before
# 3. Tracks URL → CID → versions
# 4. Stores in IPFS if enabled
```

### 2. Multi-Index Common Crawl

Check ALL Common Crawl indexes, not just latest:

```python
from ipfs_datasets_py.multi_index_archive_search import MultiIndexCommonCrawlSearcher

searcher = MultiIndexCommonCrawlSearcher()
results = await searcher.search_all_indexes(
    url_pattern="https://library.municode.com/*",
    max_results_per_index=100
)
# Searches: CC-MAIN-2025-47, CC-MAIN-2025-43, CC-MAIN-2025-40, etc.
```

### 3. WARC Integration

Export all scrapes to WARC format for preservation:

```python
# Automatic in BaseLegalScraper when enable_warc=True
scraper = MunicodeScraper(enable_warc=True)
result = await scraper.scrape(jurisdiction_url)
# This automatically exports to: legal_scraper_cache/municode/warc_exports/
```

### 4. Interplanetary Wayback

Check IPWB (Interplanetary Wayback) for archived versions:

```python
# Built into unified_web_scraper fallback chain
# Automatically tried after Common Crawl and before Archive.is
```

## Migration Timeline

### Week 1: Foundation
- [x] Create base scraper infrastructure
- [x] Create unified web scraper
- [x] Create content-addressed scraper
- [x] Audit existing scrapers

### Week 2: Municipal Scrapers
- [ ] Migrate municode_scraper.py
- [ ] Migrate ecode360_scraper.py
- [ ] Migrate american_legal_scraper.py
- [ ] Update MCP tools
- [ ] Add integration tests

### Week 3: State Scrapers (Batch 1)
- [ ] Migrate Texas
- [ ] Migrate Hawaii
- [ ] Migrate Delaware
- [ ] Migrate Maryland
- [ ] Migrate Louisiana

### Week 4: State Scrapers (Batch 2)
- [ ] Migrate Washington
- [ ] Migrate DC
- [ ] Migrate Georgia
- [ ] Migrate Wyoming
- [ ] Migrate Indiana
- [ ] Migrate Tennessee

### Week 5: Federal & Testing
- [ ] Migrate federal scrapers
- [ ] Migrate aggregator scrapers
- [ ] Comprehensive testing
- [ ] Performance optimization
- [ ] Documentation

## Success Metrics

✅ **Architecture:**
- All scrapers inherit from BaseLegalScraper
- No direct BeautifulSoup/Playwright/requests calls in scrapers
- All scraping goes through unified_web_scraper

✅ **Functionality:**
- Content addressing working (CID computation & tracking)
- Multi-index Common Crawl searches working
- WARC export working
- Fallback chain tested
- Multiprocessing working

✅ **Quality:**
- All scrapers have tests
- MCP tools call package imports (not inline scraping)
- CLI tools work identically to package imports
- No duplicate scraping code

## Next Actions

1. **Immediate:** Start with municode_scraper.py migration
2. **Today:** Complete all 3 municipal database scrapers
3. **This Week:** Start state scraper migration
4. **Ongoing:** Add tests as we migrate

## Commands to Run

```bash
# 1. View full audit report
cat /home/devel/ipfs_datasets_py/scraper_audit_report.json | jq .

# 2. Test current unified scraper
cd /home/devel/ipfs_datasets_py
python3 test_unified_scraping_architecture.py

# 3. Start migration with municode
cd /home/devel/ipfs_datasets_py
python3 -c "
from ipfs_datasets_py.legal_scrapers.core.municode import MunicodeScraper
import asyncio

async def test():
    scraper = MunicodeScraper(enable_ipfs=False, check_archives=True)
    result = await scraper.search_jurisdictions(state='WA', limit=5)
    print(result)

asyncio.run(test())
"

# 4. Test parallel scraping
python3 -c "
from ipfs_datasets_py.legal_scrapers.utils.parallel_scraper import ParallelLegalScraper
# Test implementation
"
```

## Questions for User

1. Should we prioritize municipal scrapers or state scrapers first?
2. What level of Common Crawl integration do you want? (Search all indexes? Just recent?)
3. Should IPFS storage be enabled by default or opt-in?
4. Do you want to preserve all historical versions or just latest?
5. What's the target parallelism level? (10 workers? 50? 100?)

---

**Report Generated:** 2025-12-20  
**Tool:** migrate_scrapers_to_unified.py  
**Status:** Ready for migration

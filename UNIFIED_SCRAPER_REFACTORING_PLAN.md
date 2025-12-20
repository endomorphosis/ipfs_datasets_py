# Unified Scraper Architecture Refactoring Plan

## Current Issues Identified

### 1. Duplicate Scraping Logic
- **BeautifulSoup** used in 20+ files across the codebase
- **Playwright** referenced in multiple locations
- **requests/httpx** scattered throughout

### 2. Architecture Misalignment
- MCP server tools contain business logic instead of just calling package imports
- Legal scrapers in `mcp_server/tools/legal_dataset_tools/` should be in core package
- No clear separation between interface (MCP/CLI) and implementation (package)

### 3. Missing Features
- ✅ Unified scraper exists but not fully integrated
- ❌ IPFS multiformats integration incomplete
- ❌ Multi-index Common Crawl searches not implemented
- ❌ WARC import/export partially implemented
- ❌ Interplanetary Wayback Machine (IPWB) not integrated
- ❌ Content-addressed deduplication needs enhancement
- ❌ No multiprocessing for parallel scraping

## Proposed Architecture

```
ipfs_datasets_py/
├── scrapers/                          # Core scraping infrastructure
│   ├── __init__.py
│   ├── unified_web_scraper.py        # Main unified scraper (EXISTS)
│   ├── content_addressed_scraper.py   # CID-based deduplication (EXISTS)
│   ├── legal/                         # Legal-specific scrapers
│   │   ├── __init__.py
│   │   ├── base.py                    # Base legal scraper
│   │   ├── municipal.py               # Municipal code scrapers
│   │   ├── state.py                   # State law scrapers
│   │   ├── federal.py                 # Federal law scrapers
│   │   └── courts.py                  # Court document scrapers
│   ├── medical/                       # Medical data scrapers
│   │   ├── __init__.py
│   │   ├── pubmed.py
│   │   └── clinicaltrials.py
│   └── financial/                     # Financial data scrapers
│       ├── __init__.py
│       └── sec.py
├── integrations/                      # External integrations
│   ├── __init__.py
│   ├── warc_handler.py               # WARC import/export
│   ├── common_crawl.py               # Multi-index CC searches
│   ├── wayback_machine.py            # Wayback Machine API
│   ├── ipwb_client.py                # IPWB integration
│   └── ipfs_cid.py                   # IPFS multiformats wrapper
├── cli/                              # CLI interfaces
│   ├── __init__.py
│   ├── scraper_cli.py                # Scraping commands
│   └── legal_cli.py                  # Legal-specific CLI
└── mcp_server/tools/                 # MCP server tools (thin wrappers)
    ├── web_scraping_tools/
    │   └── unified_scraper_tool.py   # Wraps scrapers.unified_web_scraper
    └── legal_dataset_tools/
        └── legal_scraper_tools.py     # Wraps scrapers.legal.*
```

## Implementation Plan

### Phase 1: Core Infrastructure (Priority: HIGH)
1. ✅ Move `unified_web_scraper.py` to `scrapers/` (already in root, keep copy there too)
2. ✅ Move `content_addressed_scraper.py` to `scrapers/` (already in root)
3. ⬜ Create `scrapers/legal/` module structure
4. ⬜ Create `integrations/` module with all external service wrappers

### Phase 2: Integration Enhancements (Priority: HIGH)
1. ⬜ Implement `integrations/common_crawl.py` with multi-index support
   - Search across CC-MAIN-2025-47, 46, 45, 44, 43 (and more)
   - Each index is a delta, so search all of them
2. ⬜ Implement `integrations/warc_handler.py`
   - Import from WARC files
   - Export to WARC format
3. ⬜ Implement `integrations/ipwb_client.py`
   - Integration with InterPlanetary Wayback Machine
4. ⬜ Enhance `integrations/ipfs_cid.py`
   - Use ipfs_multiformats for fast CID computation
   - Fallback to Kubo when needed

### Phase 3: Legal Scrapers Migration (Priority: HIGH)
1. ⬜ Create `scrapers/legal/base.py` with:
   - Base scraper class using unified_web_scraper
   - Content addressing integration
   - WARC export capability
2. ⬜ Migrate state scrapers from `mcp_server/tools/legal_dataset_tools/state_scrapers/`
   - Convert to use new base class
   - Remove duplicate BeautifulSoup logic
3. ⬜ Migrate municipal scrapers similarly
4. ⬜ Add multiprocessing support for parallel scraping

### Phase 4: MCP/CLI Refactoring (Priority: MEDIUM)
1. ⬜ Refactor MCP tools to be thin wrappers
   - `mcp_server/tools/web_scraping_tools/` just calls `scrapers.*`
   - `mcp_server/tools/legal_dataset_tools/` just calls `scrapers.legal.*`
2. ⬜ Update CLI tools similarly
   - Keep CLI in `cli/` directory
   - Call package imports only

### Phase 5: Testing & Validation (Priority: HIGH)
1. ⬜ Update `test_unified_scraping_architecture.py`
2. ⬜ Test all fallback mechanisms:
   - Playwright → BeautifulSoup → Wayback → Common Crawl → Archive.is → IPWB
3. ⬜ Test content addressing and deduplication
4. ⬜ Test WARC import/export
5. ⬜ Test multi-index Common Crawl searches
6. ⬜ Test parallel scraping with multiprocessing

## API Design

### Package Import Usage
```python
from ipfs_datasets_py.scrapers import UnifiedWebScraper, ScraperConfig
from ipfs_datasets_py.scrapers.legal import LegalScraper
from ipfs_datasets_py.integrations import CommonCrawlClient, WARCHandler

# Use unified scraper
scraper = UnifiedWebScraper()
result = scraper.scrape_sync("https://example.com")

# Use legal scraper with content addressing
legal = LegalScraper()
result = legal.scrape_with_deduplication("https://library.municode.com/...")

# Multi-index Common Crawl search
cc = CommonCrawlClient()
records = cc.search_multi_index("https://library.municode.com/*", 
                                 indexes=["CC-MAIN-2025-47", "CC-MAIN-2025-46"])

# Parallel scraping
from ipfs_datasets_py.scrapers.legal import parallel_scrape_laws
results = parallel_scrape_laws(urls, max_workers=10)
```

### CLI Usage
```bash
# Scrape with unified scraper
ipfs-datasets scrape "https://example.com" --fallback --warc-export

# Scrape legal data with multiprocessing
ipfs-datasets legal scrape-states --states CA,NY,TX --parallel --workers 10

# Check if already scraped (content addressed)
ipfs-datasets scrape check-scraped "https://example.com"

# Search Common Crawl across multiple indexes
ipfs-datasets cc-search "https://library.municode.com/*" --all-indexes
```

### MCP Tool Usage
```json
{
  "tool": "scrape_url",
  "arguments": {
    "url": "https://example.com",
    "fallback_enabled": true,
    "warc_export": true
  }
}

{
  "tool": "scrape_legal_bulk",
  "arguments": {
    "urls": ["url1", "url2", "url3"],
    "parallel": true,
    "max_workers": 10,
    "check_already_scraped": true
  }
}
```

## Success Criteria

1. ✅ All scraping logic centralized in `scrapers/` module
2. ✅ No duplicate BeautifulSoup/Playwright logic
3. ✅ MCP tools are thin wrappers calling package imports
4. ✅ CLI tools call package imports only
5. ✅ All fallback mechanisms work:
   - Playwright → BeautifulSoup → Wayback → Common Crawl → Archive.is → IPWB
6. ✅ Content addressing works with IPFS multiformats (+ Kubo fallback)
7. ✅ WARC import/export functional
8. ✅ Multi-index Common Crawl searches work
9. ✅ Parallel scraping with multiprocessing works
10. ✅ All tests pass

## Next Steps

1. Start with Phase 1 - create module structure
2. Implement Phase 2 integrations
3. Migrate legal scrapers in Phase 3
4. Refactor interfaces in Phase 4
5. Comprehensive testing in Phase 5

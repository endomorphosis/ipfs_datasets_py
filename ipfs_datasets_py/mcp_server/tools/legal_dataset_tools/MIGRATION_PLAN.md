# Legal Scrapers Migration Plan

## Current State
- MCP server tools directly use BeautifulSoup/requests
- Duplicated scraping logic in multiple places
- No unified fallback system
- Limited content addressing
- No WARC integration

## Target Architecture

```
┌─────────────────────────────────────────────────────┐
│              User Interfaces                         │
├──────────────┬──────────────┬─────────────────────────┤
│  CLI Tools   │  Package     │   MCP Server Tools      │
│              │  Imports     │                         │
└──────┬───────┴──────┬───────┴─────────┬───────────────┘
       │              │                 │
       └──────────────┼─────────────────┘
                      │
       ┌──────────────▼──────────────────┐
       │ ipfs_datasets_py.legal_scrapers  │
       │        (Core Package)             │
       ├──────────────────────────────────┤
       │  • BaseLegalScraper              │
       │  • MunicodeScraper               │
       │  • StateL awsScraper              │
       │  • USCodeScraper                 │
       │  • FederalRegisterScraper        │
       └──────────────┬───────────────────┘
                      │
       ┌──────────────▼──────────────────┐
       │   Unified Scraping Layer         │
       ├──────────────────────────────────┤
       │  • ContentAddressedScraper       │
       │  • UnifiedWebScraper             │
       │  • WARCIntegration               │
       │  • MultiIndexArchiveSearch       │
       └──────────────┬───────────────────┘
                      │
       ┌──────────────▼──────────────────┐
       │   Scraping Methods (Fallback)    │
       ├──────────────────────────────────┤
       │  1. Check content cache (CID)    │
       │  2. Common Crawl (all indexes)   │
       │  3. Wayback Machine              │
       │  4. IPWB                         │
       │  5. Archive.is                   │
       │  6. Playwright (JS rendering)    │
       │  7. BeautifulSoup (static)       │
       └──────────────────────────────────┘
```

## Migration Steps

### Phase 1: Update MCP Tools to Use Package Imports ✅
1. ✅ Update mcp_tools.py to import from ipfs_datasets_py.legal_scrapers
2. ✅ Remove direct BeautifulSoup/requests calls
3. ✅ Use BaseLegalScraper interface

### Phase 2: Ensure All Scrapers Use Unified Architecture
1. Verify each scraper inherits from BaseLegalScraper
2. Ensure all use ContentAddressedScraper
3. Add WARC import/export support
4. Implement multi-index Common Crawl search

### Phase 3: Add Missing Scrapers
1. Municode (priority 1)
2. Ecode360
3. American Legal Publishing
4. Other municipal databases

### Phase 4: Testing & Validation
1. Test CLI interface
2. Test package imports
3. Test MCP server tools
4. Verify fallback mechanisms work
5. Test WARC import/export
6. Test content addressing/deduplication

## Files to Update

### MCP Server Tools (Thin Wrappers)
- `mcp_server/tools/legal_dataset_tools/mcp_tools.py` - Main MCP interface
- Remove direct scraping from:
  - `municipal_laws_scraper.py`
  - `state_laws_scraper.py`
  - `us_code_scraper.py`
  - `federal_register_scraper.py`

### Core Package (Business Logic)
- `legal_scrapers/core/base_scraper.py` - ✅ Already good
- `legal_scrapers/core/municode.py` - Needs implementation
- `legal_scrapers/core/state_laws.py` - Needs verification
- `legal_scrapers/core/us_code.py` - Needs verification
- `legal_scrapers/core/federal_register.py` - Needs verification

### Unified Scraping Layer
- `content_addressed_scraper.py` - ✅ Already implemented
- `unified_web_scraper.py` - ✅ Already implemented
- `multi_index_archive_search.py` - ✅ Already implemented
- `warc_integration.py` - Needs verification

## Key Features to Implement

### 1. Content Addressing
- Use ipfs_multiformats for fast CID generation
- Fallback to Kubo if needed
- Track URL → CID mappings
- Store multiple versions (like Wayback)

### 2. Multi-Index Common Crawl
- Search across ALL Common Crawl indexes
- Each index is a delta from prior scrapes
- Aggregate results from multiple time periods

### 3. WARC Integration
- Import from Common Crawl WARC files
- Export scraped data to WARC format
- Enable archival and sharing

### 4. Fallback Chain
```python
async def scrape_with_fallback(url):
    # 1. Check content cache
    if cached := check_cache(url):
        return cached
    
    # 2. Try Common Crawl (multiple indexes)
    if cc_result := await search_common_crawl_multi_index(url):
        return cc_result
    
    # 3. Try Wayback Machine
    if wb_result := await search_wayback(url):
        return wb_result
    
    # 4. Try IPWB
    if ipwb_result := await search_ipwb(url):
        return ipwb_result
    
    # 5. Try Archive.is
    if archive_result := await search_archive_is(url):
        return archive_result
    
    # 6. Try Playwright (JS rendering)
    if pw_result := await scrape_playwright(url):
        return pw_result
    
    # 7. Fallback to BeautifulSoup
    return await scrape_beautifulsoup(url)
```

## Success Criteria
- ✅ MCP tools are thin wrappers calling package code
- ✅ CLI tools use same package code
- ✅ Package imports work standalone
- ✅ All scrapers use unified fallback system
- ✅ Content addressing works with deduplication
- ✅ WARC import/export functional
- ✅ Multi-index Common Crawl searches work
- ✅ Tests pass for all interfaces

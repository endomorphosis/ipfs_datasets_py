# Legal Scrapers Migration Plan

## Current State Analysis

### Files in MCP Server Tools (Need Migration)
Located: `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/`

**Core Scrapers (30 files total):**
1. `recap_archive_scraper.py` - CourtListener/RECAP federal court documents
2. `federal_register_scraper.py` - Federal regulations and notices
3. `us_code_scraper.py` - US Code federal statutory law
4. `state_laws_scraper.py` - State laws scraper
5. `municipal_laws_scraper.py` - Municipal codes
6. `citation_extraction.py` - Legal citation extraction

**Supporting Infrastructure:**
7. `scraper_adapter.py` - Adapter for unified scraping
8. `export_utils.py` - Export utilities
9. `state_manager.py` - State scraping management
10. `incremental_updates.py` - Incremental update logic
11. `state_laws_scheduler.py` - Scheduling for state scrapers

**Tests:**
12. `test_all_scrapers.py`
13. `test_sample_states.py`
14. `test_state_laws_integration.py`
15. `test_all_states_with_parquet.py`
16. `verify_us_code_scraper.py`
17. `verify_federal_register_scraper.py`
18. `verify_all_scrapers.py`
19. `quick_test_fixes.py`
20. `analyze_failed_state.py`

**Setup/Utilities:**
21. `setup_periodic_updates.py`

### Already Migrated to legal_scrapers/
Located: `ipfs_datasets_py/legal_scrapers/`

**Core Classes:**
- `core/base_scraper.py` - Base scraper with unified interface
- `core/recap.py` - RECAP scraper (partial)
- `core/federal_register.py` - Federal Register (partial)
- `core/us_code.py` - US Code (partial)
- `core/state_laws.py` - State laws (partial)
- `core/municipal_code.py` - Municipal codes
- `core/municode.py` - Municode specific
- `core/ecode360.py` - eCode360 specific

**Scrapers:**
- `scrapers/federal_register_scraper.py`
- `scrapers/us_code_scraper.py`
- `scrapers/municipal_scrapers/` (directory)
- `scrapers/state_scrapers/` (directory)

**Interfaces:**
- `cli/` - CLI tools
- `mcp/` - MCP server integration
- `utils/` - Utilities

## Missing Scrapers Identified

### CourtListener/Federal Courts
1. **CourtListener API Scraper** - General CourtListener search
2. **US Supreme Court Scraper** - supremecourt.gov opinions
3. **Federal Courts of Appeals** - Direct circuit court websites
4. **State Supreme Courts** - State high court websites (with CourtListener fallback)

### Citation Resolution
5. **Citation Resolver** - Resolve citations to actual documents using:
   - CourtListener (primary)
   - State court websites (fallback)
   - Google Scholar (fallback)
   - FindLaw/Justia (fallback)

## Migration Strategy

### Phase 1: Core Infrastructure Migration
**Goal:** Move shared utilities and base classes

1. **Consolidate Base Scrapers:**
   - Merge `scraper_adapter.py` into `core/base_scraper.py`
   - Ensure unified interface with fallback support

2. **Move Utilities:**
   - `export_utils.py` → `legal_scrapers/utils/export.py`
   - `state_manager.py` → `legal_scrapers/utils/state_manager.py`
   - `incremental_updates.py` → `legal_scrapers/utils/incremental.py`
   - `citation_extraction.py` → `legal_scrapers/utils/citations.py`

3. **Move Schedulers:**
   - `state_laws_scheduler.py` → `legal_scrapers/utils/scheduler.py`
   - `setup_periodic_updates.py` → `legal_scrapers/cli/setup_updates.py`

### Phase 2: Scraper Implementation Migration
**Goal:** Move scraper implementations to use unified architecture

1. **Federal Scrapers:**
   - Compare `us_code_scraper.py` (MCP) with `core/us_code.py` (package)
   - Merge functionality into `core/us_code.py` with unified interface
   - Same for `federal_register_scraper.py` and `recap_archive_scraper.py`

2. **State/Municipal Scrapers:**
   - Consolidate `state_laws_scraper.py` functionality
   - Consolidate `municipal_laws_scraper.py` functionality

### Phase 3: Add Missing Scrapers
**Goal:** Implement overlooked court scrapers

1. **CourtListener Integration:**
   - `core/courtlistener.py` - Full CourtListener API client
   - Include docket search, opinion search, oral arguments

2. **Federal Court Scrapers:**
   - `core/supreme_court.py` - Supreme Court opinions from supremecourt.gov
   - `core/circuit_courts.py` - Federal Circuit Courts of Appeals
   - Use CourtListener as fallback

3. **State Court Scrapers:**
   - `core/state_courts.py` - State supreme/appellate courts
   - Primary: CourtListener
   - Fallback: Individual state court websites

4. **Citation Resolution:**
   - `core/citation_resolver.py` - Multi-source citation resolution
   - Cascade: CourtListener → State Courts → Google Scholar → FindLaw/Justia

### Phase 4: Test Migration
**Goal:** Move and update all tests

1. **Move Tests:**
   - All `test_*.py` and `verify_*.py` files → `legal_scrapers/tests/`
   - Update imports to use package structure

2. **Update Tests:**
   - Ensure tests use unified scraper interface
   - Add tests for fallback mechanisms
   - Add tests for new scrapers (CourtListener, Supreme Court, etc.)

### Phase 5: Interface Layer
**Goal:** Ensure all scrapers accessible via CLI, MCP, and package imports

1. **CLI Layer:**
   - Update `legal_scrapers/cli/` to expose all scrapers
   - Add commands for each scraper type
   - Add batch/parallel scraping commands

2. **MCP Layer:**
   - Update `legal_scrapers/mcp/` to wrap all scrapers
   - Ensure MCP tools call package imports, not duplicate logic
   - Deprecate old MCP tools with pointers to new location

3. **Package Imports:**
   - Ensure clean `from ipfs_datasets_py.legal_scrapers import ...` interface
   - Document all public APIs

### Phase 6: Cleanup and Deprecation
**Goal:** Remove duplicates and mark deprecated files

1. **Deprecate MCP Tools:**
   - Add deprecation warnings to files in `mcp_server/tools/legal_dataset_tools/`
   - Point to new locations in `legal_scrapers/`
   - Consider removing after migration complete

2. **Remove Duplicates:**
   - Check for any orphaned files in both locations
   - Remove temporary/debug files

3. **Update Documentation:**
   - Update all README files
   - Update import examples
   - Add migration guide for users

## Unified Scraper Architecture

### Fallback Cascade
For each scrape request, try in order:

1. **IPFS/Cache Check** - Check if already scraped (content-addressed)
2. **Primary Source** - Original website (Beautiful Soup/Playwright)
3. **Common Crawl** - Multiple indexes (CC-MAIN-*)
4. **Internet Archive/Wayback** - archive.org
5. **Interplanetary Wayback (IPWB)** - IPFS-based archive
6. **Archive.is** - archive.today/archive.is
7. **Alternative APIs** - Court-specific APIs, CourtListener, etc.

### Content Addressing
- Use `ipfs_multiformats` for fast CID generation
- Fallback to Kubo for CID generation
- Store metadata: URL, timestamp, CID, source
- Enable deduplication across scrapes
- Support versioning (like Wayback Machine)

### WARC Integration
- Import from Common Crawl WARC files
- Export scraped data to WARC format
- Example: `https://index.commoncrawl.org/CC-MAIN-2025-47-index?url=https://library.municode.com/*&output=json`

### Parallel Scraping
- Use `multiprocessing` for parallel execution
- Respect rate limits per source
- Batch processing for efficiency
- Progress tracking and resumption

## Success Criteria

1. ✅ All scrapers accessible via 3 interfaces (CLI, MCP, package)
2. ✅ Unified fallback system working for all scrapers
3. ✅ Content-addressed storage with deduplication
4. ✅ WARC import/export functional
5. ✅ Parallel scraping working
6. ✅ All tests passing
7. ✅ No duplicate code in MCP tools vs package
8. ✅ Complete coverage: federal, state, municipal, court documents
9. ✅ Citation resolution with fallbacks
10. ✅ Documentation complete

## Next Steps

1. Start with Phase 1 - utilities migration
2. Move to Phase 2 - scraper consolidation
3. Add missing scrapers in Phase 3
4. Migrate tests in Phase 4
5. Complete interfaces in Phase 5
6. Clean up in Phase 6

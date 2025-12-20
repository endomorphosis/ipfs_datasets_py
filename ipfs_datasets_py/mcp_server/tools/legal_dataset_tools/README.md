# Legal Dataset Tools - MCP Interface

This directory contains the MCP (Model Context Protocol) server interface layer for legal dataset scrapers.

## Architecture

The legal scraping functionality follows a layered architecture:

```
┌─────────────────────────────────────────┐
│  MCP Server Tools (this directory)      │
│  - Thin wrappers exposing MCP protocol  │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│  ipfs_datasets_py.legal_scrapers        │
│  - Core scraping logic                  │
│  - Unified scraper with fallbacks       │
│  - Domain-specific scrapers             │
└─────────────────────────────────────────┘
```

## Files in This Directory

### Core Files
- **mcp_tools.py** - MCP tool definitions that delegate to the core package
- **legal_scraper_cli.py** - CLI interface (may delegate to core CLI)
- **__init__.py** - Package initialization

### What Was Migrated

The following have been moved to their proper locations:

#### To `ipfs_datasets_py/legal_scrapers/utils/`:
- `citations.py` (was citation_extraction.py) - Citation extraction
- `export.py` (was export_utils.py) - Data export utilities
- `state_manager.py` - Resumable scraping state
- `ipfs_storage.py` (was ipfs_storage_integration.py) - IPFS integration
- `incremental.py` (was incremental_updates.py) - Incremental updates

#### To `ipfs_datasets_py/legal_scrapers/municipal/`:
- All municipal law database scrapers (Municode, eCode360, American Legal)

#### To `tests/legal_scrapers/`:
- All test_*.py files
- All validate_*.py files
- All verify_*.py files

#### To `scripts/`:
- `setup_periodic_updates.py`
- `state_laws_cron.py`
- `state_laws_scheduler.py`
- `analyze_failed_state.py`

## Usage

### From MCP Client (Claude Desktop, etc.)

```python
# MCP tool call
await mcp_scrape_legal_url(
    url="https://library.municode.com/wa/seattle",
    prefer_archived=True,
    enable_warc=True
)
```

### From Python Code

```python
from ipfs_datasets_py.legal_scrapers import UnifiedLegalScraper

scraper = UnifiedLegalScraper()
result = await scraper.scrape_url("https://example.com/legal/doc")
```

### From CLI

```bash
ipfs-datasets legal scrape https://library.municode.com/wa/seattle
```

## Available MCP Tools

- `mcp_scrape_legal_url` - Scrape any legal URL with unified fallback chain
- `mcp_scrape_municode` - Scrape Municode library
- `mcp_scrape_state_laws` - Scrape state laws
- `mcp_scrape_federal_register` - Scrape Federal Register
- `mcp_scrape_us_code` - Scrape U.S. Code
- `mcp_scrape_court_opinions` - Scrape court opinions (CourtListener + fallback)

## Fallback Chain

The unified scraper automatically tries multiple sources:

1. **Check if already scraped** (content-addressed cache)
2. **Common Crawl** (searches ALL indexes - each is a delta)
3. **Interplanetary Wayback Machine (IPWB)**
4. **Internet Archive Wayback Machine**
5. **Archive.is / Archive.today**
6. **Playwright** (for JavaScript-heavy pages)
7. **BeautifulSoup** (direct scraping)

## Content Addressing

All scraped content is content-addressed using IPFS CIDs:
- Fast local hashing with `ipfs-multiformats` (Python implementation)
- Fallback to Kubo IPFS daemon if available
- Duplicate detection across scraping sessions
- Version tracking (like Wayback Machine)

## WARC Support

Can import/export WARC files:
```python
# Export to WARC
result = await scraper.scrape_url(url, enable_warc=True)
print(result["warc_path"])

# Import from WARC
scraper.import_from_warc("archive.warc.gz")
```

## Development

To add a new legal data source:

1. Create scraper in `ipfs_datasets_py/legal_scrapers/core/your_scraper.py`
2. Extend `UnifiedLegalScraper` or create domain-specific scraper
3. Add MCP tool wrapper in `mcp_tools.py`
4. Add CLI command in `ipfs_datasets_py/cli/legal_commands.py`
5. Add tests in `tests/legal_scrapers/`

## See Also

- [Legal Scrapers Package](../../legal_scrapers/README.md)
- [Content-Addressed Scraping Guide](../../../../CONTENT_ADDRESSED_SCRAPING_GUIDE.md)
- [WARC Integration Guide](../../../../WARC_INTEGRATION_GUIDE.md)

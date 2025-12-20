# Legal Scrapers Quick Reference

## Installation
```bash
cd /home/devel/ipfs_datasets_py
pip install -e .
```

## Quick Start

### 1. Package Import (Python)
```python
from ipfs_datasets_py.legal_scrapers.core import MunicodeScraper

scraper = MunicodeScraper(enable_warc=True, check_archives=True)
result = await scraper.scrape(jurisdiction_url="https://library.municode.com/ca/san_francisco")
print(f"Scraped {result['jurisdiction']} - CID: {result.get('content_cid')}")
```

### 2. CLI Tool
```bash
# Scrape municipal codes
python -m ipfs_datasets_py.legal_scrapers.cli.legal_cli municipal \
    --provider municode \
    --jurisdiction "San Francisco, CA" \
    --enable-warc

# Scrape state laws
python -m ipfs_datasets_py.legal_scrapers.cli.legal_cli state-laws \
    --states CA NY TX \
    --output state_laws.json

# Scrape US Code
python -m ipfs_datasets_py.legal_scrapers.cli.legal_cli us-code \
    --titles 18 42 \
    --format parquet
```

### 3. MCP Server Tool
```python
from ipfs_datasets_py.legal_scrapers.mcp import scrape_municipal_codes

result = await scrape_municipal_codes(
    provider="municode",
    jurisdiction="San Francisco, CA",
    enable_warc=True
)
```

## Available Scrapers

| Scraper | Data Source | Coverage |
|---------|-------------|----------|
| **MunicodeScraper** | Municode.com | 3,500+ US municipalities |
| **ECode360Scraper** | eCode360.com | 1,000+ US municipalities |
| **StateLawsScraper** | State gov sites | All 50 US states + DC |
| **USCodeScraper** | uscode.house.gov | All 54 titles of US Code |
| **FederalRegisterScraper** | federalregister.gov | Federal regulations |
| **RECAPScraper** | CourtListener | Federal court documents |

## Key Features

### Content Addressing
- Automatically generates IPFS CID for each scrape
- Checks if URL already scraped (avoids duplicates)
- Tracks versions like Wayback Machine

### Multi-Source Fallback
Tries sources in order:
1. Common Crawl (all indexes)
2. Wayback Machine
3. IPWB (Interplanetary Wayback)
4. Archive.is
5. Playwright (JS rendering)
6. Live scraping

### WARC Support
- Imports from Common Crawl WARC files
- Exports to WARC format
- Example: Search Common Crawl
  ```
  https://index.commoncrawl.org/CC-MAIN-2025-47-index?url=https://library.municode.com/*&output=json
  ```

### Parallel Scraping
```python
scraper = UnifiedLegalScraper(max_workers=8)
results = await scraper.scrape_urls(url_list)  # Parallel
```

## Configuration Options

```python
scraper = MunicodeScraper(
    cache_dir="./cache",          # Cache directory
    enable_ipfs=True,              # Store in IPFS
    enable_warc=True,              # Export to WARC
    check_archives=True,           # Check archives first
    output_format="parquet"        # json, parquet, csv
)
```

## Testing

```bash
# Run all tests
python test_unified_legal_scraper_architecture.py

# Expected: 9/9 tests passed ✅
```

## Common Use Cases

### Scrape All Municipal Codes
```python
from ipfs_datasets_py.legal_scrapers.core import MunicodeScraper

scraper = MunicodeScraper()
jurisdictions = ["San Francisco, CA", "New York, NY", "Chicago, IL"]

for jurisdiction in jurisdictions:
    result = await scraper.scrape(jurisdiction=jurisdiction)
    print(f"✓ {jurisdiction}: {result.get('content_cid')}")
```

### Scrape All State Laws
```bash
python -m ipfs_datasets_py.legal_scrapers.cli.legal_cli state-laws \
    --enable-warc \
    --format parquet \
    --output all_state_laws.parquet
```

### Check if URL Already Scraped
```python
from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper

ca_scraper = ContentAddressedScraper()
result = await ca_scraper.scrape_with_version_tracking(url)

if result.get("already_scraped"):
    print(f"Already scraped! CID: {result['content_cid']}")
else:
    print(f"New scrape. CID: {result['content_cid']}")
```

## Troubleshooting

### Import Errors
```bash
# Ensure package installed
pip install -e /home/devel/ipfs_datasets_py

# Check Python path
python -c "import sys; print('\\n'.join(sys.path))"
```

### WARC Not Working
```bash
# Install warcio
pip install warcio
```

### IPFS CID Generation Slow
```bash
# Install ipfs_multiformats for fast CID computation
pip install ipfs-multiformats

# Or falls back to Kubo (slower)
```

## Architecture

```
User Request
    ↓
MCP Tool / CLI / Package Import
    ↓
Core Scraper (inherits BaseLegalScraper)
    ↓
Content Addressed Scraper (checks if already scraped)
    ↓
Unified Scraping Adapter (tries fallbacks)
    ↓
    ├→ Common Crawl (all indexes)
    ├→ Wayback Machine
    ├→ IPWB
    ├→ Archive.is
    ├→ Playwright
    └→ Live Scraping
    ↓
WARC Export (optional)
    ↓
IPFS Storage (optional)
    ↓
Result with CID
```

## Files

### Core Package
- `ipfs_datasets_py/legal_scrapers/core/` - Scraper implementations
- `ipfs_datasets_py/content_addressed_scraper.py` - Content addressing
- `ipfs_datasets_py/multi_index_archive_search.py` - Common Crawl
- `ipfs_datasets_py/warc_integration.py` - WARC support

### Interfaces
- `ipfs_datasets_py/legal_scrapers/cli/legal_cli.py` - CLI
- `ipfs_datasets_py/legal_scrapers/mcp/legal_mcp_tools.py` - MCP tools

### Tests
- `test_unified_legal_scraper_architecture.py` - Test suite

### Documentation
- `LEGAL_SCRAPERS_UNIFIED_MIGRATION_COMPLETE.md` - Full migration docs
- `LEGAL_SCRAPERS_QUICK_REFERENCE.md` - This file

## Support

For issues or questions:
1. Check test output: `python test_unified_legal_scraper_architecture.py`
2. Review logs: scrapers use Python logging module
3. See full documentation: `LEGAL_SCRAPERS_UNIFIED_MIGRATION_COMPLETE.md`

## Status
✅ All 9/9 tests passing
✅ Migration complete
✅ Production ready

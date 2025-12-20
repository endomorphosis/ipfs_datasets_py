# Unified Legal Scrapers - Quick Reference

## Overview

All legal scrapers now use a unified architecture with:
- **Content addressing** (IPFS CIDs for deduplication)
- **Multi-source fallback** (7 different scraping methods)
- **Multi-index Common Crawl** (searches all CC indexes, not just latest)
- **WARC integration** (import/export for archival)
- **3 interfaces**: Package imports, CLI tools, MCP server

## Quick Start

### 1. Package Import (Python)

```python
from ipfs_datasets_py.legal_scrapers.core import MunicodeScraper

# Initialize
scraper = MunicodeScraper(
    enable_ipfs=True,      # Store in IPFS
    enable_warc=True,      # Export to WARC
    check_archives=True    # Check CC/Wayback first
)

# Scrape
result = await scraper.scrape("https://library.municode.com/wa/seattle")

# Check results
if result['success']:
    print(f"CID: {result['content_cid']}")
    print(f"Source: {result['source']}")
    print(f"Cached: {result['already_scraped']}")
```

### 2. MCP Server Tool

```python
# Use via MCP protocol
result = await mcp_scrape_municode_jurisdiction(
    jurisdiction_url="https://library.municode.com/wa/seattle",
    extract_sections=True
)
```

### 3. CLI Tool

```bash
python -m ipfs_datasets_py.legal_scrapers.cli.municode_cli \
    --url "https://library.municode.com/wa/seattle" \
    --extract-sections \
    --enable-ipfs
```

## Available Scrapers

### Municode (Municipal Codes)
```python
from ipfs_datasets_py.legal_scrapers.core import MunicodeScraper

scraper = MunicodeScraper()
result = await scraper.scrape("https://library.municode.com/wa/seattle")
```

### US Code (Federal Law)
```python
from ipfs_datasets_py.legal_scrapers.core import USCodeScraper

scraper = USCodeScraper()
result = await scraper.scrape(title=18)  # Title 18: Crimes
result = await scraper.scrape(title=18, section="1001")  # Specific section
```

### State Laws
```python
from ipfs_datasets_py.legal_scrapers.core import StateLawsScraper

scraper = StateLawsScraper()
result = await scraper.scrape(
    state_code="WA",
    include_statutes=True,
    include_regulations=False
)
```

### Federal Register
```python
from ipfs_datasets_py.legal_scrapers.core import FederalRegisterScraper

scraper = FederalRegisterScraper()
result = await scraper.scrape(
    query="EPA environmental",
    document_type="rule",
    start_date="2024-01-01"
)
```

## Features

### Content Addressing (Deduplication)

Check if already scraped before making requests:

```python
from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper

scraper = ContentAddressedScraper()

# Check if URL already scraped
url = "https://library.municode.com/wa/seattle"
is_scraped, versions = await scraper.check_url_scraped(url)

if is_scraped:
    print(f"Already have {len(versions)} versions")
else:
    # Scrape with version tracking
    result = await scraper.scrape_with_version_tracking(url)
    print(f"CID: {result['content_cid']}")
    print(f"Version: {result['version']}")
```

### Multi-Index Common Crawl

Search across ALL Common Crawl indexes:

```python
from ipfs_datasets_py.multi_index_archive_search import MultiIndexWebArchiveSearcher

searcher = MultiIndexWebArchiveSearcher()

# Search across all indexes
results = await searcher.search_url("library.municode.com/*")

print(f"Found in {len(results['indexes'])} indexes:")
for idx in results['indexes']:
    print(f"  - {idx}: {results[idx]['count']} URLs")
```

### WARC Import/Export

Export scraped data to WARC:

```python
from ipfs_datasets_py.warc_integration import WARCExporter

exporter = WARCExporter(output_dir="./warc_exports")
warc_path = await exporter.export(
    url="https://library.municode.com/wa/seattle",
    html=html_content,
    metadata={"source": "municode", "jurisdiction": "Seattle"}
)
print(f"Exported to: {warc_path}")
```

Import from Common Crawl WARC:

```python
from ipfs_datasets_py.warc_integration import CommonCrawlWARCImporter
from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper

content_scraper = ContentAddressedScraper()
importer = CommonCrawlWARCImporter(content_scraper)

# Import from CC WARC file
await importer.import_from_warc(
    "https://data.commoncrawl.org/crawl-data/CC-MAIN-2024-51/segments/.../warc/..."
)
```

### Parallel Scraping

Scrape multiple URLs in parallel:

```python
from ipfs_datasets_py.legal_scrapers.core import MunicodeScraper
from ipfs_datasets_py.legal_scrapers.utils import ParallelScraper

scraper = MunicodeScraper()
parallel = ParallelScraper(scraper, max_workers=10)

urls = [
    "https://library.municode.com/wa/seattle",
    "https://library.municode.com/ca/los_angeles",
    "https://library.municode.com/ny/new_york",
]

results = await parallel.scrape_all(urls)
print(f"Scraped {sum(1 for r in results if r['success'])}/{len(urls)}")
```

### Fallback Chain

The scraper automatically tries methods in this order:

1. **Cache check** - Is content already scraped? (CID lookup)
2. **Common Crawl** - Search all CC indexes
3. **Wayback Machine** - Internet Archive snapshots
4. **IPWB** - InterPlanetary Wayback
5. **Archive.is** - Permanent snapshots
6. **Playwright** - JavaScript rendering for dynamic pages
7. **BeautifulSoup** - Static HTML parsing

No configuration needed - it just works!

## MCP Server Tools

All tools available via MCP protocol:

```python
# Generic legal URL
await mcp_scrape_legal_url(url, prefer_archived=True)

# Bulk scraping
await mcp_scrape_legal_urls_bulk(urls, max_concurrent=10)

# Specialized scrapers
await mcp_scrape_municode_jurisdiction(jurisdiction_url)
await mcp_scrape_us_code_title(title=18)
await mcp_scrape_state_laws(state_code="WA")
await mcp_scrape_federal_register(query="EPA")

# Archive search
await mcp_search_common_crawl(url, indexes=["CC-MAIN-2024-51"])

# WARC
await mcp_import_from_warc(warc_url)
await mcp_export_to_warc(url, html, metadata)
```

## Common Patterns

### Pattern 1: Check before scraping

```python
# Don't waste time re-scraping
result = await scraper.scrape(url)
if result['already_scraped']:
    print("Using cached version")
else:
    print(f"Scraped from: {result['source']}")
```

### Pattern 2: Prefer archives over live

```python
# Initialize with archive checking
scraper = MunicodeScraper(
    check_archives=True  # Try CC/Wayback first
)

result = await scraper.scrape(url)
# Will use archived version if available
```

### Pattern 3: Build complete dataset

```python
async def build_municode_dataset():
    scraper = MunicodeScraper(enable_ipfs=True, enable_warc=True)
    parallel = ParallelScraper(scraper, max_workers=20)
    
    # All 3,500+ jurisdictions
    jurisdictions = load_jurisdiction_list()
    
    results = await parallel.scrape_all(jurisdictions)
    
    # Export to dataset format
    for result in results:
        if result['success']:
            save_to_dataset(result)
```

### Pattern 4: Version tracking

```python
# Track changes over time
content_scraper = ContentAddressedScraper()

# First scrape
v1 = await content_scraper.scrape_with_version_tracking(url)
print(f"Version 1 CID: {v1['content_cid']}")

# Later scrape (content changed)
v2 = await content_scraper.scrape_with_version_tracking(url)
print(f"Version 2 CID: {v2['content_cid']}")
print(f"Changed: {v2['changed']}")

# Get all versions
versions = content_scraper.version_history[url]
print(f"Total versions: {len(versions)}")
```

## Configuration Options

All scrapers support these options:

```python
scraper = SomeLegalScraper(
    cache_dir="./cache",        # Where to store cache
    enable_ipfs=False,          # Store in IPFS
    enable_warc=False,          # Export to WARC
    check_archives=True,        # Check CC/Wayback first
    output_format="json"        # json, parquet, csv, warc
)
```

## Troubleshooting

### Import errors
```python
# Make sure package is in path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from ipfs_datasets_py.legal_scrapers.core import MunicodeScraper
```

### Async/await
```python
# Legal scrapers are async
import asyncio

async def main():
    scraper = MunicodeScraper()
    result = await scraper.scrape(url)
    return result

# Run it
result = asyncio.run(main())
```

### Dependencies
```bash
# Install required packages
pip install beautifulsoup4 requests aiohttp
pip install playwright  # For JS rendering
pip install warcio     # For WARC support
```

## Performance Tips

1. **Enable archive checking** - Faster than live scraping
2. **Use parallel scraping** - Scrape multiple URLs at once
3. **Check cache first** - Avoid duplicate work
4. **Enable WARC export** - Share datasets efficiently
5. **Use IPFS storage** - Permanent archival

## More Info

- Full docs: [LEGAL_SCRAPERS_MIGRATION_COMPLETE.md](LEGAL_SCRAPERS_MIGRATION_COMPLETE.md)
- Migration plan: [MIGRATION_PLAN.md](ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/MIGRATION_PLAN.md)
- Tests: [test_legal_scraper_migration.py](test_legal_scraper_migration.py)

---
**Last Updated**: 2025-12-20  
**Status**: Production Ready ✅

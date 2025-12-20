# Unified Scraping - Quick Start Guide

## Installation

```bash
cd /home/devel/ipfs_datasets_py
pip install -e .

# Optional dependencies for full functionality
pip install playwright warcio newspaper3k readability-lxml
playwright install chromium
```

## Quick Examples

### 1. Scrape a Single Municode Jurisdiction

```python
from ipfs_datasets_py.legal_scrapers import scrape_municode

# Simple sync call
result = scrape_municode("https://library.municode.com/wa/seattle")

print(f"✅ {result['jurisdiction_name']}")
print(f"📄 Sections: {len(result['sections'])}")
print(f"🔗 CID: {result['content_cid']}")
```

### 2. Batch Scrape Multiple Jurisdictions

```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper
import asyncio

async def batch_scrape():
    scraper = MunicodeScraper()
    
    urls = [
        "https://library.municode.com/wa/seattle",
        "https://library.municode.com/wa/tacoma",
        "https://library.municode.com/wa/spokane",
    ]
    
    results = await scraper.scrape_multiple(urls, max_concurrent=5)
    
    for r in results:
        print(f"{r['jurisdiction_name']}: {r['status']}")

asyncio.run(batch_scrape())
```

### 3. Import from Common Crawl

```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper
import asyncio

async def import_historical():
    scraper = MunicodeScraper(enable_warc=True)
    
    # Import historical content from Common Crawl
    records = await scraper.import_from_common_crawl(
        url_pattern="library.municode.com/wa/*",
        index_id="CC-MAIN-2024-51",
        max_records=50
    )
    
    print(f"✅ Imported {len(records)} historical records")
    
    # Export to WARC for archiving
    warc_path = scraper.export_to_warc(records)
    print(f"📦 Exported to: {warc_path}")

asyncio.run(import_historical())
```

### 4. CLI Usage

```bash
# Scrape single jurisdiction
python -m ipfs_datasets_py.legal_scrapers.cli.municode_cli scrape \
    --url "https://library.municode.com/wa/seattle" \
    --output seattle.json

# Batch scrape from file
echo "https://library.municode.com/wa/seattle" > urls.txt
echo "https://library.municode.com/wa/tacoma" >> urls.txt

python -m ipfs_datasets_py.legal_scrapers.cli.municode_cli batch \
    --urls-file urls.txt \
    --output-dir ./scraped_codes \
    --max-concurrent 5

# Import from Common Crawl
python -m ipfs_datasets_py.legal_scrapers.cli.municode_cli import-crawl \
    --pattern "library.municode.com/wa/*" \
    --max-records 100 \
    --output crawl_import.json
```

### 5. Check if Already Scraped

```python
from ipfs_datasets_py.content_addressed_scraper import get_content_addressed_scraper

scraper = get_content_addressed_scraper()

url = "https://library.municode.com/wa/seattle"
status = scraper.check_url_scraped(url)

if status['scraped']:
    print(f"✅ Already scraped {status['total_versions']} versions")
    print(f"🔗 Latest CID: {status['latest_cid']}")
    print(f"📅 Last scraped: {status['latest_scraped_at']}")
else:
    print("❌ Not yet scraped")
```

### 6. Search All Common Crawl Indexes

```python
from ipfs_datasets_py.multi_index_archive_search import get_multi_index_searcher
import asyncio

async def search_archives():
    searcher = get_multi_index_searcher()
    
    # Search ALL Common Crawl indexes (not just one)
    results = await searcher.unified_archive_search(
        url="https://library.municode.com/wa/seattle",
        domain="library.municode.com",
        search_common_crawl=True,
        search_wayback=True,
        deduplicate_by_cid=True
    )
    
    print(f"📊 Total captures: {results['summary']['total_captures']}")
    print(f"🔗 Unique versions: {results['summary']['unique_content_versions']}")
    print(f"🗄️  Sources: {', '.join(results['summary']['sources_searched'])}")

asyncio.run(search_archives())
```

### 7. Parallel Scraping with Multiprocessing

```python
from ipfs_datasets_py.legal_scrapers.utils import ParallelScraper

# Load URLs from file
with open("jurisdictions.txt") as f:
    urls = [line.strip() for line in f]

# Scrape in parallel with 10 workers
scraper = ParallelScraper(
    scraper_class="MunicodeScraper",
    num_workers=10
)

results = scraper.scrape_parallel(urls)

# Print summary
success = sum(1 for r in results if r['status'] == 'success')
print(f"✅ Success: {success}/{len(results)}")
```

### 8. Get Statistics

```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper

scraper = MunicodeScraper()
stats = scraper.get_statistics()

print("📊 Scraping Statistics:")
print(f"  URLs tracked: {stats['total_urls_tracked']}")
print(f"  Unique content: {stats['total_unique_content_cids']}")
print(f"  Total versions: {stats['total_versions_scraped']}")
print(f"  Avg versions per URL: {stats['avg_versions_per_url']:.2f}")
print(f"  Duplicates found: {stats['duplicate_content_instances']}")
```

## Configuration Options

```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper

scraper = MunicodeScraper(
    cache_dir="./my_cache",        # Where to store scraped content
    enable_ipfs=True,               # Store in IPFS for permanence
    enable_warc=True,               # Enable WARC import/export
    check_archives=True,            # Check archives before scraping
    output_format="json"            # Output format (json, parquet, csv)
)
```

## Testing

```bash
# Run legal scrapers test suite
cd /home/devel/ipfs_datasets_py
python3 ipfs_datasets_py/legal_scrapers/test_legal_scrapers.py

# Run architecture tests
python3 test_unified_scraping_architecture.py

# Run with pytest
pytest ipfs_datasets_py/legal_scrapers/test_legal_scrapers.py -v
```

## Troubleshooting

### Missing Dependencies

```bash
# Core (required)
pip install aiohttp beautifulsoup4 multiformats requests

# Optional but recommended
pip install playwright warcio wayback newspaper3k readability-lxml pandas pyarrow

# Install Playwright browsers
playwright install chromium
```

### Force Rescrape

```python
# Force rescrape even if already cached
result = await scraper.scrape(url, force_rescrape=True)
```

### Adjust Rate Limiting

```python
scraper.config.rate_limit_delay = 0.5  # Faster (use carefully)
scraper.config.rate_limit_delay = 2.0  # Slower (more polite)
```

## Available Scrapers

- ✅ **MunicodeScraper** - 3,500+ US municipal codes
- ✅ **StateLawsScraper** - All 50 US states  
- ✅ **FederalRegisterScraper** - Federal regulations
- ✅ **USCodeScraper** - United States Code
- ✅ **eCode360Scraper** - eCode360 platform
- ✅ **MunicipalCodeScraper** - Generic municipal codes

All use the same interface!

## Key Features

✅ Content-addressed storage (CID-based)  
✅ Version tracking (like Wayback Machine)  
✅ Automatic deduplication  
✅ Multi-index Common Crawl search  
✅ WARC import/export  
✅ Intelligent fallback chain  
✅ Parallel scraping support  
✅ Three interfaces: Package, CLI, MCP  

## Documentation

- **Full Guide**: `UNIFIED_SCRAPING_MIGRATION_COMPLETE.md`
- **Legal Scrapers README**: `ipfs_datasets_py/legal_scrapers/README.md`
- **API Docs**: In docstrings (use `help()` in Python)

## Support

Run tests if you encounter issues:

```bash
python3 ipfs_datasets_py/legal_scrapers/test_legal_scrapers.py
```

Check logs for detailed error information.

---

**Quick Reference Version**: 1.0  
**Last Updated**: 2024-12-19

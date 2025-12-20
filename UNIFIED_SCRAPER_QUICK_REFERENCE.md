# Unified Scraper Quick Reference

## Quick Start

### 1. Scrape a Single URL
```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper

scraper = MunicodeScraper(check_archives=True)
result = await scraper.scrape("https://library.municode.com/wa/seattle")

print(f"CID: {result['content_cid']}")
print(f"Sections: {result['section_count']}")
```

### 2. Scrape Multiple URLs in Parallel
```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper
from ipfs_datasets_py.legal_scrapers.utils import scrape_urls_parallel

urls = ["https://library.municode.com/wa/seattle", 
        "https://library.municode.com/wa/tacoma"]

results = scrape_urls_parallel(
    scraper_class=MunicodeScraper,
    urls=urls,
    num_processes=4
)
```

### 3. Check if URL Already Scraped
```python
from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper

scraper = ContentAddressedScraper()
status = scraper.check_url_scraped("https://library.municode.com/wa/seattle")

if status['scraped']:
    print(f"Found {status['total_versions']} versions")
    print(f"Latest CID: {status['latest_cid']}")
```

### 4. Search Common Crawl Archives
```python
from ipfs_datasets_py.multi_index_archive_search import get_multi_index_searcher

searcher = get_multi_index_searcher()

# Search ALL Common Crawl indexes
results = await searcher.search_all_common_crawl_indexes(
    domain="library.municode.com",
    limit_per_index=100
)

print(f"Found {results['total_results']} results")
print(f"Unique URLs: {results['unique_urls']}")
```

### 5. Use CLI Tool
```bash
# Scrape single jurisdiction
python -m ipfs_datasets_py.legal_scrapers.cli.municode_cli \
    --jurisdiction "https://library.municode.com/wa/seattle" \
    --output results.json

# Scrape with parallel processing
python -m ipfs_datasets_py.legal_scrapers.cli.municode_cli \
    --batch jurisdictions.txt \
    --processes 8 \
    --output-dir ./results/
```

## Available Scrapers

| Scraper | Coverage | Example URL |
|---------|----------|-------------|
| **MunicodeScraper** | 3,500+ jurisdictions | `library.municode.com/wa/seattle` |
| **USCodeScraper** | 54 US Code titles | `uscode.house.gov` |
| **FederalRegisterScraper** | Federal rules/notices | `federalregister.gov` |
| **StateLawsScraper** | All 50 states | Various state sites |
| **eCode360Scraper** | eCode360 municipalities | `ecode360.com` |
| **MunicipalCodeScraper** | Generic municipal codes | Various |

## Common Patterns

### Pattern 1: Scrape with Archive Checking
```python
scraper = MunicodeScraper(
    check_archives=True,  # Check Common Crawl/Wayback first
    enable_warc=True,     # Enable WARC export
    enable_ipfs=True      # Store in IPFS
)
```

### Pattern 2: Batch Scraping with Progress
```python
from ipfs_datasets_py.legal_scrapers.utils import scrape_urls_parallel

def progress_callback(completed, total):
    print(f"Progress: {completed}/{total} ({completed/total*100:.1f}%)")

results = scrape_urls_parallel(
    scraper_class=MunicodeScraper,
    urls=my_urls,
    progress=True
)
```

### Pattern 3: Export to WARC
```python
scraper = MunicodeScraper(enable_warc=True)
results = await scraper.scrape(url)

warc_path = await scraper.export_to_warc([results])
print(f"Exported to: {warc_path}")
```

### Pattern 4: Content Deduplication
```python
from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper

scraper = ContentAddressedScraper()

# Scrape URL
result = await scraper.scrape_with_content_addressing(
    url="https://library.municode.com/wa/seattle",
    force_rescrape=False  # Skip if already scraped
)

if result['already_scraped']:
    print(f"Already have version {result['version']}")
else:
    print(f"New content! CID: {result['content_cid']}")
```

## Configuration Options

### Scraper Options
```python
MunicodeScraper(
    cache_dir="./cache",        # Cache directory
    enable_ipfs=False,          # Store in IPFS
    enable_warc=False,          # Export to WARC
    check_archives=True,        # Check archives before scraping
    output_format="json"        # Output format (json, parquet, csv)
)
```

### Parallel Scraper Options
```python
ParallelScraper(
    scraper_class=MunicodeScraper,
    num_processes=8,            # Number of processes
    max_workers=16,             # Max concurrent workers
    rate_limit=0.1,             # Seconds between requests
    use_multiprocessing=True    # True for multiprocessing, False for asyncio
)
```

## CID Computation

### Fast CID for Bytes
```python
from ipfs_datasets_py.ipfs_multiformats import compute_cid, cid_to_string

content = b"Hello, world!"
cid = compute_cid(content)
cid_str = cid_to_string(cid)
```

### CID for Strings
```python
from ipfs_datasets_py.ipfs_multiformats import get_cid

text = "Legal document text"
cid = get_cid(text, for_string=True)
```

### CID for Files
```python
from ipfs_datasets_py.ipfs_multiformats import get_cid

cid = get_cid("/path/to/file.pdf")
```

## Fallback Chain

When scraping a URL, the system tries in order:

1. **Local Cache** (by CID) - Instant
2. **Common Crawl** (all indexes) - Historical data
3. **Wayback Machine** - More historical data
4. **IPFS Wayback** - Decentralized archives
5. **Live Web** - Fetch from source

## Error Handling

```python
try:
    result = await scraper.scrape(url)
    
    if result['status'] == 'success':
        print(f"Success! CID: {result['content_cid']}")
    elif result['status'] == 'cached':
        print(f"From cache: {result['content_cid']}")
    else:
        print(f"Error: {result.get('error')}")
        
except Exception as e:
    print(f"Scraping failed: {e}")
```

## Performance Tips

1. **Use Parallel Scraping** for large batches
   - Multiprocessing for CPU-intensive parsing
   - AsyncIO for I/O-intensive network requests

2. **Enable Archive Checking** to reduce live requests
   - 50-80% of URLs may be in Common Crawl
   - Faster and reduces server load

3. **Use Content Addressing** for deduplication
   - Automatically skip duplicate content
   - Track versions over time

4. **Configure Rate Limits** appropriately
   - Respect source website policies
   - Balance speed vs. politeness

5. **Batch Operations** when possible
   - Use `scrape_urls_parallel` for multiple URLs
   - Process results in batches

## Testing

### Run All Tests
```bash
cd /home/devel/ipfs_datasets_py
python3 test_unified_scraping_architecture.py
```

### Test Specific Scraper
```bash
python3 ipfs_datasets_py/legal_scrapers/test_legal_scrapers.py
```

### Test with Live URL
```python
import asyncio
from ipfs_datasets_py.legal_scrapers import MunicodeScraper

async def test():
    scraper = MunicodeScraper()
    result = await scraper.scrape("https://library.municode.com/wa/seattle")
    print(result)

asyncio.run(test())
```

## Troubleshooting

### Issue: CID computation fails
**Solution**: Check if `multiformats` library is installed:
```bash
pip install py-multiformats
```

### Issue: WARC import fails
**Solution**: Install warcio:
```bash
pip install warcio
```

### Issue: Parallel scraping hangs
**Solution**: Use asyncio instead of multiprocessing:
```python
scraper = ParallelScraper(
    scraper_class=MunicodeScraper,
    use_multiprocessing=False  # Use asyncio
)
```

### Issue: Rate limiting
**Solution**: Increase rate limit delay:
```python
scraper = MunicodeScraper()
scraper.adapter.rate_limit_delay = 1.0  # 1 second between requests
```

## Common Use Cases

### Use Case 1: Scrape All Municipal Codes
```python
# Get list of all jurisdictions
from ipfs_datasets_py.legal_scrapers import MunicodeScraper

scraper = MunicodeScraper()
jurisdictions = await scraper.get_all_jurisdictions()

# Scrape in parallel
from ipfs_datasets_py.legal_scrapers.utils import scrape_urls_parallel

results = scrape_urls_parallel(
    scraper_class=MunicodeScraper,
    urls=jurisdictions,
    num_processes=8,
    progress=True
)
```

### Use Case 2: Update Existing Dataset
```python
from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper

scraper = ContentAddressedScraper()

for url in my_urls:
    status = scraper.check_url_scraped(url)
    
    if not status['scraped']:
        # Never scraped - scrape it
        result = await scraper.scrape_with_content_addressing(url)
    elif status['total_versions'] == 1:
        # Only one version - check for updates
        result = await scraper.scrape_with_content_addressing(
            url, 
            check_version_changes=True
        )
```

### Use Case 3: Build Citation Graph
```python
results = []

for url in legal_document_urls:
    result = await scraper.scrape(url)
    results.append({
        'url': url,
        'cid': result['content_cid'],
        'citations': extract_citations(result['content']),
        'version': result['version']
    })

# Build graph
import networkx as nx
G = nx.DiGraph()
for r in results:
    for citation in r['citations']:
        G.add_edge(r['cid'], citation['cid'])
```

## Best Practices

1. ✅ **Always use content addressing** for deduplication
2. ✅ **Check archives first** before live scraping  
3. ✅ **Use parallel processing** for large batches
4. ✅ **Export to WARC** for long-term archival
5. ✅ **Track versions** to detect changes
6. ✅ **Respect rate limits** and robots.txt
7. ✅ **Handle errors gracefully** with retries
8. ✅ **Monitor CID cache hits** to optimize

## Support

- **Documentation**: See `UNIFIED_SCRAPER_MIGRATION_COMPLETE.md`
- **Tests**: Run `test_unified_scraping_architecture.py`
- **Examples**: Check individual scraper docstrings

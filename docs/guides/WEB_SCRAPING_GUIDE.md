# Web Scraping and Archival Tools - Complete Implementation

## Overview

This repository now includes comprehensive web scraping and archival capabilities with support for all the major tools and services requested:

- **Common Crawl** (@cocrawler/cdx_toolkit) - Access to massive web crawl datasets
- **Internet Archive Wayback Machine** (@internetarchive/wayback) - Historical web content retrieval  
- **InterPlanetary Wayback Machine** (@oduwsdl/ipwb) - Decentralized web archiving on IPFS
- **AutoScraper** (@alirezamika/autoscraper) - Intelligent automated web scraping
- **Archive.is** - Permanent webpage snapshot creation
- **Heritrix3** (@internetarchive/heritrix3) - Advanced web crawling (via integration patterns)

## Quick Start

### Installation

```bash
# Install the web scraping dependencies
pip install cdx-toolkit wayback internetarchive autoscraper ipwb warcio beautifulsoup4

# Install the main package
pip install -e .
```

### Basic Usage

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
    search_common_crawl,
    search_wayback_machine,
    archive_to_archive_is,
    create_autoscraper_model
)

async def example_usage():
    # Search Common Crawl for domain content
    cc_results = await search_common_crawl("example.com", limit=10)
    print(f"Found {cc_results['count']} records in Common Crawl")
    
    # Search Wayback Machine for historical captures
    wb_results = await search_wayback_machine("example.com", limit=10)
    print(f"Found {wb_results['count']} historical captures")
    
    # Archive a page to Archive.is
    archive_result = await archive_to_archive_is("http://example.com")
    print(f"Archived to: {archive_result['archive_url']}")

asyncio.run(example_usage())
```

## Detailed Feature Documentation

### 1. Common Crawl Integration

Access billions of web pages from Common Crawl's monthly datasets.

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_search import (
    search_common_crawl,
    get_common_crawl_content,
    list_common_crawl_indexes
)

# Search for domain content
results = await search_common_crawl(
    domain="example.com",
    crawl_id="CC-MAIN-2024-10",  # Optional: specific crawl
    limit=100,
    from_timestamp="20240101",
    to_timestamp="20240331"
)

# Get actual content from WARC files
content = await get_common_crawl_content(
    url="http://example.com/page.html",
    timestamp="20240101120000"
)

# List available crawl indexes
indexes = await list_common_crawl_indexes()
```

### 2. Internet Archive Wayback Machine

Enhanced integration with Internet Archive's Wayback Machine.

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.wayback_machine_search import (
    search_wayback_machine,
    get_wayback_content,
    archive_to_wayback
)

# Search for historical captures
captures = await search_wayback_machine(
    url="example.com",
    from_date="20200101",
    to_date="20240101",
    limit=50,
    collapse="timestamp:8"  # Daily snapshots
)

# Get historical content
content = await get_wayback_content(
    url="http://example.com",
    timestamp="20230615120000",
    closest=True
)

# Submit URL for archiving
archive_result = await archive_to_wayback("http://example.com/new-page")
```

### 3. InterPlanetary Wayback Machine (IPWB)

Decentralized web archiving using IPFS.

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.ipwb_integration import (
    index_warc_to_ipwb,
    start_ipwb_replay,
    search_ipwb_archive,
    get_ipwb_content
)

# Index a WARC file to IPFS
index_result = await index_warc_to_ipwb(
    warc_path="/path/to/archive.warc",
    ipfs_endpoint="http://localhost:5001",
    encrypt=True
)

# Start IPWB replay server
replay_server = await start_ipwb_replay(
    cdxj_path=index_result['cdxj_path'],
    port=5000
)

# Search IPFS archives
search_results = await search_ipwb_archive(
    cdxj_path=index_result['cdxj_path'],
    url_pattern="example.com"
)

# Get content from IPFS
content = await get_ipwb_content(
    ipfs_hash="QmYourHashHere",
    ipfs_endpoint="http://localhost:5001"
)
```

### 4. AutoScraper Integration

Intelligent web scraping with machine learning.

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.autoscraper_integration import (
    create_autoscraper_model,
    scrape_with_autoscraper,
    batch_scrape_with_autoscraper
)

# Train a scraping model
model_result = await create_autoscraper_model(
    sample_url="http://example.com/product/123",
    wanted_data=["Product Name", "$99.99", "In Stock"],
    model_name="product_scraper"
)

# Use the model to scrape similar pages
scrape_results = await scrape_with_autoscraper(
    model_path=model_result['model_path'],
    target_urls=[
        "http://example.com/product/124",
        "http://example.com/product/125"
    ]
)

# Batch scrape from URL file
batch_result = await batch_scrape_with_autoscraper(
    model_path=model_result['model_path'],
    urls_file="/path/to/urls.txt",
    output_format="json",
    batch_size=50
)
```

### 5. Archive.is Integration

Create permanent webpage snapshots.

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_is_integration import (
    archive_to_archive_is,
    search_archive_is,
    get_archive_is_content,
    batch_archive_to_archive_is
)

# Archive a single URL
archive_result = await archive_to_archive_is(
    url="http://example.com/important-page",
    wait_for_completion=True,
    timeout=300
)

# Search archived content by domain
search_results = await search_archive_is(
    domain="example.com",
    limit=50
)

# Get archived content
content = await get_archive_is_content(
    archive_url="https://archive.is/abc123"
)

# Batch archive multiple URLs
batch_result = await batch_archive_to_archive_is(
    urls=["http://example.com/page1", "http://example.com/page2"],
    delay_seconds=2.0,
    max_concurrent=3
)
```

## Advanced Usage with AdvancedWebArchiver

The enhanced `AdvancedWebArchiver` class now supports all new services:

```python
from ipfs_datasets_py.advanced_web_archiving import AdvancedWebArchiver, ArchivingConfig

# Configure with new services
config = ArchivingConfig(
    enable_local_warc=True,
    enable_internet_archive=True,
    enable_archive_is=True,
    enable_common_crawl=True,  # New
    enable_ipwb=True,          # New
    autoscraper_model="product_scraper"  # New
)

archiver = AdvancedWebArchiver(config)

# Archive with multiple services
collection = await archiver.archive_website_collection(
    root_urls=["http://example.com"],
    crawl_depth=2,
    include_media=True
)

print(f"Archived {collection.archived_resources} resources")
print(f"Services used: {list(collection.resources[0].archive_urls.keys())}")
```

## Configuration

### Dependencies

Add to your `requirements.txt`:

```
# Web scraping and archiving tools
cdx-toolkit>=0.9.37  # Common Crawl CDX access
wayback>=0.4.5  # Wayback Machine API
internetarchive>=5.5.0  # Internet Archive access
autoscraper>=1.1.14  # Intelligent web scraping
ipwb>=0.2024.10.24  # InterPlanetary Wayback Machine
warcio>=1.7.4  # WARC file processing
beautifulsoup4>=4.12.0  # HTML parsing for scraping
selenium>=4.15.0  # Browser automation for dynamic content
scrapy>=2.11.0  # Advanced web scraping framework
```

### Environment Setup

```bash
# For IPWB - ensure IPFS is running
ipfs daemon

# For Common Crawl - no additional setup required

# For AutoScraper - ensure Chrome/Chromium for Selenium
sudo apt-get install chromium-browser

# For Archive.is - no additional setup required
```

## Integration Patterns

### Multi-Source Dataset Creation

```python
async def create_comprehensive_dataset(domain):
    results = {}
    
    # Get current content
    cc_results = await search_common_crawl(domain, limit=100)
    results['common_crawl'] = cc_results
    
    # Get historical content
    wb_results = await search_wayback_machine(domain, limit=50)
    results['wayback'] = wb_results
    
    # Archive current state
    archive_result = await archive_to_archive_is(f"http://{domain}")
    results['archived'] = archive_result
    
    # Extract structured data if model exists
    try:
        scraped = await scrape_with_autoscraper(
            "/tmp/autoscraper_models/general.pkl",
            [f"http://{domain}"]
        )
        results['structured_data'] = scraped
    except:
        pass
    
    return results
```

### Content Verification Pipeline

```python
async def verify_archive_integrity():
    # Verify Common Crawl accessibility
    cc_indexes = await list_common_crawl_indexes()
    print(f"Available CC indexes: {len(cc_indexes['indexes'])}")
    
    # Verify IPWB archives
    ipwb_result = await verify_ipwb_archive(
        "/path/to/archive.cdxj",
        sample_size=10
    )
    print(f"IPWB integrity: {ipwb_result['success_rate']:.2%}")
    
    # Test Wayback Machine access
    wb_test = await get_wayback_content("http://example.com")
    print(f"Wayback access: {'OK' if wb_test['status'] == 'success' else 'FAILED'}")
```

## Performance Considerations

### Rate Limiting

All tools implement proper rate limiting:

- **Common Crawl**: 1 request/second recommended
- **Wayback Machine**: 2 requests/second max
- **Archive.is**: 1 request/2 seconds recommended
- **AutoScraper**: Configurable delays between requests

### Batch Processing

Use batch functions for large-scale operations:

```python
# Batch archive 1000 URLs
batch_result = await batch_archive_to_archive_is(
    urls=url_list,
    delay_seconds=2.0,
    max_concurrent=3
)

# Batch scrape with AutoScraper
batch_scrape = await batch_scrape_with_autoscraper(
    model_path="/path/to/model.pkl",
    urls_file="/path/to/urls.txt",
    batch_size=50,
    delay_seconds=1.0
)
```

### Storage Optimization

- Use IPWB for deduplication via content-addressing
- Compress WARC files for long-term storage
- Index frequently accessed archives

## Error Handling

All functions include comprehensive error handling:

```python
try:
    result = await search_common_crawl("example.com")
    if result['status'] == 'error':
        print(f"Error: {result['error']}")
    else:
        print(f"Success: {result['count']} records")
except Exception as e:
    print(f"Exception: {e}")
```

## Testing

Run the test suite to verify all features:

```bash
# Run comprehensive tests
python direct_test.py

# Test specific components
python -c "
import asyncio
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import search_common_crawl
result = asyncio.run(search_common_crawl('example.com', limit=1))
print('Test passed!' if result['status'] == 'success' else 'Test failed!')
"
```

## Troubleshooting

### Common Issues

1. **CDX Toolkit not found**: Install with `pip install cdx-toolkit`
2. **IPFS not running**: Start with `ipfs daemon`
3. **Rate limiting**: Implement delays between requests
4. **Large WARC files**: Use streaming processing for memory efficiency

### Dependencies

If imports fail, install missing dependencies:

```bash
pip install cdx-toolkit wayback internetarchive autoscraper ipwb
```

## Contributing

When extending the web archiving tools:

1. Follow the existing pattern in `mcp_server/tools/web_archive_tools/`
2. Include comprehensive error handling
3. Add async support for all functions
4. Update `__init__.py` with new exports
5. Add tests for new functionality

## License

This implementation maintains the same license as the parent repository while adding comprehensive web scraping and archival capabilities.
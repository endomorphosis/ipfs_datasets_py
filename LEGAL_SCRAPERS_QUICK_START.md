# Legal Scrapers - Quick Start Guide

## Installation

```bash
cd /home/devel/ipfs_datasets_py
pip install -e .
```

## Basic Usage

### 1. Unified Scraper (Recommended)

Automatically detects scraper type and handles all fallbacks:

```python
from ipfs_datasets_py.legal_scrapers import UnifiedLegalScraper
import asyncio

async def scrape_legal_url(url):
    scraper = UnifiedLegalScraper(
        enable_ipfs=True,      # Enable IPFS content addressing
        enable_warc=True,      # Enable WARC export
        check_archives=True,   # Check archives before live scraping
        max_workers=4          # Parallel workers
    )
    
    result = await scraper.scrape_url(url)
    print(f"Success: {result.get('success')}")
    print(f"CID: {result.get('content_cid')}")
    print(f"Source: {result.get('source')}")
    return result

# Example usage
asyncio.run(scrape_legal_url("https://library.municode.com/ca/san_francisco"))
```

### 2. Court Documents

#### CourtListener - Search All Courts
```python
from ipfs_datasets_py.legal_scrapers import CourtListenerScraper
import asyncio

async def search_courts():
    scraper = CourtListenerScraper(api_token="YOUR_TOKEN")  # Token optional
    
    # Search Supreme Court opinions
    scotus = await scraper.get_supreme_court_opinions(term="2023", limit=100)
    
    # Search Circuit Courts
    circuit9 = await scraper.get_circuit_court_opinions(circuit="9", limit=50)
    
    # Search opinions by keyword
    search = await scraper.search_opinions(
        query="search and seizure",
        court_type="appellate",
        start_date="2023-01-01",
        limit=100
    )
    
    return scotus, circuit9, search

asyncio.run(search_courts())
```

#### Supreme Court Scraper
```python
from ipfs_datasets_py.legal_scrapers import SupremeCourtScraper
import asyncio

async def get_scotus_opinions():
    scraper = SupremeCourtScraper(use_courtlistener_fallback=True)
    
    # Get opinions by term
    opinions = await scraper.get_opinions(term="2023", limit=100)
    
    # Get oral arguments
    arguments = await scraper.get_oral_arguments(term="2023", limit=50)
    
    return opinions, arguments

asyncio.run(get_scotus_opinions())
```

### 3. Citation Resolution

```python
from ipfs_datasets_py.legal_scrapers import CitationResolver
import asyncio

async def resolve_citations():
    resolver = CitationResolver(courtlistener_api_token="YOUR_TOKEN")
    
    # Single citation
    result = await resolver.resolve("564 U.S. 1")
    print(f"Resolved: {result}")
    
    # Batch citations
    citations = [
        "123 F.3d 456",
        "789 S.Ct. 123",
        "456 U.S. 789"
    ]
    results = await resolver.batch_resolve(citations)
    print(f"Batch results: {len(results['results'])} citations resolved")
    
    return result, results

asyncio.run(resolve_citations())
```

### 4. Municipal Codes

```python
from ipfs_datasets_py.legal_scrapers import UnifiedLegalScraper
import asyncio

async def scrape_multiple_cities():
    scraper = UnifiedLegalScraper(max_workers=8)
    
    urls = [
        "https://library.municode.com/ca/san_francisco",
        "https://library.municode.com/ny/new_york",
        "https://library.municode.com/il/chicago",
        "https://library.municode.com/tx/houston",
        "https://library.municode.com/az/phoenix",
    ]
    
    # Scrape in parallel
    results = await asyncio.gather(*[scraper.scrape_url(url) for url in urls])
    
    for url, result in zip(urls, results):
        print(f"{url}: {'✓' if result.get('success') else '✗'}")
    
    return results

asyncio.run(scrape_multiple_cities())
```

### 5. Federal Law

```python
from ipfs_datasets_py.legal_scrapers import UnifiedLegalScraper
import asyncio

async def scrape_federal():
    scraper = UnifiedLegalScraper()
    
    # U.S. Code
    usc = await scraper.scrape_url("https://uscode.house.gov/view.xhtml?req=title:18")
    
    # Federal Register
    fr = await scraper.scrape_url("https://www.federalregister.gov/documents/...")
    
    return usc, fr

asyncio.run(scrape_federal())
```

## Advanced Usage

### Content Addressing & Deduplication

```python
from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper
import asyncio

async def content_addressed_scraping():
    scraper = ContentAddressedScraper(cache_dir="./legal_cache")
    
    url = "https://library.municode.com/ca/san_francisco"
    
    # First scrape - actually fetches content
    result1 = await scraper.scrape_with_content_addressing(url)
    print(f"First: CID={result1.get('content_cid')}")
    
    # Second scrape - detects duplicate, returns cached
    result2 = await scraper.scrape_with_content_addressing(url)
    print(f"Second: Already scraped={result2.get('already_scraped')}")
    
    return result1, result2

asyncio.run(content_addressed_scraping())
```

### Parallel Batch Scraping

```python
from ipfs_datasets_py.legal_scrapers import UnifiedLegalScraper
import asyncio

async def parallel_scraping():
    scraper = UnifiedLegalScraper(max_workers=16)
    
    # Large list of URLs
    urls = [...]  # 100s or 1000s of URLs
    
    # Scrape all in parallel
    tasks = [scraper.scrape_url(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    successful = sum(1 for r in results if isinstance(r, dict) and r.get('success'))
    failed = len(results) - successful
    
    print(f"Success: {successful}/{len(results)}")
    print(f"Failed: {failed}/{len(results)}")
    
    return results

asyncio.run(parallel_scraping())
```

## CLI Usage (Framework)

```bash
# Unified scraper
python -m ipfs_datasets_py.legal_scrapers.cli.unified_cli \
    "https://library.municode.com/ca/san_francisco" \
    --output san_francisco.json \
    --enable-ipfs \
    --check-archives

# CourtListener search
python -m ipfs_datasets_py.legal_scrapers.cli.courtlistener_cli \
    --search "search and seizure" \
    --court supreme \
    --limit 100

# Citation resolution
python -m ipfs_datasets_py.legal_scrapers.cli.citation_cli \
    --citation "564 U.S. 1" \
    --output resolved.json
```

## MCP Server (Framework)

```bash
# Start MCP server
python -m ipfs_datasets_py.legal_scrapers.mcp.server

# Or from Python
from ipfs_datasets_py.legal_scrapers.mcp import register_all_legal_scraper_tools

registry = register_all_legal_scraper_tools()
```

## Testing

```bash
# Run comprehensive test suite
cd /home/devel/ipfs_datasets_py
python ipfs_datasets_py/legal_scrapers/tests/test_comprehensive_scraping.py

# Or with pytest
pytest ipfs_datasets_py/legal_scrapers/tests/ -v
```

## Supported Sources

### Federal
- ✅ U.S. Code (uscode.house.gov)
- ✅ Federal Register (federalregister.gov)
- ✅ Supreme Court (supremecourt.gov + CourtListener)
- ✅ Circuit Courts (CourtListener)
- ✅ District Courts (CourtListener)
- ✅ RECAP Archive (CourtListener)

### State
- ✅ State statutes (all 50 states)
- ✅ State supreme courts (CourtListener + direct)
- ✅ State appellate courts (CourtListener)

### Municipal
- ✅ Municode (3,500+ jurisdictions)
- ✅ eCode360
- ✅ American Legal Publishing

### Archives
- ⚠️ Common Crawl (framework)
- ⚠️ Internet Archive (framework)
- ⚠️ IPWB (framework)
- ⚠️ Archive.is (framework)

## Fallback Cascade

For each URL, automatically tries:
1. IPFS cache (content-addressed)
2. Primary source (live website)
3. Common Crawl (multiple indexes)
4. Internet Archive / Wayback
5. Interplanetary Wayback (IPWB)
6. Archive.is
7. Alternative APIs (e.g., CourtListener)

## Common Issues

### Missing ipfs_multiformats
```bash
# Install for fast CID computation
pip install ipfs-multiformats
```

### Missing warcio
```bash
# Install for WARC support
pip install warcio
```

### CourtListener API Rate Limits
```python
# Use API token for higher limits
scraper = CourtListenerScraper(api_token="YOUR_TOKEN")

# Get token at: https://www.courtlistener.com/api/rest-info/
```

## Documentation

- **Full Reference**: `LEGAL_SCRAPERS_REFACTORING_COMPLETE.md`
- **Migration Plan**: `LEGAL_SCRAPERS_MIGRATION_PLAN.md`
- **Summary**: `SCRAPER_MIGRATION_SUMMARY.md`
- **API Docs**: See docstrings in source files

## Support

- File issues in ipfs_datasets_py repository
- Check test suite for examples
- See documentation for detailed API reference

---

**Quick Start Version**: 1.0  
**Date**: 2025-12-20

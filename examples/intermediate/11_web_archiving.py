"""
Web Archiving - Scrape, Archive, and Search Web Content

This example demonstrates how to scrape web content, archive it, and search
using Common Crawl, Wayback Machine, and custom web scraping capabilities.

Requirements:
    - beautifulsoup4: pip install beautifulsoup4
    - requests: pip install requests
    - lxml: pip install lxml

Usage:
    python examples/11_web_archiving.py
"""

import asyncio
from pathlib import Path


async def demo_basic_web_scraping():
    """Scrape content from a web page."""
    print("\n" + "="*70)
    print("DEMO 1: Basic Web Scraping")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.web_archiving import WebTextExtractor
        
        print("\n🌐 Initializing web scraper...")
        extractor = WebTextExtractor()
        
        # Example URL (using a simple page)
        url = "https://example.com"
        
        print(f"\n📥 Scraping: {url}")
        result = await extractor.extract(url)
        
        if result.success:
            print("✅ Scraping successful")
            print(f"   Title: {result.metadata.get('title', 'N/A')}")
            print(f"   Text length: {len(result.text)} characters")
            print(f"   Links found: {len(result.metadata.get('links', []))}")
            print(f"\n   Preview:")
            print(f"   {result.text[:200]}...")
        else:
            print(f"❌ Scraping failed: {result.error}")
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")
        print("   Install with: pip install beautifulsoup4 requests lxml")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("   Note: Requires internet connection")


async def demo_unified_web_scraper():
    """Use the unified web scraper with multiple strategies."""
    print("\n" + "="*70)
    print("DEMO 2: Unified Web Scraper")
    print("="*70)
    
    print("\n🔧 Unified Web Scraper")
    print("   Multi-strategy scraping with fallbacks")
    
    example_code = '''
from ipfs_datasets_py.processors.web_archiving import UnifiedWebScraper

scraper = UnifiedWebScraper(
    strategies=["beautifulsoup", "selenium", "requests"],
    fallback_enabled=True,
    timeout=30
)

# Scrape with automatic strategy selection
result = await scraper.scrape(
    url="https://example.com/page",
    extract_metadata=True,
    follow_links=False
)

print(f"Strategy used: {result.strategy}")
print(f"Success: {result.success}")
print(f"Content: {result.text[:500]}...")

# Scrape multiple URLs
urls = [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3"
]

results = await scraper.scrape_batch(urls, max_concurrent=3)

for url, result in zip(urls, results):
    print(f"{url}: {len(result.text) if result.success else 'failed'} chars")
    '''
    
    print(example_code)


async def demo_brave_search():
    """Search the web using Brave Search API."""
    print("\n" + "="*70)
    print("DEMO 3: Brave Web Search")
    print("="*70)
    
    print("\n🔍 Brave Search API")
    print("   (Requires BRAVE_API_KEY environment variable)")
    
    example_code = '''
import os
from ipfs_datasets_py.processors.web_archiving import BraveSearchClient

# Set API key
os.environ['BRAVE_API_KEY'] = 'your_api_key_here'

# Initialize client
client = BraveSearchClient()

# Search
results = await client.search(
    query="Python programming tutorials",
    count=10,
    safesearch="moderate"
)

# Process results
for i, result in enumerate(results, 1):
    print(f"{i}. {result['title']}")
    print(f"   URL: {result['url']}")
    print(f"   Snippet: {result['description'][:100]}...")
    print()

# Search with caching
results_cached = await client.search(
    query="Python programming tutorials",  # Same query
    count=10,
    use_cache=True  # Will return cached results
)
    '''
    
    print(example_code)
    
    print("\n💡 Features:")
    print("   - Fast web search")
    print("   - Result caching")
    print("   - Safe search filtering")
    print("   - Rich metadata")


async def demo_common_crawl():
    """Access Common Crawl data."""
    print("\n" + "="*70)
    print("DEMO 4: Common Crawl Access")
    print("="*70)
    
    print("\n📚 Common Crawl Search")
    print("   Access billions of archived web pages")
    
    example_code = '''
from ipfs_datasets_py.processors.web_archiving import CommonCrawlSearchEngine

engine = CommonCrawlSearchEngine()

# Search for domain
results = await engine.search(
    domain="example.com",
    date_range=("2023-01-01", "2023-12-31"),
    limit=100
)

print(f"Found {len(results)} archived pages")

for result in results[:5]:
    print(f"URL: {result['url']}")
    print(f"Timestamp: {result['timestamp']}")
    print(f"WARC record: {result['warc_record']}")
    print()

# Retrieve content from WARC
content = await engine.get_warc_content(
    warc_record=results[0]['warc_record']
)

print(f"Retrieved: {len(content)} bytes")
    '''
    
    print(example_code)
    
    print("\n🗄️  Common Crawl Benefits:")
    print("   - Massive archive (petabytes)")
    print("   - Historical snapshots")
    print("   - Free access")
    print("   - Research-friendly")


async def demo_wayback_machine():
    """Access Wayback Machine archives."""
    print("\n" + "="*70)
    print("DEMO 5: Wayback Machine")
    print("="*70)
    
    print("\n⏰ Wayback Machine Access")
    
    example_code = '''
from ipfs_datasets_py.processors.web_archiving import WaybackMachineClient

client = WaybackMachineClient()

# Check if URL is archived
url = "https://example.com"
is_archived = await client.is_archived(url)

if is_archived:
    print(f"{url} is archived")
    
    # Get available snapshots
    snapshots = await client.get_snapshots(
        url=url,
        year=2023
    )
    
    print(f"Found {len(snapshots)} snapshots in 2023")
    
    # Retrieve specific snapshot
    snapshot = snapshots[0]
    content = await client.get_snapshot(
        url=url,
        timestamp=snapshot['timestamp']
    )
    
    print(f"Retrieved snapshot from {snapshot['timestamp']}")
    print(f"Content: {len(content)} bytes")

# Archive a new URL
archive_result = await client.archive_url(
    url="https://example.com/new-page"
)

print(f"Archived at: {archive_result['archive_url']}")
    '''
    
    print(example_code)


async def demo_parallel_archiving():
    """Archive multiple URLs in parallel."""
    print("\n" + "="*70)
    print("DEMO 6: Parallel Web Archiving")
    print("="*70)
    
    print("\n⚡ Parallel Web Archiver")
    print("   10-25x faster than sequential")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import ParallelWebArchiver

archiver = ParallelWebArchiver(
    max_concurrent=10,
    fallback_sources=["common_crawl", "wayback", "direct"],
    rate_limit_per_second=5
)

# URLs to archive
urls = [
    "https://example.com/page1",
    "https://example.com/page2",
    # ... hundreds more
]

# Archive with progress tracking
def on_progress(completed, total):
    percent = (completed / total) * 100
    print(f"Progress: {completed}/{total} ({percent:.1f}%)")

results = await archiver.archive_batch(
    urls=urls,
    progress_callback=on_progress
)

# Analyze results
successful = sum(1 for r in results if r.success)
print(f"Archived: {successful}/{len(urls)} URLs")

# Results include source information
for result in results[:5]:
    print(f"{result.url}")
    print(f"  Source: {result.source}")  # common_crawl, wayback, or direct
    print(f"  Size: {result.size_bytes} bytes")
    '''
    
    print(example_code)


async def demo_scraper_framework():
    """Use the scraper testing framework."""
    print("\n" + "="*70)
    print("DEMO 7: Scraper Testing Framework")
    print("="*70)
    
    print("\n🧪 Scraper Testing & Validation")
    
    example_code = '''
from ipfs_datasets_py.processors.web_archiving import ScraperTestingFramework

framework = ScraperTestingFramework()

# Define test cases
test_cases = [
    {
        "url": "https://example.com",
        "expected_title": "Example Domain",
        "expected_keywords": ["example", "domain"],
        "min_text_length": 100
    }
]

# Run tests
results = await framework.run_tests(test_cases)

for test_case, result in zip(test_cases, results):
    print(f"URL: {test_case['url']}")
    print(f"  Passed: {result.passed}")
    print(f"  Title match: {result.checks['title_match']}")
    print(f"  Keywords found: {result.checks['keywords_found']}")
    print(f"  Length check: {result.checks['length_check']}")
    
# Validate scraped content
content = await scraper.scrape("https://example.com")
is_valid = await framework.validate(
    content=content,
    rules={
        "min_length": 100,
        "required_elements": ["title", "body"],
        "forbidden_patterns": ["404", "error"]
    }
)

print(f"Content valid: {is_valid}")
    '''
    
    print(example_code)


def show_tips():
    """Show tips for web archiving."""
    print("\n" + "="*70)
    print("TIPS FOR WEB ARCHIVING")
    print("="*70)
    
    print("\n1. Scraping Best Practices:")
    print("   - Respect robots.txt")
    print("   - Use rate limiting (don't overload servers)")
    print("   - Set user-agent string appropriately")
    print("   - Handle errors gracefully")
    print("   - Cache results to avoid redundant requests")
    
    print("\n2. Strategy Selection:")
    print("   - BeautifulSoup: Fast, good for simple HTML")
    print("   - Selenium: For JavaScript-heavy sites")
    print("   - Requests: For APIs and simple pages")
    print("   - Use UnifiedWebScraper for automatic fallback")
    
    print("\n3. Common Crawl:")
    print("   - Free access to petabytes of data")
    print("   - Historical snapshots every month")
    print("   - Use WARC format for efficiency")
    print("   - Index files help find specific content")
    
    print("\n4. Wayback Machine:")
    print("   - 700+ billion archived pages")
    print("   - Historical snapshots since 1996")
    print("   - Submit URLs for archiving")
    print("   - API available for programmatic access")
    
    print("\n5. Performance:")
    print("   - Use parallel archiving for multiple URLs")
    print("   - Implement connection pooling")
    print("   - Cache DNS lookups")
    print("   - Use CDN detection for faster access")
    
    print("\n6. Legal & Ethical:")
    print("   - Check copyright and terms of service")
    print("   - Don't scrape personal data without consent")
    print("   - Respect rate limits and robots.txt")
    print("   - Proper attribution for archived content")
    
    print("\n7. Data Quality:")
    print("   - Validate scraped content")
    print("   - Check for encoding issues")
    print("   - Handle redirects properly")
    print("   - Detect and handle errors (404, 500, etc.)")
    
    print("\n8. Storage:")
    print("   - Store on IPFS for decentralization")
    print("   - Use compression (gzip, brotli)")
    print("   - Index metadata for searchability")
    print("   - Version control archived content")
    
    print("\n9. Next Steps:")
    print("   - See 10_legal_data_scraping.py for domain-specific scraping")
    print("   - See 06_ipfs_storage.py for archiving to IPFS")


async def main():
    """Run all web archiving demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - WEB ARCHIVING")
    print("="*70)
    
    print("\n⚠️  Note: Web scraping examples require internet connection")
    
    await demo_basic_web_scraping()
    await demo_unified_web_scraper()
    await demo_brave_search()
    await demo_common_crawl()
    await demo_wayback_machine()
    await demo_parallel_archiving()
    await demo_scraper_framework()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ WEB ARCHIVING EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())

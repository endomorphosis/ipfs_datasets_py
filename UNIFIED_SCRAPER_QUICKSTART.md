# Unified Web Scraper - Quick Start Guide

## What is it?

The Unified Web Scraper is a comprehensive web scraping system that automatically tries 9 different scraping methods until one succeeds. You never have to worry about which method to use - the system handles it for you.

## Quick Start (5 minutes)

### 1. Install Basic Dependencies

```bash
pip install requests beautifulsoup4
```

### 2. Try It Out

```python
from ipfs_datasets_py.unified_web_scraper import scrape_url

# That's it! One line to scrape any URL
result = scrape_url("https://example.com")

if result.success:
    print(f"Title: {result.title}")
    print(f"Content: {result.content}")
    print(f"Method used: {result.method_used.value}")
```

### 3. Or Use the CLI

```bash
# Check what methods are available
python -m ipfs_datasets_py.scraper_cli check-methods

# Scrape a URL
python -m ipfs_datasets_py.scraper_cli scrape https://example.com

# Save to file
python -m ipfs_datasets_py.scraper_cli scrape https://example.com \
    --output result.txt --format text
```

## Why Use It?

### Before (the hard way)
```python
# You had to know which library to use
# And handle failures manually

try:
    import requests
    from bs4 import BeautifulSoup
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    text = soup.get_text()
except Exception as e:
    # Try playwright?
    try:
        from playwright.async_api import async_playwright
        # ... complex code ...
    except:
        # Try wayback machine?
        try:
            from wayback import WaybackClient
            # ... more complex code ...
        except:
            # Give up
            pass
```

### After (the easy way)
```python
# Just use the unified scraper
from ipfs_datasets_py.unified_web_scraper import scrape_url

result = scrape_url(url)
# Automatically tries 9 methods until one works!
```

## The 9 Methods (Automatic Fallback)

When you call `scrape_url()`, it automatically tries these methods in order:

1. **Playwright** - Full browser, JavaScript rendering (best for SPAs)
2. **BeautifulSoup** - Fast HTML parsing (best for static sites)
3. **Wayback Machine** - Internet Archive historical snapshots
4. **Archive.is** - Permanent webpage snapshots
5. **Common Crawl** - Large-scale web archive
6. **IPWB** - IPFS-based web archives
7. **Newspaper3k** - Article extraction
8. **Readability** - Content extraction
9. **Requests-only** - Basic fallback

You don't need to install all of them - the scraper uses what's available!

## Three Ways to Use It

### 1. Python Package (Best for Scripts)

```python
from ipfs_datasets_py.unified_web_scraper import scrape_url, scrape_urls

# Single URL
result = scrape_url("https://example.com")

# Multiple URLs
results = scrape_urls([
    "https://example.com",
    "https://example.org",
    "https://example.net"
])

for result in results:
    if result.success:
        print(f"✓ {result.url}")
```

### 2. Command Line (Best for Manual Tasks)

```bash
# Scrape one URL
python -m ipfs_datasets_py.scraper_cli scrape https://example.com

# Scrape multiple URLs
python -m ipfs_datasets_py.scraper_cli scrape-multiple \
    https://example.com https://example.org

# Scrape URLs from a file
echo "https://example.com" > urls.txt
echo "https://example.org" >> urls.txt
python -m ipfs_datasets_py.scraper_cli scrape-file urls.txt
```

### 3. MCP Server (Best for AI Assistants)

```python
from ipfs_datasets_py.mcp_server.tools.web_scraping_tools import scrape_url_tool

# AI assistants can use this
result = await scrape_url_tool(
    url="https://example.com",
    fallback_enabled=True
)
```

## Common Use Cases

### Use Case 1: Scraping News Articles

```python
from ipfs_datasets_py.unified_web_scraper import scrape_url

# Works with any news site - automatically uses best method
urls = [
    "https://news.example.com/article1",
    "https://news.example.com/article2",
]

for url in urls:
    result = scrape_url(url)
    if result.success:
        print(f"Title: {result.title}")
        print(f"Content: {result.content[:200]}...")
```

### Use Case 2: Extracting Links

```python
from ipfs_datasets_py.unified_web_scraper import scrape_url

result = scrape_url("https://example.com", extract_links=True)

if result.success:
    print(f"Found {len(result.links)} links:")
    for link in result.links[:10]:  # First 10 links
        print(f"  - {link['text']}: {link['url']}")
```

### Use Case 3: Scraping JavaScript-Heavy Sites

```python
from ipfs_datasets_py.unified_web_scraper import scrape_url, ScraperMethod

# Let it automatically choose (tries Playwright first)
result = scrape_url("https://spa-site.com")

# Or force Playwright specifically
result = scrape_url("https://spa-site.com", method=ScraperMethod.PLAYWRIGHT)
```

### Use Case 4: Batch Processing with Progress

```python
from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper

urls = ["https://example.com", "https://example.org", ...]  # 100 URLs

scraper = UnifiedWebScraper()
results = scraper.scrape_multiple_sync(urls, max_concurrent=5)

successful = sum(1 for r in results if r.success)
print(f"Scraped {successful}/{len(urls)} URLs successfully")
```

### Use Case 5: Saving Results

```python
from ipfs_datasets_py.unified_web_scraper import scrape_url
import json

result = scrape_url("https://example.com")

if result.success:
    # Save as JSON
    with open("result.json", "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    
    # Save as text
    with open("result.txt", "w") as f:
        f.write(f"Title: {result.title}\n\n")
        f.write(result.text)
```

## Configuration

### Basic Configuration

```python
from ipfs_datasets_py.unified_web_scraper import scrape_url, ScraperConfig

config = ScraperConfig(
    timeout=60,              # Wait up to 60 seconds
    extract_links=True,      # Extract all links
    fallback_enabled=True,   # Try multiple methods
)

scraper = UnifiedWebScraper(config)
result = scraper.scrape_sync("https://example.com")
```

### Advanced Configuration

```python
config = ScraperConfig(
    # Network settings
    timeout=90,
    follow_redirects=True,
    verify_ssl=True,
    rate_limit_delay=2.0,  # 2 seconds between requests
    
    # Extraction settings
    extract_links=True,
    extract_text=True,
    
    # Retry settings
    max_retries=5,
    retry_delay=2.0,
    
    # Browser settings (for Playwright)
    playwright_headless=True,
    playwright_wait_for="networkidle",
    
    # Custom user agent
    user_agent="MyBot/1.0"
)
```

## CLI Reference

```bash
# Check available methods
python -m ipfs_datasets_py.scraper_cli check-methods

# Scrape a single URL
python -m ipfs_datasets_py.scraper_cli scrape <url> [OPTIONS]
  --method METHOD           # Use specific method (playwright, beautifulsoup, etc.)
  --timeout SECONDS         # Request timeout
  --output FILE             # Output file
  --format FORMAT           # Output format (json, text, html)
  --no-fallback            # Disable automatic fallback
  --preview                # Show content preview

# Scrape multiple URLs
python -m ipfs_datasets_py.scraper_cli scrape-multiple <url1> <url2> ... [OPTIONS]
  --concurrent N           # Max concurrent requests (default: 5)
  --output FILE            # Output JSON file

# Scrape from file
python -m ipfs_datasets_py.scraper_cli scrape-file <file> [OPTIONS]
  # File should contain one URL per line
```

## Install Additional Methods

For full functionality, install additional scraping libraries:

```bash
# For JavaScript sites (Playwright)
pip install playwright
playwright install chromium

# For web archives (Wayback, Common Crawl)
pip install wayback cdx-toolkit

# For article extraction
pip install newspaper3k readability-lxml

# For IPFS archives
pip install ipwb
```

## Troubleshooting

### Problem: "No methods available"
**Solution:** Install basic dependencies
```bash
pip install requests beautifulsoup4
```

### Problem: JavaScript sites don't work
**Solution:** Install Playwright
```bash
pip install playwright
playwright install
```

### Problem: SSL errors
**Solution:** Disable SSL verification
```python
config = ScraperConfig(verify_ssl=False)
```

### Problem: Timeouts
**Solution:** Increase timeout
```python
config = ScraperConfig(timeout=120)  # 2 minutes
```

### Problem: Rate limiting
**Solution:** Add delays
```python
config = ScraperConfig(rate_limit_delay=3.0)  # 3 seconds between requests
```

## Best Practices

1. **Let fallback work** - Don't specify a method unless you have a good reason
2. **Use batch processing** - For multiple URLs, use `scrape_urls()` for better performance
3. **Respect rate limits** - Use `rate_limit_delay` to be nice to servers
4. **Handle errors gracefully** - Always check `result.success`
5. **Cache results** - Don't re-scrape the same URL unnecessarily

## Real-World Example

Here's a complete example that scrapes a list of URLs and saves the results:

```python
from ipfs_datasets_py.unified_web_scraper import scrape_urls, ScraperConfig
import json
from datetime import datetime

# Configuration
config = ScraperConfig(
    timeout=60,
    rate_limit_delay=2.0,
    extract_links=True
)

# URLs to scrape
urls = [
    "https://news.example.com/article1",
    "https://news.example.com/article2",
    "https://blog.example.org/post1",
]

# Scrape
print(f"Scraping {len(urls)} URLs...")
results = scrape_urls(urls)

# Process results
successful = []
failed = []

for result in results:
    if result.success:
        successful.append({
            'url': result.url,
            'title': result.title,
            'content': result.content,
            'method': result.method_used.value,
            'links_count': len(result.links),
            'timestamp': result.timestamp
        })
    else:
        failed.append({
            'url': result.url,
            'errors': result.errors
        })

# Save results
output = {
    'scraped_at': datetime.now().isoformat(),
    'total_urls': len(urls),
    'successful': len(successful),
    'failed': len(failed),
    'results': successful,
    'errors': failed
}

with open('scraping_results.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f"\n✓ Scraped {len(successful)}/{len(urls)} URLs successfully")
print(f"✓ Results saved to scraping_results.json")

# Print summary
for result in successful:
    print(f"\n{result['title']}")
    print(f"  URL: {result['url']}")
    print(f"  Method: {result['method']}")
    print(f"  Content: {len(result['content'])} chars")
```

## Next Steps

1. Read the full documentation: `UNIFIED_SCRAPER_README.md`
2. Check the migration guide: `UNIFIED_SCRAPER_IMPLEMENTATION.md`
3. Run the test suite: `python test_unified_scraper.py`
4. Try the examples: `python examples/unified_scraper_migration.py`

## Support

For issues or questions:
- Check the documentation in `UNIFIED_SCRAPER_README.md`
- Run `python -m ipfs_datasets_py.scraper_cli check-methods` to verify setup
- Look at examples in `examples/unified_scraper_migration.py`

---

**That's it!** You're now ready to scrape any website with automatic fallback mechanisms. 🎉

#!/usr/bin/env python3
"""
Migration Examples for Unified Web Scraper

This script shows how to migrate from existing scraping code to the unified scraper.
"""

print("="*80)
print("UNIFIED WEB SCRAPER - Migration Examples")
print("="*80)

# Example 1: Migrating from BeautifulSoup + Requests
print("\n" + "="*80)
print("Example 1: Migrating from BeautifulSoup + Requests")
print("="*80)

print("\n### Before (manual implementation):")
print("""
import requests
from bs4 import BeautifulSoup

url = "https://example.com"
response = requests.get(url)
soup = BeautifulSoup(response.content, 'html.parser')
title = soup.find('title').get_text()
text = soup.get_text()

print(f"Title: {title}")
print(f"Content: {text[:100]}...")
""")

print("\n### After (unified scraper):")
print("""
from ipfs_datasets_py import scrape_url

result = scrape_url("https://example.com")
print(f"Title: {result.title}")
print(f"Content: {result.content[:100]}...")
print(f"Method used: {result.method_used.value}")
# Automatically tries multiple methods if BeautifulSoup fails!
""")

# Actually run the unified scraper version
print("\n### Running unified scraper version:")
try:
    from ipfs_datasets_py import scrape_url
    
    result = scrape_url("http://example.com")
    if result.success:
        print(f"✓ Title: {result.title}")
        print(f"✓ Content: {result.content[:100]}...")
        print(f"✓ Method used: {result.method_used.value}")
        print(f"✓ Links found: {len(result.links)}")
    else:
        print(f"✗ Failed: {result.errors}")
except Exception as e:
    print(f"✗ Error: {e}")


# Example 2: Migrating from Playwright
print("\n" + "="*80)
print("Example 2: Migrating from Playwright")
print("="*80)

print("\n### Before (manual Playwright):")
print("""
from playwright.async_api import async_playwright

async def scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://example.com")
        content = await page.content()
        await browser.close()
        return content

content = asyncio.run(scrape())
""")

print("\n### After (unified scraper):")
print("""
from ipfs_datasets_py import scrape_url, ScraperMethod

# Try Playwright specifically
result = scrape_url("https://example.com", method=ScraperMethod.PLAYWRIGHT)

# Or let it automatically choose (tries Playwright first)
result = scrape_url("https://example.com")
# Falls back to BeautifulSoup if Playwright not available
""")


# Example 3: Migrating MCP Tools
print("\n" + "="*80)
print("Example 3: Migrating MCP Tools")
print("="*80)

print("\n### Before (separate MCP tool implementations):")
print("""
# Old: Multiple separate tool files
async def scrape_with_beautifulsoup_tool(url: str):
    import requests
    from bs4 import BeautifulSoup
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    return {"text": soup.get_text()}

async def scrape_with_playwright_tool(url: str):
    from playwright.async_api import async_playwright
    # ... complex Playwright code ...
    
async def scrape_with_wayback_tool(url: str):
    from wayback import WaybackClient
    # ... complex Wayback code ...
""")

print("\n### After (single unified MCP tool):")
print("""
from ipfs_datasets_py.mcp_server.tools.web_scraping_tools import scrape_url_tool

# One tool, tries all methods automatically
result = await scrape_url_tool(
    url="https://example.com",
    fallback_enabled=True  # Tries Playwright → BeautifulSoup → Wayback → ...
)
""")


# Example 4: Migrating CLI Usage
print("\n" + "="*80)
print("Example 4: Migrating CLI Usage")
print("="*80)

print("\n### Before (no dedicated CLI):")
print("""
# Had to write custom Python scripts for each scraping task
python my_custom_scraper.py https://example.com

# Or use curl + parsing
curl https://example.com | python -m html2text
""")

print("\n### After (unified CLI):")
print("""
# Scrape with automatic fallback
python -m ipfs_datasets_py.scraper_cli scrape https://example.com

# Save to JSON
python -m ipfs_datasets_py.scraper_cli scrape https://example.com \\
    --output result.json --format json

# Scrape multiple URLs
python -m ipfs_datasets_py.scraper_cli scrape-multiple \\
    https://example.com https://example.org

# Check available methods
python -m ipfs_datasets_py.scraper_cli check-methods
""")

print("\n### Running CLI check-methods:")
import subprocess
try:
    result = subprocess.run(
        ["python", "-m", "ipfs_datasets_py.scraper_cli", "check-methods"],
        capture_output=True,
        text=True,
        timeout=10
    )
    print(result.stdout)
except Exception as e:
    print(f"Could not run CLI: {e}")


# Example 5: Batch Processing
print("\n" + "="*80)
print("Example 5: Batch Processing Multiple URLs")
print("="*80)

print("\n### Before (manual loop with error handling):")
print("""
urls = ["https://example.com", "https://example.org", "https://example.net"]
results = []

for url in urls:
    try:
        response = requests.get(url, timeout=30)
        soup = BeautifulSoup(response.content, 'html.parser')
        results.append({
            'url': url,
            'success': True,
            'text': soup.get_text()
        })
    except Exception as e:
        results.append({
            'url': url,
            'success': False,
            'error': str(e)
        })
""")

print("\n### After (built-in batch processing):")
print("""
from ipfs_datasets_py import scrape_urls

urls = ["https://example.com", "https://example.org", "https://example.net"]
results = scrape_urls(urls)

for result in results:
    if result.success:
        print(f"✓ {result.url} - {result.method_used.value}")
    else:
        print(f"✗ {result.url} - {result.errors[0]}")
""")

print("\n### Running batch scraping:")
try:
    from ipfs_datasets_py import scrape_urls
    
    urls = ["http://example.com", "http://example.org"]
    results = scrape_urls(urls)
    
    for result in results:
        if result.success:
            print(f"✓ {result.url} - {result.method_used.value} - {len(result.content)} chars")
        else:
            print(f"✗ {result.url} - {result.errors[0]}")
except Exception as e:
    print(f"✗ Error: {e}")


# Summary
print("\n" + "="*80)
print("SUMMARY: Benefits of Unified Scraper")
print("="*80)

print("""
1. ✅ Automatic Fallback
   - No need to manually try different methods
   - Automatically uses best available method

2. ✅ Consistent Interface
   - Same API for package imports, CLI, and MCP tools
   - Predictable behavior across all use cases

3. ✅ Better Error Handling
   - Graceful degradation when methods fail
   - Comprehensive error messages

4. ✅ Less Code to Write
   - No need to implement error handling for each method
   - Built-in batch processing

5. ✅ Better Maintenance
   - Single place to update scraping logic
   - Easier to add new methods

6. ✅ More Reliable
   - Falls back to 9 different methods
   - Works even when some libraries are missing
""")

print("\n" + "="*80)
print("To get started:")
print("="*80)
print("""
# Install dependencies
pip install requests beautifulsoup4

# For full functionality
pip install playwright wayback cdx-toolkit newspaper3k readability-lxml
playwright install

# Try it out
python -m ipfs_datasets_py.scraper_cli scrape https://example.com

# Or in Python
from ipfs_datasets_py import scrape_url
result = scrape_url("https://example.com")
""")

print("\n✨ Migration complete! The unified scraper is ready to use.")

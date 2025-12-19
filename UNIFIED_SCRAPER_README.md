# Unified Web Scraper System

A comprehensive web scraping system with intelligent fallback mechanisms that automatically tries multiple scraping methods until successful.

## Features

- **Automatic Fallback**: Tries multiple scraping methods in sequence until one succeeds
- **9 Scraping Methods**: Playwright, BeautifulSoup, Wayback Machine, Archive.is, Common Crawl, IPWB, Newspaper3k, Readability, Requests-only
- **Three Access Methods**: MCP Tools, CLI, and Python Package Import
- **Concurrent Scraping**: Scrape multiple URLs in parallel
- **Link Extraction**: Automatically extract all links from pages
- **Text Extraction**: Clean text content extraction with HTML tag removal
- **Metadata Preservation**: Preserve scraping method, timestamps, and source information

## Installation

### Basic Installation
```bash
pip install requests beautifulsoup4
```

### Full Installation (All Methods)
```bash
# Install all scraping libraries
pip install requests beautifulsoup4 playwright wayback cdx-toolkit
pip install ipwb newspaper3k readability-lxml

# Install Playwright browsers
playwright install
```

## Usage

### 1. Python Package Import

```python
from ipfs_datasets_py import scrape_url, scrape_urls, UnifiedWebScraper, ScraperConfig

# Simple scraping with automatic fallback
result = scrape_url("https://example.com")
if result.success:
    print(f"Title: {result.title}")
    print(f"Content: {result.content}")
    print(f"Method used: {result.method_used.value}")
    print(f"Links found: {len(result.links)}")

# Scrape with specific method
from ipfs_datasets_py import ScraperMethod
result = scrape_url("https://example.com", method=ScraperMethod.PLAYWRIGHT)

# Scrape multiple URLs
results = scrape_urls([
    "https://example.com",
    "https://example.org",
    "https://example.net"
])

for result in results:
    if result.success:
        print(f"✓ {result.url} - {result.method_used.value}")
    else:
        print(f"✗ {result.url} - {result.errors[0]}")

# Advanced usage with custom config
config = ScraperConfig(
    timeout=60,
    extract_links=True,
    extract_text=True,
    fallback_enabled=True,
    playwright_headless=True,
    rate_limit_delay=2.0,
    max_retries=3
)

scraper = UnifiedWebScraper(config)
result = scraper.scrape_sync("https://example.com")

# Async usage
import asyncio

async def scrape_async():
    scraper = UnifiedWebScraper()
    result = await scraper.scrape("https://example.com")
    return result

result = asyncio.run(scrape_async())
```

### 2. Command-Line Interface (CLI)

```bash
# Scrape a single URL with automatic fallback
python -m ipfs_datasets_py.scraper_cli scrape https://example.com

# Scrape with specific method
python -m ipfs_datasets_py.scraper_cli scrape https://example.com --method playwright

# Save output to file
python -m ipfs_datasets_py.scraper_cli scrape https://example.com \
    --output result.json --format json

python -m ipfs_datasets_py.scraper_cli scrape https://example.com \
    --output result.txt --format text

# Scrape multiple URLs
python -m ipfs_datasets_py.scraper_cli scrape-multiple \
    https://example.com https://example.org https://example.net \
    --output results.json

# Scrape URLs from a file
echo "https://example.com" > urls.txt
echo "https://example.org" >> urls.txt
python -m ipfs_datasets_py.scraper_cli scrape-file urls.txt --output results.json

# Check available methods
python -m ipfs_datasets_py.scraper_cli check-methods

# Disable fallback (use only first available method)
python -m ipfs_datasets_py.scraper_cli scrape https://example.com --no-fallback

# Show content preview
python -m ipfs_datasets_py.scraper_cli scrape https://example.com --preview
```

### 3. MCP Server Tools

The unified scraper is exposed through the MCP server for AI assistant integration:

```python
from ipfs_datasets_py.mcp_server.tools.web_scraping_tools import (
    scrape_url_tool,
    scrape_multiple_urls_tool,
    check_scraper_methods_tool
)

# Scrape a URL
result = await scrape_url_tool(
    url="https://example.com",
    method="playwright",  # Optional
    timeout=30,
    extract_links=True,
    extract_text=True,
    fallback_enabled=True
)

# Scrape multiple URLs
result = await scrape_multiple_urls_tool(
    urls=["https://example.com", "https://example.org"],
    max_concurrent=5,
    fallback_enabled=True
)

# Check available methods
result = await check_scraper_methods_tool()
print(result['available_methods'])
print(result['fallback_sequence'])
```

## Scraping Methods

The scraper tries methods in this order until one succeeds:

### 1. Playwright
- **Best for**: JavaScript-heavy sites, SPAs, dynamic content
- **Pros**: Full browser rendering, JavaScript execution
- **Cons**: Slower, requires browser installation
- **Install**: `pip install playwright && playwright install`

### 2. BeautifulSoup + Requests
- **Best for**: Static HTML pages, fast scraping
- **Pros**: Fast, lightweight, reliable
- **Cons**: No JavaScript support
- **Install**: `pip install beautifulsoup4 requests`

### 3. Wayback Machine
- **Best for**: Historical content, archived pages
- **Pros**: Access to historical snapshots
- **Cons**: May not have recent content
- **Install**: `pip install wayback`

### 4. Archive.is
- **Best for**: Permanent snapshots, bypassing blocks
- **Pros**: Permanent archives, good coverage
- **Cons**: May not have all pages
- **Install**: `pip install requests`

### 5. Common Crawl
- **Best for**: Large-scale web archives
- **Pros**: Massive dataset, good for research
- **Cons**: Not real-time, metadata only by default
- **Install**: `pip install cdx-toolkit`

### 6. IPWB (InterPlanetary Wayback)
- **Best for**: IPFS-based archives
- **Pros**: Decentralized, IPFS integration
- **Cons**: Requires local CDXJ index
- **Install**: `pip install ipwb`

### 7. Newspaper3k
- **Best for**: News articles, blog posts
- **Pros**: Automatic article extraction
- **Cons**: Limited to article-like content
- **Install**: `pip install newspaper3k`

### 8. Readability
- **Best for**: Content extraction, removing clutter
- **Pros**: Clean content extraction
- **Cons**: May miss some content
- **Install**: `pip install readability-lxml`

### 9. Requests-only
- **Best for**: Basic fallback
- **Pros**: Always available (if requests installed)
- **Cons**: Basic text extraction only
- **Install**: `pip install requests`

## Configuration Options

```python
from ipfs_datasets_py import ScraperConfig, ScraperMethod

config = ScraperConfig(
    # Timeout and retry settings
    timeout=30,                    # Request timeout in seconds
    max_retries=3,                 # Max retry attempts
    retry_delay=1.0,               # Delay between retries
    
    # Content extraction
    extract_links=True,            # Extract links from pages
    extract_text=True,             # Extract text content
    
    # Network settings
    follow_redirects=True,         # Follow HTTP redirects
    verify_ssl=True,               # Verify SSL certificates
    rate_limit_delay=1.0,          # Delay between requests
    user_agent="Custom-Agent/1.0", # Custom user agent
    
    # Playwright settings
    playwright_headless=True,      # Run browser in headless mode
    playwright_wait_for="networkidle", # Wait condition
    
    # Fallback settings
    fallback_enabled=True,         # Enable automatic fallback
    preferred_methods=[            # Custom method order
        ScraperMethod.PLAYWRIGHT,
        ScraperMethod.BEAUTIFULSOUP,
        ScraperMethod.WAYBACK_MACHINE
    ]
)
```

## Result Format

All scraping methods return a `ScraperResult` object:

```python
@dataclass
class ScraperResult:
    url: str                        # Original URL
    content: str                    # Extracted text content
    html: str                       # Raw HTML content
    title: str                      # Page title
    text: str                       # Clean text (same as content)
    links: List[Dict[str, str]]     # Extracted links
    metadata: Dict[str, Any]        # Additional metadata
    method_used: ScraperMethod      # Method that succeeded
    success: bool                   # Whether scraping succeeded
    errors: List[str]               # Error messages if failed
    timestamp: str                  # ISO timestamp
    extraction_time: float          # Time taken in seconds
```

## Error Handling

The scraper automatically handles errors and tries fallback methods:

```python
result = scrape_url("https://example.com")

if result.success:
    print(f"Success! Used {result.method_used.value}")
    print(f"Content: {result.content}")
else:
    print("All methods failed:")
    for error in result.errors:
        print(f"  - {error}")
```

## Performance Tips

1. **Use specific methods when possible**: If you know the site works with BeautifulSoup, specify it
2. **Disable fallback for speed**: Use `fallback_enabled=False` when you trust your primary method
3. **Batch scraping**: Use `scrape_multiple_urls_tool` for better concurrency
4. **Rate limiting**: Respect servers with `rate_limit_delay`
5. **Caching**: Consider caching results to avoid re-scraping

## Integration with Existing Code

### Replacing Individual Scrapers

**Before (separate scrapers):**
```python
from bs4 import BeautifulSoup
import requests

response = requests.get("https://example.com")
soup = BeautifulSoup(response.content, 'html.parser')
text = soup.get_text()
```

**After (unified scraper):**
```python
from ipfs_datasets_py import scrape_url

result = scrape_url("https://example.com")
text = result.text
# Automatically tries multiple methods if BeautifulSoup fails
```

### Updating MCP Tools

**Before (MCP tool with single method):**
```python
async def scrape_tool(url: str) -> Dict:
    import requests
    from bs4 import BeautifulSoup
    
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    return {"text": soup.get_text()}
```

**After (unified scraper in MCP tool):**
```python
from ipfs_datasets_py.mcp_server.tools.web_scraping_tools import scrape_url_tool

async def scrape_tool(url: str) -> Dict:
    return await scrape_url_tool(url)
    # Automatically tries 9 methods with fallback
```

## Examples

See the `examples/` directory for complete examples:

- `basic_scraping.py` - Simple scraping examples
- `advanced_config.py` - Custom configuration
- `batch_scraping.py` - Scraping multiple URLs
- `method_comparison.py` - Comparing different methods
- `mcp_integration.py` - Using with MCP server

## Troubleshooting

### No methods available
```bash
pip install requests beautifulsoup4 playwright
playwright install
```

### Playwright fails
```bash
playwright install chromium
# Or use a different method
result = scrape_url(url, method=ScraperMethod.BEAUTIFULSOUP)
```

### SSL errors
```python
config = ScraperConfig(verify_ssl=False)
scraper = UnifiedWebScraper(config)
```

### Timeout issues
```python
config = ScraperConfig(timeout=60, max_retries=5)
scraper = UnifiedWebScraper(config)
```

## Architecture

```
┌─────────────────────────────────────────┐
│        User Application/CLI/MCP         │
└─────────────┬───────────────────────────┘
              │
              v
┌─────────────────────────────────────────┐
│       UnifiedWebScraper                 │
│  ┌───────────────────────────────────┐  │
│  │  Automatic Fallback System        │  │
│  │  - Try each method in order       │  │
│  │  - Return first successful result │  │
│  └───────────────────────────────────┘  │
└─────────────┬───────────────────────────┘
              │
    ┌─────────┴─────────┬──────────┬───────...
    v                   v          v
┌─────────┐     ┌─────────────┐  ┌────────────┐
│Playwright│     │BeautifulSoup│  │  Wayback   │
└─────────┘     └─────────────┘  │  Machine   │
                                 └────────────┘
    ... and 6 more methods
```

## Contributing

Contributions are welcome! To add a new scraping method:

1. Add the method to `ScraperMethod` enum
2. Implement `_scrape_<method>` in `UnifiedWebScraper`
3. Add dependency check in `_check_dependencies`
4. Update documentation

## License

See LICENSE file for details.

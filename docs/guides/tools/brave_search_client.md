# Brave Search Client - Improved Implementation

## Overview

The Brave Search client has been extracted and improved from the `common_crawl_search_engine` submodule to make it available to all web archiving tools in `ipfs_datasets_py`, not just Common Crawl integration.

## Key Improvements

### 1. Disk-Based Caching with TTL

The new implementation includes intelligent caching with:
- **Automatic caching** of search results to disk
- **TTL (Time-To-Live)** support with configurable expiration (default: 24 hours)
- **LRU eviction** when cache reaches maximum size
- **File locking** for concurrent access safety (using `fcntl` on Unix systems)

### 2. Pagination Metadata

The `brave_web_search_page()` function returns pagination metadata:
- Total number of results (when available from API)
- Maximum results per request
- Current count and offset
- Cache status and age

### 3. Better Configuration

Environment variables for fine-grained control:
- `BRAVE_SEARCH_API_KEY` or `BRAVE_API_KEY` - API key
- `BRAVE_SEARCH_CACHE_DISABLE` - Disable caching (1/true/yes/on)
- `BRAVE_SEARCH_CACHE_TTL_S` - Cache TTL in seconds (default: 86400)
- `BRAVE_SEARCH_CACHE_MAX_ENTRIES` - Max cache entries (default: 1000)
- `BRAVE_SEARCH_CACHE_PATH` - Custom cache file path
- `BRAVE_SEARCH_MAX_COUNT` - Max results per request (default: 20)

### 4. Cache Management Functions

- `brave_search_cache_stats()` - Get cache statistics
- `clear_brave_search_cache()` - Clear the cache
- `brave_search_cache_path()` - Get cache file path

## Usage

### Python Package API

```python
from ipfs_datasets_py.processors.web_archiving import BraveSearchClient

# Initialize client
client = BraveSearchClient(api_key="your-api-key")

# Simple search
results = client.search("python programming", count=20)
for result in results:
    print(f"{result['title']}: {result['url']}")

# Search with pagination metadata
page = client.search_page("data science", count=10, offset=20)
print(f"Total results: {page['meta']['total']}")
print(f"Showing {len(page['items'])} results from offset {page['meta']['offset']}")
print(f"Cached: {page['meta']['cached']}")

# Get cache statistics
stats = client.cache_stats()
print(f"Cache entries: {stats['entries']}")
print(f"Cache size: {stats['bytes']} bytes")

# Clear cache
result = client.clear_cache()
print(f"Cleared {result['freed_bytes']} bytes")

# Configure client
client.configure(country="uk", safesearch="strict", default_count=20)
```

### Direct Function API

```python
from ipfs_datasets_py.processors.web_archiving import (
    brave_web_search,
    brave_web_search_page,
    brave_search_cache_stats,
    clear_brave_search_cache
)

# Synchronous search with caching
results = brave_web_search(
    query="machine learning",
    api_key="your-api-key",  # or set BRAVE_SEARCH_API_KEY env var
    count=10,
    offset=0,
    country="us",
    safesearch="moderate"
)

# Search with pagination
page = brave_web_search_page(
    query="artificial intelligence",
    count=20,
    offset=0
)

# Cache management
stats = brave_search_cache_stats()
print(f"Cache: {stats['entries']} entries, {stats['bytes']} bytes")

result = clear_brave_search_cache()
print(f"Freed: {result['freed_bytes']} bytes")
```

### MCP Tools

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
    search_brave,
    search_brave_news,
    search_brave_images,
    get_brave_cache_stats,
    clear_brave_cache
)

# Async search (uses aiohttp)
result = await search_brave(
    query="web development",
    count=15,
    safesearch="moderate"
)

# Get cache stats via MCP
stats = await get_brave_cache_stats()
print(f"Status: {stats['status']}")
if stats['status'] == 'success':
    print(f"Cache entries: {stats['entries']}")

# Clear cache via MCP
result = await clear_brave_cache()
print(f"Cleared: {result.get('freed_bytes', 0)} bytes")
```

### Using with Other Web Archiving Tools

The Brave Search client is now available to all web archiving tools:

```python
# In your custom web scraping tool
from ipfs_datasets_py.processors.web_archiving import BraveSearchClient

class MyWebScraper:
    def __init__(self):
        self.search_client = BraveSearchClient()
    
    def find_related_content(self, topic):
        # Use Brave Search to find related URLs
        results = self.search_client.search(topic, count=20)
        urls = [r['url'] for r in results]
        
        # Then scrape the discovered URLs
        return self.scrape_urls(urls)
```

## Architecture

### File Locations

- **Core Client**: `ipfs_datasets_py/web_archiving/brave_search_client.py`
  - Standalone module with sync functions and BraveSearchClient class
  - Can be used independently of MCP tools
  
- **MCP Tools**: `ipfs_datasets_py/mcp_server/tools/web_archive_tools/brave_search.py`
  - Async wrappers for MCP protocol
  - Backward-compatible BraveSearchAPI class
  - Now uses brave_search_client under the hood when available

### Caching Architecture

```
User Request
    ↓
brave_web_search()
    ↓
Check Cache (with file lock)
    ↓
Cache Hit? → Return cached results
    ↓ No
API Request → Brave Search API
    ↓
Parse Results
    ↓
Save to Cache (with LRU eviction)
    ↓
Return Results
```

### Cache File Format

The cache is stored as JSON:

```json
{
  "sha256_hash_of_query_params": {
    "ts": 1706789123.456,
    "items": [
      {"title": "...", "url": "...", "description": "..."}
    ],
    "meta": {
      "total": 1500
    }
  }
}
```

## Configuration Examples

### Disable Caching

```bash
export BRAVE_SEARCH_CACHE_DISABLE=1
```

### Custom Cache Location

```bash
export BRAVE_SEARCH_CACHE_PATH=/var/cache/brave_search.json
```

### Short TTL for Testing

```bash
export BRAVE_SEARCH_CACHE_TTL_S=300  # 5 minutes
```

### Larger Cache

```bash
export BRAVE_SEARCH_CACHE_MAX_ENTRIES=5000
```

## Testing

Run the integration tests:

```bash
pytest tests/integration/test_brave_search_client.py -v
```

Tests cover:
- Import verification
- Client initialization and configuration
- Cache management functions
- MCP tool integration
- Environment variable handling

## Benefits

1. **Performance**: Cached results avoid redundant API calls
2. **Cost Savings**: Reduces API usage and associated costs
3. **Reliability**: Works even if API is temporarily unavailable (for cached queries)
4. **Flexibility**: Can be used by any web archiving tool, not just Common Crawl
5. **Safety**: File locking prevents cache corruption in concurrent scenarios
6. **Observability**: Cache statistics help monitor usage patterns

## Backward Compatibility

The existing MCP tools (`search_brave`, `search_brave_news`, `search_brave_images`) continue to work as before. The `BraveSearchAPI` class maintains its interface but now benefits from caching when `requests` library is installed.

## Migration from Old Implementation

If you were using the old `brave_search.py` directly:

**Before:**
```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import BraveSearchAPI

api = BraveSearchAPI(api_key="key")
# No caching, no pagination metadata
```

**After:**
```python
from ipfs_datasets_py.processors.web_archiving import BraveSearchClient

client = BraveSearchClient(api_key="key")
# Now with caching and pagination metadata
results = client.search("query")
stats = client.cache_stats()  # New feature
```

## Source

This implementation is extracted from the `common_crawl_search_engine` submodule:
- Source: `ccsearch/brave_search.py`
- Improvements: Added class wrapper, MCP integration, better documentation
- License: Same as parent project (MIT)

# Legal Scrapers - Multi-Interface Architecture

A unified package for scraping legal data from various sources with support for **three interfaces**: Python package, CLI tools, and MCP server.

## 🎯 Features

- ✅ **Content Addressing** - Every scrape gets unique CID
- ✅ **Automatic Deduplication** - By URL and content CID
- ✅ **Version Tracking** - Track content changes over time
- ✅ **WARC Import/Export** - Standard web archive format
- ✅ **Common Crawl Integration** - Access historical data
- ✅ **Batch Scraping** - Efficient concurrent requests
- ✅ **Multiple Interfaces** - Package, CLI, and MCP

## 📦 Installation

```bash
# Install the package
pip install -e ./legal_scrapers

# Or install with all dependencies
pip install -e "./legal_scrapers[all]"
```

## 🚀 Usage

### 1. Python Package Import

```python
from legal_scrapers import MunicodeScraper

# Initialize scraper
scraper = MunicodeScraper(
    enable_ipfs=True,
    check_archives=True
)

# Async scraping
result = await scraper.scrape("https://library.municode.com/wa/seattle")
print(f"Content CID: {result['content_cid']}")
print(f"Sections found: {result['section_count']}")

# Or use sync wrapper
from legal_scrapers import scrape_municode
result = scrape_municode("https://library.municode.com/wa/seattle")
```

### 2. Command Line Interface

```bash
# Scrape single jurisdiction
python -m legal_scrapers.cli.municode_cli \
    https://library.municode.com/wa/seattle \
    --output seattle.json \
    --enable-ipfs

# Batch scraping
python -m legal_scrapers.cli.municode_cli \
    --batch jurisdictions.txt \
    --output-dir ./scraped \
    --max-concurrent 10

# Import from Common Crawl
python -m legal_scrapers.cli.municode_cli \
    --import-warc "library.municode.com/*" \
    --index CC-MAIN-2025-47 \
    --max-records 100 \
    --enable-warc
```

### 3. MCP Server (Model Context Protocol)

```bash
# Start MCP server
python -m legal_scrapers.mcp.server
```

**MCP Client Usage:**

```python
import mcp

# Connect to server
client = mcp.Client("legal-scrapers")

# Call tool
result = await client.call_tool("scrape_municode_jurisdiction", {
    "jurisdiction_url": "https://library.municode.com/wa/seattle",
    "enable_ipfs": True,
    "check_archives": True
})

print(result)
```

## 📚 Available Scrapers

### Municode Scraper

Scrapes municipal codes from library.municode.com (3,500+ jurisdictions).

**Package:**
```python
from legal_scrapers import MunicodeScraper
scraper = MunicodeScraper()
result = await scraper.scrape("https://library.municode.com/wa/seattle")
```

**CLI:**
```bash
python -m legal_scrapers.cli.municode_cli <url> [options]
```

**MCP Tools:**
- `scrape_municode_jurisdiction` - Scrape single jurisdiction
- `batch_scrape_municode` - Batch scrape multiple jurisdictions
- `import_municode_from_commoncrawl` - Import from Common Crawl
- `get_municode_statistics` - Get scraping statistics

### Coming Soon

- State Laws Scraper
- Federal Register Scraper
- US Code Scraper
- RECAP Scraper
- eCode360 Scraper
- American Legal Scraper

## 🔧 API Reference

### BaseLegalScraper

Base class for all legal scrapers.

```python
class BaseLegalScraper(ABC):
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        enable_ipfs: bool = False,
        enable_warc: bool = False,
        check_archives: bool = True,
        output_format: str = "json"
    )
    
    @abstractmethod
    async def scrape(target, **kwargs) -> Dict
    
    async def scrape_url_unified(url, metadata) -> Dict
    async def batch_scrape(urls, max_concurrent) -> List[Dict]
    async def import_from_common_crawl(pattern, index) -> List[Dict]
    def export_to_warc(records, filename) -> str
    def get_statistics() -> Dict
```

### MunicodeScraper

```python
class MunicodeScraper(BaseLegalScraper):
    async def scrape(
        jurisdiction_url: str,
        include_metadata: bool = True,
        extract_sections: bool = True,
        **kwargs
    ) -> Dict[str, Any]
    
    async def scrape_multiple(
        jurisdiction_urls: List[str],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[Dict[str, Any]]
```

## 📊 Output Format

```json
{
  "status": "success",
  "jurisdiction_url": "https://library.municode.com/wa/seattle",
  "jurisdiction_name": "City of Seattle",
  "state": "WA",
  "sections": [
    {
      "number": "1.04.010",
      "title": "Definitions",
      "content": "For purposes of this code..."
    }
  ],
  "section_count": 245,
  "content_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
  "metadata_cid": "bafybeif2yx...",
  "version": 1,
  "already_scraped": false,
  "changed": true,
  "scraped_at": "2025-12-20T02:30:00Z",
  "archive_results": {
    "total_captures": 15,
    "unique_versions": 3,
    "sources": ["common_crawl", "wayback_machine", "local_cache"]
  }
}
```

## 🔌 Integration

### With IPFS Datasets

```python
from legal_scrapers import MunicodeScraper
from ipfs_datasets import IPFSDataset

scraper = MunicodeScraper(enable_ipfs=True)
result = await scraper.scrape("https://library.municode.com/wa/seattle")

# Store in IPFS dataset
dataset = IPFSDataset("municipal_codes")
dataset.add(result['content'], metadata=result)
```

### With Unified Scraping System

The scrapers use the unified scraping system automatically:

```python
from legal_scrapers import MunicodeScraper

scraper = MunicodeScraper(
    check_archives=True,  # Check Common Crawl/Wayback first
    enable_warc=True      # Enable WARC import/export
)

result = await scraper.scrape(url)
# Automatically:
# 1. Checks if URL already scraped
# 2. Searches Common Crawl for historical versions
# 3. Computes content CID
# 4. Tracks versions
# 5. Stores with deduplication
```

## 🧪 Testing

```python
# Test basic scraping
from legal_scrapers import scrape_municode

result = scrape_municode("https://library.municode.com/wa/seattle")
assert result['status'] == 'success'
assert 'content_cid' in result
print("✅ Test passed!")
```

```bash
# Test CLI
python -m legal_scrapers.cli.municode_cli --help

# Test MCP server (requires MCP library)
python -m legal_scrapers.mcp.server
```

## 📁 Project Structure

```
legal_scrapers/
├── __init__.py                 # Package exports
├── README.md                   # This file
│
├── core/                       # Core scraper implementations
│   ├── __init__.py
│   ├── base_scraper.py        # Base class with unified scraping
│   └── municode.py            # Municode scraper
│
├── cli/                        # CLI interfaces
│   ├── __init__.py
│   └── municode_cli.py        # Municode CLI
│
├── mcp/                        # MCP server and tools
│   ├── __init__.py
│   ├── server.py              # MCP server
│   ├── tool_registry.py       # Tool registry
│   └── tools/
│       ├── __init__.py
│       └── municode_tools.py  # Municode MCP tools
│
└── utils/                      # Shared utilities (future)
    └── __init__.py
```

## 🤝 Contributing

To add a new scraper:

1. Create `core/scraper_name.py` inheriting from `BaseLegalScraper`
2. Create `cli/scraper_name_cli.py` for CLI interface
3. Create `mcp/tools/scraper_name_tools.py` for MCP tools
4. Register tools in `mcp/tool_registry.py`
5. Add exports to `__init__.py` files

See `LEGAL_SCRAPERS_REFACTORING_GUIDE.md` for detailed instructions.

## 📄 License

Same as parent project.

## 🔗 Related

- [Unified Scraping System](../unified_scraping_adapter.py)
- [Content Addressed Scraping](../content_addressed_scraper.py)
- [WARC Integration](../warc_integration.py)
- [Legal Scraper Unified Adapter](../legal_scraper_unified_adapter.py)

---

**Version:** 2.0.0  
**Status:** ✅ Phase 1 Complete (Municode), Phase 2 In Progress  
**Last Updated:** December 20, 2025

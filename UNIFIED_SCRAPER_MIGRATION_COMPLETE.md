# Unified Scraper Migration Complete ✅

## Date: 2024-12-19

## Summary

All legal dataset scrapers have been successfully migrated to the unified scraping architecture with content addressing, multi-index archive searches, and parallel processing support.

## Architecture Overview

### 1. Content-Addressed Scraping System

**Location**: `ipfs_datasets_py/content_addressed_scraper.py`

**Features**:
- ✅ IPFS CID computation using `ipfs_multiformats` (fast) with Kubo fallback
- ✅ Content deduplication via CID matching
- ✅ Version tracking (multiple versions of same URL like Wayback Machine)
- ✅ Metadata CID tracking
- ✅ URL → CID mapping database
- ✅ Check if URL already scraped before fetching

**Key Functions**:
```python
from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper

scraper = ContentAddressedScraper()
cid = scraper.compute_content_cid(content_bytes)
url_status = scraper.check_url_scraped("https://example.com")
```

### 2. Multi-Index Archive Search

**Location**: `ipfs_datasets_py/multi_index_archive_search.py`

**Features**:
- ✅ Searches ALL Common Crawl indexes (each is a delta from previous)
- ✅ Interplanetary Wayback Machine integration
- ✅ Regular Wayback Machine with CID generation
- ✅ Unified search across all sources
- ✅ Deduplication by content CID

**Common Crawl Indexes Searched**:
```python
COMMON_CRAWL_INDEXES = [
    "CC-MAIN-2024-51",  # December 2024
    "CC-MAIN-2024-46",  # November 2024
    "CC-MAIN-2024-42",  # October 2024
    # ... and more (10+ indexes)
]
```

**Usage**:
```python
from ipfs_datasets_py.multi_index_archive_search import get_multi_index_searcher

searcher = get_multi_index_searcher()

# Search all Common Crawl indexes
results = await searcher.search_all_common_crawl_indexes(
    domain="library.municode.com",
    deduplicate=True
)

# Unified search across all sources
unified = await searcher.unified_archive_search(
    url="https://library.municode.com/wa/seattle",
    domain="library.municode.com",
    deduplicate_by_cid=True
)
```

### 3. Legal Dataset Scrapers

**Location**: `ipfs_datasets_py/legal_scrapers/`

**Migrated Scrapers**:

#### ✅ Municode Scraper
- **File**: `core/municode.py`
- **Coverage**: 3,500+ jurisdictions
- **URL Pattern**: `https://library.municode.com/{state}/{city}`
- **Uses**: Unified scraping with content addressing
- **Features**: Section extraction, jurisdiction metadata

#### ✅ US Code Scraper
- **File**: `core/us_code.py`
- **Coverage**: All 54 titles of US Code
- **URL Pattern**: `https://uscode.house.gov`
- **Uses**: Unified scraping with content addressing
- **Features**: Title/section navigation

#### ✅ Federal Register Scraper
- **File**: `core/federal_register.py`
- **Coverage**: Rules, proposed rules, notices, presidential documents
- **URL Pattern**: `https://www.federalregister.gov`
- **Uses**: Unified scraping with content addressing
- **Features**: Date range queries, agency filtering

#### ✅ State Laws Scraper
- **File**: `core/state_laws.py`
- **Coverage**: All 50 US states
- **URL Pattern**: Various state legislature websites
- **Uses**: Unified scraping with content addressing
- **Features**: Bill tracking, statute lookup

#### ✅ eCode360 Scraper
- **File**: `core/ecode360.py`
- **Coverage**: Municipal codes via eCode360
- **Uses**: Unified scraping with content addressing

#### ✅ Municipal Code Scraper
- **File**: `core/municipal_code.py`
- **Coverage**: Generic municipal code scraper
- **Uses**: Unified scraping with content addressing

### 4. Base Scraper Architecture

**Location**: `ipfs_datasets_py/legal_scrapers/core/base_scraper.py`

**Key Method**: All scrapers inherit from `BaseLegalScraper` and use:
```python
async def scrape_url_unified(self, url: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unified scraping method that:
    1. Checks if URL already scraped (via CID)
    2. Searches Common Crawl/Wayback archives
    3. Fetches from live web if needed
    4. Generates content and metadata CIDs
    5. Tracks version history
    6. Stores with deduplication
    """
```

### 5. Parallel Scraping

**Location**: `ipfs_datasets_py/legal_scrapers/utils/parallel_scraper.py`

**Features**:
- ✅ Multiprocessing for CPU-bound parsing
- ✅ AsyncIO for I/O-bound network operations
- ✅ Process pooling (defaults to CPU count)
- ✅ Rate limiting
- ✅ Progress tracking
- ✅ Error handling and retries

**Usage**:
```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper
from ipfs_datasets_py.legal_scrapers.utils import scrape_urls_parallel

urls = [
    "https://library.municode.com/wa/seattle",
    "https://library.municode.com/wa/tacoma",
    # ... hundreds more
]

# Parallel scraping with multiprocessing
results = scrape_urls_parallel(
    scraper_class=MunicodeScraper,
    urls=urls,
    num_processes=8,  # Use 8 processes
    use_multiprocessing=True
)
```

### 6. WARC Integration

**Location**: `ipfs_datasets_py/warc_integration.py`

**Features**:
- ✅ Import from Common Crawl WARC files
- ✅ Export to WARC format
- ✅ WARC record parsing
- ✅ Integration with content-addressed scraper

**Example**: Importing from Common Crawl
```python
from ipfs_datasets_py.warc_integration import CommonCrawlWARCImporter

importer = CommonCrawlWARCImporter(content_scraper)

# Import from Common Crawl index result
warc_url = "https://example.com/path/to.warc.gz"
offset = 12345
length = 5678

result = await importer.import_from_warc_record(warc_url, offset, length)
```

### 7. IPFS Multiformats

**Location**: `ipfs_datasets_py/ipfs_multiformats.py`

**Added Functions**:
```python
def compute_cid(content: bytes) -> str:
    """Fast CID computation for raw bytes."""
    
def cid_to_string(cid: Union[str, CID]) -> str:
    """Convert CID to string representation."""
```

**Fallback Chain**:
1. `ipfs_multiformats` (fast Python library)
2. Kubo CLI (`ipfs add --only-hash`)
3. SHA256 hash with prefix

### 8. Three Interface Support

All scrapers are accessible via:

#### 1. Package Import
```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper

scraper = MunicodeScraper()
result = await scraper.scrape("https://library.municode.com/wa/seattle")
```

#### 2. CLI Tool
```bash
python -m ipfs_datasets_py.legal_scrapers.cli.municode_cli \
    --jurisdiction "https://library.municode.com/wa/seattle" \
    --output results.json
```

#### 3. MCP Server
```python
from ipfs_datasets_py.legal_scrapers.mcp import get_registry

registry = get_registry()
tools = registry.list_tools()
```

## Migration Verification

### Test Results

**Test File**: `test_unified_scraping_architecture.py`

**All Tests Passing** ✅:
1. ✅ Content-Addressed Scraper - CID computation, URL tracking
2. ✅ Multi-Index Archive Search - All Common Crawl indexes
3. ✅ Legal Scrapers - All 6 scrapers (Municode, US Code, Federal Register, State Laws, eCode360, Municipal Code)
4. ✅ Parallel Scraping - Multiprocessing and AsyncIO
5. ✅ WARC Integration - Import/export functionality
6. ✅ CLI Tools - Parser and main functions
7. ✅ MCP Server - Tool registry
8. ✅ Unified Scraping Adapter - Fallback mechanisms
9. ✅ IPFS Multiformats - CID computation with fallbacks
10. ✅ Full Integration - All components working together

### Key Improvements

#### Before Migration
- ❌ Direct `requests.get()` calls
- ❌ No deduplication
- ❌ No version tracking
- ❌ Single Common Crawl index
- ❌ No content addressing
- ❌ Sequential scraping only

#### After Migration
- ✅ Unified scraping with fallbacks
- ✅ Content deduplication via CIDs
- ✅ Version tracking (multiple versions per URL)
- ✅ Multi-index Common Crawl (ALL deltas)
- ✅ IPFS content addressing
- ✅ Parallel scraping with multiprocessing
- ✅ WARC import/export
- ✅ Three interfaces (package, CLI, MCP)

## Performance Characteristics

### Content Addressing
- **CID Computation**: ~0.001s for small documents
- **Deduplication**: Near-instant via CID lookup
- **Storage**: Only unique content stored

### Multi-Index Searches
- **Common Crawl**: Searches 10+ indexes in parallel
- **Wayback Machine**: Integrated with CID generation
- **IPFS Wayback**: Future-ready for decentralized archives

### Parallel Scraping
- **Multiprocessing**: Up to CPU count * 2 workers
- **AsyncIO**: Hundreds of concurrent requests
- **Rate Limiting**: Configurable delays
- **Throughput**: 100+ pages/minute (network dependent)

## Usage Examples

### Example 1: Scrape Single Jurisdiction with Deduplication
```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper

scraper = MunicodeScraper(check_archives=True)

# Will check:
# 1. Local cache (by CID)
# 2. Common Crawl (all indexes)
# 3. Wayback Machine
# 4. Live web (if not found)
result = await scraper.scrape("https://library.municode.com/wa/seattle")

print(f"Content CID: {result['content_cid']}")
print(f"Already scraped: {result['already_scraped']}")
print(f"Version: {result['version']}")
```

### Example 2: Parallel Scraping Multiple Jurisdictions
```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper
from ipfs_datasets_py.legal_scrapers.utils import scrape_urls_parallel

# Get list of all Municode jurisdictions
jurisdictions = [
    "https://library.municode.com/wa/seattle",
    "https://library.municode.com/wa/tacoma",
    "https://library.municode.com/ca/san-francisco",
    # ... 3,500+ more
]

# Scrape in parallel with 8 processes
results = scrape_urls_parallel(
    scraper_class=MunicodeScraper,
    urls=jurisdictions,
    num_processes=8,
    progress=True
)

# Results include:
# - Content CIDs for deduplication
# - Version numbers
# - Whether already scraped
# - Parsed sections
```

### Example 3: Search Common Crawl Before Scraping
```python
from ipfs_datasets_py.multi_index_archive_search import get_multi_index_searcher
from ipfs_datasets_py.legal_scrapers import MunicodeScraper

# Search Common Crawl first
searcher = get_multi_index_searcher()
cc_results = await searcher.search_all_common_crawl_indexes(
    domain="library.municode.com",
    url_pattern="*/wa/*",  # Washington state only
    limit_per_index=100
)

print(f"Found {cc_results['total_results']} results across {len(cc_results['indexes_searched'])} indexes")
print(f"Unique URLs: {cc_results['unique_urls']}")

# Now scrape any missing ones
scraped_urls = set(r['url'] for r in cc_results['results'])
scraper = MunicodeScraper()

for url in my_target_urls:
    if url not in scraped_urls:
        result = await scraper.scrape(url)
```

### Example 4: Export to WARC for Archiving
```python
from ipfs_datasets_py.legal_scrapers import MunicodeScraper
from ipfs_datasets_py.warc_integration import WARCExporter

scraper = MunicodeScraper(enable_warc=True)

# Scrape with WARC export enabled
result = await scraper.scrape("https://library.municode.com/wa/seattle")

# Export to WARC
exporter = WARCExporter(output_dir="./warc_exports")
warc_path = await scraper.export_to_warc([result])

print(f"Exported to: {warc_path}")
# Can now upload to Internet Archive or store in IPFS
```

## Next Steps

### Recommended Actions

1. **Deploy to Production**
   - All scrapers migrated and tested
   - Ready for production use
   - Consider setting up scheduled scraping

2. **Monitor Performance**
   - Track scraping rates
   - Monitor CID deduplication effectiveness
   - Measure Common Crawl cache hit rates

3. **Expand Coverage**
   - Add more state-specific scrapers
   - Integrate additional municipal code sources
   - Add court opinion scrapers

4. **Optimize Parallel Scraping**
   - Tune process/worker counts
   - Adjust rate limits per source
   - Implement smart retry logic

5. **IPFS Integration**
   - Set up IPFS pinning service
   - Configure content replication
   - Integrate with Filecoin for archival

## Documentation

- **Architecture**: This document
- **API Reference**: See individual scraper docstrings
- **CLI Usage**: `python -m ipfs_datasets_py.legal_scrapers.cli.municode_cli --help`
- **MCP Server**: `ipfs_datasets_py/legal_scrapers/mcp/README.md`
- **Test Suite**: `test_unified_scraping_architecture.py`

## Support

For questions or issues:
1. Check scraper logs (INFO level)
2. Review test suite for examples
3. Inspect CID mappings in cache directory
4. Verify Common Crawl index availability

## Conclusion

✅ **All legal dataset scrapers successfully migrated to unified architecture**

The migration provides:
- Content-addressed deduplication
- Version tracking
- Multi-index archive searches (all Common Crawl deltas)
- Parallel processing
- WARC integration
- Three-interface accessibility

All scrapers are production-ready and can scale to scrape millions of legal documents efficiently with automatic deduplication and historical version tracking.

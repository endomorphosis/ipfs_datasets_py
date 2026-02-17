# HuggingFace Common Crawl Index Integration

## Overview

This document describes the integration of HuggingFace-hosted Common Crawl indexes with the Legal Web Archive Search system. The integration enables fast, local-first searches of archived legal content without requiring API calls.

## Architecture

### Smart Loading Strategy

```
┌─────────────────────┐
│  Query Submitted    │
└──────────┬──────────┘
           ↓
┌─────────────────────────────────┐
│ Check Local Filesystem          │
│ (e.g., /data/indexes/federal/)  │
└──────────┬──────────────────────┘
           ↓
      ┌────┴────┐
      │  Found? │
      └────┬────┘
     Yes ↓     ↓ No
┌─────────────┐  ┌──────────────────────────┐
│  Use Local  │  │ Try HuggingFace Download │
│   (FAST!)   │  │ (datasets library)       │
└─────────────┘  └──────────┬───────────────┘
                            ↓
                       ┌────┴────┐
                       │Success? │
                       └────┬────┘
                      Yes ↓     ↓ No
              ┌──────────────┐  ┌───────────────────┐
              │ Cache Locally│  │ Return Error      │
              │ for Future   │  │ (may be uploading)│
              └──────────────┘  └───────────────────┘
```

### Components

#### 1. CommonCrawlIndexLoader

**File**: `common_crawl_index_loader.py`

**Purpose**: Intelligently load Common Crawl indexes from local filesystem or HuggingFace.

**Key Features**:
- Local-first loading (instant if files exist)
- Automatic HuggingFace fallback
- Local caching of downloaded indexes
- Supports 5 HuggingFace repositories
- Graceful handling of partial uploads
- State-specific filtering

**Supported Repositories**:
1. `endomorphosis/common_crawl_federal_index` - Federal .gov domains
2. `endomorphosis/common_crawl_state_index` - State government domains
3. `endomorphosis/common_crawl_municipal_index` - Municipal/county domains
4. `endomorphosis/common_crawl_pointers_by_collection` - WARC file pointers
5. `endomorphosis/common_crawl_meta_indexes` - Metadata about collections

#### 2. LegalWebArchiveSearch Integration

**File**: `legal_web_archive_search.py`

**New Methods**:
- `search_with_indexes()` - Search using pre-loaded indexes
- `_search_within_index()` - Internal search logic
- `get_index_info()` - Get availability information

**Constructor Parameters**:
```python
LegalWebArchiveSearch(
    api_key=None,
    knowledge_base_dir=None,
    archive_dir=None,
    auto_archive=False,
    index_local_dir=None,      # NEW: Local index directory
    use_hf_indexes=True         # NEW: Enable HF fallback
)
```

## Usage Examples

### Basic Usage

```python
from ipfs_datasets_py.processors.legal_scrapers import (
    CommonCrawlIndexLoader,
    LegalWebArchiveSearch
)

# Initialize loader with local directory
loader = CommonCrawlIndexLoader(
    local_base_dir="/path/to/indexes",  # Checked first
    use_hf_fallback=True  # Download from HF if not found
)

# Load indexes (checks local first, then HF)
federal_index = loader.load_federal_index()
print(f"Loaded {len(federal_index)} federal records")

# Load state-specific index
ca_index = loader.load_state_index("CA")
print(f"Loaded {len(ca_index)} California records")

# Load municipal index
municipal_index = loader.load_municipal_index()
print(f"Loaded {len(municipal_index)} municipal records")
```

### Integrated Search

```python
from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch

# Initialize with HF index support
searcher = LegalWebArchiveSearch(
    index_local_dir="/data/cc_indexes",  # Optional local path
    use_hf_indexes=True  # Enable HuggingFace fallback
)

# Search using indexes (fast, no API calls)
results = searcher.search_with_indexes(
    "EPA water pollution regulations",
    jurisdiction_type="federal"  # Can be auto-detected
)

print(f"Found {results['total_results']} results")
print(f"Used local index: {results['metadata']['used_local_index']}")

for result in results['results']:
    print(f"  {result['title']}")
    print(f"  {result['url']}")
    print()
```

### State-Specific Search

```python
# Search California state indexes
ca_results = searcher.search_with_indexes(
    "housing discrimination laws",
    jurisdiction_type="state",
    state_code="CA"
)

print(f"Found {ca_results['total_results']} California results")
```

### Auto-Detection

```python
# Jurisdiction type is auto-detected from query
results = searcher.search_with_indexes(
    "OSHA workplace safety regulations"
)
# Auto-detects: federal (OSHA is federal agency)

results = searcher.search_with_indexes(
    "California housing laws"
)
# Auto-detects: state=CA
```

### Index Information

```python
# Get information about available indexes
info = searcher.get_index_info()

print("Index Availability:")
for index_type, details in info['indexes'].items():
    print(f"\n{index_type}:")
    print(f"  Local: {details['local_available']}")
    print(f"  Path: {details['local_path']}")
    print(f"  HF Repo: {details['hf_repo']}")
    print(f"  Loaded: {details['loaded']}")
```

## Configuration

### Environment Variables

```bash
# Optional: Set default local directory
export CC_INDEX_DIR="/path/to/local/indexes"

# Optional: HuggingFace cache directory
export HF_DATASETS_CACHE="/path/to/hf/cache"
```

### File Structure

Expected local directory structure:

```
/data/common_crawl_indexes/
├── federal/
│   ├── federal_index.parquet
│   └── ...
├── state/
│   ├── ca_state.parquet
│   ├── ny_state.parquet
│   └── ...
├── municipal/
│   ├── municipal_index.parquet
│   └── ...
├── pointers/
│   └── pointers.parquet
└── meta/
    └── meta_indexes.parquet
```

## Performance Characteristics

### Local Loading
- **Speed**: Instant (milliseconds)
- **API Calls**: 0
- **Network**: No network required
- **Cost**: Free

### HuggingFace Fallback
- **Speed**: Depends on dataset size and network
  - First time: Minutes (downloading)
  - Cached: Seconds (from local HF cache)
- **API Calls**: HuggingFace dataset API
- **Network**: Required
- **Cost**: Free (HuggingFace Datasets)

### Index Sizes (Estimated)

| Index Type | Approximate Size | Load Time (Local) | Load Time (HF First) |
|------------|------------------|-------------------|----------------------|
| Federal    | 50-100 MB        | <1 second         | 1-5 minutes          |
| State (All)| 200-500 MB       | 2-5 seconds       | 5-15 minutes         |
| State (CA) | 10-30 MB         | <1 second         | 1-2 minutes          |
| Municipal  | 100-300 MB       | 1-3 seconds       | 3-10 minutes         |
| Pointers   | 500 MB - 2 GB    | 5-10 seconds      | 10-30 minutes        |
| Meta       | 10-50 MB         | <1 second         | 1-2 minutes          |

## Error Handling

### Graceful Degradation

The system handles various failure scenarios gracefully:

#### 1. Local Index Not Found
```python
# Falls back to HuggingFace automatically
loader = CommonCrawlIndexLoader(use_hf_fallback=True)
federal = loader.load_federal_index()
# Downloads from HF if local not found
```

#### 2. HuggingFace Download Fails
```python
# Returns None with warning message
loader = CommonCrawlIndexLoader(use_hf_fallback=True)
federal = loader.load_federal_index()
if federal is None:
    print("Index not available yet (may still be uploading)")
```

#### 3. Partial Upload
```python
# Provides clear error message
results = searcher.search_with_indexes("query")
if results['status'] == 'error':
    print(f"Error: {results['error']}")
    # "Failed to load federal index. May still be uploading to HuggingFace."
```

#### 4. Dependencies Missing
```python
# Graceful degradation if datasets library not installed
try:
    from datasets import load_dataset
except ImportError:
    print("Install: pip install datasets")
```

## Best Practices

### 1. Pre-Download Indexes

For production deployments, pre-download indexes to local filesystem:

```bash
# Download all indexes in advance
python -c "
from ipfs_datasets_py.processors.legal_scrapers import CommonCrawlIndexLoader
loader = CommonCrawlIndexLoader(
    local_base_dir='/data/cc_indexes',
    use_hf_fallback=True
)
loader.load_federal_index()
loader.load_state_index()
loader.load_municipal_index()
print('All indexes downloaded and cached')
"
```

### 2. Use State Filtering

Load only what you need for better performance:

```python
# Better: Load only California
ca_index = loader.load_state_index("CA")

# Avoid: Loading all states when you only need one
all_states = loader.load_state_index()  # Larger, slower
```

### 3. Monitor Index Availability

Check availability before relying on indexes:

```python
info = searcher.get_index_info()
if not info['indexes']['federal']['local_available']:
    print("Warning: Federal index will download from HuggingFace")
    print("This may take a few minutes on first run")
```

### 4. Cache Management

Clear cache when needed to free memory:

```python
# Clear loaded indexes from memory
loader.clear_cache()
```

## Troubleshooting

### Issue: "datasets library not available"

**Solution**: Install the HuggingFace datasets library:
```bash
pip install datasets
```

### Issue: "Failed to load index. May still be uploading"

**Solution**: The index may not be fully uploaded to HuggingFace yet. Options:
1. Wait for upload to complete
2. Use local copy if available
3. Fall back to API-based search

### Issue: Slow first-time loading

**Expected**: First-time HuggingFace downloads can be slow for large indexes.

**Solutions**:
1. Use local indexes when possible
2. Pre-download indexes during setup/deployment
3. Use smaller state-specific indexes instead of full datasets

### Issue: Out of memory

**Solution**: Load indexes one at a time and clear cache between loads:
```python
loader = CommonCrawlIndexLoader()

# Load and use federal
federal = loader.load_federal_index()
# ... use federal index ...
loader.clear_cache()

# Load and use state
state = loader.load_state_index("CA")
# ... use state index ...
loader.clear_cache()
```

## Future Enhancements

### Planned Features

1. **Incremental Updates**
   - Download only changed portions of indexes
   - Delta updates for efficiency

2. **Compression**
   - Compressed index storage
   - Faster downloads from HuggingFace

3. **Index Statistics**
   - Usage metrics
   - Performance analytics
   - Hit rates

4. **MCP Tool Integration**
   - MCP tool for index search
   - CLI command for index management
   - Index refresh mechanism

5. **Advanced Filtering**
   - Date range filtering within indexes
   - Domain-specific subsets
   - Custom index views

## References

- HuggingFace Datasets: https://huggingface.co/docs/datasets/
- Common Crawl: https://commoncrawl.org/
- Legal Web Archive Integration: `LEGAL_WEB_ARCHIVE_INTEGRATION.md`
- Brave Legal Search: `BRAVE_LEGAL_SEARCH.md`

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review error messages carefully
3. Check index availability with `get_index_info()`
4. Verify HuggingFace dataset status at https://huggingface.co/endomorphosis

---

**Status**: Production Ready  
**Version**: 1.0.0  
**Date**: February 17, 2026  
**Integration**: Complete with Legal Web Archive Search

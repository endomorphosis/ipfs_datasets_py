# Multi-Engine Search System

## Enhancement 12 - Phase 1: Multi-Engine Search Support

This document describes the new multi-engine search infrastructure that enables legal search and other components to use multiple search engines simultaneously with intelligent fallback and result aggregation.

## Architecture Overview

### Design Principles

1. **Separation of Concerns**: Search engines are implemented in `ipfs_datasets_py/web_archiving/search_engines/` as general-purpose components, not tied to legal search
2. **Unified Interface**: All search engines implement the `SearchEngineAdapter` abstract base class
3. **Extensibility**: New search engines can be added by implementing the adapter interface
4. **Resilience**: Automatic fallback to alternate engines on failure
5. **Performance**: Parallel execution, caching, and rate limiting built-in

### Module Structure

```
ipfs_datasets_py/web_archiving/search_engines/
├── __init__.py                 # Public API exports
├── base.py                     # Abstract adapter interface
├── brave_adapter.py            # Brave Search integration
├── duckduckgo_adapter.py       # DuckDuckGo integration
├── google_cse_adapter.py       # Google Custom Search Engine
└── orchestrator.py             # Multi-engine coordination
```

## Core Components

### 1. SearchEngineAdapter (base.py)

Abstract base class defining the interface all search engines must implement.

**Key Features:**
- Unified `search()` method signature
- Built-in rate limiting
- Response caching with TTL
- Automatic cache key generation
- Statistics tracking

**Required Methods:**
```python
def search(query: str, max_results: int = 20, offset: int = 0, **kwargs) -> SearchEngineResponse
def test_connection() -> bool
```

### 2. BraveSearchEngine (brave_adapter.py)

Wraps the existing `BraveSearchClient` to provide unified interface.

**Features:**
- Reuses existing Brave Search infrastructure
- No changes to existing caching logic
- Result normalization to standard format

**Configuration:**
```python
config = SearchEngineConfig(
    engine_type="brave",
    api_key="your_brave_api_key",
    rate_limit_per_minute=60,
    cache_enabled=True,
    cache_ttl_seconds=3600
)
engine = BraveSearchEngine(config)
```

### 3. DuckDuckGoSearchEngine (duckduckgo_adapter.py)

Provides search using DuckDuckGo (no API key required).

**Features:**
- No API key required (uses duckduckgo-search library)
- Conservative rate limiting (30 requests/minute recommended)
- Automatic retry on failure
- Region and safesearch support

**Requirements:**
```bash
pip install duckduckgo-search>=6.0.0
```

**Configuration:**
```python
config = SearchEngineConfig(
    engine_type="duckduckgo",
    rate_limit_per_minute=30,  # Conservative
    cache_enabled=True
)
engine = DuckDuckGoSearchEngine(config)
```

### 4. GoogleCSESearchEngine (google_cse_adapter.py)

Integrates Google Custom Search Engine API.

**Features:**
- Requires API key and CSE ID
- 100 free queries per day
- Automatic pagination (10 results per request)
- Quota management

**Requirements:**
```bash
pip install google-api-python-client>=2.100.0
```

**Setup:**
1. Get API key: https://console.cloud.google.com/apis/credentials
2. Create CSE: https://programmablesearchengine.google.com/
3. Configure CSE to search entire web or specific sites

**Configuration:**
```python
config = SearchEngineConfig(
    engine_type="google_cse",
    api_key="your_google_api_key",
    rate_limit_per_minute=60,
    extra_params={"cse_id": "your_cse_id"}
)
engine = GoogleCSESearchEngine(config)
```

### 5. MultiEngineOrchestrator (orchestrator.py)

Coordinates searches across multiple engines with parallel execution and fallback.

**Features:**
- Parallel execution using ThreadPoolExecutor
- Automatic fallback on engine failure
- Three aggregation modes: merge, best, round_robin
- Result deduplication by URL
- Performance metrics

**Configuration:**
```python
from ipfs_datasets_py.processors.web_archiving.search_engines import (
    MultiEngineOrchestrator,
    OrchestratorConfig,
    SearchEngineConfig
)

config = OrchestratorConfig(
    engines=["brave", "duckduckgo", "google_cse"],
    parallel_enabled=True,
    fallback_enabled=True,
    result_aggregation="merge",
    deduplication_enabled=True,
    max_workers=3
)

orchestrator = MultiEngineOrchestrator(config)
response = orchestrator.search("EPA regulations California")
```

## Legal Search Integration

### MultiEngineLegalSearch

Extends `BraveLegalSearch` to use multiple search engines.

**Features:**
- 100% backward compatible with `BraveLegalSearch`
- Supports all existing query processing and knowledge base features
- Adds multi-engine execution with orchestrator
- Engine statistics and monitoring

**Usage:**

```python
from ipfs_datasets_py.processors.legal_scrapers import MultiEngineLegalSearch

# Initialize with multiple engines
searcher = MultiEngineLegalSearch(
    engines=["brave", "duckduckgo"],
    brave_api_key="your_brave_key",
    parallel_enabled=True,
    fallback_enabled=True
)

# Search (same API as BraveLegalSearch)
results = searcher.search("EPA water pollution regulations California")

# Check which engines were used
print(f"Engines used: {results['metadata']['engines_used']}")
print(f"Total results: {len(results['results'])}")

# Get engine statistics
stats = searcher.get_engine_stats()
print(f"Total requests: {stats['total_requests']}")

# Test engine connectivity
status = searcher.test_engines()
print(f"Engine status: {status}")
```

## Result Normalization

All search engines return results in a standardized format:

```python
@dataclass
class SearchEngineResult:
    title: str                           # Result title
    url: str                             # Result URL
    snippet: str                         # Description/snippet
    engine: str                          # Source engine
    score: float = 1.0                   # Ranking score
    published_date: Optional[str] = None # Publication date
    domain: Optional[str] = None         # Domain name
    metadata: Dict[str, Any]             # Engine-specific metadata
```

## Performance Features

### 1. Rate Limiting

Each engine enforces rate limits to avoid API throttling:
- Brave: 60 requests/minute (configurable)
- DuckDuckGo: 30 requests/minute (recommended)
- Google CSE: 60 requests/minute (quota limited)

### 2. Caching

- Query results cached with configurable TTL (default: 1 hour)
- Cache keys generated from query + parameters
- Cache statistics available via `get_stats()`

### 3. Parallel Execution

- Orchestrator executes searches across engines in parallel
- Configurable worker pool size
- Timeout protection

### 4. Deduplication

- Results deduplicated by URL (case-insensitive)
- Preserves highest-ranked result when duplicates found

## Migration Guide

### From BraveLegalSearch to MultiEngineLegalSearch

**Minimal Change (Just DuckDuckGo Fallback):**
```python
# Before
from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
searcher = BraveLegalSearch(api_key="...")

# After (adds DuckDuckGo as free fallback)
from ipfs_datasets_py.processors.legal_scrapers import MultiEngineLegalSearch
searcher = MultiEngineLegalSearch(
    engines=["brave", "duckduckgo"],
    brave_api_key="..."
)
```

The `search()` method API is identical, so no other changes needed!

**Full Multi-Engine Setup:**
```python
from ipfs_datasets_py.processors.legal_scrapers import MultiEngineLegalSearch

searcher = MultiEngineLegalSearch(
    engines=["brave", "duckduckgo", "google_cse"],
    brave_api_key=os.environ.get("BRAVE_API_KEY"),
    google_api_key=os.environ.get("GOOGLE_API_KEY"),
    google_cse_id=os.environ.get("GOOGLE_CSE_ID"),
    parallel_enabled=True,
    fallback_enabled=True,
    result_aggregation="merge",
    deduplication_enabled=True
)

results = searcher.search("Your legal query here")
```

## Environment Variables

```bash
# Brave Search
export BRAVE_API_KEY="your_brave_api_key"

# Google Custom Search Engine
export GOOGLE_API_KEY="your_google_api_key"
export GOOGLE_CSE_ID="your_cse_id"

# DuckDuckGo requires no API key
```

## Testing

### Test Individual Engines

```python
from ipfs_datasets_py.processors.web_archiving.search_engines import (
    BraveSearchEngine,
    DuckDuckGoSearchEngine,
    SearchEngineConfig
)

# Test Brave
brave_config = SearchEngineConfig(engine_type="brave", api_key="...")
brave = BraveSearchEngine(brave_config)
assert brave.test_connection()

# Test DuckDuckGo
ddg_config = SearchEngineConfig(engine_type="duckduckgo")
ddg = DuckDuckGoSearchEngine(ddg_config)
assert ddg.test_connection()
```

### Test Orchestrator

```python
from ipfs_datasets_py.processors.web_archiving.search_engines import (
    MultiEngineOrchestrator,
    OrchestratorConfig
)

config = OrchestratorConfig(engines=["brave", "duckduckgo"])
orchestrator = MultiEngineOrchestrator(config)

# Test all engines
status = orchestrator.test_all_connections()
print(f"Engine status: {status}")

# Test search
response = orchestrator.search("test query")
print(f"Results from {len(response.metadata['engines_used'])} engines")
```

## Performance Metrics

```python
# Get orchestrator statistics
stats = orchestrator.get_stats()

# Example output:
{
    "engines": {
        "brave": {
            "requests": 10,
            "cache_entries": 5,
            "cache_enabled": True,
            "rate_limit": 60
        },
        "duckduckgo": {
            "requests": 8,
            "cache_entries": 4,
            "cache_enabled": True,
            "rate_limit": 30
        }
    },
    "total_requests": 18,
    "total_cache_entries": 9
}
```

## Future Enhancements

1. **Additional Engines**: Bing, Yandex, Ecosia
2. **Smart Routing**: Query-based engine selection
3. **Cost Optimization**: Prefer free engines, use paid as fallback
4. **Result Ranking**: ML-based result scoring across engines
5. **A/B Testing**: Compare engine quality for different query types

## API Reference

See inline documentation in source files:
- `ipfs_datasets_py/web_archiving/search_engines/base.py`
- `ipfs_datasets_py/web_archiving/search_engines/orchestrator.py`
- `ipfs_datasets_py/processors/legal_scrapers/multi_engine_legal_search.py`

## Status

**Phase 1 COMPLETE** ✅
- Multi-engine infrastructure implemented
- Three engines supported (Brave, DuckDuckGo, Google CSE)
- Legal search integration complete
- Documentation complete
- Tests pending

**Next Phase**: Enhanced Query Expansion (Phase 2)

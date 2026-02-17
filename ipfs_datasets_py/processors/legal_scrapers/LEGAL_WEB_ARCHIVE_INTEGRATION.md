# Legal Web Archive Search Integration

## Overview

The Legal Web Archive Search integration combines the Brave Legal Search system with web archiving capabilities, providing comprehensive legal content discovery across current web content and historical archives.

## Features

### Unified Search Interface
- **Current Content**: Search live legal content via Brave Search API
- **Archived Content**: Search historical documents via Common Crawl
- **Automatic Archiving**: Automatically preserve important .gov search results
- **Result Merging**: Intelligently combine and deduplicate results from multiple sources

### Intelligent Domain Extraction
- Automatically extracts relevant .gov domains from query intent
- Maps federal agencies to their official domains (e.g., EPA → epa.gov)
- Supports state-level domain patterns (.state.ca.us, .ca.gov)
- Falls back to general .gov searches when needed

### Historical Search
- Search archived legal documents by date range
- Access historical versions of regulations and rules
- Compare current vs historical legal content
- Preserve evidence of regulatory changes over time

## Architecture

```
Query → QueryProcessor → Intent Extraction
                           ↓
              [Domain Extraction from Intent]
                           ↓
         ┌─────────────────┴─────────────────┐
         ↓                                    ↓
    Brave Search API              Common Crawl Archives
    (Current Content)              (Historical Content)
         ↓                                    ↓
         └─────────────────┬─────────────────┘
                           ↓
                [Result Merging & Deduplication]
                           ↓
                  [Optional Archiving]
                           ↓
                    Unified Results
```

## Components

### 1. LegalWebArchiveSearch Class

Main unified search interface combining legal search with web archiving.

**Location**: `ipfs_datasets_py/processors/legal_scrapers/legal_web_archive_search.py`

**Key Methods**:
- `unified_search()` - Search current + archived content
- `search_archives()` - Search only historical documents
- `get_archive_stats()` - Get archive statistics

### 2. MCP Tools (4 tools)

**Location**: `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/legal_web_archive_tools.py`

1. **legal_web_archive_search** - Unified search tool
2. **legal_search_archives_only** - Historical search tool
3. **legal_archive_results** - Archiving tool
4. **legal_get_archive_stats** - Statistics tool

## Usage Examples

### Basic Unified Search

```python
from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch

# Create searcher
searcher = LegalWebArchiveSearch()

# Search with archives included
results = searcher.unified_search(
    "EPA water pollution regulations California",
    include_archives=True
)

print(f"Current results: {len(results['current_results'])}")
print(f"Archived results: {len(results['archived_results'])}")
print(f"Total combined: {len(results['combined_results'])}")
```

### Search with Automatic Archiving

```python
# Enable auto-archiving of results
searcher = LegalWebArchiveSearch(
    archive_dir="/path/to/archives",
    auto_archive=True
)

# Results will be automatically archived
results = searcher.unified_search(
    "OSHA workplace safety requirements",
    archive_results=True  # Override auto_archive if needed
)

# Check archive info
if results['archive_info']:
    print(f"Archived {results['archive_info']['archived_count']} results")
```

### Historical Search Only

```python
# Search archived content from specific date range
historical_results = searcher.search_archives(
    query="California housing discrimination laws",
    from_date="2018-01-01",
    to_date="2022-12-31",
    domains=["hud.gov", "ca.gov"],  # Specific domains
    max_results=50
)

print(f"Found {historical_results['count']} archived documents")
```

### Agency-Specific Archives

```python
# Search specific federal agency archives
epa_results = searcher.search_archives(
    query="clean water act regulations",
    domains=["epa.gov", "regulations.gov"],
    from_date="2020-01-01"
)
```

## MCP Tool Usage

### Via MCP Server

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
    register_legal_web_archive_tools
)

# Register tools with MCP server
register_legal_web_archive_tools(tool_registry)
```

### Tool Parameters

#### legal_web_archive_search
```json
{
    "query": "EPA environmental regulations",
    "max_results": 20,
    "include_archives": true,
    "archive_results": true,
    "archive_dir": "/path/to/archives"
}
```

#### legal_search_archives_only
```json
{
    "query": "housing discrimination laws",
    "from_date": "2020-01-01",
    "to_date": "2023-12-31",
    "domains": ["hud.gov", "justice.gov"],
    "max_results": 50
}
```

#### legal_archive_results
```json
{
    "query": "OSHA workplace safety",
    "results": [
        {
            "url": "https://www.osha.gov/...",
            "title": "OSHA Workplace Safety Standards",
            "relevance_score": 0.95
        }
    ],
    "archive_dir": "/path/to/archives"
}
```

#### legal_get_archive_stats
```json
{
    "archive_dir": "/path/to/archives"
}
```

## Domain Mapping

The system automatically maps query entities to relevant domains:

### Federal Agencies
- EPA → epa.gov
- FDA → fda.gov
- FTC → ftc.gov
- SEC → sec.gov
- DOJ → justice.gov
- HUD → hud.gov

### State Domains
- California → .state.ca.us, .ca.gov
- New York → .state.ny.us, .ny.gov
- (Pattern: .state.XX.us or .XX.gov)

### Default Fallback
- General federal: .gov
- Regulations: regulations.gov, govinfo.gov

## Configuration

### Constructor Parameters

```python
LegalWebArchiveSearch(
    api_key=None,              # Brave API key (or use BRAVE_API_KEY env var)
    knowledge_base_dir=None,   # Dir with legal entity JSONL files
    archive_dir=None,          # Dir for storing archives
    auto_archive=False         # Whether to auto-archive results
)
```

### Environment Variables

- `BRAVE_API_KEY` or `BRAVE_SEARCH_API_KEY` - Brave Search API key
- Optional: Set archive_dir via config

## Result Format

### Unified Search Results

```python
{
    'status': 'success',
    'query': 'original query',
    'query_intent': {
        'agencies': ['EPA'],
        'jurisdictions': ['federal', 'CA'],
        'topics': ['water', 'pollution', 'regulations'],
        'legal_domains': ['environmental'],
        'scope': 'federal_state',
        'confidence': 0.85
    },
    'current_results': [
        {
            'title': '...',
            'url': '...',
            'relevance_score': 0.9,
            'source_type': 'current'
        }
    ],
    'archived_results': [
        {
            'url': '...',
            'timestamp': '20230115',
            'status_code': '200',
            'mime_type': 'text/html',
            'search_domain': 'epa.gov',
            'source': 'common_crawl',
            'source_type': 'archived'
        }
    ],
    'combined_results': [...],  # Merged & deduplicated
    'total_current': 15,
    'total_archived': 8,
    'total_combined': 20,
    'archive_info': {
        'status': 'success',
        'archived_count': 5,
        'archived_items': [...]
    },
    'metadata': {
        'timestamp': '2026-02-17T...',
        'search_sources': ['brave', 'common_crawl'],
        'auto_archived': true
    }
}
```

### Archive Search Results

```python
{
    'status': 'success',
    'results': [
        {
            'url': 'https://epa.gov/...',
            'timestamp': '20220315120530',
            'status_code': '200',
            'mime_type': 'text/html',
            'digest': 'sha1:...',
            'length': '45678',
            'warc_filename': 'crawl-data/...',
            'warc_offset': '123456',
            'search_domain': 'epa.gov',
            'source': 'common_crawl'
        }
    ],
    'count': 25,
    'domains_searched': ['epa.gov', 'regulations.gov'],
    'timestamp': '2026-02-17T...'
}
```

## Benefits

### 1. Comprehensive Coverage
- Access both current and historical legal content
- No content loss due to website changes or deletions
- Multiple search sources provide broader coverage

### 2. Historical Analysis
- Compare regulations over time
- Track regulatory changes
- Evidence preservation for legal research

### 3. Automatic Preservation
- Important .gov sites automatically archived
- Prioritizes legal documents for archiving
- Configurable archiving behavior

### 4. Intelligent Search
- Query intent drives domain selection
- Jurisdiction-aware archive search
- Entity-based domain mapping

## Performance Considerations

### Caching
- Brave Search results cached by BraveSearchClient
- Archive searches can be cached
- Query result caching reduces API calls

### Parallel Search
- Current and archived searches can run in parallel
- Multiple domain searches executed concurrently
- Result merging optimized for performance

### Rate Limiting
- Brave Search API has rate limits (check API docs)
- Common Crawl searches are rate-limited
- Configurable delays between requests

## Error Handling

The system handles various error conditions:

- Missing API keys (gracefully degrades to archives only)
- Archive service unavailable (current results only)
- Network errors (retries with backoff)
- Invalid date formats (validation with helpful errors)
- Missing dependencies (clear error messages)

## Dependencies

### Required
- `brave_legal_search` module (for current search)
- `query_processor` module (for intent extraction)
- Basic Python standard library

### Optional
- `ipfs_datasets_py.processors.web_archiving.web_archive` (for archiving)
- `cdx_toolkit` (for Common Crawl searches)
- `requests` (for HTTP requests)

## Testing

### Unit Tests
Test individual components:
- Domain extraction logic
- Result merging and deduplication
- Archive filtering

### Integration Tests
Test full workflows:
- Unified search with archives
- Historical search with date ranges
- Automatic archiving

### Example Test

```python
def test_unified_search():
    """Test unified search with archives."""
    # GIVEN
    searcher = LegalWebArchiveSearch()
    query = "EPA water regulations"
    
    # WHEN
    results = searcher.unified_search(
        query=query,
        include_archives=True,
        max_results=10
    )
    
    # THEN
    assert results['status'] == 'success'
    assert 'current_results' in results
    assert 'archived_results' in results
    assert 'combined_results' in results
```

## Future Enhancements

### Planned Features
- Wayback Machine integration
- WARC file creation from search results
- Advanced filtering by jurisdiction
- Entity-based archive queries
- Temporal search (find regulations effective on specific dates)
- Multi-language support
- GraphRAG integration for archived content analysis

### Possible Integrations
- Connect with PDF processing for archived documents
- Knowledge graph for tracking regulatory changes
- Automated report generation from archived content
- Semantic search across archived legal documents

## Troubleshooting

### Common Issues

**Issue**: No archived results returned
- **Solution**: Check if `include_archives=True` is set
- **Solution**: Verify cdx_toolkit is installed: `pip install cdx-toolkit`
- **Solution**: Check domain patterns are correct

**Issue**: Archiving not working
- **Solution**: Verify archive_dir exists and is writable
- **Solution**: Check if web_archiving module is available
- **Solution**: Enable auto_archive or set archive_results=True

**Issue**: Slow archive searches
- **Solution**: Reduce max_results parameter
- **Solution**: Specify narrower date ranges
- **Solution**: Use more specific domain patterns

## Support

For issues or questions:
1. Check error messages in logs
2. Verify all dependencies are installed
3. Review configuration parameters
4. Check API keys and environment variables

## Changelog

### Version 1.0.0 (2026-02-17)
- Initial release
- Unified search interface
- Common Crawl integration
- 4 MCP tools
- Automatic archiving
- Domain extraction from intent
- Date range filtering
- Result merging and deduplication

---

**Status**: Production Ready
**Version**: 1.0.0
**Date**: February 17, 2026

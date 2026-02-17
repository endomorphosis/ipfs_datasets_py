# Brave Legal Search - Natural Language Search for Legal Rules

A comprehensive natural language search system for finding federal, state, and local legal rules and regulations using the Brave Search API.

## Overview

The Brave Legal Search system transforms natural language queries about legal rules into optimized search terms by leveraging a knowledge base of over 21,000 government entities:

- **978 Federal entities** (legislative, executive, judicial branches)
- **13,256 State agencies** (across all 50 states + DC)
- **7,143 Municipal governments** (cities, towns, counties)

## Features

✅ **Natural Language Processing** - Understands queries like "EPA water pollution rules in California"  
✅ **Entity Recognition** - Identifies agencies, jurisdictions, and legal concepts  
✅ **Smart Search Term Generation** - Creates multiple optimized search queries  
✅ **Knowledge Base Integration** - Uses government entity database for accuracy  
✅ **Result Aggregation** - Combines and deduplicates results from multiple searches  
✅ **Relevance Scoring** - Ranks results by relevance to query intent  
✅ **Flexible API** - Works standalone or integrates with existing tools

## Quick Start

### Basic Usage

```python
from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch

# Initialize (requires BRAVE_API_KEY environment variable)
searcher = BraveLegalSearch()

# Search with natural language
results = searcher.search("EPA regulations on water pollution in California")

# View results
print(f"Found {len(results['results'])} results")
for result in results['results'][:5]:
    print(f"  {result['title']}: {result['url']}")
```

### Generate Search Terms Only

```python
# Just generate search terms without executing search
terms = searcher.generate_search_terms("OSHA workplace safety requirements")
print(f"Generated search terms: {terms}")
# Output: ['OSHA workplace safety requirements', 'Occupational Safety and Health Administration workplace safety', ...]
```

### Explain Query Processing

```python
# See how a query would be processed
explanation = searcher.explain_query("housing discrimination laws in New York")
print(f"Intent: {explanation['intent']}")
print(f"Search terms: {explanation['top_search_terms']}")
print(f"Scope: {explanation['intent_details']['scope']}")
```

## Architecture

The system consists of four main components:

### 1. Knowledge Base Loader (`knowledge_base_loader.py`)

Loads and indexes legal entity data from JSONL files:
- `federal_all_branches.jsonl` - Federal government entities
- `state_agencies_all.jsonl` - State-level agencies
- `us_towns_and_counties_urls.jsonl` - Municipal governments

Provides efficient lookup by:
- Entity name and aliases
- Jurisdiction (federal/state/local)
- Branch (legislative/executive/judicial)
- Domain/website

### 2. Query Processor (`query_processor.py`)

Processes natural language queries to extract:
- **Topics** - Main subjects (regulations, enforcement, permits)
- **Legal Concepts** - Legal terms and provisions
- **Jurisdictions** - Federal, state codes, municipalities
- **Agencies** - Federal agencies and departments
- **Branches** - Legislative, executive, or judicial
- **Legal Domains** - Housing, employment, civil rights, etc.

### 3. Search Term Generator (`search_term_generator.py`)

Generates optimized search terms by:
- Matching query entities to knowledge base entries
- Combining entities with topics and legal concepts
- Creating variations and synonyms
- Prioritizing by expected relevance

### 4. Brave Legal Search (`brave_legal_search.py`)

Main interface that:
- Orchestrates the complete pipeline
- Executes searches via Brave Search API
- Aggregates and deduplicates results
- Scores results by relevance

## Example Queries

### Federal Regulations

```python
# EPA environmental regulations
results = searcher.search("EPA regulations on air quality standards")

# FDA drug approval process
results = searcher.search("FDA drug approval requirements")

# OSHA workplace safety
results = searcher.search("OSHA workplace safety regulations")
```

### State-Level Rules

```python
# State employment laws
results = searcher.search("California employment discrimination laws")

# State environmental regulations
results = searcher.search("Texas environmental protection regulations")

# State housing laws
results = searcher.search("New York tenant rights and fair housing laws")
```

### Municipal Ordinances

```python
# City building codes
results = searcher.search("San Francisco building code requirements")

# Municipal zoning
results = searcher.search("Chicago zoning ordinances")

# Local health regulations
results = searcher.search("Los Angeles restaurant health regulations")
```

### Mixed Jurisdiction

```python
# Federal and state
results = searcher.search("ADA compliance requirements California")

# Multi-state comparison
results = searcher.search("workers compensation laws New York vs California")
```

## API Reference

### BraveLegalSearch

Main search interface class.

**Constructor:**
```python
BraveLegalSearch(
    api_key: Optional[str] = None,
    knowledge_base_dir: Optional[str] = None,
    cache_enabled: bool = True
)
```

**Methods:**

#### `search(query, max_results=20, country="US", lang="en", execute_search=True)`

Execute natural language legal search.

**Returns:**
```python
{
    'query': str,              # Original query
    'intent': dict,            # Parsed query intent
    'search_terms': list,      # Generated search terms
    'results': list,           # Search results with relevance scores
    'strategy': dict,          # Complete search strategy
    'metadata': dict           # Knowledge base stats and info
}
```

#### `generate_search_terms(query)`

Generate search terms without executing search.

**Returns:** List of search term strings

#### `explain_query(query)`

Explain how a query would be processed.

**Returns:** Dict with detailed processing explanation

#### `get_knowledge_base_stats()`

Get statistics about the loaded knowledge base.

**Returns:** Dict with entity counts and statistics

#### `search_entities(query, entity_type=None)`

Search for entities in the knowledge base.

**Returns:** Dict with matching entities by type

### Factory Functions

#### `create_legal_search(api_key=None, knowledge_base_dir=None)`

Create a configured BraveLegalSearch instance.

#### `search_legal(query, api_key=None)`

Simple one-function search interface for CLI/scripting.

## Configuration

### Environment Variables

- `BRAVE_API_KEY` or `BRAVE_SEARCH_API_KEY` - Brave Search API key (required)
- `BRAVE_SEARCH_CACHE_PATH` - Custom cache file location (optional)

### API Key

Get a Brave Search API key from: https://brave.com/search/api/

Set it in your environment:
```bash
export BRAVE_API_KEY="your_api_key_here"
```

Or pass it directly:
```python
searcher = BraveLegalSearch(api_key="your_api_key_here")
```

## Knowledge Base

### Data Sources

The knowledge base is built from three JSONL files in the `legal_scrapers/` directory:

1. **federal_all_branches.jsonl** (978 entities)
   - Federal agencies, departments, and services
   - Organized by branch (legislative, executive, judicial)
   - Includes websites, domains, and seed URLs

2. **state_agencies_all.jsonl** (13,256 entities)
   - State-level government agencies
   - All 50 states plus District of Columbia
   - Governor offices, attorneys general, departments, etc.

3. **us_towns_and_counties_urls.jsonl** (7,143 entities)
   - Municipal and county governments
   - Cities, towns, and counties
   - Includes official websites and codes

### Loading the Knowledge Base

The knowledge base is automatically loaded when creating a `BraveLegalSearch` instance:

```python
# Default location (same directory as module)
searcher = BraveLegalSearch()

# Custom location
searcher = BraveLegalSearch(knowledge_base_dir="/path/to/jsonl/files")

# Or load directly
from ipfs_datasets_py.processors.legal_scrapers import load_knowledge_base
kb = load_knowledge_base("/path/to/directory")
stats = kb.get_statistics()
```

## Integration with Complaint Analysis

The Brave Legal Search system leverages components from the `complaint_analysis` module for:
- Legal concept extraction
- Keyword categorization
- Domain classification (housing, employment, etc.)

This provides backward compatibility and code reuse across the legal_scrapers module.

## Performance

- **Query Processing:** < 100ms
- **Search Term Generation:** < 50ms
- **Knowledge Base Loading:** ~500ms (cached after first load)
- **Brave Search API:** Depends on API response time (typically 200-500ms per query)

## Caching

Results are cached by the Brave Search client to reduce API calls:
- Disk-based cache with TTL
- Configurable cache location
- Thread-safe with file locking

## Testing

See test files for examples:
```bash
pytest tests/unit/legal_scrapers/test_brave_legal_search.py
pytest tests/integration/test_brave_legal_search_integration.py
```

## CLI Usage

```bash
# Using the enhanced CLI
python scripts/cli/enhanced_cli.py legal_search_tools brave_legal_search \
    --query "EPA water pollution regulations California"

# Or directly via Python
python -c "
from ipfs_datasets_py.processors.legal_scrapers import search_legal
results = search_legal('OSHA workplace safety requirements')
print(f\"Found {len(results['results'])} results\")
"
```

## Future Enhancements

Potential improvements:
- [ ] Add support for more search engines (DuckDuckGo, Google CSE)
- [ ] Implement query expansion with synonyms and related terms
- [ ] Add result filtering by domain, date, jurisdiction
- [ ] Support for legal citation extraction from results
- [ ] Integration with legal text analysis (GraphRAG)
- [ ] Multi-language support for international regulations
- [ ] Historical regulation tracking and changes
- [ ] Automated report generation

## Related Modules

- `complaint_analysis/` - Legal complaint analysis and categorization
- `web_archiving/brave_search_client.py` - Brave Search API client
- `mcp_server/tools/web_archive_tools/` - MCP tools for search

## License

See main repository LICENSE file.

## Contributing

Contributions welcome! Please ensure:
- Code follows repository style guidelines
- Tests are added for new functionality
- Documentation is updated
- Backward compatibility is maintained

## Support

For issues or questions:
1. Check the documentation
2. Review example code
3. Open an issue on GitHub
4. Contact the maintainers

---

**Version:** 1.0.0  
**Last Updated:** February 2026  
**Status:** Production Ready

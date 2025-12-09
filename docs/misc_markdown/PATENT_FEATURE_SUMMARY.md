# Patent Dataset Feature Summary

## Overview

A new patent scraper has been added to the IPFS Datasets Python library, enabling users to build legal datasets from USPTO patent filings for GraphRAG knowledge graph integration.

## What's New

### Core Components

1. **Patent Scraper Module** (`ipfs_datasets_py/mcp_tools/tools/patent_scraper.py`)
   - USPTO PatentsView API integration
   - Advanced search capabilities
   - Rate limiting and error handling
   - Async/await support

2. **MCP Tools** (`ipfs_datasets_py/mcp_tools/tools/patent_dataset_mcp_tools.py`)
   - 5 MCP tools for AI assistant integration
   - GraphRAG-ready dataset building
   - Entity and relationship extraction

3. **Web Dashboard** (`/mcp/patents`)
   - Interactive search interface
   - Dataset building wizard
   - Results visualization
   - GraphRAG integration monitoring

4. **Flask API** (`ipfs_datasets_py/patent_dashboard.py`)
   - RESTful API endpoints
   - Search, build, and ingest operations
   - JSON/Parquet export

## Quick Start

### Installation

The feature is included in the main package. No additional installation required.

### Basic Usage

```python
from ipfs_datasets_py.mcp_tools.tools.patent_scraper import search_patents_by_keyword

# Search for patents
patents = search_patents_by_keyword(["artificial intelligence"], limit=100)

# View results
for patent in patents:
    print(f"{patent.patent_number}: {patent.patent_title}")
```

### Web Dashboard

```bash
# Start the admin dashboard
python -m ipfs_datasets_py.admin_dashboard

# Navigate to:
# http://127.0.0.1:8888/mcp/patents
```

## Key Features

### Search Capabilities
- ✅ Keyword search in titles/abstracts
- ✅ Inventor name search
- ✅ Assignee/organization search
- ✅ Patent number lookup
- ✅ Date range filtering
- ✅ CPC/IPC classification filtering

### Dataset Building
- ✅ JSON and Parquet export
- ✅ GraphRAG-ready structure
- ✅ Entity extraction (Patent, Inventor, Assignee, Classification)
- ✅ Relationship extraction (INVENTED_BY, ASSIGNED_TO, CLASSIFIED_AS, CITES)
- ✅ Citation network data

### Integration
- ✅ MCP tools for AI assistants
- ✅ Flask API endpoints
- ✅ Interactive web dashboard
- ✅ GraphRAG knowledge graph ready

## Documentation

- **Comprehensive Guide**: `docs/PATENT_SCRAPER_GUIDE.md`
- **Demo Script**: `demo_patent_scraper.py`
- **Tests**: `tests/test_patent_scraper.py`

## API Reference

### Search Endpoints

```http
POST /api/mcp/patents/search
{
  "keywords": ["AI"],
  "inventor_name": "Smith",
  "assignee_name": "TechCorp",
  "date_from": "2020-01-01",
  "date_to": "2024-12-31",
  "limit": 100
}
```

### Dataset Building

```http
POST /api/mcp/patents/build_dataset
{
  "search_criteria": {...},
  "output_format": "json",
  "graphrag_format": true
}
```

## MCP Tools

Available for AI assistant integration:

1. `scrape_uspto_patents` - Advanced patent search
2. `search_patents_by_keyword` - Quick keyword search
3. `search_patents_by_inventor` - Search by inventor
4. `search_patents_by_assignee` - Search by organization
5. `build_patent_dataset` - Build GraphRAG datasets

## Examples

### Advanced Search

```python
from ipfs_datasets_py.mcp_tools.tools.patent_scraper import (
    USPTOPatentScraper,
    PatentSearchCriteria
)

scraper = USPTOPatentScraper(rate_limit_delay=1.0)
criteria = PatentSearchCriteria(
    keywords=["machine learning", "neural network"],
    date_from="2020-01-01",
    cpc_classification=["G06F"],
    limit=500
)

patents = scraper.search_patents(criteria)
```

### Build GraphRAG Dataset

```python
from ipfs_datasets_py.mcp_tools.tools.patent_scraper import (
    USPTOPatentScraper,
    PatentDatasetBuilder,
    PatentSearchCriteria
)
from pathlib import Path

scraper = USPTOPatentScraper()
builder = PatentDatasetBuilder(scraper)

criteria = PatentSearchCriteria(keywords=["blockchain"], limit=1000)
result = builder.build_dataset(
    criteria=criteria,
    output_format="json",
    output_path=Path("/data/patents/blockchain.json")
)
```

## Testing

Run the comprehensive test suite:

```bash
pytest tests/test_patent_scraper.py -v
```

Or run the demo script:

```bash
python demo_patent_scraper.py
```

## Data Structure

Patents include:
- Patent number and title
- Abstract and descriptions
- Inventors and assignees
- Classifications (CPC/IPC)
- Citations and relationships
- Filing and grant dates

GraphRAG entities:
- **Patent**: Core patent documents
- **Inventor**: Individual inventors
- **Assignee**: Organizations/companies
- **Classification**: CPC/IPC codes

GraphRAG relationships:
- **INVENTED_BY**: Patent → Inventor
- **ASSIGNED_TO**: Patent → Assignee
- **CLASSIFIED_AS**: Patent → Classification
- **CITES**: Patent → Patent

## Rate Limiting

The scraper respects USPTO API rate limits:
- Default: 1 second between requests
- Configurable delay
- Automatic retry with backoff
- Handles 429 responses

## Error Handling

Comprehensive error handling for:
- Network errors
- API errors
- Rate limiting
- Invalid responses
- Parsing errors

## Future Enhancements

Potential improvements:
- Google Patents integration
- Full-text extraction
- Patent claim parsing
- Image/diagram extraction
- Citation network visualization
- Patent portfolio analysis

## Support

- **Documentation**: `docs/PATENT_SCRAPER_GUIDE.md`
- **Issues**: GitHub Issues
- **Examples**: `demo_patent_scraper.py`

## License

Same as parent project (see main LICENSE file)

## Credits

- USPTO PatentsView API: https://patentsview.org/apis/purpose
- Implementation: Part of IPFS Datasets Python library

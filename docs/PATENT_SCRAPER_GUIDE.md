# Patent Scraper Guide

## Overview

The Patent Scraper module provides integration with the USPTO PatentsView API to build legal datasets from patent filings. This tool enables users to search, collect, and structure patent data for integration with GraphRAG knowledge graphs.

## Features

### Data Sources
- **USPTO PatentsView API**: Official USPTO patent data (no authentication required)
- Comprehensive patent information including:
  - Patent numbers, titles, and abstracts
  - Inventors and assignees
  - Classifications (CPC/IPC)
  - Citations and relationships
  - Filing and grant dates

### Search Capabilities
- **Keyword Search**: Search patent abstracts and titles
- **Inventor Search**: Find patents by inventor name
- **Assignee Search**: Find patents by organization/company
- **Date Range**: Filter by filing or grant dates
- **Classification**: Filter by CPC or IPC codes
- **Patent Number**: Retrieve specific patents

### Dataset Building
- Export formats: JSON, Parquet
- GraphRAG-ready structure
- Entity and relationship extraction
- Batch processing support
- Resume capability for long-running jobs

### GraphRAG Integration
- Pre-configured entity types: Patent, Inventor, Assignee, Classification
- Pre-configured relationships: INVENTED_BY, ASSIGNED_TO, CLASSIFIED_AS, CITES
- Optimized for knowledge graph construction
- Citation network analysis

## Quick Start

### Basic Usage

```python
from ipfs_datasets_py.mcp_tools.tools.patent_scraper import (
    search_patents_by_keyword,
    search_patents_by_inventor,
    search_patents_by_assignee
)

# Search by keyword
patents = search_patents_by_keyword(
    keywords=["artificial intelligence", "machine learning"],
    limit=100
)

# Search by inventor
patents = search_patents_by_inventor(
    inventor_name="Smith",
    limit=50
)

# Search by assignee/company
patents = search_patents_by_assignee(
    assignee_name="Google",
    limit=100
)
```

### Advanced Search

```python
from ipfs_datasets_py.mcp_tools.tools.patent_scraper import (
    USPTOPatentScraper,
    PatentSearchCriteria
)

scraper = USPTOPatentScraper(rate_limit_delay=1.0)

criteria = PatentSearchCriteria(
    keywords=["blockchain", "distributed ledger"],
    date_from="2020-01-01",
    date_to="2024-12-31",
    cpc_classification=["G06F", "H04L"],
    limit=500
)

patents = scraper.search_patents(criteria)
```

### Building Datasets

```python
from ipfs_datasets_py.mcp_tools.tools.patent_scraper import (
    USPTOPatentScraper,
    PatentSearchCriteria,
    PatentDatasetBuilder
)
from pathlib import Path

scraper = USPTOPatentScraper(rate_limit_delay=1.0)
builder = PatentDatasetBuilder(scraper)

criteria = PatentSearchCriteria(
    keywords=["quantum computing"],
    limit=1000
)

result = builder.build_dataset(
    criteria=criteria,
    output_format="json",
    output_path=Path("/data/patents/quantum_computing.json")
)

print(f"Built dataset with {result['metadata']['patent_count']} patents")
```

### Async Operations

```python
import asyncio
from ipfs_datasets_py.mcp_tools.tools.patent_scraper import (
    USPTOPatentScraper,
    PatentSearchCriteria
)

async def search_patents_async():
    scraper = USPTOPatentScraper()
    criteria = PatentSearchCriteria(keywords=["neural networks"])
    patents = await scraper.search_patents_async(criteria)
    return patents

patents = asyncio.run(search_patents_async())
```

## Web Dashboard

### Accessing the Dashboard

1. Start the IPFS Datasets admin dashboard:
   ```bash
   python -m ipfs_datasets_py.admin_dashboard
   ```

2. Open your browser to:
   ```
   http://127.0.0.1:8888/mcp/patents
   ```

### Dashboard Features

#### Search Tab
- Interactive search form with multiple filters
- Real-time results display
- Export search results

#### Build Dataset Tab
- Configure dataset parameters
- Select output format (JSON/Parquet)
- Enable GraphRAG formatting
- Include citation graphs
- Include classification data

#### Results Tab
- View patent details
- Browse inventors and assignees
- Explore classifications
- View citation relationships

#### GraphRAG Integration Tab
- Monitor ingestion status
- View entity and relationship types
- Track indexed patents

## API Endpoints

### Search Patents
```http
POST /api/mcp/patents/search
Content-Type: application/json

{
  "keywords": ["artificial intelligence"],
  "inventor_name": "Smith",
  "assignee_name": "Google",
  "date_from": "2020-01-01",
  "date_to": "2024-12-31",
  "cpc_classification": ["G06F"],
  "limit": 100
}
```

### Build Dataset
```http
POST /api/mcp/patents/build_dataset
Content-Type: application/json

{
  "search_criteria": {
    "keywords": ["blockchain"],
    "limit": 1000
  },
  "output_format": "json",
  "dataset_name": "blockchain_patents",
  "include_citations": true,
  "include_classifications": true,
  "graphrag_format": true
}
```

### GraphRAG Ingestion
```http
POST /api/mcp/patents/graphrag/ingest
Content-Type: application/json

{
  "dataset_path": "/data/patents/blockchain_patents.json",
  "graph_name": "patent_graph"
}
```

## MCP Tools

The patent scraper is also available as MCP tools for integration with AI assistants:

### Available Tools

1. **scrape_uspto_patents**
   - Search and scrape USPTO patents
   - Advanced filtering options
   - Batch processing support

2. **search_patents_by_keyword**
   - Simple keyword-based search
   - Quick results

3. **search_patents_by_inventor**
   - Find patents by inventor name
   - Support for partial name matching

4. **search_patents_by_assignee**
   - Find patents by organization
   - Company/university search

5. **build_patent_dataset**
   - Build GraphRAG-ready datasets
   - Multiple output formats
   - Automatic entity extraction

### Using MCP Tools

```python
from ipfs_datasets_py.mcp_tools.tools.patent_dataset_mcp_tools import (
    ScrapeUSPTOPatentsTool
)

tool = ScrapeUSPTOPatentsTool()
result = await tool.execute({
    "keywords": ["machine learning"],
    "limit": 100,
    "output_format": "json"
})
```

## GraphRAG Integration

### Entity Types

The patent scraper extracts the following entity types:

- **Patent**: Patent documents with titles, abstracts, and metadata
- **Inventor**: Individual inventors with names
- **Assignee**: Organizations/companies that own patents
- **Classification**: CPC and IPC classification codes

### Relationship Types

The following relationships are extracted:

- **INVENTED_BY**: Patent → Inventor
- **ASSIGNED_TO**: Patent → Assignee
- **CLASSIFIED_AS**: Patent → Classification
- **CITES**: Patent → Patent (citation relationships)

### Dataset Structure

```json
{
  "status": "success",
  "metadata": {
    "dataset_type": "patents",
    "source": "USPTO PatentsView API",
    "patent_count": 100,
    "created_at": "2024-01-15T10:30:00"
  },
  "patents": [
    {
      "patent_number": "US1234567",
      "patent_title": "Method for AI Processing",
      "patent_abstract": "...",
      "patent_date": "2024-01-15",
      "inventors": [
        {"first_name": "John", "last_name": "Smith"}
      ],
      "assignees": [
        {"organization": "TechCorp Inc"}
      ],
      "cpc_classifications": ["G06F"],
      "citations": ["US9876543"]
    }
  ],
  "graphrag_metadata": {
    "entity_types": ["Patent", "Inventor", "Assignee", "Classification"],
    "relationship_types": ["INVENTED_BY", "ASSIGNED_TO", "CLASSIFIED_AS", "CITES"],
    "ready_for_ingestion": true
  }
}
```

## Rate Limiting

The scraper implements respectful rate limiting:

- Default: 1 second between requests
- Configurable delay parameter
- Automatic retry with exponential backoff
- Handles 429 (Too Many Requests) responses

```python
scraper = USPTOPatentScraper(rate_limit_delay=2.0)  # 2 seconds between requests
```

## Error Handling

The scraper provides comprehensive error handling:

```python
try:
    patents = search_patents_by_keyword(["AI"])
except requests.exceptions.RequestException as e:
    print(f"API error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Best Practices

1. **Rate Limiting**: Use appropriate delays to respect USPTO API
2. **Batch Processing**: Use pagination for large datasets
3. **Error Recovery**: Implement retry logic for network errors
4. **Data Storage**: Store results in durable storage (JSON/Parquet)
5. **GraphRAG Integration**: Use standardized entity/relationship types

## Examples

See `demo_patent_scraper.py` for comprehensive examples:

```bash
python demo_patent_scraper.py
```

## API Reference

### USPTOPatentScraper

Main class for interacting with USPTO API.

**Methods:**
- `search_patents(criteria)`: Search patents synchronously
- `search_patents_async(criteria)`: Search patents asynchronously

### PatentSearchCriteria

Dataclass for search parameters.

**Fields:**
- `keywords`: List of keywords
- `inventor_name`: Inventor last name
- `assignee_name`: Organization name
- `patent_number`: Specific patent number
- `date_from`: Start date (YYYY-MM-DD)
- `date_to`: End date (YYYY-MM-DD)
- `cpc_classification`: List of CPC codes
- `ipc_classification`: List of IPC codes
- `limit`: Maximum results (default: 100)
- `offset`: Pagination offset (default: 0)

### PatentDatasetBuilder

Class for building patent datasets.

**Methods:**
- `build_dataset(criteria, output_format, output_path)`: Build dataset
- `build_dataset_async(...)`: Async version

### Patent

Dataclass representing a patent document.

**Fields:**
- `patent_number`: Patent number
- `patent_title`: Patent title
- `patent_abstract`: Abstract text
- `patent_date`: Grant date
- `application_number`: Application number
- `application_date`: Filing date
- `inventors`: List of inventors
- `assignees`: List of assignees
- `cpc_classifications`: CPC codes
- `ipc_classifications`: IPC codes
- `claims`: Patent claims (optional)
- `description`: Full description (optional)
- `citations`: Cited patents
- `raw_data`: Raw API response

## Troubleshooting

### Common Issues

1. **Module Import Errors**
   - Ensure all dependencies are installed
   - Check Python path includes the package

2. **API Connection Errors**
   - Verify internet connection
   - Check USPTO API status
   - Verify firewall settings

3. **Rate Limiting**
   - Increase `rate_limit_delay` parameter
   - Implement exponential backoff
   - Check API quotas

4. **Empty Results**
   - Verify search criteria
   - Check date ranges
   - Try broader keywords

## Resources

- [USPTO PatentsView API Documentation](https://patentsview.org/apis/purpose)
- [CPC Classification System](https://www.cooperativepatentclassification.org/)
- [IPC Classification System](https://www.wipo.int/classifications/ipc/en/)

## Support

For issues and questions:
- GitHub Issues: [Repository Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- Documentation: [Main README](../README.md)

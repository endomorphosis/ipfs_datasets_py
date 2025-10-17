# Municipal Codes Scraping Tool

## Overview

The `scrape_municipal_codes` MCP tool provides integration with the `scrape_the_law_mk3` system to collect municipal legal codes from US cities and counties. This tool offers a standardized interface for scraping legal codes from various providers including LexisNexis, Municode, American Legal, and General Code.

## Purpose

Per the US Library of Congress, there currently does not exist a single repository for all US municipal codes. This tool aims to address this gap by providing a unified interface to scrape and collect municipal legal codes from all 22,899+ US cities and counties.

## Tool Information

- **Tool Name**: `scrape_municipal_codes`
- **Category**: Legal Datasets
- **Version**: 1.0.0
- **Tags**: legal, municipal, codes, cities, counties, dataset, scraping

## Parameters

### Required Parameters
At least one of the following must be provided:
- `jurisdiction` - Single jurisdiction to scrape
- `jurisdictions` - List of jurisdictions to scrape

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `jurisdiction` | string | None | Single jurisdiction to scrape (e.g., 'New York, NY') |
| `jurisdictions` | array[string] | None | List of jurisdictions to scrape. Use ['all'] for all jurisdictions |
| `provider` | string | "auto" | Legal code provider: 'municode', 'american_legal', 'general_code', 'lexisnexis', or 'auto' to auto-detect |
| `output_format` | string | "json" | Output format: 'json', 'parquet', or 'sql' |
| `include_metadata` | boolean | true | Include full metadata (citation info, version history, etc.) |
| `include_text` | boolean | true | Include full legal text (increases data size) |
| `rate_limit_delay` | number | 2.0 | Delay between requests in seconds |
| `max_sections` | integer | None | Maximum number of code sections to scrape per jurisdiction |
| `scraper_type` | string | "playwright" | Scraper backend: 'playwright' (async) or 'selenium' (sync) |
| `job_id` | string | None | Job identifier for resume capability (auto-generated if not provided) |
| `resume` | boolean | false | Resume from previous scraping state if job_id is provided |

## Return Value

The tool returns a dictionary with the following structure:

```json
{
  "status": "success",
  "job_id": "municipal_codes_20250101_120000",
  "message": "Municipal code scraping job initialized",
  "jurisdictions": ["New York, NY", "Los Angeles, CA"],
  "provider": "auto",
  "scraper_type": "playwright",
  "output_format": "json",
  "scraper_path": "ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3",
  "note": "scrape_the_law_mk3 integration ready. The scraper module is available at the specified path.",
  "data": [],
  "metadata": {
    "job_id": "municipal_codes_20250101_120000",
    "jurisdictions_count": 2,
    "parameters": { ... }
  }
}
```

## Usage Examples

### Example 1: Scrape a Single Jurisdiction

```python
from ipfs_datasets_py.mcp_tools.tools.legal_dataset_mcp_tools import ScrapeMunicipalCodesTool

tool = ScrapeMunicipalCodesTool()

result = await tool.execute({
    "jurisdiction": "Seattle, WA",
    "provider": "municode",
    "output_format": "json",
    "include_metadata": True
})

print(f"Job ID: {result['job_id']}")
print(f"Status: {result['status']}")
```

### Example 2: Scrape Multiple Jurisdictions

```python
result = await tool.execute({
    "jurisdictions": [
        "New York, NY",
        "Los Angeles, CA", 
        "Chicago, IL",
        "Houston, TX"
    ],
    "provider": "auto",
    "output_format": "parquet",
    "rate_limit_delay": 3.0
})

print(f"Scraping {result['metadata']['jurisdictions_count']} jurisdictions")
```

### Example 3: Resume a Previous Job

```python
# Start a job
result1 = await tool.execute({
    "jurisdictions": ["Boston, MA", "Portland, OR"],
    "job_id": "my_custom_job",
    "output_format": "sql"
})

# Later, resume the same job
result2 = await tool.execute({
    "jurisdictions": ["Boston, MA", "Portland, OR"],
    "job_id": "my_custom_job",
    "resume": True
})
```

### Example 4: Use with Custom Scraper Settings

```python
result = await tool.execute({
    "jurisdiction": "Austin, TX",
    "provider": "general_code",
    "scraper_type": "selenium",
    "rate_limit_delay": 5.0,
    "max_sections": 1000,
    "include_text": True,
    "include_metadata": True
})
```

## Integration with scrape_the_law_mk3

This tool provides a clean MCP interface to the `scrape_the_law_mk3` submodule located at:
```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3/
```

The scrape_the_law_mk3 system is designed to:
- Extract legal documents from official government or government-contracted websites
- Parse and standardize raw content into tabular data with metadata
- Store in a database with proper relationships and versioning
- Maintain version history and track code updates/amendments
- Handle different website structures and content formats

## Providers Supported

The tool supports scraping from the following major legal code providers:

1. **Municode** (~3,528 codes)
2. **American Legal** (~2,180 codes)
3. **General Code** (~1,601 codes)
4. **LexisNexis** (~3,200 codes)
5. **Other** (via general crawler)

## Error Handling

The tool provides comprehensive error handling:

- Returns `status: "error"` with error details on failure
- Validates that at least one jurisdiction is specified
- Handles missing dependencies gracefully
- Provides detailed error messages in the `error` field

## Performance Considerations

- Use `rate_limit_delay` to control request rate and avoid overloading servers
- Use `max_sections` to limit the scope of large scraping jobs
- Consider using `output_format: "parquet"` for large datasets
- Use `job_id` and `resume` for long-running scraping jobs

## Related Tools

- `scrape_state_laws` - For state-level legislation
- `scrape_us_code` - For federal statutes
- `scrape_recap_archive` - For federal court documents
- `list_scraping_jobs` - To view and manage scraping jobs

## See Also

- [scrape_the_law_mk3 Documentation](../mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3/README.md)
- [Legal Dataset Tools](./legal_dataset_mcp_tools.py)
- [MCP Tools README](../README.md)

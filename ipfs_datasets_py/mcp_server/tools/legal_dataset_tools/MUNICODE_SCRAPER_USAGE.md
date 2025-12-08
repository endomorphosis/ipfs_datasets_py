# Municode Library Scraper - Usage Guide

## Overview

The Municode Library scraper (`municode_scraper.py`) provides an MVP implementation for scraping municipal codes from library.municode.com, one of the largest municipal code providers in the United States serving 3,500+ jurisdictions.

## Quick Start

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municode_scraper import (
    scrape_municode,
    search_municode_library,
    scrape_municode_jurisdiction,
    get_municode_jurisdictions
)

# Example 1: Scrape specific jurisdictions
result = await scrape_municode(
    jurisdictions=["Seattle, WA", "Portland, OR"],
    output_format="json",
    include_metadata=True,
    rate_limit_delay=2.0
)

print(f"Scraped {result['metadata']['jurisdictions_count']} jurisdictions")
print(f"Total sections: {result['metadata']['total_sections']}")
```

## Main Functions

### 1. `search_municode_library()`

Search for jurisdictions in the Municode Library.

**Parameters:**
- `jurisdiction` (str, optional): Jurisdiction name to search for
- `state` (str, optional): State abbreviation (e.g., "CA", "NY")
- `keywords` (str, optional): Search keywords
- `limit` (int, default=100): Maximum number of results

**Returns:** Dictionary with status, jurisdictions list, and count

**Example:**
```python
# Search by state
result = await search_municode_library(state="WA", limit=10)
print(f"Found {result['count']} jurisdictions in Washington")

# Search by name
result = await search_municode_library(
    jurisdiction="Seattle",
    state="WA"
)

# Search with keywords
result = await search_municode_library(
    keywords="zoning",
    state="CA",
    limit=5
)
```

### 2. `get_municode_jurisdictions()`

Get a list of available jurisdictions.

**Parameters:**
- `state` (str, optional): Filter by state abbreviation
- `limit` (int, default=100): Maximum number of jurisdictions

**Returns:** Dictionary with status, jurisdictions, count, provider, and source

**Example:**
```python
result = await get_municode_jurisdictions(state="CA", limit=20)

for jurisdiction in result['jurisdictions']:
    print(f"{jurisdiction['name']} - {jurisdiction['url']}")
```

### 3. `scrape_municode_jurisdiction()`

Scrape a single jurisdiction's municipal code.

**Parameters:**
- `jurisdiction_name` (str): Name of the jurisdiction
- `jurisdiction_url` (str): URL to the jurisdiction's code
- `include_metadata` (bool, default=True): Include metadata
- `max_sections` (int, optional): Maximum sections to scrape

**Returns:** Dictionary with status, jurisdiction info, and sections

**Example:**
```python
result = await scrape_municode_jurisdiction(
    jurisdiction_name="Seattle, WA",
    jurisdiction_url="https://library.municode.com/seattle-wa",
    include_metadata=True,
    max_sections=50
)

print(f"Scraped {result['sections_count']} sections")
for section in result['sections']:
    print(f"  {section['section_number']}: {section['title']}")
```

### 4. `scrape_municode()` - Main Batch Scraper

Scrape multiple jurisdictions with full control.

**Parameters:**
- `jurisdictions` (list[str], optional): List of jurisdiction names
- `states` (list[str], optional): List of state abbreviations
- `output_format` (str, default="json"): Output format ("json", "parquet", "sql")
- `include_metadata` (bool, default=True): Include metadata
- `rate_limit_delay` (float, default=2.0): Delay between requests in seconds
- `max_jurisdictions` (int, optional): Maximum jurisdictions to scrape
- `max_sections_per_jurisdiction` (int, optional): Maximum sections per jurisdiction

**Returns:** Dictionary with status, data, metadata, and output format

**Example:**
```python
# Scrape specific jurisdictions
result = await scrape_municode(
    jurisdictions=["Seattle, WA", "Portland, OR", "San Francisco, CA"],
    output_format="json",
    include_metadata=True,
    rate_limit_delay=2.0,
    max_sections_per_jurisdiction=100
)

# Scrape by states
result = await scrape_municode(
    states=["WA", "OR"],
    output_format="parquet",
    max_jurisdictions=10,
    max_sections_per_jurisdiction=50
)

# Access results
print(f"Status: {result['status']}")
print(f"Jurisdictions: {result['metadata']['jurisdictions_count']}")
print(f"Total sections: {result['metadata']['total_sections']}")
print(f"Elapsed time: {result['metadata']['elapsed_time_seconds']:.2f}s")

# Iterate through data
for jurisdiction_data in result['data']:
    print(f"\n{jurisdiction_data['jurisdiction']}:")
    print(f"  Sections: {jurisdiction_data['sections_count']}")
    for section in jurisdiction_data['sections'][:3]:
        print(f"    {section['section_number']}: {section['title'][:60]}...")
```

## Common Use Cases

### Use Case 1: Research Municipal Codes in a Region

```python
# Get all jurisdictions in California
result = await scrape_municode(
    states=["CA"],
    output_format="json",
    max_jurisdictions=20,
    max_sections_per_jurisdiction=10
)

# Export to file
import json
with open("california_municipal_codes.json", "w") as f:
    json.dump(result['data'], f, indent=2)
```

### Use Case 2: Compare Specific Ordinances Across Cities

```python
# Scrape zoning codes from multiple cities
cities = [
    "Seattle, WA",
    "Portland, OR",
    "San Francisco, CA",
    "Los Angeles, CA"
]

result = await scrape_municode(
    jurisdictions=cities,
    output_format="json",
    include_metadata=True,
    rate_limit_delay=3.0  # Be respectful to the server
)

# Analyze sections
for jurisdiction_data in result['data']:
    print(f"\n{jurisdiction_data['jurisdiction']}:")
    zoning_sections = [
        s for s in jurisdiction_data['sections']
        if 'zoning' in s['title'].lower()
    ]
    print(f"  Zoning sections: {len(zoning_sections)}")
```

### Use Case 3: Build a Municipal Code Database

```python
import asyncio

# Scrape all available jurisdictions in multiple states
states_to_scrape = ["WA", "OR", "CA", "NY", "TX"]
all_data = []

for state in states_to_scrape:
    print(f"Scraping {state}...")
    
    result = await scrape_municode(
        states=[state],
        output_format="json",
        max_jurisdictions=5,  # Limit for testing
        max_sections_per_jurisdiction=20,
        rate_limit_delay=3.0
    )
    
    if result['status'] == 'success':
        all_data.extend(result['data'])
    
    # Be respectful - wait between states
    await asyncio.sleep(5.0)

print(f"Total jurisdictions scraped: {len(all_data)}")
```

## Output Structure

All functions return dictionaries with consistent structure:

### Search Results
```json
{
  "status": "success",
  "jurisdictions": [
    {
      "name": "Seattle, WA",
      "url": "https://library.municode.com/seattle-wa",
      "provider": "municode",
      "source": "library.municode.com",
      "state": "WA"
    }
  ],
  "count": 1,
  "search_params": {...}
}
```

### Scraping Results
```json
{
  "status": "success",
  "data": [
    {
      "status": "success",
      "jurisdiction": "Seattle, WA",
      "url": "https://library.municode.com/seattle-wa",
      "sections": [
        {
          "section_number": "1.01",
          "title": "General Provisions",
          "text": "Section text...",
          "jurisdiction": "Seattle, WA",
          "source_url": "https://library.municode.com/seattle-wa",
          "scraped_at": "2024-12-08T12:00:00",
          "provider": "municode"
        }
      ],
      "sections_count": 1,
      "provider": "municode"
    }
  ],
  "metadata": {
    "jurisdictions_scraped": ["Seattle, WA"],
    "jurisdictions_count": 1,
    "total_sections": 1,
    "elapsed_time_seconds": 2.5,
    "scraped_at": "2024-12-08T12:00:00",
    "provider": "municode",
    "source": "library.municode.com",
    "rate_limit_delay": 2.0,
    "include_metadata": true
  },
  "output_format": "json"
}
```

## Error Handling

The scraper includes comprehensive error handling:

```python
result = await scrape_municode(
    jurisdictions=["NonExistent, XX"]
)

if result['status'] == 'error':
    print(f"Error: {result['error']}")
else:
    # Process data
    pass
```

## Rate Limiting

Always use appropriate rate limiting to be respectful to the server:

```python
# Good: Reasonable delay
result = await scrape_municode(
    jurisdictions=["Seattle, WA", "Portland, OR"],
    rate_limit_delay=2.0  # 2 seconds between requests
)

# Better: Conservative delay for large scrapes
result = await scrape_municode(
    states=["CA"],
    rate_limit_delay=5.0,  # 5 seconds between requests
    max_jurisdictions=10
)
```

## Testing

Run the built-in test function:

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municode_scraper import test_municode_scraper

# Runs comprehensive tests of all functions
result = await test_municode_scraper()
```

Or run the test suite:

```bash
pytest tests/scraper_tests/test_municode_scraper.py -v
```

## Limitations and Notes

1. **MVP Status**: This is an MVP implementation with placeholder data when network access is unavailable
2. **JavaScript Rendering**: Some content may require JavaScript rendering (Playwright/Selenium) for full access
3. **Rate Limiting**: Always respect rate limits to avoid overloading servers
4. **Network Restrictions**: The scraper gracefully handles DNS resolution failures and network restrictions
5. **Data Accuracy**: Placeholder data is clearly marked in the response with notes

## Future Enhancements

- Integration with Playwright for JavaScript-rendered content
- IPFS storage of scraped data
- Citation extraction and cross-referencing
- Full-text search capabilities
- Differential updates tracking
- More comprehensive metadata extraction

## Support

For issues or questions:
1. Check the test file: `tests/scraper_tests/test_municode_scraper.py`
2. Review the main README: `README.md`
3. Run the built-in test function for validation

## Municipal Code Categories

The scraper recognizes these common municipal code categories:

- Administration
- Business Regulations
- Buildings and Construction
- Fire Prevention
- Health and Sanitation
- Planning and Zoning
- Police and Public Safety
- Public Works
- Streets and Sidewalks
- Taxation
- Traffic and Vehicles
- Utilities

These can be used to filter or organize scraped data.

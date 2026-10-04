# Municode Library Webscraper - MVP Specification

## Overview

MVP specification for a webscraper dedicated to scraping municipal codes from Municode Library (library.municode.com), one of the largest municipal code providers in the United States serving 3,500+ jurisdictions.

## Purpose

Municode Library hosts municipal codes, ordinances, and local laws for cities, counties, and special districts across the US. Currently, there is no single centralized repository for all US municipal codes (per the US Library of Congress). This scraper would provide structured access to this distributed legal information.

## Target Website

- **URL**: https://library.municode.com
- **Content**: Municipal codes and ordinances
- **Coverage**: 3,500+ US jurisdictions
- **Format**: HTML pages with structured content

## Core Functionality

### 1. Search Jurisdictions
- Search by jurisdiction name (city, county, district)
- Search by state (two-letter abbreviation)
- Search by keywords in code content
- Return list of matching jurisdictions with URLs

### 2. Scrape Individual Jurisdiction
- Input: Jurisdiction name and URL
- Extract: Code sections, titles, and text
- Include: Section numbers, headings, full text
- Metadata: Enactment dates, amendments, citations (optional)

### 3. Batch Scraping
- Scrape multiple jurisdictions
- Filter by state(s)
- Configurable limits (max jurisdictions, max sections per jurisdiction)
- Rate limiting to respect server resources

## Data Structure

### Jurisdiction Info
```
{
  "name": "Seattle, WA",
  "state": "WA",
  "url": "https://library.municode.com/wa/seattle",
  "provider": "municode"
}
```

### Code Section
```
{
  "jurisdiction": "Seattle, WA",
  "section_number": "1.01.020",
  "title": "Definitions",
  "chapter": "General Provisions",
  "text": "Full text of the section...",
  "source_url": "https://library.municode.com/wa/seattle/codes/municipal_code?nodeId=TIT1GEPR_CH1.01GERE",
  "scraped_at": "2024-12-08T12:00:00Z"
}
```

## Key Features

1. **Async/Await Support**: Non-blocking I/O for efficient scraping
2. **Rate Limiting**: Configurable delays between requests (default: 2 seconds)
3. **Error Handling**: Graceful fallbacks for network failures
4. **Multiple Output Formats**: JSON, Parquet, CSV
5. **Metadata Extraction**: Dates, citations, amendments
6. **Resumable Jobs**: Save state for long-running scrapes

## Technical Requirements

### Dependencies
- HTTP client (requests or httpx)
- HTML parser (BeautifulSoup or lxml)
- Async support (asyncio)
- Optional: Playwright/Selenium for JavaScript-rendered content

### Rate Limiting
- Minimum 2 seconds between requests
- Configurable delay
- Respect robots.txt
- Handle 429 (Too Many Requests) responses

### Error Handling
- Network timeouts
- DNS resolution failures
- Invalid HTML structure
- Missing content
- Server errors (5xx)

## Municipal Code Categories

Common categories to identify:
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

## Implementation Approach

### Phase 1: Basic Scraper
1. Search function to find jurisdictions
2. Single jurisdiction scraper
3. Basic error handling
4. JSON output

### Phase 2: Enhanced Features
1. Batch scraping with state filters
2. Rate limiting and retry logic
3. Multiple output formats
4. Metadata extraction

### Phase 3: Production Ready
1. Resumable jobs with state persistence
2. Incremental updates
3. IPFS storage integration
4. Citation extraction and linking

## Usage Examples

### Search for Jurisdictions
```
Input: state="WA", limit=10
Output: List of 10 jurisdictions in Washington state
```

### Scrape Single Jurisdiction
```
Input: jurisdiction="Seattle, WA"
Output: All code sections for Seattle with metadata
```

### Batch Scrape by States
```
Input: states=["WA", "OR", "CA"], max_jurisdictions=5
Output: 5 jurisdictions from each state (15 total)
```

## Challenges and Considerations

1. **Website Structure**: Municode may use JavaScript rendering requiring browser automation
2. **Content Organization**: Each jurisdiction may organize codes differently
3. **Rate Limits**: Need to be respectful of server resources
4. **Data Volume**: 3,500+ jurisdictions with potentially thousands of sections each
5. **Updates**: Codes are amended regularly, need strategy for incremental updates

## Success Metrics

- Successfully scrape at least 100 jurisdictions
- Extract complete code sections with accurate metadata
- Handle network errors gracefully (no crashes)
- Respect rate limits (no server overload)
- Structured output ready for database import

## Future Enhancements

- Full-text search across all scraped codes
- Citation graph (cross-references between sections)
- Differential updates (track changes over time)
- Integration with other legal databases
- API for querying scraped data

## References

- Municode Library: https://library.municode.com
- Similar projects: municipal-code scrapers for individual cities
- Legal citation standards: Bluebook, ALWD

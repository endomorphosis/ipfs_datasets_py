# Legal Dataset Tools

This package provides MCP server tools for scraping and building datasets from various legal sources.

## Available Scrapers

### 1. US Code Scraper (`us_code_scraper.py`)
Scrapes the United States Code from uscode.house.gov.

**Features:**
- 54 US Code titles mapped
- Configurable title selection
- Metadata includes effective dates and amendments
- Rate limiting support

**Usage:**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_us_code, get_us_code_titles

# Get available titles
titles = await get_us_code_titles()

# Scrape specific titles
result = await scrape_us_code(
    titles=["1", "15", "18"],  # Title numbers
    output_format="json",
    include_metadata=True,
    rate_limit_delay=1.0,
    max_sections=100
)
```

**API Endpoint:** `POST /api/mcp/dataset/uscode/scrape`

---

### 2. Federal Register Scraper (`federal_register_scraper.py`)
Scrapes Federal Register documents from federalregister.gov.

**Features:**
- 20+ federal agencies supported (EPA, FDA, DOL, SEC, FTC, etc.)
- Date range filtering
- Document type filtering (RULE, NOTICE, PRORULE)
- Keyword search capability

**Usage:**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_federal_register

result = await scrape_federal_register(
    agencies=["EPA", "FDA"],
    start_date="2024-01-01",
    end_date="2024-12-31",
    document_types=["RULE", "NOTICE"],
    include_full_text=False,
    max_documents=100
)
```

**API Endpoint:** `POST /api/mcp/dataset/federal_register/scrape`

---

### 3. State Laws Scraper (`state_laws_scraper.py`)
Scrapes state statutes and regulations from state legislative websites.

**Features:**
- All 50 US states + DC
- Legal area filtering
- State-specific rate limiting

**Usage:**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_state_laws

result = await scrape_state_laws(
    states=["CA", "NY", "TX"],
    legal_areas=["criminal", "civil"],
    include_metadata=True,
    max_statutes=100
)
```

**API Endpoint:** `POST /api/mcp/dataset/state_laws/scrape`

---

### 4. Municipal Laws Scraper (`municipal_laws_scraper.py`)
Scrapes municipal codes and ordinances from city and county governments.

**Features:**
- 23+ major US cities
- Population-based filtering
- City name pattern matching

**Usage:**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_municipal_laws

result = await scrape_municipal_laws(
    cities=["NYC", "LAX", "CHI"],
    include_metadata=True,
    max_ordinances=100
)
```

**API Endpoint:** `POST /api/mcp/dataset/municipal_laws/scrape`

---

### 5. RECAP Archive Scraper (`recap_archive_scraper.py`)
Scrapes federal court documents from the RECAP Archive (courtlistener.com).

**Features:**
- Federal court document scraping
- Court filtering (district, appellate, bankruptcy)
- Document type filtering (opinions, complaints, dockets, orders, motions, briefs)
- Case name pattern matching
- Date range filtering
- Optional text and metadata inclusion

**Usage:**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_recap_archive

result = await scrape_recap_archive(
    courts=["ca9", "nysd"],
    document_types=["opinion", "complaint"],
    filed_after="2024-01-01",
    filed_before="2024-12-31",
    include_text=True,
    max_documents=100
)
```

**API Endpoints:**
- `POST /api/mcp/dataset/recap/scrape` - Scrape RECAP documents
- `POST /api/mcp/dataset/recap/search` - Search RECAP archive

---

## Dashboard Integration

All scrapers are integrated into the Caselaw Dashboard at `/mcp/caselaw` with dedicated UI sections:

1. **US Code & Federal Register** tab - Configure and scrape federal laws
2. **State Laws** tab - Configure and scrape state statutes
3. **Municipal Laws** tab - Configure and scrape city/county ordinances
4. **RECAP Archive** tab - Configure and scrape federal court documents

Each section provides:
- Configuration forms for parameters
- Real-time progress tracking
- Dataset preview tables
- Export to JSON functionality
- Status monitoring

## Common Parameters

All scrapers support these common parameters:

- `output_format`: "json" or "parquet"
- `rate_limit_delay`: Delay between requests in seconds
- `include_metadata`: Include additional metadata
- `max_*`: Maximum number of items to scrape (for testing/limiting)

## Output Format

All scrapers return a standardized response:

```json
{
  "status": "success" | "error",
  "data": [...],  // Array of scraped items
  "metadata": {
    "count": 123,
    "elapsed_time_seconds": 45.6,
    "scraped_at": "2024-01-01T12:00:00",
    "source": "...",
    ...
  },
  "output_format": "json",
  "error": "..."  // Only present if status is "error"
}
```

## Dependencies

- `requests`: HTTP requests (optional, provides better error handling)
- `beautifulsoup4`: HTML parsing (optional, for scrapers that need it)

Scrapers handle missing dependencies gracefully with informative error messages.

## Testing

Run the test suite:

```bash
python test_legal_scrapers_simple.py
```

This will test all scrapers and generate a detailed report.

## Notes

- Current implementation uses placeholder data with production-ready structure
- Production implementation would connect to actual data sources
- All scrapers include rate limiting to respect server limits
- Comprehensive error handling and logging throughout
- Async implementation for efficient I/O operations

## Future Enhancements

- [ ] Connect to actual data sources (uscode.house.gov, federalregister.gov, etc.)
- [ ] Add Parquet export support
- [ ] Add IPFS storage integration
- [ ] Add resume capability for interrupted scraping
- [ ] Add incremental updates for existing datasets
- [ ] Add more court types for RECAP scraper
- [ ] Add citation extraction and linking

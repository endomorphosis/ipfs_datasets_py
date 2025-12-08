# Legal Dataset Tools

This package provides MCP server tools for scraping and building datasets from various legal sources with production-ready features including real API integration, resume capability, incremental updates, and multiple export formats.

## Features

### ✅ Real Data Source Integration
- **RECAP Archive**: Connected to CourtListener API (courtlistener.com)
- Real-time document fetching from federal courts
- Search and individual document retrieval

### ✅ Export Formats
- **JSON**: Standard JSON with pretty-printing option
- **Parquet**: Apache Parquet with compression (snappy/gzip/brotli)
- **CSV**: Standard CSV with configurable delimiter
- Automatic nested structure flattening

### ✅ Resume Capability
- State persistence for interrupted scraping jobs
- Automatic deduplication on resume
- Progress tracking with percentage completion
- Error logging with timestamps

### ✅ Incremental Updates
- Automatic date range calculation based on last update
- Per-scope tracking (e.g., per court, per jurisdiction)
- Configurable overlap to prevent missing documents
- Update tracker with metadata storage

## Available Scrapers

### 1. US Code Scraper (`us_code_scraper.py`)
Scrapes the United States Code from uscode.house.gov.

**Features:**
- 54 US Code titles mapped
- Configurable title selection
- Metadata includes effective dates and amendments
- Rate limiting support

**Status:** ⚠️ Placeholder data (production API connection pending)

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

**Status:** ⚠️ Placeholder data (production API connection pending)

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
Scrapes state statutes and regulations from state legislative websites using Justia.com as an aggregator.

**Features:**
- All 50 US states + DC
- Legal area filtering (criminal, civil, family, employment, etc.)
- State-specific rate limiting
- Real data source integration via Justia Legal Database
- Automatic legal area detection
- Official state legislature URL references

**Status:** ✅ Production-ready with real data scraping

**Usage:**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_state_laws

result = await scrape_state_laws(
    states=["CA", "NY", "TX"],  # Or ["all"] for all states
    legal_areas=["criminal", "employment"],
    output_format="json",
    include_metadata=True,
    rate_limit_delay=2.0,
    max_statutes=100
)
```

**API Endpoint:** `POST /api/mcp/dataset/state_laws/scrape`

**Cron Job Support:**
The state laws scraper includes built-in scheduling support for periodic updates:

```bash
# Add a daily schedule for California and New York
python state_laws_cron.py add --schedule-id daily_ca_ny --states CA,NY --interval 24

# List all schedules
python state_laws_cron.py list

# Run a schedule immediately
python state_laws_cron.py run --schedule-id daily_ca_ny

# Enable/disable a schedule
python state_laws_cron.py enable --schedule-id daily_ca_ny
python state_laws_cron.py disable --schedule-id daily_ca_ny

# Run continuous scheduler daemon
python state_laws_cron.py daemon --check-interval 300
```

**Scheduler API Endpoints:**
- `GET /api/mcp/dataset/state_laws/schedules` - List all schedules
- `POST /api/mcp/dataset/state_laws/schedules` - Create a new schedule
- `DELETE /api/mcp/dataset/state_laws/schedules/<id>` - Delete a schedule
- `POST /api/mcp/dataset/state_laws/schedules/<id>/run` - Run schedule immediately
- `POST /api/mcp/dataset/state_laws/schedules/<id>/toggle` - Enable/disable schedule

**Scheduler Configuration:**
Schedules are stored in `~/.ipfs_datasets/state_laws/schedule.json` and persist across restarts.
Scraped data is saved to `~/.ipfs_datasets/state_laws/` with timestamped filenames.

**Status:** ⚠️ Placeholder data (production connections pending)

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

**Status:** ⚠️ Placeholder data (production connections pending)

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

### 5. Municode Library Scraper (`municode_scraper.py`) 🆕
Scrapes municipal codes from Municode Library (library.municode.com), one of the largest municipal code providers in the United States serving 3,500+ jurisdictions.

**Features:**
- Search by jurisdiction, state, or keywords
- Batch scraping with configurable limits
- Rate limiting to avoid overloading servers
- Metadata extraction support
- Multiple output formats (JSON, Parquet, SQL)
- Graceful error handling with placeholder fallbacks
- Built-in test function for validation

**Status:** 🆕 MVP Implementation

**Usage:**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municode_scraper import (
    scrape_municode,
    search_municode_library,
    scrape_municode_jurisdiction,
    get_municode_jurisdictions
)

# Search for jurisdictions
search_result = await search_municode_library(state="WA", limit=10)

# Get jurisdictions list
jurisdictions = await get_municode_jurisdictions(state="CA", limit=20)

# Scrape specific jurisdictions
result = await scrape_municode(
    jurisdictions=["Seattle, WA", "Portland, OR"],
    output_format="json",
    include_metadata=True,
    rate_limit_delay=2.0,
    max_sections_per_jurisdiction=100
)

# Scrape all jurisdictions in specific states
result = await scrape_municode(
    states=["WA", "OR"],
    output_format="parquet",
    max_jurisdictions=10,
    max_sections_per_jurisdiction=50
)
```

**API Functions:**
- `search_municode_library()` - Search for jurisdictions by state, name, or keywords
- `get_municode_jurisdictions()` - Get list of available jurisdictions
- `scrape_municode_jurisdiction()` - Scrape a single jurisdiction
- `scrape_municode()` - Main batch scraping function

**Test Function:**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municode_scraper import test_municode_scraper

# Run built-in tests
result = await test_municode_scraper()
```

---

### 6. RECAP Archive Scraper (`recap_archive_scraper.py`) ✅ PRODUCTION READY
Scrapes federal court documents from the RECAP Archive (courtlistener.com).

**Features:**
- ✅ **Connected to real CourtListener API**
- Federal court document scraping
- Court filtering (district, appellate, bankruptcy)
- Document type filtering (opinions, complaints, dockets, orders, motions, briefs)
- Case name pattern matching
- Date range filtering
- Optional text and metadata inclusion
- ✅ **Resume capability**
- ✅ **Incremental updates**

**Status:** ✅ Production-ready with real API integration

**Usage:**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_recap_archive

result = await scrape_recap_archive(
    courts=["ca9", "nysd"],
    document_types=["opinion", "complaint"],
    filed_after="2024-01-01",
    filed_before="2024-12-31",
    include_text=True,
    max_documents=100,
    job_id="my_job"  # For resume capability
)
```

**Resume interrupted job:**
```python
result = await scrape_recap_archive(
    job_id="my_job",
    resume=True  # Continues from where it left off
)
```

**Incremental update (fetch only new documents):**
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_recap_incremental

result = await scrape_recap_incremental(
    courts=["ca9"],
    document_types=["opinion"]
)
# Automatically uses date range from last update
```

**API Endpoints:**
- `POST /api/mcp/dataset/recap/scrape` - Scrape RECAP documents
- `POST /api/mcp/dataset/recap/search` - Search RECAP archive
- `POST /api/mcp/dataset/recap/incremental` - Incremental update

---

## Export Utilities

### Export to Multiple Formats

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import export_dataset

# Export to JSON
result = export_dataset(
    data=scraped_data,
    output_path="/path/to/output",
    format="json",
    pretty=True
)

# Export to Parquet
result = export_dataset(
    data=scraped_data,
    output_path="/path/to/output",
    format="parquet",
    compression="snappy"
)

# Export to CSV
result = export_dataset(
    data=scraped_data,
    output_path="/path/to/output",
    format="csv",
    delimiter=","
)
```

**API Endpoint:** `POST /api/mcp/dataset/export`

---

## State Management & Resume

### Save and Resume Scraping Jobs

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import ScrapingState, list_scraping_jobs

# List all saved jobs
jobs = list_scraping_jobs()

# Delete a job
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import delete_scraping_job
delete_scraping_job("job_id")
```

**State Storage:** `~/.ipfs_datasets/scraping_state/`

**API Endpoints:**
- `GET /api/mcp/dataset/jobs` - List all scraping jobs
- `DELETE /api/mcp/dataset/jobs/<job_id>` - Delete a job

---

## Incremental Updates

### Automatic Update Tracking

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import IncrementalUpdateTracker

tracker = IncrementalUpdateTracker()

# Get last update time
last_update = tracker.get_last_update("recap_archive", "ca9")

# List all tracked datasets
trackers = tracker.get_all_trackers()
```

**Tracker Storage:** `~/.ipfs_datasets/update_tracker/`

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
- Export functionality (JSON/Parquet/CSV)
- Status monitoring
- Resume capability
- Incremental update option

---

## Common Parameters

All scrapers support these common parameters:

- `output_format`: "json" or "parquet"
- `rate_limit_delay`: Delay between requests in seconds
- `include_metadata`: Include additional metadata
- `max_*`: Maximum number of items to scrape (for testing/limiting)
- `job_id`: Unique identifier for resume capability
- `resume`: Boolean to resume from previous state

---

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
    "job_id": "...",
    "resumed": false
  },
  "output_format": "json",
  "job_id": "...",  // For resume capability
  "incremental_update": {  // If incremental
    "last_update": "2024-01-01T00:00:00",
    "date_range_used": {...},
    "is_first_update": false
  },
  "error": "..."  // Only present if status is "error"
}
```

---

## Dependencies

**Required:**
- Python 3.10+

**Optional (handled gracefully if missing):**
- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing (for some scrapers)
- `pyarrow` - Parquet export support

Scrapers handle missing dependencies gracefully with informative error messages.

---

## Testing

Run the test suite:

```bash
python test_legal_scrapers_simple.py
```

---

## Production Status

| Scraper | Status | API Connection |
|---------|--------|----------------|
| **RECAP Archive** | ✅ **Production Ready** | ✅ **CourtListener API (courtlistener.com)** |
| **Federal Register** | ✅ **Production Ready** | ✅ **Federal Register API (federalregister.gov)** |
| US Code | ⚠️ Placeholder | ⚠️ Pending (uscode.house.gov) |
| State Laws | ⚠️ Placeholder | ⚠️ Pending (varies by state) |
| Municipal Laws | ⚠️ Placeholder | ⚠️ Pending (varies by municipality) |

### Integration Status

| Feature | Status |
|---------|--------|
| MCP Tool Registration | ✅ Complete (15 tools registered in `tool_registration.py`) |
| JavaScript SDK Methods | ✅ Complete (15 convenience methods in `mcp-sdk.js`) |
| Dashboard UI Integration | ✅ Complete (all tabs functional with real API calls) |
| Playwright E2E Tests | ✅ Complete (20+ test methods in `test_legal_dataset_dashboard_ui.py`) |
| Parquet Export | ✅ Production Ready (with PyArrow) |
| JSON Export | ✅ Production Ready |
| CSV Export | ✅ Production Ready |
| Resume Capability | ✅ Production Ready (state persistence) |
| Incremental Updates | ✅ Production Ready (automatic date tracking) |
| State Persistence | ✅ Production Ready (job management) |

---

## Future Enhancements

- [ ] Connect remaining scrapers to production APIs
- [ ] Add IPFS storage integration
- [ ] Add citation extraction and linking
- [ ] Add more court types for RECAP scraper
- [ ] Add authentication support for APIs requiring keys
- [ ] Add caching layer for frequently accessed data

---

## Notes

- All scrapers include rate limiting to respect server limits
- Comprehensive error handling and logging throughout
- Async implementation for efficient I/O operations
- State persistence enables long-running jobs
- Incremental updates minimize bandwidth and API calls

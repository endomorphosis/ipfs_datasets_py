# RECAP Archive & State Laws Dataset Builder - Implementation Summary

## Overview

This implementation fixes the caselaw MCP server dashboard at `http://127.0.0.1:8899/mcp/caselaw` to properly expose and utilize the legal dataset scraping tools, particularly the RECAP Archive scraper and State Laws scraper.

## Problem Solved

**Original Issue**: 
- Dashboard showed only 4 MCP tools (temporal deontic logic tools)
- "Dataset Workflows" section was mostly mocked up data
- RECAP Archive Dataset Builder wasn't functional
- No integration between the scrapers and the MCP tool system
- No easy way to set up periodic updates for state laws

**Solution**:
- Created MCP tool wrappers for all legal dataset scrapers
- Integrated 5 new tools into the MCP server (total now 9 tools)
- Updated dashboard to dynamically fetch available tools from API
- Created comprehensive documentation for cron job setup
- Added resume capability for interrupted scraping jobs

## Changes Made

### 1. New File: `ipfs_datasets_py/mcp_tools/tools/legal_dataset_mcp_tools.py`

Created 5 new MCP tools that wrap the existing scraper implementations:

1. **scrape_recap_archive** - Scrape federal court documents from RECAP Archive
   - Courts filtering (9th Circuit, S.D.N.Y., etc.)
   - Document type filtering (opinions, complaints, dockets, etc.)
   - Date range filtering
   - Full text extraction
   - Resume capability with job_id
   - State management for interrupted jobs

2. **search_recap_documents** - Search RECAP Archive for specific documents
   - Text query search
   - Court, case name, document type filters
   - Date range filtering
   - Configurable result limits

3. **scrape_state_laws** - Scrape state legislation and statutes
   - Multi-state support (all 50 states + DC)
   - Legal area filtering
   - Official state source scraping
   - Metadata extraction

4. **list_scraping_jobs** - List all scraping jobs with resume info
   - Filter by status (running, completed, failed)
   - Filter by job type (recap, state_laws, us_code)
   - Shows progress and metadata

5. **scrape_us_code** - Scrape United States Code federal statutes
   - Title-based filtering
   - Section-level granularity
   - Metadata extraction

### 2. Updated: `ipfs_datasets_py/mcp_tools/temporal_deontic_mcp_server.py`

- Import LEGAL_DATASET_MCP_TOOLS
- Combine with existing temporal deontic logic tools
- Server now exposes 9 tools total instead of 4

### 3. Updated: `ipfs_datasets_py/templates/admin/caselaw_dashboard_mcp.html`

- Changed `loadAvailableTools()` to fetch from `/api/mcp/caselaw/tools` API
- Added fallback to hardcoded list if API unavailable
- Updated `callRestFallback()` with endpoints for all 9 tools
- Tool count now dynamically updates based on actual available tools

### 4. New File: `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/CRON_SETUP_SIMPLE.md`

Comprehensive documentation for setting up automatic updates:
- Quick start guide
- Schedule management commands
- Systemd service configuration
- Docker deployment instructions
- Traditional cron setup
- Troubleshooting guide

### 5. New File: `test_recap_scraping.py`

Test suite for RECAP Archive scraping:
- Search functionality
- Document retrieval
- Bulk scraping
- Resume capability

## Tool Specifications

### Tool 1: scrape_recap_archive

**Purpose**: Build datasets of federal court documents from RECAP Archive

**Parameters**:
```json
{
  "courts": ["ca9", "nysd"],           // Optional: Court identifiers
  "document_types": ["opinion"],        // Optional: Document types
  "filed_after": "2024-01-01",         // Optional: YYYY-MM-DD
  "filed_before": "2024-12-31",        // Optional: YYYY-MM-DD
  "case_name_pattern": "Smith v.",     // Optional: Case name filter
  "include_text": true,                 // Include full document text
  "include_metadata": true,             // Include metadata
  "rate_limit_delay": 1.0,             // Seconds between requests
  "max_documents": 100,                 // Maximum documents to fetch
  "job_id": "my_job_001",              // For resume capability
  "resume": false                       // Resume from previous state
}
```

**Returns**:
```json
{
  "status": "success",
  "data": [...],                        // Array of documents
  "metadata": {
    "documents_count": 100,
    "courts_count": 2,
    "elapsed_time_seconds": 45.2,
    "source": "CourtListener RECAP Archive"
  },
  "job_id": "my_job_001",
  "output_format": "json"
}
```

### Tool 2: search_recap_documents

**Purpose**: Search RECAP Archive for specific documents

**Parameters**:
```json
{
  "query": "constitutional law",        // Optional: Text search
  "court": "ca9",                       // Optional: Court filter
  "case_name": "Smith v. Jones",       // Optional: Case name
  "filed_after": "2024-01-01",         // Optional: Date range
  "filed_before": "2024-12-31",        // Optional: Date range
  "document_type": "opinion",          // Optional: Document type
  "limit": 100                          // Max results
}
```

**Returns**:
```json
{
  "status": "success",
  "documents": [...],                   // Array of matching documents
  "count": 25,
  "total_available": 250,
  "search_params": {...}
}
```

### Tool 3: scrape_state_laws

**Purpose**: Scrape state legislation from official sources

**Parameters**:
```json
{
  "states": ["CA", "NY", "TX"],        // State codes or ["all"]
  "legal_areas": ["criminal", "civil"], // Optional: Focus areas
  "output_format": "json",              // "json" or "parquet"
  "include_metadata": true,
  "rate_limit_delay": 2.0,
  "max_statutes": 1000
}
```

**Returns**:
```json
{
  "status": "success",
  "data": [...],                        // Normalized statute data
  "metadata": {
    "states_count": 3,
    "statutes_count": 1000,
    "source": "Official State Legislative Websites"
  }
}
```

### Tool 4: list_scraping_jobs

**Purpose**: List all scraping jobs for resume capability

**Parameters**:
```json
{
  "status_filter": "all",               // "all", "running", "completed", "failed"
  "job_type": "all"                     // "all", "recap", "state_laws", "us_code"
}
```

**Returns**:
```json
{
  "status": "success",
  "jobs": [
    {
      "job_id": "recap_20240101_123456",
      "status": "completed",
      "progress": {...},
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "total_count": 10
}
```

### Tool 5: scrape_us_code

**Purpose**: Scrape United States Code federal statutes

**Parameters**:
```json
{
  "titles": [17, 35],                   // USC titles (e.g., Copyright, Patents)
  "output_format": "json",
  "include_metadata": true,
  "rate_limit_delay": 1.0
}
```

**Returns**:
```json
{
  "status": "success",
  "data": [...],                        // USC sections
  "metadata": {
    "titles_count": 2,
    "sections_count": 500
  }
}
```

## API Endpoints

The dashboard can call these tools via two methods:

### 1. MCP JSON-RPC (Primary)
```
POST /api/mcp/caselaw/jsonrpc
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "scrape_recap_archive",
  "params": {...},
  "id": 1
}
```

### 2. REST API (Fallback)

- `POST /api/mcp/dataset/recap/scrape` - scrape_recap_archive
- `POST /api/mcp/dataset/recap/search` - search_recap_documents  
- `POST /api/mcp/dataset/state_laws/scrape` - scrape_state_laws
- `POST /api/mcp/dataset/uscode/scrape` - scrape_us_code
- `GET /api/mcp/dataset/jobs` - list_scraping_jobs
- `GET /api/mcp/caselaw/tools` - Get all available MCP tools

## Setting Up Periodic Updates

### Quick Start

1. **Add a daily schedule for California and New York**:
```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron add \
    --schedule-id daily_ca_ny \
    --states CA,NY \
    --interval 24
```

2. **Add a weekly schedule for all states**:
```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron add \
    --schedule-id weekly_all \
    --states all \
    --interval 168
```

3. **Run the scheduler daemon**:
```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron daemon
```

### Systemd Service (Recommended for Production)

Create `/etc/systemd/system/state-laws-updater.service`:

```ini
[Unit]
Description=State Laws Auto-Updater
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME
ExecStart=/usr/bin/python3 -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron daemon --check-interval 300
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable state-laws-updater
sudo systemctl start state-laws-updater
sudo systemctl status state-laws-updater
```

## Resume Capability

All scraping operations support resume capability:

1. Each scraping job gets a unique `job_id`
2. State is saved periodically to `~/.ipfs_datasets/scraping_state/`
3. If interrupted, resume with the same `job_id` and `resume=True`
4. Already-processed items are skipped automatically

Example:
```python
# First run
result = await scrape_recap_archive(
    courts=['ca9'],
    job_id='my_long_job',
    max_documents=10000
)

# If interrupted, resume:
result = await scrape_recap_archive(
    courts=['ca9'],
    job_id='my_long_job',
    resume=True,
    max_documents=10000
)
```

## Testing

### Test RECAP Scraping
```bash
python test_recap_scraping.py
```

This tests:
- Search functionality
- Document retrieval
- Bulk scraping
- Resume capability

### Test Tool Discovery
```python
from ipfs_datasets_py.mcp_server.temporal_deontic_mcp_server import temporal_deontic_mcp_server

schemas = temporal_deontic_mcp_server.get_tool_schemas()
print(f"Available tools: {len(schemas)}")  # Should show 9
```

### Test Dashboard
1. Start the dashboard: `python -m ipfs_datasets_py.mcp_dashboard`
2. Navigate to: `http://127.0.0.1:8899/mcp/caselaw`
3. Check that it shows "9 tools available" instead of "4 tools"
4. Try the "Dataset Workflows" section

## Data Sources

### RECAP Archive
- **Source**: CourtListener.com RECAP Archive
- **API**: https://www.courtlistener.com/api/rest/v3/
- **Coverage**: Federal courts (District, Circuit, Supreme Court)
- **Data**: Opinions, dockets, complaints, motions, briefs, orders
- **Free**: Yes, no API key required
- **Rate Limit**: Respect 1-2 second delays between requests

### State Laws
- **Source**: Official state legislative websites
- **Coverage**: All 50 US states + DC
- **Data**: State codes, statutes, regulations
- **Implementation**: State-specific scrapers with normalized schema
- **Rate Limit**: 2-5 second delays (state sites are slower)

### US Code
- **Source**: U.S. Government Publishing Office
- **Coverage**: All 54 titles of US Code
- **Data**: Federal statutes organized by title and section
- **Free**: Yes, no API key required

## Storage

Data is stored in:
- **Scraping State**: `~/.ipfs_datasets/scraping_state/`
- **Schedules**: `~/.ipfs_datasets/schedules/`
- **Output**: `~/.ipfs_datasets/legal_datasets/` (configurable)

State files include:
- `{job_id}.json` - Metadata (status, progress, parameters)
- `{job_id}.pickle` - Data (scraped items, processed IDs)

## Best Practices

1. **Start Small**: Test with a few states/courts before scaling up
2. **Rate Limiting**: Use appropriate delays (1-2s for RECAP, 2-5s for state sites)
3. **Monitoring**: Check logs regularly in production
4. **Disk Space**: Full-text storage can be large; monitor disk usage
5. **Backup**: Regularly backup `~/.ipfs_datasets` directory
6. **Resume**: Use job_id for any job that might take >10 minutes

## Troubleshooting

### Dashboard shows 4 tools instead of 9
- Check `/api/mcp/caselaw/tools` endpoint returns all 9 tools
- Check browser console for JavaScript errors
- Verify temporal_deontic_mcp_server imports both tool lists

### Scraping fails immediately
- Check internet connectivity
- Verify requests library is installed: `pip install requests`
- Check source site is accessible (courtlistener.com for RECAP)

### Jobs won't resume
- Check state files exist in `~/.ipfs_datasets/scraping_state/`
- Verify job_id matches exactly
- Check file permissions on state directory

### Scheduler daemon not running
```bash
ps aux | grep state_laws_cron
sudo systemctl status state-laws-updater  # If using systemd
```

## Future Enhancements

Potential improvements:
- Add IPFS storage integration (code exists, needs testing)
- Implement Parquet export (code exists, needs testing)
- Add citation extraction and analysis
- Implement incremental updates for RECAP
- Add webhook notifications for completed jobs
- Create web UI for job management

## Support

For issues or questions:
- GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Check logs in `~/.ipfs_datasets/scraping_state/`
- See `CRON_SETUP_SIMPLE.md` for detailed setup instructions

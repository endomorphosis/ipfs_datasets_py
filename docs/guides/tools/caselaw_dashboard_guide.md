# Caselaw Dashboard User Guide

## Overview

The Caselaw Dashboard provides a comprehensive web interface for legal document analysis and dataset building. It combines temporal deontic logic analysis with practical legal dataset scraping tools.

**Dashboard URL:** `http://127.0.0.1:8899/mcp/caselaw`

## Features

### 1. Temporal Deontic Logic Analysis (4 Tools)

The dashboard provides advanced legal document analysis using temporal deontic logic:

- **Document Consistency Analysis**: Check legal documents for consistency against temporal deontic logic theorems
- **Query Theorems**: Search for relevant legal theorems using semantic search
- **Bulk Process Caselaw**: Process entire caselaw corpora to build unified deontic logic systems
- **Add Theorem**: Manually add theorems to the RAG store

### 2. Legal Dataset Scraping (13 Tools)

Build comprehensive legal datasets from multiple sources:

#### Dataset Scraping Tools (6 tools)
- `scrape_us_code`: Scrape United States Code statutes
- `scrape_federal_register`: Scrape Federal Register documents
- `scrape_state_laws`: Scrape state law statutes (all 50 states + DC)
- `scrape_municipal_laws`: Scrape municipal law ordinances
- `scrape_recap_archive`: Scrape RECAP court documents
- `search_recap_documents`: Search RECAP archive

#### Dataset Management Tools (2 tools)
- `list_scraping_jobs`: List all saved scraping jobs with resume capability
- `export_dataset`: Export datasets in JSON, Parquet, or CSV formats

#### Scheduling Tools (5 tools)
- `create_schedule`: Create periodic update schedules for automated data refresh
- `list_schedules`: List all configured update schedules
- `run_schedule_now`: Run a schedule immediately (useful for testing)
- `enable_disable_schedule`: Toggle schedule enabled status
- `remove_schedule`: Remove update schedules

**Total Tools Available:** 17 (4 deontic logic + 13 dataset tools)

## Quick Start

### 1. Starting the Dashboard

```bash
# Start the MCP dashboard
cd /path/to/ipfs_datasets_py
python -m ipfs_datasets_py.mcp_dashboard

# Or with custom port
MCP_DASHBOARD_PORT=8899 python -m ipfs_datasets_py.mcp_dashboard
```

### 2. Accessing the Dashboard

Open your web browser and navigate to:
```
http://127.0.0.1:8899/mcp/caselaw
```

The dashboard will show:
- **MCP Server Connection Status**: Should show "Connected" with "Tools: 17"
- **Navigation Tabs**: Document Analysis, Query Theorems, Bulk Processing, etc.
- **Dataset Workflows**: US Code, Federal Register, State Laws, Municipal Laws, RECAP Archive

## Using Dataset Workflows

### US Code & Federal Register Dataset Builder

1. Navigate to the "US Code & Federal Register" tab in Dataset Workflows
2. Select data sources:
   - ☑ US Code (federal statutory law)
   - ☑ Federal Register (federal regulations and notices)
3. Configure scraping:
   - **US Code Titles**: Select specific titles or "All Titles"
   - **Federal Agencies**: Select agencies (EPA, FDA, DOL, SEC, FTC, etc.)
   - **Date Range**: Set start/end dates for Federal Register documents
4. Click "Start Scraping" to begin
5. Monitor progress in real-time
6. Export data in JSON, Parquet, or CSV formats

**Example: Scrape Environmental Laws**
```
1. Select Federal Register only
2. Choose EPA agency
3. Set date range: Last 30 days
4. Start scraping
```

### State Laws Dataset Builder

1. Navigate to the "State Laws" tab in Dataset Workflows
2. Select states:
   - Choose specific states (CA, NY, TX, etc.)
   - Or select "All States" for comprehensive coverage
3. Filter by legal areas (optional):
   - Criminal, Civil, Family, Employment, Tax, Environmental, etc.
4. Select law types:
   - ☑ State Constitution
   - ☑ State Statutes  
   - ☑ State Regulations
   - ☑ Pending Legislation
5. Click "Start Scraping"
6. Monitor progress and export results

**Example: Scrape California Employment Law**
```
1. States: CA
2. Legal Areas: employment
3. Law Types: Statutes, Regulations
4. Start scraping
```

### Municipal Laws Dataset Builder

1. Navigate to the "Municipal Laws" tab
2. Enter cities (comma-separated):
   ```
   New York, Los Angeles, Chicago, Houston
   ```
3. Filter by ordinance types (optional)
4. Start scraping
5. Export results

### RECAP Archive (Court Documents)

1. Navigate to the "RECAP Archive" tab
2. Configure search:
   - **Courts**: Select specific courts or "All Federal Courts"
   - **Document Types**: Complaints, Motions, Orders, Opinions
   - **Date Range**: Filed after/before dates
   - **Case Name**: Optional pattern matching
3. Or use the Search tab for targeted queries
4. Start scraping
5. Export results

## Setting Up Periodic Updates

### Using the Setup Script

The easiest way to set up periodic updates is using the provided setup script:

```bash
cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools

# Set up daily US Code updates
python setup_periodic_updates.py --preset daily_us_code

# Set up daily Federal Register updates
python setup_periodic_updates.py --preset daily_federal_register

# Set up daily state laws updates (CA, NY, TX)
python setup_periodic_updates.py --preset daily_state_laws

# Set up weekly updates for all states
python setup_periodic_updates.py --preset weekly_all_states

# Set up all recommended presets at once
python setup_periodic_updates.py --preset all

# List existing schedules
python setup_periodic_updates.py --list

# Run a schedule immediately for testing
python setup_periodic_updates.py --run-now daily_us_code
```

### Interactive Custom Setup

For more control, use the interactive setup:

```bash
python setup_periodic_updates.py --custom
```

This will guide you through:
1. Selecting dataset type (US Code, Federal Register, State Laws)
2. Choosing update frequency (6 hours, daily, weekly, custom)
3. Configuring dataset-specific options

### Using Cron (Advanced)

For production deployments, you can use system cron:

```bash
# Edit crontab
crontab -e

# Add schedule checker to run every hour
0 * * * * cd /path/to/ipfs_datasets_py/mcp_server/tools/legal_dataset_tools && python state_laws_cron.py daemon --check-interval 60

# Or use the setup script with cron
0 2 * * * cd /path/to/ipfs_datasets_py/mcp_server/tools/legal_dataset_tools && python setup_periodic_updates.py --run-now daily_us_code
```

### Managing Schedules via Dashboard

You can also manage schedules directly through the dashboard:

1. Navigate to the "Scheduling" section
2. View all active schedules
3. Create, enable, disable, or remove schedules
4. Run schedules immediately for testing

## API Endpoints

All functionality is also available via REST API:

### Dataset Scraping Endpoints

```bash
# US Code
curl -X POST http://127.0.0.1:8899/api/mcp/dataset/uscode/scrape \
  -H "Content-Type: application/json" \
  -d '{"titles": ["1", "15"], "output_format": "json"}'

# Federal Register
curl -X POST http://127.0.0.1:8899/api/mcp/dataset/federal_register/scrape \
  -H "Content-Type: application/json" \
  -d '{"agencies": ["EPA"], "start_date": "2024-01-01"}'

# State Laws
curl -X POST http://127.0.0.1:8899/api/mcp/dataset/state_laws/scrape \
  -H "Content-Type: application/json" \
  -d '{"states": ["CA", "NY"], "legal_areas": ["employment"]}'

# Municipal Laws
curl -X POST http://127.0.0.1:8899/api/mcp/dataset/municipal_laws/scrape \
  -H "Content-Type: application/json" \
  -d '{"cities": ["New York", "Los Angeles"]}'

# RECAP Archive
curl -X POST http://127.0.0.1:8899/api/mcp/dataset/recap/scrape \
  -H "Content-Type: application/json" \
  -d '{"courts": ["ca1"], "document_types": ["OPINION"]}'
```

### Schedule Management Endpoints

```bash
# List schedules
curl http://127.0.0.1:8899/api/mcp/dataset/state_laws/schedules

# Create schedule
curl -X POST http://127.0.0.1:8899/api/mcp/dataset/state_laws/schedules \
  -H "Content-Type: application/json" \
  -d '{"schedule_id": "daily_ca", "states": ["CA"], "interval_hours": 24}'

# Run schedule now
curl -X POST http://127.0.0.1:8899/api/mcp/dataset/state_laws/schedules/daily_ca/run

# Enable/disable schedule
curl -X POST http://127.0.0.1:8899/api/mcp/dataset/state_laws/schedules/daily_ca/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'

# Delete schedule
curl -X DELETE http://127.0.0.1:8899/api/mcp/dataset/state_laws/schedules/daily_ca
```

## Data Storage

### Default Locations

- **Schedules**: `~/.ipfs_datasets/state_laws/schedule.json`
- **Scraped Data**: `~/.ipfs_datasets/state_laws/state_laws_<schedule_id>_<timestamp>.json`
- **US Code Data**: `~/.ipfs_datasets/us_code/`
- **Federal Register**: `~/.ipfs_datasets/federal_register/`
- **RECAP Archive**: `~/.ipfs_datasets/recap/`

### Export Formats

All scrapers support multiple export formats:

- **JSON**: Standard JSON with pretty-printing
- **Parquet**: Apache Parquet with compression (snappy/gzip/brotli)
- **CSV**: Standard CSV with configurable delimiter

## Troubleshooting

### Dashboard shows "Disconnected"

1. Check if MCP dashboard is running:
   ```bash
   ps aux | grep mcp_dashboard
   ```
2. Restart the dashboard:
   ```bash
   python -m ipfs_datasets_py.mcp_dashboard
   ```

### Tool count shows less than 17

1. Clear browser cache
2. Refresh the page (Ctrl+F5)
3. Check browser console for JavaScript errors

### Scraping fails

1. Check network connectivity
2. Verify rate limiting settings (increase delay if getting errors)
3. Check logs for specific error messages
4. Try reducing `max_sections` or `max_documents` parameters

### Schedule not running

1. List schedules to verify configuration:
   ```bash
   python setup_periodic_updates.py --list
   ```
2. Test schedule manually:
   ```bash
   python setup_periodic_updates.py --run-now <schedule_id>
   ```
3. Check schedule is enabled (not disabled)
4. Verify daemon is running if using cron

## Best Practices

1. **Rate Limiting**: Always use appropriate rate limiting to be respectful to source websites
   - US Code: 1.0 second delay
   - Federal Register: 1.0 second delay
   - State Laws: 2.0 second delay minimum
   - RECAP Archive: 1.0 second delay

2. **Start Small**: Test with limited data before running full scrapes
   - Use `max_sections`, `max_documents`, or `max_statutes` parameters
   - Start with single states or specific titles

3. **Monitoring**: Check progress regularly
   - Monitor disk space usage
   - Review logs for errors
   - Verify data quality in exports

4. **Scheduling**: Use appropriate update frequencies
   - US Code: Daily or weekly (changes infrequently)
   - Federal Register: Daily (updates frequently)
   - State Laws: Weekly or monthly (changes moderately)

5. **Backup**: Regularly backup your schedule configurations and scraped data

## Support

For issues or questions:
- Check the main README: `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/README.md`
- Review CRON_SETUP_GUIDE.md for detailed scheduling instructions
- Check test files for usage examples: `test_*.py`
- Review validation reports for known issues

## Additional Resources

- **State Laws Scraper Details**: See `state_laws_scraper.py`
- **US Code Scraper Details**: See `us_code_scraper.py`
- **Federal Register Scraper Details**: See `federal_register_scraper.py`
- **Cron Setup Guide**: See `CRON_SETUP_GUIDE.md`
- **Testing Guide**: See `TESTING_GUIDE.md`

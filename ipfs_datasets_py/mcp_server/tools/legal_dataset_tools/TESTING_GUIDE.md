# State Scraper Testing with Parquet Output

## Overview

This directory contains comprehensive test scripts that validate all 51 state law scrapers by actually scraping real data from official state legislative websites and saving the results to parquet files for inspection and validation.

## Test Scripts

### 1. `test_sample_states.py` - Quick Sample Test

Tests a representative sample of 5 states to quickly verify functionality:
- California (large state, detailed implementation)
- New York (large state, detailed implementation)
- Texas (large state, detailed implementation)
- Illinois (medium state)
- Wyoming (small state)

**Usage:**
```bash
cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools
python3 test_sample_states.py
```

**Output:**
- Parquet files saved to: `~/.ipfs_datasets/state_laws/test_samples_quick/`
- Test summary JSON: `test_summary.json`
- JSON backups in: `json_backup/` subdirectory

**Duration:** ~2-5 minutes

### 2. `test_all_states_with_parquet.py` - Comprehensive Test

Tests all 51 US jurisdictions (50 states + DC) by scraping real data from each state's official legislative website.

**Usage:**
```bash
cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools
python3 test_all_states_with_parquet.py
```

**Output:**
- Parquet files saved to: `~/.ipfs_datasets/state_laws/test_samples/`
- One parquet file per state: `<STATE_CODE>_sample.parquet`
- Test summary JSON: `test_summary.json`
- JSON backups in: `json_backup/` subdirectory

**Duration:** ~15-30 minutes (depends on network and state website response times)

## What the Tests Do

### For Each State:

1. **Initialize Scraper**: Gets the state-specific scraper class
2. **Fetch Metadata**: Retrieves base URL and available codes/statutes
3. **Scrape Sample Data**: Scrapes up to 10 statutes from the first available code
4. **Validate Schema**: Verifies all required fields are present in normalized format
5. **Save to Parquet**: Stores results in Apache Parquet format for efficient storage
6. **Save to JSON**: Creates JSON backup for easy inspection
7. **Generate Report**: Creates summary with success/failure statistics

### Concurrent Processing:

- Tests run with limited concurrency (3 states at a time) to respect source websites
- Rate limiting enforced (2 seconds between requests per scraper)
- Graceful error handling ensures one failure doesn't stop other tests

## Output Format

### Parquet Files

Each state's parquet file contains the following columns (NormalizedStatute schema):

- `state_code`: Two-letter state code (e.g., "CA")
- `state_name`: Full state name (e.g., "California")
- `statute_id`: Unique identifier for the statute
- `code_name`: Name of the legal code (e.g., "Penal Code")
- `section_number`: Section number within the code
- `section_name`: Human-readable section name
- `full_text`: Full text of the statute
- `legal_area`: Detected legal area (criminal, civil, family, etc.)
- `source_url`: Official state legislative website URL
- `official_cite`: Proper legal citation format
- `scraped_at`: Timestamp when scraped
- `scraper_version`: Version of the scraper used
- `metadata`: Additional metadata (effective dates, amendments, etc.)

### Test Summary JSON

Contains comprehensive test results:

```json
{
  "test_start": "2025-10-16T08:00:00",
  "test_end": "2025-10-16T08:25:00",
  "duration_seconds": 1500,
  "total_states": 51,
  "successful": 51,
  "failed": 0,
  "total_statutes_scraped": 510,
  "parquet_files": 51,
  "json_files": 51,
  "results": {
    "CA": {
      "state_code": "CA",
      "state_name": "California",
      "success": true,
      "scraped_count": 10,
      "base_url": "https://leginfo.legislature.ca.gov",
      "codes_available": 29
    },
    ...
  }
}
```

## Inspecting Results

### Using Python with Pandas:

```python
import pandas as pd

# Load a state's parquet file
df = pd.read_parquet("~/.ipfs_datasets/state_laws/test_samples/CA_sample.parquet")

# View summary
print(df.info())
print(df.head())

# Check specific columns
print(df[['statute_id', 'official_cite', 'legal_area']])

# Filter by legal area
criminal = df[df['legal_area'] == 'criminal']
print(f"Criminal statutes: {len(criminal)}")
```

### Using JSON Files:

```python
import json

with open("~/.ipfs_datasets/state_laws/test_samples/json_backup/CA_sample.json") as f:
    data = json.load(f)

for statute in data:
    print(f"{statute['official_cite']}: {statute['section_name']}")
```

### Command Line:

```bash
# View parquet file structure
parquet-tools schema ~/.ipfs_datasets/state_laws/test_samples/CA_sample.parquet

# View JSON with jq
cat ~/.ipfs_datasets/state_laws/test_samples/json_backup/CA_sample.json | jq '.[0]'
```

## Validations Performed

1. **File Structure**: Verifies all 51 state scraper files exist
2. **Class Registration**: Confirms all scrapers registered with StateScraperRegistry
3. **Interface Implementation**: Checks required methods implemented
4. **Real Data Scraping**: Actually fetches data from official state websites
5. **Schema Validation**: Verifies normalized schema across all states
6. **Data Persistence**: Ensures data can be saved to parquet format
7. **Error Handling**: Tests graceful degradation on network errors

## Prerequisites

Required packages (already in requirements.txt):
- `pandas>=1.5.0`
- `pyarrow>=15.0.0`
- `requests>=2.28.0`
- `beautifulsoup4>=4.11.0`

## Troubleshooting

### Network Errors:

Some state websites may be temporarily unavailable or block automated access. The tests handle this gracefully:

```
⚠️  Failed to scrape <STATE>: Connection timeout
```

This is expected behavior and doesn't indicate a problem with the scraper.

### Rate Limiting:

If you see many timeouts, the websites may be rate limiting. The tests include:
- 2-second delay between requests
- Maximum 3 concurrent scrapers
- Automatic retries with exponential backoff

### Parquet Installation:

If pandas/pyarrow aren't installed:

```bash
pip install pandas pyarrow
```

The test script will attempt to install automatically if missing.

## Integration with CI/CD

### GitHub Actions Example:

```yaml
- name: Test State Scrapers
  run: |
    cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools
    python3 test_all_states_with_parquet.py
    
- name: Upload Test Results
  uses: actions/upload-artifact@v3
  with:
    name: state-scraper-test-results
    path: ~/.ipfs_datasets/state_laws/test_samples/
```

### Local Development:

```bash
# Quick check before committing
python3 test_sample_states.py

# Full validation before release
python3 test_all_states_with_parquet.py
```

## Success Criteria

Tests pass when:
- ✅ All 51 state scrapers successfully scrape data
- ✅ All parquet files created with valid data
- ✅ All schemas validated
- ✅ No critical errors in summary report

Tests may have warnings but still pass if:
- ⚠️  Some states timeout (network issues)
- ⚠️  Some states return fewer than 10 statutes (limited data)

These are documented in the summary report for investigation.

## Benefits

1. **Real Validation**: Tests actually scrape real webpages, not mocks
2. **Persistent Samples**: Parquet files saved for inspection and debugging
3. **Comprehensive Coverage**: All 51 jurisdictions tested
4. **Schema Verification**: Ensures normalized output across all states
5. **Performance Testing**: Measures scraping time and throughput
6. **Documentation**: Creates detailed report for review

## Next Steps

After running tests:

1. Review `test_summary.json` for overall results
2. Inspect parquet files for individual states
3. Investigate any failed states
4. Enhance specific state scrapers as needed
5. Re-run tests to verify fixes

## Support

For issues or questions about the test suite:
- Review VALIDATION_REPORT.md for validation methodology
- Check IMPLEMENTATION_SUMMARY.md for technical details
- See state_scrapers/README.md for scraper architecture

# Legal Dataset Scraper Verification Tools

This directory contains comprehensive verification tools for the US Code and Federal Register scrapers.

## Overview

These tools test the functionality of the legal dataset scrapers to ensure they are working correctly. They perform multiple tests including connectivity, data scraping, structure validation, and parameter testing.

## Verification Tools

### 1. US Code Scraper Verification (`verify_us_code_scraper.py`)

Tests the US Code scraper with the following checks:

**Tests Performed:**
- ✅ Get US Code Titles - Verifies retrieval of all 54 US Code titles
- ✅ Scrape Single Title - Tests scraping Title 1 (General Provisions)
- ✅ Scrape Multiple Titles - Tests scraping Titles 1, 15, and 18 simultaneously
- ✅ Validate Data Structure - Ensures scraped data has required fields
- ✅ Search Functionality - Tests search capabilities with keywords
- ✅ Metadata Inclusion - Verifies metadata is included/excluded correctly
- ✅ Rate Limiting - Confirms rate limiting is respected

**Usage:**
```bash
# Run US Code verification
python verify_us_code_scraper.py

# Or run directly
./verify_us_code_scraper.py
```

**Output:**
- Console output with detailed test results
- JSON results saved to: `~/.ipfs_datasets/us_code/verification_results.json`

### 2. Federal Register Scraper Verification (`verify_federal_register_scraper.py`)

Tests the Federal Register scraper with the following checks:

**Tests Performed:**
- ✅ Search Recent Documents - Tests searching last 7 days of documents
- ✅ Scrape by Agency - Tests scraping EPA documents specifically
- ✅ Scrape Multiple Agencies - Tests scraping EPA and FDA simultaneously
- ✅ Filter by Document Types - Tests filtering for RULE documents
- ✅ Validate Data Structure - Ensures scraped data has required fields
- ✅ Search with Keywords - Tests keyword search functionality
- ✅ Full Text Inclusion - Verifies full text can be included/excluded
- ✅ Rate Limiting - Confirms rate limiting is respected

**Usage:**
```bash
# Run Federal Register verification
python verify_federal_register_scraper.py

# Or run directly
./verify_federal_register_scraper.py
```

**Output:**
- Console output with detailed test results
- JSON results saved to: `~/.ipfs_datasets/federal_register/verification_results.json`

### 3. Unified Verification Runner (`verify_all_scrapers.py`)

Runs both verification tools and provides a combined summary.

**Usage:**
```bash
# Run all verifications
python verify_all_scrapers.py

# Or run directly
./verify_all_scrapers.py
```

**Output:**
- Combined console output from both verifications
- Individual JSON results saved to respective directories
- Overall pass/fail status

## Quick Start

### Run All Verifications

```bash
cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools
python verify_all_scrapers.py
```

### Run Individual Verifications

```bash
# US Code only
python verify_us_code_scraper.py

# Federal Register only
python verify_federal_register_scraper.py
```

## Test Results

Each verification tool provides:

1. **Console Output**: Real-time progress with pass/fail indicators
   - ✅ Green checkmark for passed tests
   - ❌ Red X for failed tests
   - ⚠️ Yellow warning for partial successes

2. **JSON Results**: Detailed test results saved to disk
   - Test name, status, message
   - Detailed information about each test
   - Summary statistics

3. **Exit Code**: 
   - `0` = All tests passed
   - `1` = One or more tests failed

## Example Output

```
================================================================================
US CODE SCRAPER VERIFICATION
================================================================================
Started at: 2024-01-15 10:30:00

================================================================================
TEST 1: Get US Code Titles
================================================================================
✅ Get Titles: Retrieved 54 US Code titles
   Details: {
     "title_count": 54,
     "sample_titles": [["1", "General Provisions"], ["2", "The Congress"], ...]
   }

================================================================================
TEST 2: Scrape Single Title (Title 1 - General Provisions)
================================================================================
✅ Scrape Single Title: Scraped Title 1: 10 sections
   Details: {
     "sections_count": 10,
     "sample_section": {...},
     "metadata": {...}
   }

...

================================================================================
VERIFICATION SUMMARY
================================================================================
Total Tests: 7
✅ Passed: 6
❌ Failed: 0
⚠️  Warnings: 1

Success Rate: 85.7%

📁 Results saved to: ~/.ipfs_datasets/us_code/verification_results.json
```

## Understanding Results

### Test Statuses

- **PASS (✅)**: Test completed successfully with expected results
- **FAIL (❌)**: Test encountered an error or produced unexpected results
- **WARN (⚠️)**: Test completed but with caveats or partial results

### Common Issues

1. **Network Connectivity**: Some tests require internet access to government websites
   - Solution: Ensure stable internet connection

2. **Rate Limiting**: Tests may take time due to built-in rate limiting
   - Expected: Tests should take 30-60 seconds to complete
   - This is normal and indicates rate limiting is working

3. **Data Availability**: Some date ranges may have no documents
   - This is expected and will result in WARN status
   - Does not indicate a failure of the scraper

4. **Missing Dependencies**: Tests require `requests` and `beautifulsoup4`
   - Solution: `pip install requests beautifulsoup4`

## Integration with CI/CD

These verification tools can be integrated into CI/CD pipelines:

```bash
# Run verifications as part of CI
python verify_all_scrapers.py

# Check exit code
if [ $? -eq 0 ]; then
    echo "All scrapers verified successfully"
else
    echo "Scraper verification failed"
    exit 1
fi
```

## Troubleshooting

### All Tests Failing

1. Check internet connectivity
2. Verify dependencies are installed: `pip install requests beautifulsoup4`
3. Check if government websites are accessible:
   - https://uscode.house.gov
   - https://www.federalregister.gov

### Specific Test Failing

1. Review the detailed error message in the output
2. Check the JSON results file for more details
3. Run the specific scraper function manually to debug

### Timeout Issues

If tests timeout:
1. Increase the timeout in `verify_all_scrapers.py` (default: 300 seconds)
2. Check network speed
3. Run individual verifications instead of unified runner

## Manual Testing

You can also test the scrapers manually:

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
    scrape_us_code,
    scrape_federal_register
)

# Test US Code scraper
async def test_us_code():
    result = await scrape_us_code(
        titles=["1"],
        max_sections=5
    )
    print(result)

# Test Federal Register scraper
async def test_fed_reg():
    result = await scrape_federal_register(
        agencies=["EPA"],
        max_documents=5
    )
    print(result)

# Run tests
asyncio.run(test_us_code())
asyncio.run(test_fed_reg())
```

## Support

For issues or questions:
- Check the main README: `../README.md`
- Review test output and JSON results
- Ensure all dependencies are installed
- Verify network connectivity to government websites

## Related Documentation

- **Main README**: `../README.md` - Overview of all legal dataset tools
- **CRON_SETUP_GUIDE**: `../CRON_SETUP_GUIDE.md` - Setting up periodic updates
- **TESTING_GUIDE**: `../TESTING_GUIDE.md` - General testing guidelines

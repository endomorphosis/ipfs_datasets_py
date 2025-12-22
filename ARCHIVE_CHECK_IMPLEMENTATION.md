# Archive Check and Submit Implementation Summary

## Overview

Implemented automatic archive checking and submission functionality for the unified web scraper, allowing it to check Archive.org (Wayback Machine) and Archive.is before scraping pages, and automatically submit pages to these archives if not already present.

## Files Created

### 1. Core Implementation
- **`ipfs_datasets_py/mcp_server/tools/web_archive_tools/archive_check_submit.py`**
  - New tool for checking and submitting URLs to web archives
  - Functions:
    - `check_and_submit_to_archives()` - Main function for checking and submitting single URLs
    - `batch_check_and_submit()` - Batch operation for multiple URLs
    - `_check_archive_org()` - Check if URL exists in Archive.org
    - `_check_archive_is()` - Check if URL exists in Archive.is
    - `_submit_to_archive_org()` - Submit URL to Archive.org
    - `_submit_to_archive_is()` - Submit URL to Archive.is
  - Features:
    - Automatic detection of existing archives
    - Conditional submission only if not present
    - Optional waiting for archive completion
    - Comprehensive error handling
    - Detailed result metadata

### 2. Unified Web Scraper Integration
- **`ipfs_datasets_py/unified_web_scraper.py`** (modified)
  - Added configuration options to `ScraperConfig`:
    - `archive_check_before_scrape` - Enable/disable archive checking
    - `archive_check_wayback` - Check Archive.org
    - `archive_check_archive_is` - Check Archive.is
    - `archive_submit_if_missing` - Submit if not present
    - `archive_wait_for_completion` - Wait for archiving to complete
    - `archive_submission_timeout` - Timeout for submissions
  - Modified `scrape()` method to:
    - Check archives before scraping (if enabled)
    - Submit to archives if not present
    - Continue with normal scraping regardless of archive status
    - Include archive check results in metadata

### 3. Documentation
- **`docs/archive_check_and_submit.md`**
  - Comprehensive documentation covering:
    - Configuration options
    - Usage examples (basic, batch, legal scrapers)
    - Response format
    - Best practices
    - Rate limiting considerations
    - Error handling
    - API reference

### 4. Demo Scripts
- **`scripts/demo/demo_archive_check_scraper.py`**
  - Demonstrates 4 key use cases:
    1. Basic archive check and submit
    2. Batch archive checking
    3. Legal scraper with archive protection
    4. Check-only mode (no submission)
  - Shows how to:
    - Configure the scraper
    - Access archive check results
    - Handle batch operations
    - Use with legal content

- **`scripts/legal/example_legal_scraper_with_archives.py`**
  - Legal scraper-specific examples
  - 4 comprehensive examples:
    1. Simple legal scraper with archive protection
    2. Batch archive legal URLs
    3. Legal scraper with verification workflow
    4. Generate archive status report
  - Demonstrates best practices for legal content preservation

### 5. Tests
- **`tests/unit/test_archive_check_submit.py`**
  - Comprehensive test suite covering:
    - Archive checking (present/not present)
    - Submission functionality
    - Batch operations
    - Error handling
    - Selective archive checking
    - Integration with unified scraper
    - Continuation on errors
  - Uses mocking to avoid actual network calls
  - Tests both success and failure scenarios

## Key Features

### 1. Automatic Archive Detection
- Checks Archive.org (Wayback Machine) for existing snapshots
- Checks Archive.is for permanent archives
- Returns archive URLs when found
- No unnecessary submissions to archives that already have the content

### 2. Conditional Submission
- Only submits to archives if not already present
- Can be configured to submit to one or both archives
- Optional waiting for archive completion
- Timeout protection

### 3. Non-Blocking Operation
- Archive checks don't block scraping
- If archive check fails, scraping continues
- Errors are logged but don't prevent data collection
- All archive results included in scraping metadata

### 4. Batch Operations
- Efficient batch checking of multiple URLs
- Configurable concurrency limits
- Rate limiting to respect archive services
- Aggregated statistics and results

### 5. Flexible Configuration
- Enable/disable per-archive checking
- Control submission behavior
- Set timeouts and delays
- Configure wait behavior

## Usage Patterns

### Basic Usage
```python
from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig

config = ScraperConfig(
    archive_check_before_scrape=True,
    archive_submit_if_missing=True
)

scraper = UnifiedWebScraper(config=config)
result = await scraper.scrape("https://example.com")

# Access archive info
archive_info = result.metadata.get("archive_check", {})
```

### Legal Scraper Integration
```python
config = ScraperConfig(
    archive_check_before_scrape=True,
    archive_check_wayback=True,
    archive_check_archive_is=True,
    archive_submit_if_missing=True,
    rate_limit_delay=2.0  # Be respectful
)

scraper = UnifiedWebScraper(config=config)
result = await scraper.scrape("https://www.supremecourt.gov/opinions")
```

### Batch Archive Checking
```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit import batch_check_and_submit

result = await batch_check_and_submit(
    urls=["https://url1.com", "https://url2.com"],
    check_archive_org=True,
    check_archive_is=True,
    submit_if_missing=True,
    max_concurrent=3
)
```

## Integration Points

### Existing Web Archive Tools
Integrates with existing MCP tools:
- `wayback_machine_search.py` - For Archive.org operations
- `archive_is_integration.py` - For Archive.is operations
- Both tools already implement search and submission functions

### Unified Web Scraper
Seamlessly integrates into the scraping workflow:
- Runs before any scraping method is attempted
- Adds metadata to scraping results
- Doesn't interfere with fallback chain
- Works with all scraping methods

### Legal Scrapers
Perfect for legal dataset scrapers where content preservation is critical:
- Ensures court decisions are archived
- Prevents loss of legal documents
- Provides timestamp proof of content
- Creates redundant archives

## Benefits

### For Legal Content
1. **Preservation** - Legal documents are automatically preserved
2. **Redundancy** - Multiple archives provide backup
3. **Provenance** - Timestamp proof of content existence
4. **Compliance** - Helps meet data retention requirements

### For All Scrapers
1. **Responsible Scraping** - Reduces need for repeated scraping
2. **Data Safety** - Content preserved even if source disappears
3. **Historical Access** - Archived versions available for research
4. **Minimal Overhead** - Non-blocking, doesn't slow down scraping

## Configuration Best Practices

### For Production Use
```python
config = ScraperConfig(
    archive_check_before_scrape=True,
    archive_submit_if_missing=True,
    archive_wait_for_completion=False,  # Don't block
    archive_submission_timeout=60,
    rate_limit_delay=1.0  # Respect archives
)
```

### For Critical Legal Content
```python
config = ScraperConfig(
    archive_check_before_scrape=True,
    archive_check_wayback=True,
    archive_check_archive_is=True,
    archive_submit_if_missing=True,
    archive_wait_for_completion=True,  # Ensure archived
    archive_submission_timeout=120,  # More time
    rate_limit_delay=2.0  # Be extra respectful
)
```

### For Development/Testing
```python
config = ScraperConfig(
    archive_check_before_scrape=True,
    archive_submit_if_missing=False,  # Check only
    rate_limit_delay=0.5
)
```

## Testing

Run the test suite:
```bash
cd /home/devel/ipfs_datasets_py
pytest tests/unit/test_archive_check_submit.py -v
```

Run the demo scripts:
```bash
# General demo
python scripts/demo/demo_archive_check_scraper.py

# Legal scraper examples
python scripts/legal/example_legal_scraper_with_archives.py
```

## Future Enhancements

Potential improvements:
1. Add support for more archive services (Archive.today, Perma.cc)
2. Implement archive priority/preference system
3. Add archive health checking
4. Create archive synchronization tools
5. Add archive quality metrics
6. Implement automatic re-archiving for stale content

## Notes

- Archive services have rate limits - always use appropriate delays
- Archive submission can take time - set `archive_wait_for_completion=False` for better performance
- Archive checking is non-blocking - scraping continues even if archives fail
- All errors are logged but don't prevent scraping
- Archive URLs are included in scraping metadata for reference

## Related Files

- `ipfs_datasets_py/unified_web_scraper.py` - Main scraper with integration
- `ipfs_datasets_py/mcp_server/tools/web_archive_tools/wayback_machine_search.py` - Archive.org tools
- `ipfs_datasets_py/mcp_server/tools/web_archive_tools/archive_is_integration.py` - Archive.is tools
- `ipfs_datasets_py/advanced_web_archiving.py` - Advanced archiving system
- `docs/archive_check_and_submit.md` - Full documentation

## Contact/Support

This feature integrates with the existing IPFS Datasets Python infrastructure.
See the main documentation for more information about the unified web scraper and legal scrapers.

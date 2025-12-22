# Archive Check and Submit Integration

## Overview

The unified web scraper now includes automatic archive checking and submission functionality. Before scraping a page, the scraper can:

1. **Check** if the URL is already archived on Archive.org (Wayback Machine) and/or Archive.is
2. **Submit** the URL to these archives if not already present
3. **Continue** with normal scraping operations

This ensures that important content (especially legal documents, court decisions, and other critical information) is preserved in multiple archives before being scraped.

## Why This Matters

- **Preservation**: Legal content and government websites can change or disappear
- **Redundancy**: Multiple archives provide backup if one service is unavailable
- **Provenance**: Archived snapshots provide timestamp proof of content existence
- **Responsible Scraping**: Archives reduce the need for repeated scraping of the same content

## Configuration

### ScraperConfig Options

```python
from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig

config = ScraperConfig(
    # Enable archive checking before scraping
    archive_check_before_scrape=True,
    
    # Which archives to check
    archive_check_wayback=True,      # Check Archive.org Wayback Machine
    archive_check_archive_is=True,   # Check Archive.is
    
    # Submission settings
    archive_submit_if_missing=True,  # Submit if not found in archives
    archive_wait_for_completion=False,  # Wait for archiving to complete
    archive_submission_timeout=60    # Timeout for archive submissions (seconds)
)

scraper = UnifiedWebScraper(config=config)
```

## Usage Examples

### Basic Usage

```python
import asyncio
from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig

async def scrape_with_archive_check():
    config = ScraperConfig(
        archive_check_before_scrape=True,
        archive_submit_if_missing=True
    )
    
    scraper = UnifiedWebScraper(config=config)
    
    result = await scraper.scrape("https://www.supremecourt.gov")
    
    # Check archive status
    if result.metadata and "archive_check" in result.metadata:
        archive_info = result.metadata["archive_check"]
        print(f"Archive.org present: {archive_info['archive_org_present']}")
        print(f"Archive.is present: {archive_info['archive_is_present']}")
        print(f"Summary: {archive_info['summary']}")
    
    return result

asyncio.run(scrape_with_archive_check())
```

### Batch Archive Checking

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit import batch_check_and_submit

async def check_multiple_urls():
    urls = [
        "https://www.supremecourt.gov",
        "https://www.law.cornell.edu",
        "https://www.courtlistener.com"
    ]
    
    result = await batch_check_and_submit(
        urls=urls,
        check_archive_org=True,
        check_archive_is=True,
        submit_if_missing=True,
        max_concurrent=3,
        delay_seconds=1.0
    )
    
    print(f"Total: {result['total_urls']}")
    print(f"Already archived: {result['already_archived_count']}")
    print(f"Submitted: {result['submitted_count']}")
    
    return result

asyncio.run(check_multiple_urls())
```

### Check Only (No Submission)

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit import check_and_submit_to_archives

async def check_archive_status():
    result = await check_and_submit_to_archives(
        url="https://www.courtlistener.com",
        check_archive_org=True,
        check_archive_is=True,
        submit_if_missing=False  # Only check, don't submit
    )
    
    print(f"Archive.org: {result['archive_org_present']}")
    print(f"Archive.is: {result['archive_is_present']}")
    print(f"Recommendation: {result['recommendation']}")
    
    return result

asyncio.run(check_archive_status())
```

### Legal Scraper with Archive Protection

```python
async def scrape_legal_content():
    config = ScraperConfig(
        # Enable archive protection
        archive_check_before_scrape=True,
        archive_check_wayback=True,
        archive_check_archive_is=True,
        archive_submit_if_missing=True,
        
        # Be respectful to legal sites
        rate_limit_delay=2.0,
        timeout=30,
        max_retries=3
    )
    
    scraper = UnifiedWebScraper(config=config)
    
    legal_urls = [
        "https://www.supremecourt.gov/opinions/opinions.aspx",
        "https://www.law.cornell.edu/supremecourt/text/home"
    ]
    
    results = []
    for url in legal_urls:
        result = await scraper.scrape(url)
        results.append(result)
        
        # Access archive information
        if result.metadata and "archive_check" in result.metadata:
            archive = result.metadata["archive_check"]
            
            if archive.get("archive_org_url"):
                print(f"Archived at: {archive['archive_org_url']}")
            
            if archive.get("submitted_to_archive_org"):
                print(f"Submitted to Archive.org for preservation")
    
    return results

asyncio.run(scrape_legal_content())
```

## Response Format

### Archive Check Result

```python
{
    "status": "success",
    "url": "https://example.com",
    "archive_org_present": True,
    "archive_is_present": False,
    "archive_org_url": "https://web.archive.org/web/20231215120000/https://example.com",
    "archive_is_url": None,
    "submitted_to_archive_org": False,
    "submitted_to_archive_is": True,
    "archive_org_submission_result": None,
    "archive_is_submission_result": {
        "status": "success",
        "archive_url": "https://archive.is/abc123",
        "submission_id": "xyz789"
    },
    "timestamp": "2024-01-15T10:30:00",
    "summary": "found in Archive.org, submitted to Archive.is",
    "recommendation": "URL is archived - safe to proceed with scraping"
}
```

## Integration with Legal Scrapers

This feature is particularly useful for legal dataset scrapers where content preservation is critical:

```python
from ipfs_datasets_py.legal_scrapers import create_legal_scraper

# Create a legal scraper with archive protection
scraper = create_legal_scraper(
    scraper_type="supreme_court",
    config={
        "archive_check_before_scrape": True,
        "archive_submit_if_missing": True
    }
)

# Scrape with automatic archiving
opinions = await scraper.scrape_opinions(year=2024)
```

## Best Practices

1. **Enable for Important Content**: Always enable for legal, government, and research content
2. **Use Batch Operations**: For multiple URLs, use `batch_check_and_submit` for efficiency
3. **Don't Wait by Default**: Set `archive_wait_for_completion=False` to avoid blocking
4. **Rate Limiting**: Use appropriate delays to avoid overwhelming archive services
5. **Check Before Submit**: The system automatically checks before submitting to avoid duplicates
6. **Monitor Results**: Always check the `archive_check` metadata in scraping results

## Rate Limiting

Archive services have rate limits. The implementation includes:

- Default delays between operations (1 second)
- Configurable max concurrent operations (default: 5)
- Automatic backoff on errors
- Timeout protection (default: 60 seconds)

## Error Handling

The archive check and submit operations are designed to be non-blocking:

- If archive checking fails, scraping continues normally
- Failed submissions are logged but don't stop the scrape
- All errors are captured in the result metadata
- Original scraping operation is never blocked by archive operations

## Demo Script

Run the comprehensive demo to see all features in action:

```bash
cd /home/devel/ipfs_datasets_py
python scripts/demo/demo_archive_check_scraper.py
```

The demo shows:
1. Basic archive check and submit
2. Batch archive checking
3. Legal scraper with archive protection
4. Check-only mode (no submission)

## API Reference

### `check_and_submit_to_archives()`

Check if URL is archived and submit if not present.

**Parameters:**
- `url` (str): URL to check and archive
- `check_archive_org` (bool): Check Archive.org Wayback Machine (default: True)
- `check_archive_is` (bool): Check Archive.is (default: True)
- `submit_if_missing` (bool): Submit to archives if not present (default: True)
- `wait_for_archive_completion` (bool): Wait for archiving to complete (default: False)
- `archive_timeout` (int): Maximum time to wait for archiving in seconds (default: 60)

**Returns:** Dict with archive check results

### `batch_check_and_submit()`

Batch check and submit multiple URLs to archives.

**Parameters:**
- `urls` (List[str]): List of URLs to check and archive
- `check_archive_org` (bool): Check Archive.org (default: True)
- `check_archive_is` (bool): Check Archive.is (default: True)
- `submit_if_missing` (bool): Submit if not present (default: True)
- `max_concurrent` (int): Maximum concurrent checks (default: 5)
- `delay_seconds` (float): Delay between operations (default: 1.0)

**Returns:** Dict with batch results

## See Also

- [Unified Web Scraper Documentation](unified_web_scraper.md)
- [Legal Scrapers Documentation](legal_scrapers.md)
- [Web Archive Tools](../ipfs_datasets_py/mcp_server/tools/web_archive_tools/)

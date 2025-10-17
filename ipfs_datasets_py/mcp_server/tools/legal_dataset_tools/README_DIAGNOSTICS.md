# Diagnostic Testing Guide

This directory contains diagnostic tools to test and fix failing state law scrapers.

## Quick Start

### 1. Run Diagnostic Tests

From your VSCode desktop with network access:

```bash
cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools
python diagnostic_test_states.py
```

This will:
- Test all 11 failing states
- Save detailed diagnostics to `diagnostic_results/`
- Save HTML samples for analysis
- Provide specific recommendations for each state
- Try fallback methods (Internet Archive, HTTP/HTTPS alternatives)

### 2. Review Results

Check the output directory:
```
diagnostic_results/
├── AL_diagnostic.json          # Alabama detailed results
├── AL_sample.html             # HTML sample from Alabama site
├── CT_diagnostic.json          # Connecticut detailed results
├── CT_sample.html             # HTML sample
├── ...                        # Other states
├── diagnostic_summary.json    # Overall summary
└── diagnostic_test.log        # Full execution log
```

### 3. Share Results

**To help fix the scrapers, share:**
1. `diagnostic_summary.json` - Quick overview
2. Individual state JSON files for failing states
3. `diagnostic_test.log` - Full log with errors

You can attach these to the GitHub issue or PR.

## Understanding the Output

### Diagnostic JSON Structure

Each state's diagnostic file contains:

```json
{
  "state_code": "AL",
  "state_name": "Alabama",
  "success": false,
  "statutes_scraped": 0,
  "base_url": "http://...",
  "diagnostics": {
    "url_accessibility": {
      "accessible": true,
      "status_code": 200,
      "content_length": 45230
    },
    "html_analysis": {
      "total_links": 150,
      "uses_javascript": false,
      "title": "Alabama Code"
    },
    "link_analysis": {
      "total_links": 150,
      "links_with_keywords": 45,
      "links_with_numbers": 80,
      "accepted_count": 25,
      "rejected_count": 125,
      "accepted_links": [...],
      "rejected_links": [...]
    }
  },
  "errors": ["list of errors"],
  "recommendations": ["list of fixes to try"]
}
```

### Key Diagnostic Indicators

**URL Accessibility**
- ✓ `accessible: true` - Site is reachable
- ✗ `accessible: false` - Check `error` field for reason

**HTML Analysis**
- `uses_javascript: true` - May need Playwright
- `total_links: 0` - Page might be empty or JavaScript-rendered

**Link Analysis**
- `accepted_count > 0` - Filtering is working
- `accepted_count == 0` - Filtering too strict OR page structure different

## Common Issues and Fixes

### Issue: "URL not accessible"

**Diagnostics show:**
```json
"url_accessibility": {
  "accessible": false,
  "error": "Timeout (30s)"
}
```

**Possible fixes:**
1. Site is down - check in browser
2. Site blocks automated access - check User-Agent
3. Network issue - try from different network
4. URL changed - verify on state website

**Action:**
- Check fallback methods in diagnostic output
- Try Internet Archive URL if available
- Update scraper URL if changed

### Issue: "Uses JavaScript"

**Diagnostics show:**
```json
"html_analysis": {
  "uses_javascript": true,
  "total_links": 5
}
```

**Possible fix:**
The scraper needs to use Playwright instead of basic HTTP requests.

**Action:**
1. Install Playwright: `pip install playwright && playwright install chromium`
2. Verify scraper uses `_playwright_scrape()` method
3. Check wait selectors are correct

### Issue: "No links accepted"

**Diagnostics show:**
```json
"link_analysis": {
  "total_links": 150,
  "accepted_count": 0,
  "links_with_keywords": 5
}
```

**Possible fixes:**
1. Keywords don't match - review `rejected_links` samples
2. Link format is different - check HTML sample
3. Links are too short - adjust length filter

**Action:**
- Review `rejected_links` in diagnostic JSON
- Look at HTML sample to see actual link structure
- Adjust keyword list in custom scraper
- Lower minimum length requirement if needed

### Issue: "Scraper returns 0 statutes"

**Diagnostics show:**
```json
"link_analysis": {
  "accepted_count": 25
},
"statutes_scraped": 0
```

**This means:**
Links are being found and accepted, but something fails during statute creation.

**Action:**
- Check `scraper_error` in diagnostics
- Review error traceback
- Verify `_extract_section_number()` works
- Check for exceptions in statute creation

## Providing Feedback to Copilot

When sharing diagnostic results, include:

### 1. Summary Information
```
State: Alabama (AL)
Success: No
Statutes scraped: 0
URL accessible: Yes
Links found: 150
Links accepted: 25
```

### 2. Sample Links
Share 5-10 examples from `accepted_links` and `rejected_links`:

**Accepted:**
- "Title 13A - Criminal Code"
- "Chapter 6 - Homicide"

**Rejected:**
- "Home" (reject_reason: no_keywords_or_numbers)
- "Search" (reject_reason: no_keywords_or_numbers)

### 3. Error Messages
Copy exact error messages from diagnostic output:
```
Alabama custom scraper failed: AttributeError: 'NoneType' object has no attribute 'get_text'
```

### 4. HTML Sample
If possible, share a snippet of the HTML showing link structure:
```html
<a href="/title13a.htm">Title 13A - Criminal Code</a>
```

## Manual Testing

To test a single state manually:

```python
import asyncio
import logging
from state_scrapers import AlabamaScraper

logging.basicConfig(level=logging.DEBUG)

async def test():
    scraper = AlabamaScraper("AL", "Alabama")
    codes = scraper.get_code_list()
    statutes = await scraper.scrape_code(codes[0]['name'], codes[0]['url'])
    print(f"Scraped {len(statutes)} statutes")

asyncio.run(test())
```

## Fallback Methods

The diagnostic script tries these fallback methods automatically:

### 1. Internet Archive (Wayback Machine)
- Useful if site is down or changed
- Provides archived version of the page
- URL format: `http://web.archive.org/web/*/original-url`

### 2. Protocol Switch (HTTP ↔ HTTPS)
- Some sites only work on HTTP or HTTPS
- Automatically tries both

### 3. Common Crawl
- Large corpus of web pages
- Useful for research but may be outdated
- Not automatically tried (requires API)

## Next Steps After Diagnostics

1. **Review all diagnostic files**
2. **Identify common patterns** in failures
3. **Share results** via GitHub issue/PR
4. **Copilot will:**
   - Analyze actual HTML structure
   - Adjust keyword matching
   - Fix URL issues
   - Add proper Playwright support
   - Update custom scrapers

## File Descriptions

- `diagnostic_test_states.py` - Main diagnostic script
- `test_state_scrapers.py` - Unit tests with mock data
- `SCRAPER_DOCUMENTATION.md` - Detailed scraper documentation
- `README_DIAGNOSTICS.md` - This file

## Support

If diagnostics don't provide enough information:

1. Share full `diagnostic_test.log`
2. Share HTML samples for failing states
3. Include network/browser test results
4. Note any site-specific requirements (VPN, cookies, etc.)

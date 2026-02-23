# Playwright Setup Guide for State Laws Scrapers

## Overview

Playwright is used for scraping state legislative websites that use JavaScript rendering. This includes 6 states: DC, HI, LA, MD, TN, and WA.

## Installation

### Step 1: Install Playwright

```bash
pip install playwright
```

### Step 2: Install Chromium Browser

```bash
python -m playwright install chromium
```

**Note:** If you encounter an error with the above command due to terminal width issues, try:
```bash
# Set a finite terminal width
export COLUMNS=80
python -m playwright install chromium
```

Or install via system package manager:
```bash
# Ubuntu/Debian
sudo apt-get install chromium-browser

# Mac
brew install chromium
```

### Step 3: Verify Installation

```python
from playwright.async_api import async_playwright
import anyio

async def verify():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.google.com")
        print("Playwright is working!")
        await browser.close()

anyio.run(verify)
```

## Usage in Scrapers

### States Using Playwright

The following 6 states require Playwright for JavaScript rendering:

1. **District of Columbia (DC)** - code.dccouncil.gov
2. **Hawaii (HI)** - capitol.hawaii.gov/hrscurrent
3. **Louisiana (LA)** - legis.la.gov
4. **Maryland (MD)** - mgaleg.maryland.gov
5. **Tennessee (TN)** - tn.gov/tga
6. **Washington (WA)** - app.leg.wa.gov/RCW

### Scraper Implementation

Each Playwright-enabled scraper uses the `_playwright_scrape()` method from `BaseStateScraper`:

```python
async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
    """Scrape using Playwright for JavaScript-rendered content."""
    return await self._playwright_scrape(
        code_name, 
        code_url, 
        "State Citation Format",
        wait_for_selector="a[href*='statute']",  # CSS selector to wait for
        timeout=45000  # 45 seconds
    )
```

### Automatic Fallback

If Playwright is not installed, scrapers automatically fall back to the generic HTTP scraper:

```python
if not self.has_playwright():
    logger.warning("Playwright not available, falling back to generic scrape")
    return await self._generic_scrape(code_name, code_url, citation_format)
```

## Running Tests

### Full Test Suite

```bash
# Make sure Playwright is installed first
pip install playwright
python -m playwright install chromium

# Run full test
cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools
python3 test_all_states_with_parquet.py
```

### Test Individual State

```python
from state_scrapers import get_scraper_for_state
import anyio

async def test_dc():
    scraper = get_scraper_for_state("DC", "District of Columbia")
    
    # Check if Playwright is available
    if scraper.has_playwright():
        print("✓ Playwright available")
    else:
        print("✗ Playwright not installed")
        return
    
    # Get codes
    codes = scraper.get_code_list()
    print(f"Available codes: {len(codes)}")
    
    # Scrape first code
    statutes = await scraper.scrape_code(
        code_name=codes[0]['name'],
        code_url=codes[0]['url']
    )
    
    print(f"Scraped {len(statutes)} statutes")
    for statute in statutes[:3]:
        print(f"  - {statute.official_cite}")

anyio.run(test_dc)
```

## Performance Considerations

### Resource Usage

- **Memory**: ~100-200MB per browser instance
- **CPU**: Moderate during page rendering
- **Time**: ~2-5 seconds per state (vs <1 second for HTTP)

### Optimization Tips

1. **Limit Concurrency**: Run max 2-3 Playwright scrapers simultaneously
   ```python
   semaphore = asyncio.Semaphore(2)  # Limit to 2 concurrent browsers
   ```

2. **Use Headless Mode**: Always use `headless=True` (default)
   ```python
   browser = await p.chromium.launch(headless=True)
   ```

3. **Set Appropriate Timeouts**: Balance between reliability and speed
   ```python
   timeout=30000  # 30 seconds is usually sufficient
   ```

4. **Reuse Browser Context**: For multiple pages from same domain
   ```python
   context = await browser.new_context()
   page = await context.new_page()
   ```

## Troubleshooting

### Issue: "playwright._impl._api_types.Error: Executable doesn't exist"

**Solution**: Install Chromium browser
```bash
python -m playwright install chromium
```

### Issue: "RangeError: Invalid count value: Infinity"

**Solution**: This occurs during installation on terminals without proper width. Try:
```bash
export COLUMNS=80
python -m playwright install chromium
```

Or use system package manager to install chromium directly.

### Issue: Browser launch fails with "Permission denied"

**Solution**: Check file permissions on Playwright browser directory
```bash
chmod -R 755 ~/.cache/ms-playwright
```

### Issue: "Timeout waiting for selector"

**Solution**: Increase timeout or adjust selector
```python
return await self._playwright_scrape(
    code_name, 
    code_url, 
    citation_format,
    wait_for_selector="body",  # More generic selector
    timeout=60000  # Increase timeout to 60 seconds
)
```

### Issue: ImportError: No module named 'playwright'

**Solution**: Install Playwright
```bash
pip install playwright
```

## Alternative: Selenium

If Playwright cannot be installed, you can use Selenium as an alternative:

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.headless = True
driver = webdriver.Chrome(options=options)
driver.get(url)
# Wait for JavaScript to load
time.sleep(3)
content = driver.page_source
driver.quit()
```

However, Playwright is preferred because:
- Better async/await support
- More reliable wait mechanisms
- Faster page loading
- Better error handling

## Testing Without Playwright

States that don't require Playwright (37 states) can be tested without installation:

```bash
# Test only non-Playwright states
python3 test_sample_states.py  # Tests CA, NY, TX, IL, WY (all work without Playwright)
```

## Production Deployment

### Docker

```dockerfile
FROM python:3.12-slim

# Install Playwright dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install playwright beautifulsoup4 requests pandas pyarrow

# Install Playwright browsers
RUN python -m playwright install chromium

WORKDIR /app
COPY . .

CMD ["python", "test_all_states_with_parquet.py"]
```

### System Service

```bash
# Install as system service for continuous scraping
sudo cp state_laws_scraper.service /etc/systemd/system/
sudo systemctl enable state_laws_scraper
sudo systemctl start state_laws_scraper
```

## Expected Results

With Playwright installed:
- **Success Rate**: ~84% (43/51 states)
- **Includes**: All Priority 3 states (DC, HI, LA, MD, TN, WA)
- **Time**: ~5-10 minutes for all 51 states

Without Playwright:
- **Success Rate**: ~72% (37/51 states)
- **Missing**: 6 Priority 3 states + 8 Priority 2 states
- **Time**: ~2-3 minutes for 37 states

## Support

For issues with Playwright setup:
- Playwright documentation: https://playwright.dev/python/
- GitHub issues: https://github.com/microsoft/playwright-python/issues

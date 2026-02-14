# Scraper Testing Quick Start Guide

## What This Does

This framework automatically tests all web scrapers for the four MCP dashboards to ensure they:
- ✅ Don't include HTML/DOM styling in scraped data
- ✅ Don't include menu/navigation content
- ✅ Produce coherent, properly structured data
- ✅ Don't have duplicate records

## Quick Start - Using GitHub Actions

### 1. Manual Test Run

1. Go to the **Actions** tab in GitHub
2. Click on **"Scraper Validation and Testing"** workflow
3. Click **"Run workflow"** button
4. Select:
   - **Domain**: Choose which domain to test (or "all" for everything)
   - **Test mode**: Choose "quick" for fast feedback, "comprehensive" for thorough testing
5. Click **"Run workflow"** to start

### 2. View Results

After the workflow completes:

1. Click on the workflow run
2. View the **Summary** page for overall results
3. Click on individual jobs to see detailed test output
4. Download **artifacts** for detailed JSON reports and test results

### 3. Understand the Results

The summary shows:
- ✅ **Passed**: Scraper works and data quality is good (score ≥ 70)
- ❌ **Failed**: Scraper works but data quality issues detected
- ⚠️ **Error**: Scraper failed to run

Each result includes:
- Number of records scraped
- Data quality score (0-100)
- List of quality issues found
- Execution time

## Quick Start - Local Testing

### 1. Install Dependencies

```bash
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-timeout
```

### 2. Run Tests for a Domain

```bash
# Test caselaw scrapers
pytest tests/scraper_tests/test_caselaw_scrapers.py -v

# Test finance scrapers
pytest tests/scraper_tests/test_finance_scrapers.py -v

# Test medicine scrapers  
pytest tests/scraper_tests/test_medicine_scrapers.py -v

# Test software scrapers
pytest tests/scraper_tests/test_software_scrapers.py -v

# Test all scrapers
pytest tests/scraper_tests/ -v
```

### 3. Using the CLI Tool

```bash
# List all available scrapers
python scraper_management.py list --domain all

# Test specific domain (quick mode)
python scraper_management.py test --domain caselaw

# Test all domains (comprehensive mode)
python scraper_management.py test --domain all --comprehensive --output-dir ./my_results

# Validate existing test results
python scraper_management.py validate --input test_results/caselaw_scrapers_test.json
```

## What Each Dashboard Tests

### Caselaw (`http://localhost:8899/mcp/caselaw`)

Tests 5 scrapers:
- **US Code**: Federal statutes
- **Federal Register**: Federal regulations  
- **State Laws**: State statutes (all 50 states)
- **Municipal Laws**: City/county codes
- **RECAP Archive**: Court documents

### Finance (`http://localhost:8899/mcp/finance`)

Tests 2 scrapers:
- **Stock Data**: Market data (OHLCV)
- **Financial News**: News articles

### Medicine (`http://localhost:8899/mcp/medicine`)

Tests 2 scrapers:
- **Clinical Trials**: ClinicalTrials.gov data
- **PubMed**: Medical research papers

### Software (`http://localhost:8899/mcp/software`)

Tests 1 scraper:
- **GitHub Repositories**: Repository metadata

## Common Data Quality Issues

### ❌ HTML/DOM Content Found

**Problem**: Data contains HTML tags or styling
```json
{
  "text": "<div class='content'>Some text</div>"
}
```

**Fix**: Strip HTML before storing:
```python
from bs4 import BeautifulSoup

def clean_html(text):
    soup = BeautifulSoup(text, 'html.parser')
    return soup.get_text()
```

### ❌ Menu Content Found

**Problem**: Navigation menus in scraped data
```json
{
  "text": "Home | About | Contact | Login"
}
```

**Fix**: Filter out navigation elements:
```python
# Skip elements with common menu classes/ids
if 'nav' in element.get('class', []) or 'menu' in element.get('id', ''):
    continue
```

### ❌ Incoherent Data

**Problem**: Disconnected text fragments
```json
{
  "text": "Menu item some statute text footer copyright"
}
```

**Fix**: Target specific content containers:
```python
# Get only the main content area
main_content = soup.find('div', class_='main-content')
text = main_content.get_text()
```

## When Tests Run Automatically

The workflow automatically runs on:

1. **Push** to main/develop (if scraper files changed)
2. **Pull Request** to main/develop  
3. **Schedule**: Daily at 3 AM UTC
4. **Manual**: Via "Run workflow" button

## Interpreting Quality Scores

- **90-100**: Excellent - Data is production-ready
- **70-89**: Good - Minor issues, acceptable for most uses
- **50-69**: Fair - Needs improvement
- **Below 50**: Poor - Major data quality problems

## Next Steps

1. **Review Failed Tests**: Check what quality issues were found
2. **Fix Scrapers**: Update scraper code to address issues
3. **Re-run Tests**: Verify fixes work
4. **Monitor**: Check daily test runs for regressions

## Need Help?

- Check `docs/SCRAPER_TESTING_FRAMEWORK.md` for detailed documentation
- Review test results artifacts for specific error messages
- Look at scraper implementation for data extraction logic
- Check GitHub Actions logs for detailed error traces

## Adding New Scrapers

1. Implement scraper in appropriate tools directory
2. Add test case to relevant test file (follow existing patterns)
3. Update `scraper_management.py` SCRAPERS list
4. Run tests locally to verify
5. Commit and push - CI will automatically test

## Troubleshooting

**Tests timeout?**
```bash
pytest tests/scraper_tests/ --timeout=600
```

**Import errors?**
```bash
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-timeout
```

**Docker build fails?**
```bash
# Make sure you're in repo root
cd /path/to/ipfs_datasets_py
docker build -f Dockerfile.scraper-tests -t scraper-tests .
```

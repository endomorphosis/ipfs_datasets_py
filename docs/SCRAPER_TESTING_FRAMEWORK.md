# Scraper Validation Framework

## Overview

This framework provides comprehensive testing and validation for web scrapers across all four MCP dashboard domains:

- **Caselaw** (`http://localhost:8899/mcp/caselaw`)
- **Finance** (`http://localhost:8899/mcp/finance`)
- **Medicine** (`http://localhost:8899/mcp/medicine`)
- **Software** (`http://localhost:8899/mcp/software`)

The framework ensures that scraped data is clean, coherent, and properly formatted without HTML/DOM artifacts, menu content, or other web page elements that shouldn't be in the final dataset.

## Key Features

### ✅ Data Quality Validation

The framework validates that scraped data:

1. **No HTML/DOM Content**: Detects and flags HTML tags, CSS classes, inline styles, and HTML entities
2. **No Menu/Navigation**: Identifies menu items, navigation elements, headers, and footers
3. **Data Coherence**: Ensures data is properly structured and not fragmented
4. **No Empty Fields**: Validates that required fields contain meaningful data
5. **Duplicate Detection**: Identifies duplicate records in datasets

### 📊 Quality Scoring

Each scraper test receives a quality score from 0-100 based on:
- Number and severity of quality issues detected
- Data completeness
- Structural coherence

### 🔄 Automated Testing

- **GitHub Actions Workflow**: Automatically tests scrapers on every push
- **Matrix Testing**: Tests all four domains in parallel
- **Docker Containerization**: Isolated, reproducible test environment
- **Self-hosted Runner Support**: Can run on your own infrastructure
- **Scheduled Testing**: Daily validation runs at 3 AM UTC

## Components

### 1. Core Framework (`ipfs_datasets_py/scraper_testing_framework.py`)

The main testing framework with:

- `ScraperDomain`: Enum for the four dashboard domains
- `DataQualityIssue`: Types of quality issues that can be detected
- `ScraperTestResult`: Standardized test result data class
- `ScraperValidator`: Validates data quality for scraped records
- `ScraperTestRunner`: Executes scraper tests and collects results

### 2. Test Suites (`tests/scraper_tests/`)

Domain-specific test suites:

- `test_caselaw_scrapers.py`: Tests for legal dataset tools
- `test_finance_scrapers.py`: Tests for finance data tools
- `test_medicine_scrapers.py`: Tests for medical research scrapers
- `test_software_scrapers.py`: Tests for software engineering tools

### 3. GitHub Actions Workflow (`.github/workflows/scraper-validation.yml`)

Automated testing workflow with:

- Multi-domain matrix testing
- Docker containerization
- Test result artifacts
- Quality reporting
- Self-hosted runner support

### 4. Management CLI (`scraper_management.py`)

Command-line tool for:

- Listing all available scrapers
- Running tests manually
- Validating test results
- Generating reports

## Usage

### Using the CLI Tool

#### List Available Scrapers

```bash
# List all scrapers
python scraper_management.py list --domain all

# List scrapers for specific domain
python scraper_management.py list --domain caselaw
```

#### Run Tests

```bash
# Test all caselaw scrapers (quick mode)
python scraper_management.py test --domain caselaw

# Test all scrapers (comprehensive mode)
python scraper_management.py test --domain all --comprehensive

# Save results to custom directory
python scraper_management.py test --domain finance --output-dir ./my_results
```

#### Validate Results

```bash
# Validate test results from a file
python scraper_management.py validate --input test_results/caselaw_scrapers_test.json
```

### Using GitHub Actions

#### Trigger Manual Test Run

1. Go to Actions tab in GitHub
2. Select "Scraper Validation and Testing" workflow
3. Click "Run workflow"
4. Choose domain to test (or "all")
5. Choose test mode (quick/comprehensive/stress)

#### View Test Results

1. Navigate to workflow run
2. Check the summary for domain-by-domain results
3. Download artifacts for detailed reports
4. Review data quality metrics

### Running Tests Locally

```bash
# Install dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-timeout

# Run tests for a specific domain
pytest tests/scraper_tests/test_caselaw_scrapers.py -v -s

# Run all scraper tests
pytest tests/scraper_tests/ -v -s
```

### Using Docker

```bash
# Build the test container
docker build -f Dockerfile.scraper-tests -t scraper-tests:latest .

# Run tests in container
docker run --rm scraper-tests:latest \
  pytest tests/scraper_tests/test_caselaw_scrapers.py -v
```

## Understanding Test Results

### Test Result Structure

```json
{
  "timestamp": "2024-10-30T01:00:00Z",
  "total_tests": 5,
  "passed": 4,
  "failed": 1,
  "errors": 0,
  "results": [
    {
      "scraper_name": "us_code_scraper",
      "domain": "caselaw",
      "status": "success",
      "records_scraped": 10,
      "execution_time_seconds": 5.2,
      "data_quality_score": 95.0,
      "quality_issues": [],
      "sample_data": [...]
    }
  ]
}
```

### Quality Issues

Issues are categorized by type and severity:

**Types:**
- `dom_styling`: HTML tags, CSS, inline styles found in data
- `menu_content`: Navigation menus, headers, footers in data
- `incoherent_data`: Disconnected or nonsensical data
- `empty_fields`: Required fields are empty
- `malformed_data`: Data structure is invalid
- `duplicate_data`: Duplicate records detected

**Severity:**
- `high`: Critical issue affecting data usability (10 point deduction)
- `medium`: Moderate issue (5 point deduction)
- `low`: Minor issue (2 point deduction)

### Quality Score Interpretation

- **90-100**: Excellent - Data is clean and well-structured
- **70-89**: Good - Minor issues, but data is usable
- **50-69**: Fair - Some quality issues need attention
- **Below 50**: Poor - Significant data quality problems

## Data Quality Standards

### What Should NOT Be in Scraped Data

❌ **HTML Tags and Elements**
```html
<div class="content">Text</div>
<p>Paragraph</p>
<span style="color: red;">Styled text</span>
```

❌ **Menu and Navigation Content**
```
Home | About | Contact | Login
← Previous | Next →
Copyright © 2024
```

❌ **CSS and Styling**
```
class="navbar-item"
style="margin: 10px;"
id="main-content"
```

❌ **Disconnected Content**
```
"Menu text statute section back to top footer"
```

### What SHOULD Be in Scraped Data

✅ **Clean Legal Text**
```json
{
  "title": "Title 1, Section 101",
  "text": "This section establishes...",
  "citation": "1 U.S.C. § 101"
}
```

✅ **Structured Financial Data**
```json
{
  "symbol": "AAPL",
  "date": "2024-10-30",
  "open": 150.25,
  "high": 152.50,
  "low": 149.75,
  "close": 151.80,
  "volume": 45000000
}
```

✅ **Clean Medical Research**
```json
{
  "title": "Clinical Trial Title",
  "nct_id": "NCT12345678",
  "conditions": ["Diabetes", "Type 2"],
  "interventions": ["Drug A", "Placebo"],
  "enrollment": 500
}
```

## Adding New Scrapers

### 1. Implement the Scraper

Place your scraper in the appropriate tools directory:
- Legal: `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/`
- Finance: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/`
- Medicine: `ipfs_datasets_py/mcp_server/tools/medical_research_scrapers/`
- Software: `ipfs_datasets_py/mcp_server/tools/software_engineering_tools/`

### 2. Add Test Cases

Add test cases to the appropriate test file in `tests/scraper_tests/`:

```python
@pytest.mark.asyncio
async def test_my_new_scraper(self, test_runner):
    """
    GIVEN my new scraper
    WHEN scraping data
    THEN data should be clean and coherent
    """
    result = await test_runner.run_scraper_test(
        scraper_func=my_scraper_function,
        scraper_name="my_new_scraper",
        domain=ScraperDomain.CASELAW,
        test_args={'param': 'value'}
    )
    
    assert result.status == 'success'
    assert result.data_quality_score >= 70
```

### 3. Update Scraper List

Add your scraper to `scraper_management.py` in the `SCRAPERS` dictionary.

### 4. Test Locally

```bash
python scraper_management.py test --domain your_domain
```

## Continuous Integration

The GitHub Actions workflow automatically:

1. **Triggers on:**
   - Push to main/develop branches (when scraper files change)
   - Pull requests
   - Manual workflow dispatch
   - Daily schedule (3 AM UTC)

2. **Runs tests:**
   - In isolated Docker containers
   - For all four domains in parallel
   - With configurable test modes

3. **Generates reports:**
   - Per-domain test results
   - Data quality metrics
   - Issue summaries
   - Consolidated reports

4. **Uploads artifacts:**
   - XML test results (30 day retention)
   - JSON quality reports (30 day retention)
   - Consolidated report (90 day retention)

## Troubleshooting

### Tests Failing with Import Errors

Make sure all dependencies are installed:
```bash
pip install -r requirements.txt
```

### Scrapers Timing Out

Increase the timeout in pytest:
```bash
pytest tests/scraper_tests/ --timeout=600
```

### Quality Score Too Low

1. Check the quality issues in the test results
2. Review scraper implementation for HTML cleanup
3. Ensure proper data extraction (not extracting DOM elements)
4. Add filters to remove menu/navigation content

### Docker Build Failures

Ensure you're building from the repository root:
```bash
cd /path/to/ipfs_datasets_py
docker build -f Dockerfile.scraper-tests -t scraper-tests:latest .
```

## Best Practices

### For Scraper Developers

1. **Clean HTML Early**: Strip HTML tags before storing data
2. **Validate Structure**: Ensure data has expected fields
3. **Handle Errors**: Return proper error messages in standardized format
4. **Test Locally**: Run tests before committing
5. **Document Behavior**: Add docstrings explaining data format

### For Test Writers

1. **Use Quick Tests**: Keep test data small for fast feedback
2. **Check Core Issues**: Focus on HTML, menus, and coherence
3. **Set Realistic Thresholds**: Not all scrapers can achieve 100
4. **Sample Data**: Include sample data in test results for debugging
5. **Follow GIVEN-WHEN-THEN**: Use this format for test descriptions

## Support and Contributing

For issues or questions:
1. Check the test results for specific error messages
2. Review the quality issues in detail
3. Consult the scraper implementation
4. Open an issue with test results attached

## License

Same as parent project.

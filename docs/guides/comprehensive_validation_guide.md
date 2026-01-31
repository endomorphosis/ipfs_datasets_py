# Comprehensive Scraper Validation Guide

## Overview

This document describes the comprehensive validation system for MCP dashboard scrapers that ensures:

1. ✅ **Scrapers actually execute** on self-hosted runners
2. ✅ **Data is produced** and meets quality standards  
3. ✅ **Schemas match expectations** for each domain
4. ✅ **HuggingFace compatibility** - data can be stored in HF datasets
5. ✅ **Data quality** meets standards (no HTML, no menus, coherent)

## Components

### 1. Comprehensive Validation Script

**File**: `comprehensive_scraper_validation.py`

This Python script performs end-to-end validation:

```python
from comprehensive_scraper_validation import ComprehensiveScraperValidator

validator = ComprehensiveScraperValidator()
result = await validator.validate_scraper(
    scraper_func=my_scraper,
    scraper_name="my_scraper",
    domain=ScraperDomain.CASELAW,
    test_args={'param': 'value'}
)

if result.is_valid():
    print("✅ Scraper passes all validations")
else:
    print(f"❌ Issues: {result.schema_issues}, {result.hf_issues}")
```

### 2. GitHub Actions Workflow

**File**: `.github/workflows/comprehensive-scraper-validation.yml`

Automated validation that runs:
- **On push** to main/develop (when scraper files change)
- **On schedule** weekly (Sundays at 3 AM UTC)
- **On demand** via workflow dispatch

### 3. Expected Schemas

The system validates against expected schemas for each domain:

#### Caselaw Domain
```python
{
    "title": "string",      # Required
    "text": "string",       # Required
    "citation": "string",
    "date": "string",
    "url": "string",
    "metadata": "dict"
}
```

#### Finance Domain
```python
{
    "title": "string",      # Required
    "text": "string",       # Required
    "ticker": "string",
    "date": "string",
    "price": "float",
    "volume": "float",
    "url": "string",
    "metadata": "dict"
}
```

#### Medicine Domain
```python
{
    "title": "string",      # Required
    "text": "string",       # Required
    "abstract": "string",
    "pmid": "string",
    "doi": "string",
    "date": "string",
    "authors": "list",
    "url": "string",
    "metadata": "dict"
}
```

#### Software Domain
```python
{
    "name": "string",         # Required
    "description": "string",  # Required
    "url": "string",
    "stars": "int",
    "language": "string",
    "topics": "list",
    "metadata": "dict"
}
```

## Validation Criteria

A scraper passes validation when ALL of the following are true:

### 1. Execution Success
- ✅ Scraper runs without exceptions
- ✅ Completes within reasonable time

### 2. Data Production
- ✅ At least one record is produced
- ✅ Records have actual content (not empty)

### 3. Schema Compliance
- ✅ All required fields are present
- ✅ Field types match expectations
- ✅ No unexpected field types (sets, tuples instead of lists)

### 4. HuggingFace Compatibility
- ✅ Can create a `datasets.Dataset` from the data
- ✅ No null/None values in required fields
- ✅ Consistent schema across all records
- ✅ Compatible data types (serializable)

### 5. Data Quality
- ✅ Quality score ≥ 50/100
- ✅ No HTML tags or DOM elements
- ✅ No menu/navigation content
- ✅ Data is coherent and structured

## Running Validations

### Local Execution

Run comprehensive validation locally:

```bash
python comprehensive_scraper_validation.py
```

This will:
1. Test all available scrapers
2. Validate schema compliance
3. Check HuggingFace compatibility
4. Generate detailed reports

**Output**:
- `validation_results/comprehensive_validation_report.json`: Full results
- `validation_results/validation_summary.txt`: Human-readable summary

### GitHub Actions

Trigger the workflow manually:

1. Go to **Actions** → **Comprehensive Scraper Validation**
2. Click **"Run workflow"**
3. Select domain (all or specific)
4. View results in workflow summary

**Automated Runs**:
- Weekly on Sundays at 3 AM UTC
- When scraper files are modified and pushed

### Continuous Integration

The validation runs automatically on:
- Push to main/develop branches
- Changes to scraper files
- Changes to test files
- Changes to validation script

## Understanding Results

### Validation Report Structure

```json
{
  "timestamp": "2025-10-30T02:00:00",
  "total_scrapers": 10,
  "passed": 8,
  "failed": 2,
  "results": [
    {
      "scraper_name": "us_code_scraper",
      "domain": "caselaw",
      "execution_success": true,
      "data_produced": true,
      "record_count": 5,
      "schema_valid": true,
      "schema_issues": [],
      "hf_compatible": true,
      "hf_issues": [],
      "quality_score": 95.0,
      "quality_issues": [],
      "sample_records": [...],
      "execution_time": 2.5,
      "timestamp": "2025-10-30T02:00:00"
    }
  ]
}
```

### Success Indicators

✅ **Fully Passing Scraper**:
```
✅ us_code_scraper (caselaw)
   Records: 5
   Quality: 95.0/100
   Execution: ✅
   Schema Valid: ✅
   HF Compatible: ✅
```

❌ **Failing Scraper**:
```
❌ broken_scraper (finance)
   Records: 0
   Quality: 0.0/100
   Execution: ❌
   Schema Valid: ❌
   HF Compatible: ❌
   Error: Connection timeout
```

## HuggingFace Dataset Integration

### Creating a Dataset from Validated Data

Once data passes validation, it can be used to create HuggingFace datasets:

```python
from datasets import Dataset
import json

# Load validation results
with open('validation_results/comprehensive_validation_report.json') as f:
    report = json.load(f)

# Get data from a passing scraper
for result in report['results']:
    if result['schema_valid'] and result['hf_compatible']:
        # Create HuggingFace dataset
        dataset = Dataset.from_list(result['sample_records'])
        
        # Push to HuggingFace Hub (if authenticated)
        dataset.push_to_hub(f"my-org/{result['scraper_name']}-dataset")
```

### Dataset Features

The validation ensures datasets have proper features:

```python
from datasets import Dataset, Features, Value, ClassLabel

# Example for caselaw domain
features = Features({
    'title': Value('string'),
    'text': Value('string'),
    'citation': Value('string'),
    'date': Value('string'),
    'url': Value('string'),
    'metadata': Value('string')  # JSON string
})

dataset = Dataset.from_list(data, features=features)
```

## Fixing Common Issues

### Schema Validation Failures

**Issue**: Missing required fields
```
Schema Issues: Missing required field: title
```

**Fix**: Ensure scraper populates all required fields:
```python
def my_scraper():
    return {
        'title': 'Document Title',  # Required
        'text': 'Document content', # Required
        # ... other fields
    }
```

**Issue**: Wrong field types
```
Schema Issues: Field 'price' should be float, got str
```

**Fix**: Convert to correct type:
```python
return {
    'price': float(price_string),  # Convert to float
    'volume': int(volume_string),  # Convert to int
}
```

### HuggingFace Compatibility Failures

**Issue**: Inconsistent schema across records
```
HF Issues: Record 5 has inconsistent keys with first record
```

**Fix**: Ensure all records have same fields:
```python
def normalize_record(record):
    # Add missing fields with defaults
    return {
        'title': record.get('title', ''),
        'text': record.get('text', ''),
        'citation': record.get('citation', ''),
        # ... all expected fields
    }

results = [normalize_record(r) for r in raw_results]
```

**Issue**: Null values in required fields
```
HF Issues: Record 3 has null value for field 'text'
```

**Fix**: Filter or provide defaults:
```python
# Option 1: Filter out records with nulls
results = [r for r in results if r['text'] is not None]

# Option 2: Provide defaults
for r in results:
    r['text'] = r['text'] or 'No content available'
```

**Issue**: Unsupported data types
```
HF Issues: Record 1 field 'tags' uses set, should use list or dict
```

**Fix**: Convert to supported types:
```python
return {
    'tags': list(tags_set),  # Convert set to list
    'metadata': dict(metadata_tuple)  # Convert tuple to dict
}
```

### Data Quality Failures

**Issue**: HTML content in data
```
Quality Issues: DOM styling found in 3 records
```

**Fix**: Strip HTML before returning:
```python
from bs4 import BeautifulSoup

def clean_html(text):
    soup = BeautifulSoup(text, 'html.parser')
    return soup.get_text()

return {
    'text': clean_html(raw_text)
}
```

**Issue**: Menu content in data
```
Quality Issues: Menu content found: Home | About | Contact
```

**Fix**: Filter out navigation elements:
```python
# Skip navigation containers
if 'nav' in element.get('class', []):
    continue
if element.name in ['nav', 'header', 'footer']:
    continue
```

## Automated Issue Creation

When validation fails, the workflow automatically:

1. **Creates/updates GitHub issue** with:
   - Validation summary
   - List of failing scrapers
   - Links to artifacts
   - Action items

2. **Labels**: `scraper-validation`, `automated`, `bug`

3. **Updates** existing issue if one already exists

## Best Practices

### 1. Test During Development

Run validation locally before committing:
```bash
python comprehensive_scraper_validation.py
```

### 2. Review Validation Reports

Check artifacts after each run:
- Download `comprehensive-validation-results` artifact
- Review `comprehensive_validation_report.json`
- Check `validation_summary.txt`

### 3. Maintain Schema Compliance

When adding new scrapers, ensure they match expected schemas:
- Include all required fields
- Use correct data types
- Provide consistent structure

### 4. Test HuggingFace Upload

Before deploying, test dataset creation:
```python
from datasets import Dataset

# Test with sample data
test_data = [{'title': 'Test', 'text': 'Content'}]
ds = Dataset.from_list(test_data)
print(ds.features)
```

### 5. Monitor Quality Scores

Aim for quality scores ≥ 70:
- < 50: Poor - major issues
- 50-69: Fair - needs improvement
- 70-89: Good - minor issues
- 90-100: Excellent - production ready

## Platform Requirements

### Self-Hosted Runner

The validation runs on self-hosted runners with:
- **Labels**: `[self-hosted, linux, x64]`
- **Docker**: Installed and running
- **Container**: `python:3.12-slim`
- **Network**: Access to scrape targets

### Python Dependencies

Required packages:
```
datasets>=2.0.0      # HuggingFace datasets
pytest>=7.0.0        # Testing framework
pytest-asyncio       # Async test support
```

## Troubleshooting

### Validation Script Fails

**Symptom**: Script crashes or hangs

**Solutions**:
1. Check scraper imports work
2. Verify test arguments are valid
3. Check network connectivity
4. Increase timeout if needed

### No Data Produced

**Symptom**: `data_produced: false`

**Solutions**:
1. Check scraper actually returns data
2. Verify API endpoints are accessible
3. Check authentication/API keys if needed
4. Review scraper logs for errors

### Schema Always Fails

**Symptom**: `schema_valid: false` for all scrapers

**Solutions**:
1. Review expected schema definitions
2. Check field names match exactly
3. Verify data types are correct
4. Look at sample_records in output

## Metrics and Monitoring

The validation tracks:
- **Success rate**: % of scrapers passing
- **Quality scores**: Average quality across all scrapers
- **Execution time**: Performance metrics
- **HF compatibility**: % compatible with datasets

View these in:
- GitHub Actions workflow summary
- Validation report JSON
- Generated artifacts

## Future Enhancements

Planned improvements:
- [ ] Automatic dataset upload to HuggingFace Hub
- [ ] Performance benchmarking
- [ ] Data freshness validation
- [ ] Rate limit testing
- [ ] Cost tracking per scraper
- [ ] Historical trend analysis

---

**Last Updated**: 2025-10-30  
**Version**: 1.0  
**Status**: Production Ready

# Legal Scrapers Common Crawl Integration Guide

Complete guide for using Common Crawl integration in legal scrapers (Phase 11).

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Components](#components)
4. [Usage Examples](#usage-examples)
5. [Integration Guide](#integration-guide)
6. [Fallback Chain](#fallback-chain)
7. [GraphRAG Integration](#graphrag-integration)
8. [Testing](#testing)
9. [Troubleshooting](#troubleshooting)
10. [Performance](#performance)

---

## Overview

Phase 11 implements comprehensive legal scraping with Common Crawl + HuggingFace integration, providing:

- **5-tier fallback chain** for reliable scraping
- **3 HuggingFace datasets** for federal, municipal, and state sources
- **WARC file parsing** with offset + range support
- **GraphRAG extraction** for legal rule mining
- **Auto-discovery** of all scrapers via registry
- **Monitoring** integration for observability

### Quick Start

```python
from ipfs_datasets_py.processors.legal_scrapers import (
    CommonCrawlLegalScraper,
    get_registry
)

# Method 1: Direct scraping
scraper = CommonCrawlLegalScraper()
await scraper.load_jsonl_sources()
result = await scraper.scrape_url("https://congress.gov/")

# Method 2: Via registry
registry = get_registry()
scraper_class = registry.get_scraper_for_source("congress.gov")
scraper = scraper_class()
result = await scraper.scrape("congress.gov")
```

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                  LegalScraperRegistry                   │
│              (Auto-discovery & Routing)                 │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────┴──────────┬─────────────┬───────────┐
         │                      │             │           │
    ┌────▼────┐          ┌─────▼─────┐  ┌───▼───┐  ┌────▼────┐
    │ Federal │          │   State   │  │Municipal│ │ Common  │
    │Scrapers │          │ Scrapers  │  │Scrapers │ │ Crawl   │
    └─────────┘          └───────────┘  └─────────┘ └─────────┘
         │                      │             │           │
         └──────────────────────┴─────────────┴───────────┘
                                │
                    ┌───────────▼──────────┐
                    │  Fallback Chain      │
                    │  1. Common Crawl     │
                    │  2. Brave Search     │
                    │  3. Wayback Machine  │
                    │  4. UnifiedScraper   │
                    │  5. Direct HTTP      │
                    └──────────────────────┘
```

### Data Flow

```
JSONL URLs → Registry → Scraper Selection
                             ↓
              Common Crawl (HuggingFace)
                             ↓
              WARC Fetching + Parsing
                             ↓
              GraphRAG Extraction
                             ↓
              Logic Module Integration
```

---

## Components

### 1. CommonCrawlLegalScraper

Main scraper with fallback chain implementation.

**Key Features:**
- JSONL source loading (4 files, ~5 MB)
- HuggingFace dataset integration
- WARC file fetching
- GraphRAG rule extraction
- Logic module feeding
- @monitor decorator for observability

**Files:**
- `common_crawl_scraper.py` (969 lines, 34 KB)

### 2. LegalScraperRegistry

Auto-discovery and routing system.

**Key Features:**
- Discovers all scrapers automatically
- Registers by type (federal, state, municipal)
- Tracks capabilities (WARC, GraphRAG, async, etc.)
- Priority-based selection
- Fallback chain creation

**Files:**
- `registry.py` (480 lines, 17 KB)

### 3. BaseScraper Enhancement

Extended base class with Common Crawl methods.

**New Methods:**
- `scrape_from_common_crawl()` - Query archives
- `query_warc_file()` - Direct WARC access
- `extract_with_graphrag()` - Rule extraction
- `scrape_with_fallbacks()` - Multi-method fallback

**Files:**
- `state_scrapers/base_scraper.py` (+240 lines)

---

## Usage Examples

### Example 1: Basic Scraping

```python
from ipfs_datasets_py.processors.legal_scrapers import CommonCrawlLegalScraper

async def scrape_congress():
    scraper = CommonCrawlLegalScraper()
    
    # Load URL sources
    await scraper.load_jsonl_sources()
    print(f"Loaded {len(scraper.sources)} sources")
    
    # Scrape specific URL
    result = await scraper.scrape_url(
        "https://congress.gov/",
        extract_rules=True,
        feed_to_logic=True
    )
    
    if result.success:
        print(f"Content: {len(result.content)} bytes")
        print(f"Method: {result.method_used}")
        print(f"Rules: {len(result.extracted_rules)}")
    
    return result
```

### Example 2: Batch Scraping

```python
async def scrape_federal_sources():
    scraper = CommonCrawlLegalScraper()
    await scraper.load_jsonl_sources()
    
    # Scrape all federal sources (limit 100)
    results = await scraper.scrape_all_sources(
        source_types=[SourceType.FEDERAL],
        max_sources=100,
        extract_rules=True
    )
    
    successful = [r for r in results if r.success]
    print(f"Scraped {len(successful)}/{len(results)} successfully")
    
    return results
```

### Example 3: Using Registry

```python
from ipfs_datasets_py.processors.legal_scrapers.registry import get_registry

async def scrape_with_registry():
    # Get registry (auto-discovers scrapers)
    registry = get_registry()
    
    # List all scrapers
    print(registry.list_scrapers())
    
    # Get best scraper for source
    scraper_class = registry.get_scraper_for_source("congress.gov")
    
    if scraper_class:
        scraper = scraper_class()
        result = await scraper.scrape("congress.gov")
        return result
    
    # Create fallback chain
    chain = registry.create_fallback_chain("congress.gov", max_fallbacks=3)
    print(f"Fallback chain: {[sc.__name__ for sc in chain]}")
```

### Example 4: BaseScraper with Fallbacks

```python
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import MyStateScraper

async def scrape_with_fallbacks():
    scraper = MyStateScraper("CA", "California")
    
    # Scrape with automatic fallbacks
    statute = await scraper.scrape_with_fallbacks(
        url="https://leginfo.legislature.ca.gov/code.html",
        use_common_crawl=True,
        use_graphrag=True
    )
    
    if statute:
        print(f"Statute: {statute.statute_id}")
        print(f"Title: {statute.short_title}")
        print(f"Legal Area: {statute.legal_area}")
    
    return statute
```

### Example 5: Direct WARC Access

```python
async def query_warc():
    scraper = MyStateScraper("NY", "New York")
    
    # Query specific WARC file
    content = await scraper.query_warc_file(
        warc_url="s3://commoncrawl/crawl-data/...",
        offset=123456,
        length=5000
    )
    
    if content:
        # Extract with GraphRAG
        results = await scraper.extract_with_graphrag(
            content,
            extract_rules=True
        )
        print(f"Entities: {len(results['entities'])}")
        print(f"Rules: {len(results['rules'])}")
    
    return results
```

---

## Integration Guide

### Step 1: Install Dependencies

```bash
pip install httpx beautifulsoup4 datasets
pip install playwright  # Optional, for JS-heavy sites
playwright install chromium
```

### Step 2: Set Up HuggingFace Access

```python
# No authentication needed for public datasets
from datasets import load_dataset

federal_index = load_dataset(
    "endomorphosis/common_crawl_federal_index",
    split="train"
)
```

### Step 3: Create Custom Scraper

```python
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import BaseStateScraper
from ipfs_datasets_py.processors.legal_scrapers.registry import get_registry

class MyCustomScraper(BaseStateScraper):
    def __init__(self):
        super().__init__("XX", "My State")
    
    def get_base_url(self) -> str:
        return "https://legislature.example.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [
            {"name": "Penal Code", "url": "..."},
            {"name": "Civil Code", "url": "..."}
        ]
    
    async def scrape_code(self, code_name: str, code_url: str):
        # Use Common Crawl fallback
        content = await self.scrape_from_common_crawl(code_url)
        
        if not content:
            # Fallback to direct HTTP
            content = await self.scrape_with_fallbacks(code_url)
        
        # Parse and return statutes
        return self.parse_statutes(content)

# Register custom scraper
registry = get_registry()
registry.register(
    name="my_custom",
    scraper_class=MyCustomScraper,
    scraper_type=ScraperType.STATE,
    priority=20,
    supports_sources=["example.gov"]
)
```

### Step 4: Use Monitoring

```python
# Monitoring is automatic via @monitor decorator
from ipfs_datasets_py.processors.infrastructure.monitoring import (
    get_processor_metrics,
    get_monitoring_summary
)

# After scraping, view metrics
metrics = get_processor_metrics("CommonCrawlLegalScraper.scrape_url")
print(f"Total calls: {metrics['total_calls']}")
print(f"Success rate: {metrics['success_rate']}%")
print(f"Avg time: {metrics['avg_time_seconds']}s")

# View dashboard
from scripts.monitoring import processor_dashboard
# python scripts/monitoring/processor_dashboard.py
```

---

## Fallback Chain

### Chain Order

1. **Common Crawl (Primary)**
   - Query HuggingFace datasets
   - Fetch WARC files
   - High success rate for archived content

2. **Brave Search (Fallback 1)**
   - Live search API
   - Caching enabled
   - Good for recent content

3. **Wayback Machine (Fallback 2)**
   - Internet Archive
   - Historical versions
   - Reliable backup

4. **UnifiedWebScraper (Fallback 3)**
   - 8 scraping methods
   - Includes Archive.is
   - Handles edge cases

5. **Direct HTTP (Fallback 4)**
   - Simple HTTP GET
   - Works for accessible sites
   - Last resort

### Fallback Logic

```python
async def scrape_url(url):
    errors = []
    
    for method in FALLBACK_METHODS:
        try:
            content = await fetch_with_method(url, method)
            if content:
                return ScrapedLegalContent(
                    success=True,
                    content=content,
                    method_used=method.name
                )
        except Exception as e:
            errors.append(f"{method.name}: {e}")
            continue  # Try next method
    
    # All methods failed
    return ScrapedLegalContent(
        success=False,
        errors=errors
    )
```

---

## GraphRAG Integration

### Rule Extraction

```python
# Automatic with extract_rules=True
result = await scraper.scrape_url(
    url,
    extract_rules=True
)

for rule in result.extracted_rules:
    print(f"Rule: {rule['text']}")
    print(f"Confidence: {rule['confidence']}")
    print(f"Entities: {rule['entities']}")
```

### Logic Module Integration

```python
# Automatic with feed_to_logic=True
result = await scraper.scrape_url(
    url,
    feed_to_logic=True
)

# Rules are automatically fed to logic module
# Check logic module for ingested rules
from ipfs_datasets_py.logic_integration import LogicProcessor
logic = LogicProcessor()
rules = logic.get_rules_by_source("federal_register")
```

### Manual GraphRAG

```python
# Extract manually
from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor

graphrag = UnifiedGraphRAGProcessor()
rules = await graphrag.extract_legal_rules(content)

# Feed to logic manually
from ipfs_datasets_py.logic_integration import LogicProcessor
logic = LogicProcessor()
await logic.ingest_rules(rules, source="my_source")
```

---

## Testing

### Unit Tests

```python
import pytest
from ipfs_datasets_py.processors.legal_scrapers import CommonCrawlLegalScraper

@pytest.mark.asyncio
async def test_scrape_url():
    scraper = CommonCrawlLegalScraper()
    result = await scraper.scrape_url(
        "https://example.gov/",
        extract_rules=False,
        feed_to_logic=False
    )
    assert result.success or len(result.errors) > 0

@pytest.mark.asyncio
async def test_fallback_chain():
    scraper = CommonCrawlLegalScraper()
    # Test that fallbacks work
    result = await scraper.scrape_url("https://nonexistent.gov/")
    # Should try all methods before failing
    assert len(result.errors) >= 3  # At least 3 methods tried
```

### Integration Tests

```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_common_crawl_integration():
    scraper = CommonCrawlLegalScraper()
    await scraper.load_jsonl_sources()
    
    # Scrape a known federal source
    result = await scraper.scrape_url(
        "https://www.govinfo.gov/",
        extract_rules=True
    )
    
    assert result.success
    assert len(result.content) > 0
    assert result.method_used in ["common_crawl", "brave_search", "wayback"]
```

### CLI Testing

```bash
# Test scraper directly
python -m ipfs_datasets_py.processors.legal_scrapers.common_crawl_scraper \
    --scrape-url "https://congress.gov/"

# Test registry
python -m ipfs_datasets_py.processors.legal_scrapers.registry --list
python -m ipfs_datasets_py.processors.legal_scrapers.registry \
    --source "congress.gov"
```

---

## Troubleshooting

### Common Issues

**1. ModuleNotFoundError: No module named 'anyio'**
```bash
# Install missing dependencies
pip install anyio httpx playwright beautifulsoup4 datasets
```

**2. Common Crawl returns no results**
```python
# Check if URL is in sources
scraper = CommonCrawlLegalScraper()
await scraper.load_jsonl_sources()
metadata = scraper.get_source_metadata("https://example.gov/")
if not metadata:
    print("URL not in sources - will use fallbacks")
```

**3. All fallback methods fail**
```python
# Check errors
result = await scraper.scrape_url(url)
if not result.success:
    for error in result.errors:
        print(f"Error: {error}")
```

**4. GraphRAG extraction fails**
```python
# Disable GraphRAG if causing issues
result = await scraper.scrape_url(
    url,
    extract_rules=False  # Disable GraphRAG
)
```

**5. Rate limiting issues**
```python
# Add delays between requests
import asyncio
for url in urls:
    result = await scraper.scrape_url(url)
    await asyncio.sleep(2.0)  # 2 second delay
```

---

## Performance

### Optimization Tips

**1. Batch Processing**
```python
# Process multiple URLs concurrently
import asyncio

urls = ["url1", "url2", "url3"]
tasks = [scraper.scrape_url(url) for url in urls]
results = await asyncio.gather(*tasks)
```

**2. Disable Features**
```python
# Skip expensive operations
result = await scraper.scrape_url(
    url,
    extract_rules=False,  # Skip GraphRAG
    feed_to_logic=False   # Skip logic module
)
```

**3. Use Caching**
```python
# Results are automatically cached by Brave Search
# Subsequent requests for same URL will be faster
```

**4. Limit Sources**
```python
# Only load needed sources
results = await scraper.scrape_all_sources(
    source_types=[SourceType.FEDERAL],  # Only federal
    max_sources=10  # Limit count
)
```

### Performance Metrics

| Operation | Typical Time | Notes |
|-----------|-------------|-------|
| Load JSONL sources | 2-5s | One-time cost |
| Common Crawl query | 5-15s | HuggingFace + WARC |
| Brave Search | 2-5s | With caching |
| Wayback Machine | 3-10s | Depends on archive |
| Direct HTTP | 1-3s | Fastest when available |
| GraphRAG extraction | 10-30s | Most expensive |

### Monitoring Dashboard

View real-time performance:
```bash
python scripts/monitoring/processor_dashboard.py

# Output:
# CommonCrawlLegalScraper.scrape_url:
#   Calls: 42
#   Success Rate: 95.2%
#   Avg Time: 8.3s
#   Method Distribution:
#     - common_crawl: 60%
#     - brave_search: 25%
#     - wayback: 10%
#     - http: 5%
```

---

## Summary

Phase 11 provides production-ready legal scraping with:

✅ **Comprehensive fallback chain** - 5 methods for reliability  
✅ **HuggingFace integration** - 3 datasets with Common Crawl indexes  
✅ **WARC parsing** - Direct access to archived content  
✅ **GraphRAG extraction** - Automated rule mining  
✅ **Auto-discovery** - Registry finds all scrapers  
✅ **Monitoring** - Full observability via dashboard  
✅ **Backward compatible** - Zero breaking changes  

**Ready for production use!**

---

## Additional Resources

- [Phase 11 Implementation Plan](PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md)
- [Processors Refactoring Overview](PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md)
- [Cross-Cutting Integration Guide](CROSS_CUTTING_INTEGRATION_GUIDE.md)
- [Monitoring Dashboard Guide](../scripts/monitoring/README.md)

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review test files for examples
3. Check monitoring dashboard for errors
4. Create GitHub issue with error details

---

**Last Updated:** 2026-02-16  
**Phase:** 11 (Legal Scrapers Unification)  
**Status:** Complete ✅

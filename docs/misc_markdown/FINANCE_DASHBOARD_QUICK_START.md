# Finance Dashboard Quick Start Guide

This guide shows you how to use the new finance data tools in the MCP dashboard.

## 🚀 Getting Started

### Prerequisites

```bash
# Optional: Install production dependencies for full functionality
pip install yfinance requests beautifulsoup4
pip install pandas numpy
```

### Basic Usage

#### 1. Import the Modules

```python
# Stock data tools
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
    fetch_stock_data,
    fetch_corporate_actions,
    StockDataPoint
)

# News scraping tools
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.news_scrapers import (
    fetch_financial_news,
    search_archive_news
)

# Financial theorems
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
    list_financial_theorems,
    apply_financial_theorem,
    FinancialTheoremLibrary
)
```

## 📈 Common Use Cases

### Use Case 1: Track a Stock Split

```python
import json
from datetime import datetime

# Step 1: Check for corporate actions
actions_json = fetch_corporate_actions(
    symbol="AAPL",
    start_date="2020-08-01",
    end_date="2020-09-01",
    source="yahoo"
)
actions = json.loads(actions_json)
print(f"Found {actions['actions_count']} corporate actions")

# Step 2: Get price data around the split
price_data_json = fetch_stock_data(
    symbol="AAPL",
    start_date="2020-08-28",
    end_date="2020-09-02",
    interval="1d",
    source="yahoo"
)
price_data = json.loads(price_data_json)
print(f"Fetched {price_data['data_points']} data points")

# Step 3: Apply stock split theorem
theorem_result = apply_financial_theorem(
    theorem_id="fin_001",  # Stock Split theorem
    symbol="AAPL",
    event_date="2020-08-31",
    event_data=json.dumps({
        "split_ratio": 4,
        "pre_split_price": 499.23,
        "post_split_price": 124.81
    })
)
result = json.loads(theorem_result)
print(f"Theorem application: {result['success']}")
```

### Use Case 2: Monitor Merger Announcement

```python
# Step 1: Search for merger news
news_json = fetch_financial_news(
    topic="Microsoft Activision merger",
    start_date="2022-01-01",
    end_date="2022-12-31",
    sources="reuters,bloomberg",
    max_articles=50
)
news = json.loads(news_json)
print(f"Found {news['total_articles']} news articles")

# Step 2: Get relevant theorems
theorems_json = list_financial_theorems(event_type="merger")
theorems = json.loads(theorems_json)
print(f"Merger theorems: {theorems['total_theorems']}")

# Print theorem details
for theorem in theorems['theorems']:
    print(f"\nTheorem: {theorem['name']}")
    print(f"Formula: {theorem['formula']}")
    print(f"Confidence: {theorem['confidence_threshold']}")
```

### Use Case 3: Validate Dividend Adjustment

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
    FinancialTheoremLibrary,
    FinancialEventType
)

# Get dividend theorem
library = FinancialTheoremLibrary()
dividend_theorem = library.get_theorem("fin_003")

print(f"Theorem: {dividend_theorem.name}")
print(f"Natural Language: {dividend_theorem.natural_language}")
print(f"Expected deviation: ±{dividend_theorem.metadata['tolerance']*100}%")

# Apply to real data
theorem_result = apply_financial_theorem(
    theorem_id="fin_003",
    symbol="MSFT",
    event_date="2024-02-15",
    event_data=json.dumps({
        "dividend_amount": 0.75,
        "previous_close": 420.00,
        "opening_price": 419.10
    })
)
print(json.dumps(json.loads(theorem_result), indent=2))
```

### Use Case 4: Analyze Earnings Surprise

```python
# List all available theorems
all_theorems_json = list_financial_theorems()
all_theorems = json.loads(all_theorems_json)

print(f"Total theorems available: {all_theorems['total_theorems']}\n")

# Find earnings theorem
for theorem in all_theorems['theorems']:
    if theorem['event_type'] == 'earnings':
        print(f"Earnings Theorem: {theorem['name']}")
        print(f"Description: {theorem['natural_language']}")
        print(f"Confidence: {theorem['confidence_threshold']}")
        break
```

### Use Case 5: Search Historical News in Archive.org

```python
# Search for archived article
archive_result = search_archive_news(
    url="https://www.reuters.com/business/some-article",
    date="2020-01-15"  # Optional: specific date
)
result = json.loads(archive_result)

if result['found']:
    print(f"Found in archive!")
    print(f"Content length: {result['content_length']} bytes")
    print(f"Preview: {result['content_preview'][:200]}...")
else:
    print(f"Not found: {result['error']}")
```

## 🔧 Advanced Usage

### Custom Theorem Creation

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
    FinancialTheorem,
    FinancialEventType,
    FinancialTheoremLibrary
)

# Create custom theorem
custom_theorem = FinancialTheorem(
    theorem_id="custom_001",
    name="Triple Top Pattern",
    event_type=FinancialEventType.ANALYST_UPGRADE,
    formula="""
    ∀s,t: (TripleTop(s, t) → P(Reversal(s, t+Δt)))
    """,
    natural_language="""
    When a stock forms a triple top pattern at time t,
    there is PERMISSION for a price reversal within the
    next temporal window.
    """,
    applicability_conditions=[
        "three_distinct_peaks",
        "similar_price_levels",
        "valid_support_level"
    ],
    confidence_threshold=0.60,
    temporal_window=14,  # 14 days
    metadata={
        "pattern_type": "reversal",
        "technical_indicator": True
    }
)

# Add to library
library = FinancialTheoremLibrary()
library.add_custom_theorem(custom_theorem)
print(f"Added custom theorem: {custom_theorem.theorem_id}")
```

### Data Validation Pipeline

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
    StockDataPoint,
    StockDataScraper
)
from datetime import datetime

# Create multiple data points
data_points = [
    StockDataPoint(
        symbol="TSLA",
        timestamp=datetime(2024, 1, 1),
        open=250.0,
        high=255.0,
        low=248.0,
        close=252.0,
        volume=50000000
    ),
    StockDataPoint(
        symbol="TSLA",
        timestamp=datetime(2024, 1, 2),
        open=252.0,
        high=248.0,  # Invalid: high < low
        low=250.0,
        close=249.0,
        volume=45000000
    )
]

# Validate all data points
scraper = StockDataScraper()
valid_points, errors = scraper.validate_data(data_points)

print(f"Valid points: {len(valid_points)}")
print(f"Invalid points: {len(errors)}")

for error in errors:
    print(f"\nError in {error['symbol']} at {error['timestamp']}:")
    for err_msg in error['errors']:
        print(f"  - {err_msg}")
```

### Rate-Limited Scraping

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
    YahooFinanceScraper
)
from datetime import datetime, timedelta

# Create scraper with strict rate limits
scraper = YahooFinanceScraper(
    rate_limit_calls=5,      # 5 calls
    rate_limit_period=60,    # per 60 seconds
    max_retries=3,           # retry up to 3 times
    retry_delay=2            # wait 2 seconds between retries
)

# Fetch data for multiple symbols
symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
start = datetime(2024, 1, 1)
end = datetime(2024, 1, 31)

for symbol in symbols:
    try:
        # Rate limiting is automatic
        data = scraper.fetch_data(symbol, start, end, interval="1d")
        print(f"Fetched {symbol}: {len(data)} data points")
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
```

## 📊 MCP Server Integration

When running through the MCP server, these tools are automatically available:

```bash
# Start MCP server
python -m ipfs_datasets_py.mcp_server

# Access via HTTP
curl http://localhost:8000/tools

# Execute tool
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "fetch_stock_data",
    "parameters": {
      "symbol": "AAPL",
      "start_date": "2024-01-01",
      "end_date": "2024-01-31",
      "interval": "1d",
      "source": "yahoo"
    }
  }'
```

## 🎯 Dashboard Integration

The finance dashboard at `https://localhost:8899/mcp/finance` can be enhanced with these tools:

```javascript
// JavaScript example for dashboard
async function fetchStockData(symbol) {
    const response = await fetch('/api/mcp/finance/stock_data', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            symbol: symbol,
            start_date: '2024-01-01',
            end_date: '2024-01-31'
        })
    });
    
    const data = await response.json();
    renderChart(data.data_points);
}

async function listTheorems() {
    const response = await fetch('/api/mcp/finance/theorems');
    const theorems = await response.json();
    
    theorems.theorems.forEach(theorem => {
        console.log(`${theorem.name}: ${theorem.confidence_threshold * 100}%`);
    });
}
```

## 🐛 Troubleshooting

### Issue: "YahooFinanceScraper.fetch_data is a placeholder"

**Solution**: The base implementation is a placeholder. Install yfinance:

```bash
pip install yfinance
```

Then implement the actual API calls in `stock_scrapers.py`.

### Issue: "Entity extraction is a placeholder"

**Solution**: Install NLP libraries:

```bash
pip install spacy
python -m spacy download en_core_web_sm
```

Then implement NLP-based extraction in `news_scrapers.py`.

### Issue: Rate limit errors

**Solution**: Adjust rate limiting parameters:

```python
scraper = StockDataScraper(
    rate_limit_calls=10,     # Increase calls
    rate_limit_period=60,    # Keep period same
    max_retries=5            # More retries
)
```

## 📚 Further Reading

- **Full Implementation Plan**: See `FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md`
- **Implementation Summary**: See `FINANCE_DASHBOARD_IMPLEMENTATION_SUMMARY.md`
- **Module Documentation**: See `ipfs_datasets_py/mcp_server/tools/finance_data_tools/README.md`
- **Test Examples**: See `tests/finance_dashboard/test_finance_data_tools.py`

## 💡 Tips

1. **Always validate data** before processing
2. **Use rate limiting** to avoid API bans
3. **Enable retry logic** for production robustness
4. **Cache frequently accessed data** to reduce API calls
5. **Monitor theorem confidence scores** when making decisions

## 🤝 Contributing

To add new features:
1. Follow existing class patterns
2. Add comprehensive docstrings
3. Create MCP tool wrapper functions
4. Write tests
5. Update documentation

---

**Quick Links**:
- [Main README](./README.md)
- [Improvement Plan](./FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md)
- [Implementation Summary](./FINANCE_DASHBOARD_IMPLEMENTATION_SUMMARY.md)
- [Module Documentation](./ipfs_datasets_py/mcp_server/tools/finance_data_tools/README.md)

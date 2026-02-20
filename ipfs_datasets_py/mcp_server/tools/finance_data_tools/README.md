# Finance Data Tools

Comprehensive financial data collection, analysis, and reasoning tools for the MCP server.

## Overview

This module provides a complete suite of tools for:

1. **Market Data Scraping**: Collect time series data from stocks, currencies, bonds, futures, and crypto markets
2. **News Intelligence**: Scrape financial news from major sources with archive.org fallback
3. **Knowledge Graph Construction**: Build temporal knowledge graphs of business entities and relationships
4. **Temporal Deontic Logic**: Apply formal reasoning to financial events and patterns

## Module Structure

```
finance_data_tools/
├── __init__.py                     # Module initialization
├── stock_scrapers.py               # Stock market data scrapers
├── news_scrapers.py                # Financial news scrapers
├── finance_theorems.py             # Temporal deontic logic theorems
├── embedding_correlation.py        # MCP thin wrapper for embedding analysis
├── embedding_analysis_engine.py    # Reusable embedding/latent-space engine
├── graphrag_news_analyzer.py       # MCP wrapper for GraphRAG news analysis
├── README.md                       # This file
├── EMBEDDING_CORRELATION.md        # Architecture: vector embedding analysis
└── GRAPHRAG_ANALYSIS.md            # Architecture: executive-performance analysis
```

## Features

### Stock Data Scraping

```python
from finance_data_tools.stock_scrapers import fetch_stock_data

# Fetch stock data
result = fetch_stock_data(
    symbol="AAPL",
    start_date="2024-01-01",
    end_date="2024-01-31",
    interval="1d",
    source="yahoo"
)
```

**Supported Sources**:
- Yahoo Finance (current)
- Alpha Vantage (planned)
- Polygon.io (planned)

**Data Points**:
- OHLCV (Open, High, Low, Close, Volume)
- Adjusted close prices
- Corporate actions (splits, dividends)
- Validation and error checking

### News Scraping

```python
from finance_data_tools.news_scrapers import fetch_financial_news

# Fetch news articles
result = fetch_financial_news(
    topic="stock market",
    start_date="2024-01-01",
    end_date="2024-01-31",
    sources="ap,reuters,bloomberg",
    max_articles=100
)
```

**Supported Sources**:
- AP News
- Reuters  
- Bloomberg

**Features**:
- Archive.org fallback for historical articles
- Entity extraction (companies, people, events)
- Sentiment analysis
- Duplicate detection
- IPFS storage integration

### Financial Theorems

```python
from finance_data_tools.finance_theorems import list_financial_theorems

# List available theorems
theorems = list_financial_theorems(event_type="stock_split")
```

**Available Theorems**:

1. **Stock Split Price Adjustment** (`fin_001`)
   - Formula: Price adjustment = Pre-split price / Split ratio
   - Confidence: 95%
   - Example: 4:1 split at $400 → $100 post-split

2. **Reverse Split Price Adjustment** (`fin_002`)
   - Formula: Price adjustment = Pre-split price × Reverse ratio
   - Confidence: 95%

3. **Ex-Dividend Date Price Adjustment** (`fin_003`)
   - Formula: Opening price ≈ Previous close - Dividend amount
   - Confidence: 75%

4. **Merger Price Convergence** (`fin_004`)
   - Formula: Target price → Acquirer price × Exchange ratio × (1 + Premium)
   - Confidence: 70%
   - Temporal window: 90 days

5. **Earnings Surprise Price Movement** (`fin_005`)
   - Formula: |Price change| > Average volatility when surprise > 5%
   - Confidence: 65%

## MCP Tool Integration

All modules provide MCP-compatible tool functions that can be called through the MCP server:

### Available MCP Tools

#### Stock Data Tools
- `fetch_stock_data(symbol, start_date, end_date, interval, source)`
- `fetch_corporate_actions(symbol, start_date, end_date, source)`

#### News Tools
- `fetch_financial_news(topic, start_date, end_date, sources, max_articles)`
- `search_archive_news(url, date)`

#### Theorem Tools
- `list_financial_theorems(event_type)`
- `apply_financial_theorem(theorem_id, symbol, event_date, event_data)`

## Implementation Status

### Completed (Foundation Phase)
- ✅ Stock scraper base class with rate limiting
- ✅ News scraper base class with archive.org fallback
- ✅ Financial theorem library with 5 core theorems
- ✅ Data validation pipeline
- ✅ MCP tool function wrappers
- ✅ Embedding analysis engine (`embedding_analysis_engine.py`) with reusable latent-space analysis
- ✅ GraphRAG news analyzer (`graphrag_news_analyzer.py`) for executive-performance correlation
- ✅ Documentation (README + EMBEDDING_CORRELATION.md + GRAPHRAG_ANALYSIS.md)

### In Progress / Planned
- ⏳ Yahoo Finance live data integration
- ⏳ Entity extraction from news (NLP pipeline)
- ⏳ Sentiment analysis models
- ⏳ Additional market data sources (Alpha Vantage, Polygon.io)
- ⏳ Forex/currency, cryptocurrency, bonds, futures scrapers
- ⏳ IPFS time series storage
- ⏳ Causal reasoning engine
- ⏳ Dashboard UI components

## Usage Examples

### Example 1: Track Stock Split

```python
from finance_data_tools import (
    fetch_stock_data,
    fetch_corporate_actions,
    apply_financial_theorem
)
import json

# 1. Fetch corporate actions
actions = fetch_corporate_actions(
    symbol="AAPL",
    start_date="2020-08-01",
    end_date="2020-09-01",
    source="yahoo"
)

# 2. Fetch price data around split
price_data = fetch_stock_data(
    symbol="AAPL",
    start_date="2020-08-28",
    end_date="2020-09-02",
    interval="1d"
)

# 3. Apply stock split theorem
result = apply_financial_theorem(
    theorem_id="fin_001",
    symbol="AAPL",
    event_date="2020-08-31",
    event_data=json.dumps({
        "split_ratio": 4,
        "pre_split_price": 499.23,
        "post_split_price": 124.81
    })
)

print(result)
```

### Example 2: News-Based Event Detection

```python
from finance_data_tools import fetch_financial_news, search_archive_news

# Fetch recent merger news
merger_news = fetch_financial_news(
    topic="merger acquisition",
    start_date="2024-01-01",
    end_date="2024-01-31",
    sources="reuters,bloomberg"
)

# Search archive for historical context
archive_result = search_archive_news(
    url="https://www.reuters.com/some-article",
    date="2020-01-15"
)
```

### Example 3: Theorem Validation

```python
from finance_data_tools import FinancialTheoremLibrary

# Initialize library
library = FinancialTheoremLibrary()

# Get all dividend theorems
dividend_theorems = library.get_theorems_by_event_type(
    FinancialEventType.DIVIDEND
)

# Apply to validate against historical data
for theorem in dividend_theorems:
    print(f"Theorem: {theorem.name}")
    print(f"Confidence: {theorem.confidence_threshold}")
    print(f"Formula: {theorem.formula}\n")
```

## Testing

Tests will be located in `/tests/finance_dashboard/`:

```bash
# Run all finance data tools tests
pytest tests/finance_dashboard/

# Run specific test suites
pytest tests/finance_dashboard/test_stock_scrapers.py
pytest tests/finance_dashboard/test_news_scrapers.py
pytest tests/finance_dashboard/test_theorems.py
```

## Dependencies

### Required
- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing
- `python-dateutil` - Date parsing

### Optional (for full functionality)
- `yfinance` - Yahoo Finance data
- `alpha_vantage` - Alpha Vantage API
- `pandas` - Data manipulation
- `numpy` - Numerical operations
- `spacy` - Entity extraction
- `transformers` - NLP models
- `selenium` - JavaScript rendering (Bloomberg)

## Configuration

Configure scrapers via environment variables or config file:

```bash
# API Keys
export ALPHA_VANTAGE_API_KEY="your_key"
export POLYGON_IO_API_KEY="your_key"

# Rate Limiting
export FINANCE_SCRAPER_RATE_LIMIT_CALLS=5
export FINANCE_SCRAPER_RATE_LIMIT_PERIOD=60

# Archive.org
export USE_ARCHIVE_FALLBACK=true
```

## Architecture

### Data Flow

```
1. Data Collection
   ├─ Market Data Scrapers → IPFS Storage
   ├─ News Scrapers → Entity Extraction → Knowledge Graph
   └─ Archive.org Fallback → Historical Data

2. Processing
   ├─ Data Validation
   ├─ Entity Extraction (NLP)
   ├─ Knowledge Graph Building
   └─ Temporal Indexing

3. Reasoning
   ├─ Theorem Matching
   ├─ Fuzzy Logic Evaluation
   ├─ Causal Chain Building
   └─ Confidence Scoring

4. Output
   ├─ MCP Tool Results
   ├─ Dashboard Visualization
   └─ API Endpoints
```

### Integration with Existing Systems

This module integrates with:

- **Temporal Deontic Logic** (`logic_integration/`) - Core reasoning engine
- **GraphRAG** (`graphrag_integration.py`) - Knowledge graph construction
- **Web Archive** (`web_archive.py`) - Archive.org integration
- **IPFS Storage** (`ipld/`) - Decentralized data storage
- **MCP Dashboard** (`mcp_dashboard.py`) - UI and visualization

## Future Enhancements

### Phase 2
- Machine learning price prediction models
- Advanced sentiment analysis (fine-tuned transformers)
- Cross-market correlation analysis
- Real-time data streaming

### Phase 3
- Distributed scraping across IPFS network
- Decentralized reasoning validators
- Multi-modal analysis (text + numerical + social)
- Alternative data sources (satellite, web traffic)

### Phase 4
- Portfolio optimization algorithms
- Risk assessment dashboard
- Regulatory compliance checking
- Automated trading signal generation

## Contributing

When adding new scrapers or theorems:

1. Follow the base class patterns in `stock_scrapers.py` and `news_scrapers.py`
2. Include proper error handling and rate limiting
3. Add data validation
4. Create MCP tool wrapper functions
5. Write tests
6. Update this README

## License

Same as parent project.

## Support

For issues or questions:
- Check existing GitHub issues
- Review the main project documentation
- See `FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` for detailed architecture

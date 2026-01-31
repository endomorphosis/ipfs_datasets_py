# Finance Data Tools - Usage Examples

This document provides comprehensive examples for using the finance data collection and analysis features in ipfs_datasets_py.

## Overview

The Finance integration follows the **correct integration pattern** where all interfaces are peer consumers of the core package:

```
    finance/ (Core Package - re-exports from MCP tools)
                ↓
    ┌───────────┼──────────────┐
    │           │              │
   CLI      MCP Tools      Python API
```

The Finance integration provides:
1. **Finance Package** (`ipfs_datasets_py.finance`) - Core Python interface ⭐
2. **Finance CLI** (`finance_cli.py`) - Command-line interface (imports from finance)
3. **MCP Tools** (`ipfs_datasets_py.mcp_server.tools.finance_data_tools`) - Source implementations
4. **Finance Dashboard** (optional) - Web-based analysis UI

## Installation

No additional dependencies required beyond standard Python libraries. Optional dependencies can enhance functionality:

```bash
# Basic finance tools (no extra dependencies)
pip install ipfs-datasets-py

# With optional enhancements
pip install ipfs-datasets-py[finance]  # Adds yfinance, pandas, numpy
```

## Components

### 1. Stock Market Data

Scrape stock data from various sources:

#### Python Package

```python
from ipfs_datasets_py.finance import get_stock_data, get_stock_data_yfinance
from datetime import datetime, timedelta

# Fetch stock data (uses available scraper)
result = get_stock_data(
    symbol='AAPL',
    start_date=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
    end_date=datetime.now().strftime('%Y-%m-%d'),
    interval='1d'
)

# Fetch specifically from Yahoo Finance
yf_result = get_stock_data_yfinance(
    symbol='AAPL',
    start_date='2024-01-01',
    end_date='2024-12-31',
    interval='1d'
)

print(f"Fetched {len(result)} data points")
```

#### CLI

```bash
# Fetch stock data
ipfs-datasets finance stock AAPL --start 2024-01-01 --end 2024-12-31

# Save to file
ipfs-datasets finance stock AAPL --start 2024-01-01 --output aapl_2024.json

# Different intervals
ipfs-datasets finance stock AAPL --interval 1h --start 2024-12-01
```

### 2. Financial News Scraping

Collect financial news from AP, Reuters, Bloomberg:

#### Python Package

```python
from ipfs_datasets_py.finance import scrape_financial_news, scrape_reuters_news
from datetime import datetime, timedelta

# Scrape news from multiple sources
news = scrape_financial_news(
    topic='tech stocks',
    start_date='2024-11-01',
    end_date='2024-12-01',
    sources=['reuters', 'ap', 'bloomberg'],
    max_articles=100
)

# Scrape from specific source
reuters = scrape_reuters_news(
    query='artificial intelligence',
    start_date='2024-11-01',
    max_articles=50
)

print(f"Collected {len(news)} articles")
```

#### CLI

```bash
# Scrape financial news
ipfs-datasets finance news "tech stocks" --start 2024-11-01 --end 2024-12-01

# Specify sources
ipfs-datasets finance news "AI companies" --sources reuters,ap --max-articles 100

# Save results
ipfs-datasets finance news "earnings" --output news_data.json
```

### 3. GraphRAG News Analysis

Analyze news with knowledge graphs:

#### Python Package

```python
from ipfs_datasets_py.finance import (
    analyze_news_with_graphrag,
    create_financial_knowledge_graph
)
import json

# Load news and stock data
with open('news_data.json', 'r') as f:
    news_articles = json.load(f)

with open('stock_data.json', 'r') as f:
    stock_data = json.load(f)

# Analyze with GraphRAG
analysis = analyze_news_with_graphrag(
    news_articles=news_articles,
    stock_data=stock_data,
    analysis_type='executive_performance',
    hypothesis='Executive announcements correlate with stock movement',
    groups={'A': 'tech_companies', 'B': 'finance_companies'}
)

# Create knowledge graph
kg = create_financial_knowledge_graph(
    news_articles=news_articles,
    stock_data=stock_data
)

print(f"Analysis confidence: {analysis['confidence']}")
```

#### CLI

```bash
# Analyze executive performance
ipfs-datasets finance executives \
    --news news_data.json \
    --stocks stock_data.json \
    --hypothesis "CEO changes affect stock price" \
    --attribute "leadership_change" \
    --group-a tech_companies \
    --group-b finance_companies \
    --output analysis.json
```

### 4. Embedding Correlation Analysis

Analyze market correlations using embeddings:

#### Python Package

```python
from ipfs_datasets_py.finance import (
    calculate_embedding_correlation,
    analyze_multimodal_correlations
)

# Calculate embedding correlation
correlation = calculate_embedding_correlation(
    news_articles=news_data,
    stock_data=stock_data,
    time_window=7,  # days
    n_clusters=5
)

# Multimodal analysis (text + images)
multimodal = analyze_multimodal_correlations(
    news_articles=news_data,
    stock_data=stock_data,
    enable_multimodal=True,
    time_window=7,
    n_clusters=5
)

print(f"Found {len(correlation['patterns'])} correlation patterns")
```

#### CLI

```bash
# Embedding correlation analysis
ipfs-datasets finance embeddings \
    --news news_data.json \
    --stocks stock_data.json \
    --time-window 7 \
    --clusters 5 \
    --output correlations.json

# Enable multimodal
ipfs-datasets finance embeddings \
    --news news_data.json \
    --stocks stock_data.json \
    --multimodal \
    --output multimodal_analysis.json
```

### 5. Financial Theorems

Apply temporal deontic logic theorems to financial events:

#### Python Package

```python
from ipfs_datasets_py.finance import (
    list_finance_theorems,
    apply_theorem,
    validate_theorem_assumptions
)

# List available theorems
theorems = list_finance_theorems(event_type='stock_split')
print(f"Available theorems: {len(theorems)}")

# Apply theorem to event data
event_data = {
    'event_type': 'stock_split',
    'symbol': 'AAPL',
    'split_ratio': '4:1',
    'announcement_date': '2024-01-15',
    'effective_date': '2024-02-01',
    'stock_prices': [...]
}

result = apply_theorem(
    theorem_id='stock_split_price_adjustment',
    event_data=event_data
)

# Validate assumptions
valid, messages = validate_theorem_assumptions(
    theorem_id='stock_split_price_adjustment',
    event_data=event_data
)

print(f"Theorem result: {result['conclusion']}")
print(f"Confidence: {result['confidence']}")
```

#### CLI

```bash
# List all theorems
ipfs-datasets finance theorems --list

# List by event type
ipfs-datasets finance theorems --list --event-type merger

# Apply theorem
ipfs-datasets finance theorems \
    --apply stock_split_price_adjustment \
    --data event_data.json \
    --output theorem_result.json
```

## MCP Server Tools

The MCP tools provide the same functionality for AI assistants:

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools import (
    stock_scrapers,
    news_scrapers,
    graphrag_news_analyzer,
    embedding_correlation,
    finance_theorems
)

# These are the source implementations
# The finance package re-exports them for clean API
```

## Architecture Notes

### Integration Pattern

The finance module uses a **re-export pattern** to maintain clean separation:

- **Source of Truth**: MCP server tools (`mcp_server/tools/finance_data_tools/`)
- **Public API**: Finance package (`finance/__init__.py`) re-exports
- **CLI**: Imports from finance package (not MCP tools directly)

This ensures:
1. Single source of truth (MCP tools)
2. Clean public API (finance package)
3. Proper dependency direction (CLI → finance → MCP tools)

### Generic vs. Domain-Specific

**Finance-specific** (this module):
- `finance_theorems.py` - Financial event theorems (mergers, splits, etc.)
- `embedding_correlation.py` - Market-specific embedding analysis

**Generic infrastructure** (separate modules):
- `logic_integration/` - General theorem proving (used by legal, medical, finance)
- `embeddings/` - General embedding generation (used by all domains)

The finance tools are domain-specific applications of the generic infrastructure.

## Common Use Cases

### 1. Track Stock Performance

```bash
# Daily monitoring
ipfs-datasets finance stock AAPL --interval 1d --output daily.json
ipfs-datasets finance news "AAPL" --max-articles 20 --output news.json
ipfs-datasets finance embeddings --news news.json --stocks daily.json
```

### 2. Executive Performance Analysis

```bash
# Collect data
ipfs-datasets finance news "CEO announcements" --start 2024-01-01 --output ceo_news.json
ipfs-datasets finance stock AAPL --start 2024-01-01 --output aapl_stock.json

# Analyze
ipfs-datasets finance executives \
    --news ceo_news.json \
    --stocks aapl_stock.json \
    --hypothesis "CEO announcements impact stock" \
    --output analysis.json
```

### 3. Market Event Analysis with Theorems

```bash
# Apply financial theorem
ipfs-datasets finance theorems --list --event-type merger
ipfs-datasets finance theorems \
    --apply merger_price_impact \
    --data merger_event.json \
    --output theorem_analysis.json
```

## Tips and Best Practices

1. **Rate Limiting**: Financial APIs have rate limits. Space out requests appropriately.
2. **Data Quality**: Validate scraped data before analysis.
3. **Time Windows**: Use appropriate time windows for correlation analysis (7-30 days typical).
4. **Multimodal**: Enable multimodal analysis when articles contain relevant images.
5. **Theorem Selection**: Match theorems to specific event types for best results.

## Troubleshooting

### Import Errors

```python
# If imports fail, check if finance package is properly installed
from ipfs_datasets_py.finance import STOCK_AVAILABLE, NEWS_AVAILABLE
print(f"Stock tools: {STOCK_AVAILABLE}")
print(f"News tools: {NEWS_AVAILABLE}")
```

### Data Format Issues

All tools expect JSON format. Ensure your data files are valid JSON:

```bash
python -m json.tool your_file.json  # Validate JSON
```

### Missing Dependencies

Some features require optional dependencies:

```bash
pip install yfinance pandas numpy  # For enhanced stock scraping
pip install beautifulsoup4 requests  # For web scraping
```

## See Also

- [Email Usage Examples](email_usage_examples.md) - Email ingestion
- [Discord Usage Examples](discord_usage_examples.md) - Discord chat exports
- [GraphRAG Documentation](../README.md#graphrag) - Knowledge graph analysis
- [Logic Integration](../ipfs_datasets_py/logic_integration/README.md) - Theorem proving

# Finance Dashboard Integration Guide

This guide explains how to access the finance dashboard functionality through different interfaces: Python package imports, MCP server, CLI, and JavaScript MCP SDK.

## Overview

The finance dashboard tools are integrated into the `ipfs_datasets_py` library at multiple levels:

1. **Core Library** - Direct Python imports from `ipfs_datasets_py`
2. **MCP Server** - Auto-discovered tools accessible via MCP protocol
3. **CLI Tool** - Command-line interface via `ipfs-datasets finance`
4. **JavaScript SDK** - MCP client access from JavaScript/TypeScript

## 1. Python Package Imports

### Installation

```bash
pip install ipfs_datasets_py
```

### Direct Import Usage

```python
from ipfs_datasets_py import (
    # Core analyzers
    StockDataScraper,
    NewsScraperBase,
    FinancialTheoremLibrary,
    GraphRAGNewsAnalyzer,
    VectorEmbeddingAnalyzer,
    
    # MCP tool functions
    fetch_stock_data,
    fetch_financial_news,
    list_financial_theorems,
    analyze_executive_performance,
    analyze_embedding_market_correlation,
)

# Example: Analyze executive performance
analyzer = GraphRAGNewsAnalyzer()
executives = analyzer.extract_executive_profiles(news_articles)
result = analyzer.test_hypothesis(
    hypothesis="Female CEOs outperform male CEOs",
    attribute_name="gender",
    group_a_value="female",
    group_b_value="male",
    metric="return_percentage"
)
```

### Module-Level Imports

```python
# Import specific modules
from ipfs_datasets_py.mcp_server.tools.finance_data_tools import (
    stock_scrapers,
    news_scrapers,
    finance_theorems,
    graphrag_news_analyzer,
    embedding_correlation
)

# Use classes and functions
scraper = stock_scrapers.YahooFinanceScraper()
data = scraper.fetch_data("AAPL", "2024-01-01", "2024-12-31")
```

### Check Availability

```python
import ipfs_datasets_py

# Check if finance tools are available
if ipfs_datasets_py.HAVE_FINANCE_TOOLS:
    print("✓ Finance dashboard tools available")
    
    # Access components
    analyzer = ipfs_datasets_py.GraphRAGNewsAnalyzer()
    # ... use analyzer
else:
    print("✗ Finance tools not available - check dependencies")
```

## 2. MCP Server Integration

The finance tools are automatically discovered by the MCP server through the tools directory structure.

### Start MCP Server

```bash
# Start in stdio mode (default, for VS Code)
python -m ipfs_datasets_py.mcp_server

# Start in HTTP mode
python -m ipfs_datasets_py.mcp_server --http --host 0.0.0.0 --port 8000

# With debugging
python -m ipfs_datasets_py.mcp_server --debug
```

### Available MCP Tools

The server automatically exposes these tools:

1. **Stock Market Tools**
   - `fetch_stock_data` - Get OHLCV data for stocks
   - `fetch_corporate_actions` - Get splits, dividends, mergers

2. **News Intelligence Tools**
   - `fetch_financial_news` - Scrape news from AP/Reuters/Bloomberg
   - `search_archive_news` - Search archive.org for historical news

3. **Financial Theorems Tools**
   - `list_financial_theorems` - List all available theorems
   - `apply_financial_theorem` - Apply theorem to event data

4. **GraphRAG Analysis Tools**
   - `analyze_executive_performance` - Test hypothesis about executives
   - `extract_executive_profiles_from_archives` - Extract profiles from archives

5. **Vector Embedding Tools**
   - `analyze_embedding_market_correlation` - Correlate embeddings with markets
   - `find_predictive_embedding_patterns` - Discover predictive patterns

### Tool Discovery

Tools are auto-discovered from:
```
ipfs_datasets_py/mcp_server/tools/finance_data_tools/
├── stock_scrapers.py (tools: fetch_stock_data, fetch_corporate_actions)
├── news_scrapers.py (tools: fetch_financial_news, search_archive_news)
├── finance_theorems.py (tools: list_financial_theorems, apply_financial_theorem)
├── graphrag_news_analyzer.py (tools: analyze_executive_performance, extract_executive_profiles_from_archives)
└── embedding_correlation.py (tools: analyze_embedding_market_correlation, find_predictive_embedding_patterns)
```

## 3. CLI Tool Usage

### Installation

The CLI is available after installing the package:

```bash
pip install ipfs_datasets_py
```

### Command Structure

```bash
ipfs-datasets finance <command> [options]

# Or directly via Python module
python -m ipfs_datasets_py.finance_cli <command> [options]
```

### Available Commands

#### Fetch Stock Data

```bash
# Basic usage
ipfs-datasets finance stock AAPL --start 2024-01-01 --end 2024-12-31

# Save to file
ipfs-datasets finance stock AAPL --start 2024-01-01 --end 2024-12-31 --output aapl_data.json

# With custom interval
ipfs-datasets finance stock AAPL --interval 1h --output hourly_data.json
```

#### Fetch Financial News

```bash
# Basic usage
ipfs-datasets finance news "technology stocks" --start 2024-01-01 --end 2024-12-31

# Specify sources
ipfs-datasets finance news "CEO announcements" --sources reuters,bloomberg --max-articles 500

# Save to file
ipfs-datasets finance news "market analysis" --output news.json
```

#### Analyze Executives

```bash
# Test hypothesis about executives
ipfs-datasets finance executives \
    --news news_articles.json \
    --stocks stock_data.json \
    --hypothesis "Female CEOs outperform male CEOs" \
    --attribute gender \
    --group-a female \
    --group-b male \
    --output analysis_results.json
```

#### Analyze Embeddings

```bash
# Basic embedding analysis
ipfs-datasets finance embeddings \
    --news news_articles.json \
    --stocks stock_data.json \
    --output embedding_analysis.json

# With multimodal (text + images)
ipfs-datasets finance embeddings \
    --news news_articles.json \
    --stocks stock_data.json \
    --multimodal \
    --time-window 48 \
    --clusters 15 \
    --output multimodal_analysis.json
```

#### List/Apply Theorems

```bash
# List all theorems
ipfs-datasets finance theorems --list

# List theorems by event type
ipfs-datasets finance theorems --list --event-type STOCK_SPLIT

# Apply theorem
ipfs-datasets finance theorems \
    --apply stock_split_001 \
    --data event_data.json \
    --output theorem_result.json
```

### CLI Examples

**Example 1: Complete analysis workflow**
```bash
# Step 1: Fetch stock data
ipfs-datasets finance stock AAPL --start 2023-01-01 --end 2024-01-01 --output aapl.json

# Step 2: Fetch news
ipfs-datasets finance news "Apple CEO" --start 2023-01-01 --end 2024-01-01 --output apple_news.json

# Step 3: Analyze embeddings
ipfs-datasets finance embeddings --news apple_news.json --stocks aapl.json --multimodal --output analysis.json
```

**Example 2: Executive comparison**
```bash
# Fetch news about multiple CEOs
ipfs-datasets finance news "CEO leadership" --max-articles 1000 --output ceo_news.json

# Fetch stock data for multiple companies
ipfs-datasets finance stock TECH --output tech_stocks.json

# Compare by gender
ipfs-datasets finance executives \
    --news ceo_news.json \
    --stocks tech_stocks.json \
    --hypothesis "Female vs Male CEO performance" \
    --attribute gender \
    --group-a female \
    --group-b male \
    --output gender_analysis.json
```

## 4. JavaScript MCP SDK Integration

The finance tools are accessible from JavaScript/TypeScript via the MCP SDK.

### Installation

```bash
npm install @modelcontextprotocol/sdk
```

### Connect to MCP Server

```typescript
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

// Create transport (stdio mode)
const transport = new StdioClientTransport({
    command: 'python',
    args: ['-m', 'ipfs_datasets_py.mcp_server']
});

// Create client
const client = new Client({
    name: 'finance-dashboard-client',
    version: '1.0.0'
}, {
    capabilities: {
        tools: {}
    }
});

// Connect
await client.connect(transport);

// List available tools
const tools = await client.listTools();
console.log('Available tools:', tools);
```

### Call Finance Tools

```typescript
// Fetch stock data
const stockData = await client.callTool({
    name: 'fetch_stock_data',
    arguments: {
        symbol: 'AAPL',
        start_date: '2024-01-01',
        end_date: '2024-12-31',
        interval: '1d'
    }
});
console.log('Stock data:', JSON.parse(stockData.content[0].text));

// Fetch financial news
const news = await client.callTool({
    name: 'fetch_financial_news',
    arguments: {
        topic: 'technology stocks',
        start_date: '2024-01-01',
        end_date: '2024-12-31',
        sources: 'reuters,bloomberg',
        max_articles: 100
    }
});
console.log('News:', JSON.parse(news.content[0].text));

// Analyze executive performance
const analysis = await client.callTool({
    name: 'analyze_executive_performance',
    arguments: {
        news_articles_json: JSON.stringify(newsArticles),
        stock_data_json: JSON.stringify(stockData),
        hypothesis: 'Female CEOs outperform male CEOs',
        attribute: 'gender',
        group_a: 'female',
        group_b: 'male'
    }
});
console.log('Analysis:', JSON.parse(analysis.content[0].text));

// Analyze embeddings
const embeddings = await client.callTool({
    name: 'analyze_embedding_market_correlation',
    arguments: {
        news_articles_json: JSON.stringify(newsArticles),
        stock_data_json: JSON.stringify(stockData),
        enable_multimodal: true,
        time_window: 24,
        n_clusters: 10
    }
});
console.log('Embeddings:', JSON.parse(embeddings.content[0].text));
```

### Dashboard Integration Example

```typescript
// Example: Finance dashboard that uses MCP tools
class FinanceDashboard {
    constructor(private client: Client) {}
    
    async fetchMarketData(symbol: string) {
        const result = await this.client.callTool({
            name: 'fetch_stock_data',
            arguments: {
                symbol,
                start_date: this.getLastMonth(),
                end_date: this.getToday(),
                interval: '1d'
            }
        });
        return JSON.parse(result.content[0].text);
    }
    
    async analyzeExecutives(newsData: any[], stockData: any[]) {
        const result = await this.client.callTool({
            name: 'analyze_executive_performance',
            arguments: {
                news_articles_json: JSON.stringify(newsData),
                stock_data_json: JSON.stringify(stockData),
                hypothesis: 'Female CEOs outperform male CEOs',
                attribute: 'gender',
                group_a: 'female',
                group_b: 'male'
            }
        });
        return JSON.parse(result.content[0].text);
    }
    
    async correlateEmbeddings(newsData: any[], stockData: any[]) {
        const result = await this.client.callTool({
            name: 'analyze_embedding_market_correlation',
            arguments: {
                news_articles_json: JSON.stringify(newsData),
                stock_data_json: JSON.stringify(stockData),
                enable_multimodal: true,
                time_window: 24,
                n_clusters: 10
            }
        });
        return JSON.parse(result.content[0].text);
    }
    
    // ... more methods
}

// Usage
const dashboard = new FinanceDashboard(client);
const marketData = await dashboard.fetchMarketData('AAPL');
const analysis = await dashboard.analyzeExecutives(newsArticles, marketData);
```

### HTTP Mode (Alternative)

If using HTTP mode instead of stdio:

```typescript
// HTTP client example (custom implementation needed)
const response = await fetch('http://localhost:8000/tools/fetch_stock_data', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        symbol: 'AAPL',
        start_date: '2024-01-01',
        end_date: '2024-12-31'
    })
});
const data = await response.json();
```

## 5. Access Pattern Summary

| Access Method | Use Case | Command/Import |
|--------------|----------|----------------|
| **Python Package** | Direct library usage | `from ipfs_datasets_py import GraphRAGNewsAnalyzer` |
| **Python Modules** | Detailed access | `from ipfs_datasets_py.mcp_server.tools.finance_data_tools import stock_scrapers` |
| **MCP Server (stdio)** | VS Code, AI agents | `python -m ipfs_datasets_py.mcp_server` |
| **MCP Server (HTTP)** | Web services | `python -m ipfs_datasets_py.mcp_server --http` |
| **CLI** | Command line | `ipfs-datasets finance stock AAPL` |
| **JavaScript SDK** | Web dashboards | `await client.callTool({name: 'fetch_stock_data', ...})` |

## 6. Tool Function Reference

### fetch_stock_data

**Parameters:**
- `symbol` (str): Stock ticker
- `start_date` (str): Start date (YYYY-MM-DD)
- `end_date` (str): End date (YYYY-MM-DD)  
- `interval` (str): Data interval (1d, 1h, etc.)

**Returns:** JSON with OHLCV data

### fetch_financial_news

**Parameters:**
- `topic` (str): Search query
- `start_date` (str): Start date
- `end_date` (str): End date
- `sources` (str): Comma-separated sources
- `max_articles` (int): Maximum articles

**Returns:** JSON with news articles

### analyze_executive_performance

**Parameters:**
- `news_articles_json` (str): News JSON string
- `stock_data_json` (str): Stock JSON string
- `hypothesis` (str): Hypothesis statement
- `attribute` (str): Attribute to compare
- `group_a` (str): Group A value
- `group_b` (str): Group B value

**Returns:** JSON with hypothesis test results

### analyze_embedding_market_correlation

**Parameters:**
- `news_articles_json` (str): News JSON string
- `stock_data_json` (str): Stock JSON string
- `enable_multimodal` (bool): Enable text+image
- `time_window` (int): Hours for market impact
- `n_clusters` (int): Number of clusters

**Returns:** JSON with correlation analysis

## 7. Dashboard Integration

### Web Dashboard (JavaScript/React)

```javascript
// React component example
import React, { useEffect, useState } from 'react';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';

function FinanceDashboard() {
    const [client, setClient] = useState(null);
    const [data, setData] = useState(null);
    
    useEffect(() => {
        // Initialize MCP client
        const initClient = async () => {
            const mcpClient = new Client({/*...*/});
            await mcpClient.connect(/*...*/);
            setClient(mcpClient);
        };
        initClient();
    }, []);
    
    const fetchData = async () => {
        if (!client) return;
        
        const result = await client.callTool({
            name: 'fetch_stock_data',
            arguments: { symbol: 'AAPL', /*...*/ }
        });
        setData(JSON.parse(result.content[0].text));
    };
    
    return (
        <div>
            <button onClick={fetchData}>Fetch Data</button>
            {data && <div>{/* Render data */}</div>}
        </div>
    );
}
```

### Backend Service (Node.js)

```javascript
// Express.js API endpoint
const express = require('express');
const { Client } = require('@modelcontextprotocol/sdk/client');

const app = express();
let mcpClient;

// Initialize MCP client on startup
async function initMCP() {
    mcpClient = new Client({/*...*/});
    await mcpClient.connect(/*...*/);
}

// API endpoint
app.post('/api/finance/stock', async (req, res) => {
    const { symbol, startDate, endDate } = req.body;
    
    const result = await mcpClient.callTool({
        name: 'fetch_stock_data',
        arguments: { symbol, start_date: startDate, end_date: endDate }
    });
    
    res.json(JSON.parse(result.content[0].text));
});

initMCP().then(() => {
    app.listen(3000, () => console.log('Server running'));
});
```

## 8. Troubleshooting

### Issue: Finance tools not available

**Check availability:**
```python
import ipfs_datasets_py
print(f"Finance tools available: {ipfs_datasets_py.HAVE_FINANCE_TOOLS}")
```

**Solution:** Ensure all dependencies are installed:
```bash
pip install flask  # Required dependency
```

### Issue: MCP server not discovering tools

**Verify tool directory:**
```bash
ls ipfs_datasets_py/mcp_server/tools/finance_data_tools/
```

**Check tool files have MCP functions** (functions not starting with `_`)

### Issue: CLI command not found

**Solution:** Ensure package is installed:
```bash
pip install -e .  # For development
pip install ipfs_datasets_py  # For production
```

## 9. Production Deployment

### Deploy MCP Server

```bash
# As a service (systemd example)
[Unit]
Description=IPFS Datasets MCP Server
After=network.target

[Service]
Type=simple
User=mcp
WorkingDirectory=/opt/ipfs_datasets
ExecStart=/usr/bin/python3 -m ipfs_datasets_py.mcp_server --http --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

### Docker Deployment

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY . .

RUN pip install -e .

EXPOSE 8000

CMD ["python", "-m", "ipfs_datasets_py.mcp_server", "--http", "--host", "0.0.0.0", "--port", "8000"]
```

### Environment Variables

```bash
# Optional configuration
export IPFS_DATASETS_AUTO_INSTALL=true
export ALPHA_VANTAGE_API_KEY=your_key
export POLYGON_IO_API_KEY=your_key
```

## Support

- **Documentation**: See module README files
- **Issues**: https://github.com/endomorphosis/ipfs_datasets_py/issues
- **Examples**: See `tests/finance_dashboard/` for usage examples

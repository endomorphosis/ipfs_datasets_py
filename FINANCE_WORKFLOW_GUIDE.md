# Finance Workflow Pipeline Guide

## Overview

The Finance Workflow Pipeline Dashboard provides a comprehensive, end-to-end demonstration of financial data processing using the MCP (Model Context Protocol) JavaScript SDK. This guide covers the complete workflow from data scraping to synthetic dataset generation.

## Workflow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Finance Workflow Pipeline                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  1. SCRAPE          2. FILTER         3. ANALYZE                │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐              │
│  │ Stocks   │──┐   │ Quality  │──┐   │Embeddings│──┐           │
│  │ News     │  │   │ Dedupe   │  │   │  K-Graph │  │           │
│  │ Archives │  │   │ Label    │  │   │ Patterns │  │           │
│  └──────────┘  │   └──────────┘  │   └──────────┘  │           │
│                │                  │                  │           │
│  4. HYPOTHESIZE     5. TRANSFORM      6. EXPORT                 │
│  ┌──────────┐  │   ┌──────────┐  │   ┌──────────┐  │           │
│  │ Generate │◄─┘   │ Augment  │◄─┘   │ IPFS/CAR │◄─┘           │
│  │ Test     │──┐   │ Enrich   │──┐   │ Metadata │              │
│  │ Validate │  │   │ Quality  │  │   │ Download │              │
│  └──────────┘  │   └──────────┘  │   └──────────┘              │
│                └───────────────────┘                             │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Access Methods

### 1. Interactive Dashboard

Navigate to the workflow dashboard:
```
http://localhost:8899/mcp/finance/workflow
```

The dashboard provides:
- Visual step-by-step pipeline execution
- Real-time progress tracking
- Interactive configuration forms
- Result visualization
- JavaScript SDK code examples

### 2. CLI Interface

Execute workflows from command line:

```bash
# Start MCP server
ipfs-datasets mcp start

# Execute complete pipeline
ipfs-datasets finance workflow pipeline \
    --symbols AAPL,MSFT,GOOGL \
    --start 2023-01-01 \
    --end 2024-12-31 \
    --sources reuters,bloomberg,ap \
    --hypothesis "Female CEOs outperform male CEOs" \
    --export synthetic_finance_dataset.car

# Individual steps
ipfs-datasets finance stock AAPL --start 2024-01-01 --end 2024-12-31
ipfs-datasets finance news "tech stocks" --sources reuters --max-results 100
ipfs-datasets finance executives --news news.json --stocks stocks.json
ipfs-datasets finance embeddings --news news.json --multimodal --clusters 10
ipfs-datasets finance theorems --list
```

### 3. Python API

Use directly in Python code:

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools import (
    fetch_stock_data,
    fetch_financial_news,
    analyze_executive_performance,
    analyze_embedding_market_correlation
)

# Scrape data
stocks = fetch_stock_data(symbol="AAPL", start_date="2024-01-01")
news = fetch_financial_news(query="AAPL", sources=["reuters"])

# Analyze
results = analyze_executive_performance(
    news_articles_json=json.dumps(news),
    stock_data_json=json.dumps(stocks),
    hypothesis="Female CEOs outperform male CEOs"
)
```

### 4. JavaScript/TypeScript SDK

Integrate with web applications:

```javascript
// Initialize MCP client
const mcpClient = new MCPClient({
    serverUrl: 'http://localhost:8899/api/mcp'
});

// Execute workflow
async function runFinanceWorkflow() {
    // Step 1: Scrape
    const stocks = await mcpClient.callTool({
        name: 'fetch_stock_data',
        arguments: { symbol: 'AAPL', start_date: '2024-01-01' }
    });
    
    const news = await mcpClient.callTool({
        name: 'fetch_financial_news',
        arguments: { query: 'AAPL', sources: ['reuters'] }
    });
    
    // Step 2: Analyze
    const analysis = await mcpClient.callTool({
        name: 'analyze_embedding_market_correlation',
        arguments: {
            news_articles_json: JSON.stringify(news),
            enable_multimodal: true,
            n_clusters: 10
        }
    });
    
    // Step 3: Test hypotheses
    const hypothesis = await mcpClient.callTool({
        name: 'analyze_executive_performance',
        arguments: {
            news_articles_json: JSON.stringify(news),
            stock_data_json: JSON.stringify(stocks),
            hypothesis: 'Female CEOs outperform male CEOs',
            attribute: 'gender',
            group_a: 'female',
            group_b: 'male'
        }
    });
    
    return { stocks, news, analysis, hypothesis };
}
```

## Pipeline Stages

### Stage 1: Data Scraping

**Purpose**: Collect raw financial data from multiple sources

**Data Sources**:
- Stock market data (Yahoo Finance, Alpha Vantage, Polygon.io)
- News articles (AP, Reuters, Bloomberg)
- Historical archives (archive.org Wayback Machine)

**Configuration**:
```javascript
{
    symbols: ['AAPL', 'MSFT', 'GOOGL'],
    startDate: '2024-01-01',
    endDate: '2024-12-31',
    sources: ['reuters', 'bloomberg', 'ap'],
    maxArticlesPerSource: 100
}
```

**Outputs**:
- OHLCV stock data with validation
- News articles with metadata
- Corporate actions (splits, dividends)

### Stage 2: Data Filtering & Labeling

**Purpose**: Clean, deduplicate, and label data for quality control

**Filters Applied**:
- Quality threshold scoring
- Duplicate detection (SHA-256 hashing)
- Short article removal (<100 words)
- Source credibility scoring

**Labeling Categories**:
- Data quality (0-100 score)
- Entity tags (CEO, company, product)
- Sentiment labels
- Topic categories

**Configuration**:
```javascript
{
    qualityThreshold: 70,
    removeDuplicates: true,
    removeShortArticles: true,
    enableLabeling: true
}
```

### Stage 3: Analysis & Knowledge Graph

**Purpose**: Extract insights, generate embeddings, build knowledge graphs

**Analysis Types**:

1. **Vector Embeddings**:
   - Text embeddings (768-dim transformers)
   - Image embeddings (512-dim CLIP)
   - Multimodal fusion

2. **Knowledge Graph**:
   - Entity extraction (executives, companies, products)
   - Relationship mapping (leads, founded, acquired)
   - Temporal constraints

3. **Pattern Discovery**:
   - Clustering (thematic groups)
   - Latent factor extraction
   - Correlation patterns

**Configuration**:
```javascript
{
    analysisType: 'both', // 'embeddings', 'knowledge-graph', or 'both'
    enableMultimodal: true,
    nClusters: 10,
    extractEntities: true
}
```

### Stage 4: Hypothesis Generation & Testing

**Purpose**: Generate and statistically test hypotheses about market behavior

**Built-in Hypotheses**:

1. **Female vs Male CEOs**: Do female CEOs deliver better returns?
2. **Introvert vs Extrovert**: Are introverted leaders more effective?
3. **MBA Education**: Does MBA education correlate with growth?
4. **Tenure Length**: Does longer tenure correlate with stability?

**Statistical Tests**:
- T-tests for group comparisons
- ANOVA for multi-group analysis
- Correlation analysis
- Confidence intervals and p-values

**Configuration**:
```javascript
{
    hypotheses: [
        {
            name: 'Female CEOs outperform male CEOs',
            attribute: 'gender',
            groupA: 'female',
            groupB: 'male',
            metric: 'return_percentage'
        }
    ]
}
```

**Results Format**:
```json
{
    "hypothesis": "Female CEOs outperform male CEOs",
    "p_value": 0.042,
    "group_a_mean": 45.2,
    "group_b_mean": 32.1,
    "difference": 13.1,
    "conclusion": "Statistically significant",
    "confidence_level": 0.95
}
```

### Stage 5: Data Transformation & Augmentation

**Purpose**: Transform and augment data to create high-quality synthetic datasets

**Augmentation Strategies**:

1. **Paraphrasing**: Rephrase text while preserving meaning
2. **Back-translation**: Translate to another language and back
3. **Entity Swapping**: Replace entities with similar ones
4. **Contextual**: Use language models for semantic variations

**Quality Control**:
- Automated quality scoring
- Semantic similarity validation
- Human-in-the-loop review (optional)

**Configuration**:
```javascript
{
    strategy: 'paraphrase', // or 'backtranslation', 'entity-swap', 'all'
    augmentationFactor: 3, // Generate 3x original size
    qualityCheck: true,
    minQualityScore: 0.7
}
```

### Stage 6: Export Synthetic Dataset

**Purpose**: Package and export the synthetic dataset with metadata

**Export Formats**:
- **IPFS CAR**: Content-addressed archive for decentralized storage
- **JSON**: Structured format with full metadata
- **CSV**: Tabular format for analysis tools
- **Parquet**: Columnar format for big data processing

**Metadata Included**:
```json
{
    "name": "synthetic_finance_dataset",
    "created": "2024-01-15T10:00:00Z",
    "sources": ["reuters", "bloomberg", "ap"],
    "original_count": 250,
    "augmented_count": 750,
    "quality_score": 0.92,
    "hypotheses_tested": 4,
    "significant_findings": 2,
    "ipfs_hash": "QmXyz123...",
    "version": "1.0.0"
}
```

**IPFS Integration**:
```javascript
// Export to IPFS
const dataset = {
    data: transformedData,
    metadata: metadata
};

const carFile = await exportToCAR(dataset);
const ipfsHash = await pinToIPFS(carFile);

console.log(`Dataset pinned: ${ipfsHash}`);
// Access at: ipfs://QmXyz123...
```

## Use Cases

### 1. Executive Performance Research

**Goal**: Determine if executive characteristics predict company performance

**Workflow**:
1. Scrape news about CEOs and their companies
2. Filter for articles with executive profiles
3. Extract attributes (gender, personality, education)
4. Link to stock performance data
5. Test hypotheses statistically
6. Generate report with findings

**Example Findings**:
- Female CEOs showed 13.1% higher returns (p=0.042)
- Introverted leaders performed better in volatile markets (p=0.031)

### 2. Market Sentiment Analysis

**Goal**: Predict stock movements from news sentiment and embeddings

**Workflow**:
1. Scrape financial news continuously
2. Generate multimodal embeddings (text + images)
3. Cluster by topic and sentiment
4. Correlate with short-term price movements
5. Identify predictive patterns
6. Export training dataset for ML models

**Example Patterns**:
- Cluster 5 articles predict 3%+ moves within 24h (correlation: 0.85)
- Articles with CEO photos showing concern correlate with declines

### 3. Synthetic Dataset Generation for ML

**Goal**: Create high-quality training data for financial NLP models

**Workflow**:
1. Scrape diverse financial news
2. Filter for quality and relevance
3. Label with sentiment, entities, events
4. Augment using multiple strategies
5. Validate quality
6. Export to ML-ready format

**Output**:
- 750 high-quality training examples (from 250 originals)
- Average quality score: 0.92
- Multiple formats (JSON, CSV, Parquet)
- Ready for fine-tuning financial models

## Production Deployment

### Requirements

**Infrastructure**:
- MCP server running on port 8899
- IPFS node (optional, for dataset storage)
- PostgreSQL (optional, for caching)

**Dependencies**:
```bash
pip install yfinance requests beautifulsoup4
pip install sentence-transformers transformers torch
pip install spacy scikit-learn scipy
pip install ipfs-car-py  # For IPFS CAR file generation
```

**Environment Variables**:
```bash
export ALPHA_VANTAGE_API_KEY="your_key"
export POLYGON_IO_API_KEY="your_key"
export IPFS_HTTP_GATEWAY="https://ipfs.io"
```

### Scaling Considerations

**For Large-Scale Processing**:

1. **Parallel Scraping**: Use task queue (Celery) for concurrent scraping
2. **Caching**: Redis for intermediate results
3. **Batch Processing**: Process data in batches to manage memory
4. **Distributed Storage**: IPFS cluster for dataset distribution
5. **Monitoring**: Prometheus + Grafana for pipeline metrics

**Example Architecture**:
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Web UI    │────▶│ MCP Server  │────▶│ Task Queue  │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                     │
                           ▼                     ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   Redis     │     │  Workers    │
                    │   Cache     │     │  (Celery)   │
                    └─────────────┘     └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │ IPFS Cluster│
                                        └─────────────┘
```

### Security & Privacy

**Best Practices**:

1. **API Keys**: Store in environment variables or secrets manager
2. **Rate Limiting**: Implement per-user/IP rate limits
3. **Data Sanitization**: Clean PII from scraped data
4. **Access Control**: Authenticate API requests
5. **Audit Logging**: Log all pipeline executions

## Troubleshooting

### Common Issues

**Issue**: "MCP Server not responding"
**Solution**: Check if server is running on correct port
```bash
ipfs-datasets mcp status
ipfs-datasets mcp start
```

**Issue**: "Failed to scrape news"
**Solution**: Check API keys and rate limits
```bash
# Test individual scraper
ipfs-datasets finance news "test query" --sources reuters
```

**Issue**: "Quality filtering removed all data"
**Solution**: Lower quality threshold or check data sources
```javascript
{ qualityThreshold: 50 }  // Lower from default 70
```

**Issue**: "Hypothesis test shows no significance"
**Solution**: May need more data or different groupings
```javascript
// Increase sample size or try different attributes
{ minSampleSize: 50 }
```

## Next Steps

### Extending the Pipeline

**Add New Data Sources**:
```python
# In stock_scrapers.py, add new scraper class
class AlphaVantageScraper(StockDataScraper):
    def fetch_data(self, symbol, start_date, end_date):
        # Implementation
        pass
```

**Add Custom Hypotheses**:
```python
# In graphrag_news_analyzer.py
def test_custom_hypothesis(self, data, hypothesis_config):
    # Your custom statistical test
    return HypothesisTestResult(...)
```

**Add New Augmentation Strategy**:
```python
# In embedding_correlation.py
def augment_contextual(self, text):
    # Use LLM for contextual augmentation
    return augmented_text
```

## Support & Documentation

- **Full API Reference**: See `FINANCE_INTEGRATION_GUIDE.md`
- **MCP Tools Documentation**: See `finance_data_tools/README.md`
- **Issues**: Report at https://github.com/endomorphosis/ipfs_datasets_py/issues

## License

MIT License - See LICENSE file for details

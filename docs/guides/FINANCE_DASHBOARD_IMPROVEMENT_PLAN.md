# Finance Dashboard Comprehensive Improvement Plan

## Executive Summary

This document outlines a comprehensive plan to enhance the MCP finance dashboard with advanced data scraping, knowledge graph generation, and temporal deontic logic reasoning capabilities for financial market analysis.

## Current State

### Existing Infrastructure
- **Dashboard Location**: `https://localhost:8899/mcp/finance`
- **Backend**: `ipfs_datasets_py/mcp_dashboard.py` (lines 1237-1436)
- **Template**: `ipfs_datasets_py/templates/admin/finance_dashboard_mcp.html`
- **Logic System**: `logic_integration/temporal_deontic_rag_store.py`
- **Scraper Infrastructure**: `mcp_server/tools/legal_dataset_tools/` (can be adapted)
- **Archive Tools**: `web_archive.py`, `web_archive_utils.py`

### Current Capabilities
- Basic temporal deontic logic framework (inherited from caselaw system)
- Document consistency checking
- RAG-based theorem retrieval
- Web archiving infrastructure
- GraphRAG integration foundation

## Vision & Goals

### Primary Objectives
1. **Comprehensive Market Data Collection**: Scrape time series data from stock, currency, bond, futures, and crypto markets
2. **News Intelligence**: Extract and archive financial news from AP, Reuters, Bloomberg with archive.org fallbacks
3. **Knowledge Graph Construction**: Build temporal knowledge graphs of business entities, relationships, and events
4. **Symbolic Reasoning**: Develop temporal deontic logic theorems for financial rules and causal chains
5. **Predictive Analysis**: Use fuzzy logic and symbolic reasoning for market pattern recognition

## Detailed Implementation Plan

### Phase 1: Market Data Scraper Infrastructure

#### 1.1 Stock Market Data Scrapers
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/stock_scrapers.py`

**Data Sources**:
- Yahoo Finance API (yfinance library)
- Alpha Vantage API
- Polygon.io API
- IEX Cloud
- Quandl

**Data Points to Collect**:
```python
{
    "symbol": "AAPL",
    "timestamp": "2024-01-01T09:30:00Z",
    "open": 150.00,
    "high": 152.50,
    "low": 149.50,
    "close": 151.00,
    "volume": 1000000,
    "adjusted_close": 151.00,
    "metadata": {
        "splits": [],
        "dividends": [],
        "corporate_actions": []
    }
}
```

**Implementation Requirements**:
- Rate limiting and API key management
- Retry logic with exponential backoff
- Data validation and normalization
- IPFS storage integration
- Historical data backfill capabilities

#### 1.2 Currency/Forex Data Scrapers
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/forex_scrapers.py`

**Data Sources**:
- OANDA API
- Forex.com
- XE.com
- Central bank APIs (Fed, ECB, BoJ, etc.)

**Currency Pairs**:
- Major pairs (EUR/USD, GBP/USD, USD/JPY, etc.)
- Minor pairs
- Exotic pairs
- Cryptocurrency pairs

#### 1.3 Bonds and Treasury Data Scrapers
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/bond_scrapers.py`

**Data Sources**:
- US Treasury Direct
- Federal Reserve Economic Data (FRED)
- Bloomberg (via web archive)
- Municipal bond databases

**Data Points**:
- Yield curves (2Y, 5Y, 10Y, 30Y)
- Credit spreads
- Municipal bond data
- Corporate bond indices

#### 1.4 Futures Market Data Scrapers
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/futures_scrapers.py`

**Data Sources**:
- CME Group
- ICE (Intercontinental Exchange)
- Eurex
- Commodity futures databases

**Contracts**:
- Commodity futures (oil, gold, agricultural)
- Index futures (S&P 500, NASDAQ)
- Currency futures
- Interest rate futures

#### 1.5 Cryptocurrency Data Scrapers
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/crypto_scrapers.py`

**Data Sources**:
- CoinGecko API
- CoinMarketCap API
- Binance API
- Kraken API
- On-chain data (Etherscan, etc.)

**Data Points**:
- Price data (OHLCV)
- Market cap and volume
- On-chain metrics
- DeFi protocol data

### Phase 2: Financial News Scrapers

#### 2.1 News Source Scrapers
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/news_scrapers.py`

**Primary Sources**:
```python
NEWS_SOURCES = {
    "ap_news": {
        "url": "https://apnews.com/hub/financial-markets",
        "archive_fallback": "https://web.archive.org/web/*/apnews.com/*",
        "scraper_type": "rss_feed"
    },
    "reuters": {
        "url": "https://www.reuters.com/finance/",
        "archive_fallback": "https://web.archive.org/web/*/reuters.com/*",
        "scraper_type": "html_parser"
    },
    "bloomberg": {
        "url": "https://www.bloomberg.com/markets",
        "archive_fallback": "https://web.archive.org/web/*/bloomberg.com/*",
        "scraper_type": "selenium_js"
    }
}
```

**Archive.org Integration**:
- Wayback Machine API for historical articles
- CDX Server API for bulk queries
- Common Crawl for large-scale text extraction
- Internet Archive Scholar for financial research papers

**Data Schema**:
```python
{
    "article_id": "uuid",
    "source": "reuters",
    "url": "https://...",
    "title": "...",
    "content": "...",
    "published_date": "2024-01-01T12:00:00Z",
    "authors": ["..."],
    "entities_mentioned": {
        "companies": ["AAPL", "MSFT"],
        "people": ["CEO Name"],
        "events": ["merger", "earnings"]
    },
    "sentiment": {
        "overall": 0.6,
        "entity_specific": {...}
    },
    "archive_urls": [
        "https://web.archive.org/..."
    ],
    "ipfs_cid": "Qm..."
}
```

#### 2.2 Archive Tool Integration
**Location**: Extend `ipfs_datasets_py/web_archive.py`

**Capabilities**:
- Automatic archiving of scraped articles to archive.org
- Fallback retrieval from Wayback Machine
- IPFS pinning for decentralized storage
- Version tracking and change detection

### Phase 3: Time Series Data Management

#### 3.1 Data Storage Schema
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/timeseries_storage.py`

**IPFS-Native Time Series Design**:
```python
class FinancialTimeSeriesStore:
    """
    Store financial time series data in IPFS with efficient temporal indexing.
    
    Structure:
    - Daily snapshots as IPLD DAG nodes
    - Merkle tree indexing for range queries
    - Chunked storage for large datasets
    """
    
    def store_timeseries(self, symbol, data, timeframe):
        """Store time series data with temporal indexing."""
        pass
    
    def query_range(self, symbol, start_date, end_date):
        """Efficient range queries using IPLD traversal."""
        pass
    
    def update_latest(self, symbol, new_data):
        """Append new data points efficiently."""
        pass
```

**Indexing Strategy**:
- Time-based sharding (daily, weekly, monthly)
- Symbol-based partitioning
- IPLD DAG for efficient traversal
- Bloom filters for existence checks

#### 3.2 Data Validation Pipeline
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/data_validator.py`

**Validation Rules**:
```python
class FinancialDataValidator:
    """Validate and clean financial data."""
    
    def validate_price_data(self, data):
        """
        Checks:
        - OHLC consistency (High >= Low, Open/Close within range)
        - Volume positivity
        - Timestamp ordering
        - Outlier detection
        - Corporate action adjustments
        """
        pass
    
    def detect_anomalies(self, timeseries):
        """Statistical anomaly detection."""
        pass
    
    def adjust_for_splits(self, data, corporate_actions):
        """Adjust historical prices for stock splits."""
        pass
```

### Phase 4: Knowledge Graph Construction

#### 4.1 Entity Extraction from News
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/entity_extractor.py`

**Extraction Pipeline**:
```python
class FinancialEntityExtractor:
    """Extract financial entities and relationships from text."""
    
    def extract_entities(self, text):
        """
        Extract:
        - Companies (with ticker symbols)
        - People (executives, analysts)
        - Products and services
        - Financial instruments
        - Events (mergers, acquisitions, earnings)
        - Locations (markets, countries)
        """
        pass
    
    def extract_relationships(self, text, entities):
        """
        Relationships:
        - Company-Person (CEO_OF, ANALYST_COVERS)
        - Company-Company (ACQUIRES, COMPETES_WITH, SUPPLIES_TO)
        - Company-Event (ANNOUNCES, PARTICIPATES_IN)
        - Temporal relationships (BEFORE, AFTER, DURING)
        """
        pass
```

**Integration with GraphRAG**:
- Use existing `ipfs_datasets_py/graphrag_integration.py`
- Extend with financial domain knowledge
- Link entities to market data

#### 4.2 Temporal Knowledge Graph
**Location**: `ipfs_datasets_py/mcp_server/tools/finance_data_tools/finance_knowledge_graph.py`

**Graph Schema**:
```python
class FinancialKnowledgeGraph:
    """Build and query temporal knowledge graphs."""
    
    # Node Types
    COMPANY = "company"
    PERSON = "person"
    EVENT = "event"
    FINANCIAL_INSTRUMENT = "instrument"
    
    # Edge Types with Temporal Validity
    edges = {
        ("AAPL", "CEO_OF", "Tim Cook"): {
            "valid_from": "2011-08-24",
            "valid_to": None,
            "confidence": 1.0
        },
        ("AAPL", "STOCK_SPLIT", "4:1 Split"): {
            "valid_from": "2020-08-31",
            "valid_to": "2020-08-31",
            "confidence": 1.0,
            "metadata": {
                "split_ratio": 4,
                "pre_split_price": 499.23,
                "post_split_price": 124.81
            }
        }
    }
    
    def add_temporal_fact(self, subject, predicate, object, 
                          valid_from, valid_to, confidence):
        """Add fact with temporal validity."""
        pass
    
    def query_at_time(self, time, entity):
        """Query graph state at specific time."""
        pass
```

**IPLD Storage**:
- Store graph as IPLD DAG
- Version history through CID chains
- Efficient temporal queries

### Phase 5: Temporal Deontic Logic for Finance

#### 5.1 Financial Theorem Templates
**Location**: `ipfs_datasets_py/logic_integration/finance_theorems.py`

**Theorem Examples**:
```python
class FinancialTheorems:
    """
    Define financial rules as temporal deontic logic theorems.
    """
    
    STOCK_SPLIT_THEOREM = {
        "name": "stock_split_price_adjustment",
        "formula": """
        ∀s,t,r: (StockSplit(s, t, r) → 
            O(AdjustPrice(s, t, Price(s, t-) / r)))
        
        Translation: If stock s has a split at time t with ratio r,
        then it is OBLIGATORY to adjust the price to the pre-split 
        price divided by the split ratio.
        """,
        "fuzzy_confidence": lambda data: calculate_split_confidence(data),
        "applicability_conditions": [
            "has_corporate_action",
            "action_type == 'split'",
            "valid_split_ratio"
        ]
    }
    
    MERGER_THEOREM = {
        "name": "merger_price_convergence",
        "formula": """
        ∀a,b,t,p: (Merger(a, b, t, premium=p) →
            P(Price(b, t+) ≈ Price(a, t) × ExchangeRatio(a, b, t)))
        
        Translation: If company a acquires company b at time t with 
        exchange ratio, then it is PERMITTED that the price of b's 
        stock converges to a's price times the exchange ratio.
        """,
        "fuzzy_logic": {
            "convergence_threshold": 0.02,  # 2% tolerance
            "time_window": "30 days"
        }
    }
    
    DIVIDEND_THEOREM = {
        "name": "ex_dividend_price_adjustment",
        "formula": """
        ∀s,t,d: (ExDividendDate(s, t) ∧ DividendAmount(s, d) →
            O(Price(s, t) ≈ Price(s, t-) - d))
        
        Translation: On ex-dividend date t for stock s with dividend d,
        the opening price OUGHT to be approximately the previous close 
        minus the dividend amount.
        """
    }
```

#### 5.2 Fuzzy Logic System
**Location**: `ipfs_datasets_py/logic_integration/finance_fuzzy_logic.py`

**Fuzzy Logic Implementation**:
```python
class FinancialFuzzyLogicEngine:
    """
    Apply fuzzy logic to financial theorems for soft constraints.
    """
    
    def evaluate_theorem(self, theorem, market_data, threshold=0.7):
        """
        Evaluate theorem with fuzzy logic.
        
        Returns confidence score [0, 1] indicating how well the
        market data matches the expected behavior.
        """
        pass
    
    def membership_functions(self):
        """
        Define membership functions for fuzzy sets:
        - Price_Near(target, tolerance)
        - Volume_High(threshold)
        - Volatility_Low(threshold)
        """
        pass
    
    def fuzzy_rules(self):
        """
        IF price_change is LARGE AND volume is HIGH 
        THEN confidence is VERY_HIGH
        
        IF price_matches_theorem is CLOSE AND time_proximity is NEAR
        THEN theorem_validity is HIGH
        """
        pass
```

#### 5.3 Causal Reasoning Chain
**Location**: `ipfs_datasets_py/logic_integration/finance_causal_reasoning.py`

**Causal Chain Builder**:
```python
class FinancialCausalChain:
    """
    Build and validate causal reasoning chains for market events.
    """
    
    def build_chain(self, event, knowledge_graph, market_data):
        """
        Example chain:
        1. Company A announces merger with Company B (NEWS)
        2. Company B stock price rises (MARKET DATA)
        3. Analyst upgrades Company B rating (NEWS)
        4. Institutional investors increase holdings (MARKET DATA)
        5. Merger completes (EVENT)
        6. Stock prices converge per exchange ratio (THEOREM)
        
        Each step has:
        - Temporal ordering
        - Causal relationship type (causes, enables, prevents)
        - Confidence score
        - Supporting evidence (news, data, theorems)
        """
        pass
    
    def validate_chain(self, chain):
        """
        Validate causal chain using:
        - Temporal consistency (causes precede effects)
        - Logical consistency with theorems
        - Statistical significance in market data
        - News sentiment alignment
        """
        pass
    
    def explain_prediction(self, prediction):
        """
        Generate human-readable explanation of reasoning chain.
        
        "Based on the announced merger on Jan 1, we expect Company B's
        stock to converge to $X because:
        1. Historical merger theorem (95% confidence)
        2. Exchange ratio of 1.5:1 announced
        3. Market has not yet fully priced in the merger
        4. Similar mergers showed 30-day convergence pattern"
        """
        pass
```

### Phase 6: Dashboard UI Enhancements

#### 6.1 Real-Time Data Visualization
**Location**: Extend `ipfs_datasets_py/templates/admin/finance_dashboard_mcp.html`

**New Components**:
```html
<!-- Market Data Dashboard -->
<div class="card">
    <div class="card-header">
        <h5>Real-Time Market Data</h5>
    </div>
    <div class="card-body">
        <!-- Multi-asset price charts -->
        <div id="price-charts"></div>
        
        <!-- Market heatmap -->
        <div id="market-heatmap"></div>
        
        <!-- Volume indicators -->
        <div id="volume-chart"></div>
    </div>
</div>

<!-- Knowledge Graph Visualization -->
<div class="card">
    <div class="card-header">
        <h5>Business Entity Knowledge Graph</h5>
    </div>
    <div class="card-body">
        <!-- Interactive graph using D3.js or Cytoscape.js -->
        <div id="knowledge-graph-viz"></div>
        
        <!-- Entity inspector -->
        <div id="entity-details"></div>
    </div>
</div>

<!-- Reasoning Chain Display -->
<div class="card">
    <div class="card-header">
        <h5>Causal Reasoning Chain</h5>
    </div>
    <div class="card-body">
        <!-- Step-by-step reasoning visualization -->
        <div id="reasoning-chain"></div>
        
        <!-- Confidence scores -->
        <div id="confidence-metrics"></div>
    </div>
</div>
```

**JavaScript Libraries**:
- Chart.js or Plotly.js for time series
- D3.js for knowledge graph
- DataTables for data grids
- Socket.IO for real-time updates

#### 6.2 Interactive Query Interface
**Location**: Add to finance dashboard template

**Query Types**:
1. **Temporal Queries**: "What was AAPL's price on 2020-08-31?"
2. **Causal Queries**: "Why did TSLA stock rise on X date?"
3. **Theorem Queries**: "Find all stock splits in 2023"
4. **Graph Queries**: "Show all companies acquired by MSFT"
5. **News Queries**: "Find news about mergers in tech sector"

**UI Components**:
```html
<div class="query-interface">
    <div class="form-group">
        <label>Query Type</label>
        <select class="form-control" id="query-type">
            <option>Temporal Query</option>
            <option>Causal Reasoning</option>
            <option>Theorem Search</option>
            <option>Knowledge Graph</option>
            <option>News Search</option>
        </select>
    </div>
    
    <div class="form-group">
        <label>Query Input</label>
        <textarea class="form-control" id="query-input"></textarea>
    </div>
    
    <button class="btn btn-primary" onclick="executeQuery()">
        Execute Query
    </button>
    
    <div id="query-results"></div>
</div>
```

### Phase 7: API Endpoints

#### 7.1 New Finance Dashboard Routes
**Location**: Extend `ipfs_datasets_py/mcp_dashboard.py`

**Endpoints to Add**:
```python
# Market Data Endpoints
@app.route('/api/mcp/finance/market_data/<symbol>', methods=['GET'])
def get_market_data(symbol):
    """Get latest market data for symbol."""
    pass

@app.route('/api/mcp/finance/timeseries/<symbol>', methods=['GET'])
def get_timeseries(symbol):
    """Get historical time series data."""
    # Query params: start_date, end_date, interval
    pass

# News Endpoints
@app.route('/api/mcp/finance/news/search', methods=['POST'])
def search_news():
    """Search financial news articles."""
    # Body: query, date_range, sources, entities
    pass

@app.route('/api/mcp/finance/news/article/<article_id>', methods=['GET'])
def get_article(article_id):
    """Get specific news article with entities."""
    pass

# Knowledge Graph Endpoints
@app.route('/api/mcp/finance/graph/entity/<entity_id>', methods=['GET'])
def get_entity(entity_id):
    """Get entity details and relationships."""
    pass

@app.route('/api/mcp/finance/graph/query', methods=['POST'])
def query_graph():
    """Execute graph query."""
    # Body: cypher-like query language
    pass

# Reasoning Endpoints
@app.route('/api/mcp/finance/reason/chain', methods=['POST'])
def build_reasoning_chain():
    """Build causal reasoning chain for event."""
    pass

@app.route('/api/mcp/finance/theorems/apply', methods=['POST'])
def apply_theorem():
    """Apply financial theorem to data."""
    pass

# Scraper Management
@app.route('/api/mcp/finance/scrapers/status', methods=['GET'])
def scraper_status():
    """Get status of all scrapers."""
    pass

@app.route('/api/mcp/finance/scrapers/run', methods=['POST'])
def run_scraper():
    """Manually trigger scraper."""
    # Body: scraper_type, symbols, date_range
    pass
```

### Phase 8: Testing Strategy

#### 8.1 Unit Tests
**Location**: `tests/finance_dashboard/`

**Test Coverage**:
```python
# test_stock_scrapers.py
def test_yahoo_finance_scraper():
    """Test Yahoo Finance data scraping."""
    pass

def test_data_validation():
    """Test OHLCV validation logic."""
    pass

def test_split_adjustment():
    """Test stock split price adjustment."""
    pass

# test_news_scrapers.py
def test_reuters_scraper():
    """Test Reuters news scraping."""
    pass

def test_archive_fallback():
    """Test archive.org fallback mechanism."""
    pass

# test_knowledge_graph.py
def test_entity_extraction():
    """Test entity extraction from news."""
    pass

def test_temporal_graph_query():
    """Test temporal knowledge graph queries."""
    pass

# test_theorems.py
def test_stock_split_theorem():
    """Test stock split theorem application."""
    pass

def test_fuzzy_logic_evaluation():
    """Test fuzzy logic theorem evaluation."""
    pass

def test_causal_chain_building():
    """Test causal reasoning chain construction."""
    pass
```

#### 8.2 Integration Tests
```python
# test_end_to_end.py
def test_full_pipeline():
    """
    Test complete pipeline:
    1. Scrape stock data
    2. Scrape related news
    3. Extract entities
    4. Build knowledge graph
    5. Apply theorems
    6. Build reasoning chain
    7. Query via API
    """
    pass

def test_realtime_updates():
    """Test real-time data updates through dashboard."""
    pass
```

## Technology Stack

### Python Libraries
- **Data Scraping**: `requests`, `beautifulsoup4`, `selenium`, `scrapy`
- **Financial Data**: `yfinance`, `alpha_vantage`, `pandas-datareader`
- **Time Series**: `pandas`, `numpy`, `arrow`
- **NLP**: `spacy`, `transformers`, `sentence-transformers`
- **Knowledge Graph**: Existing GraphRAG integration
- **Logic**: `z3-solver` (SMT solver), `sympy`
- **API**: `flask`, `fastapi` (already in use)
- **Storage**: `ipfshttpclient`, existing IPLD integration

### Frontend Libraries
- **Charts**: `Chart.js`, `Plotly.js`, `TradingView Lightweight Charts`
- **Graphs**: `D3.js`, `Cytoscape.js`, `vis.js`
- **UI**: Bootstrap 5 (already in use), `jQuery`
- **Real-time**: `Socket.IO`

## Implementation Timeline

### Sprint 1 (Weeks 1-2): Foundation
- [ ] Set up finance_data_tools directory structure
- [ ] Implement basic stock scraper (Yahoo Finance)
- [ ] Create time series storage schema
- [ ] Add first API endpoints

### Sprint 2 (Weeks 3-4): Data Sources
- [ ] Implement remaining market data scrapers
- [ ] Add news scrapers (AP, Reuters)
- [ ] Implement archive.org integration
- [ ] Create data validation pipeline

### Sprint 3 (Weeks 5-6): Knowledge Graph
- [ ] Entity extraction from news
- [ ] Build temporal knowledge graph
- [ ] Graph query interface
- [ ] Integration with existing GraphRAG

### Sprint 4 (Weeks 7-8): Logic & Reasoning
- [ ] Define financial theorems
- [ ] Implement fuzzy logic engine
- [ ] Build causal reasoning chains
- [ ] Theorem validation tests

### Sprint 5 (Weeks 9-10): Dashboard UI
- [ ] Add real-time charts
- [ ] Knowledge graph visualization
- [ ] Reasoning chain display
- [ ] Interactive query interface

### Sprint 6 (Weeks 11-12): Testing & Documentation
- [ ] Comprehensive test suite
- [ ] Integration testing
- [ ] API documentation
- [ ] User guide and examples

## Success Metrics

### Technical Metrics
- **Data Coverage**: >95% uptime for scraper
- **Data Quality**: <1% error rate in validation
- **Query Performance**: <100ms for time series queries
- **Graph Size**: Support >100K entities, >1M relationships
- **Theorem Accuracy**: >90% confidence in causal chains

### User Metrics
- **Dashboard Load Time**: <2 seconds
- **Query Response Time**: <500ms
- **Visualization FPS**: >30 FPS for interactive graphs
- **API Throughput**: >1000 requests/minute

## Risk Mitigation

### Technical Risks
1. **API Rate Limits**: Use multiple data sources, implement caching
2. **Data Quality**: Robust validation, anomaly detection
3. **Storage Costs**: IPFS deduplication, data compression
4. **Performance**: Indexing strategy, query optimization

### Operational Risks
1. **Scraper Failures**: Archive.org fallbacks, retry logic
2. **Data Staleness**: Real-time update mechanisms
3. **Compliance**: Respect robots.txt, API ToS

## Future Enhancements

### Phase 2 Additions
- Machine learning price prediction models
- Sentiment analysis for news
- Portfolio optimization tools
- Risk assessment dashboard
- Regulatory compliance checking
- Real-time alert system

### Advanced Features
- Multi-modal analysis (text + numerical + social media)
- Distributed scraping across IPFS network
- Decentralized reasoning validators
- Cross-market correlation analysis
- Alternative data sources (satellite imagery, web traffic)

## Conclusion

This comprehensive plan transforms the finance dashboard into a powerful analytical tool combining real-time market data, news intelligence, knowledge graphs, and formal reasoning. The implementation leverages existing infrastructure (temporal deontic logic, GraphRAG, IPFS storage) while adding domain-specific capabilities for financial analysis.

The phased approach ensures incremental value delivery while maintaining system stability. Each phase builds upon the previous, creating a robust foundation for advanced financial intelligence and reasoning capabilities.

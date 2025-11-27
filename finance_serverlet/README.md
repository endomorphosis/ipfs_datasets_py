# Finance Data Serverlet

A self-contained lightweight Node.js server for financial data collection with multi-source integrity validation.

## Features

- **SQLite Local Storage**: Persistent data storage using better-sqlite3
- **HTTP REST API**: Full RESTful API for data access and management
- **Multiple Data Sources**: Integration with Yahoo Finance, Binance, TradingView, and Webull
- **Data Integrity Validation**: Cross-source comparison to verify data accuracy
- **Consensus Values**: Automatic calculation of consensus data from multiple sources

## Quick Start

### Installation

```bash
cd finance_serverlet
npm install
```

### Running the Server

```bash
npm start
```

The server will start on `http://localhost:3000` by default.

### Configuration

Configure via environment variables:

```bash
PORT=3000           # Server port
HOST=0.0.0.0        # Server host
DB_PATH=./data/finance.db  # SQLite database path
```

## API Endpoints

### Health Check

```
GET /api/health
```

Returns server health status.

### Symbols

```
GET /api/symbols           # List all tracked symbols
POST /api/symbols          # Add a new symbol
GET /api/symbols/:symbol   # Get specific symbol details
```

**Add Symbol Example:**
```bash
curl -X POST http://localhost:3000/api/symbols \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "name": "Apple Inc.", "assetType": "stock"}'
```

### Data Sources

```
GET /api/sources   # List all available data sources
```

### Market Data

```
GET /api/ohlcv/:symbol        # Get stored OHLCV data
POST /api/fetch/:symbol       # Fetch fresh data from sources
GET /api/price/:symbol        # Get current prices from all sources
```

**Fetch Data Example:**
```bash
curl -X POST http://localhost:3000/api/fetch/AAPL \
  -H "Content-Type: application/json" \
  -d '{
    "sources": ["yahoo_finance", "tradingview"],
    "startDate": "2024-01-01",
    "endDate": "2024-01-31",
    "timeframe": "1d"
  }'
```

**Get OHLCV Data:**
```bash
curl "http://localhost:3000/api/ohlcv/AAPL?timeframe=1d&limit=100"
```

**Get Current Prices:**
```bash
curl "http://localhost:3000/api/price/AAPL"
```

### Integrity Validation

```
POST /api/validate/:symbol           # Validate data across sources
GET /api/integrity/:symbol           # Get integrity check history
POST /api/validate-and-fetch/:symbol # Fetch, validate, and get consensus
```

**Validate and Fetch Example:**
```bash
curl -X POST http://localhost:3000/api/validate-and-fetch/BTC-USD \
  -H "Content-Type: application/json" \
  -d '{
    "sources": ["binance", "yahoo_finance"],
    "startDate": "2024-01-01",
    "endDate": "2024-01-15",
    "timeframe": "1d"
  }'
```

### Search

```
GET /api/search?q=query   # Search for symbols across sources
```

## Data Sources

### Yahoo Finance
- Stocks, ETFs, mutual funds, indices
- Historical OHLCV data
- Adjusted close prices

### Binance
- Cryptocurrency pairs
- High-frequency data (1m, 5m, 15m, 1h, 4h, 1d)
- Large historical data availability

### TradingView
- Stocks, forex, crypto
- Current snapshot data
- Symbol search

### Webull
- US stocks
- Real-time and historical data
- Extended hours data

## Data Integrity Validation

The serverlet compares data from multiple sources to ensure accuracy:

### Variance Thresholds
- **Price Variance**: Default 1% (configurable)
- **Volume Variance**: Default 10% (configurable)

### Validation Process
1. Fetch data from all requested sources
2. Compare OHLCV values at each timestamp
3. Calculate variance statistics (min, max, mean, median, std dev)
4. Identify discrepancies exceeding thresholds
5. Generate consensus values using median
6. Record validation results for audit trail

### Consensus Calculation
When sources disagree, the serverlet calculates consensus using:
- Median values for prices (robust to outliers)
- Statistical outlier detection using MAD (Median Absolute Deviation)

## Database Schema

### Tables

- **symbols**: Tracked financial instruments
- **data_sources**: Configured data source providers
- **ohlcv_data**: Historical OHLCV data points
- **integrity_checks**: Validation audit trail

### Example Queries

```sql
-- Get all data for a symbol
SELECT * FROM ohlcv_data 
JOIN symbols ON ohlcv_data.symbol_id = symbols.id 
WHERE symbols.symbol = 'AAPL';

-- Find integrity issues
SELECT * FROM integrity_checks 
WHERE is_valid = 0 
ORDER BY created_at DESC;
```

## Testing

```bash
npm test
```

Tests cover:
- Database operations
- Integrity validation logic
- Adapter functionality

## Project Structure

```
finance_serverlet/
├── src/
│   ├── index.js           # Main entry point
│   ├── api/
│   │   └── routes.js      # REST API routes
│   ├── db/
│   │   ├── index.js       # Database operations
│   │   └── schema.js      # SQLite schema
│   ├── adapters/
│   │   ├── base.js        # Base adapter class
│   │   ├── yahoo.js       # Yahoo Finance adapter
│   │   ├── binance.js     # Binance adapter
│   │   ├── tradingview.js # TradingView adapter
│   │   └── webull.js      # Webull adapter
│   └── utils/
│       └── integrity.js   # Data integrity validator
├── tests/
│   ├── db.test.js
│   ├── integrity.test.js
│   └── adapters.test.js
├── data/                  # SQLite database location
├── package.json
└── README.md
```

## Use Cases

### 1. Crypto Price Monitoring
```bash
# Track BTC with multi-source validation
curl -X POST http://localhost:3000/api/symbols \
  -d '{"symbol": "BTC-USD", "assetType": "crypto"}'

curl -X POST http://localhost:3000/api/validate-and-fetch/BTC-USD \
  -d '{"sources": ["binance", "yahoo_finance"]}'
```

### 2. Stock Data Collection
```bash
# Collect daily stock data
curl -X POST http://localhost:3000/api/fetch/TSLA \
  -d '{"timeframe": "1d", "startDate": "2024-01-01"}'
```

### 3. Data Quality Audit
```bash
# Check for data discrepancies
curl "http://localhost:3000/api/integrity/AAPL?onlyInvalid=true"
```

## Error Handling

All endpoints return consistent error responses:

```json
{
  "success": false,
  "error": "Error message description"
}
```

## Rate Limiting

Each data source adapter implements its own rate limiting:
- Yahoo Finance: 5 requests/minute
- Binance: 20 requests/minute
- TradingView: 5 requests/minute
- Webull: 10 requests/minute

## License

MIT

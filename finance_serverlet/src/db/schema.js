/**
 * Database Schema for Finance Data Serverlet
 * 
 * Tables:
 * - symbols: Track all symbols across data sources
 * - ohlcv_data: Store OHLCV (Open, High, Low, Close, Volume) data
 * - data_sources: Track data source configurations
 * - integrity_checks: Store cross-source comparison results
 */

export const SCHEMA = `
-- Symbols table: Track all symbols across data sources
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    name TEXT,
    asset_type TEXT NOT NULL DEFAULT 'stock', -- stock, crypto, forex, etc.
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Data sources configuration
CREATE TABLE IF NOT EXISTS data_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 0,
    config TEXT, -- JSON config
    last_sync DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- OHLCV data storage
CREATE TABLE IF NOT EXISTS ohlcv_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    timestamp DATETIME NOT NULL,
    timeframe TEXT NOT NULL DEFAULT '1d', -- 1m, 5m, 15m, 1h, 4h, 1d, 1w
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL DEFAULT 0,
    adjusted_close REAL,
    metadata TEXT, -- JSON for extra data
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (symbol_id) REFERENCES symbols(id),
    FOREIGN KEY (source_id) REFERENCES data_sources(id),
    UNIQUE(symbol_id, source_id, timestamp, timeframe)
);

-- Integrity check results
CREATE TABLE IF NOT EXISTS integrity_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    timestamp DATETIME NOT NULL,
    timeframe TEXT NOT NULL,
    sources_compared TEXT NOT NULL, -- JSON array of source IDs
    price_variance REAL, -- percentage variance across sources
    volume_variance REAL,
    is_valid INTEGER DEFAULT 1,
    discrepancies TEXT, -- JSON details of any discrepancies
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (symbol_id) REFERENCES symbols(id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_time ON ohlcv_data(symbol_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_ohlcv_source_time ON ohlcv_data(source_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_symbols_symbol ON symbols(symbol);
CREATE INDEX IF NOT EXISTS idx_integrity_symbol ON integrity_checks(symbol_id, timestamp);
`;

export const DEFAULT_DATA_SOURCES = [
    { name: 'yahoo_finance', enabled: 1, priority: 1 },
    { name: 'binance', enabled: 1, priority: 2 },
    { name: 'tradingview', enabled: 1, priority: 3 },
    { name: 'webull', enabled: 1, priority: 4 }
];

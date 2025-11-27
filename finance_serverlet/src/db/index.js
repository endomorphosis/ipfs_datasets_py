/**
 * Database Connection and Operations
 * 
 * Provides SQLite database management using better-sqlite3 for synchronous operations.
 */

import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';
import { SCHEMA, DEFAULT_DATA_SOURCES } from './schema.js';

let db = null;

/**
 * Initialize the database connection and create schema
 * @param {string} dbPath - Path to the SQLite database file
 * @returns {Database} The database instance
 */
export function initDatabase(dbPath = './data/finance.db') {
    // Ensure directory exists
    const dir = path.dirname(dbPath);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
    
    db = new Database(dbPath);
    db.pragma('journal_mode = WAL'); // Enable Write-Ahead Logging for better concurrency
    db.pragma('foreign_keys = ON');
    
    // Create schema
    db.exec(SCHEMA);
    
    // Initialize default data sources
    const insertSource = db.prepare(`
        INSERT OR IGNORE INTO data_sources (name, enabled, priority) 
        VALUES (?, ?, ?)
    `);
    
    for (const source of DEFAULT_DATA_SOURCES) {
        insertSource.run(source.name, source.enabled, source.priority);
    }
    
    console.log(`Database initialized at ${dbPath}`);
    return db;
}

/**
 * Get the database instance
 * @returns {Database}
 */
export function getDatabase() {
    if (!db) {
        throw new Error('Database not initialized. Call initDatabase() first.');
    }
    return db;
}

/**
 * Close the database connection
 */
export function closeDatabase() {
    if (db) {
        db.close();
        db = null;
    }
}

// ============================================
// Symbol Operations
// ============================================

/**
 * Create or get a symbol
 * @param {string} symbol - The ticker symbol
 * @param {string} name - Optional name
 * @param {string} assetType - Asset type (stock, crypto, forex)
 * @returns {object} The symbol record
 */
export function upsertSymbol(symbol, name = null, assetType = 'stock') {
    const db = getDatabase();
    const insert = db.prepare(`
        INSERT INTO symbols (symbol, name, asset_type, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(symbol) DO UPDATE SET 
            name = COALESCE(excluded.name, symbols.name),
            asset_type = excluded.asset_type,
            updated_at = CURRENT_TIMESTAMP
        RETURNING *
    `);
    return insert.get(symbol.toUpperCase(), name, assetType);
}

/**
 * Get a symbol by ticker
 * @param {string} symbol - The ticker symbol
 * @returns {object|undefined} The symbol record
 */
export function getSymbol(symbol) {
    const db = getDatabase();
    return db.prepare('SELECT * FROM symbols WHERE symbol = ?').get(symbol.toUpperCase());
}

/**
 * List all symbols
 * @returns {Array} List of symbols
 */
export function listSymbols() {
    const db = getDatabase();
    return db.prepare('SELECT * FROM symbols ORDER BY symbol').all();
}

// ============================================
// Data Source Operations
// ============================================

/**
 * Get a data source by name
 * @param {string} name - Source name
 * @returns {object|undefined}
 */
export function getDataSource(name) {
    const db = getDatabase();
    return db.prepare('SELECT * FROM data_sources WHERE name = ?').get(name);
}

/**
 * List all data sources
 * @returns {Array}
 */
export function listDataSources() {
    const db = getDatabase();
    return db.prepare('SELECT * FROM data_sources ORDER BY priority').all();
}

/**
 * Update data source sync time
 * @param {string} name - Source name
 */
export function updateSourceSyncTime(name) {
    const db = getDatabase();
    db.prepare('UPDATE data_sources SET last_sync = CURRENT_TIMESTAMP WHERE name = ?').run(name);
}

// ============================================
// OHLCV Data Operations
// ============================================

/**
 * Insert OHLCV data point
 * @param {object} data - OHLCV data
 * @returns {object} The inserted record
 */
export function insertOHLCV(data) {
    const db = getDatabase();
    const { symbolId, sourceId, timestamp, timeframe = '1d', open, high, low, close, volume = 0, adjustedClose = null, metadata = null } = data;
    
    const insert = db.prepare(`
        INSERT INTO ohlcv_data (symbol_id, source_id, timestamp, timeframe, open, high, low, close, volume, adjusted_close, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol_id, source_id, timestamp, timeframe) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            adjusted_close = excluded.adjusted_close,
            metadata = excluded.metadata
        RETURNING *
    `);
    
    return insert.get(symbolId, sourceId, timestamp, timeframe, open, high, low, close, volume, adjustedClose, 
        metadata ? JSON.stringify(metadata) : null);
}

/**
 * Bulk insert OHLCV data
 * @param {Array} dataPoints - Array of OHLCV data points
 * @returns {number} Number of records inserted
 */
export function bulkInsertOHLCV(dataPoints) {
    const db = getDatabase();
    const insert = db.prepare(`
        INSERT INTO ohlcv_data (symbol_id, source_id, timestamp, timeframe, open, high, low, close, volume, adjusted_close, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol_id, source_id, timestamp, timeframe) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            adjusted_close = excluded.adjusted_close,
            metadata = excluded.metadata
    `);
    
    const insertMany = db.transaction((points) => {
        for (const data of points) {
            const { symbolId, sourceId, timestamp, timeframe = '1d', open, high, low, close, volume = 0, adjustedClose = null, metadata = null } = data;
            insert.run(symbolId, sourceId, timestamp, timeframe, open, high, low, close, volume, adjustedClose,
                metadata ? JSON.stringify(metadata) : null);
        }
        return points.length;
    });
    
    return insertMany(dataPoints);
}

/**
 * Get OHLCV data for a symbol
 * @param {string} symbol - Ticker symbol
 * @param {object} options - Query options
 * @returns {Array} OHLCV data points
 */
export function getOHLCV(symbol, options = {}) {
    const db = getDatabase();
    const { startDate, endDate, timeframe = '1d', source = null, limit = 1000 } = options;
    
    let query = `
        SELECT o.*, s.symbol, ds.name as source_name
        FROM ohlcv_data o
        JOIN symbols s ON o.symbol_id = s.id
        JOIN data_sources ds ON o.source_id = ds.id
        WHERE s.symbol = ? AND o.timeframe = ?
    `;
    const params = [symbol.toUpperCase(), timeframe];
    
    if (startDate) {
        query += ' AND o.timestamp >= ?';
        params.push(startDate);
    }
    if (endDate) {
        query += ' AND o.timestamp <= ?';
        params.push(endDate);
    }
    if (source) {
        query += ' AND ds.name = ?';
        params.push(source);
    }
    
    query += ' ORDER BY o.timestamp DESC LIMIT ?';
    params.push(limit);
    
    return db.prepare(query).all(...params);
}

/**
 * Get OHLCV data from all sources for comparison
 * @param {string} symbol - Ticker symbol
 * @param {string} timestamp - Specific timestamp
 * @param {string} timeframe - Timeframe
 * @returns {Array} Data from all sources
 */
export function getOHLCVFromAllSources(symbol, timestamp, timeframe = '1d') {
    const db = getDatabase();
    const query = `
        SELECT o.*, s.symbol, ds.name as source_name
        FROM ohlcv_data o
        JOIN symbols s ON o.symbol_id = s.id
        JOIN data_sources ds ON o.source_id = ds.id
        WHERE s.symbol = ? AND o.timestamp = ? AND o.timeframe = ?
        ORDER BY ds.priority
    `;
    return db.prepare(query).all(symbol.toUpperCase(), timestamp, timeframe);
}

// ============================================
// Integrity Check Operations
// ============================================

/**
 * Record an integrity check result
 * @param {object} check - Check data
 * @returns {object} The inserted record
 */
export function recordIntegrityCheck(check) {
    const db = getDatabase();
    const { symbolId, timestamp, timeframe, sourcesCompared, priceVariance, volumeVariance, isValid, discrepancies } = check;
    
    const insert = db.prepare(`
        INSERT INTO integrity_checks (symbol_id, timestamp, timeframe, sources_compared, price_variance, volume_variance, is_valid, discrepancies)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *
    `);
    
    return insert.get(
        symbolId,
        timestamp,
        timeframe,
        JSON.stringify(sourcesCompared),
        priceVariance,
        volumeVariance,
        isValid ? 1 : 0,
        discrepancies ? JSON.stringify(discrepancies) : null
    );
}

/**
 * Get integrity check results for a symbol
 * @param {string} symbol - Ticker symbol
 * @param {object} options - Query options
 * @returns {Array}
 */
export function getIntegrityChecks(symbol, options = {}) {
    const db = getDatabase();
    const { startDate, endDate, onlyInvalid = false, limit = 100 } = options;
    
    let query = `
        SELECT ic.*, s.symbol
        FROM integrity_checks ic
        JOIN symbols s ON ic.symbol_id = s.id
        WHERE s.symbol = ?
    `;
    const params = [symbol.toUpperCase()];
    
    if (startDate) {
        query += ' AND ic.timestamp >= ?';
        params.push(startDate);
    }
    if (endDate) {
        query += ' AND ic.timestamp <= ?';
        params.push(endDate);
    }
    if (onlyInvalid) {
        query += ' AND ic.is_valid = 0';
    }
    
    query += ' ORDER BY ic.timestamp DESC LIMIT ?';
    params.push(limit);
    
    return db.prepare(query).all(...params);
}

export default {
    initDatabase,
    getDatabase,
    closeDatabase,
    upsertSymbol,
    getSymbol,
    listSymbols,
    getDataSource,
    listDataSources,
    updateSourceSyncTime,
    insertOHLCV,
    bulkInsertOHLCV,
    getOHLCV,
    getOHLCVFromAllSources,
    recordIntegrityCheck,
    getIntegrityChecks
};

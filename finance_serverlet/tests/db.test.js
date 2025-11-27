/**
 * Database Tests
 */

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Use a test database
const TEST_DB_PATH = path.join(__dirname, '..', 'data', 'test.db');

describe('Database Operations', async () => {
    let db;

    before(async () => {
        // Clean up test database if exists
        if (fs.existsSync(TEST_DB_PATH)) {
            fs.unlinkSync(TEST_DB_PATH);
        }
        
        // Import database module
        const dbModule = await import('../src/db/index.js');
        db = dbModule;
        db.initDatabase(TEST_DB_PATH);
    });

    after(() => {
        db.closeDatabase();
        // Clean up test database
        if (fs.existsSync(TEST_DB_PATH)) {
            fs.unlinkSync(TEST_DB_PATH);
        }
    });

    test('should initialize database with schema', () => {
        const sources = db.listDataSources();
        assert.ok(sources.length >= 4, 'Should have at least 4 default data sources');
        
        const sourceNames = sources.map(s => s.name);
        assert.ok(sourceNames.includes('yahoo_finance'), 'Should have yahoo_finance source');
        assert.ok(sourceNames.includes('binance'), 'Should have binance source');
        assert.ok(sourceNames.includes('tradingview'), 'Should have tradingview source');
        assert.ok(sourceNames.includes('webull'), 'Should have webull source');
    });

    test('should create and retrieve symbols', () => {
        const symbol = db.upsertSymbol('AAPL', 'Apple Inc.', 'stock');
        assert.ok(symbol.id, 'Symbol should have an ID');
        assert.strictEqual(symbol.symbol, 'AAPL');
        assert.strictEqual(symbol.name, 'Apple Inc.');
        assert.strictEqual(symbol.asset_type, 'stock');

        const retrieved = db.getSymbol('AAPL');
        assert.deepStrictEqual(retrieved.symbol, 'AAPL');
    });

    test('should handle case-insensitive symbol lookup', () => {
        db.upsertSymbol('MSFT', 'Microsoft', 'stock');
        
        const upper = db.getSymbol('MSFT');
        const lower = db.getSymbol('msft');
        const mixed = db.getSymbol('Msft');
        
        assert.ok(upper, 'Should find with uppercase');
        assert.ok(lower, 'Should find with lowercase');
        assert.ok(mixed, 'Should find with mixed case');
    });

    test('should insert and retrieve OHLCV data', () => {
        const symbol = db.upsertSymbol('BTC', 'Bitcoin', 'crypto');
        const source = db.getDataSource('binance');
        
        const ohlcvData = {
            symbolId: symbol.id,
            sourceId: source.id,
            timestamp: '2024-01-15T00:00:00.000Z',
            timeframe: '1d',
            open: 42000.5,
            high: 43500.0,
            low: 41800.0,
            close: 43200.0,
            volume: 25000000
        };
        
        const inserted = db.insertOHLCV(ohlcvData);
        assert.ok(inserted.id, 'Should return inserted record with ID');
        assert.strictEqual(inserted.open, 42000.5);
        
        const retrieved = db.getOHLCV('BTC', { source: 'binance', limit: 1 });
        assert.strictEqual(retrieved.length, 1);
        assert.strictEqual(retrieved[0].close, 43200.0);
    });

    test('should bulk insert OHLCV data', () => {
        const symbol = db.upsertSymbol('ETH', 'Ethereum', 'crypto');
        const source = db.getDataSource('binance');
        
        const dataPoints = [
            { symbolId: symbol.id, sourceId: source.id, timestamp: '2024-01-10T00:00:00.000Z', timeframe: '1d', open: 2200, high: 2300, low: 2150, close: 2280, volume: 1000000 },
            { symbolId: symbol.id, sourceId: source.id, timestamp: '2024-01-11T00:00:00.000Z', timeframe: '1d', open: 2280, high: 2400, low: 2270, close: 2380, volume: 1100000 },
            { symbolId: symbol.id, sourceId: source.id, timestamp: '2024-01-12T00:00:00.000Z', timeframe: '1d', open: 2380, high: 2420, low: 2350, close: 2400, volume: 900000 }
        ];
        
        const count = db.bulkInsertOHLCV(dataPoints);
        assert.strictEqual(count, 3);
        
        const retrieved = db.getOHLCV('ETH', { source: 'binance' });
        assert.ok(retrieved.length >= 3);
    });

    test('should get OHLCV from all sources', () => {
        const symbol = db.upsertSymbol('TEST', 'Test Symbol', 'stock');
        const yahooSource = db.getDataSource('yahoo_finance');
        const binanceSource = db.getDataSource('binance');
        
        const timestamp = '2024-01-20T00:00:00.000Z';
        
        // Insert data from two sources
        db.insertOHLCV({ symbolId: symbol.id, sourceId: yahooSource.id, timestamp, timeframe: '1d', open: 100, high: 105, low: 99, close: 103, volume: 5000 });
        db.insertOHLCV({ symbolId: symbol.id, sourceId: binanceSource.id, timestamp, timeframe: '1d', open: 100.1, high: 105.2, low: 98.9, close: 103.1, volume: 5100 });
        
        const allSources = db.getOHLCVFromAllSources('TEST', timestamp, '1d');
        assert.strictEqual(allSources.length, 2, 'Should have data from 2 sources');
        
        const sourceNames = allSources.map(d => d.source_name);
        assert.ok(sourceNames.includes('yahoo_finance'));
        assert.ok(sourceNames.includes('binance'));
    });

    test('should record and retrieve integrity checks', () => {
        const symbol = db.upsertSymbol('INTEG', 'Integrity Test', 'stock');
        
        const check = db.recordIntegrityCheck({
            symbolId: symbol.id,
            timestamp: '2024-01-25T00:00:00.000Z',
            timeframe: '1d',
            sourcesCompared: ['yahoo_finance', 'binance'],
            priceVariance: 0.5,
            volumeVariance: 2.3,
            isValid: true,
            discrepancies: null
        });
        
        assert.ok(check.id);
        assert.strictEqual(check.is_valid, 1);
        
        const checks = db.getIntegrityChecks('INTEG');
        assert.ok(checks.length >= 1);
    });
});

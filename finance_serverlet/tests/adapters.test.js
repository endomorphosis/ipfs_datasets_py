/**
 * Adapter Tests
 */

import { test, describe } from 'node:test';
import assert from 'node:assert';
import { BaseAdapter } from '../src/adapters/base.js';
import { YahooFinanceAdapter } from '../src/adapters/yahoo.js';
import { BinanceAdapter } from '../src/adapters/binance.js';
import { TradingViewAdapter } from '../src/adapters/tradingview.js';
import { WebullAdapter } from '../src/adapters/webull.js';

describe('BaseAdapter', () => {
    test('should initialize with correct defaults', () => {
        const adapter = new BaseAdapter('test');
        
        assert.strictEqual(adapter.name, 'test');
        assert.strictEqual(adapter.timeout, 30000);
        assert.strictEqual(adapter.retryAttempts, 3);
    });

    test('should track rate limiting', () => {
        const adapter = new BaseAdapter('test', {
            rateLimit: { requests: 2, perSeconds: 60 }
        });
        
        assert.strictEqual(adapter.canMakeRequest(), true);
        adapter.recordRequest();
        assert.strictEqual(adapter.canMakeRequest(), true);
        adapter.recordRequest();
        assert.strictEqual(adapter.canMakeRequest(), false);
    });

    test('should validate OHLCV data', () => {
        const adapter = new BaseAdapter('test');
        
        // Valid data
        const valid = adapter.validateOHLCV({
            timestamp: '2024-01-15T00:00:00Z',
            open: 100,
            high: 105,
            low: 98,
            close: 103,
            volume: 1000
        });
        assert.strictEqual(valid.isValid, true);
        
        // Invalid: high < low
        const invalid = adapter.validateOHLCV({
            timestamp: '2024-01-15T00:00:00Z',
            open: 100,
            high: 95, // Less than low
            low: 98,
            close: 103
        });
        assert.strictEqual(invalid.isValid, false);
        assert.ok(invalid.errors.length > 0);
    });
});

describe('YahooFinanceAdapter', () => {
    const adapter = new YahooFinanceAdapter();

    test('should have correct name and base URL', () => {
        assert.strictEqual(adapter.name, 'yahoo_finance');
        assert.ok(adapter.baseUrl.includes('yahoo'));
    });

    test('should map intervals correctly', () => {
        assert.strictEqual(adapter.mapInterval('1m'), '1m');
        assert.strictEqual(adapter.mapInterval('1h'), '60m');
        assert.strictEqual(adapter.mapInterval('1d'), '1d');
        assert.strictEqual(adapter.mapInterval('1w'), '1wk');
    });

    test('should normalize OHLCV data', () => {
        const mockResponse = {
            chart: {
                result: [{
                    timestamp: [1705276800, 1705363200],
                    indicators: {
                        quote: [{
                            open: [180.5, 181.0],
                            high: [183.0, 184.0],
                            low: [179.0, 180.0],
                            close: [182.0, 183.5],
                            volume: [50000, 55000]
                        }],
                        adjclose: [{
                            adjclose: [182.0, 183.5]
                        }]
                    }
                }]
            }
        };

        const normalized = adapter.normalizeOHLCV(mockResponse, 'AAPL', '1d');
        
        assert.strictEqual(normalized.length, 2);
        assert.strictEqual(normalized[0].symbol, 'AAPL');
        assert.strictEqual(normalized[0].source, 'yahoo_finance');
        assert.strictEqual(normalized[0].open, 180.5);
        assert.strictEqual(normalized[0].close, 182.0);
    });
});

describe('BinanceAdapter', () => {
    const adapter = new BinanceAdapter();

    test('should have correct name', () => {
        assert.strictEqual(adapter.name, 'binance');
    });

    test('should normalize symbols', () => {
        assert.strictEqual(adapter.normalizeSymbol('BTC-USD'), 'BTCUSDT');
        assert.strictEqual(adapter.normalizeSymbol('ETH/USDT'), 'ETHUSDT');
        assert.strictEqual(adapter.normalizeSymbol('BTCUSDT'), 'BTCUSDT');
    });

    test('should map intervals', () => {
        assert.strictEqual(adapter.mapInterval('1m'), '1m');
        assert.strictEqual(adapter.mapInterval('4h'), '4h');
        assert.strictEqual(adapter.mapInterval('1d'), '1d');
    });

    test('should normalize kline data', () => {
        const mockKlines = [
            [1705276800000, '42000', '43000', '41500', '42800', '1000', 1705363199999, '42500000', 5000, '500', '21250000', '0'],
            [1705363200000, '42800', '43500', '42500', '43200', '1200', 1705449599999, '51600000', 5500, '600', '25800000', '0']
        ];

        const normalized = adapter.normalizeOHLCV(mockKlines, 'BTC-USD', '1d');
        
        assert.strictEqual(normalized.length, 2);
        assert.strictEqual(normalized[0].open, 42000);
        assert.strictEqual(normalized[0].close, 42800);
        assert.strictEqual(normalized[0].volume, 1000);
    });
});

describe('TradingViewAdapter', () => {
    const adapter = new TradingViewAdapter();

    test('should have correct name', () => {
        assert.strictEqual(adapter.name, 'tradingview');
    });

    test('should normalize symbols', () => {
        const normalized = adapter.normalizeSymbol('AAPL', 'NASDAQ');
        assert.strictEqual(normalized, 'AAPL');
        
        // Crypto should get exchange prefix
        const crypto = adapter.normalizeSymbol('BTC-USD');
        assert.ok(crypto.includes('BINANCE') || crypto === 'BTCUSD');
    });
});

describe('WebullAdapter', () => {
    const adapter = new WebullAdapter();

    test('should have correct name', () => {
        assert.strictEqual(adapter.name, 'webull');
    });

    test('should map intervals', () => {
        assert.strictEqual(adapter.mapInterval('1m'), 'm1');
        assert.strictEqual(adapter.mapInterval('1h'), 'm60');
        assert.strictEqual(adapter.mapInterval('1d'), 'd1');
    });
});

describe('Adapter Integration', () => {
    test('all adapters should extend BaseAdapter', () => {
        const adapters = [
            new YahooFinanceAdapter(),
            new BinanceAdapter(),
            new TradingViewAdapter(),
            new WebullAdapter()
        ];

        for (const adapter of adapters) {
            assert.ok(adapter instanceof BaseAdapter, `${adapter.name} should extend BaseAdapter`);
            assert.ok(typeof adapter.fetchOHLCV === 'function');
            assert.ok(typeof adapter.getCurrentPrice === 'function');
            assert.ok(typeof adapter.validateOHLCV === 'function');
        }
    });
});

/**
 * Integrity Validator Tests
 */

import { test, describe } from 'node:test';
import assert from 'node:assert';
import { IntegrityValidator } from '../src/utils/integrity.js';

describe('IntegrityValidator', () => {
    const validator = new IntegrityValidator({
        priceVarianceThreshold: 1.0,
        volumeVarianceThreshold: 10.0
    });

    describe('compareDataPoints', () => {
        test('should validate consistent data points', () => {
            const dataPoints = [
                { source: 'yahoo', open: 100, high: 105, low: 99, close: 103, volume: 1000 },
                { source: 'binance', open: 100.1, high: 105.1, low: 99.1, close: 103.1, volume: 1020 },
                { source: 'tradingview', open: 99.9, high: 104.9, low: 98.9, close: 102.9, volume: 980 }
            ];

            const result = validator.compareDataPoints(dataPoints);
            
            assert.strictEqual(result.isValid, true, 'Should be valid for consistent data');
            assert.strictEqual(result.sourcesCompared.length, 3);
            assert.ok(result.priceVariance < 1.0, 'Price variance should be under threshold');
        });

        test('should detect price discrepancies', () => {
            const dataPoints = [
                { source: 'yahoo', open: 100, high: 105, low: 99, close: 103, volume: 1000 },
                { source: 'binance', open: 100, high: 105, low: 99, close: 110, volume: 1000 }, // Close is way off
                { source: 'tradingview', open: 100, high: 105, low: 99, close: 103, volume: 1000 }
            ];

            const result = validator.compareDataPoints(dataPoints);
            
            assert.strictEqual(result.isValid, false, 'Should be invalid due to price discrepancy');
            assert.ok(result.discrepancies.length > 0, 'Should have discrepancies');
            assert.ok(result.discrepancies.some(d => d.field === 'close'), 'Should flag close price');
        });

        test('should handle insufficient data sources', () => {
            const dataPoints = [
                { source: 'yahoo', open: 100, high: 105, low: 99, close: 103, volume: 1000 }
            ];

            const result = validator.compareDataPoints(dataPoints);
            
            assert.strictEqual(result.isValid, false);
            assert.ok(result.error, 'Should have error message');
        });

        test('should calculate consensus values', () => {
            const dataPoints = [
                { source: 'yahoo', open: 100, high: 105, low: 99, close: 103, volume: 1000 },
                { source: 'binance', open: 102, high: 107, low: 101, close: 105, volume: 1100 },
                { source: 'tradingview', open: 101, high: 106, low: 100, close: 104, volume: 1050 }
            ];

            const result = validator.compareDataPoints(dataPoints);
            
            assert.ok(result.consensusValues, 'Should have consensus values');
            assert.ok(result.consensusValues.close, 'Should have consensus close');
            // Median of 103, 105, 104 = 104
            assert.strictEqual(result.consensusValues.close, 104);
        });
    });

    describe('identifyOutliers', () => {
        test('should identify outlier values', () => {
            const dataPoints = [
                { source: 'yahoo', close: 100 },
                { source: 'binance', close: 101 },
                { source: 'tradingview', close: 99 },
                { source: 'webull', close: 150 } // Outlier
            ];

            const outliers = validator.identifyOutliers(dataPoints, 'close');
            
            assert.ok(outliers.length > 0, 'Should identify outliers');
            assert.strictEqual(outliers[0].source, 'webull');
        });

        test('should return empty for consistent data', () => {
            const dataPoints = [
                { source: 'yahoo', close: 100 },
                { source: 'binance', close: 100.5 },
                { source: 'tradingview', close: 99.5 }
            ];

            const outliers = validator.identifyOutliers(dataPoints, 'close');
            assert.strictEqual(outliers.length, 0);
        });
    });

    describe('mergeToConsensus', () => {
        test('should merge data points to consensus', () => {
            const dataPoints = [
                { source: 'yahoo', timestamp: '2024-01-15T00:00:00Z', symbol: 'AAPL', timeframe: '1d', open: 180, high: 185, low: 178, close: 183, volume: 50000 },
                { source: 'binance', timestamp: '2024-01-15T00:00:00Z', symbol: 'AAPL', timeframe: '1d', open: 180.5, high: 185.5, low: 178.5, close: 183.5, volume: 51000 }
            ];

            const consensus = validator.mergeToConsensus(dataPoints);
            
            assert.ok(consensus, 'Should return consensus');
            assert.strictEqual(consensus.symbol, 'AAPL');
            assert.ok(consensus.sources.length === 2);
            assert.ok(consensus.close > 0);
        });

        test('should handle empty input', () => {
            const consensus = validator.mergeToConsensus([]);
            assert.strictEqual(consensus, null);
        });
    });

    describe('validateSeries', () => {
        test('should validate consistent time series', () => {
            const series = [
                { timestamp: '2024-01-15T00:00:00Z', timeframe: '1d', open: 100, high: 105, low: 98, close: 103 },
                { timestamp: '2024-01-16T00:00:00Z', timeframe: '1d', open: 103, high: 108, low: 101, close: 106 },
                { timestamp: '2024-01-17T00:00:00Z', timeframe: '1d', open: 106, high: 110, low: 104, close: 108 }
            ];

            const result = validator.validateSeries(series);
            
            assert.strictEqual(result.isValid, true);
            assert.strictEqual(result.issueCount, 0);
        });

        test('should detect OHLC inconsistencies', () => {
            const series = [
                { timestamp: '2024-01-15T00:00:00Z', timeframe: '1d', open: 100, high: 95, low: 98, close: 103 } // High < Low
            ];

            const result = validator.validateSeries(series);
            
            assert.strictEqual(result.isValid, false);
            assert.ok(result.issues.some(i => i.issue === 'high_less_than_low'));
        });

        test('should detect open outside range', () => {
            const series = [
                { timestamp: '2024-01-15T00:00:00Z', timeframe: '1d', open: 120, high: 105, low: 98, close: 103 } // Open > High
            ];

            const result = validator.validateSeries(series);
            
            assert.strictEqual(result.isValid, false);
            assert.ok(result.issues.some(i => i.issue === 'open_outside_range'));
        });
    });

    describe('calculateVariance', () => {
        test('should calculate variance statistics', () => {
            const values = [100, 102, 98, 101, 99];
            const stats = validator.calculateVariance(values);
            
            assert.strictEqual(stats.min, 98);
            assert.strictEqual(stats.max, 102);
            assert.strictEqual(stats.mean, 100);
            assert.ok(stats.stdDev > 0);
            assert.ok(stats.percentVariance < 5); // Should be low for this data
        });

        test('should handle empty array', () => {
            const stats = validator.calculateVariance([]);
            
            assert.strictEqual(stats.min, 0);
            assert.strictEqual(stats.max, 0);
            assert.strictEqual(stats.mean, 0);
        });

        test('should handle single value', () => {
            const stats = validator.calculateVariance([100]);
            
            assert.strictEqual(stats.min, 100);
            assert.strictEqual(stats.max, 100);
            assert.strictEqual(stats.mean, 100);
            assert.strictEqual(stats.percentVariance, 0);
        });
    });
});

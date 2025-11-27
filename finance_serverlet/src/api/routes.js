/**
 * REST API Routes
 * 
 * Defines all HTTP REST endpoints for the finance data serverlet.
 */

import express from 'express';
import db from '../db/index.js';
import { YahooFinanceAdapter } from '../adapters/yahoo.js';
import { BinanceAdapter } from '../adapters/binance.js';
import { TradingViewAdapter } from '../adapters/tradingview.js';
import { WebullAdapter } from '../adapters/webull.js';
import { IntegrityValidator } from '../utils/integrity.js';

const router = express.Router();

// Initialize adapters
const adapters = {
    yahoo_finance: new YahooFinanceAdapter(),
    binance: new BinanceAdapter(),
    tradingview: new TradingViewAdapter(),
    webull: new WebullAdapter()
};

const validator = new IntegrityValidator();

// ============================================
// Health Check
// ============================================

router.get('/health', (req, res) => {
    res.json({
        status: 'healthy',
        timestamp: new Date().toISOString(),
        version: '1.0.0'
    });
});

// ============================================
// Symbol Endpoints
// ============================================

/**
 * GET /api/symbols
 * List all tracked symbols
 */
router.get('/symbols', (req, res) => {
    try {
        const symbols = db.listSymbols();
        res.json({ success: true, data: symbols });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

/**
 * POST /api/symbols
 * Add a new symbol to track
 * Body: { symbol: 'AAPL', name: 'Apple Inc.', assetType: 'stock' }
 */
router.post('/symbols', (req, res) => {
    try {
        const { symbol, name, assetType = 'stock' } = req.body;
        if (!symbol) {
            return res.status(400).json({ success: false, error: 'Symbol is required' });
        }
        const result = db.upsertSymbol(symbol, name, assetType);
        res.json({ success: true, data: result });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

/**
 * GET /api/symbols/:symbol
 * Get a specific symbol
 */
router.get('/symbols/:symbol', (req, res) => {
    try {
        const symbol = db.getSymbol(req.params.symbol);
        if (!symbol) {
            return res.status(404).json({ success: false, error: 'Symbol not found' });
        }
        res.json({ success: true, data: symbol });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// ============================================
// Data Source Endpoints
// ============================================

/**
 * GET /api/sources
 * List all data sources
 */
router.get('/sources', (req, res) => {
    try {
        const sources = db.listDataSources();
        res.json({ success: true, data: sources });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// ============================================
// Market Data Endpoints
// ============================================

/**
 * GET /api/ohlcv/:symbol
 * Get stored OHLCV data for a symbol
 * Query params: startDate, endDate, timeframe, source, limit
 */
router.get('/ohlcv/:symbol', (req, res) => {
    try {
        const { startDate, endDate, timeframe = '1d', source, limit } = req.query;
        const data = db.getOHLCV(req.params.symbol, {
            startDate,
            endDate,
            timeframe,
            source,
            limit: limit ? parseInt(limit) : undefined
        });
        res.json({ success: true, data, count: data.length });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

/**
 * POST /api/fetch/:symbol
 * Fetch fresh data from external sources and store it
 * Body: { sources: ['yahoo_finance', 'binance'], startDate, endDate, timeframe }
 */
router.post('/fetch/:symbol', async (req, res) => {
    try {
        const symbol = req.params.symbol.toUpperCase();
        const { 
            sources = Object.keys(adapters),
            startDate,
            endDate,
            timeframe = '1d'
        } = req.body;

        // Ensure symbol exists
        const symbolRecord = db.upsertSymbol(symbol);
        const results = {};
        const errors = [];

        // Fetch from each source
        for (const sourceName of sources) {
            const adapter = adapters[sourceName];
            if (!adapter) {
                errors.push({ source: sourceName, error: 'Unknown source' });
                continue;
            }

            try {
                const sourceRecord = db.getDataSource(sourceName);
                if (!sourceRecord) {
                    errors.push({ source: sourceName, error: 'Source not configured' });
                    continue;
                }

                const data = await adapter.fetchOHLCV(symbol, { startDate, endDate, interval: timeframe });
                
                if (data && data.length > 0) {
                    // Convert to database format and insert
                    const dbData = data.map(d => ({
                        symbolId: symbolRecord.id,
                        sourceId: sourceRecord.id,
                        timestamp: d.timestamp,
                        timeframe: d.timeframe || timeframe,
                        open: d.open,
                        high: d.high,
                        low: d.low,
                        close: d.close,
                        volume: d.volume,
                        adjustedClose: d.adjustedClose
                    }));

                    const inserted = db.bulkInsertOHLCV(dbData);
                    db.updateSourceSyncTime(sourceName);
                    
                    results[sourceName] = { 
                        success: true, 
                        count: inserted,
                        latestTimestamp: data[data.length - 1]?.timestamp
                    };
                } else {
                    results[sourceName] = { success: false, count: 0, error: 'No data returned' };
                }
            } catch (error) {
                errors.push({ source: sourceName, error: error.message });
                results[sourceName] = { success: false, error: error.message };
            }
        }

        res.json({ 
            success: errors.length === 0, 
            symbol,
            results,
            errors: errors.length > 0 ? errors : undefined
        });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

/**
 * GET /api/price/:symbol
 * Get current price from all sources
 */
router.get('/price/:symbol', async (req, res) => {
    try {
        const symbol = req.params.symbol.toUpperCase();
        const { sources = Object.keys(adapters) } = req.query;
        const sourceList = Array.isArray(sources) ? sources : sources.split(',');

        const prices = {};
        const errors = [];

        for (const sourceName of sourceList) {
            const adapter = adapters[sourceName.trim()];
            if (!adapter) continue;

            try {
                const price = await adapter.getCurrentPrice(symbol);
                if (price) {
                    prices[sourceName] = price;
                }
            } catch (error) {
                errors.push({ source: sourceName, error: error.message });
            }
        }

        // Compare prices if we have multiple sources
        let comparison = null;
        const priceDataPoints = Object.entries(prices).map(([source, data]) => ({
            source,
            open: data.open || data.price,
            high: data.high24h || data.high || data.price,
            low: data.low24h || data.low || data.price,
            close: data.price,
            volume: data.volume || 0
        }));

        if (priceDataPoints.length >= 2) {
            comparison = validator.compareDataPoints(priceDataPoints);
        }

        res.json({
            success: true,
            symbol,
            prices,
            comparison,
            errors: errors.length > 0 ? errors : undefined
        });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// ============================================
// Integrity Check Endpoints
// ============================================

/**
 * POST /api/validate/:symbol
 * Validate data integrity across sources for a symbol
 * Body: { timestamp, timeframe }
 */
router.post('/validate/:symbol', async (req, res) => {
    try {
        const symbol = req.params.symbol.toUpperCase();
        const { timestamp, timeframe = '1d' } = req.body;

        const symbolRecord = db.getSymbol(symbol);
        if (!symbolRecord) {
            return res.status(404).json({ success: false, error: 'Symbol not found' });
        }

        // Get data from all sources
        const allSourceData = db.getOHLCVFromAllSources(symbol, timestamp, timeframe);
        
        if (allSourceData.length < 2) {
            return res.json({
                success: false,
                error: 'Insufficient data sources for validation',
                dataPoints: allSourceData.length
            });
        }

        // Convert to validation format
        const dataPoints = allSourceData.map(d => ({
            source: d.source_name,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
            volume: d.volume
        }));

        const validation = validator.compareDataPoints(dataPoints);

        // Store the integrity check result
        db.recordIntegrityCheck({
            symbolId: symbolRecord.id,
            timestamp,
            timeframe,
            sourcesCompared: validation.sourcesCompared,
            priceVariance: validation.priceVariance,
            volumeVariance: validation.volumeVariance,
            isValid: validation.isValid,
            discrepancies: validation.discrepancies
        });

        res.json({
            success: true,
            symbol,
            timestamp,
            validation
        });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

/**
 * GET /api/integrity/:symbol
 * Get integrity check history for a symbol
 * Query: startDate, endDate, onlyInvalid, limit
 */
router.get('/integrity/:symbol', (req, res) => {
    try {
        const { startDate, endDate, onlyInvalid, limit } = req.query;
        const checks = db.getIntegrityChecks(req.params.symbol, {
            startDate,
            endDate,
            onlyInvalid: onlyInvalid === 'true',
            limit: limit ? parseInt(limit) : undefined
        });

        // Parse JSON fields
        const parsed = checks.map(c => ({
            ...c,
            sources_compared: JSON.parse(c.sources_compared || '[]'),
            discrepancies: c.discrepancies ? JSON.parse(c.discrepancies) : null
        }));

        res.json({ success: true, data: parsed, count: parsed.length });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

/**
 * POST /api/validate-and-fetch/:symbol
 * Fetch from all sources, validate, and return consensus
 */
router.post('/validate-and-fetch/:symbol', async (req, res) => {
    try {
        const symbol = req.params.symbol.toUpperCase();
        const { 
            sources = Object.keys(adapters),
            startDate,
            endDate,
            timeframe = '1d'
        } = req.body;

        // Ensure symbol exists
        const symbolRecord = db.upsertSymbol(symbol);
        
        // Fetch from all sources
        const allData = {};
        const errors = [];

        for (const sourceName of sources) {
            const adapter = adapters[sourceName];
            if (!adapter) continue;

            try {
                const sourceRecord = db.getDataSource(sourceName);
                const data = await adapter.fetchOHLCV(symbol, { startDate, endDate, interval: timeframe });
                
                if (data && data.length > 0) {
                    allData[sourceName] = data;
                    
                    // Store in database
                    const dbData = data.map(d => ({
                        symbolId: symbolRecord.id,
                        sourceId: sourceRecord.id,
                        timestamp: d.timestamp,
                        timeframe: d.timeframe || timeframe,
                        open: d.open,
                        high: d.high,
                        low: d.low,
                        close: d.close,
                        volume: d.volume,
                        adjustedClose: d.adjustedClose
                    }));
                    db.bulkInsertOHLCV(dbData);
                    db.updateSourceSyncTime(sourceName);
                }
            } catch (error) {
                errors.push({ source: sourceName, error: error.message });
            }
        }

        // Group data by timestamp and validate each
        const byTimestamp = {};
        for (const [source, data] of Object.entries(allData)) {
            for (const point of data) {
                const ts = point.timestamp;
                if (!byTimestamp[ts]) {
                    byTimestamp[ts] = [];
                }
                byTimestamp[ts].push({ ...point, source });
            }
        }

        // Validate and create consensus for each timestamp
        const consensusData = [];
        const validationResults = [];

        for (const [timestamp, points] of Object.entries(byTimestamp)) {
            if (points.length >= 2) {
                const validation = validator.compareDataPoints(points);
                const consensus = validator.mergeToConsensus(points);
                
                validationResults.push({
                    timestamp,
                    ...validation
                });

                if (consensus) {
                    consensusData.push(consensus);
                }

                // Record integrity check
                db.recordIntegrityCheck({
                    symbolId: symbolRecord.id,
                    timestamp,
                    timeframe,
                    sourcesCompared: validation.sourcesCompared,
                    priceVariance: validation.priceVariance,
                    volumeVariance: validation.volumeVariance,
                    isValid: validation.isValid,
                    discrepancies: validation.discrepancies
                });
            } else if (points.length === 1) {
                // Single source - use as-is but mark as unvalidated
                consensusData.push({
                    ...points[0],
                    sources: [points[0].source],
                    isValidated: false
                });
            }
        }

        // Summary statistics
        const validCount = validationResults.filter(v => v.isValid).length;
        const invalidCount = validationResults.filter(v => !v.isValid).length;

        res.json({
            success: true,
            symbol,
            summary: {
                totalTimestamps: Object.keys(byTimestamp).length,
                validatedCount: validationResults.length,
                validCount,
                invalidCount,
                consensusDataPoints: consensusData.length
            },
            consensusData: consensusData.slice(0, 100), // Limit response size
            validationIssues: validationResults.filter(v => !v.isValid),
            errors: errors.length > 0 ? errors : undefined
        });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

/**
 * GET /api/search
 * Search for symbols across sources
 * Query: q (search query)
 */
router.get('/search', async (req, res) => {
    try {
        const { q } = req.query;
        if (!q) {
            return res.status(400).json({ success: false, error: 'Query parameter "q" is required' });
        }

        const results = {};
        
        // Search on TradingView (has good symbol search)
        try {
            results.tradingview = await adapters.tradingview.searchSymbols(q);
        } catch (error) {
            results.tradingview = [];
        }

        // Search on Webull
        try {
            results.webull = await adapters.webull.searchSymbols(q);
        } catch (error) {
            results.webull = [];
        }

        res.json({ success: true, query: q, results });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

export default router;

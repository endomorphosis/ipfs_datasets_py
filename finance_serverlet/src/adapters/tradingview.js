/**
 * TradingView Adapter
 * 
 * Fetches market data using TradingView's public API endpoints.
 * Note: TradingView doesn't have an official public API, this uses
 * their public-facing endpoints which may change.
 */

import { BaseAdapter } from './base.js';

export class TradingViewAdapter extends BaseAdapter {
    constructor(options = {}) {
        super('tradingview', {
            baseUrl: 'https://scanner.tradingview.com',
            symbolSearchUrl: 'https://symbol-search.tradingview.com',
            rateLimit: { requests: 5, perSeconds: 60 },
            ...options
        });
        
        this.exchanges = ['NYSE', 'NASDAQ', 'AMEX', 'BINANCE', 'COINBASE', 'FX'];
    }

    /**
     * Convert symbol to TradingView format
     * @param {string} symbol - Standard symbol
     * @param {string} exchange - Exchange name
     * @returns {string} TradingView symbol
     */
    normalizeSymbol(symbol, exchange = 'NASDAQ') {
        // Remove common suffixes and prefixes
        let normalized = symbol.toUpperCase().replace(/[-\/]/g, '');
        
        // For crypto, add exchange prefix if not present
        if (symbol.includes('BTC') || symbol.includes('ETH')) {
            if (!normalized.includes(':')) {
                normalized = `BINANCE:${normalized}`;
            }
        }
        
        return normalized;
    }

    /**
     * Fetch OHLCV data from TradingView
     * Note: TradingView's free API has limited historical data
     * @param {string} symbol - Symbol
     * @param {object} options - Options
     * @returns {Promise<Array>} OHLCV data
     */
    async fetchOHLCV(symbol, options = {}) {
        const { 
            startDate,
            endDate,
            interval = '1d',
            exchange = 'NASDAQ'
        } = options;

        // TradingView's scanner API for basic data
        const body = {
            symbols: {
                tickers: [this.normalizeSymbol(symbol, exchange)],
                query: { types: [] }
            },
            columns: [
                'name',
                'close',
                'open',
                'high',
                'low',
                'volume',
                'change',
                'change_abs',
                'Recommend.All'
            ]
        };

        try {
            const response = await fetch(`${this.baseUrl}/america/scan`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(body)
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            return this.normalizeOHLCV(data, symbol, interval);
        } catch (error) {
            console.error(`TradingView error for ${symbol}:`, error.message);
            return [];
        }
    }

    /**
     * Get current price from TradingView
     * @param {string} symbol - Symbol
     * @param {string} exchange - Exchange
     * @returns {Promise<object>}
     */
    async getCurrentPrice(symbol, exchange = 'NASDAQ') {
        const body = {
            symbols: {
                tickers: [this.normalizeSymbol(symbol, exchange)],
                query: { types: [] }
            },
            columns: [
                'name',
                'description',
                'close',
                'open',
                'high',
                'low',
                'volume',
                'change',
                'change_abs',
                'Recommend.All',
                'market_cap_basic',
                'price_earnings_ttm'
            ]
        };

        try {
            const response = await fetch(`${this.baseUrl}/america/scan`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(body)
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            
            if (!data.data || data.data.length === 0) {
                return null;
            }

            const item = data.data[0];
            const d = item.d;
            
            return {
                symbol,
                name: d[0],
                description: d[1],
                price: d[2],
                open: d[3],
                high: d[4],
                low: d[5],
                volume: d[6],
                changePercent: d[7],
                change: d[8],
                recommendation: d[9],
                marketCap: d[10],
                peRatio: d[11],
                timestamp: new Date().toISOString(),
                source: this.name
            };
        } catch (error) {
            console.error(`TradingView price error for ${symbol}:`, error.message);
            return null;
        }
    }

    /**
     * Search for symbols on TradingView
     * @param {string} query - Search query
     * @returns {Promise<Array>}
     */
    async searchSymbols(query) {
        const url = `${this.symbolSearchUrl}/symbol_search/?text=${encodeURIComponent(query)}&hl=1&exchange=&lang=en&type=&domain=production`;
        
        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            return data.map(item => ({
                symbol: item.symbol,
                description: item.description,
                exchange: item.exchange,
                type: item.type,
                country: item.country
            }));
        } catch (error) {
            console.error('TradingView search error:', error.message);
            return [];
        }
    }

    /**
     * Normalize TradingView scanner response
     * @param {object} rawData - Raw response
     * @param {string} symbol - Symbol
     * @param {string} interval - Interval
     * @returns {Array} Normalized data
     */
    normalizeOHLCV(rawData, symbol, interval) {
        if (!rawData.data || !Array.isArray(rawData.data)) {
            return [];
        }

        // Scanner API returns current snapshot, not historical
        return rawData.data.map(item => {
            const d = item.d;
            return {
                timestamp: new Date().toISOString(),
                symbol,
                open: d[2],  // Using close as approximation since scanner gives snapshot
                high: d[3],
                low: d[4],
                close: d[1],
                volume: d[5] || 0,
                timeframe: interval,
                source: this.name
            };
        }).filter(dp => this.validateOHLCV(dp).isValid);
    }
}

export default TradingViewAdapter;

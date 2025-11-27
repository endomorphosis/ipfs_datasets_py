/**
 * Webull Adapter
 * 
 * Fetches market data from Webull's public API endpoints.
 * Note: Webull doesn't have an official public API, this uses
 * their mobile app endpoints.
 */

import { BaseAdapter } from './base.js';

export class WebullAdapter extends BaseAdapter {
    constructor(options = {}) {
        super('webull', {
            baseUrl: 'https://quotes-gw.webullbroker.com',
            infoUrl: 'https://infoapi.webull.com',
            rateLimit: { requests: 10, perSeconds: 60 },
            ...options
        });
    }

    /**
     * Search for a ticker ID by symbol
     * @param {string} symbol - Stock symbol
     * @returns {Promise<string|null>} Ticker ID
     */
    async getTickerId(symbol) {
        const url = `https://quotes-gw.webullfintech.com/api/search/pc/tickers?keyword=${encodeURIComponent(symbol)}&pageIndex=1&pageSize=10`;
        
        try {
            const data = await this.fetchWithRetry(url);
            if (data.data && data.data.length > 0) {
                // Find exact match
                const exact = data.data.find(t => t.symbol.toUpperCase() === symbol.toUpperCase());
                return exact ? exact.tickerId : data.data[0].tickerId;
            }
            return null;
        } catch (error) {
            console.error(`Webull ticker search error for ${symbol}:`, error.message);
            return null;
        }
    }

    /**
     * Map interval to Webull format
     * @param {string} interval - Standard interval
     * @returns {string} Webull interval type
     */
    mapInterval(interval) {
        const mapping = {
            '1m': 'm1',
            '5m': 'm5',
            '15m': 'm15',
            '30m': 'm30',
            '1h': 'm60',
            '1d': 'd1',
            '1w': 'w1',
            '1M': 'mon1'
        };
        return mapping[interval] || 'd1';
    }

    /**
     * Fetch OHLCV data from Webull
     * @param {string} symbol - Stock symbol
     * @param {object} options - Options
     * @returns {Promise<Array>} OHLCV data
     */
    async fetchOHLCV(symbol, options = {}) {
        const { 
            interval = '1d',
            count = 200
        } = options;

        // First, get the ticker ID
        const tickerId = await this.getTickerId(symbol);
        if (!tickerId) {
            console.error(`Could not find ticker ID for ${symbol}`);
            return [];
        }

        const webullInterval = this.mapInterval(interval);
        const url = `https://quotes-gw.webullfintech.com/api/quote/charts/query?tickerIds=${tickerId}&type=${webullInterval}&count=${count}`;

        try {
            const data = await this.fetchWithRetry(url);
            return this.normalizeOHLCV(data, symbol, interval);
        } catch (error) {
            console.error(`Webull OHLCV error for ${symbol}:`, error.message);
            return [];
        }
    }

    /**
     * Get current price from Webull
     * @param {string} symbol - Symbol
     * @returns {Promise<object>}
     */
    async getCurrentPrice(symbol) {
        const tickerId = await this.getTickerId(symbol);
        if (!tickerId) {
            return null;
        }

        const url = `https://quotes-gw.webullfintech.com/api/bgw/quote/realtime?tickerIds=${tickerId}&includeSecu=1&includeQuote=1`;
        
        try {
            const data = await this.fetchWithRetry(url);
            
            if (!data || !data.length) {
                return null;
            }

            const quote = data[0];
            return {
                symbol,
                name: quote.name || symbol,
                price: parseFloat(quote.close || quote.price),
                previousClose: parseFloat(quote.preClose),
                change: parseFloat(quote.change),
                changePercent: parseFloat(quote.changeRatio) * 100,
                volume: parseFloat(quote.volume),
                open: parseFloat(quote.open),
                high: parseFloat(quote.high),
                low: parseFloat(quote.low),
                marketCap: quote.marketValue,
                timestamp: new Date().toISOString(),
                source: this.name
            };
        } catch (error) {
            console.error(`Webull price error for ${symbol}:`, error.message);
            return null;
        }
    }

    /**
     * Normalize Webull OHLCV response
     * @param {object} rawData - Raw response
     * @param {string} symbol - Symbol
     * @param {string} interval - Interval
     * @returns {Array} Normalized data
     */
    normalizeOHLCV(rawData, symbol, interval) {
        if (!rawData || !Array.isArray(rawData)) {
            // Try to extract from nested structure
            if (rawData && rawData.data) {
                rawData = rawData.data;
            } else {
                return [];
            }
        }

        // Webull returns data for each ticker
        const tickerData = rawData[0];
        if (!tickerData || !tickerData.data) {
            return [];
        }

        return tickerData.data.map(item => {
            const dataPoint = {
                timestamp: new Date(item.timestamp || item.t).toISOString(),
                open: parseFloat(item.open || item.o),
                high: parseFloat(item.high || item.h),
                low: parseFloat(item.low || item.l),
                close: parseFloat(item.close || item.c),
                volume: parseFloat(item.volume || item.v) || 0,
                timeframe: interval,
                source: this.name,
                symbol
            };
            return dataPoint;
        }).filter(dp => this.validateOHLCV(dp).isValid);
    }

    /**
     * Search for stocks on Webull
     * @param {string} query - Search query
     * @returns {Promise<Array>}
     */
    async searchSymbols(query) {
        const url = `https://quotes-gw.webullfintech.com/api/search/pc/tickers?keyword=${encodeURIComponent(query)}&pageIndex=1&pageSize=20`;
        
        try {
            const data = await this.fetchWithRetry(url);
            if (!data.data) return [];
            
            return data.data.map(item => ({
                tickerId: item.tickerId,
                symbol: item.symbol,
                name: item.name,
                exchange: item.exchangeCode,
                type: item.type,
                region: item.regionCode
            }));
        } catch (error) {
            console.error('Webull search error:', error.message);
            return [];
        }
    }
}

export default WebullAdapter;

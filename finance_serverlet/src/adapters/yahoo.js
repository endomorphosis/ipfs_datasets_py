/**
 * Yahoo Finance Adapter
 * 
 * Fetches market data from Yahoo Finance API.
 * Free tier with reasonable rate limits.
 */

import { BaseAdapter } from './base.js';

export class YahooFinanceAdapter extends BaseAdapter {
    constructor(options = {}) {
        super('yahoo_finance', {
            baseUrl: 'https://query1.finance.yahoo.com',
            rateLimit: { requests: 5, perSeconds: 60 },
            ...options
        });
    }

    /**
     * Map interval to Yahoo Finance format
     * @param {string} interval - Standard interval
     * @returns {string} Yahoo interval
     */
    mapInterval(interval) {
        const mapping = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '30m': '30m',
            '1h': '60m',
            '4h': '60m', // Yahoo doesn't have 4h, use 1h
            '1d': '1d',
            '1w': '1wk',
            '1M': '1mo'
        };
        return mapping[interval] || '1d';
    }

    /**
     * Fetch OHLCV data from Yahoo Finance
     * @param {string} symbol - Stock/crypto symbol (e.g., 'AAPL', 'BTC-USD')
     * @param {object} options - Options
     * @returns {Promise<Array>} Normalized OHLCV data
     */
    async fetchOHLCV(symbol, options = {}) {
        const { 
            startDate = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000), // 30 days ago
            endDate = new Date(),
            interval = '1d'
        } = options;

        const period1 = Math.floor(new Date(startDate).getTime() / 1000);
        const period2 = Math.floor(new Date(endDate).getTime() / 1000);
        const yahooInterval = this.mapInterval(interval);

        const url = `${this.baseUrl}/v8/finance/chart/${encodeURIComponent(symbol)}?period1=${period1}&period2=${period2}&interval=${yahooInterval}`;

        try {
            const data = await this.fetchWithRetry(url);
            return this.normalizeOHLCV(data, symbol, interval);
        } catch (error) {
            console.error(`Yahoo Finance error for ${symbol}:`, error.message);
            return [];
        }
    }

    /**
     * Get current price from Yahoo Finance
     * @param {string} symbol - Symbol
     * @returns {Promise<object>}
     */
    async getCurrentPrice(symbol) {
        const url = `${this.baseUrl}/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1m&range=1d`;
        
        try {
            const data = await this.fetchWithRetry(url);
            const result = data.chart?.result?.[0];
            if (!result) return null;

            const quote = result.meta;
            return {
                symbol,
                price: quote.regularMarketPrice,
                previousClose: quote.chartPreviousClose,
                change: quote.regularMarketPrice - quote.chartPreviousClose,
                changePercent: ((quote.regularMarketPrice - quote.chartPreviousClose) / quote.chartPreviousClose) * 100,
                timestamp: new Date(quote.regularMarketTime * 1000).toISOString(),
                source: this.name
            };
        } catch (error) {
            console.error(`Yahoo Finance price error for ${symbol}:`, error.message);
            return null;
        }
    }

    /**
     * Normalize Yahoo Finance OHLCV response
     * @param {object} rawData - Raw Yahoo Finance response
     * @param {string} symbol - Symbol
     * @param {string} interval - Interval
     * @returns {Array} Normalized OHLCV data
     */
    normalizeOHLCV(rawData, symbol, interval) {
        const result = rawData.chart?.result?.[0];
        if (!result) return [];

        const timestamps = result.timestamp || [];
        const quote = result.indicators?.quote?.[0] || {};
        const adjClose = result.indicators?.adjclose?.[0]?.adjclose;

        const normalized = [];
        for (let i = 0; i < timestamps.length; i++) {
            if (quote.open?.[i] == null) continue; // Skip null entries
            
            const dataPoint = {
                timestamp: new Date(timestamps[i] * 1000).toISOString(),
                open: quote.open[i],
                high: quote.high[i],
                low: quote.low[i],
                close: quote.close[i],
                volume: quote.volume?.[i] || 0,
                adjustedClose: adjClose?.[i] || quote.close[i],
                timeframe: interval,
                source: this.name,
                symbol
            };

            const validation = this.validateOHLCV(dataPoint);
            if (validation.isValid) {
                normalized.push(dataPoint);
            }
        }

        return normalized;
    }
}

export default YahooFinanceAdapter;

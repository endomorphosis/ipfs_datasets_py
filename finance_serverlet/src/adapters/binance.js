/**
 * Binance Adapter
 * 
 * Fetches cryptocurrency market data from Binance API.
 * Supports spot and futures markets.
 */

import { BaseAdapter } from './base.js';

export class BinanceAdapter extends BaseAdapter {
    constructor(options = {}) {
        super('binance', {
            baseUrl: 'https://api.binance.com',
            rateLimit: { requests: 20, perSeconds: 60 },
            ...options
        });
    }

    /**
     * Map standard interval to Binance format
     * @param {string} interval - Standard interval
     * @returns {string} Binance interval
     */
    mapInterval(interval) {
        const mapping = {
            '1m': '1m',
            '3m': '3m',
            '5m': '5m',
            '15m': '15m',
            '30m': '30m',
            '1h': '1h',
            '2h': '2h',
            '4h': '4h',
            '6h': '6h',
            '8h': '8h',
            '12h': '12h',
            '1d': '1d',
            '3d': '3d',
            '1w': '1w',
            '1M': '1M'
        };
        return mapping[interval] || '1d';
    }

    /**
     * Convert symbol to Binance format
     * @param {string} symbol - Standard symbol (e.g., 'BTC-USD', 'ETH/USDT')
     * @returns {string} Binance symbol (e.g., 'BTCUSDT')
     */
    normalizeSymbol(symbol) {
        // Remove separators and ensure USDT suffix for crypto
        let normalized = symbol.replace(/[-\/]/g, '').toUpperCase();
        
        // If it ends with USD but not USDT, convert to USDT
        if (normalized.endsWith('USD') && !normalized.endsWith('USDT')) {
            normalized = normalized.slice(0, -3) + 'USDT';
        }
        
        return normalized;
    }

    /**
     * Fetch OHLCV data from Binance
     * @param {string} symbol - Crypto pair (e.g., 'BTC-USD', 'BTCUSDT')
     * @param {object} options - Options
     * @returns {Promise<Array>} Normalized OHLCV data
     */
    async fetchOHLCV(symbol, options = {}) {
        const { 
            startDate,
            endDate,
            interval = '1d',
            limit = 1000
        } = options;

        const binanceSymbol = this.normalizeSymbol(symbol);
        const binanceInterval = this.mapInterval(interval);

        let url = `${this.baseUrl}/api/v3/klines?symbol=${binanceSymbol}&interval=${binanceInterval}&limit=${limit}`;
        
        if (startDate) {
            url += `&startTime=${new Date(startDate).getTime()}`;
        }
        if (endDate) {
            url += `&endTime=${new Date(endDate).getTime()}`;
        }

        try {
            const data = await this.fetchWithRetry(url);
            return this.normalizeOHLCV(data, symbol, interval);
        } catch (error) {
            console.error(`Binance error for ${symbol}:`, error.message);
            return [];
        }
    }

    /**
     * Get current price from Binance
     * @param {string} symbol - Symbol
     * @returns {Promise<object>}
     */
    async getCurrentPrice(symbol) {
        const binanceSymbol = this.normalizeSymbol(symbol);
        const tickerUrl = `${this.baseUrl}/api/v3/ticker/24hr?symbol=${binanceSymbol}`;
        
        try {
            const data = await this.fetchWithRetry(tickerUrl);
            return {
                symbol,
                price: parseFloat(data.lastPrice),
                previousClose: parseFloat(data.prevClosePrice),
                change: parseFloat(data.priceChange),
                changePercent: parseFloat(data.priceChangePercent),
                volume: parseFloat(data.volume),
                quoteVolume: parseFloat(data.quoteVolume),
                high24h: parseFloat(data.highPrice),
                low24h: parseFloat(data.lowPrice),
                timestamp: new Date(data.closeTime).toISOString(),
                source: this.name
            };
        } catch (error) {
            console.error(`Binance price error for ${symbol}:`, error.message);
            return null;
        }
    }

    /**
     * Normalize Binance OHLCV response
     * Binance returns: [[openTime, open, high, low, close, volume, closeTime, ...], ...]
     * @param {Array} rawData - Raw Binance klines response
     * @param {string} symbol - Symbol
     * @param {string} interval - Interval
     * @returns {Array} Normalized OHLCV data
     */
    normalizeOHLCV(rawData, symbol, interval) {
        if (!Array.isArray(rawData)) return [];

        return rawData.map(kline => {
            const dataPoint = {
                timestamp: new Date(kline[0]).toISOString(),
                open: parseFloat(kline[1]),
                high: parseFloat(kline[2]),
                low: parseFloat(kline[3]),
                close: parseFloat(kline[4]),
                volume: parseFloat(kline[5]),
                closeTime: new Date(kline[6]).toISOString(),
                quoteVolume: parseFloat(kline[7]),
                trades: kline[8],
                timeframe: interval,
                source: this.name,
                symbol
            };
            return dataPoint;
        }).filter(dp => this.validateOHLCV(dp).isValid);
    }

    /**
     * Get supported symbols from Binance
     * @returns {Promise<Array>}
     */
    async getSupportedSymbols() {
        const url = `${this.baseUrl}/api/v3/exchangeInfo`;
        
        try {
            const data = await this.fetchWithRetry(url);
            return data.symbols
                .filter(s => s.status === 'TRADING')
                .map(s => ({
                    symbol: s.symbol,
                    baseAsset: s.baseAsset,
                    quoteAsset: s.quoteAsset,
                    status: s.status
                }));
        } catch (error) {
            console.error('Binance exchange info error:', error.message);
            return [];
        }
    }
}

export default BinanceAdapter;

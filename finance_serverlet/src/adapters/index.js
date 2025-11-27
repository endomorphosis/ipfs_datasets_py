/**
 * Data Source Adapters Index
 * 
 * Exports all available data source adapters.
 */

import { BaseAdapter } from './base.js';
import { YahooFinanceAdapter } from './yahoo.js';
import { BinanceAdapter } from './binance.js';
import { TradingViewAdapter } from './tradingview.js';
import { WebullAdapter } from './webull.js';

export { BaseAdapter, YahooFinanceAdapter, BinanceAdapter, TradingViewAdapter, WebullAdapter };

/**
 * Factory to create adapter by name
 * @param {string} name - Adapter name
 * @param {object} options - Adapter options
 * @returns {BaseAdapter}
 */
export function createAdapter(name, options = {}) {
    switch (name.toLowerCase()) {
        case 'yahoo':
        case 'yahoo_finance':
        case 'yahoofinance':
            return new YahooFinanceAdapter(options);
        case 'binance':
            return new BinanceAdapter(options);
        case 'tradingview':
        case 'trading_view':
            return new TradingViewAdapter(options);
        case 'webull':
            return new WebullAdapter(options);
        default:
            throw new Error(`Unknown adapter: ${name}`);
    }
}

/**
 * Get all available adapter instances
 * @param {object} options - Options to pass to adapters
 * @returns {object} Map of adapter name to instance
 */
export function getAllAdapters(options = {}) {
    return {
        yahoo_finance: new YahooFinanceAdapter(options),
        binance: new BinanceAdapter(options),
        tradingview: new TradingViewAdapter(options),
        webull: new WebullAdapter(options)
    };
}

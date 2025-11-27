/**
 * Data Source Adapters Index
 * 
 * Exports all available data source adapters.
 */

export { BaseAdapter } from './base.js';
export { YahooFinanceAdapter } from './yahoo.js';
export { BinanceAdapter } from './binance.js';
export { TradingViewAdapter } from './tradingview.js';
export { WebullAdapter } from './webull.js';

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
            return new (await import('./yahoo.js')).YahooFinanceAdapter(options);
        case 'binance':
            return new (await import('./binance.js')).BinanceAdapter(options);
        case 'tradingview':
        case 'trading_view':
            return new (await import('./tradingview.js')).TradingViewAdapter(options);
        case 'webull':
            return new (await import('./webull.js')).WebullAdapter(options);
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
        yahoo_finance: new (require('./yahoo.js')).YahooFinanceAdapter(options),
        binance: new (require('./binance.js')).BinanceAdapter(options),
        tradingview: new (require('./tradingview.js')).TradingViewAdapter(options),
        webull: new (require('./webull.js')).WebullAdapter(options)
    };
}

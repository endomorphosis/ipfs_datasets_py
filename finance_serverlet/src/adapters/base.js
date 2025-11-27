/**
 * Base Adapter for Data Sources
 * 
 * Provides common functionality for all data source adapters.
 */

export class BaseAdapter {
    constructor(name, options = {}) {
        this.name = name;
        this.baseUrl = options.baseUrl || '';
        this.timeout = options.timeout || 30000;
        this.retryAttempts = options.retryAttempts || 3;
        this.retryDelay = options.retryDelay || 1000;
        this.rateLimit = options.rateLimit || { requests: 10, perSeconds: 60 };
        this.requestCount = 0;
        this.lastResetTime = Date.now();
    }

    /**
     * Check if rate limit allows a request
     * @returns {boolean}
     */
    canMakeRequest() {
        const now = Date.now();
        if (now - this.lastResetTime > this.rateLimit.perSeconds * 1000) {
            this.requestCount = 0;
            this.lastResetTime = now;
        }
        return this.requestCount < this.rateLimit.requests;
    }

    /**
     * Record a request for rate limiting
     */
    recordRequest() {
        this.requestCount++;
    }

    /**
     * Wait for rate limit reset
     */
    async waitForRateLimit() {
        const waitTime = (this.rateLimit.perSeconds * 1000) - (Date.now() - this.lastResetTime) + 100;
        if (waitTime > 0) {
            await new Promise(resolve => setTimeout(resolve, waitTime));
        }
        this.requestCount = 0;
        this.lastResetTime = Date.now();
    }

    /**
     * Make an HTTP request with retry logic
     * @param {string} url - URL to fetch
     * @param {object} options - Fetch options
     * @returns {Promise<object>} Response data
     */
    async fetchWithRetry(url, options = {}) {
        let lastError;
        
        for (let attempt = 1; attempt <= this.retryAttempts; attempt++) {
            try {
                // Check rate limit
                if (!this.canMakeRequest()) {
                    await this.waitForRateLimit();
                }
                
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), this.timeout);
                
                const response = await fetch(url, {
                    ...options,
                    signal: controller.signal
                });
                
                clearTimeout(timeoutId);
                this.recordRequest();
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                return await response.json();
            } catch (error) {
                lastError = error;
                console.warn(`Attempt ${attempt}/${this.retryAttempts} failed for ${url}: ${error.message}`);
                
                if (attempt < this.retryAttempts) {
                    await new Promise(resolve => setTimeout(resolve, this.retryDelay * attempt));
                }
            }
        }
        
        throw new Error(`Failed after ${this.retryAttempts} attempts: ${lastError.message}`);
    }

    /**
     * Fetch OHLCV data (to be implemented by subclasses)
     * @param {string} symbol - Symbol to fetch
     * @param {object} options - Fetch options
     * @returns {Promise<Array>} OHLCV data
     */
    async fetchOHLCV(symbol, options = {}) {
        throw new Error('fetchOHLCV must be implemented by subclass');
    }

    /**
     * Get current price (to be implemented by subclasses)
     * @param {string} symbol - Symbol to fetch
     * @returns {Promise<object>} Current price data
     */
    async getCurrentPrice(symbol) {
        throw new Error('getCurrentPrice must be implemented by subclass');
    }

    /**
     * Validate OHLCV data point
     * @param {object} data - OHLCV data point
     * @returns {object} Validation result
     */
    validateOHLCV(data) {
        const errors = [];
        
        // Check for required fields
        const required = ['timestamp', 'open', 'high', 'low', 'close'];
        for (const field of required) {
            if (data[field] === undefined || data[field] === null) {
                errors.push(`Missing required field: ${field}`);
            }
        }
        
        // Check OHLC consistency
        if (data.high < data.low) {
            errors.push(`High (${data.high}) is less than Low (${data.low})`);
        }
        if (data.open > data.high || data.open < data.low) {
            errors.push(`Open (${data.open}) is outside High-Low range`);
        }
        if (data.close > data.high || data.close < data.low) {
            errors.push(`Close (${data.close}) is outside High-Low range`);
        }
        
        // Check for negative/zero values
        if ([data.open, data.high, data.low, data.close].some(v => v < 0)) {
            errors.push('Negative price values detected');
        }
        if ([data.open, data.high, data.low, data.close].some(v => v === 0)) {
            errors.push('Zero price values detected (possible missing data)');
        }
        
        return {
            isValid: errors.length === 0,
            errors
        };
    }

    /**
     * Normalize OHLCV data to standard format
     * @param {object} rawData - Raw data from source
     * @returns {object} Normalized OHLCV data
     */
    normalizeOHLCV(rawData) {
        // To be overridden by subclasses for source-specific normalization
        return rawData;
    }
}

export default BaseAdapter;

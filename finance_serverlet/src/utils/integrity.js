/**
 * Data Integrity Validator
 * 
 * Validates and compares data across multiple sources to ensure integrity.
 * Uses statistical analysis to detect discrepancies and outliers.
 */

/**
 * Calculate percentage difference between two values
 * @param {number} a - First value
 * @param {number} b - Second value
 * @returns {number} Percentage difference
 */
function percentDiff(a, b) {
    if (a === 0 && b === 0) return 0;
    const avg = (Math.abs(a) + Math.abs(b)) / 2;
    return avg === 0 ? 0 : (Math.abs(a - b) / avg) * 100;
}

/**
 * Calculate mean of an array
 * @param {Array<number>} arr - Array of numbers
 * @returns {number} Mean value
 */
function mean(arr) {
    if (arr.length === 0) return 0;
    return arr.reduce((a, b) => a + b, 0) / arr.length;
}

/**
 * Calculate standard deviation
 * @param {Array<number>} arr - Array of numbers
 * @returns {number} Standard deviation
 */
function stdDev(arr) {
    if (arr.length <= 1) return 0;
    const avg = mean(arr);
    const squareDiffs = arr.map(value => Math.pow(value - avg, 2));
    return Math.sqrt(mean(squareDiffs));
}

/**
 * Calculate median of an array
 * @param {Array<number>} arr - Array of numbers
 * @returns {number} Median value
 */
function median(arr) {
    if (arr.length === 0) return 0;
    const sorted = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * Data Integrity Validator class
 */
export class IntegrityValidator {
    constructor(options = {}) {
        // Maximum allowed variance percentage between sources
        this.priceVarianceThreshold = options.priceVarianceThreshold || 1.0; // 1%
        this.volumeVarianceThreshold = options.volumeVarianceThreshold || 10.0; // 10%
        
        // Minimum sources required for validation
        this.minSources = options.minSources || 2;
    }

    /**
     * Compare OHLCV data points from multiple sources
     * @param {Array<object>} dataPoints - Array of OHLCV data from different sources
     * @returns {object} Validation result
     */
    compareDataPoints(dataPoints) {
        if (!dataPoints || dataPoints.length < this.minSources) {
            return {
                isValid: false,
                error: `Insufficient data sources. Required: ${this.minSources}, Got: ${dataPoints?.length || 0}`,
                sourcesCompared: dataPoints?.map(d => d.source) || [],
                discrepancies: []
            };
        }

        const sources = dataPoints.map(d => d.source);
        const discrepancies = [];

        // Extract price values
        const opens = dataPoints.map(d => d.open).filter(v => v != null);
        const highs = dataPoints.map(d => d.high).filter(v => v != null);
        const lows = dataPoints.map(d => d.low).filter(v => v != null);
        const closes = dataPoints.map(d => d.close).filter(v => v != null);
        const volumes = dataPoints.map(d => d.volume).filter(v => v != null);

        // Calculate variances
        const priceMetrics = {
            open: this.calculateVariance(opens),
            high: this.calculateVariance(highs),
            low: this.calculateVariance(lows),
            close: this.calculateVariance(closes)
        };

        const volumeMetrics = this.calculateVariance(volumes);

        // Check each price metric
        for (const [field, metrics] of Object.entries(priceMetrics)) {
            if (metrics.percentVariance > this.priceVarianceThreshold) {
                discrepancies.push({
                    field,
                    type: 'price_variance',
                    variance: metrics.percentVariance.toFixed(4),
                    threshold: this.priceVarianceThreshold,
                    values: dataPoints.map(d => ({ source: d.source, value: d[field] })),
                    consensusValue: metrics.median
                });
            }
        }

        // Check volume variance
        if (volumeMetrics.percentVariance > this.volumeVarianceThreshold) {
            discrepancies.push({
                field: 'volume',
                type: 'volume_variance',
                variance: volumeMetrics.percentVariance.toFixed(4),
                threshold: this.volumeVarianceThreshold,
                values: dataPoints.map(d => ({ source: d.source, value: d.volume })),
                consensusValue: volumeMetrics.median
            });
        }

        // Calculate overall price variance (using close as primary)
        const overallPriceVariance = priceMetrics.close.percentVariance;
        const overallVolumeVariance = volumeMetrics.percentVariance;

        return {
            isValid: discrepancies.filter(d => d.type === 'price_variance').length === 0,
            sourcesCompared: sources,
            priceVariance: overallPriceVariance,
            volumeVariance: overallVolumeVariance,
            discrepancies,
            consensusValues: {
                open: priceMetrics.open.median,
                high: priceMetrics.high.median,
                low: priceMetrics.low.median,
                close: priceMetrics.close.median,
                volume: volumeMetrics.median
            },
            metrics: {
                price: priceMetrics,
                volume: volumeMetrics
            }
        };
    }

    /**
     * Calculate variance statistics for an array of values
     * @param {Array<number>} values - Array of values
     * @returns {object} Variance statistics
     */
    calculateVariance(values) {
        if (values.length === 0) {
            return { min: 0, max: 0, mean: 0, median: 0, stdDev: 0, percentVariance: 0 };
        }

        const min = Math.min(...values);
        const max = Math.max(...values);
        const meanVal = mean(values);
        const medianVal = median(values);
        const stdDevVal = stdDev(values);

        // Calculate percent variance as range/mean
        const percentVariance = meanVal === 0 ? 0 : ((max - min) / meanVal) * 100;

        return {
            min,
            max,
            mean: meanVal,
            median: medianVal,
            stdDev: stdDevVal,
            percentVariance
        };
    }

    /**
     * Identify outliers in data points
     * @param {Array<object>} dataPoints - Data from different sources
     * @param {string} field - Field to check (open, high, low, close, volume)
     * @returns {Array<object>} Outlier data points with their sources
     */
    identifyOutliers(dataPoints, field = 'close') {
        if (dataPoints.length < 3) return [];

        const values = dataPoints.map(d => d[field]).filter(v => v != null);
        const medianVal = median(values);
        const madValues = values.map(v => Math.abs(v - medianVal));
        const mad = median(madValues); // Median Absolute Deviation
        
        // Use MAD-based outlier detection (robust method)
        // A value is an outlier if it deviates more than 3 MADs from median
        const threshold = 3;
        const outliers = [];

        for (const dp of dataPoints) {
            const value = dp[field];
            if (value == null) continue;
            
            const deviation = Math.abs(value - medianVal);
            const normalizedDeviation = mad === 0 ? 0 : deviation / mad;
            
            if (normalizedDeviation > threshold) {
                outliers.push({
                    source: dp.source,
                    value,
                    medianValue: medianVal,
                    deviation: normalizedDeviation.toFixed(4),
                    field
                });
            }
        }

        return outliers;
    }

    /**
     * Merge data from multiple sources using consensus values
     * @param {Array<object>} dataPoints - Data from different sources
     * @returns {object} Merged consensus data point
     */
    mergeToConsensus(dataPoints) {
        if (!dataPoints || dataPoints.length === 0) {
            return null;
        }

        const comparison = this.compareDataPoints(dataPoints);
        
        return {
            timestamp: dataPoints[0].timestamp,
            symbol: dataPoints[0].symbol,
            timeframe: dataPoints[0].timeframe,
            ...comparison.consensusValues,
            sources: comparison.sourcesCompared,
            isValidated: comparison.isValid,
            priceVariance: comparison.priceVariance,
            volumeVariance: comparison.volumeVariance,
            discrepancyCount: comparison.discrepancies.length
        };
    }

    /**
     * Validate a series of OHLCV data for internal consistency
     * @param {Array<object>} series - Time series data
     * @returns {object} Validation result
     */
    validateSeries(series) {
        const issues = [];
        
        for (let i = 0; i < series.length; i++) {
            const dp = series[i];
            
            // Check OHLC consistency
            if (dp.high < dp.low) {
                issues.push({
                    index: i,
                    timestamp: dp.timestamp,
                    issue: 'high_less_than_low',
                    details: { high: dp.high, low: dp.low }
                });
            }
            
            if (dp.open > dp.high || dp.open < dp.low) {
                issues.push({
                    index: i,
                    timestamp: dp.timestamp,
                    issue: 'open_outside_range',
                    details: { open: dp.open, high: dp.high, low: dp.low }
                });
            }
            
            if (dp.close > dp.high || dp.close < dp.low) {
                issues.push({
                    index: i,
                    timestamp: dp.timestamp,
                    issue: 'close_outside_range',
                    details: { close: dp.close, high: dp.high, low: dp.low }
                });
            }
            
            // Check for gaps in time series (if sorted chronologically)
            if (i > 0) {
                const prevTime = new Date(series[i - 1].timestamp).getTime();
                const currTime = new Date(dp.timestamp).getTime();
                
                // This is a simple check - in reality, you'd need to account for weekends, holidays, etc.
                const expectedGap = this.getExpectedGap(dp.timeframe);
                const actualGap = currTime - prevTime;
                
                if (actualGap > expectedGap * 2) {
                    issues.push({
                        index: i,
                        timestamp: dp.timestamp,
                        issue: 'time_gap',
                        details: { 
                            expectedGap: expectedGap,
                            actualGap: actualGap,
                            gapMultiplier: (actualGap / expectedGap).toFixed(2)
                        }
                    });
                }
            }
        }

        return {
            isValid: issues.length === 0,
            totalPoints: series.length,
            issueCount: issues.length,
            issues
        };
    }

    /**
     * Get expected time gap in milliseconds for a timeframe
     * @param {string} timeframe - Timeframe
     * @returns {number} Expected gap in ms
     */
    getExpectedGap(timeframe) {
        const gaps = {
            '1m': 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '30m': 30 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000,
            '1w': 7 * 24 * 60 * 60 * 1000
        };
        return gaps[timeframe] || 24 * 60 * 60 * 1000;
    }
}

export default IntegrityValidator;

/**
 * JavaScript Error Reporter for MCP Dashboard
 * 
 * This module captures JavaScript runtime errors and sends them to a backend
 * endpoint for automatic GitHub issue creation.
 */

class JavaScriptErrorReporter {
    constructor(options = {}) {
        this.enabled = options.enabled !== undefined ? options.enabled : 
                      (window.ERROR_REPORTING_ENABLED || false);
        this.endpoint = options.endpoint || '/api/report-error';
        this.reportedErrors = new Set();
        this.minReportInterval = options.minReportInterval || 3600000; // 1 hour in ms
        this.maxReportsPerSession = options.maxReportsPerSession || 10;
        this.reportCount = 0;
        
        if (this.enabled) {
            this.install();
        }
    }

    /**
     * Compute a hash for error deduplication
     */
    computeErrorHash(errorType, errorMessage, errorLocation) {
        const content = `${errorType}|${errorMessage}|${errorLocation}`;
        // Simple hash function for browser
        let hash = 0;
        for (let i = 0; i < content.length; i++) {
            const char = content.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32bit integer
        }
        return Math.abs(hash).toString(16);
    }

    /**
     * Check if error should be reported based on deduplication
     */
    shouldReportError(errorHash) {
        // Check report limit
        if (this.reportCount >= this.maxReportsPerSession) {
            console.warn('Error reporting: Maximum reports per session reached');
            return false;
        }

        // Check if already reported
        if (this.reportedErrors.has(errorHash)) {
            return false;
        }

        return true;
    }

    /**
     * Extract error location from stack trace
     */
    extractErrorLocation(stack) {
        if (!stack) return 'unknown';
        
        const lines = stack.split('\n');
        for (const line of lines) {
            // Look for file:line:column pattern
            const match = line.match(/\((.*?):(\d+):(\d+)\)/) || 
                         line.match(/at (.*?):(\d+):(\d+)/);
            if (match) {
                return `${match[1]}:${match[2]}`;
            }
        }
        return 'unknown';
    }

    /**
     * Format error data for reporting
     */
    formatErrorData(errorType, errorMessage, stack, context = {}) {
        const location = this.extractErrorLocation(stack);
        
        return {
            error_type: errorType,
            error_message: errorMessage,
            source: 'javascript',
            timestamp: new Date().toISOString(),
            error_location: location,
            stack_trace: stack,
            context: {
                ...context,
                userAgent: navigator.userAgent,
                url: window.location.href,
                viewport: {
                    width: window.innerWidth,
                    height: window.innerHeight
                }
            }
        };
    }

    /**
     * Send error report to backend
     */
    async sendErrorReport(errorData) {
        try {
            const response = await fetch(this.endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(errorData)
            });

            if (response.ok) {
                const result = await response.json();
                console.log('Error reported successfully:', result);
                return result;
            } else {
                console.error('Failed to report error:', response.statusText);
                return { success: false, error: response.statusText };
            }
        } catch (e) {
            console.error('Error reporting failed:', e);
            return { success: false, error: e.message };
        }
    }

    /**
     * Report an error
     */
    async reportError(errorType, errorMessage, stack, context = {}) {
        if (!this.enabled) {
            return { success: false, error: 'Error reporting is disabled' };
        }

        // Compute error hash
        const location = this.extractErrorLocation(stack);
        const errorHash = this.computeErrorHash(errorType, errorMessage, location);

        // Check if should report
        if (!this.shouldReportError(errorHash)) {
            return { success: false, error: 'Error already reported' };
        }

        // Mark as reported
        this.reportedErrors.add(errorHash);
        this.reportCount++;

        // Format and send error
        const errorData = this.formatErrorData(errorType, errorMessage, stack, context);
        return await this.sendErrorReport(errorData);
    }

    /**
     * Handle window error events
     */
    handleWindowError(message, source, lineno, colno, error) {
        const errorType = error ? error.constructor.name : 'Error';
        const errorMessage = message || 'Unknown error';
        const stack = error ? error.stack : `at ${source}:${lineno}:${colno}`;

        this.reportError(errorType, errorMessage, stack, {
            source_file: source,
            line: lineno,
            column: colno
        });

        // Don't suppress default error handling
        return false;
    }

    /**
     * Handle unhandled promise rejections
     */
    handleUnhandledRejection(event) {
        const errorType = event.reason ? event.reason.constructor.name : 'UnhandledRejection';
        const errorMessage = event.reason ? event.reason.message || String(event.reason) : 'Unknown rejection';
        const stack = event.reason && event.reason.stack ? event.reason.stack : 'No stack trace available';

        this.reportError(errorType, errorMessage, stack, {
            promise_rejection: true
        });
    }

    /**
     * Install error handlers
     */
    install() {
        // Handle uncaught errors
        window.addEventListener('error', (event) => {
            this.handleWindowError(
                event.message,
                event.filename,
                event.lineno,
                event.colno,
                event.error
            );
        });

        // Handle unhandled promise rejections
        window.addEventListener('unhandledrejection', (event) => {
            this.handleUnhandledRejection(event);
        });

        console.log('JavaScript error reporting installed');
    }

    /**
     * Enable error reporting
     */
    enable() {
        if (!this.enabled) {
            this.enabled = true;
            this.install();
        }
    }

    /**
     * Disable error reporting
     */
    disable() {
        this.enabled = false;
    }
}

// Create global error reporter instance
window.errorReporter = new JavaScriptErrorReporter({
    enabled: window.ERROR_REPORTING_ENABLED || false
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = JavaScriptErrorReporter;
}

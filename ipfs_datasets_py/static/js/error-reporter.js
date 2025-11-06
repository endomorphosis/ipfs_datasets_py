/**
 * Client-side error reporter for automatic GitHub issue creation
 * 
 * This script handles JavaScript errors in the dashboard and reports them
 * to the backend API for conversion to GitHub issues.
 */

class ErrorReporter {
    constructor() {
        this.config = {
            enabled: true,
            apiEndpoint: '/api/report-error',
            batchSize: 5,
            batchTimeout: 5000, // 5 seconds
            maxErrorsPerSession: 50,
        };
        
        this.errorQueue = [];
        this.errorCount = 0;
        this.batchTimer = null;
        
        this.init();
    }
    
    init() {
        // Install global error handlers
        this.installErrorHandlers();
        
        console.log('✅ Error reporting initialized');
    }
    
    installErrorHandlers() {
        // Global error handler
        window.addEventListener('error', (event) => {
            this.handleError({
                type: 'JavaScript Error',
                message: event.message,
                filename: event.filename,
                lineno: event.lineno,
                colno: event.colno,
                stack: event.error ? event.error.stack : null,
                timestamp: new Date().toISOString(),
            });
        });
        
        // Unhandled promise rejection handler
        window.addEventListener('unhandledrejection', (event) => {
            this.handleError({
                type: 'Unhandled Promise Rejection',
                message: event.reason ? event.reason.toString() : 'Unknown rejection',
                stack: event.reason && event.reason.stack ? event.reason.stack : null,
                timestamp: new Date().toISOString(),
            });
        });
    }
    
    handleError(errorData) {
        if (!this.config.enabled) {
            return;
        }
        
        // Check session limit
        if (this.errorCount >= this.config.maxErrorsPerSession) {
            console.warn('Error reporting: session limit reached');
            return;
        }
        
        this.errorCount++;
        
        // Add browser and page context
        const enrichedError = {
            ...errorData,
            url: window.location.href,
            userAgent: navigator.userAgent,
            timestamp: errorData.timestamp || new Date().toISOString(),
            source: 'MCP Dashboard JavaScript',
        };
        
        // Add to queue
        this.errorQueue.push(enrichedError);
        
        // Log to console for debugging
        console.error('Error captured:', enrichedError);
        
        // Batch errors to avoid overwhelming the server
        if (this.errorQueue.length >= this.config.batchSize) {
            this.flushErrors();
        } else {
            this.scheduleBatchFlush();
        }
    }
    
    scheduleBatchFlush() {
        // Clear existing timer
        if (this.batchTimer) {
            clearTimeout(this.batchTimer);
        }
        
        // Schedule flush
        this.batchTimer = setTimeout(() => {
            this.flushErrors();
        }, this.config.batchTimeout);
    }
    
    async flushErrors() {
        // Clear timer
        if (this.batchTimer) {
            clearTimeout(this.batchTimer);
            this.batchTimer = null;
        }
        
        // Get errors to send
        const errorsToSend = this.errorQueue.splice(0, this.config.batchSize);
        
        if (errorsToSend.length === 0) {
            return;
        }
        
        try {
            const response = await fetch(this.config.apiEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    errors: errorsToSend,
                }),
            });
            
            if (!response.ok) {
                console.error('Failed to report errors to server:', response.statusText);
            } else {
                const result = await response.json();
                console.log('Errors reported:', result);
            }
        } catch (error) {
            console.error('Error reporting failed:', error);
            // Don't try to report the error reporting failure to avoid infinite loop
        }
    }
    
    reportError(error, context = {}) {
        /**
         * Manually report an error
         * 
         * @param {Error} error - The error object
         * @param {Object} context - Additional context about the error
         */
        const errorData = {
            type: error.name || 'Error',
            message: error.message,
            stack: error.stack,
            context: context,
            timestamp: new Date().toISOString(),
        };
        
        this.handleError(errorData);
    }
    
    disable() {
        this.config.enabled = false;
        console.log('Error reporting disabled');
    }
    
    enable() {
        this.config.enabled = true;
        console.log('Error reporting enabled');
    }
}

// Create global error reporter instance
window.errorReporter = new ErrorReporter();

// Add convenience method to window
window.reportError = (error, context) => {
    window.errorReporter.reportError(error, context);
};

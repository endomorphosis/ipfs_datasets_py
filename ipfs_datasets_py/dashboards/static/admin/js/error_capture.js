/**
 * JavaScript Error Capture and Reporting Module
 * 
 * Captures JavaScript errors, console logs, and user actions in the MCP dashboard
 * and sends them to the backend for GitHub issue creation and auto-healing.
 */

class DashboardErrorCapture {
    constructor(config = {}) {
        this.config = {
            apiEndpoint: config.apiEndpoint || '/api/report-js-error',
            maxConsoleHistory: config.maxConsoleHistory || 100,
            maxActionHistory: config.maxActionHistory || 50,
            debounceMs: config.debounceMs || 1000,
            enableConsoleCapture: config.enableConsoleCapture !== false,
            enableActionTracking: config.enableActionTracking !== false,
            ...config
        };
        
        this.consoleHistory = [];
        this.actionHistory = [];
        this.errorQueue = [];
        this.isReporting = false;
        this.reportTimer = null;
        
        this.init();
    }
    
    init() {
        // Capture unhandled errors
        window.addEventListener('error', (event) => {
            this.captureError({
                type: 'error',
                message: event.message,
                filename: event.filename,
                lineno: event.lineno,
                colno: event.colno,
                stack: event.error ? event.error.stack : null,
                timestamp: new Date().toISOString()
            });
        });
        
        // Capture unhandled promise rejections
        window.addEventListener('unhandledrejection', (event) => {
            this.captureError({
                type: 'unhandledrejection',
                message: event.reason ? event.reason.message || String(event.reason) : 'Unknown rejection',
                stack: event.reason ? event.reason.stack : null,
                timestamp: new Date().toISOString()
            });
        });
        
        // Intercept console methods
        if (this.config.enableConsoleCapture) {
            this.interceptConsole();
        }
        
        // Track user actions
        if (this.config.enableActionTracking) {
            this.trackUserActions();
        }
        
        console.info('[ErrorCapture] Dashboard error capture initialized');
    }
    
    interceptConsole() {
        const originalConsole = {
            log: console.log,
            error: console.error,
            warn: console.warn,
            info: console.info
        };
        
        const captureConsoleCall = (level, args) => {
            const message = Array.from(args).map(arg => {
                if (typeof arg === 'object') {
                    try {
                        return JSON.stringify(arg, null, 2);
                    } catch (e) {
                        return String(arg);
                    }
                }
                return String(arg);
            }).join(' ');
            
            this.consoleHistory.push({
                level,
                message,
                timestamp: new Date().toISOString()
            });
            
            // Keep only the most recent entries
            if (this.consoleHistory.length > this.config.maxConsoleHistory) {
                this.consoleHistory.shift();
            }
        };
        
        console.log = function(...args) {
            captureConsoleCall('log', args);
            originalConsole.log.apply(console, args);
        };
        
        console.error = function(...args) {
            captureConsoleCall('error', args);
            originalConsole.error.apply(console, args);
        };
        
        console.warn = function(...args) {
            captureConsoleCall('warn', args);
            originalConsole.warn.apply(console, args);
        };
        
        console.info = function(...args) {
            captureConsoleCall('info', args);
            originalConsole.info.apply(console, args);
        };
    }
    
    trackUserActions() {
        // Track clicks
        document.addEventListener('click', (event) => {
            const target = event.target;
            const action = {
                type: 'click',
                element: target.tagName,
                id: target.id || null,
                className: target.className || null,
                text: target.textContent ? target.textContent.substring(0, 50) : null,
                timestamp: new Date().toISOString()
            };
            
            this.actionHistory.push(action);
            
            if (this.actionHistory.length > this.config.maxActionHistory) {
                this.actionHistory.shift();
            }
        });
        
        // Track form submissions
        document.addEventListener('submit', (event) => {
            const form = event.target;
            this.actionHistory.push({
                type: 'submit',
                element: 'FORM',
                id: form.id || null,
                action: form.action || null,
                timestamp: new Date().toISOString()
            });
        });
        
        // Track navigation
        window.addEventListener('hashchange', () => {
            this.actionHistory.push({
                type: 'navigation',
                hash: window.location.hash,
                timestamp: new Date().toISOString()
            });
        });
    }
    
    captureError(errorInfo) {
        console.error('[ErrorCapture] Captured error:', errorInfo);
        
        // Add to error queue
        this.errorQueue.push({
            ...errorInfo,
            userAgent: navigator.userAgent,
            url: window.location.href,
            consoleHistory: [...this.consoleHistory],
            actionHistory: [...this.actionHistory]
        });
        
        // Debounce reporting to avoid overwhelming the server
        if (this.reportTimer) {
            clearTimeout(this.reportTimer);
        }
        
        this.reportTimer = setTimeout(() => {
            this.reportErrors();
        }, this.config.debounceMs);
    }
    
    async reportErrors() {
        if (this.isReporting || this.errorQueue.length === 0) {
            return;
        }
        
        this.isReporting = true;
        const errors = [...this.errorQueue];
        this.errorQueue = [];
        
        try {
            const response = await fetch(this.config.apiEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    errors,
                    reportedAt: new Date().toISOString(),
                    sessionId: this.getSessionId()
                })
            });
            
            if (!response.ok) {
                console.error('[ErrorCapture] Failed to report errors:', response.status);
                // Re-queue errors if reporting failed
                this.errorQueue.unshift(...errors);
            } else {
                const result = await response.json();
                console.info('[ErrorCapture] Errors reported successfully:', result);
            }
        } catch (error) {
            console.error('[ErrorCapture] Error reporting failed:', error);
            // Re-queue errors if reporting failed
            this.errorQueue.unshift(...errors);
        } finally {
            this.isReporting = false;
        }
    }
    
    getSessionId() {
        let sessionId = sessionStorage.getItem('dashboard_session_id');
        if (!sessionId) {
            sessionId = this.generateSessionId();
            sessionStorage.setItem('dashboard_session_id', sessionId);
        }
        return sessionId;
    }
    
    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substring(2, 15);
    }
    
    // Manual error reporting
    reportManualError(error, context = {}) {
        this.captureError({
            type: 'manual',
            message: error.message || String(error),
            stack: error.stack || null,
            context,
            timestamp: new Date().toISOString()
        });
    }
}

// Initialize error capture when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.dashboardErrorCapture = new DashboardErrorCapture();
});

// Also make it available immediately for early errors
window.DashboardErrorCapture = DashboardErrorCapture;

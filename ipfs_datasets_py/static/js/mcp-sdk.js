/**
 * MCP Client JavaScript SDK for IPFS Datasets
 * 
 * This SDK provides a simple interface for interacting with the IPFS Datasets
 * MCP server dashboard from web applications.
 * 
 * Features:
 * - Tool discovery and execution
 * - Real-time server status monitoring
 * - Execution history management
 * - Error handling and retry logic
 * 
 * @version 1.0.0
 */

class MCPClient {
    /**
     * Initialize the MCP Client
     * @param {string} baseUrl - Base URL of the MCP API (e.g., 'http://localhost:8080/api/mcp')
     * @param {Object} options - Configuration options
     */
    constructor(baseUrl, options = {}) {
        this.baseUrl = baseUrl.replace(/\/$/, ''); // Remove trailing slash
        this.options = {
            timeout: 30000, // 30 seconds default timeout
            retries: 3,     // Number of retries for failed requests
            retryDelay: 1000, // Delay between retries in milliseconds
            ...options
        };
        
        // Internal state
        this.cache = new Map();
        this.listeners = new Map();
        this.requestId = 0;
    }

    /**
     * Make an HTTP request with error handling and retries
     * @private
     */
    async _request(method, path, data = null, retryCount = 0) {
        const requestId = ++this.requestId;
        const url = `${this.baseUrl}${path}`;
        
        try {
            const options = {
                method: method.toUpperCase(),
                headers: {
                    'Content-Type': 'application/json',
                    'X-Request-ID': requestId.toString()
                }
            };
            
            if (data) {
                options.body = JSON.stringify(data);
            }
            
            // Add timeout
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), this.options.timeout);
            options.signal = controller.signal;
            
            const response = await fetch(url, options);
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                const errorText = await response.text();
                let errorData;
                try {
                    errorData = JSON.parse(errorText);
                } catch {
                    errorData = { error: errorText };
                }
                throw new MCPError(
                    errorData.error || `HTTP ${response.status}`,
                    response.status,
                    errorData
                );
            }
            
            const result = await response.json();
            return result;
            
        } catch (error) {
            if (error.name === 'AbortError') {
                throw new MCPError('Request timeout', 408);
            }
            
            // Retry logic for network errors
            if (retryCount < this.options.retries && this._shouldRetry(error)) {
                await this._delay(this.options.retryDelay * (retryCount + 1));
                return this._request(method, path, data, retryCount + 1);
            }
            
            throw error;
        }
    }

    /**
     * Determine if a request should be retried
     * @private
     */
    _shouldRetry(error) {
        // Retry on network errors or 5xx server errors
        return !error.status || error.status >= 500;
    }

    /**
     * Delay helper for retries
     * @private
     */
    _delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Get all available MCP tools
     * @param {boolean} useCache - Whether to use cached results
     * @returns {Promise<Object>} Tools organized by category
     */
    async getTools(useCache = true) {
        if (useCache && this.cache.has('tools')) {
            return this.cache.get('tools');
        }
        
        const tools = await this._request('GET', '/tools');
        this.cache.set('tools', tools);
        return tools;
    }

    /**
     * Get information about a specific tool
     * @param {string} category - Tool category
     * @param {string} toolName - Tool name
     * @returns {Promise<Object>} Tool information
     */
    async getToolInfo(category, toolName) {
        return this._request('GET', `/tools/${category}/${toolName}`);
    }

    /**
     * Execute an MCP tool with given parameters
     * @param {string} category - Tool category
     * @param {string} toolName - Tool name
     * @param {Object} parameters - Tool parameters
     * @param {Object} options - Execution options
     * @returns {Promise<Object>} Execution result
     */
    async executeTool(category, toolName, parameters = {}, options = {}) {
        const executionOptions = {
            timeout: this.options.timeout,
            ...options
        };
        
        this._emit('toolExecutionStart', { category, toolName, parameters });
        
        try {
            const result = await this._request(
                'POST', 
                `/tools/${category}/${toolName}/execute`,
                { ...parameters, ...executionOptions }
            );
            
            this._emit('toolExecutionComplete', { category, toolName, result });
            return result;
        } catch (error) {
            this._emit('toolExecutionError', { category, toolName, error });
            throw error;
        }
    }

    /**
     * Get the status of a specific tool execution
     * @param {string} executionId - Execution ID
     * @returns {Promise<Object>} Execution status
     */
    async getExecutionStatus(executionId) {
        return this._request('GET', `/executions/${executionId}`);
    }

    /**
     * Get tool execution history
     * @param {number} limit - Maximum number of executions to return
     * @returns {Promise<Object>} Execution history
     */
    async getExecutionHistory(limit = 50) {
        return this._request('GET', `/history?limit=${limit}`);
    }

    /**
     * Get MCP server status
     * @returns {Promise<Object>} Server status
     */
    async getServerStatus() {
        return this._request('GET', '/status');
    }

    /**
     * Poll server status at regular intervals
     * @param {number} interval - Polling interval in milliseconds
     * @param {Function} callback - Callback function to call with status updates
     * @returns {Function} Stop polling function
     */
    startStatusPolling(interval = 5000, callback = null) {
        let isPolling = true;
        
        const poll = async () => {
            if (!isPolling) return;
            
            try {
                const status = await this.getServerStatus();
                this._emit('statusUpdate', status);
                if (callback) callback(null, status);
            } catch (error) {
                this._emit('statusError', error);
                if (callback) callback(error, null);
            }
            
            if (isPolling) {
                setTimeout(poll, interval);
            }
        };
        
        poll(); // Start immediately
        
        return () => {
            isPolling = false;
        };
    }

    /**
     * Clear all cached data
     */
    clearCache() {
        this.cache.clear();
    }

    /**
     * Add event listener
     * @param {string} event - Event name
     * @param {Function} listener - Listener function
     */
    on(event, listener) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(listener);
    }

    /**
     * Remove event listener
     * @param {string} event - Event name
     * @param {Function} listener - Listener function to remove
     */
    off(event, listener) {
        const listeners = this.listeners.get(event);
        if (listeners) {
            const index = listeners.indexOf(listener);
            if (index !== -1) {
                listeners.splice(index, 1);
            }
        }
    }

    /**
     * Emit event to listeners
     * @private
     */
    _emit(event, data) {
        const listeners = this.listeners.get(event);
        if (listeners) {
            listeners.forEach(listener => {
                try {
                    listener(data);
                } catch (error) {
                    console.error('Error in event listener:', error);
                }
            });
        }
    }

    /**
     * Create a tool execution builder for fluent API
     * @param {string} category - Tool category
     * @param {string} toolName - Tool name
     * @returns {ToolExecutionBuilder} Builder instance
     */
    tool(category, toolName) {
        return new ToolExecutionBuilder(this, category, toolName);
    }
}

/**
 * Fluent API builder for tool execution
 */
class ToolExecutionBuilder {
    constructor(client, category, toolName) {
        this.client = client;
        this.category = category;
        this.toolName = toolName;
        this.parameters = {};
        this.options = {};
    }

    /**
     * Set tool parameters
     * @param {Object} params - Parameters to set
     * @returns {ToolExecutionBuilder} This builder instance
     */
    withParams(params) {
        this.parameters = { ...this.parameters, ...params };
        return this;
    }

    /**
     * Set execution options
     * @param {Object} opts - Options to set
     * @returns {ToolExecutionBuilder} This builder instance
     */
    withOptions(opts) {
        this.options = { ...this.options, ...opts };
        return this;
    }

    /**
     * Execute the tool
     * @returns {Promise<Object>} Execution result
     */
    async execute() {
        return this.client.executeTool(
            this.category,
            this.toolName,
            this.parameters,
            this.options
        );
    }

    /**
     * Get tool information
     * @returns {Promise<Object>} Tool information
     */
    async info() {
        return this.client.getToolInfo(this.category, this.toolName);
    }
}

/**
 * Custom error class for MCP operations
 */
class MCPError extends Error {
    constructor(message, status = null, data = null) {
        super(message);
        this.name = 'MCPError';
        this.status = status;
        this.data = data;
    }
}

/**
 * Utility functions for common MCP operations
 */
class MCPUtils {
    /**
     * Format execution result for display
     * @param {Object} result - Execution result
     * @returns {string} Formatted result
     */
    static formatExecutionResult(result) {
        if (!result) return 'No result';
        
        if (result.error) {
            return `Error: ${result.error}`;
        }
        
        if (result.result) {
            if (typeof result.result === 'string') {
                return result.result;
            }
            return JSON.stringify(result.result, null, 2);
        }
        
        return 'Completed successfully';
    }

    /**
     * Create a status badge HTML
     * @param {string} status - Execution status
     * @returns {string} HTML for status badge
     */
    static createStatusBadge(status) {
        const statusClasses = {
            'running': 'badge-warning',
            'completed': 'badge-success',
            'failed': 'badge-danger',
            'pending': 'badge-secondary'
        };
        
        const cssClass = statusClasses[status] || 'badge-secondary';
        return `<span class="badge ${cssClass}">${status}</span>`;
    }

    /**
     * Parse tool parameters from string
     * @param {string} paramString - JSON string of parameters
     * @returns {Object} Parsed parameters
     */
    static parseParameters(paramString) {
        if (!paramString || !paramString.trim()) {
            return {};
        }
        
        try {
            return JSON.parse(paramString);
        } catch (error) {
            throw new Error(`Invalid parameter JSON: ${error.message}`);
        }
    }

    /**
     * Debounce function for rate limiting
     * @param {Function} func - Function to debounce
     * @param {number} wait - Wait time in milliseconds
     * @returns {Function} Debounced function
     */
    static debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
}

// Export classes for both CommonJS and ES6 modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { MCPClient, ToolExecutionBuilder, MCPError, MCPUtils };
} else {
    // Browser global
    window.MCPClient = MCPClient;
    window.ToolExecutionBuilder = ToolExecutionBuilder;
    window.MCPError = MCPError;
    window.MCPUtils = MCPUtils;
}

/**
 * jQuery plugin for easy MCP integration (if jQuery is available)
 * Only register when a real jQuery instance is present (i.e., $.fn exists).
 */
if (typeof $ !== 'undefined' && $.fn && typeof $.fn === 'object') {
    $.fn.mcpToolExecutor = function(options = {}) {
        const settings = {
            baseUrl: '/api/mcp',
            onResult: null,
            onError: null,
            ...options
        };
        
        const client = new MCPClient(settings.baseUrl);
        
        return this.each(function() {
            const $element = $(this);
            const category = $element.data('category');
            const toolName = $element.data('tool');
            
            $element.on('click', async function(e) {
                e.preventDefault();
                
                try {
                    const params = $element.data('params') || {};
                    const result = await client.executeTool(category, toolName, params);
                    
                    if (settings.onResult) {
                        settings.onResult(result, $element);
                    }
                } catch (error) {
                    if (settings.onError) {
                        settings.onError(error, $element);
                    } else {
                        console.error('Tool execution failed:', error);
                    }
                }
            });
        });
    };
}
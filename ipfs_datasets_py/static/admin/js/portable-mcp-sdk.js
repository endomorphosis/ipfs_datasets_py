/**
 * Portable MCP SDK for IPFS Datasets Dashboard
 * 
 * This SDK provides portable client functionality for interacting with the 
 * IPFS Datasets MCP server with queue management capabilities.
 * 
 * Features:
 * - Task queue management
 * - Real-time status updates
 * - Tool execution with queuing
 * - Task cancellation and control
 * 
 * @version 2.0.0
 */

class PortableMCPSDK {
    /**
     * Initialize the Portable MCP SDK
     * @param {string} baseUrl - Base URL of the MCP API
     * @param {Object} options - Configuration options
     */
    constructor(baseUrl, options = {}) {
        this.baseUrl = baseUrl.replace(/\/$/, ''); // Remove trailing slash
        this.options = {
            timeout: 30000,
            retries: 3,
            retryDelay: 1000,
            pollInterval: 2000, // Queue status polling interval
            ...options
        };
        
        // Internal state
        this.requestId = 0;
        this.isPolling = false;
        this.listeners = new Map();
        
        // Queue state
        this.queueStatus = {
            queue_length: 0,
            active_tasks: 0,
            completed_tasks: 0,
            failed_tasks: 0,
            max_concurrent: 5,
            queue_paused: false
        };
        
        this.tasks = {
            queued: [],
            active: [],
            completed: [],
            failed: []
        };
    }

    /**
     * Make an HTTP request with error handling and retries
     * @private
     */
    async request(method, path, data = null, retryCount = 0) {
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
            
            if (data && (method.toUpperCase() === 'POST' || method.toUpperCase() === 'PUT')) {
                options.body = JSON.stringify(data);
            }
            
            const response = await fetch(url, options);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const result = await response.json();
            return result;
            
        } catch (error) {
            if (retryCount < this.options.retries) {
                await new Promise(resolve => setTimeout(resolve, this.options.retryDelay));
                return this.request(method, path, data, retryCount + 1);
            }
            
            // If this is a "Method not found" error, create a custom MCPError
            if (error.message.includes('404') || error.message.includes('Method not found')) {
                const mcpError = new Error('Method not found');
                mcpError.name = 'MCPError';
                throw mcpError;
            }
            
            throw error;
        }
    }

    /**
     * Get current queue status
     */
    async getQueueStatus() {
        try {
            const status = await this.request('GET', '/api/mcp/queue/status');
            this.queueStatus = status;
            this.emit('queueStatusUpdate', status);
            return status;
        } catch (error) {
            console.error('Failed to get queue status:', error);
            throw error;
        }
    }

    /**
     * Get all tasks in various states
     */
    async getQueueTasks() {
        try {
            const tasks = await this.request('GET', '/api/mcp/queue/tasks');
            this.tasks = tasks;
            this.emit('tasksUpdate', tasks);
            return tasks;
        } catch (error) {
            console.error('Failed to get queue tasks:', error);
            throw error;
        }
    }

    /**
     * Queue a new task for execution
     * @param {Object} taskData - Task configuration
     */
    async queueTask(taskData) {
        try {
            const result = await this.request('POST', '/api/mcp/queue/tasks', taskData);
            this.emit('taskQueued', result);
            return result;
        } catch (error) {
            console.error('Failed to queue task:', error);
            throw error;
        }
    }

    /**
     * Cancel a task by ID
     * @param {string} taskId - Task ID to cancel
     */
    async cancelTask(taskId) {
        try {
            const result = await this.request('POST', `/api/mcp/queue/tasks/${taskId}/cancel`);
            this.emit('taskCancelled', result);
            return result;
        } catch (error) {
            console.error('Failed to cancel task:', error);
            throw error;
        }
    }

    /**
     * Get details for a specific task
     * @param {string} taskId - Task ID
     */
    async getTaskDetails(taskId) {
        try {
            return await this.request('GET', `/api/mcp/queue/tasks/${taskId}`);
        } catch (error) {
            console.error('Failed to get task details:', error);
            throw error;
        }
    }

    /**
     * Start polling for queue status updates
     * @param {number} interval - Polling interval in milliseconds
     */
    startPolling(interval = null) {
        if (this.isPolling) return;
        
        this.isPolling = true;
        const pollInterval = interval || this.options.pollInterval;
        
        const poll = async () => {
            if (!this.isPolling) return;
            
            try {
                await this.getQueueStatus();
                await this.getQueueTasks();
            } catch (error) {
                console.warn('Polling error:', error);
            }
            
            if (this.isPolling) {
                setTimeout(poll, pollInterval);
            }
        };
        
        poll();
    }

    /**
     * Stop polling for updates
     */
    stopPolling() {
        this.isPolling = false;
    }

    /**
     * Add event listener
     * @param {string} event - Event name
     * @param {Function} callback - Callback function
     */
    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }

    /**
     * Remove event listener
     * @param {string} event - Event name
     * @param {Function} callback - Callback function to remove
     */
    off(event, callback) {
        if (this.listeners.has(event)) {
            const callbacks = this.listeners.get(event);
            const index = callbacks.indexOf(callback);
            if (index > -1) {
                callbacks.splice(index, 1);
            }
        }
    }

    /**
     * Emit an event
     * @param {string} event - Event name
     * @param {*} data - Event data
     * @private
     */
    emit(event, data) {
        if (this.listeners.has(event)) {
            this.listeners.get(event).forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error(`Error in event listener for ${event}:`, error);
                }
            });
        }
    }

    /**
     * Get available MCP tools
     */
    async getTools() {
        try {
            return await this.request('GET', '/api/mcp/tools');
        } catch (error) {
            console.error('Failed to get tools:', error);
            throw error;
        }
    }

    /**
     * Execute a tool directly (bypassing queue)
     * @param {string} category - Tool category
     * @param {string} toolName - Tool name
     * @param {Object} parameters - Tool parameters
     */
    async executeTool(category, toolName, parameters = {}) {
        try {
            return await this.request('POST', `/api/mcp/tools/${category}/${toolName}/execute`, parameters);
        } catch (error) {
            console.error('Failed to execute tool:', error);
            throw error;
        }
    }
}

// Export for both module and global usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PortableMCPSDK;
} else {
    window.PortableMCPSDK = PortableMCPSDK;
}
// Enhanced MCP JavaScript SDK with GraphRAG Support
class MCPError extends Error {
    constructor(message, status = 500, data = null) {
        super(message);
        this.name = 'MCPError';
        this.status = status;
        this.data = data;
    }
}

class MCPClient {
    constructor(baseUrl, options = {}) {
        this.baseUrl = baseUrl.replace(/\/$/, '');
        this.timeout = options.timeout || 30000;
        this.apiKey = options.apiKey || null;
    }

    async _request(path, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), this.timeout);
        
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (this.apiKey) {
            headers['Authorization'] = `Bearer ${this.apiKey}`;
        }
        
        try {
            const res = await fetch(`${this.baseUrl}${path}`, { 
                ...options, 
                headers,
                signal: controller.signal 
            });
            
            let data;
            try {
                data = await res.json();
            } catch (e) {
                data = {};
            }
            
            if (!res.ok) {
                throw new MCPError(data.error || res.statusText, res.status, data);
            }
            
            return data;
        } finally {
            clearTimeout(timer);
        }
    }

    // Core MCP methods
    getServerStatus() { 
        return this._request('/status'); 
    }
    
    getTools() { 
        return this._request('/tools'); 
    }
    
    getTool(category, tool) { 
        return this._request(`/tools/${encodeURIComponent(category)}/${encodeURIComponent(tool)}`); 
    }
    
    executeTool(category, tool, params = {}) {
        return this._request(`/tools/${encodeURIComponent(category)}/${encodeURIComponent(tool)}/execute`, {
            method: 'POST',
            body: JSON.stringify(params)
        });
    }

    getExecutionStatus(executionId) {
        return this._request(`/executions/${encodeURIComponent(executionId)}`);
    }

    getExecutionHistory(limit = 50) {
        return this._request(`/history?limit=${limit}`);
    }

    // GraphRAG methods
    startGraphRAGProcessing(url, mode = 'balanced') {
        return this._request('/graphrag/process', {
            method: 'POST',
            body: JSON.stringify({ url, mode })
        });
    }

    getGraphRAGSession(sessionId) {
        return this._request(`/graphrag/sessions/${encodeURIComponent(sessionId)}`);
    }

    listGraphRAGSessions() {
        return this._request('/graphrag/sessions');
    }

    // Analytics methods
    getAnalyticsMetrics() {
        return this._request('/analytics/metrics');
    }

    getAnalyticsHistory(limit = 100) {
        return this._request(`/analytics/history?limit=${limit}`);
    }

    // RAG Query methods
    executeRAGQuery(query, context = {}) {
        return this._request('/rag/query', {
            method: 'POST',
            body: JSON.stringify({ query, context })
        });
    }

    // Investigation methods
    startInvestigation(url, analysisType = 'comprehensive', metadata = {}) {
        return this._request('/investigation/analyze', {
            method: 'POST',
            body: JSON.stringify({ url, analysis_type: analysisType, metadata })
        });
    }

    // Real-time monitoring
    startStatusPolling(intervalMs = 5000, callback = () => {}) {
        let stopped = false;
        
        const tick = async () => {
            if (stopped) return;
            
            try {
                const status = await this.getServerStatus();
                callback(null, status);
            } catch (error) {
                callback(error);
            }
            
            if (!stopped) {
                setTimeout(tick, intervalMs);
            }
        };
        
        setTimeout(tick, 0);
        
        return () => { stopped = true; };
    }

    // WebSocket connection for real-time updates
    connectWebSocket(onMessage = () => {}, onError = () => {}) {
        const wsUrl = this.baseUrl.replace(/^http/, 'ws') + '/ws';
        const ws = new WebSocket(wsUrl);
        
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                onMessage(data);
            } catch (e) {
                onError(new Error('Failed to parse WebSocket message'));
            }
        };
        
        ws.onerror = (error) => {
            onError(error);
        };
        
        return ws;
    }

    // Utility methods
    async waitForExecution(executionId, pollInterval = 1000, maxWait = 300000) {
        const startTime = Date.now();
        
        while (Date.now() - startTime < maxWait) {
            try {
                const status = await this.getExecutionStatus(executionId);
                
                if (status.status === 'completed' || status.status === 'failed') {
                    return status;
                }
                
                await new Promise(resolve => setTimeout(resolve, pollInterval));
            } catch (error) {
                if (error.status === 404) {
                    throw new MCPError('Execution not found', 404);
                }
                throw error;
            }
        }
        
        throw new MCPError('Execution timeout', 408);
    }

    async waitForGraphRAGSession(sessionId, pollInterval = 2000, maxWait = 600000) {
        const startTime = Date.now();
        
        while (Date.now() - startTime < maxWait) {
            try {
                const session = await this.getGraphRAGSession(sessionId);
                
                if (session.status === 'completed' || session.status === 'failed') {
                    return session;
                }
                
                await new Promise(resolve => setTimeout(resolve, pollInterval));
            } catch (error) {
                if (error.status === 404) {
                    throw new MCPError('Session not found', 404);
                }
                throw error;
            }
        }
        
        throw new MCPError('Session timeout', 408);
    }
}

// Export for both browser and Node.js environments
if (typeof window !== 'undefined') {
    window.MCPClient = MCPClient;
    window.MCPError = MCPError;
} else if (typeof module !== 'undefined' && module.exports) {
    module.exports = { MCPClient, MCPError };
}
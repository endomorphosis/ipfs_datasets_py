/**
 * Unified Investigation MCP SDK - JavaScript client for investigation dashboard
 * 
 * This SDK provides a centralized interface for communicating with the MCP server
 * using JSON-RPC calls for all investigation and news analysis functionality.
 * 
 * @version 2.0.0
 */

class UnifiedInvestigationMCPClient {
    constructor(config = {}) {
        this.baseUrl = config.baseUrl || 'http://localhost:8080';
        this.mcpEndpoint = `${this.baseUrl}/mcp/call-tool`;
        this.options = {
            timeout: 60000, // 60 seconds for investigation operations
            retries: 3,
            retryDelay: 2000,
            ...config.options
        };
        
        // Internal state management
        this.requestId = 0;
        this.activeRequests = new Map();
        this.cache = new Map();
        this.listeners = new Map();
        
        // Connection state
        this.connected = false;
        this.connectionStatus = 'disconnected';
        
        // Initialize connection monitoring
        this._initializeConnectionMonitoring();
    }

    // ============== CONNECTION MANAGEMENT ==============

    async connect() {
        try {
            await this._testMCPConnection();
            this.connected = true;
            this.connectionStatus = 'connected';
            this._notifyStatusChange('connected');
            return { status: 'connected', timestamp: new Date().toISOString() };
        } catch (error) {
            this.connected = false;
            this.connectionStatus = 'error';
            this._notifyStatusChange('error', error);
            throw error;
        }
    }

    async disconnect() {
        this.connected = false;
        this.connectionStatus = 'disconnected';
        this._notifyStatusChange('disconnected');
    }

    async _testMCPConnection() {
        const response = await this._callMCPTool('health_check', {});
        if (!response || response.isError) {
            throw new Error('MCP server health check failed');
        }
        return response;
    }

    _initializeConnectionMonitoring() {
        // Monitor connection status every 30 seconds
        setInterval(async () => {
            if (this.connected) {
                try {
                    await this._testMCPConnection();
                } catch (error) {
                    this.connected = false;
                    this.connectionStatus = 'error';
                    this._notifyStatusChange('error', error);
                }
            }
        }, 30000);
    }

    // ============== CORE MCP COMMUNICATION ==============

    async _callMCPTool(toolName, args = {}, options = {}) {
        const requestId = ++this.requestId;
        const mergedOptions = { ...this.options, ...options };
        
        const payload = {
            name: toolName,
            arguments: args
        };

        try {
            const response = await this._makeJSONRPCRequest(payload, requestId, mergedOptions);
            
            if (response.isError) {
                throw new InvestigationMCPError(
                    `Tool ${toolName} failed: ${response.content[0]?.text || 'Unknown error'}`,
                    { toolName, args, response }
                );
            }
            
            return response;
        } catch (error) {
            console.error(`MCP tool call failed: ${toolName}`, error);
            throw error;
        }
    }

    async _makeJSONRPCRequest(payload, requestId, options) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), options.timeout);
        
        this.activeRequests.set(requestId, { controller, payload });
        
        try {
            const response = await fetch(this.mcpEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-Request-ID': requestId.toString()
                },
                body: JSON.stringify(payload),
                signal: controller.signal
            });

            clearTimeout(timeoutId);
            this.activeRequests.delete(requestId);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            return result;

        } catch (error) {
            clearTimeout(timeoutId);
            this.activeRequests.delete(requestId);

            if (error.name === 'AbortError') {
                throw new InvestigationMCPError('Request timeout', { requestId, payload });
            }
            
            throw error;
        }
    }

    // ============== ENTITY ANALYSIS METHODS ==============

    async analyzeEntities(corpusData, options = {}) {
        const args = {
            corpus_data: JSON.stringify(corpusData),
            analysis_type: options.analysisType || 'comprehensive',
            entity_types: options.entityTypes || ['PERSON', 'ORG', 'GPE', 'EVENT'],
            confidence_threshold: options.confidenceThreshold || 0.85,
            user_context: options.userContext || null
        };

        const response = await this._callMCPTool('analyze_entities', args);
        return this._parseToolResponse(response);
    }

    async exploreEntity(entityId, corpusData, options = {}) {
        const args = {
            entity_id: entityId,
            corpus_data: JSON.stringify(corpusData),
            include_relationships: options.includeRelationships !== false,
            include_timeline: options.includeTimeline !== false,
            include_sources: options.includeSources !== false
        };

        const response = await this._callMCPTool('explore_entity', args);
        return this._parseToolResponse(response);
    }

    // ============== RELATIONSHIP MAPPING METHODS ==============

    async mapRelationships(corpusData, options = {}) {
        const args = {
            corpus_data: JSON.stringify(corpusData),
            relationship_types: options.relationshipTypes || ['co_occurrence', 'citation', 'semantic', 'temporal'],
            min_strength: options.minStrength || 0.5,
            max_depth: options.maxDepth || 3,
            focus_entity: options.focusEntity || null
        };

        const response = await this._callMCPTool('map_relationships', args);
        return this._parseToolResponse(response);
    }

    async analyzeEntityTimeline(entityId, corpusData, options = {}) {
        const args = {
            entity_id: entityId,
            corpus_data: JSON.stringify(corpusData),
            time_granularity: options.timeGranularity || 'day',
            include_related: options.includeRelated !== false,
            event_types: options.eventTypes || ['mention', 'action', 'relationship', 'property_change']
        };

        const response = await this._callMCPTool('analyze_entity_timeline', args);
        return this._parseToolResponse(response);
    }

    // ============== PATTERN DETECTION METHODS ==============

    async detectPatterns(corpusData, options = {}) {
        const args = {
            corpus_data: JSON.stringify(corpusData),
            pattern_types: options.patternTypes || ['behavioral', 'relational', 'temporal', 'anomaly'],
            time_window: options.timeWindow || '30d',
            confidence_threshold: options.confidenceThreshold || 0.7
        };

        const response = await this._callMCPTool('detect_patterns', args);
        return this._parseToolResponse(response);
    }

    async trackProvenance(entityId, corpusData, options = {}) {
        const args = {
            entity_id: entityId,
            corpus_data: JSON.stringify(corpusData),
            trace_depth: options.traceDepth || 5,
            include_citations: options.includeCitations !== false,
            include_transformations: options.includeTransformations !== false
        };

        const response = await this._callMCPTool('track_provenance', args);
        return this._parseToolResponse(response);
    }

    // ============== DEONTOLOGICAL REASONING METHODS ==============

    async analyzeDeontologicalConflicts(corpusData, options = {}) {
        const args = {
            corpus_data: JSON.stringify(corpusData),
            conflict_types: options.conflictTypes || ['direct', 'conditional', 'jurisdictional', 'temporal'],
            severity_threshold: options.severityThreshold || 'medium',
            entity_filter: options.entityFilter || null
        };

        const response = await this._callMCPTool('analyze_deontological_conflicts', args);
        return this._parseToolResponse(response);
    }

    async queryDeonticStatements(corpusData, options = {}) {
        const args = {
            corpus_data: JSON.stringify(corpusData),
            entity: options.entity || null,
            modality: options.modality || null,
            action_pattern: options.actionPattern || null,
            confidence_min: options.confidenceMin || 0.0
        };

        const response = await this._callMCPTool('query_deontic_statements', args);
        return this._parseToolResponse(response);
    }

    async queryDeonticConflicts(corpusData, options = {}) {
        const args = {
            corpus_data: JSON.stringify(corpusData),
            conflict_type: options.conflictType || null,
            severity: options.severity || null,
            entity: options.entity || null,
            resolved_only: options.resolvedOnly || false
        };

        const response = await this._callMCPTool('query_deontic_conflicts', args);
        return this._parseToolResponse(response);
    }

    // ============== DATA INGESTION METHODS ==============

    async ingestNewsArticle(url, options = {}) {
        const args = {
            url: url,
            source_type: options.sourceType || 'news',
            analysis_type: options.analysisType || 'comprehensive',
            metadata: options.metadata ? JSON.stringify(options.metadata) : null
        };

        const response = await this._callMCPTool('ingest_news_article', args);
        return this._parseToolResponse(response);
    }

    async ingestNewsFeed(feedUrl, options = {}) {
        const args = {
            feed_url: feedUrl,
            max_articles: options.maxArticles || 50,
            filters: options.filters ? JSON.stringify(options.filters) : null,
            processing_mode: options.processingMode || 'parallel'
        };

        const response = await this._callMCPTool('ingest_news_feed', args);
        return this._parseToolResponse(response);
    }

    async ingestWebsite(baseUrl, options = {}) {
        const args = {
            base_url: baseUrl,
            max_pages: options.maxPages || 100,
            max_depth: options.maxDepth || 3,
            url_patterns: options.urlPatterns ? JSON.stringify(options.urlPatterns) : null,
            content_types: options.contentTypes ? JSON.stringify(options.contentTypes) : null
        };

        const response = await this._callMCPTool('ingest_website', args, { timeout: 120000 }); // Extended timeout
        return this._parseToolResponse(response);
    }

    async ingestDocumentCollection(documentPaths, options = {}) {
        const args = {
            document_paths: JSON.stringify(documentPaths),
            collection_name: options.collectionName || 'document_collection',
            processing_options: options.processingOptions ? JSON.stringify(options.processingOptions) : null,
            metadata_extraction: options.metadataExtraction !== false
        };

        const response = await this._callMCPTool('ingest_document_collection', args, { timeout: 180000 }); // Extended timeout
        return this._parseToolResponse(response);
    }

    // ============== WORKFLOW MANAGEMENT ==============

    async startInvestigationWorkflow(workflowType, parameters = {}) {
        const workflowId = `workflow_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        
        // Store workflow state
        this._setWorkflowState(workflowId, {
            type: workflowType,
            status: 'running',
            parameters: parameters,
            startTime: new Date().toISOString(),
            steps: []
        });

        try {
            let result;
            
            switch (workflowType) {
                case 'comprehensive_entity_analysis':
                    result = await this._runComprehensiveEntityAnalysis(workflowId, parameters);
                    break;
                case 'relationship_investigation':
                    result = await this._runRelationshipInvestigation(workflowId, parameters);
                    break;
                case 'deontological_analysis':
                    result = await this._runDeontologicalAnalysis(workflowId, parameters);
                    break;
                case 'data_ingestion_pipeline':
                    result = await this._runDataIngestionPipeline(workflowId, parameters);
                    break;
                default:
                    throw new InvestigationMCPError(`Unknown workflow type: ${workflowType}`);
            }

            this._updateWorkflowState(workflowId, { 
                status: 'completed', 
                result: result,
                endTime: new Date().toISOString()
            });

            return { workflowId, status: 'completed', result };

        } catch (error) {
            this._updateWorkflowState(workflowId, { 
                status: 'failed', 
                error: error.message,
                endTime: new Date().toISOString()
            });
            
            throw error;
        }
    }

    async getWorkflowStatus(workflowId) {
        return this._getWorkflowState(workflowId);
    }

    // ============== WORKFLOW IMPLEMENTATIONS ==============

    async _runComprehensiveEntityAnalysis(workflowId, params) {
        const steps = [
            { name: 'entity_extraction', method: 'analyzeEntities' },
            { name: 'relationship_mapping', method: 'mapRelationships' },
            { name: 'pattern_detection', method: 'detectPatterns' }
        ];

        const results = {};
        
        for (const step of steps) {
            this._addWorkflowStep(workflowId, step.name, 'running');
            
            try {
                const result = await this[step.method](params.corpusData, params.options || {});
                results[step.name] = result;
                
                this._addWorkflowStep(workflowId, step.name, 'completed', result);
            } catch (error) {
                this._addWorkflowStep(workflowId, step.name, 'failed', { error: error.message });
                throw error;
            }
        }

        return results;
    }

    async _runRelationshipInvestigation(workflowId, params) {
        const steps = [
            { name: 'relationship_mapping', method: 'mapRelationships' },
            { name: 'timeline_analysis', method: 'analyzeEntityTimeline' },
            { name: 'provenance_tracking', method: 'trackProvenance' }
        ];

        const results = {};
        
        for (const step of steps) {
            this._addWorkflowStep(workflowId, step.name, 'running');
            
            try {
                let result;
                if (step.method === 'analyzeEntityTimeline' || step.method === 'trackProvenance') {
                    result = await this[step.method](params.entityId, params.corpusData, params.options || {});
                } else {
                    result = await this[step.method](params.corpusData, params.options || {});
                }
                results[step.name] = result;
                
                this._addWorkflowStep(workflowId, step.name, 'completed', result);
            } catch (error) {
                this._addWorkflowStep(workflowId, step.name, 'failed', { error: error.message });
                throw error;
            }
        }

        return results;
    }

    async _runDeontologicalAnalysis(workflowId, params) {
        const steps = [
            { name: 'conflict_analysis', method: 'analyzeDeontologicalConflicts' },
            { name: 'statement_query', method: 'queryDeonticStatements' },
            { name: 'conflict_query', method: 'queryDeonticConflicts' }
        ];

        const results = {};
        
        for (const step of steps) {
            this._addWorkflowStep(workflowId, step.name, 'running');
            
            try {
                const result = await this[step.method](params.corpusData, params.options || {});
                results[step.name] = result;
                
                this._addWorkflowStep(workflowId, step.name, 'completed', result);
            } catch (error) {
                this._addWorkflowStep(workflowId, step.name, 'failed', { error: error.message });
                throw error;
            }
        }

        return results;
    }

    async _runDataIngestionPipeline(workflowId, params) {
        const results = {};
        
        // Determine ingestion type based on parameters
        if (params.urls && params.urls.length > 0) {
            this._addWorkflowStep(workflowId, 'url_ingestion', 'running');
            
            const urlResults = [];
            for (const url of params.urls) {
                try {
                    const result = await this.ingestNewsArticle(url, params.options || {});
                    urlResults.push(result);
                } catch (error) {
                    urlResults.push({ url, error: error.message });
                }
            }
            results.url_ingestion = urlResults;
            this._addWorkflowStep(workflowId, 'url_ingestion', 'completed', urlResults);
        }

        if (params.feeds && params.feeds.length > 0) {
            this._addWorkflowStep(workflowId, 'feed_ingestion', 'running');
            
            const feedResults = [];
            for (const feed of params.feeds) {
                try {
                    const result = await this.ingestNewsFeed(feed, params.options || {});
                    feedResults.push(result);
                } catch (error) {
                    feedResults.push({ feed, error: error.message });
                }
            }
            results.feed_ingestion = feedResults;
            this._addWorkflowStep(workflowId, 'feed_ingestion', 'completed', feedResults);
        }

        if (params.websites && params.websites.length > 0) {
            this._addWorkflowStep(workflowId, 'website_ingestion', 'running');
            
            const websiteResults = [];
            for (const website of params.websites) {
                try {
                    const result = await this.ingestWebsite(website, params.options || {});
                    websiteResults.push(result);
                } catch (error) {
                    websiteResults.push({ website, error: error.message });
                }
            }
            results.website_ingestion = websiteResults;
            this._addWorkflowStep(workflowId, 'website_ingestion', 'completed', websiteResults);
        }

        if (params.documentPaths && params.documentPaths.length > 0) {
            this._addWorkflowStep(workflowId, 'document_ingestion', 'running');
            
            try {
                const result = await this.ingestDocumentCollection(params.documentPaths, params.options || {});
                results.document_ingestion = result;
                this._addWorkflowStep(workflowId, 'document_ingestion', 'completed', result);
            } catch (error) {
                results.document_ingestion = { error: error.message };
                this._addWorkflowStep(workflowId, 'document_ingestion', 'failed', { error: error.message });
            }
        }

        return results;
    }

    // ============== WORKFLOW STATE MANAGEMENT ==============

    _setWorkflowState(workflowId, state) {
        this.cache.set(`workflow_${workflowId}`, state);
    }

    _updateWorkflowState(workflowId, updates) {
        const current = this.cache.get(`workflow_${workflowId}`) || {};
        this.cache.set(`workflow_${workflowId}`, { ...current, ...updates });
    }

    _getWorkflowState(workflowId) {
        return this.cache.get(`workflow_${workflowId}`) || null;
    }

    _addWorkflowStep(workflowId, stepName, status, result = null) {
        const workflow = this.cache.get(`workflow_${workflowId}`);
        if (workflow) {
            workflow.steps.push({
                name: stepName,
                status: status,
                timestamp: new Date().toISOString(),
                result: result
            });
            this.cache.set(`workflow_${workflowId}`, workflow);
        }
    }

    // ============== UTILITY METHODS ==============

    _parseToolResponse(response) {
        if (response.isError) {
            throw new InvestigationMCPError(
                response.content[0]?.text || 'Tool execution failed',
                { response }
            );
        }

        // Parse the response content
        const content = response.content[0]?.text;
        if (!content) {
            return response;
        }

        try {
            // Try to parse as JSON
            const parsed = JSON.parse(content.replace(/^[^{]*/, '').replace(/[^}]*$/, ''));
            return parsed;
        } catch (error) {
            // If not valid JSON, return the raw content
            return { raw_content: content };
        }
    }

    _notifyStatusChange(status, error = null) {
        const listeners = this.listeners.get('connectionStatus') || [];
        listeners.forEach(callback => {
            try {
                callback({ status, error, timestamp: new Date().toISOString() });
            } catch (err) {
                console.error('Error in connection status listener:', err);
            }
        });
    }

    // ============== EVENT LISTENERS ==============

    onConnectionStatusChange(callback) {
        if (!this.listeners.has('connectionStatus')) {
            this.listeners.set('connectionStatus', []);
        }
        this.listeners.get('connectionStatus').push(callback);
    }

    onWorkflowUpdate(callback) {
        if (!this.listeners.has('workflowUpdate')) {
            this.listeners.set('workflowUpdate', []);
        }
        this.listeners.get('workflowUpdate').push(callback);
    }

    // ============== DEBUGGING AND MONITORING ==============

    getConnectionStatus() {
        return {
            connected: this.connected,
            status: this.connectionStatus,
            activeRequests: this.activeRequests.size,
            cacheSize: this.cache.size
        };
    }

    getActiveRequests() {
        return Array.from(this.activeRequests.entries()).map(([id, req]) => ({
            requestId: id,
            tool: req.payload.name,
            timestamp: req.timestamp || new Date().toISOString()
        }));
    }

    clearCache() {
        this.cache.clear();
    }

    // ============== BATCH OPERATIONS ==============

    async batchExecute(operations) {
        const results = {};
        const promises = [];

        for (const [key, operation] of Object.entries(operations)) {
            const promise = this._executeBatchOperation(operation)
                .then(result => ({ key, success: true, result }))
                .catch(error => ({ key, success: false, error: error.message }));
            promises.push(promise);
        }

        const settled = await Promise.allSettled(promises);
        
        for (const outcome of settled) {
            if (outcome.status === 'fulfilled') {
                const { key, success, result, error } = outcome.value;
                results[key] = success ? result : { error };
            } else {
                console.error('Batch operation failed:', outcome.reason);
            }
        }

        return results;
    }

    async _executeBatchOperation(operation) {
        const { method, args = [] } = operation;
        
        if (typeof this[method] !== 'function') {
            throw new InvestigationMCPError(`Unknown method: ${method}`);
        }

        return await this[method](...args);
    }
}

// Custom error class for Investigation MCP errors
class InvestigationMCPError extends Error {
    constructor(message, details = {}) {
        super(message);
        this.name = 'InvestigationMCPError';
        this.details = details;
        this.timestamp = new Date().toISOString();
    }
}

// Export for use in different environments
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { UnifiedInvestigationMCPClient, InvestigationMCPError };
} else if (typeof window !== 'undefined') {
    window.UnifiedInvestigationMCPClient = UnifiedInvestigationMCPClient;
    window.InvestigationMCPError = InvestigationMCPError;
}
/**
 * News Analysis SDK - JavaScript client for news analysis dashboard
 * 
 * Extends the MCP SDK with specialized news analysis functionality
 * for data scientists, historians, and lawyers.
 */

class NewsAnalysisClient extends MCPClient {
    constructor(config = {}) {
        super(config);
        this.userType = config.userType || 'general';
        this.newsCache = new Map();
        this.activeWorkflows = new Map();
    }

    // ============== CORE NEWS INGESTION ==============

    /**
     * Ingest a single news article
     */
    async ingestNewsArticle(url, metadata = {}) {
        const payload = {
            url: url,
            metadata: {
                ...metadata,
                user_type: this.userType,
                ingestion_timestamp: new Date().toISOString()
            }
        };

        try {
            const response = await this._makeRequest('/api/news/ingest/article', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            if (response.status === 'completed') {
                this._cacheArticleResult(response);
                this._notifyWorkflowComplete('article_ingestion', response);
            }

            return response;
        } catch (error) {
            console.error('Article ingestion failed:', error);
            throw new NewsAnalysisError('Failed to ingest article', { url, error });
        }
    }

    /**
     * Batch ingest from news feed (RSS, JSON feed, etc.)
     */
    async ingestNewsFeed(feedUrl, options = {}) {
        const payload = {
            feed_url: feedUrl,
            filters: options.filters || {},
            max_articles: options.maxArticles || 50,
            user_type: this.userType
        };

        try {
            const response = await this._makeRequest('/api/news/ingest/batch', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            if (response.status === 'completed') {
                this._cacheWorkflowResult('batch_ingestion', response);
                this._notifyWorkflowComplete('batch_ingestion', response);
            }

            return response;
        } catch (error) {
            console.error('Feed ingestion failed:', error);
            throw new NewsAnalysisError('Failed to ingest news feed', { feedUrl, error });
        }
    }

    /**
     * Upload and process document collection
     */
    async ingestDocumentCollection(files, metadata = {}) {
        const formData = new FormData();
        
        // Add files to form data
        files.forEach((file, index) => {
            formData.append(`file_${index}`, file);
        });

        // Add metadata
        formData.append('metadata', JSON.stringify({
            ...metadata,
            user_type: this.userType,
            collection_size: files.length
        }));

        try {
            const response = await fetch(`${this.baseUrl}/api/news/ingest/documents`, {
                method: 'POST',
                headers: this._getAuthHeaders(),
                body: formData
            });

            const result = await response.json();
            
            if (result.status === 'completed') {
                this._cacheWorkflowResult('document_collection', result);
                this._notifyWorkflowComplete('document_collection', result);
            }

            return result;
        } catch (error) {
            console.error('Document collection ingestion failed:', error);
            throw new NewsAnalysisError('Failed to ingest document collection', { error });
        }
    }

    // ============== TIMELINE ANALYSIS ==============

    /**
     * Generate interactive timeline for a query
     */
    async generateTimeline(query, dateRange, options = {}) {
        const params = new URLSearchParams({
            query: query,
            start_date: dateRange.start.toISOString(),
            end_date: dateRange.end.toISOString(),
            granularity: options.granularity || 'day'
        });

        try {
            const response = await this._makeRequest(`/api/news/timeline?${params}`);
            
            // Cache timeline data for visualization
            const cacheKey = `timeline_${query}_${dateRange.start}_${dateRange.end}`;
            this.newsCache.set(cacheKey, response);

            return response;
        } catch (error) {
            console.error('Timeline generation failed:', error);
            throw new NewsAnalysisError('Failed to generate timeline', { query, error });
        }
    }

    /**
     * Identify event clusters in articles
     */
    async identifyEventClusters(articleIds, options = {}) {
        const payload = {
            article_ids: articleIds,
            min_cluster_size: options.minClusterSize || 3,
            clustering_method: options.method || 'semantic_clustering'
        };

        try {
            const response = await this._makeRequest('/api/news/analysis/clusters', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            return response;
        } catch (error) {
            console.error('Event clustering failed:', error);
            throw new NewsAnalysisError('Failed to identify event clusters', { articleIds, error });
        }
    }

    /**
     * Track story evolution over time
     */
    async trackStoryEvolution(seedArticleId) {
        try {
            const response = await this._makeRequest(`/api/news/analysis/story-evolution/${seedArticleId}`);
            return response;
        } catch (error) {
            console.error('Story evolution tracking failed:', error);
            throw new NewsAnalysisError('Failed to track story evolution', { seedArticleId, error });
        }
    }

    // ============== ENTITY ANALYSIS ==============

    /**
     * Build entity relationship graph
     */
    async buildEntityGraph(articleIds, options = {}) {
        const payload = {
            article_ids: articleIds,
            include_relationships: options.includeRelationships !== false,
            entity_types: options.entityTypes || ['person', 'organization', 'location', 'event']
        };

        try {
            const response = await this._makeRequest('/api/news/entities/graph', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            return response;
        } catch (error) {
            console.error('Entity graph building failed:', error);
            throw new NewsAnalysisError('Failed to build entity graph', { articleIds, error });
        }
    }

    /**
     * Get entities for specific article
     */
    async getArticleEntities(articleId) {
        try {
            const response = await this._makeRequest(`/api/news/entities/${articleId}`);
            return response;
        } catch (error) {
            console.error('Entity extraction failed:', error);
            throw new NewsAnalysisError('Failed to extract entities', { articleId, error });
        }
    }

    /**
     * Track entity mentions over time
     */
    async trackEntityMentions(entityName, dateRange = null) {
        const payload = {
            entity: entityName
        };

        if (dateRange) {
            payload.start_date = dateRange.start.toISOString();
            payload.end_date = dateRange.end.toISOString();
        }

        try {
            const response = await this._makeRequest('/api/news/entities/mentions', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            return response;
        } catch (error) {
            console.error('Entity mention tracking failed:', error);
            throw new NewsAnalysisError('Failed to track entity mentions', { entityName, error });
        }
    }

    // ============== CROSS-DOCUMENT ANALYSIS ==============

    /**
     * Find conflicting reports on a topic
     */
    async findConflictingReports(topic, dateRange = null) {
        const payload = {
            topic: topic
        };

        if (dateRange) {
            payload.start_date = dateRange.start.toISOString();
            payload.end_date = dateRange.end.toISOString();
        }

        try {
            const response = await this._makeRequest('/api/news/search/conflicts', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            return response;
        } catch (error) {
            console.error('Conflict detection failed:', error);
            throw new NewsAnalysisError('Failed to find conflicting reports', { topic, error });
        }
    }

    /**
     * Trace information flow for a claim
     */
    async traceInformationFlow(claim) {
        const payload = { claim: claim };

        try {
            const response = await this._makeRequest('/api/news/analysis/information-flow', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            return response;
        } catch (error) {
            console.error('Information flow tracing failed:', error);
            throw new NewsAnalysisError('Failed to trace information flow', { claim, error });
        }
    }

    // ============== PROFESSIONAL EXPORT ==============

    /**
     * Export data for data science workflows
     */
    async exportForDataScience(datasetId, format = 'csv', options = {}) {
        const params = new URLSearchParams({
            dataset_id: datasetId,
            format: format,
            include_embeddings: options.includeEmbeddings || false,
            include_metadata: options.includeMetadata !== false,
            user_type: 'data_scientist'
        });

        try {
            const response = await fetch(`${this.baseUrl}/api/news/export/data-science?${params}`, {
                headers: this._getAuthHeaders()
            });

            if (format === 'json') {
                return await response.json();
            } else {
                return await response.blob();
            }
        } catch (error) {
            console.error('Data science export failed:', error);
            throw new NewsAnalysisError('Failed to export for data science', { datasetId, format, error });
        }
    }

    /**
     * Export data for legal research
     */
    async exportForLegalResearch(caseId, options = {}) {
        const params = new URLSearchParams({
            case_id: caseId,
            include_chain_of_custody: options.includeChainOfCustody !== false,
            citation_format: options.citationFormat || 'bluebook',
            user_type: 'lawyer'
        });

        try {
            const response = await fetch(`${this.baseUrl}/api/news/export/legal?${params}`, {
                headers: this._getAuthHeaders()
            });

            return await response.blob(); // Usually PDF or DOCX
        } catch (error) {
            console.error('Legal export failed:', error);
            throw new NewsAnalysisError('Failed to export for legal research', { caseId, error });
        }
    }

    /**
     * Export data for academic research
     */
    async exportForAcademicResearch(researchId, options = {}) {
        const params = new URLSearchParams({
            research_id: researchId,
            citation_style: options.citationStyle || 'apa',
            include_bibliography: options.includeBibliography !== false,
            user_type: 'historian'
        });

        try {
            const response = await fetch(`${this.baseUrl}/api/news/export/academic?${params}`, {
                headers: this._getAuthHeaders()
            });

            return await response.blob(); // Usually PDF or DOCX
        } catch (error) {
            console.error('Academic export failed:', error);
            throw new NewsAnalysisError('Failed to export for academic research', { researchId, error });
        }
    }

    // ============== WORKFLOW MANAGEMENT ==============

    /**
     * Start professional workflow
     */
    async startProfessionalWorkflow(workflowType, config = {}) {
        const payload = {
            workflow_type: workflowType,
            user_type: this.userType,
            config: config
        };

        try {
            const response = await this._makeRequest('/api/workflows/start', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            if (response.workflow_id) {
                this.activeWorkflows.set(response.workflow_id, {
                    type: workflowType,
                    status: response.status,
                    startTime: new Date(),
                    config: config
                });
            }

            return response;
        } catch (error) {
            console.error('Workflow start failed:', error);
            throw new NewsAnalysisError('Failed to start workflow', { workflowType, error });
        }
    }

    /**
     * Get workflow status
     */
    async getWorkflowStatus(workflowId) {
        try {
            const response = await this._makeRequest(`/api/workflows/${workflowId}/status`);
            
            if (this.activeWorkflows.has(workflowId)) {
                const workflow = this.activeWorkflows.get(workflowId);
                workflow.status = response.status;
                workflow.lastUpdate = new Date();
            }

            return response;
        } catch (error) {
            console.error('Workflow status check failed:', error);
            throw new NewsAnalysisError('Failed to get workflow status', { workflowId, error });
        }
    }

    // ============== SPECIALIZED SEARCH ==============

    /**
     * Semantic search with news-specific context
     */
    async semanticSearch(query, filters = {}) {
        const payload = {
            query: query,
            filters: {
                ...filters,
                user_type_context: this.userType
            },
            search_type: 'semantic'
        };

        try {
            const response = await this._makeRequest('/api/news/search/semantic', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            return response;
        } catch (error) {
            console.error('Semantic search failed:', error);
            throw new NewsAnalysisError('Failed to perform semantic search', { query, error });
        }
    }

    /**
     * Professional search tailored for user type
     */
    async professionalSearch(query, context = {}) {
        let searchConfig;

        switch (this.userType) {
            case 'data_scientist':
                searchConfig = {
                    prioritize_structured_data: true,
                    include_statistical_context: true,
                    filter_by_data_quality: true
                };
                break;
            case 'historian':
                searchConfig = {
                    prioritize_primary_sources: true,
                    include_temporal_context: true,
                    verify_historical_accuracy: true
                };
                break;
            case 'lawyer':
                searchConfig = {
                    prioritize_authoritative_sources: true,
                    include_legal_precedents: true,
                    verify_factual_claims: true
                };
                break;
            default:
                searchConfig = {};
        }

        const payload = {
            query: query,
            user_type: this.userType,
            search_config: { ...searchConfig, ...context },
            filters: context.filters || {}
        };

        try {
            const response = await this._makeRequest('/api/news/search/professional', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            return response;
        } catch (error) {
            console.error('Professional search failed:', error);
            throw new NewsAnalysisError('Failed to perform professional search', { query, error });
        }
    }

    // ============== UTILITY METHODS ==============

    /**
     * Cache article result for quick access
     */
    _cacheArticleResult(result) {
        if (result.storage_id) {
            this.newsCache.set(`article_${result.storage_id}`, result);
        }
    }

    /**
     * Cache workflow result
     */
    _cacheWorkflowResult(workflowType, result) {
        const cacheKey = `workflow_${workflowType}_${result.workflow_id}`;
        this.newsCache.set(cacheKey, result);
    }

    /**
     * Notify listeners about workflow completion
     */
    _notifyWorkflowComplete(workflowType, result) {
        this.emit('workflowComplete', {
            type: workflowType,
            result: result,
            timestamp: new Date()
        });
    }

    /**
     * Get cached data
     */
    getCachedData(key) {
        return this.newsCache.get(key);
    }

    /**
     * Clear cache
     */
    clearCache() {
        this.newsCache.clear();
    }

    /**
     * Get active workflows summary
     */
    getActiveWorkflows() {
        const workflows = Array.from(this.activeWorkflows.entries()).map(([id, workflow]) => ({
            id,
            ...workflow
        }));

        return workflows;
    }
}

/**
 * News Analysis specific error class
 */
class NewsAnalysisError extends Error {
    constructor(message, context = {}) {
        super(message);
        this.name = 'NewsAnalysisError';
        this.context = context;
        this.timestamp = new Date();
    }
}

/**
 * News Analysis Dashboard UI Components
 */
class NewsAnalysisDashboard {
    constructor(containerId, config = {}) {
        this.container = document.getElementById(containerId);
        this.client = new NewsAnalysisClient(config);
        this.components = new Map();
        this.activeViews = new Set();
        
        this.init();
    }

    init() {
        this._createLayout();
        this._initializeComponents();
        this._setupEventListeners();
    }

    _createLayout() {
        this.container.innerHTML = `
            <div class="news-dashboard">
                <!-- Header -->
                <div class="dashboard-header">
                    <h1>News Analysis Dashboard</h1>
                    <div class="user-controls">
                        <select id="userTypeSelector" class="user-type-selector">
                            <option value="general">General User</option>
                            <option value="data_scientist">Data Scientist</option>
                            <option value="historian">Historian</option>
                            <option value="lawyer">Lawyer</option>
                        </select>
                        <button id="settingsBtn" class="settings-btn">⚙️</button>
                    </div>
                </div>

                <!-- Navigation -->
                <div class="dashboard-nav">
                    <button class="nav-btn active" data-view="overview">Overview</button>
                    <button class="nav-btn" data-view="ingest">Ingest</button>
                    <button class="nav-btn" data-view="analyze">Analyze</button>
                    <button class="nav-btn" data-view="timeline">Timeline</button>
                    <button class="nav-btn" data-view="entities">Entities</button>
                    <button class="nav-btn" data-view="search">Search</button>
                    <button class="nav-btn" data-view="export">Export</button>
                </div>

                <!-- Main Content Area -->
                <div class="dashboard-content">
                    <!-- Overview Panel -->
                    <div id="overviewPanel" class="content-panel active">
                        <div class="stats-grid">
                            <div class="stat-card">
                                <h3>Articles Processed</h3>
                                <div class="stat-value" id="articlesCount">0</div>
                            </div>
                            <div class="stat-card">
                                <h3>Entities Extracted</h3>
                                <div class="stat-value" id="entitiesCount">0</div>
                            </div>
                            <div class="stat-card">
                                <h3>Active Workflows</h3>
                                <div class="stat-value" id="workflowsCount">0</div>
                            </div>
                            <div class="stat-card">
                                <h3>Sources Analyzed</h3>
                                <div class="stat-value" id="sourcesCount">0</div>
                            </div>
                        </div>
                        
                        <div class="recent-activity">
                            <h3>Recent Activity</h3>
                            <div id="activityList" class="activity-list">
                                <!-- Activity items will be populated here -->
                            </div>
                        </div>
                    </div>

                    <!-- Ingestion Panel -->
                    <div id="ingestPanel" class="content-panel">
                        <div class="ingestion-tabs">
                            <button class="tab-btn active" data-tab="single">Single Article</button>
                            <button class="tab-btn" data-tab="batch">Batch/Feed</button>
                            <button class="tab-btn" data-tab="documents">Documents</button>
                        </div>

                        <div class="tab-content">
                            <div id="singleTab" class="tab-panel active">
                                <h3>Ingest Single Article</h3>
                                <form id="singleArticleForm">
                                    <input type="url" id="articleUrl" placeholder="Article URL" required>
                                    <textarea id="articleMetadata" placeholder="Additional metadata (JSON format)"></textarea>
                                    <button type="submit">Ingest Article</button>
                                </form>
                            </div>

                            <div id="batchTab" class="tab-panel">
                                <h3>Batch Ingest from Feed</h3>
                                <form id="batchIngestForm">
                                    <input type="url" id="feedUrl" placeholder="RSS/JSON Feed URL" required>
                                    <input type="number" id="maxArticles" placeholder="Max Articles (default: 50)" min="1" max="1000">
                                    <textarea id="batchFilters" placeholder="Filters (JSON format)"></textarea>
                                    <button type="submit">Ingest Feed</button>
                                </form>
                            </div>

                            <div id="documentsTab" class="tab-panel">
                                <h3>Upload Document Collection</h3>
                                <div id="documentDropZone" class="drop-zone">
                                    <p>Drop documents here or click to select</p>
                                    <input type="file" id="documentFiles" multiple accept=".pdf,.txt,.doc,.docx,.html">
                                </div>
                                <div id="documentList" class="document-list"></div>
                                <button id="uploadDocuments" disabled>Upload Documents</button>
                            </div>
                        </div>
                    </div>

                    <!-- Timeline Panel -->
                    <div id="timelinePanel" class="content-panel">
                        <div class="timeline-controls">
                            <input type="text" id="timelineQuery" placeholder="Search query for timeline">
                            <input type="date" id="timelineStartDate">
                            <input type="date" id="timelineEndDate">
                            <select id="timelineGranularity">
                                <option value="day">Daily</option>
                                <option value="week">Weekly</option>
                                <option value="month">Monthly</option>
                            </select>
                            <button id="generateTimelineBtn">Generate Timeline</button>
                        </div>
                        <div id="timelineVisualization" class="timeline-viz">
                            <!-- Timeline visualization will be rendered here -->
                        </div>
                    </div>

                    <!-- Analysis Panel -->
                    <div id="analyzePanel" class="content-panel">
                        <div class="analysis-tools">
                            <div class="tool-section">
                                <h3>Cross-Document Analysis</h3>
                                <input type="text" id="conflictTopic" placeholder="Topic to analyze for conflicts">
                                <button id="findConflictsBtn">Find Conflicting Reports</button>
                            </div>
                            
                            <div class="tool-section">
                                <h3>Information Flow Tracing</h3>
                                <input type="text" id="claimToTrace" placeholder="Claim to trace">
                                <button id="traceFlowBtn">Trace Information Flow</button>
                            </div>
                        </div>
                        <div id="analysisResults" class="analysis-results">
                            <!-- Analysis results will be displayed here -->
                        </div>
                    </div>

                    <!-- Other panels (entities, search, export) would be implemented similarly -->
                </div>
            </div>
        `;
    }

    _initializeComponents() {
        // Initialize individual UI components
        this.components.set('stats', new StatsComponent('#statsGrid'));
        this.components.set('timeline', new TimelineComponent('#timelineVisualization'));
        this.components.set('entities', new EntityGraphComponent('#entityGraph'));
        this.components.set('ingestion', new IngestionWizardComponent('#ingestPanel'));
        
        // Update user type when changed
        document.getElementById('userTypeSelector').addEventListener('change', (e) => {
            this.client.userType = e.target.value;
            this._updateUIForUserType(e.target.value);
        });
    }

    _setupEventListeners() {
        // Navigation
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this._switchView(e.target.dataset.view);
            });
        });

        // Single article ingestion
        document.getElementById('singleArticleForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            await this._handleSingleArticleIngest();
        });

        // Batch ingestion
        document.getElementById('batchIngestForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            await this._handleBatchIngest();
        });

        // Timeline generation
        document.getElementById('generateTimelineBtn').addEventListener('click', async () => {
            await this._handleTimelineGeneration();
        });

        // Analysis tools
        document.getElementById('findConflictsBtn').addEventListener('click', async () => {
            await this._handleConflictAnalysis();
        });

        document.getElementById('traceFlowBtn').addEventListener('click', async () => {
            await this._handleInformationFlowTracing();
        });
    }

    _switchView(viewName) {
        // Update navigation
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === viewName);
        });

        // Update content panels
        document.querySelectorAll('.content-panel').forEach(panel => {
            panel.classList.toggle('active', panel.id === `${viewName}Panel`);
        });

        this.activeViews.clear();
        this.activeViews.add(viewName);
    }

    _updateUIForUserType(userType) {
        // Customize UI based on user type
        document.body.className = `user-type-${userType}`;
        
        // Show/hide features based on user type
        const features = {
            'data_scientist': ['stats', 'timeline', 'export'],
            'historian': ['timeline', 'entities', 'search'],
            'lawyer': ['search', 'analyze', 'export']
        };

        // Implementation would customize UI based on user needs
    }

    async _handleSingleArticleIngest() {
        const url = document.getElementById('articleUrl').value;
        const metadataText = document.getElementById('articleMetadata').value;
        
        let metadata = {};
        try {
            if (metadataText.trim()) {
                metadata = JSON.parse(metadataText);
            }
        } catch (e) {
            alert('Invalid metadata JSON');
            return;
        }

        try {
            const result = await this.client.ingestNewsArticle(url, metadata);
            this._showNotification('Article ingested successfully', 'success');
            this._updateStats();
        } catch (error) {
            this._showNotification('Failed to ingest article: ' + error.message, 'error');
        }
    }

    async _handleBatchIngest() {
        const feedUrl = document.getElementById('feedUrl').value;
        const maxArticles = parseInt(document.getElementById('maxArticles').value) || 50;
        const filtersText = document.getElementById('batchFilters').value;
        
        let filters = {};
        try {
            if (filtersText.trim()) {
                filters = JSON.parse(filtersText);
            }
        } catch (e) {
            alert('Invalid filters JSON');
            return;
        }

        try {
            const result = await this.client.ingestNewsFeed(feedUrl, { filters, maxArticles });
            this._showNotification(`Batch ingestion completed: ${result.successful_ingests} articles processed`, 'success');
            this._updateStats();
        } catch (error) {
            this._showNotification('Failed to ingest feed: ' + error.message, 'error');
        }
    }

    async _handleTimelineGeneration() {
        const query = document.getElementById('timelineQuery').value;
        const startDate = new Date(document.getElementById('timelineStartDate').value);
        const endDate = new Date(document.getElementById('timelineEndDate').value);
        const granularity = document.getElementById('timelineGranularity').value;

        if (!query || !startDate || !endDate) {
            alert('Please fill in all timeline parameters');
            return;
        }

        try {
            const result = await this.client.generateTimeline(
                query, 
                { start: startDate, end: endDate }, 
                { granularity }
            );
            
            this.components.get('timeline').renderTimeline(result);
            this._showNotification('Timeline generated successfully', 'success');
        } catch (error) {
            this._showNotification('Failed to generate timeline: ' + error.message, 'error');
        }
    }

    async _handleConflictAnalysis() {
        const topic = document.getElementById('conflictTopic').value;
        
        if (!topic) {
            alert('Please enter a topic to analyze');
            return;
        }

        try {
            const result = await this.client.findConflictingReports(topic);
            this._displayAnalysisResults('conflicts', result);
            this._showNotification('Conflict analysis completed', 'success');
        } catch (error) {
            this._showNotification('Failed to analyze conflicts: ' + error.message, 'error');
        }
    }

    async _handleInformationFlowTracing() {
        const claim = document.getElementById('claimToTrace').value;
        
        if (!claim) {
            alert('Please enter a claim to trace');
            return;
        }

        try {
            const result = await this.client.traceInformationFlow(claim);
            this._displayAnalysisResults('information_flow', result);
            this._showNotification('Information flow tracing completed', 'success');
        } catch (error) {
            this._showNotification('Failed to trace information flow: ' + error.message, 'error');
        }
    }

    _displayAnalysisResults(type, results) {
        const resultsContainer = document.getElementById('analysisResults');
        
        // Implementation would render results based on type
        // This is a simplified version
        resultsContainer.innerHTML = `
            <h3>Analysis Results: ${type}</h3>
            <pre>${JSON.stringify(results, null, 2)}</pre>
        `;
    }

    _showNotification(message, type = 'info') {
        // Create and show notification
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 5000);
    }

    async _updateStats() {
        try {
            const stats = await this.client.getStats();
            document.getElementById('articlesCount').textContent = stats.articles_processed || 0;
            document.getElementById('entitiesCount').textContent = stats.entities_extracted || 0;
            document.getElementById('workflowsCount').textContent = stats.active_workflows || 0;
            document.getElementById('sourcesCount').textContent = stats.sources_analyzed || 0;
        } catch (error) {
            console.error('Failed to update stats:', error);
        }
    }
}

// Additional component classes would be implemented here
class TimelineComponent {
    constructor(selector) {
        this.container = document.querySelector(selector);
    }

    renderTimeline(data) {
        // Implementation would use D3.js or similar for visualization
        this.container.innerHTML = `<p>Timeline for: ${data.query}</p>`;
    }
}

class EntityGraphComponent {
    constructor(selector) {
        this.container = document.querySelector(selector);
    }

    renderGraph(data) {
        // Implementation would render interactive network graph
        this.container.innerHTML = `<p>Entity Graph: ${data.total_entities} entities</p>`;
    }
}

class IngestionWizardComponent {
    constructor(selector) {
        this.container = document.querySelector(selector);
    }
}

class StatsComponent {
    constructor(selector) {
        this.container = document.querySelector(selector);
    }
}

// Export for use in browser or Node.js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { NewsAnalysisClient, NewsAnalysisDashboard, NewsAnalysisError };
}
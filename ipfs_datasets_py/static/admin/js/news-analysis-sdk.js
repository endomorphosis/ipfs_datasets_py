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

// ============== EXTENDED FUNCTIONALITY ==============

/**
 * Website Crawling Component
 */
class WebsiteCrawlingComponent {
    constructor(selector, client) {
        this.container = document.querySelector(selector);
        this.client = client;
        this.progressBar = null;
        this.progressLog = null;
        this.currentCrawlId = null;
        
        this.initializeComponent();
    }

    initializeComponent() {
        // Initialize progress tracking elements
        this.progressBar = document.getElementById('crawlProgressFill');
        this.progressLog = document.getElementById('crawlLog');
        
        // Bind form submission
        const form = document.getElementById('websiteCrawlForm');
        if (form) {
            form.addEventListener('submit', this.handleCrawlSubmission.bind(this));
        }
    }

    async handleCrawlSubmission(event) {
        event.preventDefault();
        
        const formData = new FormData(event.target);
        const crawlConfig = {
            url: formData.get('websiteUrl'),
            maxPages: parseInt(formData.get('maxPages')) || 50,
            maxDepth: parseInt(formData.get('maxDepth')) || 3,
            includePatterns: this.parsePatterns(formData.get('includePatterns')),
            excludePatterns: this.parsePatterns(formData.get('excludePatterns')),
            contentTypes: this.getSelectedContentTypes(),
            metadata: this.parseJSON(formData.get('crawlMetadata')) || {}
        };

        try {
            this.showProgressSection();
            this.currentCrawlId = await this.client.crawlWebsite(crawlConfig);
            this.startProgressMonitoring();
        } catch (error) {
            console.error('Website crawl failed:', error);
            this.logError('Crawl failed: ' + error.message);
        }
    }

    parsePatterns(patternsString) {
        return patternsString ? patternsString.split(',').map(p => p.trim()).filter(p => p.length > 0) : [];
    }

    getSelectedContentTypes() {
        const checkboxes = document.querySelectorAll('input[name="contentTypes"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    }

    parseJSON(jsonString) {
        try {
            return jsonString ? JSON.parse(jsonString) : null;
        } catch (e) {
            return null;
        }
    }

    showProgressSection() {
        const progressSection = document.getElementById('crawlProgress');
        if (progressSection) {
            progressSection.style.display = 'block';
        }
    }

    startProgressMonitoring() {
        if (!this.currentCrawlId) return;

        const pollInterval = setInterval(async () => {
            try {
                const status = await this.client.getCrawlStatus(this.currentCrawlId);
                this.updateProgress(status);
                
                if (status.status === 'completed' || status.status === 'failed') {
                    clearInterval(pollInterval);
                    this.handleCrawlComplete(status);
                }
            } catch (error) {
                console.error('Error monitoring crawl progress:', error);
                clearInterval(pollInterval);
            }
        }, 2000);
    }

    updateProgress(status) {
        const percentage = (status.crawledPages / status.totalPages) * 100;
        if (this.progressBar) {
            this.progressBar.style.width = `${percentage}%`;
        }
        
        document.getElementById('crawledPages').textContent = status.crawledPages;
        document.getElementById('totalPages').textContent = status.totalPages;
        
        if (status.lastLog) {
            this.addLogEntry(status.lastLog);
        }
    }

    addLogEntry(logEntry) {
        if (!this.progressLog) return;
        
        const entryElement = document.createElement('div');
        entryElement.className = `log-entry ${logEntry.level || 'info'}`;
        entryElement.textContent = `${new Date().toLocaleTimeString()}: ${logEntry.message}`;
        
        this.progressLog.appendChild(entryElement);
        this.progressLog.scrollTop = this.progressLog.scrollHeight;
    }

    logError(message) {
        this.addLogEntry({ level: 'error', message });
    }

    handleCrawlComplete(status) {
        this.addLogEntry({ 
            level: status.status === 'completed' ? 'success' : 'error', 
            message: `Crawl ${status.status}. ${status.crawledPages} pages processed.`
        });
        
        if (status.status === 'completed') {
            this.displayCrawlResults(status.results);
        }
    }

    displayCrawlResults(results) {
        const resultsDiv = document.getElementById('websiteCrawlResults');
        if (!resultsDiv) return;
        
        const resultSummary = document.createElement('div');
        resultSummary.className = 'crawl-summary';
        resultSummary.innerHTML = `
            <h4>Crawl Complete</h4>
            <p>Successfully crawled ${results.totalPages} pages</p>
            <p>Extracted ${results.totalEntities} entities</p>
            <p>Found ${results.totalRelationships} relationships</p>
        `;
        
        resultsDiv.appendChild(resultSummary);
    }
}

/**
 * GraphRAG Query Component
 */
class GraphRAGQueryComponent {
    constructor(selector, client) {
        this.container = document.querySelector(selector);
        this.client = client;
        this.currentQueryType = 'semantic';
        
        this.initializeComponent();
    }

    initializeComponent() {
        // Initialize query type toggles
        const typeButtons = document.querySelectorAll('.type-btn');
        typeButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.switchQueryType(e.target.dataset.type);
            });
        });

        // Initialize query execution
        const executeBtn = document.getElementById('executeQueryBtn');
        if (executeBtn) {
            executeBtn.addEventListener('click', this.executeQuery.bind(this));
        }

        // Initialize other buttons
        this.initializeQueryActions();
    }

    switchQueryType(type) {
        this.currentQueryType = type;
        
        // Update button states
        document.querySelectorAll('.type-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.type === type);
        });
        
        // Show/hide appropriate query tabs
        document.querySelectorAll('.query-tab').forEach(tab => {
            tab.classList.toggle('active', tab.id === `${type}QueryTab`);
        });
    }

    initializeQueryActions() {
        const actions = {
            'saveQueryBtn': this.saveQuery.bind(this),
            'loadQueryBtn': this.loadQuery.bind(this),
            'clearQueryBtn': this.clearQuery.bind(this)
        };

        Object.entries(actions).forEach(([btnId, handler]) => {
            const btn = document.getElementById(btnId);
            if (btn) {
                btn.addEventListener('click', handler);
            }
        });
    }

    async executeQuery() {
        const queryData = this.getQueryData();
        if (!queryData.query) {
            alert('Please enter a query');
            return;
        }

        try {
            this.showLoadingState();
            const results = await this.client.executeGraphRAGQuery(queryData);
            this.displayQueryResults(results);
        } catch (error) {
            console.error('Query execution failed:', error);
            this.showError('Query failed: ' + error.message);
        } finally {
            this.hideLoadingState();
        }
    }

    getQueryData() {
        const baseData = {
            type: this.currentQueryType,
            userType: this.client.userType
        };

        switch (this.currentQueryType) {
            case 'semantic':
                return {
                    ...baseData,
                    query: document.getElementById('semanticQuery')?.value,
                    context: document.getElementById('semanticContext')?.value,
                    limit: parseInt(document.getElementById('resultLimit')?.value) || 10
                };
            case 'entity':
                return {
                    ...baseData,
                    query: document.getElementById('entityQueryInput')?.value,
                    entityTypes: this.getSelectedOptions('entityTypes'),
                    hops: parseInt(document.getElementById('entityHops')?.value) || 0
                };
            case 'relationship':
                return {
                    ...baseData,
                    sourceEntity: document.getElementById('sourceEntity')?.value,
                    relationshipType: document.getElementById('relationshipType')?.value,
                    targetEntity: document.getElementById('targetEntity')?.value,
                    minStrength: parseInt(document.getElementById('relationshipStrength')?.value) || 0
                };
            case 'temporal':
                return {
                    ...baseData,
                    query: document.getElementById('temporalQuery')?.value,
                    startDate: document.getElementById('timeStartDate')?.value,
                    endDate: document.getElementById('timeEndDate')?.value,
                    granularity: document.getElementById('timeGranularity')?.value
                };
            case 'cross_doc':
                return {
                    ...baseData,
                    query: document.getElementById('crossDocQuery')?.value,
                    analysisType: document.getElementById('analysisType')?.value,
                    sources: this.parseSources(document.getElementById('documentSources')?.value)
                };
            default:
                return baseData;
        }
    }

    getSelectedOptions(selectId) {
        const select = document.getElementById(selectId);
        if (!select) return [];
        return Array.from(select.selectedOptions).map(option => option.value);
    }

    parseSources(sourcesString) {
        return sourcesString ? sourcesString.split(',').map(s => s.trim()).filter(s => s.length > 0) : [];
    }

    displayQueryResults(results) {
        const resultsContent = document.getElementById('queryResultsContent');
        const resultsPlaceholder = document.querySelector('.results-placeholder');
        
        if (resultsPlaceholder) {
            resultsPlaceholder.style.display = 'none';
        }
        
        if (resultsContent) {
            resultsContent.style.display = 'block';
            resultsContent.innerHTML = this.formatResults(results);
        }
    }

    formatResults(results) {
        if (!results || !results.results) {
            return '<p>No results found.</p>';
        }

        let html = `<div class="query-results-summary">
            <h4>Found ${results.results.length} results</h4>
            <p>Query executed in ${results.processingTime}ms</p>
        </div>`;

        results.results.forEach((result, index) => {
            html += `
                <div class="result-item">
                    <h5>Result ${index + 1}</h5>
                    <p><strong>Source:</strong> ${result.source || 'Unknown'}</p>
                    <p><strong>Relevance:</strong> ${result.relevanceScore || 'N/A'}</p>
                    <div class="result-content">${result.content || result.snippet || 'No content available'}</div>
                </div>
            `;
        });

        return html;
    }

    showLoadingState() {
        const executeBtn = document.getElementById('executeQueryBtn');
        if (executeBtn) {
            executeBtn.disabled = true;
            executeBtn.innerHTML = '⏳ Executing...';
        }
    }

    hideLoadingState() {
        const executeBtn = document.getElementById('executeQueryBtn');
        if (executeBtn) {
            executeBtn.disabled = false;
            executeBtn.innerHTML = '🔍 Execute Query';
        }
    }

    showError(message) {
        const resultsContent = document.getElementById('queryResultsContent');
        if (resultsContent) {
            resultsContent.innerHTML = `<div class="error-message">${message}</div>`;
            resultsContent.style.display = 'block';
        }
    }

    saveQuery() {
        const queryData = this.getQueryData();
        localStorage.setItem('saved-graphrag-query', JSON.stringify(queryData));
        alert('Query saved locally');
    }

    loadQuery() {
        const saved = localStorage.getItem('saved-graphrag-query');
        if (saved) {
            const queryData = JSON.parse(saved);
            this.loadQueryData(queryData);
            alert('Query loaded');
        }
    }

    clearQuery() {
        // Clear all query inputs based on current type
        document.querySelectorAll('.query-tab.active input, .query-tab.active textarea').forEach(input => {
            input.value = '';
        });
    }

    loadQueryData(data) {
        // Load query data back into form
        this.switchQueryType(data.type);
        
        // Fill in the appropriate fields based on query type
        Object.entries(data).forEach(([key, value]) => {
            const element = document.getElementById(key);
            if (element) {
                element.value = value;
            }
        });
    }
}

/**
 * Graph Explorer Component
 */
class GraphExplorerComponent {
    constructor(selector, client) {
        this.container = document.querySelector(selector);
        this.client = client;
        this.graphData = null;
        this.graphInstance = null;
        
        this.initializeComponent();
    }

    initializeComponent() {
        // Initialize control actions
        const actions = {
            'refreshGraphBtn': this.refreshGraph.bind(this),
            'centerGraphBtn': this.centerGraph.bind(this),
            'findPathBtn': this.findPath.bind(this),
            'clusterGraphBtn': this.detectCommunities.bind(this),
            'exportGraphBtn': this.exportGraph.bind(this),
            'loadGraphBtn': this.loadGraphData.bind(this),
            'findShortestPath': this.findShortestPath.bind(this)
        };

        Object.entries(actions).forEach(([btnId, handler]) => {
            const btn = document.getElementById(btnId);
            if (btn) {
                btn.addEventListener('click', handler);
            }
        });

        // Initialize filter change handlers
        ['graphLayout', 'nodeFilter', 'relationshipFilter', 'nodeSize', 'edgeWeight'].forEach(id => {
            const element = document.getElementById(id);
            if (element) {
                element.addEventListener('change', this.handleFilterChange.bind(this));
            }
        });

        // Initialize time slider
        const timeSlider = document.getElementById('timeRangeSlider');
        if (timeSlider) {
            timeSlider.addEventListener('input', this.handleTimeRangeChange.bind(this));
        }
    }

    async loadGraphData() {
        try {
            this.showGraphLoading();
            const graphData = await this.client.getKnowledgeGraph();
            this.graphData = graphData;
            this.renderGraph();
            this.updateGraphStats();
        } catch (error) {
            console.error('Failed to load graph data:', error);
            this.showGraphError('Failed to load graph data: ' + error.message);
        }
    }

    renderGraph() {
        if (!this.graphData) return;

        const graphContainer = document.getElementById('knowledgeGraph');
        if (!graphContainer) return;

        // Clear placeholder
        graphContainer.innerHTML = '<div id="graph-svg"></div>';

        // Initialize D3 force simulation
        this.initializeD3Graph();
    }

    initializeD3Graph() {
        const width = 800;
        const height = 600;

        const svg = d3.select('#graph-svg')
            .append('svg')
            .attr('width', width)
            .attr('height', height);

        const simulation = d3.forceSimulation(this.graphData.nodes)
            .force('link', d3.forceLink(this.graphData.links).id(d => d.id))
            .force('charge', d3.forceManyBody().strength(-300))
            .force('center', d3.forceCenter(width / 2, height / 2));

        // Add links
        const link = svg.append('g')
            .selectAll('line')
            .data(this.graphData.links)
            .enter().append('line')
            .attr('stroke', '#999')
            .attr('stroke-opacity', 0.6);

        // Add nodes
        const node = svg.append('g')
            .selectAll('circle')
            .data(this.graphData.nodes)
            .enter().append('circle')
            .attr('r', 5)
            .attr('fill', d => this.getNodeColor(d.type))
            .call(d3.drag()
                .on('start', this.dragstarted)
                .on('drag', this.dragged)
                .on('end', this.dragended));

        // Add labels
        const label = svg.append('g')
            .selectAll('text')
            .data(this.graphData.nodes)
            .enter().append('text')
            .text(d => d.name)
            .attr('font-size', 10)
            .attr('dx', 8)
            .attr('dy', 3);

        // Update positions on tick
        simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);

            node
                .attr('cx', d => d.x)
                .attr('cy', d => d.y);

            label
                .attr('x', d => d.x)
                .attr('y', d => d.y);
        });

        this.graphInstance = { svg, simulation, nodes: node, links: link };
    }

    getNodeColor(type) {
        const colors = {
            'PERSON': '#ff6b6b',
            'ORG': '#4ecdc4',
            'GPE': '#45b7d1',
            'EVENT': '#f9ca24',
            'TOPIC': '#a55eea'
        };
        return colors[type] || '#95a5a6';
    }

    handleFilterChange() {
        if (this.graphData) {
            this.applyFilters();
            this.renderGraph();
        }
    }

    handleTimeRangeChange(event) {
        const value = event.target.value;
        // Update time labels and apply temporal filtering
        this.applyTemporalFilter(value);
    }

    applyFilters() {
        const nodeTypes = this.getSelectedOptions('nodeFilter');
        const relationshipTypes = this.getSelectedOptions('relationshipFilter');

        if (nodeTypes.length > 0) {
            this.graphData.nodes = this.graphData.nodes.filter(node => 
                nodeTypes.includes(node.type)
            );
        }

        if (relationshipTypes.length > 0) {
            this.graphData.links = this.graphData.links.filter(link => 
                relationshipTypes.includes(link.type)
            );
        }
    }

    updateGraphStats() {
        if (!this.graphData) return;

        document.getElementById('nodeCount').textContent = this.graphData.nodes.length;
        document.getElementById('edgeCount').textContent = this.graphData.links.length;
        
        // Calculate density
        const n = this.graphData.nodes.length;
        const maxEdges = n * (n - 1) / 2;
        const density = maxEdges > 0 ? (this.graphData.links.length / maxEdges * 100).toFixed(1) : 0;
        document.getElementById('graphDensity').textContent = density + '%';
    }

    async refreshGraph() {
        await this.loadGraphData();
    }

    centerGraph() {
        if (this.graphInstance && this.graphInstance.simulation) {
            this.graphInstance.simulation.restart();
        }
    }

    findPath() {
        // Toggle path finder mode
        alert('Click on two nodes to find the shortest path between them');
    }

    async detectCommunities() {
        try {
            const communities = await this.client.detectCommunities(this.graphData);
            document.getElementById('communityCount').textContent = communities.length;
            this.highlightCommunities(communities);
        } catch (error) {
            console.error('Community detection failed:', error);
        }
    }

    exportGraph() {
        const dataStr = JSON.stringify(this.graphData, null, 2);
        const dataBlob = new Blob([dataStr], {type: 'application/json'});
        const url = URL.createObjectURL(dataBlob);
        
        const link = document.createElement('a');
        link.href = url;
        link.download = 'knowledge-graph.json';
        link.click();
        
        URL.revokeObjectURL(url);
    }

    async findShortestPath() {
        const startNode = document.getElementById('pathStart').value;
        const endNode = document.getElementById('pathEnd').value;
        
        if (!startNode || !endNode) {
            alert('Please enter both start and end nodes');
            return;
        }

        try {
            const path = await this.client.findShortestPath(startNode, endNode);
            this.displayPath(path);
        } catch (error) {
            console.error('Path finding failed:', error);
        }
    }

    displayPath(path) {
        const pathResults = document.getElementById('pathResults');
        if (pathResults && path) {
            pathResults.innerHTML = `
                <div class="path-found">
                    <strong>Path found (${path.length} steps):</strong><br>
                    ${path.join(' → ')}
                </div>
            `;
        }
    }

    showGraphLoading() {
        const graph = document.getElementById('knowledgeGraph');
        if (graph) {
            graph.innerHTML = '<div class="loading">Loading graph data...</div>';
        }
    }

    showGraphError(message) {
        const graph = document.getElementById('knowledgeGraph');
        if (graph) {
            graph.innerHTML = `<div class="error">${message}</div>`;
        }
    }

    dragstarted(event, d) {
        if (!event.active) this.graphInstance.simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }

    dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }

    dragended(event, d) {
        if (!event.active) this.graphInstance.simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }
}

// Add new methods to NewsAnalysisClient for extended functionality
NewsAnalysisClient.prototype.crawlWebsite = async function(crawlConfig) {
    const response = await this._makeRequest('/api/news/crawl/website', {
        method: 'POST',
        body: JSON.stringify(crawlConfig)
    });
    return response.crawlId;
};

NewsAnalysisClient.prototype.getCrawlStatus = async function(crawlId) {
    return await this._makeRequest(`/api/news/crawl/status/${crawlId}`);
};

NewsAnalysisClient.prototype.executeGraphRAGQuery = async function(queryData) {
    return await this._makeRequest('/api/news/graphrag/query', {
        method: 'POST',
        body: JSON.stringify(queryData)
    });
};

NewsAnalysisClient.prototype.getKnowledgeGraph = async function(filters = {}) {
    return await this._makeRequest('/api/news/graph/data', {
        method: 'POST',
        body: JSON.stringify(filters)
    });
};

NewsAnalysisClient.prototype.detectCommunities = async function(graphData) {
    return await this._makeRequest('/api/news/graph/communities', {
        method: 'POST',
        body: JSON.stringify({ graphData })
    });
};

NewsAnalysisClient.prototype.findShortestPath = async function(startNode, endNode) {
    return await this._makeRequest('/api/news/graph/path', {
        method: 'POST',
        body: JSON.stringify({ startNode, endNode })
    });
};

// Export for use in browser or Node.js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { 
        NewsAnalysisClient, 
        NewsAnalysisDashboard, 
        NewsAnalysisError,
        WebsiteCrawlingComponent,
        GraphRAGQueryComponent,
        GraphExplorerComponent
    };
}
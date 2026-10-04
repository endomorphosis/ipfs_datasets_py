/**
 * MCP Dashboard Main JavaScript
 * Handles navigation, API calls, and user interactions
 */

class MCPDashboard {
    constructor() {
        this.currentSection = 'dataset-creation';
        this.apiClient = new MCPApiClient();
        this.init();
    }

    init() {
        this.setupNavigation();
        this.setupEventListeners();
        this.showSection(this.currentSection);
        this.updateSystemStatus();
        
        // Update status every 30 seconds
        setInterval(() => {
            this.updateSystemStatus();
        }, 30000);
    }

    setupNavigation() {
        const navLinks = document.querySelectorAll('.nav-link');
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const sectionId = link.getAttribute('data-section');
                if (sectionId) {
                    this.showSection(sectionId);
                    this.setActiveNavLink(link);
                }
            });
        });
    }

    setupEventListeners() {
        // Dataset Creation
        const createDatasetBtn = document.getElementById('create-dataset-btn');
        if (createDatasetBtn) {
            createDatasetBtn.addEventListener('click', () => this.handleDatasetCreation());
        }

        const loadHuggingFaceBtn = document.getElementById('load-huggingface-btn');
        if (loadHuggingFaceBtn) {
            loadHuggingFaceBtn.addEventListener('click', () => this.handleHuggingFaceLoad());
        }

        const loadIPFSBtn = document.getElementById('load-ipfs-btn');
        if (loadIPFSBtn) {
            loadIPFSBtn.addEventListener('click', () => this.handleIPFSLoad());
        }

        const uploadFileBtn = document.getElementById('upload-file-btn');
        if (uploadFileBtn) {
            uploadFileBtn.addEventListener('click', () => this.handleFileUpload());
        }

        // Data Transformation
        const processDataBtn = document.getElementById('process-data-btn');
        if (processDataBtn) {
            processDataBtn.addEventListener('click', () => this.handleDataProcessing());
        }

        const generateEmbeddingsBtn = document.getElementById('generate-embeddings-btn');
        if (generateEmbeddingsBtn) {
            generateEmbeddingsBtn.addEventListener('click', () => this.handleEmbeddingGeneration());
        }

        const classifyContentBtn = document.getElementById('classify-content-btn');
        if (classifyContentBtn) {
            classifyContentBtn.addEventListener('click', () => this.handleContentClassification());
        }

        const clusterDataBtn = document.getElementById('cluster-data-btn');
        if (clusterDataBtn) {
            clusterDataBtn.addEventListener('click', () => this.handleDataClustering());
        }

        // Data Search
        const searchVectorBtn = document.getElementById('search-vector-btn');
        if (searchVectorBtn) {
            searchVectorBtn.addEventListener('click', () => this.handleVectorSearch());
        }

        const queryGraphBtn = document.getElementById('query-graph-btn');
        if (queryGraphBtn) {
            queryGraphBtn.addEventListener('click', () => this.handleGraphQuery());
        }

        const searchArchiveBtn = document.getElementById('search-archive-btn');
        if (searchArchiveBtn) {
            searchArchiveBtn.addEventListener('click', () => this.handleArchiveSearch());
        }

        // Visualization
        const generateChartsBtn = document.getElementById('generate-charts-btn');
        if (generateChartsBtn) {
            generateChartsBtn.addEventListener('click', () => this.handleChartGeneration());
        }

        const runAnalyticsBtn = document.getElementById('run-analytics-btn');
        if (runAnalyticsBtn) {
            runAnalyticsBtn.addEventListener('click', () => this.handleAnalytics());
        }

        const assessQualityBtn = document.getElementById('assess-quality-btn');
        if (assessQualityBtn) {
            assessQualityBtn.addEventListener('click', () => this.handleQualityAssessment());
        }

        const exportDataBtn = document.getElementById('export-data-btn');
        if (exportDataBtn) {
            exportDataBtn.addEventListener('click', () => this.handleDataExport());
        }

        // System Management
        const runTestsBtn = document.getElementById('run-tests-btn');
        if (runTestsBtn) {
            runTestsBtn.addEventListener('click', () => this.handleTestExecution());
        }

        const manageWorkflowsBtn = document.getElementById('manage-workflows-btn');
        if (manageWorkflowsBtn) {
            manageWorkflowsBtn.addEventListener('click', () => this.handleWorkflowManagement());
        }

        const optimizeSystemBtn = document.getElementById('optimize-system-btn');
        if (optimizeSystemBtn) {
            optimizeSystemBtn.addEventListener('click', () => this.handleSystemOptimization());
        }

        const monitorHealthBtn = document.getElementById('monitor-health-btn');
        if (monitorHealthBtn) {
            monitorHealthBtn.addEventListener('click', () => this.handleHealthMonitoring());
        }
    }

    showSection(sectionId) {
        // Hide all sections
        const sections = document.querySelectorAll('.content-section');
        sections.forEach(section => {
            section.classList.remove('active');
        });

        // Show target section
        const targetSection = document.getElementById(sectionId);
        if (targetSection) {
            targetSection.classList.add('active');
            this.currentSection = sectionId;
        }
    }

    setActiveNavLink(activeLink) {
        // Remove active class from all nav links
        const navLinks = document.querySelectorAll('.nav-link');
        navLinks.forEach(link => {
            link.classList.remove('active');
        });

        // Add active class to clicked link
        activeLink.classList.add('active');
    }

    async updateSystemStatus() {
        try {
            const status = await this.apiClient.getSystemStatus();
            this.updateStatusCards(status);
        } catch (error) {
            console.error('Failed to update system status:', error);
        }
    }

    updateStatusCards(status) {
        const toolsCountElement = document.getElementById('tools-count');
        const activeTasksElement = document.getElementById('active-tasks');
        const datasetsProcessedElement = document.getElementById('datasets-processed');
        const systemHealthElement = document.getElementById('system-health');

        if (toolsCountElement) toolsCountElement.textContent = status.tools_count || '130+';
        if (activeTasksElement) activeTasksElement.textContent = status.active_tasks || '0';
        if (datasetsProcessedElement) datasetsProcessedElement.textContent = status.datasets_processed || '0';
        if (systemHealthElement) systemHealthElement.textContent = status.system_health || 'Healthy';
    }

    // Dataset Creation Handlers
    async handleDatasetCreation() {
        const resultPanel = document.getElementById('dataset-creation-results');
        this.showLoading(resultPanel, 'Creating dataset...');

        try {
            const result = await this.apiClient.createDataset({
                type: 'custom',
                name: 'New Dataset',
                description: 'Custom dataset creation'
            });
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleHuggingFaceLoad() {
        const datasetName = document.getElementById('huggingface-dataset')?.value;
        const resultPanel = document.getElementById('dataset-creation-results');
        
        if (!datasetName) {
            this.showError(resultPanel, 'Please enter a dataset name');
            return;
        }

        this.showLoading(resultPanel, 'Loading HuggingFace dataset...');

        try {
            const result = await this.apiClient.loadHuggingFaceDataset(datasetName);
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleIPFSLoad() {
        const cid = document.getElementById('ipfs-cid')?.value;
        const resultPanel = document.getElementById('dataset-creation-results');
        
        if (!cid) {
            this.showError(resultPanel, 'Please enter a CID');
            return;
        }

        this.showLoading(resultPanel, 'Loading from IPFS...');

        try {
            const result = await this.apiClient.loadFromIPFS(cid);
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleFileUpload() {
        const fileInput = document.getElementById('file-upload');
        const resultPanel = document.getElementById('dataset-creation-results');
        
        if (!fileInput?.files?.length) {
            this.showError(resultPanel, 'Please select a file');
            return;
        }

        this.showLoading(resultPanel, 'Uploading file...');

        try {
            const result = await this.apiClient.uploadFile(fileInput.files[0]);
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    // Data Transformation Handlers
    async handleDataProcessing() {
        const resultPanel = document.getElementById('transformation-results');
        this.showLoading(resultPanel, 'Processing data...');

        try {
            const result = await this.apiClient.processData({
                operation: 'filter',
                parameters: { column: 'text', condition: 'length > 100' }
            });
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleEmbeddingGeneration() {
        const resultPanel = document.getElementById('transformation-results');
        this.showLoading(resultPanel, 'Generating embeddings...');

        try {
            const result = await this.apiClient.generateEmbeddings({
                model: 'sentence-transformers/all-MiniLM-L6-v2',
                field: 'text'
            });
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleContentClassification() {
        const resultPanel = document.getElementById('transformation-results');
        this.showLoading(resultPanel, 'Classifying content...');

        try {
            const result = await this.apiClient.classifyContent({
                classifier: 'automatic',
                confidence_threshold: 0.8
            });
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleDataClustering() {
        const resultPanel = document.getElementById('transformation-results');
        this.showLoading(resultPanel, 'Clustering data...');

        try {
            const result = await this.apiClient.clusterData({
                algorithm: 'kmeans',
                n_clusters: 5
            });
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    // Data Search Handlers
    async handleVectorSearch() {
        const query = document.getElementById('search-query')?.value;
        const resultPanel = document.getElementById('search-results');
        
        if (!query) {
            this.showError(resultPanel, 'Please enter a search query');
            return;
        }

        this.showLoading(resultPanel, 'Searching vectors...');

        try {
            const result = await this.apiClient.searchVectors(query);
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleGraphQuery() {
        const query = document.getElementById('graph-query')?.value;
        const resultPanel = document.getElementById('search-results');
        
        if (!query) {
            this.showError(resultPanel, 'Please enter a graph query');
            return;
        }

        this.showLoading(resultPanel, 'Querying knowledge graph...');

        try {
            const result = await this.apiClient.queryGraph(query);
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleArchiveSearch() {
        const url = document.getElementById('archive-url')?.value;
        const resultPanel = document.getElementById('search-results');
        
        if (!url) {
            this.showError(resultPanel, 'Please enter a URL');
            return;
        }

        this.showLoading(resultPanel, 'Searching archives...');

        try {
            const result = await this.apiClient.searchArchive(url);
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    // Visualization Handlers
    async handleChartGeneration() {
        const resultPanel = document.getElementById('visualization-results');
        this.showLoading(resultPanel, 'Generating charts...');

        try {
            const result = await this.apiClient.generateCharts({
                type: 'histogram',
                column: 'text_length'
            });
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleAnalytics() {
        const resultPanel = document.getElementById('visualization-results');
        this.showLoading(resultPanel, 'Running analytics...');

        try {
            const result = await this.apiClient.runAnalytics();
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleQualityAssessment() {
        const resultPanel = document.getElementById('visualization-results');
        this.showLoading(resultPanel, 'Assessing data quality...');

        try {
            const result = await this.apiClient.assessQuality();
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleDataExport() {
        const format = document.getElementById('export-format')?.value || 'parquet';
        const resultPanel = document.getElementById('visualization-results');
        this.showLoading(resultPanel, 'Exporting data...');

        try {
            const result = await this.apiClient.exportData(format);
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    // System Management Handlers
    async handleTestExecution() {
        const testType = document.getElementById('test-type')?.value || 'unit';
        const resultPanel = document.getElementById('management-results');
        this.showLoading(resultPanel, 'Running tests...');

        try {
            const result = await this.apiClient.runTests(testType);
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleWorkflowManagement() {
        const resultPanel = document.getElementById('management-results');
        this.showLoading(resultPanel, 'Managing workflows...');

        try {
            const result = await this.apiClient.manageWorkflows();
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleSystemOptimization() {
        const resultPanel = document.getElementById('management-results');
        this.showLoading(resultPanel, 'Optimizing system...');

        try {
            const result = await this.apiClient.optimizeSystem();
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    async handleHealthMonitoring() {
        const resultPanel = document.getElementById('management-results');
        this.showLoading(resultPanel, 'Monitoring system health...');

        try {
            const result = await this.apiClient.monitorHealth();
            this.showResults(resultPanel, result);
        } catch (error) {
            this.showError(resultPanel, error.message);
        }
    }

    // Utility methods
    showLoading(panel, message) {
        if (panel) {
            panel.innerHTML = `
                <div class="loading">
                    <div class="spinner"></div>
                    <span>${message}</span>
                </div>
            `;
        }
    }

    showResults(panel, result) {
        if (panel) {
            panel.innerHTML = `<pre>${JSON.stringify(result, null, 2)}</pre>`;
        }
    }

    showError(panel, error) {
        if (panel) {
            panel.innerHTML = `<pre style="color: #dc2626;">Error: ${error}</pre>`;
        }
    }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.mcpDashboard = new MCPDashboard();
});
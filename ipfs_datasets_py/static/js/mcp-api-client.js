/**
 * MCP API Client
 * Handles all API communication with the MCP server
 */

class MCPApiClient {
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
    }

    async makeRequest(endpoint, options = {}) {
        const url = `${this.baseUrl}/api/mcp${endpoint}`;
        const defaultOptions = {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
        };

        const finalOptions = { ...defaultOptions, ...options };

        try {
            const response = await fetch(url, finalOptions);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error('API request failed:', error);
            throw error;
        }
    }

    // System Status
    async getSystemStatus() {
        return this.makeRequest('/status');
    }

    // Dataset Creation
    async createDataset(params) {
        return this.makeRequest('/dataset/create', {
            method: 'POST',
            body: JSON.stringify(params)
        });
    }

    async loadHuggingFaceDataset(datasetName) {
        return this.makeRequest('/dataset/huggingface', {
            method: 'POST',
            body: JSON.stringify({ dataset_name: datasetName })
        });
    }

    async loadFromIPFS(cid) {
        return this.makeRequest('/dataset/ipfs', {
            method: 'POST',
            body: JSON.stringify({ cid: cid })
        });
    }

    async uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        
        return this.makeRequest('/dataset/upload', {
            method: 'POST',
            body: formData,
            headers: {} // Let browser set content-type for FormData
        });
    }

    // Data Transformation
    async processData(params) {
        return this.makeRequest('/transform/process', {
            method: 'POST',
            body: JSON.stringify(params)
        });
    }

    async generateEmbeddings(params) {
        return this.makeRequest('/transform/embeddings', {
            method: 'POST',
            body: JSON.stringify(params)
        });
    }

    async classifyContent(params) {
        return this.makeRequest('/transform/classify', {
            method: 'POST',
            body: JSON.stringify(params)
        });
    }

    async clusterData(params) {
        return this.makeRequest('/transform/cluster', {
            method: 'POST',
            body: JSON.stringify(params)
        });
    }

    // Data Search
    async searchVectors(query) {
        return this.makeRequest('/search/vector', {
            method: 'POST',
            body: JSON.stringify({ query: query })
        });
    }

    async queryGraph(query) {
        return this.makeRequest('/search/graph', {
            method: 'POST',
            body: JSON.stringify({ query: query })
        });
    }

    async searchArchive(url) {
        return this.makeRequest('/search/archive', {
            method: 'POST',
            body: JSON.stringify({ url: url })
        });
    }

    // Visualization
    async generateCharts(params) {
        return this.makeRequest('/visualize/charts', {
            method: 'POST',
            body: JSON.stringify(params)
        });
    }

    async runAnalytics() {
        return this.makeRequest('/visualize/analytics');
    }

    async assessQuality() {
        return this.makeRequest('/visualize/quality');
    }

    async exportData(format) {
        return this.makeRequest('/visualize/export', {
            method: 'POST',
            body: JSON.stringify({ format: format })
        });
    }

    // System Management
    async runTests(testType) {
        return this.makeRequest('/system/tests', {
            method: 'POST',
            body: JSON.stringify({ type: testType })
        });
    }

    async manageWorkflows() {
        return this.makeRequest('/system/workflows');
    }

    async optimizeSystem() {
        return this.makeRequest('/system/optimize', {
            method: 'POST'
        });
    }

    async monitorHealth() {
        return this.makeRequest('/system/health');
    }

    // Tools
    async listTools() {
        return this.makeRequest('/tools');
    }

    async executeTool(toolName, params) {
        return this.makeRequest('/tools/execute', {
            method: 'POST',
            body: JSON.stringify({
                tool: toolName,
                parameters: params
            })
        });
    }
}
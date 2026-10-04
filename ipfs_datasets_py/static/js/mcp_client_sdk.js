/**
 * MCP Client SDK for JavaScript/Browser
 * 
 * This SDK provides a consistent interface for calling MCP tools from the browser,
 * ensuring the same code paths are used regardless of access method (CLI, MCP server, or Python API).
 * 
 * Usage:
 *   const client = new MCPClient('/api/mcp');
 *   const result = await client.callTool('medical_research_scrapers', 'scrape_pubmed_medical_research', {
 *       query: 'COVID-19 treatment',
 *       max_results: 100
 *   });
 */

class MCPClient {
    /**
     * Create an MCP client instance.
     * @param {string} baseUrl - Base URL for MCP API endpoint (default: '/api/mcp')
     * @param {object} options - Additional options (timeout, headers, etc.)
     */
    constructor(baseUrl = '/api/mcp', options = {}) {
        this.baseUrl = baseUrl.replace(/\/$/, ''); // Remove trailing slash
        this.timeout = options.timeout || 30000; // 30 second default timeout
        this.headers = options.headers || {};
        this.requestId = 1;
    }

    /**
     * Call an MCP tool function.
     * @param {string} category - Tool category (e.g., 'medical_research_scrapers')
     * @param {string} toolName - Tool name (e.g., 'scrape_pubmed_medical_research')
     * @param {object} params - Parameters to pass to the tool
     * @returns {Promise<object>} - Tool execution result
     */
    async callTool(category, toolName, params = {}) {
        const url = `${this.baseUrl}/${category}/${toolName}`;
        const requestId = this.requestId++;

        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), this.timeout);

            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.headers
                },
                body: JSON.stringify({
                    id: requestId,
                    params: params
                }),
                signal: controller.signal
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            return result;

        } catch (error) {
            if (error.name === 'AbortError') {
                throw new Error(`Request timed out after ${this.timeout}ms`);
            }
            throw error;
        }
    }

    /**
     * List available tool categories.
     * @returns {Promise<Array<string>>} - List of category names
     */
    async listCategories() {
        const url = `${this.baseUrl}/categories`;
        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            const result = await response.json();
            return result.categories || [];
        } catch (error) {
            console.error('Failed to list categories:', error);
            return [];
        }
    }

    /**
     * List available tools in a category.
     * @param {string} category - Category name
     * @returns {Promise<Array<object>>} - List of tool definitions
     */
    async listTools(category) {
        const url = `${this.baseUrl}/${category}/tools`;
        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            const result = await response.json();
            return result.tools || [];
        } catch (error) {
            console.error(`Failed to list tools in ${category}:`, error);
            return [];
        }
    }
}

/**
 * Convenience wrapper for medical research tools.
 * Provides typed interfaces for medical research scraping and biomolecule discovery.
 */
class MedicalResearchTools {
    /**
     * Create a medical research tools client.
     * @param {MCPClient} mcpClient - MCP client instance
     */
    constructor(mcpClient) {
        this.client = mcpClient;
        this.category = 'medical_research_scrapers';
    }

    /**
     * Scrape medical research from PubMed.
     * @param {object} params - Scraping parameters
     * @param {string} params.query - Search query
     * @param {number} params.max_results - Maximum number of results
     * @param {string} params.email - Email for NCBI E-utilities
     * @param {string} params.research_type - Type of research
     * @returns {Promise<object>} - Scraping result
     */
    async scrapePubMed(params) {
        return await this.client.callTool(
            this.category,
            'scrape_pubmed_medical_research',
            params
        );
    }

    /**
     * Scrape clinical trials from ClinicalTrials.gov.
     * @param {object} params - Scraping parameters
     * @param {string} params.query - Search query
     * @param {string} params.condition - Medical condition
     * @param {string} params.intervention - Intervention/treatment
     * @param {string} params.phase - Trial phase
     * @param {number} params.max_results - Maximum number of results
     * @returns {Promise<object>} - Scraping result
     */
    async scrapeClinicalTrials(params) {
        return await this.client.callTool(
            this.category,
            'scrape_clinical_trials',
            params
        );
    }

    /**
     * Scrape biochemical research data.
     * @param {object} params - Scraping parameters
     * @param {string} params.topic - Research topic
     * @param {number} params.max_results - Maximum number of results
     * @param {number} params.time_range_days - Time range in days
     * @returns {Promise<object>} - Scraping result
     */
    async scrapeBiochemical(params) {
        return await this.client.callTool(
            this.category,
            'scrape_biochemical_research',
            params
        );
    }

    /**
     * Generate medical theorems from trial data.
     * @param {object} params - Generation parameters
     * @param {object} params.trial_data - Clinical trial data
     * @param {object} params.outcomes_data - Outcomes data
     * @returns {Promise<object>} - Generated theorems
     */
    async generateTheorems(params) {
        return await this.client.callTool(
            this.category,
            'generate_medical_theorems_from_trials',
            params
        );
    }

    /**
     * Validate a medical theorem using fuzzy logic.
     * @param {object} params - Validation parameters
     * @param {object} params.theorem - Theorem to validate
     * @param {object} params.empirical_data - Empirical data for validation
     * @returns {Promise<object>} - Validation result
     */
    async validateTheorem(params) {
        return await this.client.callTool(
            this.category,
            'validate_medical_theorem_fuzzy',
            params
        );
    }

    /**
     * Discover protein binders using RAG.
     * @param {object} params - Discovery parameters
     * @param {string} params.target_protein - Target protein name
     * @param {string} params.interaction_type - Type of interaction
     * @param {number} params.min_confidence - Minimum confidence (0-1)
     * @param {number} params.max_results - Maximum number of results
     * @returns {Promise<object>} - Discovery result with candidates
     */
    async discoverProteinBinders(params) {
        return await this.client.callTool(
            this.category,
            'discover_protein_binders',
            params
        );
    }

    /**
     * Discover enzyme inhibitors using RAG.
     * @param {object} params - Discovery parameters
     * @param {string} params.target_enzyme - Target enzyme name
     * @param {string} params.enzyme_class - Enzyme classification
     * @param {number} params.min_confidence - Minimum confidence (0-1)
     * @param {number} params.max_results - Maximum number of results
     * @returns {Promise<object>} - Discovery result with inhibitors
     */
    async discoverEnzymeInhibitors(params) {
        return await this.client.callTool(
            this.category,
            'discover_enzyme_inhibitors',
            params
        );
    }

    /**
     * Discover pathway biomolecules using RAG.
     * @param {object} params - Discovery parameters
     * @param {string} params.pathway_name - Pathway name
     * @param {Array<string>} params.biomolecule_types - Types to search for
     * @param {number} params.min_confidence - Minimum confidence (0-1)
     * @param {number} params.max_results - Maximum number of results
     * @returns {Promise<object>} - Discovery result with components
     */
    async discoverPathwayBiomolecules(params) {
        return await this.client.callTool(
            this.category,
            'discover_pathway_biomolecules',
            params
        );
    }

    /**
     * Discover biomolecules using RAG (unified interface).
     * @param {object} params - Discovery parameters
     * @param {string} params.target - Target protein, enzyme, or pathway
     * @param {string} params.discovery_type - Type: 'binders', 'inhibitors', or 'pathway'
     * @param {number} params.min_confidence - Minimum confidence (0-1)
     * @param {number} params.max_results - Maximum number of results
     * @returns {Promise<object>} - Discovery result with candidates
     */
    async discoverBiomoleculesRAG(params) {
        return await this.client.callTool(
            this.category,
            'discover_biomolecules_rag',
            params
        );
    }

    /**
     * Collect population health data.
     * @param {object} params - Collection parameters
     * @param {string} params.condition - Medical condition
     * @param {string} params.intervention - Intervention (optional)
     * @returns {Promise<object>} - Population data result
     */
    async scrapePopulationData(params) {
        return await this.client.callTool(
            this.category,
            'scrape_population_health_data',
            params
        );
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { MCPClient, MedicalResearchTools };
}

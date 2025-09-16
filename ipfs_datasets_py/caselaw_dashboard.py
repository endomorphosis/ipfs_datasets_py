"""
Caselaw Access Project GraphRAG Dashboard

This module provides a web-based dashboard for searching and exploring
the Caselaw Access Project dataset using GraphRAG capabilities.
"""

import os
import json
import logging
import asyncio
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path
from collections import defaultdict

try:
    from flask import Flask, render_template, request, jsonify, send_from_directory
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    import plotly.utils
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

from .caselaw_graphrag import CaselawGraphRAGProcessor

logger = logging.getLogger(__name__)


class CaselawDashboard:
    """Web dashboard for Caselaw Access Project GraphRAG search"""
    
    def __init__(self, cache_dir: Optional[str] = None, debug: bool = False):
        self.cache_dir = cache_dir
        self.debug = debug
        self.processor = CaselawGraphRAGProcessor(cache_dir=cache_dir)
        self.app = None
        self.processed_data = None
        
        if FLASK_AVAILABLE:
            self.app = Flask(__name__, 
                           template_folder=self._get_template_dir(),
                           static_folder=self._get_static_dir())
            self._setup_routes()
    
    def _get_template_dir(self) -> str:
        """Get templates directory"""
        current_dir = Path(__file__).parent
        template_dir = current_dir / "templates" / "caselaw"
        template_dir.mkdir(parents=True, exist_ok=True)
        return str(template_dir)
    
    def _get_static_dir(self) -> str:
        """Get static files directory"""
        current_dir = Path(__file__).parent
        static_dir = current_dir / "static" / "caselaw"
        static_dir.mkdir(parents=True, exist_ok=True)
        return str(static_dir)
    
    def initialize_data(self, max_samples: Optional[int] = None) -> Dict[str, Any]:
        """Initialize the dashboard with processed caselaw data"""
        logger.info("Initializing caselaw data for dashboard...")
        
        try:
            self.processed_data = self.processor.process_dataset(max_samples=max_samples)
            return {
                'status': 'success',
                'message': f"Loaded {self.processed_data['dataset_info']['count']} cases",
                'data': self.processed_data
            }
        except Exception as e:
            logger.error(f"Failed to initialize data: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            """Main dashboard page"""
            return self._render_dashboard()
        
        @self.app.route('/api/search')
        def search():
            """Search endpoint"""
            query = request.args.get('q', '')
            max_results = int(request.args.get('limit', 10))
            
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                results = self.processor.query_knowledge_graph(query, max_results)
                return jsonify({
                    'status': 'success',
                    'query': query,
                    'results': results,
                    'count': len(results)
                })
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
        
        @self.app.route('/case/<case_id>')
        def case_detail_page(case_id):
            """Case detail page with sidebar for legal issues and shepherding links"""
            return self._render_case_detail_page(case_id)

        @self.app.route('/api/case/<case_id>')
        def case_details(case_id):
            """Get detailed information about a specific case"""
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                # Get comprehensive case relationships
                relationships = self.processor.get_case_relationships(case_id)
                
                return jsonify(relationships)
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
        
        @self.app.route('/api/statistics')
        def statistics():
            """Get dataset statistics"""
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            return jsonify({
                'status': 'success',
                'statistics': self.processed_data['knowledge_graph']['statistics']
            })
        
        @self.app.route('/api/visualizations')
        def visualizations():
            """Generate visualization data"""
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                viz_data = self._generate_visualizations()
                return jsonify({
                    'status': 'success',
                    'visualizations': viz_data
                })
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })

        @self.app.route('/api/temporal-deontic/<doctrine>')
        def temporal_deontic_analysis(doctrine):
            """Get temporal deontic logic analysis for a doctrine"""
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                # Get cases related to the doctrine
                related_cases = self._get_doctrine_cases(doctrine)
                
                if not related_cases:
                    return jsonify({
                        'status': 'error',
                        'message': f'No cases found for doctrine: {doctrine}'
                    })
                
                # Process through temporal deontic logic
                from .temporal_deontic_caselaw_processor import TemporalDeonticCaselawProcessor
                temporal_processor = TemporalDeonticCaselawProcessor()
                
                # Run the analysis asynchronously
                import asyncio
                result = asyncio.run(temporal_processor.process_caselaw_lineage(related_cases, doctrine))
                
                return jsonify({
                    'status': 'success',
                    'doctrine': doctrine,
                    'temporal_deontic_analysis': result
                })
                
            except Exception as e:
                logger.error(f"Temporal deontic analysis failed for {doctrine}: {e}")
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })

        @self.app.route('/api/legal-doctrines')
        def legal_doctrines():
            """Get all legal doctrines with case counts and clustering data"""
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                doctrines_data = self._get_legal_doctrines_with_clustering()
                # Return the data structure directly with status
                result = {
                    'status': 'success',
                    **doctrines_data  # Unpack the doctrines data (doctrines, clusters, etc.)
                }
                return jsonify(result)
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })

        @self.app.route('/api/legal-doctrines/search')
        def search_doctrines():
            """Search and filter legal doctrines with dynamic clustering"""
            query = request.args.get('q', '').lower()
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                filtered_doctrines = self._search_and_cluster_doctrines(query)
                # Return the data structure directly with status
                result = {
                    'status': 'success',
                    **filtered_doctrines  # Unpack the filtered doctrines data
                }
                return jsonify(result)
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })

        @self.app.route('/doctrine/<doctrine_name>')
        def doctrine_page(doctrine_name):
            """Individual doctrine page showing case shepherding lineage"""
            return self._render_doctrine_page(doctrine_name)
        
        @self.app.route('/api/initialize', methods=['POST'])
        def initialize():
            """Initialize the dashboard with data"""
            try:
                result = self.initialize_data(max_samples=100)
                return jsonify(result)
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
    
    def _render_dashboard(self) -> str:
        """Render the main dashboard HTML"""
        if not self.processed_data:
            return self._render_initialization_page()
        
        # Create dashboard HTML
        html_content = self._create_dashboard_html()
        return html_content
    
    def _render_initialization_page(self) -> str:
        """Render initialization page when data is not loaded"""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Caselaw Access Project - GraphRAG Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }
                .container { max-width: 800px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                .header { text-align: center; margin-bottom: 40px; }
                .init-button { background: #007bff; color: white; padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
                .init-button:hover { background: #0056b3; }
                .loading { display: none; text-align: center; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🏛️ Caselaw Access Project</h1>
                    <h2>GraphRAG Dashboard</h2>
                    <p>Search and explore legal cases using advanced knowledge graph technology</p>
                </div>
                
                <div style="text-align: center;">
                    <button class="init-button" onclick="initializeData()">Initialize Dataset</button>
                    <div class="loading" id="loading">
                        <p>Loading dataset and building knowledge graph...</p>
                        <p>This may take a few moments.</p>
                    </div>
                </div>
            </div>
            
            <script>
                function initializeData() {
                    document.querySelector('.init-button').style.display = 'none';
                    document.getElementById('loading').style.display = 'block';
                    
                    fetch('/api/initialize', { method: 'POST' })
                        .then(response => response.json())
                        .then(data => {
                            if (data.status === 'success') {
                                window.location.reload();
                            } else {
                                alert('Failed to initialize: ' + data.message);
                                document.querySelector('.init-button').style.display = 'block';
                                document.getElementById('loading').style.display = 'none';
                            }
                        })
                        .catch(error => {
                            alert('Error: ' + error);
                            document.querySelector('.init-button').style.display = 'block';
                            document.getElementById('loading').style.display = 'none';
                        });
                }
            </script>
        </body>
        </html>
        """
    
    def _get_javascript_code(self):
        """Generate JavaScript code without f-string conflicts"""
        return '''
            <script>
                // Professional JavaScript functionality for legal research platform
                
                // Tab management
                function showTab(tabName) {
                    // Hide all tabs
                    document.querySelectorAll('.tab-content').forEach(tab => {
                        tab.classList.remove('active');
                    });
                    document.querySelectorAll('.nav-tab').forEach(tab => {
                        tab.classList.remove('active');
                    });
                    
                    // Show selected tab
                    document.getElementById(tabName + '-tab').classList.add('active');
                    event.target.classList.add('active');
                    
                    // Load tab-specific content
                    if (tabName === 'doctrines') {
                        loadDoctrines();
                    } else if (tabName === 'analytics') {
                        loadAnalytics();
                    } else if (tabName === 'temporal') {
                        loadTemporalLogic();
                    }
                }
                
                // Search functionality
                function performSearch() {
                    const query = document.getElementById('searchQuery').value.trim();
                    if (!query) return;
                    
                    showLoading();
                    hideResults();
                    
                    fetch(`/api/search?q=${encodeURIComponent(query)}&limit=10`)
                        .then(response => response.json())
                        .then(data => {
                            hideLoading();
                            displayResults(data);
                        })
                        .catch(error => {
                            hideLoading();
                            showError('Search failed: ' + error.message);
                        });
                }
                
                function setSearchQuery(query) {
                    document.getElementById('searchQuery').value = query;
                    performSearch();
                }
                
                function displayResults(data) {
                    const resultsDiv = document.getElementById('searchResults');
                    const countDiv = document.getElementById('resultsCount');
                    const listDiv = document.getElementById('casesList');
                    
                    if (data.results && data.results.length > 0) {
                        countDiv.textContent = `${data.results.length} cases found for "${data.query}"`;
                        
                        const casesHTML = data.results.map(caseItem => `
                            <div class="case-result" onclick="viewCase('${caseItem.id}')">
                                <div class="case-title">${caseItem.title || caseItem.name}</div>
                                <div class="case-citation">${caseItem.citation}</div>
                                <div class="case-summary">${caseItem.summary || 'Legal case summary unavailable.'}</div>
                                <div class="case-meta">
                                    <div class="meta-item"><strong>${caseItem.court}</strong> • ${caseItem.year}</div>
                                    <div class="meta-item">Relevance: ${caseItem.relevance ? (caseItem.relevance * 100).toFixed(1) + '%' : 'N/A'}</div>
                                </div>
                            </div>
                        `).join('');
                        
                        listDiv.innerHTML = casesHTML;
                        resultsDiv.style.display = 'block';
                    } else {
                        countDiv.textContent = `No cases found for "${data.query || 'your search'}"`;
                        listDiv.innerHTML = '<div class="no-results">No matching cases found. Try different search terms or browse by legal doctrine.</div>';
                        resultsDiv.style.display = 'block';
                    }
                }
                
                function viewCase(caseId) {
                    window.location.href = `/case/${caseId}`;
                }
                
                function showLoading() {
                    document.getElementById('loadingSpinner').style.display = 'block';
                }
                
                function hideLoading() {
                    document.getElementById('loadingSpinner').style.display = 'none';
                }
                
                function hideResults() {
                    document.getElementById('searchResults').style.display = 'none';
                }
                
                function showError(message) {
                    alert('Error: ' + message);
                }
                
                function loadDoctrines() {
                    fetch('/api/doctrines')
                        .then(response => response.json())
                        .then(data => {
                            displayDoctrines(data);
                        })
                        .catch(error => {
                            showError('Failed to load doctrines: ' + error.message);
                        });
                }
                
                function displayDoctrines(data) {
                    const doctrinesDiv = document.getElementById('doctrinesGrid');
                    if (!doctrinesDiv || !data.doctrines) return;
                    
                    const html = data.doctrines.map(doctrine => `
                        <div class="doctrine-item" onclick="searchDoctrine('${doctrine.name}')">
                            <div class="doctrine-name">${doctrine.name}</div>
                            <div class="doctrine-count">${doctrine.case_count} cases</div>
                        </div>
                    `).join('');
                    
                    doctrinesDiv.innerHTML = html;
                }
                
                function searchDoctrine(doctrine) {
                    document.getElementById('searchQuery').value = doctrine;
                    showTab('search');
                    performSearch();
                }
                
                function loadTemporalLogic() {
                    // Temporal logic content is server-side rendered
                }
                
                // Temporal deontic logic analysis
                function analyzeTemporalLogic() {
                    const doctrine = document.getElementById('doctrineSelect').value;
                    if (!doctrine) {
                        alert('Please select a legal doctrine to analyze.');
                        return;
                    }
                    
                    fetch(`/api/temporal-deontic/${encodeURIComponent(doctrine)}`)
                        .then(response => response.json())
                        .then(data => {
                            displayTemporalResults(data);
                        })
                        .catch(error => {
                            showError('Temporal analysis failed: ' + error.message);
                        });
                }
                
                function displayTemporalResults(data) {
                    const resultsDiv = document.getElementById('temporalResults');
                    
                    if (data.status === 'success' && data.analysis) {
                        const analysis = data.analysis;
                        const html = `
                            <div class="results-header">
                                <div class="results-title">Temporal Deontic Logic Analysis</div>
                                <div class="results-count">${analysis.chronological_evolution.length} cases analyzed</div>
                            </div>
                            <div style="padding: 20px;">
                                <h3>Chronological Evolution:</h3>
                                ${analysis.chronological_evolution.map(caseItem => `
                                    <div class="case-result">
                                        <div class="case-title">${caseItem.year}: ${caseItem.case_id}</div>
                                        <div class="case-meta">O:${caseItem.obligations} P:${caseItem.permissions} F:${caseItem.prohibitions}</div>
                                    </div>
                                `).join('')}
                                
                                <h3>Generated Theorems:</h3>
                                ${analysis.theorems.map((theorem, index) => `
                                    <div class="case-result">
                                        <div class="case-title">📜 ${theorem.name}</div>
                                        <div class="case-citation">Formal: ${theorem.formal_logic.substring(0, 100)}...</div>
                                        <div class="case-summary">${theorem.natural_language}</div>
                                        <div class="case-meta">
                                            <div class="meta-item">Supporting Cases: ${theorem.supporting_cases}</div>
                                        </div>
                                    </div>
                                `).join('')}
                                
                                <div class="metric-card">
                                    <h3>Consistency Analysis: ${analysis.consistency_check.is_consistent ? '✅ CONSISTENT' : '❌ CONFLICTS DETECTED'}</h3>
                                    <p>Conflicts: ${analysis.consistency_check.conflicts}</p>
                                    <p>Temporal Violations: ${analysis.consistency_check.temporal_violations}</p>
                                </div>
                            </div>
                        `;
                        
                        resultsDiv.innerHTML = html;
                        resultsDiv.style.display = 'block';
                    } else {
                        resultsDiv.innerHTML = '<div style="padding: 20px; text-align: center; color: #64748b;">No temporal logic analysis available for this doctrine.</div>';
                        resultsDiv.style.display = 'block';
                    }
                }
                
                function loadAnalytics() {
                    // Analytics tab is already populated server-side
                }
                
                // Event listeners
                document.addEventListener('DOMContentLoaded', function() {
                    document.getElementById('searchQuery').addEventListener('keypress', function(e) {
                        if (e.key === 'Enter') {
                            performSearch();
                        }
                    });
                    
                    // Load initial content
                    loadDoctrines();
                });
            </script>
        '''
    
    def _create_dashboard_html(self) -> str:
        """Create the main dashboard HTML"""
        stats = self.processed_data['knowledge_graph']['statistics']
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Caselaw Access Project - Legal Research Platform</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <!-- Professional Legal Research Platform Styles -->
            <style>
                /* Reset and base styles */
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                
                body {{ 
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
                    margin: 0; padding: 0; background: #f8fafc; color: #1e293b; line-height: 1.6;
                    font-size: 14px;
                }}
                
                /* Professional header */
                .header {{ 
                    background: #1e293b; color: white; padding: 20px 0; border-bottom: 3px solid #0f172a;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }}
                
                .header .container {{
                    display: flex; justify-content: space-between; align-items: center;
                    max-width: 1400px; margin: 0 auto; padding: 0 24px;
                }}
                
                .header h1 {{ 
                    font-size: 1.75rem; font-weight: 600; margin: 0;
                    display: flex; align-items: center; gap: 12px;
                }}
                
                .header .legal-badge {{
                    background: #dc2626; color: white; padding: 4px 8px;
                    border-radius: 4px; font-size: 0.75rem; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }}
                
                .header .user-info {{
                    display: flex; align-items: center; gap: 16px; font-size: 0.875rem;
                }}
                
                .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
                
                /* Professional metrics grid */
                .metrics-grid {{ 
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); 
                    gap: 20px; margin-bottom: 32px;
                }}
                
                .metric-card {{ 
                    background: white; border: 1px solid #e2e8f0; border-radius: 8px;
                    padding: 24px; transition: all 0.2s ease;
                }}
                
                .metric-card:hover {{ 
                    border-color: #3b82f6; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.1);
                }}
                
                .metric-header {{
                    display: flex; justify-content: space-between; align-items: flex-start;
                    margin-bottom: 16px;
                }}
                
                .metric-title {{
                    font-size: 0.875rem; font-weight: 500; color: #64748b;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }}
                
                .metric-icon {{
                    width: 32px; height: 32px; background: #f1f5f9; border-radius: 6px;
                    display: flex; align-items: center; justify-content: center;
                    font-size: 14px; color: #475569;
                }}
                
                .metric-value {{
                    font-size: 2.5rem; font-weight: 700; color: #0f172a; margin-bottom: 8px;
                }}
                
                .metric-change {{
                    font-size: 0.75rem; color: #059669; font-weight: 500;
                }}
                
                /* Professional navigation */
                .nav-tabs {{
                    background: white; border: 1px solid #e2e8f0; border-radius: 8px;
                    margin-bottom: 24px; overflow: hidden;
                }}
                
                .nav-tabs-list {{
                    display: flex; border-bottom: 1px solid #e2e8f0;
                }}
                
                .nav-tab {{
                    flex: 1; padding: 16px 20px; border: none; background: none;
                    font-size: 0.875rem; font-weight: 500; color: #64748b; cursor: pointer;
                    border-bottom: 2px solid transparent; transition: all 0.2s ease;
                }}
                
                .nav-tab.active {{
                    color: #3b82f6; border-bottom-color: #3b82f6; background: #f8fafc;
                }}
                
                .nav-tab:hover:not(.active) {{
                    color: #1e293b; background: #f8fafc;
                }}
                
                .tab-content {{
                    display: none; padding: 24px;
                }}
                
                .tab-content.active {{
                    display: block;
                }}
                
                /* Professional search interface */
                .search-section {{
                    background: white; border: 1px solid #e2e8f0; border-radius: 8px;
                    padding: 24px; margin-bottom: 24px;
                }}
                
                .search-header {{
                    margin-bottom: 20px;
                }}
                
                .search-header h2 {{
                    font-size: 1.25rem; font-weight: 600; color: #0f172a; margin-bottom: 8px;
                }}
                
                .search-header p {{
                    color: #64748b; font-size: 0.875rem;
                }}
                
                .search-form {{
                    display: flex; gap: 12px; margin-bottom: 20px;
                }}
                
                .search-input {{
                    flex: 1; padding: 12px 16px; border: 1px solid #d1d5db; border-radius: 6px;
                    font-size: 0.875rem; transition: border-color 0.2s ease;
                    outline: none;
                }}
                
                .search-input:focus {{
                    border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
                }}
                
                .search-button {{
                    padding: 12px 24px; background: #3b82f6; color: white; border: none;
                    border-radius: 6px; font-size: 0.875rem; font-weight: 500;
                    cursor: pointer; transition: background-color 0.2s ease;
                }}
                
                .search-button:hover {{
                    background: #2563eb;
                }}
                
                .search-filters {{
                    display: flex; gap: 12px; flex-wrap: wrap;
                }}
                
                .filter-chip {{
                    background: #f1f5f9; color: #475569; padding: 6px 12px; border-radius: 16px;
                    font-size: 0.75rem; font-weight: 500; cursor: pointer;
                    border: 1px solid transparent; transition: all 0.2s ease;
                }}
                
                .filter-chip:hover {{
                    background: #e2e8f0; border-color: #cbd5e1;
                }}
                
                .filter-chip.active {{
                    background: #3b82f6; color: white;
                }}
                
                /* Professional results */
                .results-section {{
                    background: white; border: 1px solid #e2e8f0; border-radius: 8px;
                }}
                
                .results-header {{
                    padding: 20px 24px; border-bottom: 1px solid #e2e8f0;
                    display: flex; justify-content: space-between; align-items: center;
                }}
                
                .results-title {{
                    font-size: 1.125rem; font-weight: 600; color: #0f172a;
                }}
                
                .results-count {{
                    font-size: 0.875rem; color: #64748b;
                }}
                
                .case-result {{
                    padding: 20px 24px; border-bottom: 1px solid #f1f5f9;
                    transition: background-color 0.2s ease; cursor: pointer;
                }}
                
                .case-result:last-child {{
                    border-bottom: none;
                }}
                
                .case-result:hover {{
                    background: #f8fafc;
                }}
                
                .case-title {{
                    font-weight: 600; color: #0f172a; margin-bottom: 8px;
                    font-size: 1rem; line-height: 1.4;
                }}
                
                .case-citation {{
                    font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.8125rem;
                    color: #dc2626; background: #fef2f2; padding: 4px 8px; border-radius: 4px;
                    display: inline-block; margin-bottom: 12px; border-left: 3px solid #dc2626;
                }}
                
                .case-summary {{
                    color: #475569; font-size: 0.875rem; line-height: 1.5;
                    margin-bottom: 12px;
                }}
                
                .case-meta {{
                    display: flex; gap: 16px; font-size: 0.75rem; color: #64748b;
                    text-transform: uppercase; letter-spacing: 0.5px; font-weight: 500;
                }}
                
                .meta-item {{
                    display: flex; align-items: center; gap: 4px;
                }}
                
                /* Loading and empty states */
                .loading {{
                    display: none; text-align: center; padding: 60px; color: #64748b;
                }}
                
                .loading-spinner {{
                    width: 24px; height: 24px; border: 2px solid #f1f5f9;
                    border-top: 2px solid #3b82f6; border-radius: 50%;
                    animation: spin 1s linear infinite; margin: 0 auto 16px;
                }}
                
                @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
                
                .no-results {{
                    text-align: center; padding: 60px; color: #64748b;
                    background: #f8fafc; border-radius: 8px; margin: 24px 0;
                }}
                
                /* Professional footer */
                .footer {{
                    background: #f1f5f9; border-top: 1px solid #e2e8f0; 
                    padding: 24px; text-align: center; margin-top: 48px;
                }}
                
                .footer-text {{
                    font-size: 0.75rem; color: #64748b;
                }}
                
                /* Responsive design */
                @media (max-width: 768px) {{
                    .container {{ padding: 16px; }}
                    .metrics-grid {{ grid-template-columns: 1fr; }}
                    .search-form {{ flex-direction: column; }}
                    .search-filters {{ justify-content: center; }}
                    .nav-tabs-list {{ flex-wrap: wrap; }}
                    .nav-tab {{ flex: none; min-width: 120px; }}
                    .case-meta {{ flex-direction: column; align-items: flex-start; gap: 8px; }}
                    .header .container {{ flex-direction: column; gap: 12px; text-align: center; }}
            </style>
        </head>
        <body>
            <!-- Professional Legal Research Platform Header -->
            <div class="header">
                <div class="container">
                    <h1>
                        ⚖️ Caselaw Access Project
                        <span class="legal-badge">Legal Research</span>
                    </h1>
                    <div class="user-info">
                        <span>Legal Research Platform</span>
                        <span>•</span>
                        <span>{stats['total_nodes']} Total Resources</span>
                    </div>
                </div>
            </div>
            
            <!-- Main Container -->
            <div class="container">
                <!-- Key Metrics -->
                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-header">
                            <div>
                                <div class="metric-title">Legal Cases</div>
                                <div class="metric-value">{stats.get('case_nodes', 100)}</div>
                                <div class="metric-change">+{len(self.processed_data.get('cases', []))} available</div>
                            </div>
                            <div class="metric-icon">⚖️</div>
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-header">
                            <div>
                                <div class="metric-title">Knowledge Entities</div>
                                <div class="metric-value">{stats.get('total_nodes', 130)}</div>
                                <div class="metric-change">Linked resources</div>
                            </div>
                            <div class="metric-icon">🏛️</div>
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-header">
                            <div>
                                <div class="metric-title">Legal Relationships</div>
                                <div class="metric-value">{stats.get('total_edges', 764)}</div>
                                <div class="metric-change">Precedent connections</div>
                            </div>
                            <div class="metric-icon">🔗</div>
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-header">
                            <div>
                                <div class="metric-title">Temporal Coverage</div>
                                <div class="metric-value">{stats.get('year_range', {}).get('span', 220)}</div>
                                <div class="metric-change">Years of jurisprudence</div>
                            </div>
                            <div class="metric-icon">📅</div>
                        </div>
                    </div>
                </div>
                
                <!-- Professional Navigation Tabs -->
                <div class="nav-tabs">
                    <div class="nav-tabs-list">
                        <button class="nav-tab active" onclick="showTab('search')">Case Search</button>
                        <button class="nav-tab" onclick="showTab('doctrines')">Legal Doctrines</button>
                        <button class="nav-tab" onclick="showTab('temporal')">Temporal Analysis</button>
                        <button class="nav-tab" onclick="showTab('analytics')">Analytics</button>
                    </div>
                    
                    <!-- Case Search Tab -->
                    <div id="search-tab" class="tab-content active">
                        <div class="search-section">
                            <div class="search-header">
                                <h2>Legal Case Research</h2>
                                <p>Search through comprehensive caselaw database using advanced GraphRAG technology for legal precedent analysis</p>
                            </div>
                            <div class="search-form">
                                <input type="text" class="search-input" id="searchQuery" placeholder="Enter case name, citation, legal doctrine, or search terms..." />
                                <button class="search-button" onclick="performSearch()">Search Cases</button>
                            </div>
                            <div class="search-filters">
                                <div class="filter-chip" onclick="setSearchQuery('civil rights')">Civil Rights</div>
                                <div class="filter-chip" onclick="setSearchQuery('Supreme Court')">Supreme Court</div>
                                <div class="filter-chip" onclick="setSearchQuery('constitutional law')">Constitutional Law</div>
                                <div class="filter-chip" onclick="setSearchQuery('criminal procedure')">Criminal Procedure</div>
                                <div class="filter-chip" onclick="setSearchQuery('qualified immunity')">Qualified Immunity</div>
                                <div class="filter-chip" onclick="setSearchQuery('due process')">Due Process</div>
                            </div>
                        </div>
                        
                        <!-- Search Results -->
                        <div class="results-section" id="searchResults" style="display: none;">
                            <div class="results-header">
                                <div class="results-title">Search Results</div>
                                <div class="results-count" id="resultsCount">0 cases found</div>
                            </div>
                            <div id="casesList"></div>
                        </div>
                        
                        <!-- Loading State -->
                        <div class="loading" id="searchLoading">
                            <div class="loading-spinner"></div>
                            <div>Searching legal database...</div>
                        </div>
                        
                        <!-- No Results State -->
                        <div class="no-results" id="noResults" style="display: none;">
                            <h3>No cases found</h3>
                            <p>Try adjusting your search terms or using the suggested filters above.</p>
                        </div>
                    </div>
                    
                    <!-- Legal Doctrines Tab -->
                    <div id="doctrines-tab" class="tab-content">
                        <div class="search-section">
                            <div class="search-header">
                                <h2>Legal Doctrines Explorer</h2>
                                <p>Explore legal doctrines through intelligent clustering and case relationship analysis</p>
                            </div>
                            <div class="search-form">
                                <input type="text" class="search-input" id="doctrineSearch" placeholder="Filter legal doctrines..." onkeyup="filterDoctrines()" />
                            </div>
                            <div id="doctrineCloud" class="tag-cloud">
                                <!-- Doctrine cloud will be populated by JavaScript -->
                            </div>
                        </div>
                    </div>
                    
                    <!-- Temporal Analysis Tab -->
                    <div id="temporal-tab" class="tab-content">
                        <div class="search-section">
                            <div class="search-header">
                                <h2>Temporal Deontic Logic Analysis</h2>
                                <p>Convert legal precedents into formal temporal deontic logic and analyze chronological consistency</p>
                            </div>
                            <div class="search-form">
                                <select class="search-input" id="doctrineSelect">
                                    <option value="">Select a legal doctrine...</option>
                                    <option value="qualified immunity">Qualified Immunity</option>
                                    <option value="civil rights">Civil Rights</option>
                                    <option value="due process">Due Process</option>
                                    <option value="constitutional law">Constitutional Law</option>
                                </select>
                                <button class="search-button" onclick="analyzeTemporalLogic()">Analyze Logic</button>
                            </div>
                            <div id="temporalResults" class="results-section" style="display: none;">
                                <!-- Temporal logic results will be populated by JavaScript -->
                            </div>
                        </div>
                    </div>
                    
                    <!-- Analytics Tab -->
                    <div id="analytics-tab" class="tab-content">
                        <div class="search-section">
                            <div class="search-header">
                                <h2>Dataset Analytics & Visualizations</h2>
                                <p>Statistical analysis and visual insights into the legal knowledge graph</p>
                            </div>
                            <div id="analyticsContent">
                                <!-- Analytics content will be loaded here -->
                                <div class="metric-card">
                                    <h3>Court Distribution</h3>
                                    <div class="court-stats">
                                        {self._generate_court_stats_html()}
                                    </div>
                                </div>
                                <div class="metric-card">
                                    <h3>Legal Topic Distribution</h3>
                                    <div class="topic-stats">
                                        {self._generate_topic_stats_html()}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            
            <script>
                // Professional JavaScript functionality for legal research platform
                
                // Tab management
                function showTab(tabName) {{
                    // Hide all tabs
                    document.querySelectorAll('.tab-content').forEach(tab => {{
                        tab.classList.remove('active');
                    }});
                    document.querySelectorAll('.nav-tab').forEach(tab => {{
                        tab.classList.remove('active');
                    }});
                    
                    // Show selected tab
                    document.getElementById(tabName + '-tab').classList.add('active');
                    event.target.classList.add('active');
                    
                    // Load tab-specific content
                    if (tabName === 'doctrines') {{
                        loadDoctrines();
                    }} else if (tabName === 'analytics') {{
                        loadAnalytics();
                    }}
                }}
                
                // Search functionality
                function performSearch() {{
                    const query = document.getElementById('searchQuery').value.trim();
                    if (!query) return;
                    
                    showLoading();
                    hideResults();
                    
                    fetch(`/api/search?q=${{encodeURIComponent(query)}}&limit=10`)
                        .then(response => response.json())
                        .then(data => {{
                            hideLoading();
                            displayResults(data);
                        }})
                        .catch(error => {{
                            hideLoading();
                            showError('Search failed: ' + error.message);
                        }});
                }}
                
                function setSearchQuery(query) {{
                    document.getElementById('searchQuery').value = query;
                    performSearch();
                }}
                
                function displayResults(data) {{
                    const resultsDiv = document.getElementById('searchResults');
                    const countDiv = document.getElementById('resultsCount');
                    const listDiv = document.getElementById('casesList');
                    
                    if (data.results && data.results.length > 0) {{
                        countDiv.textContent = `${{data.results.length}} cases found for "${{data.query}}"`;
                        
                        const casesHTML = data.results.map(case => `
                            <div class="case-result" onclick="viewCase('${{case.id}}')">
                                <div class="case-title">${{case.title || case.name}}</div>
                                <div class="case-citation">${{case.citation}}</div>
                                <div class="case-summary">${{case.summary || 'Legal case summary unavailable.'}}</div>
                                <div class="case-meta">
                                    <div class="meta-item">Court: ${{case.court}}</div>
                                    <div class="meta-item">Year: ${{case.year}}</div>
                                    <div class="meta-item">Topic: ${{case.topic}}</div>
                                    <div class="meta-item">Relevance: ${{(case.relevance * 100).toFixed(1)}}%</div>
                                </div>
                            </div>
                        `).join('');
                        
                        listDiv.innerHTML = casesHTML;
                        resultsDiv.style.display = 'block';
                        document.getElementById('noResults').style.display = 'none';
                    }} else {{
                        resultsDiv.style.display = 'none';
                        document.getElementById('noResults').style.display = 'block';
                    }}
                }}
                
                function showLoading() {{
                    document.getElementById('searchLoading').style.display = 'block';
                }}
                
                function hideLoading() {{
                    document.getElementById('searchLoading').style.display = 'none';
                }}
                
                function hideResults() {{
                    document.getElementById('searchResults').style.display = 'none';
                    document.getElementById('noResults').style.display = 'none';
                }}
                
                function showError(message) {{
                    alert('Error: ' + message);
                }}
                
                function viewCase(caseId) {{
                    window.open(`/case/${{caseId}}`, '_blank');
                }}
                
                // Doctrine cloud functionality
                function loadDoctrines() {{
                    const doctrines = [
                        'Civil Rights', 'Constitutional Law', 'Criminal Procedure', 'Due Process',
                        'Equal Protection', 'Qualified Immunity', 'Search and Seizure', 'Free Speech',
                        'Commerce Clause', 'Substantive Due Process', 'Procedural Due Process',
                        'Miranda Rights', 'Habeas Corpus', 'Double Jeopardy', 'Self-Incrimination',
                        'Cruel and Unusual Punishment', 'Establishment Clause', 'Free Exercise',
                        'Privacy Rights', 'Property Rights', 'Contract Law', 'Tort Law',
                        'Administrative Law', 'Federal Jurisdiction', 'State Sovereignty'
                    ];
                    
                    const cloudHTML = doctrines.map(doctrine => {{
                        const size = Math.random() > 0.7 ? 'large' : Math.random() > 0.4 ? 'medium' : 'small';
                        return `<span class="doctrine-tag size-${{size}}" onclick="searchDoctrine('${{doctrine}}')">${{doctrine}}</span>`;
                    }}).join('');
                    
                    document.getElementById('doctrineCloud').innerHTML = cloudHTML;
                }}
                
                function filterDoctrines() {{
                    const filter = document.getElementById('doctrineSearch').value.toLowerCase();
                    const tags = document.querySelectorAll('.doctrine-tag');
                    
                    tags.forEach(tag => {{
                        if (tag.textContent.toLowerCase().includes(filter)) {{
                            tag.style.display = 'inline-block';
                        }} else {{
                            tag.style.display = 'none';
                        }}
                    }});
                }}
                
                function searchDoctrine(doctrine) {{
                    document.getElementById('searchQuery').value = doctrine;
                    showTab('search');
                    performSearch();
                }}
                
                // Temporal deontic logic analysis
                function analyzeTemporalLogic() {{
                    const doctrine = document.getElementById('doctrineSelect').value;
                    if (!doctrine) {{
                        alert('Please select a legal doctrine to analyze.');
                        return;
                    }}
                    
                    fetch(`/api/temporal-deontic/${{encodeURIComponent(doctrine)}}`)
                        .then(response => response.json())
                        .then(data => {{
                            displayTemporalResults(data);
                        }})
                        .catch(error => {{
                            showError('Temporal analysis failed: ' + error.message);
                        }});
                }}
                
                function displayTemporalResults(data) {{
                    const resultsDiv = document.getElementById('temporalResults');
                    
                    if (data.status === 'success' && data.analysis) {{
                        const analysis = data.analysis;
                        const html = `
                            <div class="results-header">
                                <div class="results-title">Temporal Deontic Logic Analysis</div>
                                <div class="results-count">${{analysis.chronological_evolution.length}} cases analyzed</div>
                            </div>
                            <div style="padding: 20px;">
                                <h3>Chronological Evolution:</h3>
                                ${{analysis.chronological_evolution.map(case => `
                                    <div class="case-result">
                                        <div class="case-title">${{case.year}}: ${{case.case_id}}</div>
                                        <div class="case-meta">O:${{case.obligations}} P:${{case.permissions}} F:${{case.prohibitions}}</div>
                                    </div>
                                `).join('')}}
                                
                                <h3>Generated Theorems:</h3>
                                ${{analysis.theorems.map((theorem, index) => `
                                    <div class="case-result">
                                        <div class="case-title">📜 ${{theorem.name}}</div>
                                        <div class="case-citation">Formal: ${{theorem.formal_logic.substring(0, 100)}}...</div>
                                        <div class="case-summary">${{theorem.natural_language}}</div>
                                        <div class="case-meta">
                                            <div class="meta-item">Supporting Cases: ${{theorem.supporting_cases}}</div>
                                        </div>
                                    </div>
                                `).join('')}}
                                
                                <div class="metric-card">
                                    <h3>Consistency Analysis: ${{analysis.consistency_check.is_consistent ? '✅ CONSISTENT' : '❌ CONFLICTS DETECTED'}}</h3>
                                    <p>Conflicts: ${{analysis.consistency_check.conflicts}}</p>
                                    <p>Temporal Violations: ${{analysis.consistency_check.temporal_violations}}</p>
                                </div>
                            </div>
                        `;
                        
                        resultsDiv.innerHTML = html;
                        resultsDiv.style.display = 'block';
                    }} else {{
                        resultsDiv.innerHTML = '<div style="padding: 20px; text-align: center; color: #64748b;">No temporal logic analysis available for this doctrine.</div>';
                        resultsDiv.style.display = 'block';
                    }}
                }}
                
                function loadAnalytics() {{
                    // Analytics tab is already populated server-side
                }}
                
                // Event listeners
                document.addEventListener('DOMContentLoaded', function() {{
                    document.getElementById('searchQuery').addEventListener('keypress', function(e) {{
                        if (e.key === 'Enter') {{
                            performSearch();
                        }}
                    }});
                    
                    // Load initial content
                    loadDoctrines();
                }});
            </script>
        </body>
        </html>
        """
    
    def _generate_court_stats_html(self) -> str:
        """Generate HTML for court distribution statistics"""
        if not self.processed_data:
            return "<p>No data available</p>"
        
        stats = self.processed_data['knowledge_graph']['statistics']
        court_dist = stats.get('court_distribution', {})
        
        html_parts = []
        for court, count in list(court_dist.items())[:8]:
            percentage = (count / sum(court_dist.values())) * 100 if court_dist.values() else 0
            html_parts.append(f"""
                <div class="stat-row">
                    <div class="stat-label">{court}</div>
                    <div class="stat-bar">
                        <div class="stat-fill" style="width: {percentage:.1f}%"></div>
                    </div>
                    <div class="stat-value">{count} cases</div>
                </div>
            """)
        
        return ''.join(html_parts) + """
            <style>
                .stat-row { display: flex; align-items: center; margin: 8px 0; }
                .stat-label { flex: 1; font-size: 0.875rem; color: #475569; }
                .stat-bar { flex: 2; height: 8px; background: #f1f5f9; border-radius: 4px; margin: 0 12px; }
                .stat-fill { height: 100%; background: linear-gradient(90deg, #3b82f6, #1d4ed8); border-radius: 4px; }
                .stat-value { font-size: 0.75rem; color: #64748b; font-weight: 500; }
            </style>
        """
    
    def _generate_topic_stats_html(self) -> str:
        """Generate HTML for legal topic distribution statistics"""
        if not self.processed_data:
            return "<p>No data available</p>"
        
        stats = self.processed_data['knowledge_graph']['statistics']
        topic_dist = stats.get('most_common_topics', {})
        
        html_parts = []
        for topic, count in list(topic_dist.items())[:8]:
            percentage = (count / sum(topic_dist.values())) * 100 if topic_dist.values() else 0
            html_parts.append(f"""
                <div class="stat-row">
                    <div class="stat-label">{topic.title()}</div>
                    <div class="stat-bar">
                        <div class="stat-fill" style="width: {percentage:.1f}%"></div>
                    </div>
                    <div class="stat-value">{count} cases</div>
                </div>
            """)
        
        return ''.join(html_parts) + """
            <style>
                .stat-row { display: flex; align-items: center; margin: 8px 0; }
                .stat-label { flex: 1; font-size: 0.875rem; color: #475569; }
                .stat-bar { flex: 2; height: 8px; background: #f1f5f9; border-radius: 4px; margin: 0 12px; }
                .stat-fill { height: 100%; background: linear-gradient(90deg, #dc2626, #991b1b); border-radius: 4px; }
                .stat-value { font-size: 0.75rem; color: #64748b; font-weight: 500; }
            </style>
        """
    
    def _render_case_detail_page(self, case_id: str) -> str:
        """Render the case detail page with sidebar for legal issues and shepherding"""
        if not self.processed_data:
            return self._render_error_page("Dashboard not initialized. Please load the data first.")
        
        # Get case relationships data
        relationships_data = self.processor.get_case_relationships(case_id)
        
        if relationships_data['status'] != 'success':
            return self._render_error_page(f"Case not found: {case_id}")
        
        case = relationships_data['case']
        legal_issues = relationships_data['legal_issues']
        shepherding_info = relationships_data['shepherding_info']
        similar_cases = relationships_data['similar_cases']
        
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{case.get('title', 'Case Details')} | Caselaw Access Project</title>
            <style>
                * {{
                    margin: 0; padding: 0; box-sizing: border-box;
                }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    color: #2c3e50;
                }}
                .header {{
                    background: rgba(255, 255, 255, 0.95);
                    backdrop-filter: blur(10px);
                    padding: 20px 0;
                    box-shadow: 0 2px 20px rgba(0,0,0,0.1);
                    position: sticky;
                    top: 0;
                    z-index: 100;
                }}
                .header-content {{
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 0 20px;
                    display: flex;
                    align-items: center;
                    gap: 20px;
                }}
                .back-button {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 25px;
                    text-decoration: none;
                    font-weight: 600;
                    transition: transform 0.3s ease;
                }}
                .back-button:hover {{
                    transform: translateY(-2px);
                }}
                .header h1 {{
                    font-size: 1.5em;
                    color: #2c3e50;
                    flex-grow: 1;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 30px auto;
                    padding: 0 20px;
                    display: grid;
                    grid-template-columns: 1fr 300px;
                    gap: 30px;
                }}
                .main-content {{
                    background: white;
                    border-radius: 20px;
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                    overflow: hidden;
                }}
                .case-header {{
                    background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                    padding: 40px;
                    border-bottom: 1px solid #dee2e6;
                }}
                .case-title {{
                    font-size: 2.2em;
                    font-weight: 700;
                    color: #2c3e50;
                    margin-bottom: 15px;
                    line-height: 1.2;
                }}
                .case-citation {{
                    font-size: 1.2em;
                    font-family: 'Courier New', monospace;
                    background: #fff;
                    padding: 12px 16px;
                    border-radius: 8px;
                    border-left: 4px solid #007bff;
                    margin-bottom: 20px;
                    color: #495057;
                }}
                .case-meta {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 15px;
                    margin-top: 20px;
                }}
                .meta-item {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 10px 15px;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                }}
                .case-content {{
                    padding: 40px;
                }}
                .section {{
                    margin-bottom: 40px;
                }}
                .section h2 {{
                    font-size: 1.5em;
                    color: #2c3e50;
                    margin-bottom: 20px;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }}
                .case-summary {{
                    font-size: 1.1em;
                    line-height: 1.6;
                    color: #495057;
                    background: #f8f9fa;
                    padding: 25px;
                    border-radius: 10px;
                    border-left: 4px solid #667eea;
                }}
                .sidebar {{
                    display: flex;
                    flex-direction: column;
                    gap: 20px;
                }}
                .sidebar-card {{
                    background: white;
                    border-radius: 15px;
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                    overflow: hidden;
                }}
                .sidebar-header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    font-weight: 600;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }}
                .sidebar-content {{
                    padding: 20px;
                }}
                .legal-issue {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 12px 15px;
                    margin-bottom: 10px;
                    background: #f8f9fa;
                    border-radius: 8px;
                    cursor: pointer;
                    transition: all 0.3s ease;
                    border-left: 4px solid #dee2e6;
                }}
                .legal-issue:hover {{
                    background: #e3f2fd;
                    border-left-color: #2196f3;
                    transform: translateX(5px);
                }}
                .issue-name {{
                    font-weight: 500;
                    color: #495057;
                }}
                .confidence-badge {{
                    background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
                    color: white;
                    padding: 4px 8px;
                    border-radius: 12px;
                    font-size: 0.8em;
                    font-weight: 500;
                }}
                .shepherding-case {{
                    padding: 15px;
                    margin-bottom: 12px;
                    background: #f8f9fa;
                    border-radius: 8px;
                    border-left: 4px solid #6c757d;
                    transition: all 0.3s ease;
                    cursor: pointer;
                }}
                .shepherding-case:hover {{
                    background: #e9ecef;
                    transform: translateX(3px);
                }}
                .shepherding-case.citing {{
                    border-left-color: #28a745;
                }}
                .shepherding-case.cited {{
                    border-left-color: #dc3545;
                }}
                .shepherding-case.related {{
                    border-left-color: #ffc107;
                }}
                .case-link {{
                    text-decoration: none;
                    color: inherit;
                }}
                .case-link:hover {{
                    text-decoration: underline;
                }}
                .shepherding-title {{
                    font-weight: 500;
                    color: #495057;
                    margin-bottom: 5px;
                }}
                .shepherding-meta {{
                    font-size: 0.9em;
                    color: #6c757d;
                    display: flex;
                    align-items: center;
                    gap: 15px;
                }}
                .relationship-badge {{
                    background: #e9ecef;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-size: 0.8em;
                    text-transform: uppercase;
                    font-weight: 500;
                }}
                .similar-case {{
                    padding: 15px;
                    margin-bottom: 12px;
                    background: #f8f9fa;
                    border-radius: 8px;
                    border-left: 4px solid #667eea;
                    transition: all 0.3s ease;
                    cursor: pointer;
                }}
                .similar-case:hover {{
                    background: #e3f2fd;
                    transform: translateX(3px);
                }}
                .similarity-score {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 4px 8px;
                    border-radius: 12px;
                    font-size: 0.8em;
                    font-weight: 500;
                }}
                @media (max-width: 968px) {{
                    .container {{
                        grid-template-columns: 1fr;
                        gap: 20px;
                    }}
                    .header-content {{
                        flex-direction: column;
                        text-align: center;
                    }}
                    .case-meta {{
                        grid-template-columns: 1fr;
                    }}
                }}
                .no-data {{
                    text-align: center;
                    color: #6c757d;
                    font-style: italic;
                    padding: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="header-content">
                    <a href="/" class="back-button">⬅️ Back to Dashboard</a>
                    <h1>⚖️ Case Details</h1>
                </div>
            </div>
            
            <div class="container">
                <div class="main-content">
                    <div class="case-header">
                        <div class="case-title">{case.get('title', 'Unknown Case')}</div>
                        <div class="case-citation">
                            <strong>{case.get('citation', 'Citation not available')}</strong>
                        </div>
                        <div class="case-meta">
                            <div class="meta-item">
                                <span>🏛️</span>
                                <span>{case.get('court_abbrev', case.get('court', 'Unknown Court'))}</span>
                            </div>
                            <div class="meta-item">
                                <span>📅</span>
                                <span>{case.get('year', 'Unknown Year')}</span>
                            </div>
                            <div class="meta-item">
                                <span>🏷️</span>
                                <span>{case.get('topic', 'Unknown Topic')}</span>
                            </div>
                            <div class="meta-item">
                                <span>📄</span>
                                <span>Case ID: {case.get('id', 'Unknown')}</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="case-content">
                        <div class="section">
                            <h2>📋 Case Summary</h2>
                            <div class="case-summary">
                                {case.get('summary', 'No summary available for this case.')}
                            </div>
                        </div>
                        
                        <div class="section">
                            <h2>📖 Full Case Text</h2>
                            <div style="background: #f8f9fa; padding: 25px; border-radius: 10px; line-height: 1.6; color: #495057;">
                                {case.get('text', 'Full case text not available.')[:2000]}
                                {'...' if len(case.get('text', '')) > 2000 else ''}
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="sidebar">
                    <div class="sidebar-card">
                        <div class="sidebar-header">
                            🏷️ Legal Issues & Tags
                        </div>
                        <div class="sidebar-content">
                            {self._render_legal_issues(legal_issues)}
                        </div>
                    </div>
                    
                    <div class="sidebar-card">
                        <div class="sidebar-header">
                            📈 Case Shepherding - Citing Cases
                        </div>
                        <div class="sidebar-content">
                            {self._render_shepherding_cases(shepherding_info.get('citing_cases', []), 'citing')}
                        </div>
                    </div>
                    
                    <div class="sidebar-card">
                        <div class="sidebar-header">
                            📉 Case Shepherding - Cited Cases
                        </div>
                        <div class="sidebar-content">
                            {self._render_shepherding_cases(shepherding_info.get('cited_cases', []), 'cited')}
                        </div>
                    </div>
                    
                    <div class="sidebar-card">
                        <div class="sidebar-header">
                            🔗 Related Doctrine Cases
                        </div>
                        <div class="sidebar-content">
                            {self._render_shepherding_cases(shepherding_info.get('related_doctrine_cases', []), 'related')}
                        </div>
                    </div>
                    
                    <div class="sidebar-card">
                        <div class="sidebar-header">
                            🔍 Similar Cases
                        </div>
                        <div class="sidebar-content">
                            {self._render_similar_cases(similar_cases)}
                        </div>
                    </div>
                </div>
            </div>
            
            <script>
                // Handle legal issue clicks
                document.querySelectorAll('.legal-issue').forEach(issue => {{
                    issue.addEventListener('click', function() {{
                        const issueName = this.querySelector('.issue-name').textContent;
                        // Navigate to search results for this legal issue
                        window.location.href = `/?search=${{encodeURIComponent(issueName)}}`;
                    }});
                }});
                
                // Handle case link clicks
                document.querySelectorAll('.shepherding-case, .similar-case').forEach(caseElement => {{
                    caseElement.addEventListener('click', function() {{
                        const caseId = this.getAttribute('data-case-id');
                        if (caseId) {{
                            window.location.href = `/case/${{caseId}}`;
                        }}
                    }});
                }});
            </script>
        </body>
        </html>
        """
    
    def _render_legal_issues(self, legal_issues: List[Dict[str, Any]]) -> str:
        """Render legal issues sidebar section"""
        if not legal_issues:
            return '<div class="no-data">No legal issues identified for this case.</div>'
        
        html = ""
        for issue in legal_issues:
            confidence_pct = int(issue['confidence'] * 100)
            html += f"""
            <div class="legal-issue" data-issue="{issue['slug']}">
                <div class="issue-name">{issue['issue']}</div>
                <div class="confidence-badge">{confidence_pct}%</div>
            </div>
            """
        return html
    
    def _render_shepherding_cases(self, cases: List[Dict[str, Any]], relationship_type: str) -> str:
        """Render shepherding cases section"""
        if not cases:
            if relationship_type == 'citing':
                return '<div class="no-data">No cases found that cite this case.</div>'
            elif relationship_type == 'cited':
                return '<div class="no-data">No cases found that this case cites.</div>'
            else:
                return '<div class="no-data">No related doctrine cases found.</div>'
        
        html = ""
        for case in cases:
            html += f"""
            <div class="shepherding-case {relationship_type}" data-case-id="{case['id']}">
                <div class="shepherding-title">{case['title']}</div>
                <div class="shepherding-meta">
                    <span>📅 {case['year']}</span>
                    <span>🏛️ {case['court']}</span>
                    <span class="relationship-badge">{case['shared_concepts']} shared concepts</span>
                </div>
            </div>
            """
        return html
    
    def _render_similar_cases(self, similar_cases: List[Dict[str, Any]]) -> str:
        """Render similar cases section"""
        if not similar_cases:
            return '<div class="no-data">No similar cases found.</div>'
        
        html = ""
        for case in similar_cases[:5]:  # Limit to top 5
            similarity_pct = int(case['similarity'] * 100)
            html += f"""
            <div class="similar-case" data-case-id="{case['id']}">
                <div class="shepherding-title">{case['title']}</div>
                <div class="shepherding-meta">
                    <span>📅 {case['year']}</span>
                    <span>🏛️ {case['court']}</span>
                    <span class="similarity-score">{similarity_pct}% similar</span>
                </div>
            </div>
            """
        return html
    
    def _render_error_page(self, error_message: str) -> str:
        """Render an error page"""
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Error | Caselaw Access Project</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0;
                }}
                .error-container {{
                    background: white;
                    border-radius: 20px;
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                    padding: 50px;
                    text-align: center;
                    max-width: 500px;
                }}
                .error-icon {{ font-size: 4em; margin-bottom: 20px; }}
                .error-title {{ font-size: 2em; color: #dc3545; margin-bottom: 15px; }}
                .error-message {{ color: #6c757d; margin-bottom: 30px; line-height: 1.5; }}
                .back-button {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    padding: 15px 30px;
                    border-radius: 25px;
                    text-decoration: none;
                    font-weight: 600;
                    display: inline-block;
                    transition: transform 0.3s ease;
                }}
                .back-button:hover {{ transform: translateY(-2px); }}
            </style>
        </head>
        <body>
            <div class="error-container">
                <div class="error-icon">❌</div>
                <div class="error-title">Error</div>
                <div class="error-message">{error_message}</div>
                <a href="/" class="back-button">⬅️ Back to Dashboard</a>
            </div>
        </body>
        </html>
        """

    def _generate_visualizations(self) -> Dict[str, Any]:
        """Generate visualization data for the dashboard"""
        if not PLOTLY_AVAILABLE:
            return {
                'error': 'Plotly not available for visualizations'
            }
        
        stats = self.processed_data['knowledge_graph']['statistics']
        
        # Topics distribution chart
        topics_data = stats['most_common_topics']
        topics_fig = px.bar(
            x=list(topics_data.keys()),
            y=list(topics_data.values()),
            title="Distribution of Legal Topics",
            labels={'x': 'Legal Topic', 'y': 'Number of Cases'}
        )
        topics_fig.update_layout(
            showlegend=False,
            title_x=0.5
        )
        
        # Courts distribution chart
        courts_data = stats['court_distribution']
        courts_fig = px.pie(
            values=list(courts_data.values()),
            names=list(courts_data.keys()),
            title="Distribution by Court Type"
        )
        courts_fig.update_layout(title_x=0.5)
        
        return {
            'topics_chart': {
                'data': topics_fig.data,
                'layout': topics_fig.layout
            },
            'courts_chart': {
                'data': courts_fig.data,
                'layout': courts_fig.layout
            }
        }

    def _get_doctrine_cases(self, doctrine: str) -> List[Dict[str, Any]]:
        """Get cases related to a specific legal doctrine"""
        if not self.processed_data:
            return []
        
        # Use the processor directly instead of making HTTP request (avoiding circular dependency)
        try:
            # Use query_knowledge_graph method directly
            results = self.processor.query_knowledge_graph(doctrine, max_results=15)
            if results:
                logger.info(f"Found {len(results)} cases for doctrine: {doctrine}")
                
                doctrine_cases = []
                for result in results:
                    case = result.get('case', {})
                    
                    # Format case for temporal deontic logic processing
                    formatted_case = {
                        'id': case.get('id', case.get('case_id', str(len(doctrine_cases)))),
                        'case_name': case.get('title', case.get('case_name', case.get('full_caption', 'Unknown Case'))),
                        'citation': case.get('citation', ''),
                        'date': str(case.get('year', '')) if case.get('year') else '',
                        'court': case.get('court', ''),
                        'content': case.get('text', case.get('content', case.get('summary', ''))),
                        'topic': case.get('topic', ''),
                        'summary': case.get('summary', ''),
                        'legal_topics': case.get('legal_concepts', [])
                    }
                    doctrine_cases.append(formatted_case)
                
                return doctrine_cases
        except Exception as e:
            logger.warning(f"Could not use direct processor query for doctrine cases: {e}")
        
        # Fallback: Get cases from the processor's internal data
        cases = getattr(self.processor, 'processed_data', {}).get('cases', [])
        if not cases:
            # Fallback: try to get cases from knowledge graph nodes
            kg_nodes = self.processed_data.get('knowledge_graph', {}).get('nodes', [])
            cases = [node for node in kg_nodes if node.get('type') == 'case']
        
        doctrine_cases = []
        doctrine_lower = doctrine.lower().replace('_', ' ')
        
        for case in cases:
            # Check if doctrine appears in case content, title, topic, or summary
            case_text = (
                case.get('title', '') + ' ' +
                case.get('content', '') + ' ' + 
                case.get('topic', '') + ' ' +
                case.get('summary', '') + ' ' +
                ' '.join(case.get('legal_topics', []))
            ).lower()
            
            if doctrine_lower in case_text or any(doctrine_lower in topic.lower() 
                                                for topic in case.get('legal_topics', [])):
                # Format case for temporal deontic logic processing
                formatted_case = {
                    'id': case.get('id', case.get('case_id', str(len(doctrine_cases)))),
                    'case_name': case.get('title', case.get('case_name', 'Unknown Case')),
                    'citation': case.get('citation', ''),
                    'date': case.get('date', case.get('year', '')),
                    'court': case.get('court', ''),
                    'content': case.get('content', case.get('full_text', '')),
                    'topic': case.get('topic', ''),
                    'summary': case.get('summary', ''),
                    'legal_topics': case.get('legal_topics', [])
                }
                doctrine_cases.append(formatted_case)
        
        # Sort by date if available
        def extract_year(case):
            date_str = case.get('date', '')
            try:
                if isinstance(date_str, str) and len(date_str) >= 4:
                    return int(date_str[:4])
                elif isinstance(date_str, int):
                    return date_str
            except (ValueError, TypeError):
                pass
            return 0
        
        doctrine_cases.sort(key=extract_year)
        return doctrine_cases

    def _get_legal_doctrines_with_clustering(self) -> Dict[str, Any]:
        """Get all legal doctrines from the knowledge graph with k-means clustering"""
        if not self.processed_data:
            return {'doctrines': [], 'clusters': []}
        
        # Get cases from the processor's internal data
        cases = getattr(self.processor, 'processed_data', {}).get('cases', [])
        if not cases:
            # Fallback: try to get cases from knowledge graph nodes
            kg_nodes = self.processed_data.get('knowledge_graph', {}).get('nodes', [])
            cases = [node for node in kg_nodes if node.get('type') == 'case']
        
        # Extract all legal doctrines from cases
        doctrine_counts = defaultdict(int)
        doctrine_cases = defaultdict(list)
        all_doctrines = set()
        
        # Collect doctrines from all cases
        for case in cases:
            case_doctrines = case.get('legal_concepts', [])
            for doctrine in case_doctrines:
                doctrine_clean = doctrine.lower().strip()
                doctrine_counts[doctrine_clean] += 1
                doctrine_cases[doctrine_clean].append(case['id'])
                all_doctrines.add(doctrine_clean)
        
        # Add common legal doctrines that might not be in cases
        common_doctrines = [
            'qualified immunity', 'due process', 'equal protection', 'miranda rights',
            'search and seizure', 'probable cause', 'first amendment', 'fourth amendment',
            'civil rights', 'constitutional law', 'criminal procedure', 'habeas corpus',
            'double jeopardy', 'cruel and unusual punishment', 'freedom of speech',
            'freedom of religion', 'commerce clause', 'supremacy clause', 'interstate commerce',
            'separation of powers', 'right to counsel', 'eminent domain', 'substantive due process',
            'procedural due process', 'strict scrutiny', 'intermediate scrutiny', 'rational basis',
            'incorporation doctrine', 'exclusionary rule', 'fruit of poisonous tree',
            'good faith exception', 'inevitable discovery', 'plain view doctrine'
        ]
        
        for doctrine in common_doctrines:
            all_doctrines.add(doctrine)
            if doctrine not in doctrine_counts:
                doctrine_counts[doctrine] = 0
        
        # Create doctrine data
        doctrines_data = []
        for doctrine in all_doctrines:
            if doctrine and len(doctrine.strip()) > 2:
                case_count = int(doctrine_counts[doctrine])  # Convert numpy int32 to Python int
                doctrines_data.append({
                    'name': doctrine,
                    'display_name': doctrine.title(),
                    'case_count': case_count,
                    'cases': doctrine_cases[doctrine][:10],  # Limit for performance
                    'url_name': doctrine.replace(' ', '-').replace('&', 'and').lower(),
                    'size_factor': float(min(max(case_count / 10, 0.5), 3.0) if case_count > 0 else 0.5)  # Convert to float
                })
        
        # Sort by case count
        doctrines_data.sort(key=lambda x: x['case_count'], reverse=True)
        
        # Perform k-means clustering if possible
        clusters = self._cluster_doctrines(doctrines_data)
        
        return {
            'doctrines': doctrines_data,
            'clusters': clusters,
            'total_doctrines': len(doctrines_data),
            'total_cases': sum(d['case_count'] for d in doctrines_data)
        }
    
    def _cluster_doctrines(self, doctrines_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Cluster legal doctrines using k-means on doctrine names and case counts"""
        try:
            if not NUMPY_AVAILABLE or len(doctrines_data) < 3:
                return self._create_simple_clusters(doctrines_data)
            
            # Create feature matrix: doctrine name similarity + case count
            from sklearn.cluster import KMeans
            from sklearn.feature_extraction.text import TfidfVectorizer
            
            # Extract doctrine names and case counts
            doctrine_names = [d['name'] for d in doctrines_data]
            case_counts = np.array([d['case_count'] for d in doctrines_data])
            
            # Vectorize doctrine names using TF-IDF
            vectorizer = TfidfVectorizer(max_features=50, stop_words='english')
            name_features = vectorizer.fit_transform(doctrine_names).toarray()
            
            # Normalize case counts
            max_count = case_counts.max() if len(case_counts) > 0 else 1
            normalized_counts = (case_counts / max(max_count, 1)).reshape(-1, 1)
            
            # Combine features
            features = np.hstack([name_features, normalized_counts])
            
            # Determine optimal number of clusters (3-8)
            n_clusters = min(max(len(doctrines_data) // 8, 3), 8)
            
            # Perform k-means clustering
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            cluster_labels = kmeans.fit_predict(features)
            
            # Organize clusters
            clusters = defaultdict(list)
            for idx, label in enumerate(cluster_labels):
                clusters[label].append(doctrines_data[idx])
            
            # Create cluster data with names
            cluster_names = [
                'Constitutional Rights', 'Criminal Law', 'Civil Procedure', 
                'Administrative Law', 'Commercial Law', 'Property Law',
                'Evidence & Procedure', 'Federal Jurisdiction'
            ]
            
            cluster_data = []
            for cluster_id, doctrines in clusters.items():
                cluster_name = cluster_names[cluster_id % len(cluster_names)]
                total_cases = sum(int(d['case_count']) for d in doctrines)  # Ensure int conversion
                cluster_data.append({
                    'id': int(cluster_id),  # Convert numpy types
                    'name': cluster_name,
                    'doctrines': sorted(doctrines, key=lambda x: x['case_count'], reverse=True),
                    'total_cases': total_cases,
                    'size': len(doctrines)
                })
            
            return sorted(cluster_data, key=lambda x: x['total_cases'], reverse=True)
            
        except ImportError:
            return self._create_simple_clusters(doctrines_data)
    
    def _create_simple_clusters(self, doctrines_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create simple rule-based clusters when sklearn is not available"""
        # Simple categorization based on keywords
        clusters = {
            'Constitutional Rights': [],
            'Criminal Law': [],
            'Civil Rights': [],
            'Procedure & Evidence': [],
            'Administrative Law': [],
            'Other Legal Concepts': []
        }
        
        for doctrine in doctrines_data:
            name = doctrine['name'].lower()
            if any(word in name for word in ['amendment', 'constitutional', 'due process', 'equal protection']):
                clusters['Constitutional Rights'].append(doctrine)
            elif any(word in name for word in ['criminal', 'miranda', 'search', 'seizure', 'probable cause']):
                clusters['Criminal Law'].append(doctrine)
            elif any(word in name for word in ['civil rights', 'discrimination', 'freedom']):
                clusters['Civil Rights'].append(doctrine)
            elif any(word in name for word in ['procedure', 'evidence', 'discovery', 'trial']):
                clusters['Procedure & Evidence'].append(doctrine)
            elif any(word in name for word in ['administrative', 'regulation', 'agency']):
                clusters['Administrative Law'].append(doctrine)
            else:
                clusters['Other Legal Concepts'].append(doctrine)
        
        # Convert to cluster data format
        cluster_data = []
        for cluster_id, (cluster_name, doctrines) in enumerate(clusters.items()):
            if doctrines:  # Only include non-empty clusters
                total_cases = sum(int(d['case_count']) for d in doctrines)  # Ensure int conversion
                cluster_data.append({
                    'id': cluster_id,
                    'name': cluster_name,
                    'doctrines': sorted(doctrines, key=lambda x: x['case_count'], reverse=True),
                    'total_cases': total_cases,
                    'size': len(doctrines)
                })
        
        return sorted(cluster_data, key=lambda x: x['total_cases'], reverse=True)
    
    def _search_and_cluster_doctrines(self, query: str) -> Dict[str, Any]:
        """Search doctrines and return filtered results with updated clustering"""
        all_doctrines_data = self._get_legal_doctrines_with_clustering()
        
        if not query:
            return all_doctrines_data
        
        # Filter doctrines based on query
        filtered_doctrines = []
        for doctrine in all_doctrines_data['doctrines']:
            if (query in doctrine['name'].lower() or 
                query in doctrine['display_name'].lower() or
                any(query in case_id.lower() for case_id in doctrine.get('cases', []))):
                filtered_doctrines.append(doctrine)
        
        # Re-cluster the filtered results
        if filtered_doctrines:
            clusters = self._cluster_doctrines(filtered_doctrines)
        else:
            clusters = []
        
        return {
            'doctrines': filtered_doctrines,
            'clusters': clusters,
            'total_doctrines': len(filtered_doctrines),
            'total_cases': sum(d['case_count'] for d in filtered_doctrines),
            'query': query
        }
    
    def _render_doctrine_page(self, doctrine_name: str) -> str:
        """Render individual doctrine page with case shepherding lineage"""
        if not self.processed_data:
            return self._render_error_page("Dashboard not initialized. Please load the data first.")
        
        # Clean doctrine name 
        doctrine_clean = doctrine_name.replace('-', ' ').replace('_', ' ').lower()
        
        # Get cases from the processor's internal data
        cases = getattr(self.processor, 'processed_data', {}).get('cases', [])
        if not cases:
            # Fallback: try to get cases from knowledge graph nodes
            kg_nodes = self.processed_data.get('knowledge_graph', {}).get('nodes', [])
            cases = [node for node in kg_nodes if node.get('type') == 'case']
        
        # Find cases related to this doctrine
        related_cases = []
        for case in cases:
            case_concepts = [c.lower() for c in case.get('legal_concepts', [])]
            if any(doctrine_clean in concept or concept in doctrine_clean for concept in case_concepts):
                related_cases.append(case)
        
        if not related_cases:
            return self._render_error_page(f"No cases found for doctrine: {doctrine_name}")
        
        # Sort cases chronologically to show lineage
        related_cases.sort(key=lambda x: x.get('year', 0))
        
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{doctrine_name.title()} - Legal Doctrine | Caselaw Access Project</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh; color: #2c3e50;
                }}
                .header {{
                    background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(10px);
                    padding: 20px 0; box-shadow: 0 2px 20px rgba(0,0,0,0.1);
                    position: sticky; top: 0; z-index: 100;
                }}
                .header-content {{
                    max-width: 1200px; margin: 0 auto; padding: 0 20px;
                    display: flex; align-items: center; gap: 20px;
                }}
                .back-button {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white; border: none; padding: 10px 20px; border-radius: 25px;
                    text-decoration: none; font-weight: 600; transition: transform 0.3s ease;
                }}
                .back-button:hover {{ transform: translateY(-2px); }}
                .doctrine-title {{
                    font-size: 2em; color: #2c3e50; flex-grow: 1;
                }}
                .container {{
                    max-width: 1200px; margin: 30px auto; padding: 0 20px;
                }}
                .doctrine-info {{
                    background: white; border-radius: 20px; padding: 40px;
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1); margin-bottom: 30px;
                }}
                .doctrine-description {{
                    background: #f8f9fa; padding: 25px; border-radius: 10px;
                    border-left: 4px solid #667eea; margin-bottom: 30px;
                }}
                .cases-timeline {{
                    background: white; border-radius: 20px; padding: 40px;
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                }}
                .timeline-header {{
                    font-size: 1.8em; margin-bottom: 30px; color: #2c3e50;
                    display: flex; align-items: center; gap: 10px;
                }}
                .timeline-case {{
                    border-left: 4px solid #667eea; padding: 25px; margin: 20px 0;
                    background: linear-gradient(135deg, #f8f9fa 0%, #fff 100%);
                    border-radius: 0 10px 10px 0; transition: all 0.3s ease;
                    cursor: pointer; position: relative;
                }}
                .timeline-case:hover {{
                    transform: translateX(5px); border-left-color: #764ba2;
                    box-shadow: 0 8px 25px rgba(102, 126, 234, 0.15);
                }}
                .case-year {{
                    position: absolute; left: -30px; top: 20px;
                    background: #667eea; color: white; padding: 5px 10px;
                    border-radius: 15px; font-weight: 600; font-size: 0.9em;
                }}
                .case-name {{
                    font-size: 1.3em; font-weight: 700; color: #2c3e50;
                    margin-bottom: 10px; margin-left: 30px;
                }}
                .case-citation {{
                    font-family: 'Courier New', monospace; color: #495057;
                    margin-bottom: 15px; font-size: 1.1em; margin-left: 30px;
                }}
                .case-significance {{
                    background: #e3f2fd; padding: 15px; border-radius: 8px;
                    margin-left: 30px; margin-top: 15px; font-style: italic;
                }}
                .stats-grid {{
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px; margin-bottom: 30px;
                }}
                .stat-card {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white; padding: 25px; border-radius: 15px; text-align: center;
                }}
                .stat-number {{ font-size: 2.5em; font-weight: 900; margin-bottom: 5px; }}
                .stat-label {{ opacity: 0.9; }}
                @media (max-width: 768px) {{
                    .header-content {{ flex-direction: column; text-align: center; }}
                    .case-year {{ position: static; margin-bottom: 10px; }}
                    .case-name, .case-citation, .case-significance {{ margin-left: 0; }}
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="header-content">
                    <a href="/" class="back-button">⬅️ Back to Dashboard</a>
                    <div class="doctrine-title">⚖️ {doctrine_name.replace('-', ' ').title()}</div>
                </div>
            </div>
            
            <div class="container">
                <div class="doctrine-info">
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-number">{len(related_cases)}</div>
                            <div class="stat-label">Related Cases</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{max([c.get('year', 0) for c in related_cases]) - min([c.get('year', 1900) for c in related_cases if c.get('year', 0) > 0])}</div>
                            <div class="stat-label">Years of Precedent</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{len(set(c.get('court', '') for c in related_cases))}</div>
                            <div class="stat-label">Different Courts</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{len(set(c.get('topic', '') for c in related_cases))}</div>
                            <div class="stat-label">Legal Topics</div>
                        </div>
                    </div>
                    
                    <div class="doctrine-description">
                        <h3>📖 About {doctrine_name.replace('-', ' ').title()}</h3>
                        <p>This legal doctrine encompasses {len(related_cases)} cases spanning from {min([c.get('year', 1900) for c in related_cases if c.get('year', 0) > 0])} to {max([c.get('year', 0) for c in related_cases])}. The cases show the evolution and application of this legal principle across different courts and jurisdictions.</p>
                    </div>
                </div>
                
                <div class="cases-timeline">
                    <div class="timeline-header">
                        📅 Case Shepherding Lineage
                    </div>
                    
                    {self._render_doctrine_timeline(related_cases)}
                </div>
            </div>
        </body>
        </html>
        """
    
    def _render_doctrine_timeline(self, cases: List[Dict[str, Any]]) -> str:
        """Render timeline of cases for a doctrine"""
        timeline_html = ""
        
        for case in cases:
            year = case.get('year', 'Unknown')
            title = case.get('title', 'Unknown Case')
            citation = case.get('citation', 'No citation')
            summary = case.get('summary', 'No summary available.')
            case_id = case.get('id', '')
            
            # Determine case significance
            significance = "This case contributed to the development of the legal doctrine."
            if 'Supreme Court' in case.get('court', ''):
                significance = "🏛️ Supreme Court precedent - Binding nationwide authority."
            elif 'Circuit' in case.get('court', ''):
                significance = "📍 Circuit court decision - Regional precedential value."
            
            timeline_html += f"""
            <div class="timeline-case" onclick="window.location.href='/case/{case_id}';">
                <div class="case-year">{year}</div>
                <div class="case-name">{title}</div>
                <div class="case-citation">{citation}</div>
                <div>{summary[:300]}{'...' if len(summary) > 300 else ''}</div>
                <div class="case-significance">{significance}</div>
            </div>
            """
        
        return timeline_html if timeline_html else "<p>No cases found in the timeline.</p>"
    
    def run(self, host: str = "0.0.0.0", port: int = 5000, initialize_data: bool = True):
        """Run the dashboard web application"""
        if not FLASK_AVAILABLE:
            logger.error("Flask not available - cannot run web dashboard")
            return
        
        if initialize_data:
            init_result = self.initialize_data(max_samples=100)  # Limit for demo
            if init_result['status'] == 'success':
                logger.info(f"✅ Dashboard initialized with {init_result['data']['dataset_info']['count']} cases")
            else:
                logger.warning(f"⚠️ Data initialization failed: {init_result['message']}")
        
        logger.info(f"🚀 Starting Caselaw Dashboard at http://{host}:{port}")
        self.app.run(host=host, port=port, debug=self.debug)


def create_caselaw_dashboard(cache_dir: Optional[str] = None, debug: bool = False) -> CaselawDashboard:
    """Factory function to create a Caselaw dashboard"""
    return CaselawDashboard(cache_dir=cache_dir, debug=debug)


if __name__ == "__main__":
    # Run the dashboard
    print("🏛️ Starting Caselaw Access Project GraphRAG Dashboard...")
    
    dashboard = create_caselaw_dashboard(debug=True)
    dashboard.run(port=5000)
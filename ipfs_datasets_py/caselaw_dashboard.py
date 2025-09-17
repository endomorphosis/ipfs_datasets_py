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
        env_cache_dir = os.environ.get('CASELAW_CACHE_DIR')
        self.cache_dir = cache_dir or env_cache_dir
        self.debug = debug
        self.processor = CaselawGraphRAGProcessor(cache_dir=self.cache_dir)
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
                raw_results = self.processor.query_knowledge_graph(query, max_results)

                def _flatten_result(item: Dict[str, Any]) -> Dict[str, Any]:
                    case = item.get('case', item)
                    # Extract reasonable defaults
                    case_id = case.get('id') or case.get('case_id') or case.get('short_citation') or case.get('citation') or case.get('title') or 'unknown'
                    title = case.get('title') or case.get('case_name') or case.get('full_caption') or str(case_id)
                    citation = case.get('citation') or case.get('short_citation') or ''
                    court = case.get('court') or case.get('court_abbrev') or ''
                    year = case.get('year') or ''
                    topic = case.get('topic') or ''
                    summary = case.get('summary') or case.get('content') or case.get('text', '')
                    relevance = item.get('relevance') or item.get('relevance_score')

                    return {
                        'id': case_id,
                        'title': title,
                        'citation': citation,
                        'court': court,
                        'year': year,
                        'topic': topic,
                        'summary': summary,
                        'relevance': relevance
                    }

                flat_results = [_flatten_result(r) for r in raw_results]

                return jsonify({
                    'status': 'success',
                    'query': query,
                    'results': flat_results,
                    'count': len(flat_results)
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
        
        @self.app.route('/api/case/<case_id>/deontic-logic')
        def case_deontic_logic(case_id):
            """Get deontic first-order logic analysis for a specific case"""
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                deontic_analysis = self._get_case_deontic_logic(case_id)
                return jsonify(deontic_analysis)
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
        
        @self.app.route('/api/case/<case_id>/citations')
        def case_citations(case_id):
            """Get citation connections and network for a specific case"""
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                citation_network = self._get_case_citation_network(case_id)
                return jsonify(citation_network)
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
        
        @self.app.route('/api/case/<case_id>/subsequent-quotes')
        def case_subsequent_quotes(case_id):
            """Get quotes from subsequent cases citing this case"""
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                subsequent_quotes = self._get_case_subsequent_quotes(case_id)
                return jsonify(subsequent_quotes)
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

                # Normalize for UI schema
                ui_analysis = self._normalize_temporal_result_for_ui(result)
                
                return jsonify({
                    'status': 'success',
                    'doctrine': doctrine,
                    'temporal_deontic_analysis': result,
                    # Provide the UI-friendly structure expected by the frontend
                    'analysis': ui_analysis
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
                result = {
                    'status': 'success',
                    **doctrines_data
                }
                return jsonify(result)
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })

        # Backward-compatible alias for legacy JS that calls /api/doctrines
        @self.app.route('/api/doctrines')
        def legal_doctrines_alias():
            return legal_doctrines()

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
                result = {
                    'status': 'success',
                    **filtered_doctrines
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

    def _normalize_temporal_result_for_ui(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Map TemporalDeonticCaselawProcessor result into the UI schema.
        Expected by UI:
          - analysis.chronological_evolution: list with {case_id, year, obligations, permissions, prohibitions}
          - analysis.theorems: list with {name, formal_logic, natural_language, supporting_cases}
          - analysis.consistency_check: {is_consistent, conflicts, temporal_violations}
        """
        if not isinstance(result, dict):
            return {'chronological_evolution': [], 'theorems': [], 'consistency_check': {}}

        precedents = result.get('precedents', []) or []
        chronological = []
        for p in precedents:
            # Extract year
            year = None
            date_str = p.get('date') or p.get('date_decided') or ''
            try:
                if isinstance(date_str, str) and len(date_str) >= 4:
                    year = int(date_str[:4])
            except Exception:
                year = None

            # Count modalities
            obligations = permissions = prohibitions = 0
            stmts = p.get('deontic_statements', []) or []
            for s in stmts:
                modality = None
                if isinstance(s, dict):
                    modality = s.get('modality') or s.get('type')
                elif hasattr(s, 'modality'):
                    modality = getattr(s, 'modality', None)

                m = (str(modality).lower() if modality else '')
                if 'obligation' in m:
                    obligations += 1
                elif 'permission' in m:
                    permissions += 1
                elif 'prohibition' in m:
                    prohibitions += 1

            chronological.append({
                'case_id': p.get('case_id') or p.get('id') or '',
                'year': year if year is not None else p.get('year', ''),
                'obligations': obligations,
                'permissions': permissions,
                'prohibitions': prohibitions
            })

        # Preserve any existing order; if empty years, leave ordering as-is
        try:
            chronological.sort(key=lambda x: (x['year'] if isinstance(x['year'], int) else 0))
        except Exception:
            pass

        # Map theorems
        src_theorems = result.get('generated_theorems', []) or []
        theorems = []
        for t in src_theorems:
            if not isinstance(t, dict):
                continue
            theorems.append({
                'name': t.get('name') or t.get('theorem_id') or 'Theorem',
                'formal_logic': t.get('formal_statement') or t.get('formal_logic') or '',
                'natural_language': t.get('natural_language') or '',
                'supporting_cases': t.get('supporting_cases') or []
            })

        # Consistency mapping
        ca = result.get('consistency_analysis', {}) or {}
        def _safe_len(v):
            try:
                return len(v)
            except Exception:
                try:
                    return int(v)
                except Exception:
                    return 0

        consistency_check = {
            'is_consistent': bool(ca.get('overall_consistent', True)),
            'conflicts': _safe_len(ca.get('conflicts_detected', [])),
            'temporal_violations': _safe_len(ca.get('temporal_violations', [])),
        }

        return {
            'chronological_evolution': chronological,
            'theorems': theorems,
            'consistency_check': consistency_check
        }

    
    
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
                function showToast(msg, type='info', timeout=2800) {{
                    const container = document.getElementById('toastContainer');
                    if (!container) return;
                    const t = document.createElement('div');
                    t.className = `toast ${type}`;
                    t.textContent = msg;
                    container.appendChild(t);
                    setTimeout(() => {{ t.remove(); }}, timeout);
                }}
                
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
                    document.getElementById('searchLoading').style.display = 'block';
                }
                
                function hideLoading() {
                    document.getElementById('searchLoading').style.display = 'none';
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

                /* Toast */
                .toast-container {{
                    position: fixed; top: 16px; right: 16px; z-index: 9999;
                }}
                .toast {{
                    background: #1f2937; color: #fff; padding: 10px 14px; border-radius: 6px; margin-top: 8px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.15); font-size: 0.9rem;
                }}
                .toast.info {{ background: #2563eb; }}
                .toast.warn {{ background: #d97706; }}
                .toast.error {{ background: #dc2626; }}
                .toast.success {{ background: #059669; }}
                
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
                <div class="toast-container" id="toastContainer"></div>
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
                        <div class="loading" id="searchLoading" style="display: none;">
                            <div class="loading-spinner" id="loadingSpinner"></div>
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
                        
                        const casesHTML = data.results.map(caseItem => `
                            <div class="case-result" onclick="viewCase('${{caseItem.id}}')">
                                <div class="case-title">${{caseItem.title || caseItem.name}}</div>
                                <div class="case-citation">${{caseItem.citation}}</div>
                                <div class="case-summary">${{caseItem.summary || 'Legal case summary unavailable.'}}</div>
                                <div class="case-meta">
                                    <div class="meta-item">Court: ${{caseItem.court}}</div>
                                    <div class="meta-item">Year: ${{caseItem.year}}</div>
                                    <div class="meta-item">Topic: ${{caseItem.topic}}</div>
                                    <div class="meta-item">Relevance: ${{(caseItem.relevance * 100).toFixed(1)}}%</div>
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
                    let doctrine = document.getElementById('doctrineSelect').value;
                    if (!doctrine) {{
                        doctrine = 'qualified immunity'; // default fallback
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
                        // Prefer normalized fields if available, else fallback to raw
                        const chronEvolution = analysis.chronological_evolution || analysis.temporal_patterns?.chronological_evolution || [];
                        const theorems = analysis.theorems || analysis.generated_theorems || [];
                        const consistency = analysis.consistency_check || analysis.consistency_analysis || {{}};
                        
                        const html = `
                            <div class="results-header">
                                <div class="results-title">Temporal Deontic Logic Analysis</div>
                                <div class="results-count">${{chronEvolution.length}} cases analyzed</div>
                            </div>
                            <div style="padding: 20px;">
                                <h3>Chronological Evolution:</h3>
                                ${{chronEvolution.map(caseItem => `
                                    <div class="case-result">
                                        <div class="case-title">${{(caseItem.year || caseItem.date?.substring(0,4) || 'Unknown')}}: ${{caseItem.case_id || 'Unknown Case'}}</div>
                                        <div class="case-meta">
                                            Obligations: ${{caseItem.obligations ?? caseItem.new_obligations?.length ?? 0}} | 
                                            Permissions: ${{caseItem.permissions ?? caseItem.new_permissions?.length ?? 0}} | 
                                            Prohibitions: ${{caseItem.prohibitions ?? caseItem.new_prohibitions?.length ?? 0}}
                                        </div>
                                    </div>
                                `).join('')}}
                                
                                <h3>Generated Theorems:</h3>
                                ${{(theorems.length ? theorems : [{{name:'No theorems generated', natural_language:'The analysis completed but did not produce formal theorems for this selection.', formal_logic:'', supporting_cases:[]}}]).map((theorem, index) => `
                                    <div class="case-result">
                                        <div class="case-title">📜 ${{theorem.name || 'Theorem ' + (index + 1)}}</div>
                                        <div class="case-citation">Formal: ${{(theorem.formal_statement || theorem.formal_logic || '').substring(0, 100)}}...</div>
                                        <div class="case-summary">${{theorem.natural_language || 'No description available'}}</div>
                                        <div class="case-meta">
                                            <div class="meta-item">Supporting Cases: ${{(theorem.supporting_cases || []).length}}</div>
                                        </div>
                                    </div>
                                `).join('')}}
                                
                                <div class="metric-card">
                                    <h3>Consistency Analysis: ${{(consistency.is_consistent ?? consistency.overall_consistent) ? '✅ CONSISTENT' : '❌ CONFLICTS DETECTED'}}</h3>
                                    <p>Conflicts: ${{consistency.conflicts ?? (consistency.conflicts_detected || []).length || 0}}</p>
                                    <p>Temporal Violations: ${{consistency.temporal_violations ?? (consistency.temporal_violations || []).length || 0}}</p>
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

                    // Persist doctrine selection
                    try {{
                        const select = document.getElementById('doctrineSelect');
                        const saved = localStorage.getItem('caselaw_doctrine');
                        if (saved && select) {{
                            for (let i = 0; i < select.options.length; i++) {{
                                if ((select.options[i].value || '').toLowerCase() === saved.toLowerCase()) {{
                                    select.selectedIndex = i; break;
                                }}
                            }}
                        }}
                        if (select) {{
                            select.addEventListener('change', () => {{
                                const v = select.value || '';
                                localStorage.setItem('caselaw_doctrine', v);
                                if (!v) {{ showToast('Doctrine cleared. Default will be used for analysis.', 'info'); }}
                            }});
                        }}
                    }} catch (e) {{ /* ignore */ }}
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

                /* Tab Navigation Styles */
                .tab-navigation {{
                    display: flex;
                    background: #f8f9fa;
                    border-radius: 10px 10px 0 0;
                    padding: 5px;
                    margin-bottom: 0;
                    border-bottom: 2px solid #e9ecef;
                }}
                
                .tab-button {{
                    flex: 1;
                    padding: 15px 20px;
                    border: none;
                    background: transparent;
                    cursor: pointer;
                    font-weight: 500;
                    border-radius: 8px;
                    transition: all 0.3s ease;
                    color: #6c757d;
                    font-size: 0.95em;
                }}
                
                .tab-button:hover {{
                    background: rgba(102, 126, 234, 0.1);
                    color: #495057;
                }}
                
                .tab-button.active {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
                }}

                /* Tab Content Styles */
                .tab-content {{
                    display: none;
                    animation: fadeIn 0.3s ease-in-out;
                }}
                
                .tab-content.active {{
                    display: block;
                }}
                
                @keyframes fadeIn {{
                    from {{ opacity: 0; transform: translateY(10px); }}
                    to {{ opacity: 1; transform: translateY(0); }}
                }}

                .loading-message {{
                    text-align: center;
                    padding: 40px;
                    color: #6c757d;
                    font-style: italic;
                }}

                /* Deontic Logic Panel Styles */
                .deontic-statement {{
                    background: #f8f9fa;
                    border-left: 4px solid #007bff;
                    padding: 15px 20px;
                    margin: 10px 0;
                    border-radius: 0 8px 8px 0;
                }}

                .deontic-statement.obligation {{
                    border-left-color: #dc3545;
                }}

                .deontic-statement.permission {{
                    border-left-color: #28a745;
                }}

                .deontic-statement.prohibition {{
                    border-left-color: #ffc107;
                }}

                .formal-logic {{
                    font-family: 'Courier New', monospace;
                    background: #2c3e50;
                    color: #ecf0f1;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 10px 0;
                    font-size: 0.9em;
                    overflow-x: auto;
                }}

                .logic-explanation {{
                    font-size: 0.9em;
                    color: #6c757d;
                    margin-top: 8px;
                    font-style: italic;
                }}

                /* Citation Network Styles */
                #citation-network {{
                    width: 100%;
                    height: 400px;
                    border: 1px solid #e9ecef;
                    border-radius: 8px;
                    margin: 20px 0;
                }}

                .citation-stats {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 15px;
                    margin: 20px 0;
                }}

                .citation-stat {{
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 8px;
                    text-align: center;
                    border-left: 4px solid #007bff;
                }}

                .citation-stat-value {{
                    font-size: 1.5em;
                    font-weight: bold;
                    color: #495057;
                }}

                .citation-stat-label {{
                    font-size: 0.9em;
                    color: #6c757d;
                    margin-top: 5px;
                }}

                /* Quote Panel Styles */
                .quote-item {{
                    background: #f8f9fa;
                    border-left: 4px solid #17a2b8;
                    padding: 20px;
                    margin: 15px 0;
                    border-radius: 0 8px 8px 0;
                    position: relative;
                }}

                .quote-text {{
                    font-style: italic;
                    font-size: 1.1em;
                    line-height: 1.6;
                    color: #495057;
                    margin-bottom: 15px;
                }}

                .quote-citation {{
                    font-size: 0.9em;
                    color: #6c757d;
                    margin-bottom: 10px;
                }}

                .quote-meta {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    font-size: 0.85em;
                    color: #6c757d;
                }}

                .quote-type {{
                    background: #e9ecef;
                    padding: 4px 8px;
                    border-radius: 12px;
                    font-weight: 500;
                    text-transform: uppercase;
                }}

                .quote-type.holding {{
                    background: #dc3545;
                    color: white;
                }}

                .quote-type.rationale {{
                    background: #28a745;
                    color: white;
                }}

                .quote-type.dicta {{
                    background: #ffc107;
                    color: #212529;
                }}

                .central-holding {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    border-radius: 10px;
                    margin: 20px 0;
                }}

                .central-holding h3 {{
                    margin: 0 0 15px 0;
                    font-size: 1.2em;
                }}

                .holding-text {{
                    font-size: 1.1em;
                    line-height: 1.6;
                    font-style: italic;
                }}

                .quotes-by-principle {{
                    margin: 20px 0;
                }}

                .principle-group {{
                    background: white;
                    border: 1px solid #e9ecef;
                    border-radius: 10px;
                    margin: 15px 0;
                    overflow: hidden;
                }}

                .principle-header {{
                    background: #f8f9fa;
                    padding: 15px 20px;
                    border-bottom: 1px solid #e9ecef;
                    font-weight: 600;
                    color: #495057;
                    cursor: pointer;
                    transition: background-color 0.3s ease;
                }}

                .principle-header:hover {{
                    background: #e9ecef;
                }}

                .principle-quotes {{
                    padding: 0;
                }}

                .expandable {{
                    cursor: pointer;
                    user-select: none;
                }}

                .expandable::after {{
                    content: ' ▼';
                    float: right;
                    transition: transform 0.3s ease;
                }}

                .expandable.collapsed::after {{
                    transform: rotate(-90deg);
                }}

                .collapsible {{
                    max-height: 0;
                    overflow: hidden;
                    transition: max-height 0.3s ease;
                }}

                .collapsible.expanded {{
                    max-height: 1000px;
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
                        <!-- Tab Navigation -->
                        <div class="tab-navigation">
                            <button class="tab-button active" data-tab="summary">📋 Case Summary</button>
                            <button class="tab-button" data-tab="deontic">⚖️ Deontic Logic</button>
                            <button class="tab-button" data-tab="citations">🔗 Citation Network</button>
                            <button class="tab-button" data-tab="quotes">💬 Subsequent Quotes</button>
                        </div>

                        <!-- Tab Content -->
                        <div class="tab-content active" id="summary-tab">
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

                        <div class="tab-content" id="deontic-tab">
                            <div class="section">
                                <h2>⚖️ Deontic First-Order Logic Analysis</h2>
                                <div class="loading-message">Loading deontic logic analysis...</div>
                                <div id="deontic-content" style="display: none;"></div>
                            </div>
                        </div>

                        <div class="tab-content" id="citations-tab">
                            <div class="section">
                                <h2>🔗 Citation Network & Connections</h2>
                                <div class="loading-message">Loading citation network...</div>
                                <div id="citations-content" style="display: none;"></div>
                            </div>
                        </div>

                        <div class="tab-content" id="quotes-tab">
                            <div class="section">
                                <h2>💬 Subsequent Quotes & Central Holdings</h2>
                                <div class="loading-message">Loading subsequent quotes...</div>
                                <div id="quotes-content" style="display: none;"></div>
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
                const caseId = '{case.get("id", "")}';
                
                // Tab switching functionality
                document.querySelectorAll('.tab-button').forEach(button => {{
                    button.addEventListener('click', function() {{
                        const tabName = this.getAttribute('data-tab');
                        
                        // Update active button
                        document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
                        this.classList.add('active');
                        
                        // Update active content
                        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
                        document.getElementById(tabName + '-tab').classList.add('active');
                        
                        // Load content for the tab
                        loadTabContent(tabName);
                    }});
                }});
                
                // Load content for different tabs
                function loadTabContent(tabName) {{
                    switch(tabName) {{
                        case 'deontic':
                            loadDeonticLogic();
                            break;
                        case 'citations':
                            loadCitationNetwork();
                            break;
                        case 'quotes':
                            loadSubsequentQuotes();
                            break;
                    }}
                }}
                
                // Load deontic logic analysis
                function loadDeonticLogic() {{
                    const contentDiv = document.getElementById('deontic-content');
                    const loadingDiv = document.querySelector('#deontic-tab .loading-message');
                    
                    if (contentDiv.innerHTML.trim() !== '') {{
                        contentDiv.style.display = 'block';
                        loadingDiv.style.display = 'none';
                        return;
                    }}
                    
                    fetch(`/api/case/${{caseId}}/deontic-logic`)
                        .then(response => response.json())
                        .then(data => {{
                            loadingDiv.style.display = 'none';
                            if (data.status === 'success') {{
                                renderDeonticLogic(data.deontic_analysis);
                            }} else {{
                                contentDiv.innerHTML = `<div class="error-message">Error loading deontic logic: ${{data.message}}</div>`;
                            }}
                            contentDiv.style.display = 'block';
                        }})
                        .catch(error => {{
                            loadingDiv.style.display = 'none';
                            contentDiv.innerHTML = `<div class="error-message">Failed to load deontic logic analysis</div>`;
                            contentDiv.style.display = 'block';
                        }});
                }}
                
                // Load citation network
                function loadCitationNetwork() {{
                    const contentDiv = document.getElementById('citations-content');
                    const loadingDiv = document.querySelector('#citations-tab .loading-message');
                    
                    if (contentDiv.innerHTML.trim() !== '') {{
                        contentDiv.style.display = 'block';
                        loadingDiv.style.display = 'none';
                        return;
                    }}
                    
                    fetch(`/api/case/${{caseId}}/citations`)
                        .then(response => response.json())
                        .then(data => {{
                            loadingDiv.style.display = 'none';
                            if (data.status === 'success') {{
                                renderCitationNetwork(data.citation_network, data.citation_details);
                            }} else {{
                                contentDiv.innerHTML = `<div class="error-message">Error loading citations: ${{data.message}}</div>`;
                            }}
                            contentDiv.style.display = 'block';
                        }})
                        .catch(error => {{
                            loadingDiv.style.display = 'none';
                            contentDiv.innerHTML = `<div class="error-message">Failed to load citation network</div>`;
                            contentDiv.style.display = 'block';
                        }});
                }}
                
                // Load subsequent quotes
                function loadSubsequentQuotes() {{
                    const contentDiv = document.getElementById('quotes-content');
                    const loadingDiv = document.querySelector('#quotes-tab .loading-message');
                    
                    if (contentDiv.innerHTML.trim() !== '') {{
                        contentDiv.style.display = 'block';
                        loadingDiv.style.display = 'none';
                        return;
                    }}
                    
                    fetch(`/api/case/${{caseId}}/subsequent-quotes`)
                        .then(response => response.json())
                        .then(data => {{
                            loadingDiv.style.display = 'none';
                            if (data.status === 'success') {{
                                renderSubsequentQuotes(data.subsequent_quotes);
                            }} else {{
                                contentDiv.innerHTML = `<div class="error-message">Error loading quotes: ${{data.message}}</div>`;
                            }}
                            contentDiv.style.display = 'block';
                        }})
                        .catch(error => {{
                            loadingDiv.style.display = 'none';
                            contentDiv.innerHTML = `<div class="error-message">Failed to load subsequent quotes</div>`;
                            contentDiv.style.display = 'block';
                        }});
                }}
                
                // Render deontic logic analysis
                function renderDeonticLogic(analysis) {{
                    const contentDiv = document.getElementById('deontic-content');
                    let html = '';
                    
                    // Central holdings
                    if (analysis.central_holdings && analysis.central_holdings.length > 0) {{
                        html += '<div class="central-holding">';
                        html += '<h3>🎯 Central Legal Holdings</h3>';
                        analysis.central_holdings.forEach(holding => {{
                            html += `<div class="holding-text">"${{holding.holding_text}}"</div>`;
                            if (holding.type) {{
                                html += `<div style="margin-top: 10px; font-size: 0.9em; opacity: 0.8;">Type: ${{holding.type}} (Confidence: ${{Math.round((holding.confidence || 0.5) * 100)}}%)</div>`;
                            }}
                        }});
                        html += '</div>';
                    }}
                    
                    // Deontic statements
                    if (analysis.deontic_statements && analysis.deontic_statements.length > 0) {{
                        html += '<h3>📜 Deontic Statements</h3>';
                        analysis.deontic_statements.forEach(statement => {{
                            html += `<div class="deontic-statement ${{statement.type}}">`;
                            html += `<strong>${{statement.type.toUpperCase()}}</strong>: ${{statement.content}}`;
                            html += `<div class="logic-explanation">Confidence: ${{Math.round((statement.confidence || 0.5) * 100)}}%</div>`;
                            html += '</div>';
                        }});
                    }}
                    
                    // Formal logic expressions
                    if (analysis.formal_logic_expressions && analysis.formal_logic_expressions.length > 0) {{
                        html += '<h3>🔬 Formal Logic Expressions</h3>';
                        analysis.formal_logic_expressions.forEach(expr => {{
                            html += '<div style="margin: 15px 0;">';
                            html += `<div class="formal-logic">${{expr.formal_statement}}</div>`;
                            html += `<div class="logic-explanation">${{expr.natural_language}}</div>`;
                            html += '</div>';
                        }});
                    }}
                    
                    // Legal modalities
                    if (analysis.legal_modalities) {{
                        html += '<h3>⚖️ Legal Modality Distribution</h3>';
                        html += '<div class="citation-stats">';
                        Object.entries(analysis.legal_modalities).forEach(([modality, count]) => {{
                            html += '<div class="citation-stat">';
                            html += `<div class="citation-stat-value">${{count}}</div>`;
                            html += `<div class="citation-stat-label">${{modality.charAt(0).toUpperCase() + modality.slice(1)}}s</div>`;
                            html += '</div>';
                        }});
                        html += '</div>';
                    }}
                    
                    // Precedential strength
                    if (analysis.precedential_strength) {{
                        const strength = analysis.precedential_strength;
                        html += '<h3>💪 Precedential Strength Analysis</h3>';
                        html += '<div class="deontic-statement">';
                        html += `<strong>Strength Level:</strong> ${{strength.strength_level}} (${{Math.round(strength.strength_score * 100)}}%)<br>`;
                        html += `<strong>Court:</strong> ${{strength.court}}<br>`;
                        html += `<strong>Binding Scope:</strong> ${{strength.binding_scope}}`;
                        html += '</div>';
                    }}
                    
                    if (!html) {{
                        html = '<div class="no-data">No deontic logic analysis available for this case.</div>';
                    }}
                    
                    contentDiv.innerHTML = html;
                }}
                
                // Render citation network
                function renderCitationNetwork(network, details) {{
                    const contentDiv = document.getElementById('citations-content');
                    let html = '';
                    
                    // Statistics
                    if (network.statistics) {{
                        html += '<div class="citation-stats">';
                        html += `<div class="citation-stat">
                            <div class="citation-stat-value">${{network.statistics.total_citations}}</div>
                            <div class="citation-stat-label">Cases Cited</div>
                        </div>`;
                        html += `<div class="citation-stat">
                            <div class="citation-stat-value">${{network.statistics.total_cited_by}}</div>
                            <div class="citation-stat-label">Citing Cases</div>
                        </div>`;
                        html += `<div class="citation-stat">
                            <div class="citation-stat-value">${{network.statistics.related_cases}}</div>
                            <div class="citation-stat-label">Related Cases</div>
                        </div>`;
                        html += `<div class="citation-stat">
                            <div class="citation-stat-value">${{Math.round(network.statistics.network_density * 100)}}%</div>
                            <div class="citation-stat-label">Network Density</div>
                        </div>`;
                        html += '</div>';
                    }}
                    
                    // Network visualization placeholder
                    html += '<div id="citation-network"><div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #6c757d;">Citation Network Visualization<br><small>(Interactive graph would be rendered here with proper visualization library)</small></div></div>';
                    
                    // Citation details
                    if (details) {{
                        if (details.backward_citations && details.backward_citations.length > 0) {{
                            html += '<h3>📉 Cases Cited by This Case</h3>';
                            details.backward_citations.forEach(caseItem => {{
                                html += renderCitationCase(caseItem, 'cited');
                            }});
                        }}
                        
                        if (details.forward_citations && details.forward_citations.length > 0) {{
                            html += '<h3>📈 Cases Citing This Case</h3>';
                            details.forward_citations.forEach(caseItem => {{
                                html += renderCitationCase(caseItem, 'citing');
                            }});
                        }}
                        
                        if (details.related_cases && details.related_cases.length > 0) {{
                            html += '<h3>🔗 Topically Related Cases</h3>';
                            details.related_cases.forEach(caseItem => {{
                                html += renderCitationCase(caseItem, 'related');
                            }});
                        }}
                    }}
                    
                    if (!html || html.trim() === '') {{
                        html = '<div class="no-data">No citation network data available for this case.</div>';
                    }}
                    
                    contentDiv.innerHTML = html;
                }}
                
                // Render a citation case item
                function renderCitationCase(caseItem, type) {{
                    return `<div class="shepherding-case ${{type}}" data-case-id="${{caseItem.id}}">
                        <div class="shepherding-title">${{caseItem.title || 'Unknown Case'}}</div>
                        <div class="shepherding-meta">
                            <span>${{caseItem.citation || 'No citation'}}</span>
                            <span>${{caseItem.year || 'Unknown year'}}</span>
                            <span>${{caseItem.court || 'Unknown court'}}</span>
                        </div>
                    </div>`;
                }}
                
                // Render subsequent quotes
                function renderSubsequentQuotes(quotes) {{
                    const contentDiv = document.getElementById('quotes-content');
                    let html = '';
                    
                    // Central holdings
                    if (quotes.central_holdings && quotes.central_holdings.length > 0) {{
                        html += '<div class="central-holding">';
                        html += '<h3>🎯 Central Holdings of This Case</h3>';
                        quotes.central_holdings.forEach(holding => {{
                            html += `<div class="holding-text">"${{holding.holding_text}}"</div>`;
                        }});
                        html += '</div>';
                    }}
                    
                    // Quote analysis summary
                    if (quotes.quote_analysis) {{
                        html += '<div class="citation-stats">';
                        html += `<div class="citation-stat">
                            <div class="citation-stat-value">${{quotes.total_quotes}}</div>
                            <div class="citation-stat-label">Total Quotes</div>
                        </div>`;
                        html += `<div class="citation-stat">
                            <div class="citation-stat-value">${{quotes.citing_cases_count}}</div>
                            <div class="citation-stat-label">Citing Cases</div>
                        </div>`;
                        if (quotes.quote_analysis.temporal_span) {{
                            html += `<div class="citation-stat">
                                <div class="citation-stat-value">${{quotes.quote_analysis.temporal_span.span_years}}</div>
                                <div class="citation-stat-label">Years Span</div>
                            </div>`;
                        }}
                        html += '</div>';
                    }}
                    
                    // Most quoted holding
                    if (quotes.quote_analysis && quotes.quote_analysis.most_quoted_holding) {{
                        html += '<div class="central-holding">';
                        html += '<h3>🔥 Most Quoted Holding</h3>';
                        html += `<div class="holding-text">"${{quotes.quote_analysis.most_quoted_holding}}"</div>`;
                        html += '</div>';
                    }}
                    
                    // Grouped quotes by principle
                    if (quotes.grouped_quotes) {{
                        html += '<h3>💬 Quotes Grouped by Legal Principle</h3>';
                        html += '<div class="quotes-by-principle">';
                        
                        Object.entries(quotes.grouped_quotes).forEach(([principle, principleQuotes]) => {{
                            html += '<div class="principle-group">';
                            html += `<div class="principle-header expandable" onclick="togglePrinciple(this)">
                                ${{principle}} (${{principleQuotes.length}} quotes)
                            </div>`;
                            html += '<div class="principle-quotes collapsible">';
                            
                            principleQuotes.forEach(quote => {{
                                html += `<div class="quote-item">
                                    <div class="quote-text">"${{quote.quote_text}}"</div>
                                    <div class="quote-citation">
                                        <strong>${{quote.citing_case.title}}</strong>, ${{quote.citing_case.citation}} (${{quote.citing_case.year}})
                                    </div>
                                    <div class="quote-meta">
                                        <span class="quote-type ${{quote.quote_type}}">${{quote.quote_type}}</span>
                                        <span>Relevance: ${{Math.round((quote.relevance_score || 0) * 100)}}%</span>
                                    </div>
                                </div>`;
                            }});
                            
                            html += '</div></div>';
                        }});
                        
                        html += '</div>';
                    }}
                    
                    // All quotes (if no grouping available)
                    else if (quotes.all_quotes && quotes.all_quotes.length > 0) {{
                        html += '<h3>💬 All Subsequent Quotes</h3>';
                        quotes.all_quotes.forEach(quote => {{
                            html += `<div class="quote-item">
                                <div class="quote-text">"${{quote.quote_text}}"</div>
                                <div class="quote-citation">
                                    <strong>${{quote.citing_case.title}}</strong>, ${{quote.citing_case.citation}} (${{quote.citing_case.year}})
                                </div>
                                <div class="quote-meta">
                                    <span class="quote-type ${{quote.quote_type}}">${{quote.quote_type}}</span>
                                    <span>Relevance: ${{Math.round((quote.relevance_score || 0) * 100)}}%</span>
                                </div>
                            </div>`;
                        }});
                    }}
                    
                    if (!html) {{
                        html = '<div class="no-data">No subsequent quotes found for this case.</div>';
                    }}
                    
                    contentDiv.innerHTML = html;
                }}
                
                // Toggle principle group visibility
                function togglePrinciple(header) {{
                    const content = header.nextElementSibling;
                    const isExpanded = content.classList.contains('expanded');
                    
                    if (isExpanded) {{
                        content.classList.remove('expanded');
                        header.classList.add('collapsed');
                    }} else {{
                        content.classList.add('expanded');
                        header.classList.remove('collapsed');
                    }}
                }}
                
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
                
                // Handle dynamically added case links
                document.addEventListener('click', function(e) {{
                    if (e.target.closest('.shepherding-case')) {{
                        const caseElement = e.target.closest('.shepherding-case');
                        const caseId = caseElement.getAttribute('data-case-id');
                        if (caseId && caseId !== caseId) {{ // Avoid self-reference
                            window.location.href = `/case/${{caseId}}`;
                        }}
                    }}
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
    
    def _get_case_deontic_logic(self, case_id: str) -> Dict[str, Any]:
        """Generate deontic first-order logic analysis for a specific case"""
        try:
            # Find the case in processed data
            case_data = None
            if self.processed_data and 'cases' in self.processed_data:
                for case in self.processed_data['cases']:
                    if str(case.get('id', '')) == str(case_id):
                        case_data = case
                        break
            
            if not case_data:
                return {
                    'status': 'error',
                    'message': 'Case not found'
                }
            
            # Extract legal text content
            legal_text = case_data.get('content', '') or case_data.get('summary', '') or case_data.get('text', '')
            if not legal_text:
                legal_text = case_data.get('title', '') + " - " + case_data.get('citation', '')
            
            # Generate deontic logic analysis
            deontic_statements = self._extract_deontic_statements(legal_text, case_data)
            formal_logic = self._convert_to_formal_logic(deontic_statements, case_data)
            temporal_constraints = self._extract_temporal_constraints(legal_text, case_data)
            
            return {
                'status': 'success',
                'case_id': case_id,
                'case_name': case_data.get('title', 'Unknown Case'),
                'deontic_analysis': {
                    'deontic_statements': deontic_statements,
                    'formal_logic_expressions': formal_logic,
                    'temporal_constraints': temporal_constraints,
                    'legal_modalities': self._identify_legal_modalities(deontic_statements),
                    'precedential_strength': self._assess_precedential_strength(case_data),
                    'central_holdings': self._extract_central_holdings(legal_text, case_data)
                }
            }
        except Exception as e:
            logger.error(f"Error generating deontic logic for case {case_id}: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _get_case_citation_network(self, case_id: str) -> Dict[str, Any]:
        """Get citation connections and network visualization data for a case"""
        try:
            # Find the case in processed data
            case_data = None
            if self.processed_data and 'cases' in self.processed_data:
                for case in self.processed_data['cases']:
                    if str(case.get('id', '')) == str(case_id):
                        case_data = case
                        break
            
            if not case_data:
                return {
                    'status': 'error',
                    'message': 'Case not found'
                }
            
            # Build citation network
            cited_by = self._get_cases_citing_this(case_id)
            cites_to = self._get_cases_cited_by_this(case_id)
            related_cases = self._get_topically_related_cases(case_id)
            
            # Create network graph data
            nodes = []
            edges = []
            
            # Add central case node
            nodes.append({
                'id': case_id,
                'label': case_data.get('title', 'Unknown Case')[:50] + '...',
                'type': 'central',
                'citation': case_data.get('citation', ''),
                'year': case_data.get('year', ''),
                'court': case_data.get('court', ''),
                'size': 20,
                'color': '#e74c3c'
            })
            
            # Add cited cases (backward citations)
            for case in cites_to:
                nodes.append({
                    'id': case.get('id', ''),
                    'label': case.get('title', '')[:50] + '...',
                    'type': 'cited',
                    'citation': case.get('citation', ''),
                    'year': case.get('year', ''),
                    'court': case.get('court', ''),
                    'size': 15,
                    'color': '#3498db'
                })
                edges.append({
                    'from': case_id,
                    'to': case.get('id', ''),
                    'type': 'cites',
                    'label': 'cites'
                })
            
            # Add citing cases (forward citations)
            for case in cited_by:
                nodes.append({
                    'id': case.get('id', ''),
                    'label': case.get('title', '')[:50] + '...',
                    'type': 'citing',
                    'citation': case.get('citation', ''),
                    'year': case.get('year', ''),
                    'court': case.get('court', ''),
                    'size': 15,
                    'color': '#2ecc71'
                })
                edges.append({
                    'from': case.get('id', ''),
                    'to': case_id,
                    'type': 'cites',
                    'label': 'cites'
                })
            
            return {
                'status': 'success',
                'case_id': case_id,
                'case_name': case_data.get('title', 'Unknown Case'),
                'citation_network': {
                    'nodes': nodes,
                    'edges': edges,
                    'statistics': {
                        'total_citations': len(cites_to),
                        'total_cited_by': len(cited_by),
                        'related_cases': len(related_cases),
                        'network_density': len(edges) / max(len(nodes) * (len(nodes) - 1), 1)
                    }
                },
                'citation_details': {
                    'backward_citations': cites_to,
                    'forward_citations': cited_by,
                    'related_cases': related_cases
                }
            }
        except Exception as e:
            logger.error(f"Error generating citation network for case {case_id}: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _get_case_subsequent_quotes(self, case_id: str) -> Dict[str, Any]:
        """Get quotes from subsequent cases that cite this case"""
        try:
            # Find the case in processed data
            case_data = None
            if self.processed_data and 'cases' in self.processed_data:
                for case in self.processed_data['cases']:
                    if str(case.get('id', '')) == str(case_id):
                        case_data = case
                        break
            
            if not case_data:
                return {
                    'status': 'error',
                    'message': 'Case not found'
                }
            
            # Get cases that cite this case
            citing_cases = self._get_cases_citing_this(case_id)
            
            # Extract quotes and their context
            quotes_data = []
            central_holdings = self._extract_central_holdings(
                case_data.get('content', '') or case_data.get('summary', ''), 
                case_data
            )
            
            for citing_case in citing_cases:
                quotes = self._extract_quotes_about_case(citing_case, case_data, central_holdings)
                if quotes:
                    for quote in quotes:
                        quotes_data.append({
                            'quote_text': quote['text'],
                            'context': quote['context'],
                            'citing_case': {
                                'id': citing_case.get('id', ''),
                                'title': citing_case.get('title', ''),
                                'citation': citing_case.get('citation', ''),
                                'year': citing_case.get('year', ''),
                                'court': citing_case.get('court', '')
                            },
                            'quote_type': quote['type'],  # 'holding', 'rationale', 'dicta'
                            'relevance_score': quote.get('relevance_score', 0.0),
                            'legal_principle': quote.get('legal_principle', '')
                        })
            
            # Sort by relevance and group by legal principle
            quotes_data.sort(key=lambda x: x['relevance_score'], reverse=True)
            
            # Group quotes by legal principle
            grouped_quotes = defaultdict(list)
            for quote in quotes_data:
                principle = quote['legal_principle'] or 'General Citation'
                grouped_quotes[principle].append(quote)
            
            return {
                'status': 'success',
                'case_id': case_id,
                'case_name': case_data.get('title', 'Unknown Case'),
                'subsequent_quotes': {
                    'total_quotes': len(quotes_data),
                    'citing_cases_count': len(citing_cases),
                    'grouped_quotes': dict(grouped_quotes),
                    'all_quotes': quotes_data[:50],  # Limit to 50 most relevant
                    'central_holdings': central_holdings,
                    'quote_analysis': {
                        'most_quoted_holding': self._find_most_quoted_holding(quotes_data),
                        'citation_frequency': len(citing_cases),
                        'temporal_span': self._calculate_citation_temporal_span(citing_cases)
                    }
                }
            }
        except Exception as e:
            logger.error(f"Error generating subsequent quotes for case {case_id}: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    # Helper methods for the new functionality
    def _extract_deontic_statements(self, legal_text: str, case_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract deontic statements from legal text"""
        statements = []
        
        # Look for obligation patterns
        obligation_patterns = [
            r'must\s+([^.]+)',
            r'shall\s+([^.]+)',
            r'required\s+to\s+([^.]+)',
            r'obligated\s+to\s+([^.]+)',
            r'duty\s+to\s+([^.]+)'
        ]
        
        # Look for permission patterns  
        permission_patterns = [
            r'may\s+([^.]+)',
            r'permitted\s+to\s+([^.]+)',
            r'authorized\s+to\s+([^.]+)',
            r'right\s+to\s+([^.]+)'
        ]
        
        # Look for prohibition patterns
        prohibition_patterns = [
            r'cannot\s+([^.]+)',
            r'shall\s+not\s+([^.]+)',
            r'prohibited\s+from\s+([^.]+)',
            r'forbidden\s+to\s+([^.]+)',
            r'no\s+right\s+to\s+([^.]+)'
        ]
        
        for pattern in obligation_patterns:
            matches = re.finditer(pattern, legal_text, re.IGNORECASE)
            for match in matches:
                statements.append({
                    'type': 'obligation',
                    'content': match.group(1).strip(),
                    'full_text': match.group(0),
                    'position': match.start(),
                    'confidence': 0.8
                })
        
        for pattern in permission_patterns:
            matches = re.finditer(pattern, legal_text, re.IGNORECASE)
            for match in matches:
                statements.append({
                    'type': 'permission',
                    'content': match.group(1).strip(),
                    'full_text': match.group(0),
                    'position': match.start(),
                    'confidence': 0.7
                })
        
        for pattern in prohibition_patterns:
            matches = re.finditer(pattern, legal_text, re.IGNORECASE)
            for match in matches:
                statements.append({
                    'type': 'prohibition',
                    'content': match.group(1).strip(),
                    'full_text': match.group(0),
                    'position': match.start(),
                    'confidence': 0.8
                })
        
        return statements[:10]  # Return top 10 statements
    
    def _convert_to_formal_logic(self, deontic_statements: List[Dict[str, Any]], case_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert deontic statements to formal logic expressions"""
        formal_expressions = []
        
        for i, statement in enumerate(deontic_statements):
            content_preview = statement['content'][:30] + ('...' if len(statement['content']) > 30 else '')
            
            if statement['type'] == 'obligation':
                formal = f"O({content_preview})"
                natural = f"It is obligatory that {statement['content']}"
            elif statement['type'] == 'permission':
                formal = f"P({content_preview})"
                natural = f"It is permitted that {statement['content']}"
            elif statement['type'] == 'prohibition':
                formal = f"F({content_preview})"
                natural = f"It is forbidden that {statement['content']}"
            else:
                formal = f"L({content_preview})"
                natural = f"Legal statement: {statement['content']}"
            
            formal_expressions.append({
                'id': f"expr_{i}",
                'formal_statement': formal,
                'natural_language': natural,
                'original_statement': statement,
                'confidence': statement.get('confidence', 0.5),
                'temporal_scope': 'present'  # Could be enhanced with temporal analysis
            })
        
        return formal_expressions
    
    def _extract_temporal_constraints(self, legal_text: str, case_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract temporal constraints from legal text"""
        constraints = []
        
        temporal_patterns = [
            r'after\s+([^.]+)',
            r'before\s+([^.]+)', 
            r'during\s+([^.]+)',
            r'within\s+(\d+\s+\w+)',
            r'until\s+([^.]+)',
            r'from\s+([^.]+)\s+to\s+([^.]+)'
        ]
        
        for pattern in temporal_patterns:
            matches = re.finditer(pattern, legal_text, re.IGNORECASE)
            for match in matches:
                constraints.append({
                    'type': 'temporal',
                    'constraint': match.group(1).strip() if len(match.groups()) == 1 else f"{match.group(1)} to {match.group(2)}",
                    'full_text': match.group(0),
                    'temporal_operator': match.group(0).split()[0].lower()
                })
        
        return constraints[:5]  # Return top 5 constraints
    
    def _identify_legal_modalities(self, deontic_statements: List[Dict[str, Any]]) -> Dict[str, int]:
        """Identify and count legal modalities in the statements"""
        modalities = defaultdict(int)
        for statement in deontic_statements:
            modalities[statement['type']] += 1
        return dict(modalities)
    
    def _assess_precedential_strength(self, case_data: Dict[str, Any]) -> Dict[str, Any]:
        """Assess the precedential strength of a case"""
        court = case_data.get('court', '').lower()
        
        if 'supreme court' in court:
            strength = 'highest'
            score = 1.0
        elif 'circuit' in court or 'appeals' in court:
            strength = 'high'
            score = 0.8
        elif 'district' in court:
            strength = 'moderate'
            score = 0.6
        else:
            strength = 'unknown'
            score = 0.5
        
        return {
            'strength_level': strength,
            'strength_score': score,
            'court': case_data.get('court', ''),
            'binding_scope': self._determine_binding_scope(court)
        }
    
    def _determine_binding_scope(self, court: str) -> str:
        """Determine the binding scope of a court's decision"""
        court_lower = court.lower()
        if 'supreme court' in court_lower:
            return 'nationwide'
        elif 'circuit' in court_lower:
            return 'regional'
        elif 'district' in court_lower:
            return 'local'
        else:
            return 'limited'
    
    def _extract_central_holdings(self, legal_text: str, case_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract the central legal holdings from a case"""
        holdings = []
        
        # Look for holding indicators
        holding_patterns = [
            r'we\s+hold\s+that\s+([^.]+)',
            r'the\s+court\s+holds\s+that\s+([^.]+)',
            r'it\s+is\s+held\s+that\s+([^.]+)',
            r'our\s+holding\s+is\s+that\s+([^.]+)'
        ]
        
        for pattern in holding_patterns:
            matches = re.finditer(pattern, legal_text, re.IGNORECASE)
            for match in matches:
                holdings.append({
                    'holding_text': match.group(1).strip(),
                    'full_statement': match.group(0),
                    'type': 'primary_holding',
                    'confidence': 0.9
                })
        
        # If no explicit holdings found, extract key legal principles
        if not holdings:
            principle_patterns = [
                r'the\s+principle\s+that\s+([^.]+)',
                r'establishes\s+that\s+([^.]+)',
                r'requires\s+that\s+([^.]+)'
            ]
            
            for pattern in principle_patterns:
                matches = re.finditer(pattern, legal_text, re.IGNORECASE)
                for match in matches:
                    holdings.append({
                        'holding_text': match.group(1).strip(),
                        'full_statement': match.group(0),
                        'type': 'legal_principle',
                        'confidence': 0.7
                    })
        
        return holdings[:3]  # Return top 3 holdings
    
    def _get_cases_citing_this(self, case_id: str) -> List[Dict[str, Any]]:
        """Get cases that cite the given case"""
        citing_cases = []
        if not self.processed_data or 'cases' not in self.processed_data:
            return citing_cases
        
        # Simple implementation - in practice would use citation analysis
        target_case = None
        for case in self.processed_data['cases']:
            if str(case.get('id', '')) == str(case_id):
                target_case = case
                break
        
        if not target_case:
            return citing_cases
        
        target_citation = target_case.get('citation', '')
        target_title = target_case.get('title', '')
        
        for case in self.processed_data['cases'][:50]:  # Limit search
            if str(case.get('id', '')) == str(case_id):
                continue
                
            case_text = (case.get('content', '') + ' ' + case.get('summary', '')).lower()
            
            # Check if this case mentions the target case
            if (target_citation.lower() in case_text or 
                target_title.lower() in case_text or
                any(word in case_text for word in target_title.lower().split() if len(word) > 3)):
                citing_cases.append(case)
        
        return citing_cases[:10]  # Return up to 10 citing cases
    
    def _get_cases_cited_by_this(self, case_id: str) -> List[Dict[str, Any]]:
        """Get cases cited by the given case"""
        cited_cases = []
        if not self.processed_data or 'cases' not in self.processed_data:
            return cited_cases
        
        # Find the target case
        target_case = None
        for case in self.processed_data['cases']:
            if str(case.get('id', '')) == str(case_id):
                target_case = case
                break
        
        if not target_case:
            return cited_cases
        
        target_text = (target_case.get('content', '') + ' ' + target_case.get('summary', '')).lower()
        
        # Look for citations in the target case text
        for case in self.processed_data['cases'][:50]:  # Limit search
            if str(case.get('id', '')) == str(case_id):
                continue
                
            case_citation = case.get('citation', '')
            case_title = case.get('title', '')
            
            # Check if target case cites this case
            if (case_citation.lower() in target_text or
                case_title.lower() in target_text or
                any(word in target_text for word in case_title.lower().split() if len(word) > 3)):
                cited_cases.append(case)
        
        return cited_cases[:10]  # Return up to 10 cited cases
    
    def _get_topically_related_cases(self, case_id: str) -> List[Dict[str, Any]]:
        """Get topically related cases"""
        # This would use the existing similarity search functionality
        try:
            relationships = self.processor.get_case_relationships(case_id)
            if relationships['status'] == 'success':
                return relationships.get('similar_cases', [])[:5]
        except:
            pass
        return []
    
    def _extract_quotes_about_case(self, citing_case: Dict[str, Any], cited_case: Dict[str, Any], central_holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract quotes from citing case about the cited case"""
        quotes = []
        citing_text = citing_case.get('content', '') or citing_case.get('summary', '')
        cited_title = cited_case.get('title', '')
        cited_citation = cited_case.get('citation', '')
        
        if not citing_text:
            return quotes
        
        # Split into sentences
        sentences = re.split(r'[.!?]+', citing_text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:  # Skip very short sentences
                continue
                
            # Check if sentence mentions the cited case
            if (cited_title.lower() in sentence.lower() or 
                cited_citation.lower() in sentence.lower()):
                
                # Determine quote type and relevance
                quote_type = 'general'
                relevance_score = 0.5
                legal_principle = ''
                
                # Check for holding references
                if any(word in sentence.lower() for word in ['held', 'holding', 'ruled', 'decided']):
                    quote_type = 'holding'
                    relevance_score = 0.9
                elif any(word in sentence.lower() for word in ['rationale', 'reasoning', 'because']):
                    quote_type = 'rationale'
                    relevance_score = 0.7
                elif any(word in sentence.lower() for word in ['dicta', 'noted', 'observed']):
                    quote_type = 'dicta'
                    relevance_score = 0.4
                
                # Try to match with central holdings
                for holding in central_holdings:
                    if any(word in sentence.lower() for word in holding['holding_text'].lower().split() if len(word) > 3):
                        legal_principle = holding['holding_text'][:100] + '...'
                        relevance_score = min(relevance_score + 0.2, 1.0)
                        break
                
                quotes.append({
                    'text': sentence,
                    'context': self._extract_quote_context(citing_text, sentence),
                    'type': quote_type,
                    'relevance_score': relevance_score,
                    'legal_principle': legal_principle
                })
        
        return quotes[:5]  # Return up to 5 quotes per case
    
    def _extract_quote_context(self, full_text: str, quote: str) -> str:
        """Extract context around a quote"""
        try:
            start_pos = full_text.find(quote)
            if start_pos == -1:
                return ""
            
            # Get surrounding text (100 chars before and after)
            context_start = max(0, start_pos - 100)
            context_end = min(len(full_text), start_pos + len(quote) + 100)
            
            context = full_text[context_start:context_end]
            if context_start > 0:
                context = "..." + context
            if context_end < len(full_text):
                context = context + "..."
            
            return context.strip()
        except:
            return ""
    
    def _find_most_quoted_holding(self, quotes_data: List[Dict[str, Any]]) -> str:
        """Find the most frequently quoted holding"""
        if not quotes_data:
            return "No specific holding identified as most quoted"
        
        # Count quotes by legal principle
        principle_counts = defaultdict(int)
        for quote in quotes_data:
            principle = quote.get('legal_principle', 'General Citation')
            if principle and principle != 'General Citation':
                principle_counts[principle] += 1
        
        if principle_counts:
            return max(principle_counts.items(), key=lambda x: x[1])[0]
        else:
            return "General citation without specific holding focus"
    
    def _calculate_citation_temporal_span(self, citing_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate temporal span of citations"""
        if not citing_cases:
            return {'earliest': None, 'latest': None, 'span_years': 0}
        
        years = []
        for case in citing_cases:
            year = case.get('year')
            if year and str(year).isdigit():
                years.append(int(year))
        
        if not years:
            return {'earliest': None, 'latest': None, 'span_years': 0}
        
        earliest = min(years)
        latest = max(years)
        
        return {
            'earliest': earliest,
            'latest': latest,
            'span_years': latest - earliest,
            'citation_trend': 'increasing' if len([y for y in years if y > (earliest + latest) / 2]) > len(years) / 2 else 'decreasing'
        }
    
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
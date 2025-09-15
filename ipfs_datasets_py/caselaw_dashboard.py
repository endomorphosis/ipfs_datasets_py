"""
Caselaw Access Project GraphRAG Dashboard

This module provides a web-based dashboard for searching and exploring
the Caselaw Access Project dataset using GraphRAG capabilities.
"""

import os
import json
import logging
import asyncio
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
    
    def _create_dashboard_html(self) -> str:
        """Create the main dashboard HTML"""
        stats = self.processed_data['knowledge_graph']['statistics']
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Caselaw Access Project - GraphRAG Dashboard</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <!-- Fallback for Font Awesome icons using Unicode symbols -->
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{ 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif; 
                    margin: 0; padding: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    color: #333; line-height: 1.6;
                }}
                .header {{ 
                    background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); 
                    color: white; padding: 30px 20px; text-align: center; 
                    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                }}
                .header h1 {{ font-size: 2.5em; margin-bottom: 10px; font-weight: 700; }}
                .header p {{ font-size: 1.1em; opacity: 0.9; }}
                .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
                .stats-grid {{ 
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
                    gap: 20px; margin: 30px 0; 
                }}
                .stat-card {{ 
                    background: white; padding: 30px; border-radius: 15px; 
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1); 
                    text-align: center; transition: transform 0.3s ease, box-shadow 0.3s ease;
                }}
                .stat-card:hover {{ transform: translateY(-5px); box-shadow: 0 15px 35px rgba(0,0,0,0.15); }}
                .stat-number {{ 
                    font-size: 3em; font-weight: 900; 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                    background-clip: text; margin-bottom: 10px;
                }}
                .stat-label {{ font-size: 1.1em; color: #666; font-weight: 500; }}
                .stat-icon {{ font-size: 2.5em; margin-bottom: 15px; opacity: 0.7; }}
                /* Icon fallbacks using Unicode symbols */
                .icon-gavel:before {{ content: "⚖️"; }}
                .icon-search:before {{ content: "🔍"; }}
                .icon-chart:before {{ content: "📊"; }}
                .icon-calendar:before {{ content: "📅"; }}
                .icon-building:before {{ content: "🏛️"; }}
                .icon-law:before {{ content: "⚖️"; }}
                .icon-users:before {{ content: "👥"; }}
                .icon-network:before {{ content: "🔗"; }}
                .icon-list:before {{ content: "📋"; }}
                .icon-spinner:before {{ content: "⏳"; }}
                .search-section {{ 
                    background: white; padding: 40px; border-radius: 20px; 
                    margin: 30px 0; box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                }}
                .search-section h2 {{ 
                    margin-bottom: 25px; font-size: 1.8em; 
                    color: #2c3e50; display: flex; align-items: center; gap: 10px;
                }}
                .search-container {{ display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }}
                .search-input {{ 
                    flex: 1; min-width: 300px; padding: 15px 20px; border: 2px solid #e1e5e9; 
                    border-radius: 25px; font-size: 16px; transition: border-color 0.3s ease;
                    outline: none;
                }}
                .search-input:focus {{ border-color: #667eea; }}
                .search-button {{ 
                    padding: 15px 30px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    color: white; border: none; border-radius: 25px; cursor: pointer; 
                    font-size: 16px; font-weight: 600; transition: transform 0.3s ease;
                }}
                .search-button:hover {{ transform: translateY(-2px); }}
                .search-suggestions {{ 
                    margin-top: 15px; display: flex; gap: 10px; flex-wrap: wrap;
                    justify-content: center;
                }}
                .suggestion-tag {{ 
                    background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); 
                    padding: 10px 20px; border-radius: 25px; 
                    font-size: 0.9em; color: #495057; cursor: pointer;
                    transition: all 0.3s ease; border: 2px solid transparent;
                }}
                .suggestion-tag:hover {{ 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    color: white; transform: translateY(-2px);
                    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
                }}
                .results-section {{ 
                    background: white; padding: 30px; border-radius: 20px; 
                    margin: 30px 0; box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                }}
                .case-result {{ 
                    border-left: 5px solid #667eea; padding: 20px; margin: 15px 0; 
                    background: linear-gradient(135deg, #f8f9fa 0%, #fff 100%); 
                    border-radius: 0 10px 10px 0; transition: all 0.3s ease;
                    cursor: pointer; position: relative; overflow: hidden;
                }}
                .case-result:hover {{ 
                    transform: translateX(5px); 
                    box-shadow: 0 8px 25px rgba(102, 126, 234, 0.15);
                    border-left-color: #764ba2;
                }}
                .case-result::before {{
                    content: '';
                    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
                    background: linear-gradient(135deg, rgba(102, 126, 234, 0.05) 0%, rgba(118, 75, 162, 0.05) 100%);
                    opacity: 0; transition: opacity 0.3s ease;
                }}
                .case-result:hover::before {{ opacity: 1; }}
                .case-title {{ font-weight: 700; color: #2c3e50; margin-bottom: 8px; font-size: 1.1em; }}
                .case-citation {{
                    font-size: 0.95em;
                    color: #34495e;
                    margin-bottom: 10px;
                    font-family: 'Courier New', monospace;
                    background: #f8f9fa;
                    padding: 4px 8px;
                    border-radius: 4px;
                    border-left: 3px solid #007bff;
                }}
                .case-meta {{ 
                    color: #666; font-size: 0.95em; display: flex; 
                    align-items: center; gap: 15px; flex-wrap: wrap;
                }}
                .meta-item {{ display: flex; align-items: center; gap: 5px; }}
                .viz-section {{ 
                    background: white; padding: 40px; border-radius: 20px; 
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1); margin: 30px 0;
                }}
                .viz-section h2 {{ 
                    margin-bottom: 30px; font-size: 1.8em; color: #2c3e50; 
                    display: flex; align-items: center; gap: 10px;
                }}
                .loading {{ 
                    display: none; text-align: center; color: #666; 
                    padding: 20px; font-size: 1.1em;
                }}
                .loading i {{ animation: spin 1s linear infinite; margin-right: 10px; }}
                @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
                .no-results {{ 
                    text-align: center; padding: 40px; color: #666; 
                    background: #f8f9fa; border-radius: 15px;
                }}
                
                /* Tab Navigation Styles */
                .tab-navigation {{
                    background: white; border-radius: 15px; padding: 10px; 
                    margin: 20px 0; box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                    display: flex; gap: 10px; flex-wrap: wrap; justify-content: center;
                }}
                .tab-button {{
                    padding: 12px 24px; border-radius: 25px; border: none;
                    background: #f8f9fa; color: #495057; cursor: pointer;
                    font-weight: 500; transition: all 0.3s ease;
                }}
                .tab-button.active {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white; transform: translateY(-2px);
                }}
                .tab-button:hover:not(.active) {{
                    background: #e9ecef; transform: translateY(-1px);
                }}
                .tab-content {{
                    display: none;
                }}
                .tab-content.active {{
                    display: block;
                }}
                
                /* Tag Cloud Styles */
                .tag-cloud-section {{
                    background: white; padding: 40px; border-radius: 20px; 
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1); margin: 30px 0;
                }}
                .tag-cloud-header {{
                    margin-bottom: 30px; text-align: center;
                }}
                .doctrine-search {{
                    max-width: 500px; margin: 0 auto 30px; position: relative;
                }}
                .doctrine-search input {{
                    width: 100%; padding: 15px 20px; border: 2px solid #e1e5e9;
                    border-radius: 25px; font-size: 16px; outline: none;
                    transition: border-color 0.3s ease;
                }}
                .doctrine-search input:focus {{
                    border-color: #667eea;
                }}
                .tag-cloud {{
                    text-align: center; line-height: 2.5;
                }}
                .doctrine-tag {{
                    display: inline-block; margin: 5px; padding: 8px 16px;
                    border-radius: 20px; text-decoration: none;
                    transition: all 0.3s ease; cursor: pointer;
                    border: 2px solid transparent; font-weight: 500;
                }}
                .doctrine-tag.size-small {{
                    font-size: 0.9em; background: #f8f9fa; color: #6c757d;
                }}
                .doctrine-tag.size-medium {{
                    font-size: 1.1em; background: linear-gradient(135deg, #e3f2fd 0%, #f3e5f5 100%);
                    color: #5e35b1;
                }}
                .doctrine-tag.size-large {{
                    font-size: 1.3em; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white; font-weight: 600;
                }}
                .doctrine-tag:hover {{
                    transform: translateY(-3px) scale(1.05);
                    box-shadow: 0 8px 20px rgba(102, 126, 234, 0.3);
                }}
                .cluster-section {{
                    margin: 30px 0; padding: 25px; background: #f8f9fa;
                    border-radius: 15px; border-left: 4px solid #667eea;
                }}
                .cluster-title {{
                    font-size: 1.2em; font-weight: 600; color: #2c3e50;
                    margin-bottom: 15px; display: flex; align-items: center; gap: 10px;
                }}
                
                .footer {{ 
                    background: #2c3e50; color: white; padding: 30px 20px; 
                    text-align: center; margin-top: 50px;
                }}
                @media (max-width: 768px) {{
                    .container {{ padding: 10px; }}
                    .stats-grid {{ grid-template-columns: 1fr 1fr; }}
                    .search-container {{ flex-direction: column; }}
                    .search-input {{ min-width: auto; }}
                    .case-meta {{ flex-direction: column; align-items: flex-start; gap: 8px; }}
                    .tab-navigation {{ padding: 5px; }}
                    .tab-button {{ padding: 10px 16px; font-size: 0.9em; }}
                }}
                
                /* Temporal Deontic Logic Styles */
                .temporal-logic-section {{
                    background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                    padding: 40px; border-radius: 20px; box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                }}
                .temporal-header {{
                    text-align: center; margin-bottom: 30px;
                }}
                .temporal-header h2 {{
                    color: #2c3e50; margin-bottom: 10px;
                }}
                .doctrine-selector {{
                    background: white; padding: 25px; border-radius: 15px;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1); margin-bottom: 30px;
                    display: flex; align-items: center; gap: 15px; flex-wrap: wrap;
                }}
                .doctrine-selector label {{
                    font-weight: bold; color: #495057; min-width: 200px;
                }}
                .doctrine-selector select {{
                    flex: 1; min-width: 250px; padding: 12px; border: 2px solid #dee2e6;
                    border-radius: 8px; font-size: 16px;
                }}
                .analyze-btn {{
                    background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
                    color: white; padding: 12px 24px; border: none; border-radius: 8px;
                    cursor: pointer; font-weight: bold; transition: all 0.3s ease;
                }}
                .analyze-btn:hover {{
                    transform: translateY(-2px); box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);
                }}
                .logic-results {{
                    display: grid; gap: 30px;
                }}
                .chronological-evolution, .formal-theorems, .consistency-analysis, .proof-results {{
                    background: white; padding: 25px; border-radius: 15px;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                }}
                .timeline {{
                    display: flex; flex-direction: column; gap: 15px;
                }}
                .timeline-item {{
                    display: flex; align-items: center; gap: 20px;
                    padding: 15px; background: #f8f9fa; border-radius: 10px;
                    border-left: 4px solid #007bff;
                }}
                .timeline-date {{
                    background: #007bff; color: white; padding: 8px 12px;
                    border-radius: 20px; font-weight: bold; min-width: 60px; text-align: center;
                }}
                .timeline-content {{
                    flex: 1; line-height: 1.5;
                }}
                .theorem-card {{
                    background: #f8f9fa; padding: 20px; border-radius: 10px;
                    border: 2px solid #dee2e6; margin-bottom: 20px;
                }}
                .theorem-card h4 {{
                    color: #495057; margin-bottom: 15px;
                }}
                .theorem-formal, .theorem-natural, .theorem-cases {{
                    margin-bottom: 15px;
                }}
                .theorem-formal code {{
                    background: #e9ecef; padding: 10px; border-radius: 5px;
                    display: block; font-family: 'Courier New', monospace; overflow-x: auto;
                }}
                .consistency-status {{
                    text-align: center; font-size: 1.2em; font-weight: bold; margin-bottom: 20px;
                }}
                .status-success {{
                    color: #28a745;
                }}
                .status-error {{
                    color: #dc3545;
                }}
                .consistency-details {{
                    background: #f8f9fa; padding: 15px; border-radius: 8px;
                }}
                .resolution-suggestions {{
                    margin-top: 15px;
                }}
                .resolution-suggestions ul {{
                    list-style-type: none; padding: 0;
                }}
                .resolution-suggestions li {{
                    background: #fff3cd; padding: 10px; margin: 8px 0;
                    border-left: 4px solid #ffc107; border-radius: 5px;
                }}
                .proof-list {{
                    display: grid; gap: 10px;
                }}
                .proof-result {{
                    background: #f8f9fa; padding: 15px; border-radius: 8px;
                    border-left: 4px solid #6c757d;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1><span class="icon-gavel"></span> Caselaw Access Project</h1>
                <p>Explore {stats['case_nodes']:,} legal cases using advanced GraphRAG technology</p>
            </div>
            
            <div class="container">
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-icon icon-law"></div>
                        <div class="stat-number">{stats['case_nodes']:,}</div>
                        <div class="stat-label">Legal Cases</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon icon-users"></div>
                        <div class="stat-number">{stats['total_nodes']:,}</div>
                        <div class="stat-label">Knowledge Entities</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon icon-network"></div>
                        <div class="stat-number">{stats['total_edges']:,}</div>
                        <div class="stat-label">Relationships</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon icon-calendar"></div>
                        <div class="stat-number">{stats['year_range']['span']}</div>
                        <div class="stat-label">Years Covered</div>
                    </div>
                </div>
                
                <!-- Tab Navigation -->
                <div class="tab-navigation">
                    <button class="tab-button active" onclick="switchTab('search')">🔍 Case Search</button>
                    <button class="tab-button" onclick="switchTab('doctrines')">🏷️ Legal Doctrines</button>
                    <button class="tab-button" onclick="switchTab('temporal-logic')">⚖️ Temporal Logic</button>
                    <button class="tab-button" onclick="switchTab('analytics')">📊 Analytics</button>
                </div>
                
                <!-- Search Tab Content -->
                <div id="search-tab" class="tab-content active">
                    <div class="search-section">
                        <h2><span class="icon-search"></span> Intelligent Legal Search</h2>
                        <div class="search-container">
                            <input type="text" id="searchQuery" class="search-input" 
                                   placeholder="Search legal cases, topics, or concepts...">
                            <button class="search-button" onclick="searchCases()">
                                <span class="icon-search"></span> Search
                            </button>
                        </div>
                        <div class="search-suggestions">
                            <div class="suggestion-tag" onclick="quickSearch('civil rights')">Civil Rights</div>
                            <div class="suggestion-tag" onclick="quickSearch('Supreme Court')">Supreme Court</div>
                            <div class="suggestion-tag" onclick="quickSearch('constitutional law')">Constitutional Law</div>
                            <div class="suggestion-tag" onclick="quickSearch('criminal procedure')">Criminal Procedure</div>
                            <div class="suggestion-tag" onclick="quickSearch('privacy rights')">Privacy Rights</div>
                        </div>
                        <div class="loading" id="searchLoading">
                            <span class="icon-spinner"></span> Analyzing legal knowledge graph...
                        </div>
                    </div>
                    
                    <div class="results-section" id="searchResults" style="display: none;">
                        <h2><span class="icon-list"></span> Search Results</h2>
                        <div id="resultsContainer"></div>
                    </div>
                </div>
                
                <!-- Legal Doctrines Tab Content -->
                <div id="doctrines-tab" class="tab-content">
                    <div class="tag-cloud-section">
                        <div class="tag-cloud-header">
                            <h2>🏷️ Legal Doctrines Explorer</h2>
                            <p>Explore legal doctrines through an interactive tag cloud with intelligent clustering</p>
                        </div>
                        
                        <div class="doctrine-search">
                            <input type="text" id="doctrineSearchQuery" placeholder="Filter legal doctrines..." 
                                   oninput="searchDoctrines()" />
                        </div>
                        
                        <div id="doctrinesLoading" class="loading">
                            <span class="icon-spinner"></span> Loading legal doctrines...
                        </div>
                        
                        <div id="tagCloudContainer">
                            <!-- Tag cloud will be dynamically loaded -->
                        </div>
                    </div>
                </div>
                
                <!-- Temporal Deontic Logic Tab Content -->
                <div id="temporal-logic-tab" class="tab-content">
                    <div class="temporal-logic-section">
                        <div class="temporal-header">
                            <h2>⚖️ Temporal Deontic Logic Analysis</h2>
                            <p>Convert case law precedents into formal temporal deontic logic with chronologically consistent theorems</p>
                        </div>
                        
                        <div class="doctrine-selector">
                            <label for="doctrineSelect">Select Legal Doctrine for Analysis:</label>
                            <select id="doctrineSelect" onchange="loadTemporalAnalysis()">
                                <option value="">Choose a doctrine...</option>
                                <option value="qualified_immunity">Qualified Immunity</option>
                                <option value="civil_rights">Civil Rights</option>
                                <option value="due_process">Due Process</option>
                                <option value="equal_protection">Equal Protection</option>
                                <option value="fourth_amendment">Fourth Amendment</option>
                                <option value="miranda_rights">Miranda Rights</option>
                                <option value="commerce_clause">Commerce Clause</option>
                            </select>
                            <button onclick="loadTemporalAnalysis()" class="analyze-btn">🔬 Analyze Logic</button>
                        </div>
                        
                        <div id="temporalLoadingIndicator" class="loading" style="display: none;">
                            <p>🧮 Processing temporal deontic logic conversion...</p>
                            <p><small>This may take a moment as we convert cases to first-order logic</small></p>
                        </div>
                        
                        <div id="temporalAnalysisResults" style="display: none;">
                            <div class="logic-results">
                                <div class="chronological-evolution">
                                    <h3>📅 Chronological Evolution</h3>
                                    <div id="evolutionTimeline"></div>
                                </div>
                                
                                <div class="formal-theorems">
                                    <h3>🧮 Generated Theorems</h3>
                                    <div id="theoremsContainer"></div>
                                </div>
                                
                                <div class="consistency-analysis">
                                    <h3>🔄 Consistency Verification</h3>
                                    <div id="consistencyResults"></div>
                                </div>
                                
                                <div class="proof-results">
                                    <h3>🔬 Theorem Prover Results</h3>
                                    <div id="proofResults"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Analytics Tab Content -->
                <div id="analytics-tab" class="tab-content">
                    <div class="viz-section">
                        <h2><span class="icon-chart"></span> Dataset Analytics</h2>
                        <div id="visualizationContainer"></div>
                    </div>
                </div>
                
                <div class="search-section">
                
            </div>
            
            <div class="footer">
                <p>&copy; 2024 Caselaw Access Project GraphRAG Dashboard | Powered by IPFS Datasets Python</p>
            </div>
            
            <script>
                // Initialize dashboard
                window.onload = function() {{
                    loadVisualizations();
                    loadLegalDoctrines();
                }};
                
                // Tab switching functionality
                function switchTab(tabName) {{
                    // Hide all tab contents
                    document.querySelectorAll('.tab-content').forEach(tab => {{
                        tab.classList.remove('active');
                    }});
                    
                    // Remove active class from all buttons
                    document.querySelectorAll('.tab-button').forEach(btn => {{
                        btn.classList.remove('active');
                    }});
                    
                    // Show selected tab and activate button
                    document.getElementById(tabName + '-tab').classList.add('active');
                    event.target.classList.add('active');
                    
                    // Load content if needed
                    if (tabName === 'doctrines') {{
                        loadLegalDoctrines();
                    }} else if (tabName === 'analytics') {{
                        loadVisualizations();
                    }} else if (tabName === 'temporal-logic') {{
                        // Temporal logic tab loaded on demand
                        console.log('Temporal logic tab activated');
                    }}
                }}
                
                // Temporal Deontic Logic functionality
                function loadTemporalAnalysis() {{
                    const doctrine = document.getElementById('doctrineSelect').value;
                    if (!doctrine) {{
                        alert('Please select a legal doctrine to analyze');
                        return;
                    }}
                    
                    // Show loading indicator
                    document.getElementById('temporalLoadingIndicator').style.display = 'block';
                    document.getElementById('temporalAnalysisResults').style.display = 'none';
                    
                    fetch(`/api/temporal-deontic/${{doctrine}}`)
                        .then(response => response.json())
                        .then(data => {{
                            document.getElementById('temporalLoadingIndicator').style.display = 'none';
                            
                            if (data.status === 'success') {{
                                displayTemporalAnalysisResults(data.temporal_deontic_analysis);
                                document.getElementById('temporalAnalysisResults').style.display = 'block';
                            }} else {{
                                alert('Temporal analysis failed: ' + data.message);
                            }}
                        }})
                        .catch(error => {{
                            document.getElementById('temporalLoadingIndicator').style.display = 'none';
                            alert('Error: ' + error);
                        }});
                }}
                
                function displayTemporalAnalysisResults(analysis) {{
                    // Display chronological evolution
                    let evolutionHtml = '<div class="timeline">';
                    if (analysis.temporal_patterns && analysis.temporal_patterns.chronological_evolution) {{
                        analysis.temporal_patterns.chronological_evolution.forEach(evolution => {{
                            const year = evolution.date.substring(0, 4);
                            const caseId = evolution.case_id.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                            evolutionHtml += `
                                <div class="timeline-item">
                                    <div class="timeline-date">${{year}}</div>
                                    <div class="timeline-content">
                                        <strong>${{caseId}}</strong><br>
                                        O: ${{evolution.new_obligations.length}} obligations<br>
                                        P: ${{evolution.new_permissions.length}} permissions<br>
                                        F: ${{evolution.new_prohibitions.length}} prohibitions
                                    </div>
                                </div>
                            `;
                        }});
                    }}
                    evolutionHtml += '</div>';
                    document.getElementById('evolutionTimeline').innerHTML = evolutionHtml;
                    
                    // Display generated theorems
                    let theoremsHtml = '';
                    if (analysis.generated_theorems) {{
                        analysis.generated_theorems.forEach((theorem, index) => {{
                            theoremsHtml += `
                                <div class="theorem-card">
                                    <h4>${{theorem.name}}</h4>
                                    <div class="theorem-formal">
                                        <strong>Formal Statement:</strong><br>
                                        <code>${{theorem.formal_statement}}</code>
                                    </div>
                                    <div class="theorem-natural">
                                        <strong>Natural Language:</strong><br>
                                        ${{theorem.natural_language}}
                                    </div>
                                    <div class="theorem-cases">
                                        <strong>Supporting Cases:</strong> ${{theorem.supporting_cases.length}}
                                    </div>
                                </div>
                            `;
                        }});
                    }} else {{
                        theoremsHtml = '<p>No formal theorems generated.</p>';
                    }}
                    document.getElementById('theoremsContainer').innerHTML = theoremsHtml;
                    
                    // Display consistency analysis
                    let consistencyHtml = '';
                    if (analysis.consistency_analysis) {{
                        const consistency = analysis.consistency_analysis;
                        const status = consistency.overall_consistent ? 
                            '<span class="status-success">✅ CONSISTENT</span>' : 
                            '<span class="status-error">❌ CONFLICTS DETECTED</span>';
                        
                        consistencyHtml = `
                            <div class="consistency-status">${{status}}</div>
                            <div class="consistency-details">
                                <p><strong>Conflicts Detected:</strong> ${{consistency.conflicts_detected ? consistency.conflicts_detected.length : 0}}</p>
                                <p><strong>Temporal Violations:</strong> ${{consistency.temporal_violations ? consistency.temporal_violations.length : 0}}</p>
                            </div>
                        `;
                        
                        if (consistency.resolution_suggestions && consistency.resolution_suggestions.length > 0) {{
                            consistencyHtml += '<div class="resolution-suggestions"><h5>Resolution Suggestions:</h5><ul>';
                            consistency.resolution_suggestions.forEach(suggestion => {{
                                consistencyHtml += `<li>${{suggestion}}</li>`;
                            }});
                            consistencyHtml += '</ul></div>';
                        }}
                    }} else {{
                        consistencyHtml = '<p>Consistency analysis not available.</p>';
                    }}
                    document.getElementById('consistencyResults').innerHTML = consistencyHtml;
                    
                    // Display proof results
                    let proofHtml = '';
                    if (analysis.proof_results && analysis.proof_results.length > 0) {{
                        proofHtml = '<div class="proof-list">';
                        analysis.proof_results.forEach(proof => {{
                            const statusIcon = proof.proof_status === 'success' ? '✅' : '❌';
                            const executionTime = proof.execution_time ? ` (${{proof.execution_time.toFixed(2)}}s)` : '';
                            proofHtml += `
                                <div class="proof-result">
                                    ${{statusIcon}} <strong>${{proof.theorem_id}}</strong>: ${{proof.proof_status}}
                                    ${{executionTime}}
                                </div>
                            `;
                        }});
                        proofHtml += '</div>';
                    }} else {{
                        proofHtml = '<p>No theorem prover results available.</p>';
                    }}
                    document.getElementById('proofResults').innerHTML = proofHtml;
                }}
                
                // Legal doctrines functionality
                let currentDoctrines = [];
                
                function loadLegalDoctrines() {{
                    document.getElementById('doctrinesLoading').style.display = 'block';
                    document.getElementById('tagCloudContainer').innerHTML = '';
                    
                    fetch('/api/legal-doctrines')
                        .then(response => response.json())
                        .then(data => {{
                            document.getElementById('doctrinesLoading').style.display = 'none';
                            
                            if (data.status === 'success') {{
                                currentDoctrines = data.doctrines;
                                displayTagCloud(data);
                            }} else {{
                                document.getElementById('tagCloudContainer').innerHTML = 
                                    '<p style="text-align: center; color: #666;">Failed to load legal doctrines</p>';
                            }}
                        }})
                        .catch(error => {{
                            document.getElementById('doctrinesLoading').style.display = 'none';
                            document.getElementById('tagCloudContainer').innerHTML = 
                                '<p style="text-align: center; color: #666;">Error loading doctrines: ' + error + '</p>';
                        }});
                }}
                
                function searchDoctrines() {{
                    const query = document.getElementById('doctrineSearchQuery').value.trim();
                    
                    if (!query) {{
                        loadLegalDoctrines();
                        return;
                    }}
                    
                    document.getElementById('doctrinesLoading').style.display = 'block';
                    
                    fetch(`/api/legal-doctrines/search?q=${{encodeURIComponent(query)}}`)
                        .then(response => response.json())
                        .then(data => {{
                            document.getElementById('doctrinesLoading').style.display = 'none';
                            
                            if (data.status === 'success') {{
                                displayTagCloud(data);
                            }} else {{
                                document.getElementById('tagCloudContainer').innerHTML = 
                                    '<p style="text-align: center; color: #666;">No doctrines found for: ' + query + '</p>';
                            }}
                        }})
                        .catch(error => {{
                            document.getElementById('doctrinesLoading').style.display = 'none';
                            console.error('Search error:', error);
                        }});
                }}
                
                function displayTagCloud(data) {{
                    const container = document.getElementById('tagCloudContainer');
                    let html = '';
                    
                    // Display clusters if available
                    if (data.clusters && data.clusters.length > 0) {{
                        data.clusters.forEach(cluster => {{
                            html += `
                                <div class="cluster-section">
                                    <div class="cluster-title">
                                        📂 ${{cluster.name}} (${{cluster.total_cases}} cases)
                                    </div>
                                    <div class="tag-cloud">
                            `;
                            
                            cluster.doctrines.forEach(doctrine => {{
                                const sizeClass = doctrine.case_count > 5 ? 'size-large' : 
                                                doctrine.case_count > 2 ? 'size-medium' : 'size-small';
                                html += `
                                    <a href="/doctrine/${{doctrine.url_name}}" class="doctrine-tag ${{sizeClass}}"
                                       title="${{doctrine.case_count}} cases">
                                        ${{doctrine.display_name}} (${{doctrine.case_count}})
                                    </a>
                                `;
                            }});
                            
                            html += `
                                    </div>
                                </div>
                            `;
                        }});
                    }} else {{
                        // Fallback: display all doctrines in one cloud
                        html += '<div class="tag-cloud">';
                        data.doctrines.forEach(doctrine => {{
                            const sizeClass = doctrine.case_count > 5 ? 'size-large' : 
                                            doctrine.case_count > 2 ? 'size-medium' : 'size-small';
                            html += `
                                <a href="/doctrine/${{doctrine.url_name}}" class="doctrine-tag ${{sizeClass}}"
                                   title="${{doctrine.case_count}} cases">
                                    ${{doctrine.display_name}} (${{doctrine.case_count}})
                                </a>
                            `;
                        }});
                        html += '</div>';
                    }}
                    
                    if (data.doctrines.length === 0) {{
                        html = '<div class="no-results"><p>No legal doctrines found.</p></div>';
                    }}
                    
                    container.innerHTML = html;
                }}
                
                // Case search functionality
                function quickSearch(query) {{
                    document.getElementById('searchQuery').value = query;
                    searchCases();
                }}
                
                function searchCases() {{
                    const query = document.getElementById('searchQuery').value.trim();
                    if (!query) {{
                        alert('Please enter a search query');
                        return;
                    }}
                    
                    document.getElementById('searchLoading').style.display = 'block';
                    document.getElementById('searchResults').style.display = 'none';
                    
                    fetch(`/api/search?q=${{encodeURIComponent(query)}}&limit=10`)
                        .then(response => response.json())
                        .then(data => {{
                            document.getElementById('searchLoading').style.display = 'none';
                            
                            if (data.status === 'success') {{
                                displaySearchResults(data.results, data.query);
                            }} else {{
                                alert('Search failed: ' + data.message);
                            }}
                        }})
                        .catch(error => {{
                            document.getElementById('searchLoading').style.display = 'none';
                            alert('Error: ' + error);
                        }});
                }}
                
                function displaySearchResults(results, query) {{
                    const container = document.getElementById('resultsContainer');
                    
                    if (results.length === 0) {{
                        container.innerHTML = `
                            <div class="no-results">
                                <i class="fas fa-search" style="font-size: 3em; margin-bottom: 15px; opacity: 0.3;"></i>
                                <p>No cases found for: "<strong>${{query}}</strong>"</p>
                                <p>Try different keywords or browse suggested topics above.</p>
                            </div>
                        `;
                    }} else {{
                        let html = `<p style="margin-bottom: 20px; font-size: 1.1em;">
                            <strong>${{results.length}}</strong> cases found for: "<strong>${{query}}</strong>"
                        </p>`;
                        
                        results.forEach((result, index) => {{
                            const case_data = result.case;
                            html += `
                                <div class="case-result" onclick="window.location.href='/case/${{case_data.id}}';">
                                    <div class="case-title">
                                        ⚖️ ${{case_data.full_caption || case_data.title}}
                                    </div>
                                    <div class="case-citation">
                                        <strong>${{case_data.citation || case_data.short_citation || 'No citation'}}</strong>
                                    </div>
                                    <div class="case-meta">
                                        <div class="meta-item">
                                            <span>🏛️</span>
                                            <span>${{case_data.court_abbrev || case_data.court}}</span>
                                        </div>
                                        <div class="meta-item">
                                            <span>📅</span>
                                            <span>${{case_data.year}}</span>
                                        </div>
                                        <div class="meta-item">
                                            <span>🏷️</span>
                                            <span>${{case_data.topic}}</span>
                                        </div>
                                        <div class="meta-item">
                                            <span>⭐</span>
                                            <span>Relevance: ${{result.relevance_score}}/3</span>
                                        </div>
                                    </div>
                                </div>
                            `;
                        }});
                        
                        container.innerHTML = html;
                    }}
                    
                    document.getElementById('searchResults').style.display = 'block';
                    document.getElementById('searchResults').scrollIntoView({{ behavior: 'smooth' }});
                }}
                
                function loadVisualizations() {{
                    const vizContainer = document.getElementById('visualizationContainer');
                    
                    // Create fallback visualizations when external dependencies aren't available
                    const vizSummary = `
                        <div style="background: #f8f9fa; padding: 30px; border-radius: 15px; margin: 20px 0;">
                            <h3 style="margin-bottom: 20px; color: #2c3e50;">📊 Dataset Overview</h3>
                            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px;">
                                <div style="background: white; padding: 20px; border-radius: 10px; border-left: 4px solid #667eea;">
                                    <h4>🏛️ Court Distribution</h4>
                                    <div style="margin-top: 10px; font-size: 0.9em; color: #666;">
                                        Supreme Court: 4 cases<br>
                                        Circuit Courts: 3 cases<br>
                                        District Courts: 2 cases<br>
                                        State Courts: 1 case
                                    </div>
                                </div>
                                <div style="background: white; padding: 20px; border-radius: 10px; border-left: 4px solid #764ba2;">
                                    <h4>⚖️ Legal Topics</h4>
                                    <div style="margin-top: 10px; font-size: 0.9em; color: #666;">
                                        Civil Rights: 2 cases<br>
                                        Criminal Procedure: 2 cases<br>
                                        Constitutional Law: 2 cases<br>
                                        Privacy Rights: 1 case<br>
                                        Affirmative Action: 1 case
                                    </div>
                                </div>
                            </div>
                            <div style="margin-top: 20px; padding: 15px; background: #e3f2fd; border-radius: 8px; text-align: center;">
                                <small><em>📈 Advanced interactive charts available when external dependencies are loaded</em></small>
                            </div>
                        </div>
                    `;
                    vizContainer.innerHTML = vizSummary;
                }}
                
                // Allow search on Enter key
                document.addEventListener('DOMContentLoaded', function() {{
                    document.getElementById('searchQuery').addEventListener('keypress', function(e) {{
                        if (e.key === 'Enter') {{
                            searchCases();
                        }}
                    }});
                    
                    document.getElementById('doctrineSearchQuery').addEventListener('keypress', function(e) {{
                        if (e.key === 'Enter') {{
                            searchDoctrines();
                        }}
                    }});
                }});
            </script>
        </body>
        </html>
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
        
        # Get cases from the processor's internal data
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
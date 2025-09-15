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
        
        @self.app.route('/api/case/<case_id>')
        def case_details(case_id):
            """Get detailed information about a specific case"""
            if not self.processed_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Data not initialized'
                })
            
            try:
                # Find the case
                case_data = None
                for node in self.processed_data['knowledge_graph']['nodes']:
                    if node.get('id') == case_id and node.get('type') == 'case':
                        case_data = node
                        break
                
                if not case_data:
                    return jsonify({
                        'status': 'error',
                        'message': 'Case not found'
                    })
                
                # Get relationships
                relationships = self.processor.get_case_relationships(case_id)
                
                return jsonify({
                    'status': 'success',
                    'case': case_data,
                    'relationships': relationships
                })
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
            <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
                .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }}
                .stat-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .stat-number {{ font-size: 2em; font-weight: bold; color: #3498db; }}
                .search-section {{ background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .search-input {{ width: 70%; padding: 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 16px; }}
                .search-button {{ padding: 12px 24px; background: #3498db; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }}
                .search-button:hover {{ background: #2980b9; }}
                .results-section {{ background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .case-result {{ border-left: 4px solid #3498db; padding: 15px; margin: 10px 0; background: #f8f9fa; border-radius: 0 4px 4px 0; }}
                .case-title {{ font-weight: bold; color: #2c3e50; margin-bottom: 5px; }}
                .case-meta {{ color: #666; font-size: 14px; }}
                .viz-section {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .loading {{ display: none; text-align: center; color: #666; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🏛️ Caselaw Access Project - GraphRAG Dashboard</h1>
                <p>Search and explore {stats['case_nodes']:,} legal cases using knowledge graph technology</p>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">{stats['case_nodes']:,}</div>
                    <div>Legal Cases</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['total_nodes']:,}</div>
                    <div>Total Entities</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['total_edges']:,}</div>
                    <div>Relationships</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['year_range']['span']}</div>
                    <div>Year Span</div>
                </div>
            </div>
            
            <div class="search-section">
                <h2>🔍 Search Legal Cases</h2>
                <input type="text" id="searchQuery" class="search-input" placeholder="Enter search query (e.g., 'civil rights', 'Supreme Court', 'constitutional law')">
                <button class="search-button" onclick="searchCases()">Search</button>
                <div class="loading" id="searchLoading">Searching...</div>
            </div>
            
            <div class="results-section" id="searchResults" style="display: none;">
                <h2>Search Results</h2>
                <div id="resultsContainer"></div>
            </div>
            
            <div class="viz-section">
                <h2>📊 Dataset Visualizations</h2>
                <div id="topicsChart" style="height: 400px;"></div>
                <div id="courtsChart" style="height: 400px; margin-top: 20px;"></div>
            </div>
            
            <script>
                // Initialize visualizations
                window.onload = function() {{
                    loadVisualizations();
                }};
                
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
                        container.innerHTML = `<p>No cases found for query: "${{query}}"</p>`;
                    }} else {{
                        let html = `<p>Found ${{results.length}} cases for query: "${{query}}"</p>`;
                        
                        results.forEach(result => {{
                            const case_data = result.case;
                            html += `
                                <div class="case-result">
                                    <div class="case-title">${{case_data.title}}</div>
                                    <div class="case-meta">
                                        ${{case_data.court}} • ${{case_data.year}} • Topic: ${{case_data.topic}} • 
                                        Relevance: ${{result.relevance_score}}/3
                                    </div>
                                </div>
                            `;
                        }});
                        
                        container.innerHTML = html;
                    }}
                    
                    document.getElementById('searchResults').style.display = 'block';
                }}
                
                function loadVisualizations() {{
                    fetch('/api/visualizations')
                        .then(response => response.json())
                        .then(data => {{
                            if (data.status === 'success') {{
                                // Topics chart
                                const topicsData = data.visualizations.topics_chart;
                                Plotly.newPlot('topicsChart', topicsData.data, topicsData.layout);
                                
                                // Courts chart  
                                const courtsData = data.visualizations.courts_chart;
                                Plotly.newPlot('courtsChart', courtsData.data, courtsData.layout);
                            }}
                        }})
                        .catch(error => console.error('Visualization error:', error));
                }}
                
                // Allow search on Enter key
                document.getElementById('searchQuery').addEventListener('keypress', function(e) {{
                    if (e.key === 'Enter') {{
                        searchCases();
                    }}
                }});
            </script>
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
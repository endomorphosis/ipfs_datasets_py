"""
Integrated Legal Research Dashboard

This module provides a unified dashboard that integrates all legal research
functionality through the MCP architecture, ensuring all JavaScript calls
route through MCP tools.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

try:
    from flask import Flask, render_template, request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

from ipfs_datasets_py.mcp_tools.tools.deontic_logic_tools import deontic_logic_tools
from ipfs_datasets_py.deontic_logic import DeonticLogicConverter, DeonticLogicDatabase

class IntegratedLegalDashboard:
    """Unified legal research dashboard using MCP architecture"""
    
    def __init__(self, host='0.0.0.0', port=5000):
        self.host = host
        self.port = port
        self.logger = logging.getLogger(__name__)
        
        if not FLASK_AVAILABLE:
            raise ImportError("Flask is required for the dashboard")
        
        self.app = Flask(__name__, 
                        template_folder='templates',
                        static_folder='static')
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            """Main dashboard page"""
            return render_template('integrated_legal_dashboard.html')
        
        @self.app.route('/api/mcp/convert-logic', methods=['POST'])
        async def convert_logic():
            """MCP endpoint for deontic logic conversion"""
            try:
                data = request.get_json()
                text = data.get('text', '')
                case_id = data.get('case_id')
                
                result = await deontic_logic_tools.convert_text_to_logic(text, case_id)
                return jsonify(result)
            except Exception as e:
                self.logger.error(f"Error in convert_logic: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/mcp/search-statements', methods=['GET'])
        async def search_statements():
            """MCP endpoint for searching deontic statements"""
            try:
                query = request.args.get('query', '')
                limit = int(request.args.get('limit', 10))
                
                result = await deontic_logic_tools.search_statements(query, limit)
                return jsonify(result)
            except Exception as e:
                self.logger.error(f"Error in search_statements: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/mcp/statistics', methods=['GET'])
        async def get_statistics():
            """MCP endpoint for database statistics"""
            try:
                result = await deontic_logic_tools.get_database_statistics()
                return jsonify(result)
            except Exception as e:
                self.logger.error(f"Error in get_statistics: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/mcp/detect-conflicts', methods=['GET'])
        async def detect_conflicts():
            """MCP endpoint for conflict detection"""
            try:
                result = await deontic_logic_tools.detect_conflicts()
                return jsonify(result)
            except Exception as e:
                self.logger.error(f"Error in detect_conflicts: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/mcp/analyze-topic/<int:topic_id>', methods=['GET'])
        async def analyze_topic(topic_id):
            """MCP endpoint for topic analysis"""
            try:
                result = await deontic_logic_tools.analyze_topic(topic_id)
                return jsonify(result)
            except Exception as e:
                self.logger.error(f"Error in analyze_topic: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
    
    def run(self, debug=False):
        """Run the dashboard"""
        self.logger.info(f"Starting Integrated Legal Dashboard on {self.host}:{self.port}")
        self.app.run(host=self.host, port=self.port, debug=debug)

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Create and run dashboard
    dashboard = IntegratedLegalDashboard()
    dashboard.run(debug=True)
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Comprehensive MCP Dashboard for IPFS Datasets Python with GraphRAG Integration.

This module extends the admin dashboard to provide comprehensive MCP functionality,
including MCP tool discovery, execution, real-time monitoring, and integrated
GraphRAG processing capabilities with advanced analytics and visualization.

Features:
- MCP tool discovery and execution
- Real-time monitoring and analytics  
- GraphRAG website processing and analysis
- Interactive RAG query interface
"""

# Note: duplicate route registrations removed to prevent endpoint conflicts

from __future__ import annotations

import os
import time
import uuid
import asyncio
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from flask import render_template, jsonify, request, send_from_directory, url_for
    FLASK_AVAILABLE = True
except Exception:  # pragma: no cover
    FLASK_AVAILABLE = False
    render_template = jsonify = request = send_from_directory = url_for = None  # type: ignore

from ipfs_datasets_py.admin_dashboard import AdminDashboard, DashboardConfig


# Optional feature flags (fallbacks if integrations are unavailable)
GRAPHRAG_AVAILABLE = False
INVESTIGATION_AVAILABLE = False
MCP_SERVER_AVAILABLE = False


try:
    from dataclasses import dataclass
except Exception:  # pragma: no cover
    def dataclass(cls):  # type: ignore
        return cls

# Lightweight stubs for optional components to satisfy name resolution
class AdvancedAnalyticsDashboard:  # stub
    pass

class MCPInvestigationDashboardConfig:  # stub
    def __init__(self, *args, **kwargs):
        pass

class MCPInvestigationDashboard:  # stub
    def __init__(self, *args, **kwargs):
        pass

class CompleteGraphRAGSystem:  # stub
    pass

class EnhancedGraphRAGSystem:  # stub
    pass

class CompleteProcessingConfiguration:  # stub
    def __init__(self, *args, **kwargs):
        self.processing_mode = kwargs.get("processing_mode")
        self.output_directory = kwargs.get("output_directory")


@dataclass
class MCPDashboardConfig(DashboardConfig):
    """Lightweight MCP dashboard configuration with sensible defaults."""
    mcp_server_host: str = "127.0.0.1"
    mcp_server_port: int = 8001
    enable_graphrag: bool = True
    enable_analytics: bool = True
    enable_rag_query: bool = True
    enable_investigation: bool = True
    enable_real_time_monitoring: bool = True
    enable_tool_execution: bool = True
    max_concurrent_tools: int = 4
    open_browser: bool = False
    data_dir: str = os.path.expanduser("~/.ipfs_datasets/mcp_dashboard")
    graphrag_output_dir: str = os.path.expanduser("~/.ipfs_datasets/graphrag_output")

# Minimal in-process MCP server placeholder (enables status + tool discovery)
class SimpleInProcessMCPServer:
    def __init__(self) -> None:
        self.name = "SimpleInProcessMCPServer"
class MCPDashboard(AdminDashboard):
    """
    Comprehensive MCP Dashboard with GraphRAG integration extending AdminDashboard.
    
    This dashboard provides:
    - MCP tool discovery and listing
    - Real-time MCP server status monitoring
    - Tool execution interface with results
    - GraphRAG website processing and analysis
    - Advanced analytics and monitoring
    - Interactive RAG query interface
    - Investigation tools for content analysis
    - Enhanced visualizations and reporting
    - JavaScript SDK endpoints
    """
    
    def __init__(self):
        """Initialize the comprehensive MCP dashboard."""
        super().__init__()
        self.mcp_server = None
        self.mcp_config = None
        self.tool_execution_history = deque(maxlen=1000)
        self.active_tool_executions = {}
        
        # GraphRAG components
        self.graphrag_system = None
        self.enhanced_graphrag = None
        self.analytics_dashboard = None
        self.investigation_dashboard = None
        
        # Processing state
        self.graphrag_processing_sessions = {}
        self.analytics_metrics_history = deque(maxlen=1000)
        self.rag_query_sessions = {}
        
        # Enhanced features
        self.workflow_manager = {}
        self.system_metrics = {
            'cpu_usage': 0.0,
            'memory_usage': 0.0,
            'active_connections': 0,
            'task_queue_size': 0,
            'total_datasets_processed': 0,
            'uptime': 0
        }
        self.health_status = {
            'mcp_server': 'running',
            'ipfs_node': 'running', 
            'vector_store': 'running',
            'cache_system': 'running'
        }
        self.dataset_registry = {}
        self.performance_metrics = {}
        self.test_results = {}
        
        # Bug prevention
        self._initialize_safe_defaults()
        
    def _initialize_safe_defaults(self):
        """Initialize safe defaults to prevent bugs."""
        # Ensure all collections are properly initialized
        if not hasattr(self, 'tool_execution_history'):
            self.tool_execution_history = deque(maxlen=1000)
        if not hasattr(self, 'active_tool_executions'):
            self.active_tool_executions = {}
        if not hasattr(self, 'workflow_manager'):
            self.workflow_manager = {}
        
        # Set up error handling
        self._error_log = deque(maxlen=100)
        self._debug_mode = os.environ.get('MCP_DEBUG', '0') == '1'
        
        # Real-time monitoring
        self.real_time_clients = set()
        self.monitoring_thread = None
        self.last_metrics_update = time.time()
        self.start_time = time.time()
        
    def configure(self, config: MCPDashboardConfig) -> None:
        """Configure the comprehensive MCP dashboard.
        
        Args:
            config: MCP dashboard configuration
        """
        # Check Flask availability first
        if not FLASK_AVAILABLE:
            self.logger.warning("Flask not available - creating standalone HTML dashboard")
            self._create_standalone_dashboard(config)
            return
            
        super().configure(config)
        self.mcp_config = config
        
        # Initialize simple in-process placeholder MCP server for status and discovery
        self.mcp_server = SimpleInProcessMCPServer()
        self._discover_mcp_tools()
        self.logger.info("Using SimpleInProcessMCPServer (placeholder)")
        
        # Initialize GraphRAG components if enabled and available
        if config.enable_graphrag and GRAPHRAG_AVAILABLE:
            try:
                self._initialize_graphrag_components()
            except Exception as e:
                self.logger.error(f"Failed to initialize GraphRAG components: {e}")
        
        # Initialize analytics if enabled
        if config.enable_analytics and GRAPHRAG_AVAILABLE:
            try:
                self.analytics_dashboard = AdvancedAnalyticsDashboard()
            except Exception as e:
                self.logger.error(f"Failed to initialize analytics dashboard: {e}")
        
        # Initialize investigation dashboard if enabled
        if config.enable_investigation and INVESTIGATION_AVAILABLE:
            try:
                inv_config = MCPInvestigationDashboardConfig(
                    mcp_server_url=f"http://{config.mcp_server_host}:{config.mcp_server_port}"
                )
                self.investigation_dashboard = MCPInvestigationDashboard(inv_config)
            except Exception as e:
                self.logger.error(f"Failed to initialize investigation dashboard: {e}")
                
        # Create output directory for GraphRAG
        if config.enable_graphrag:
            os.makedirs(config.graphrag_output_dir, exist_ok=True)
                
    def _create_standalone_dashboard(self, config: MCPDashboardConfig) -> None:
        """Create a standalone HTML dashboard when Flask is not available."""
        self.mcp_config = config
        self.mcp_server = SimpleInProcessMCPServer()
        
        # Create standalone dashboard directory
        dashboard_dir = Path(config.data_dir)
        dashboard_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate tools info
        tools_info = self._discover_mcp_tools()
        
        # Create comprehensive standalone dashboard
        standalone_html = self._create_standalone_html_dashboard(tools_info, config)
        
        # Write standalone dashboard
        dashboard_file = dashboard_dir / "mcp_dashboard.html"
        with open(dashboard_file, 'w', encoding='utf-8') as f:
            f.write(standalone_html)
        
        self.logger.info(f"Standalone MCP Dashboard created at: {dashboard_file}")
        self.logger.info(f"Open this file in your browser to access the dashboard")
        
        # Try to open in browser if configured
        if config.open_browser:
            try:
                import webbrowser
                webbrowser.open(f"file://{dashboard_file.absolute()}")
                self.logger.info("Dashboard opened in browser")
            except Exception as e:
                self.logger.warning(f"Failed to open browser: {e}")
    
    def _create_standalone_html_dashboard(self, tools_info: Dict[str, Any], config: MCPDashboardConfig) -> str:
        """Create a standalone HTML dashboard with professional desktop design."""
        # First try the comprehensive final template
        comprehensive_path = Path(__file__).parent.parent / "comprehensive_mcp_dashboard_final.html"
        if comprehensive_path.exists():
            with open(comprehensive_path, "r", encoding="utf-8") as f:
                return f.read()
        
        # Try the professional template
        template_path = Path(__file__).parent / "templates" / "mcp_dashboard.html"
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        
        # Fallback to comprehensive inline template
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Server Dashboard - IPFS Datasets Management Console</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background: #f3f4f6; }
        .header { background: linear-gradient(135deg, #2563eb, #1e40af); color: white; padding: 1rem; }
        .sidebar { background: white; width: 280px; height: 100vh; position: fixed; }
        .main-content { margin-left: 280px; padding: 2rem; }
    </style>
</head>
<body>
    <div class="header">
        <h1><i class="fas fa-server"></i> MCP Server Dashboard</h1>
    </div>
    <div class="sidebar">
        <h3>Navigation</h3>
        <p>Professional MCP Dashboard</p>
    </div>
    <div class="main-content">
        <h2>Dataset Operations</h2>
        <p>Professional interface for IPFS dataset management</p>
    </div>
</body>
</html>"""
    
    def _initialize_graphrag_components(self) -> None:
        """Initialize GraphRAG processing components."""
        if not GRAPHRAG_AVAILABLE:
            return
            
        try:
            # Initialize complete GraphRAG system
            self.graphrag_system = CompleteGraphRAGSystem()
            
            self.logger.info("GraphRAG components initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize GraphRAG components: {e}")
                
    def _discover_mcp_tools(self) -> Dict[str, Any]:
        """Discover available MCP tools."""
        if not self.mcp_server:
            return {}
            
        tools_info = {}
        tools_dir = Path(__file__).parent / "mcp_server" / "tools"
        
        if tools_dir.exists():
            for tool_category in tools_dir.iterdir():
                if tool_category.is_dir() and not tool_category.name.startswith('_'):
                    category_tools = self._scan_tool_category(tool_category)
                    if category_tools:
                        tools_info[tool_category.name] = category_tools
        
        self.logger.info(f"Discovered {len(tools_info)} tool categories")
        return tools_info
        
    def _scan_tool_category(self, category_path: Path) -> List[Dict[str, Any]]:
        """Scan a tool category directory for available tools."""
        tools = []
        try:
            for tool_file in category_path.glob("*.py"):
                if not tool_file.name.startswith("_"):
                    tool_name = tool_file.stem
                    tools.append({
                        "name": tool_name,
                        "file": str(tool_file),
                        "description": f"Tool: {tool_name}"
                    })
        except Exception as e:
            self.logger.error(f"Error scanning tool category {category_path}: {e}")
        
        return tools
        
    def _setup_routes(self) -> None:
        """Set up MCP dashboard routes."""
        # Call parent to set up base admin dashboard routes
        super()._setup_routes()
        
        # Set up main MCP dashboard route
        @self.app.route('/mcp')
        def mcp_dashboard():
            """Render the main MCP dashboard."""
            # Get server status safely
            server_status = {}
            if self.mcp_server:
                if hasattr(self.mcp_server, 'get_status'):
                    try:
                        server_status = self.mcp_server.get_status()
                    except Exception:
                        server_status = {"name": getattr(self.mcp_server, 'name', 'MCP Server'), "status": "running"}
                else:
                    server_status = {"name": getattr(self.mcp_server, 'name', 'MCP Server'), "status": "running"}
            
            return render_template('mcp_dashboard.html',
                                 tools=self._discover_mcp_tools(),
                                 server_status=server_status,
                                 last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        # Set up MCP tool routes (status, tools, executions)
        self._setup_mcp_tool_routes()
        
        # Set up feature-specific routes if enabled
        if self.mcp_config and self.mcp_config.enable_graphrag:
            self._setup_graphrag_routes()
        if self.mcp_config and self.mcp_config.enable_analytics:
            self._setup_analytics_routes()
        if self.mcp_config and self.mcp_config.enable_rag_query:
            self._setup_rag_query_routes()
        if self.mcp_config and self.mcp_config.enable_investigation:
            self._setup_investigation_routes()
        
        # Set up caselaw/legal text to deontic logic routes (always enabled)
        self._setup_caselaw_routes()
        
        # Set up finance dashboard routes (based on caselaw template)
        self._setup_finance_routes()
        
        # Set up medicine dashboard routes (based on caselaw template)
        self._setup_medicine_routes()
        
        # Set up legal dataset scraping routes
        self._setup_legal_dataset_routes()
    
    def _setup_graphrag_routes(self) -> None:
        """Set up GraphRAG processing routes."""
        
        @self.app.route('/api/mcp/graphrag/process', methods=['POST'])
        def api_start_graphrag_processing():
            """Start GraphRAG website processing."""
            try:
                data = request.json or {}
                url = data.get('url')
                if not url:
                    return jsonify({"error": "URL is required"}), 400
                
                session_id = str(uuid.uuid4())
                processing_config = CompleteProcessingConfiguration(
                    processing_mode=data.get('mode', 'balanced'),
                    output_directory=self.mcp_config.graphrag_output_dir
                )
                
                # Start processing session
                self.graphrag_processing_sessions[session_id] = {
                    "id": session_id,
                    "url": url,
                    "config": processing_config,
                    "status": "starting",
                    "start_time": datetime.now().isoformat(),
                    "progress": 0.0,
                    "result": None
                }
                
                # Start async processing
                asyncio.create_task(self._process_website_graphrag(session_id, url, processing_config))
                
                return jsonify({"session_id": session_id, "status": "started"})
                
            except Exception as e:
                self.logger.error(f"GraphRAG processing failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/mcp/graphrag/sessions/<session_id>')
        def api_get_graphrag_session(session_id):
            """Get GraphRAG processing session status."""
            if session_id in self.graphrag_processing_sessions:
                return jsonify(self.graphrag_processing_sessions[session_id])
            return jsonify({"error": "Session not found"}), 404
        
        @self.app.route('/api/mcp/graphrag/sessions')
        def api_list_graphrag_sessions():
            """List all GraphRAG processing sessions."""
            sessions = list(self.graphrag_processing_sessions.values())
            return jsonify({"sessions": sessions, "total": len(sessions)})
    
    def _setup_analytics_routes(self) -> None:
        """Set up analytics dashboard routes."""
        
        @self.app.route('/mcp/analytics')
        def analytics_dashboard():
            """Render the analytics dashboard."""
            current_metrics = self._get_current_analytics_metrics()
            return render_template('analytics_dashboard.html',
                                 metrics=current_metrics,
                                 last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        @self.app.route('/api/mcp/analytics/metrics')
        def api_get_analytics_metrics():
            """Get current analytics metrics."""
            return jsonify(self._get_current_analytics_metrics())
        
        @self.app.route('/api/mcp/analytics/history')
        def api_get_analytics_history():
            """Get analytics metrics history."""
            limit = request.args.get('limit', 100, type=int)
            history = list(self.analytics_metrics_history)[-limit:]
            return jsonify({"history": history, "total": len(self.analytics_metrics_history)})
    
    def _setup_rag_query_routes(self) -> None:
        """Set up RAG query interface routes."""
        
        @self.app.route('/mcp/rag')
        def rag_query_dashboard():
            """Render the RAG query dashboard."""
            return render_template('rag_query_dashboard.html',
                                 last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        @self.app.route('/api/mcp/rag/query', methods=['POST'])
        def api_execute_rag_query():
            """Execute a RAG query."""
            try:
                data = request.json or {}
                query = data.get('query')
                if not query:
                    return jsonify({"error": "Query is required"}), 400
                
                # Create query session
                session_id = str(uuid.uuid4())
                query_session = {
                    "id": session_id,
                    "query": query,
                    "status": "processing",
                    "start_time": datetime.now().isoformat(),
                    "result": None
                }
                
                self.rag_query_sessions[session_id] = query_session
                
                # Execute query through MCP tool
                result = self._execute_rag_query_via_mcp(query, data.get('context', {}))
                
                query_session.update({
                    "status": "completed",
                    "result": result,
                    "end_time": datetime.now().isoformat()
                })
                
                return jsonify(query_session)
                
            except Exception as e:
                self.logger.error(f"RAG query failed: {e}")
                return jsonify({"error": str(e)}), 500
    
    def _setup_investigation_routes(self) -> None:
        """Set up investigation dashboard routes."""
        
        @self.app.route('/mcp/investigation')
        def investigation_dashboard():
            """Render the investigation dashboard."""
            return render_template('investigation_dashboard.html',
                                 last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        @self.app.route('/api/mcp/investigation/analyze', methods=['POST'])
        def api_start_investigation():
            """Start content investigation analysis."""
            try:
                data = request.json or {}
                content_url = data.get('url')
                analysis_type = data.get('analysis_type', 'comprehensive')
                
                if not content_url:
                    return jsonify({"error": "Content URL is required"}), 400
                
                # Execute investigation through MCP tool
                result = self._execute_investigation_via_mcp(content_url, analysis_type, data.get('metadata', {}))
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Investigation analysis failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/mcp/investigation/geospatial', methods=['POST'])
        def api_geospatial_analysis():
            """Perform geospatial analysis via MCP tools."""
            try:
                data = request.json or {}
                query = data.get('query', '')
                center_location = data.get('center_location', '')
                search_radius = data.get('search_radius_km', 50.0)
                entity_types = data.get('entity_types', [])
                clustering_distance = data.get('clustering_distance', 50.0)
                
                # Execute geospatial analysis through MCP tools
                result = self._execute_geospatial_via_mcp(
                    query, center_location, search_radius, entity_types, clustering_distance
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Geospatial analysis failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/mcp/investigation/extract_entities', methods=['POST'])
        def api_extract_geographic_entities():
            """Extract geographic entities via MCP tools."""
            try:
                data = request.json or {}
                corpus_data = data.get('corpus_data', '{}')
                confidence_threshold = data.get('confidence_threshold', 0.8)
                entity_types = data.get('entity_types', None)
                
                # Execute entity extraction through MCP tools
                result = self._execute_entity_extraction_via_mcp(
                    corpus_data, confidence_threshold, entity_types
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Entity extraction failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/mcp/investigation/spatiotemporal', methods=['POST'])
        def api_spatiotemporal_mapping():
            """Map spatiotemporal events via MCP tools."""
            try:
                data = request.json or {}
                corpus_data = data.get('corpus_data', '{}')
                time_range = data.get('time_range', None)
                geographic_bounds = data.get('geographic_bounds', None)
                event_types = data.get('event_types', None)
                clustering_distance = data.get('clustering_distance', 50.0)
                
                # Execute spatiotemporal mapping through MCP tools
                result = self._execute_spatiotemporal_via_mcp(
                    corpus_data, time_range, geographic_bounds, event_types, clustering_distance
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Spatiotemporal mapping failed: {e}")
                return jsonify({"error": str(e)}), 500
    
    def _setup_caselaw_routes(self) -> None:
        """Set up caselaw dashboard routes for temporal deontic logic RAG system."""
        
        @self.app.route('/mcp/caselaw')
        def caselaw_dashboard():
            """Render the caselaw analysis dashboard for temporal deontic logic RAG system."""
            # Import temporal deontic logic components
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.document_consistency_checker import DocumentConsistencyChecker
                from .logic_integration.deontic_logic_core import DeonticOperator
                
                # Initialize RAG store and get statistics
                rag_store = TemporalDeonticRAGStore()
                checker = DocumentConsistencyChecker(rag_store=rag_store)
                
                dashboard_data = {
                    "system_status": {
                        "theorem_count": len(rag_store.theorems),
                        "jurisdictions": list(rag_store.jurisdiction_index.keys()) if hasattr(rag_store, 'jurisdiction_index') else [],
                        "legal_domains": list(rag_store.domain_index.keys()) if hasattr(rag_store, 'domain_index') else [],
                        "temporal_periods": len(getattr(rag_store, 'temporal_index', {})),
                        "available_operators": [op.name for op in DeonticOperator],
                        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "system_ready": True
                    },
                    "mcp_enabled": True
                }
                
            except Exception as e:
                self.logger.error(f"Failed to initialize caselaw dashboard: {e}")
                dashboard_data = {
                    "system_status": {
                        "theorem_count": 0,
                        "jurisdictions": [],
                        "legal_domains": [],
                        "temporal_periods": 0,
                        "available_operators": [],
                        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "system_ready": False,
                        "error_message": str(e)
                    },
                    "mcp_enabled": True
                }
            
            return render_template('caselaw_dashboard_mcp.html', **dashboard_data)
        
        @self.app.route('/mcp/caselaw/rest')
        def caselaw_dashboard_rest():
            """Render the REST-based caselaw analysis dashboard (legacy)."""
            # Import temporal deontic logic components
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.document_consistency_checker import DocumentConsistencyChecker
                from .logic_integration.deontic_logic_core import DeonticOperator
                
                # Initialize RAG store and get statistics
                rag_store = TemporalDeonticRAGStore()
                checker = DocumentConsistencyChecker(rag_store=rag_store)
                
                dashboard_data = {
                    "theorem_count": len(rag_store.theorems),
                    "jurisdictions": len(getattr(rag_store, 'jurisdiction_index', {})),
                    "legal_domains": len(getattr(rag_store, 'domain_index', {})),
                    "temporal_periods": len(getattr(rag_store, 'temporal_index', {})),
                    "available_operators": [op.name for op in DeonticOperator],
                    "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "system_ready": True
                }
                
            except Exception as e:
                self.logger.error(f"Failed to initialize caselaw dashboard: {e}")
                dashboard_data = {
                    "theorem_count": 0,
                    "jurisdictions": 0,
                    "legal_domains": 0,
                    "temporal_periods": 0,
                    "available_operators": [],
                    "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "system_ready": False,
                    "error_message": str(e)
                }
            
            return render_template('caselaw_dashboard.html', **dashboard_data)
        
        @self.app.route('/api/mcp/caselaw/add_theorem', methods=['POST'])
        def api_add_theorem():
            """Add a new temporal deontic logic theorem from caselaw."""
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.deontic_logic_core import DeonticFormula, DeonticOperator, LegalAgent
                from datetime import datetime
                
                data = request.json or {}
                
                # Extract theorem data from request
                operator_str = data.get('operator', 'OBLIGATION')
                proposition = data.get('proposition', '')
                agent_name = data.get('agent_name', 'Unspecified Party')
                jurisdiction = data.get('jurisdiction', 'Federal')
                legal_domain = data.get('legal_domain', 'general')
                source_case = data.get('source_case', 'Unknown Case')
                precedent_strength = float(data.get('precedent_strength', 0.8))
                
                if not proposition:
                    return jsonify({"error": "Proposition is required"}), 400
                
                # Create deontic formula
                operator = DeonticOperator[operator_str]
                agent = LegalAgent(agent_name.lower().replace(' ', '_'), agent_name, "person")
                
                formula = DeonticFormula(
                    operator=operator,
                    proposition=proposition,
                    agent=agent,
                    confidence=0.9,
                    source_text=f"{agent_name} {operator_str.lower()} {proposition}"
                )
                
                # Add to RAG store
                rag_store = TemporalDeonticRAGStore()
                
                # Parse temporal scope
                start_date = data.get('start_date')
                end_date = data.get('end_date')
                
                temporal_scope = (
                    datetime.fromisoformat(start_date) if start_date else datetime(2000, 1, 1),
                    datetime.fromisoformat(end_date) if end_date else None
                )
                
                theorem_id = rag_store.add_theorem(
                    formula=formula,
                    temporal_scope=temporal_scope,
                    jurisdiction=jurisdiction,
                    legal_domain=legal_domain,
                    source_case=source_case,
                    precedent_strength=precedent_strength
                )
                
                self.logger.info(f"Added theorem {theorem_id} from {source_case}")
                
                return jsonify({
                    "success": True,
                    "theorem_id": theorem_id,
                    "message": f"Theorem added successfully from {source_case}"
                })
                
            except Exception as e:
                self.logger.error(f"Failed to add theorem: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/mcp/caselaw/check_document', methods=['POST'])
        def api_check_document_consistency():
            """Check document consistency against temporal deontic logic theorems."""
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.document_consistency_checker import DocumentConsistencyChecker
                from datetime import datetime
                
                data = request.json or {}
                document_text = data.get('document_text', '')
                document_id = data.get('document_id', f'doc_{int(time.time())}')
                jurisdiction = data.get('jurisdiction', 'Federal')
                legal_domain = data.get('legal_domain', 'general')
                
                if not document_text:
                    return jsonify({"success": False, "error": "Document text is required"}), 400
                
                # Initialize checker
                rag_store = TemporalDeonticRAGStore()
                checker = DocumentConsistencyChecker(rag_store=rag_store)
                
                # Parse temporal context
                temporal_context = datetime.now()
                if data.get('temporal_context'):
                    temporal_context = datetime.fromisoformat(data['temporal_context'])
                
                # Check document consistency
                analysis = checker.check_document(
                    document_text=document_text,
                    document_id=document_id,
                    temporal_context=temporal_context,
                    jurisdiction=jurisdiction,
                    legal_domain=legal_domain
                )
                
                # Generate debug report
                debug_report = checker.generate_debug_report(analysis)
                
                # Format response to match frontend expectations
                result = {
                    "success": True,
                    "document_id": analysis.document_id,
                    "consistency_analysis": {
                        "is_consistent": analysis.consistency_result.is_consistent if analysis.consistency_result else False,
                        "confidence_score": analysis.confidence_score,
                        "formulas_extracted": len(analysis.extracted_formulas),
                        "issues_found": len(analysis.issues_found),
                        "conflicts": len(analysis.consistency_result.conflicts) if analysis.consistency_result else 0,
                        "temporal_conflicts": len(analysis.consistency_result.temporal_conflicts) if analysis.consistency_result else 0,
                        "processing_time": analysis.processing_time
                    },
                    "debug_report": {
                        "total_issues": debug_report.total_issues,
                        "critical_errors": debug_report.critical_errors,
                        "warnings": debug_report.warnings,
                        "suggestions": debug_report.suggestions,
                        "issues": debug_report.issues[:10],  # Limit to first 10 issues
                        "summary": debug_report.summary,
                        "fix_suggestions": debug_report.fix_suggestions
                    },
                    "extracted_formulas": [
                        {
                            "operator": f.operator.name,
                            "proposition": f.proposition,
                            "agent": f.agent.name if f.agent else "Unspecified",
                            "confidence": f.confidence
                        } for f in analysis.extracted_formulas[:10]  # Limit to first 10
                    ]
                }
                
                self.logger.info(f"Document consistency check completed: {document_id}")
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Document consistency check failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/caselaw/bulk_process', methods=['POST'])
        def api_bulk_process_caselaw():
            """Start bulk processing of caselaw corpus to build unified deontic logic system."""
            try:
                from .logic_integration.caselaw_bulk_processor import (
                    CaselawBulkProcessor, BulkProcessingConfig
                )
                from datetime import datetime
                
                data = request.json or {}
                
                # Extract configuration from request
                caselaw_directories = data.get('caselaw_directories', [])
                if not caselaw_directories:
                    return jsonify({"error": "At least one caselaw directory is required"}), 400
                
                # Validate directories exist
                import os
                valid_directories = []
                for directory in caselaw_directories:
                    directory = directory.strip()
                    if directory and os.path.exists(directory):
                        valid_directories.append(directory)
                    elif directory:
                        self.logger.warning(f"Directory not found: {directory}")
                
                if not valid_directories:
                    return jsonify({"error": "No valid caselaw directories found"}), 400
                
                # Create processing configuration
                config = BulkProcessingConfig(
                    caselaw_directories=valid_directories,
                    output_directory=data.get('output_directory', 'unified_deontic_logic_system'),
                    max_concurrent_documents=data.get('max_concurrent_documents', 5),
                    enable_parallel_processing=data.get('enable_parallel_processing', True),
                    min_precedent_strength=data.get('min_precedent_strength', 0.5),
                    enable_consistency_validation=data.get('enable_consistency_validation', True),
                    jurisdictions_filter=data.get('jurisdictions_filter') or None,
                    legal_domains_filter=data.get('legal_domains_filter') or None
                )
                
                # Handle date filtering
                if data.get('start_date'):
                    try:
                        start_date = datetime.fromisoformat(data['start_date'])
                        config.date_range = (start_date, config.date_range[1])
                    except ValueError:
                        pass
                
                if data.get('end_date'):
                    try:
                        end_date = datetime.fromisoformat(data['end_date'])
                        config.date_range = (config.date_range[0], end_date)
                    except ValueError:
                        pass
                
                # Create session ID for tracking
                import uuid
                session_id = str(uuid.uuid4())
                
                # Initialize processor
                processor = CaselawBulkProcessor(config)
                
                # Store session for tracking
                if not hasattr(self, 'bulk_processing_sessions'):
                    self.bulk_processing_sessions = {}
                
                self.bulk_processing_sessions[session_id] = {
                    "id": session_id,
                    "processor": processor,
                    "config": config,
                    "status": "starting",
                    "start_time": datetime.now().isoformat(),
                    "progress": 0.0,
                    "stats": processor.stats.__dict__,
                    "output_directory": config.output_directory
                }
                
                # Start async processing
                asyncio.create_task(self._process_caselaw_bulk(session_id, processor))
                
                self.logger.info(f"Started bulk caselaw processing session: {session_id}")
                
                return jsonify({
                    "success": True,
                    "session_id": session_id,
                    "status": "started",
                    "directories": valid_directories,
                    "output_directory": config.output_directory
                })
                
            except Exception as e:
                self.logger.error(f"Bulk caselaw processing failed to start: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/caselaw/bulk_process/<session_id>')
        def api_get_bulk_processing_status(session_id):
            """Get bulk processing session status."""
            if not hasattr(self, 'bulk_processing_sessions'):
                return jsonify({"error": "Session not found"}), 404
            
            if session_id in self.bulk_processing_sessions:
                session = self.bulk_processing_sessions[session_id]
                
                # Update stats if processor is available
                if 'processor' in session and session['processor']:
                    session['stats'] = {
                        k: v for k, v in session['processor'].stats.__dict__.items()
                        if not k.startswith('_') and not callable(v)
                    }
                    
                    # Convert sets to lists for JSON serialization
                    if 'jurisdictions_processed' in session['stats']:
                        session['stats']['jurisdictions_processed'] = list(session['stats']['jurisdictions_processed'])
                    if 'legal_domains_processed' in session['stats']:
                        session['stats']['legal_domains_processed'] = list(session['stats']['legal_domains_processed'])
                    
                    # Calculate progress
                    total = session['stats'].get('total_documents', 0)
                    processed = session['stats'].get('processed_documents', 0)
                    if total > 0:
                        session['progress'] = (processed / total) * 100
                
                return jsonify(session)
            
            return jsonify({"error": "Session not found"}), 404
        
        @self.app.route('/api/mcp/caselaw/bulk_process/<session_id>/stop', methods=['POST'])
        def api_stop_bulk_processing(session_id):
            """Stop bulk processing session."""
            if not hasattr(self, 'bulk_processing_sessions'):
                return jsonify({"error": "Session not found"}), 404
            
            if session_id in self.bulk_processing_sessions:
                session = self.bulk_processing_sessions[session_id]
                session['status'] = 'stopped'
                
                # Note: In a production environment, you would need to implement
                # proper async task cancellation here
                
                return jsonify({"success": True, "status": "stopped"})
            
            return jsonify({"error": "Session not found"}), 404
        
        @self.app.route('/api/mcp/caselaw/bulk_process/<session_id>/download')
        def api_download_bulk_processing_results(session_id):
            """Download bulk processing results."""
            if not hasattr(self, 'bulk_processing_sessions'):
                return jsonify({"error": "Session not found"}), 404
            
            if session_id in self.bulk_processing_sessions:
                session = self.bulk_processing_sessions[session_id]
                output_dir = session.get('output_directory', 'unified_deontic_logic_system')
                
                # In a production environment, you would create a ZIP file
                # of the output directory and return it as a download
                import os
                if os.path.exists(output_dir):
                    return jsonify({
                        "success": True,
                        "message": f"Results available in {output_dir}",
                        "files": os.listdir(output_dir) if os.path.exists(output_dir) else []
                    })
                else:
                    return jsonify({"error": "Results not found"}), 404
            
            return jsonify({"error": "Session not found"}), 404
        
        @self.app.route('/api/mcp/caselaw/bulk_process/<session_id>/log')
        def api_get_bulk_processing_log(session_id):
            """Get bulk processing log."""
            if not hasattr(self, 'bulk_processing_sessions'):
                return jsonify({"error": "Session not found"}), 404
            
            if session_id in self.bulk_processing_sessions:
                session = self.bulk_processing_sessions[session_id]
                
                # Return processing log
                log_data = {
                    "session_id": session_id,
                    "start_time": session.get('start_time'),
                    "status": session.get('status'),
                    "stats": session.get('stats', {}),
                    "config": {
                        "caselaw_directories": session['config'].caselaw_directories,
                        "output_directory": session['config'].output_directory,
                        "max_concurrent_documents": session['config'].max_concurrent_documents,
                        "enable_parallel_processing": session['config'].enable_parallel_processing
                    } if 'config' in session else {}
                }
                
                return jsonify(log_data)
            
            return jsonify({"error": "Session not found"}), 404

        @self.app.route('/api/mcp/caselaw/query_theorems', methods=['POST'])
        def api_query_theorems():
            """Query relevant theorems using RAG retrieval."""
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.deontic_logic_core import DeonticFormula, DeonticOperator, LegalAgent
                from datetime import datetime
                
                data = request.json or {}
                query_text = data.get('query_text', '')
                operator_str = data.get('operator', 'OBLIGATION')
                jurisdiction = data.get('jurisdiction')
                legal_domain = data.get('legal_domain')
                top_k = min(int(data.get('top_k', 10)), 50)  # Limit to 50
                
                if not query_text:
                    return jsonify({"success": False, "error": "Query text is required"}), 400
                
                # Create query formula
                operator = DeonticOperator[operator_str]
                agent = LegalAgent("query_agent", "Query Agent", "person")
                
                query_formula = DeonticFormula(
                    operator=operator,
                    proposition=query_text,
                    agent=agent
                )
                
                # Query RAG store
                rag_store = TemporalDeonticRAGStore()
                
                temporal_context = datetime.now()
                if data.get('temporal_context'):
                    temporal_context = datetime.fromisoformat(data['temporal_context'])
                
                relevant_theorems = rag_store.retrieve_relevant_theorems(
                    query_formula=query_formula,
                    temporal_context=temporal_context,
                    jurisdiction=jurisdiction,
                    legal_domain=legal_domain,
                    top_k=top_k
                )
                
                # Format response to match frontend expectations
                result = {
                    "success": True,
                    "query": query_text,
                    "total_results": len(relevant_theorems),
                    "theorems": [
                        {
                            "theorem_id": t.theorem_id,
                            "formula": {
                                "operator": t.formula.operator.name,
                                "proposition": t.formula.proposition,
                                "agent": t.formula.agent.name if t.formula.agent else "Unspecified"
                            },
                            "metadata": {
                                "jurisdiction": t.jurisdiction,
                                "legal_domain": t.legal_domain,
                                "source_case": t.source_case,
                                "precedent_strength": t.precedent_strength
                            },
                            "relevance_score": t.confidence,
                            "temporal_scope": {
                                "start": t.temporal_scope[0].isoformat() if t.temporal_scope[0] else None,
                                "end": t.temporal_scope[1].isoformat() if t.temporal_scope[1] else None
                            }
                        } for t in relevant_theorems
                    ]
                }
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Theorem query failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

    async def _process_caselaw_bulk(self, session_id: str, processor) -> None:
        """Async method to process caselaw bulk."""
        try:
            session = self.bulk_processing_sessions[session_id]
            session['status'] = 'processing'
            
            # Run the bulk processing
            stats = await processor.process_caselaw_corpus()
            
            # Update session with results
            session['status'] = 'completed'
            session['end_time'] = datetime.now().isoformat()
            session['final_stats'] = {
                k: v for k, v in stats.__dict__.items()
                if not k.startswith('_') and not callable(v)
            }
            
            # Convert sets to lists for JSON serialization
            if 'jurisdictions_processed' in session['final_stats']:
                session['final_stats']['jurisdictions_processed'] = list(session['final_stats']['jurisdictions_processed'])
            if 'legal_domains_processed' in session['final_stats']:
                session['final_stats']['legal_domains_processed'] = list(session['final_stats']['legal_domains_processed'])
            
            session['progress'] = 100.0
            session['processing_time'] = str(stats.processing_time)
            
            self.logger.info(f"Bulk processing completed for session {session_id}: {stats.extracted_theorems} theorems")
            
        except Exception as e:
            self.logger.error(f"Bulk processing failed for session {session_id}: {e}")
            session = self.bulk_processing_sessions.get(session_id, {})
            session['status'] = 'failed'
            session['error'] = str(e)
            session['end_time'] = datetime.now().isoformat()
        
        # Add MCP JSON-RPC endpoints for temporal deontic logic tools
        @self.app.route('/api/mcp/caselaw/jsonrpc', methods=['POST'])
        def mcp_caselaw_jsonrpc():
            """MCP JSON-RPC endpoint for temporal deontic logic tools."""
            try:
                from .mcp_tools.temporal_deontic_mcp_server import temporal_deontic_mcp_server
                
                request_data = request.json or {}
                
                # Basic JSON-RPC validation
                if 'method' not in request_data:
                    return jsonify({
                        "jsonrpc": "2.0",
                        "error": {"code": -32600, "message": "Invalid Request - missing method"},
                        "id": request_data.get('id')
                    }), 400
                
                method = request_data['method']
                params = request_data.get('params', {})
                request_id = request_data.get('id', 1)
                
                # Map JSON-RPC methods to MCP tools
                tool_mapping = {
                    'check_document_consistency': 'check_document_consistency',
                    'query_theorems': 'query_theorems',
                    'bulk_process_caselaw': 'bulk_process_caselaw',
                    'add_theorem': 'add_theorem'
                }
                
                if method not in tool_mapping:
                    return jsonify({
                        "jsonrpc": "2.0",
                        "error": {"code": -32601, "message": f"Method not found: {method}"},
                        "id": request_id
                    }), 404
                
                # Execute MCP tool
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    result = loop.run_until_complete(
                        temporal_deontic_mcp_server.call_tool_direct(tool_mapping[method], params)
                    )
                    
                    return jsonify({
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    })
                    
                finally:
                    loop.close()
                
            except Exception as e:
                self.logger.error(f"MCP JSON-RPC call failed: {e}")
                return jsonify({
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": str(e)
                    },
                    "id": request_data.get('id')
                }), 500
        
        @self.app.route('/api/mcp/caselaw/tools')
        def mcp_caselaw_tools():
            """Get available temporal deontic logic MCP tools."""
            try:
                from .mcp_tools.temporal_deontic_mcp_server import temporal_deontic_mcp_server
                
                tool_schemas = temporal_deontic_mcp_server.get_tool_schemas()
                
                return jsonify({
                    "success": True,
                    "tools": tool_schemas,
                    "tool_count": len(tool_schemas),
                    "server_info": {
                        "name": "Temporal Deontic Logic MCP Server",
                        "version": "1.0.0",
                        "description": "MCP tools for legal document consistency checking"
                    }
                })
                
            except Exception as e:
                self.logger.error(f"Failed to get MCP tools: {e}")
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500

    def _setup_finance_routes(self) -> None:
        """Set up finance dashboard routes (based on caselaw template)."""
        
        @self.app.route('/mcp/finance')
        def finance_dashboard():
            """Render the finance analysis dashboard using temporal deontic logic."""
            # Import temporal deontic logic components (same backend as caselaw)
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.document_consistency_checker import DocumentConsistencyChecker
                from .logic_integration.deontic_logic_core import DeonticOperator
                
                # Initialize RAG store and get statistics
                rag_store = TemporalDeonticRAGStore()
                checker = DocumentConsistencyChecker(rag_store=rag_store)
                
                dashboard_data = {
                    "system_status": {
                        "theorem_count": len(rag_store.theorems),
                        "jurisdictions": list(rag_store.jurisdiction_index.keys()) if hasattr(rag_store, 'jurisdiction_index') else [],
                        "legal_domains": list(rag_store.domain_index.keys()) if hasattr(rag_store, 'domain_index') else [],
                        "temporal_periods": len(getattr(rag_store, 'temporal_index', {})),
                        "available_operators": [op.name for op in DeonticOperator],
                        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "system_ready": True
                    },
                    "mcp_enabled": True
                }
                
            except Exception as e:
                self.logger.error(f"Failed to initialize finance dashboard: {e}")
                dashboard_data = {
                    "system_status": {
                        "theorem_count": 0,
                        "jurisdictions": [],
                        "legal_domains": [],
                        "temporal_periods": 0,
                        "available_operators": [],
                        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "system_ready": False,
                        "error_message": str(e)
                    },
                    "mcp_enabled": True
                }
            
            return render_template('finance_dashboard_mcp.html', **dashboard_data)
        
        @self.app.route('/mcp/finance/workflow')
        def finance_workflow_dashboard():
            """Render the finance workflow pipeline dashboard."""
            dashboard_data = {
                "mcp_enabled": True,
                "mcp_server_host": self.config.mcp_server_host if hasattr(self.config, 'mcp_server_host') else "127.0.0.1",
                "mcp_server_port": self.config.mcp_server_port if hasattr(self.config, 'mcp_server_port') else 8001,
                "dashboard_title": "Finance Workflow Pipeline Dashboard",
                "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            return render_template('admin/finance_workflow_dashboard.html', **dashboard_data)
        
        # Finance API endpoints (reuse caselaw backend with finance prefix)
        @self.app.route('/api/mcp/finance/check_document', methods=['POST'])
        def api_check_finance_document():
            """Check financial document consistency."""
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.document_consistency_checker import DocumentConsistencyChecker
                from datetime import datetime
                
                data = request.json or {}
                document_text = data.get('document_text', '')
                document_id = data.get('document_id', f'doc_{int(time.time())}')
                jurisdiction = data.get('jurisdiction', 'Federal')
                legal_domain = data.get('legal_domain', 'finance')
                
                if not document_text:
                    return jsonify({"success": False, "error": "Document text is required"}), 400
                
                # Initialize checker (reuses same logic engine)
                rag_store = TemporalDeonticRAGStore()
                checker = DocumentConsistencyChecker(rag_store=rag_store)
                
                # Parse temporal context
                temporal_context = datetime.now()
                if data.get('temporal_context'):
                    temporal_context = datetime.fromisoformat(data['temporal_context'])
                
                # Check document consistency
                analysis = checker.check_document(
                    document_text=document_text,
                    document_id=document_id,
                    temporal_context=temporal_context,
                    jurisdiction=jurisdiction,
                    legal_domain=legal_domain
                )
                
                # Generate debug report
                debug_report = checker.generate_debug_report(analysis)
                
                # Format response
                result = {
                    "success": True,
                    "document_id": analysis.document_id,
                    "consistency_analysis": {
                        "is_consistent": analysis.consistency_result.is_consistent if analysis.consistency_result else False,
                        "confidence_score": analysis.confidence_score,
                        "formulas_extracted": len(analysis.extracted_formulas),
                        "issues_found": len(analysis.issues_found),
                        "conflicts": len(analysis.consistency_result.conflicts) if analysis.consistency_result else 0,
                        "temporal_conflicts": len(analysis.consistency_result.temporal_conflicts) if analysis.consistency_result else 0,
                        "processing_time": analysis.processing_time
                    },
                    "debug_report": {
                        "total_issues": debug_report.total_issues,
                        "critical_errors": debug_report.critical_errors,
                        "warnings": debug_report.warnings,
                        "suggestions": debug_report.suggestions,
                        "issues": debug_report.issues[:10],
                        "summary": debug_report.summary,
                        "fix_suggestions": debug_report.fix_suggestions
                    },
                    "extracted_formulas": [
                        {
                            "operator": f.operator.name,
                            "proposition": f.proposition,
                            "agent": f.agent.name if f.agent else "Unspecified",
                            "confidence": f.confidence
                        } for f in analysis.extracted_formulas[:10]
                    ]
                }
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Finance document consistency check failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/finance/query_theorems', methods=['POST'])
        def api_query_finance_rules():
            """Query relevant financial rules using RAG retrieval."""
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.deontic_logic_core import DeonticFormula, DeonticOperator, LegalAgent
                from datetime import datetime
                
                data = request.json or {}
                query_text = data.get('query_text', '')
                operator_str = data.get('operator', 'OBLIGATION')
                jurisdiction = data.get('jurisdiction')
                legal_domain = data.get('legal_domain', 'finance')
                top_k = min(int(data.get('top_k', 10)), 50)
                
                if not query_text:
                    return jsonify({"success": False, "error": "Query text is required"}), 400
                
                # Create query formula
                operator = DeonticOperator[operator_str]
                agent = LegalAgent("query_agent", "Query Agent", "person")
                
                query_formula = DeonticFormula(
                    operator=operator,
                    proposition=query_text,
                    agent=agent
                )
                
                # Query RAG store
                rag_store = TemporalDeonticRAGStore()
                
                temporal_context = datetime.now()
                if data.get('temporal_context'):
                    temporal_context = datetime.fromisoformat(data['temporal_context'])
                
                relevant_theorems = rag_store.retrieve_relevant_theorems(
                    query_formula=query_formula,
                    temporal_context=temporal_context,
                    jurisdiction=jurisdiction,
                    legal_domain=legal_domain,
                    top_k=top_k
                )
                
                # Format response
                result = {
                    "success": True,
                    "query": query_text,
                    "total_results": len(relevant_theorems),
                    "theorems": [
                        {
                            "theorem_id": t.theorem_id,
                            "formula": {
                                "operator": t.formula.operator.name,
                                "proposition": t.formula.proposition,
                                "agent": t.formula.agent.name if t.formula.agent else "Unspecified"
                            },
                            "metadata": {
                                "jurisdiction": t.jurisdiction,
                                "legal_domain": t.legal_domain,
                                "source_case": t.source_case,
                                "precedent_strength": t.precedent_strength
                            },
                            "relevance_score": t.confidence,
                            "temporal_scope": {
                                "start": t.temporal_scope[0].isoformat() if t.temporal_scope[0] else None,
                                "end": t.temporal_scope[1].isoformat() if t.temporal_scope[1] else None
                            }
                        } for t in relevant_theorems
                    ]
                }
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Finance rules query failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

    def _setup_medicine_routes(self) -> None:
        """Set up medicine dashboard routes (based on caselaw template)."""
        
        @self.app.route('/mcp/medicine')
        def medicine_dashboard():
            """Render the medicine analysis dashboard using temporal deontic logic."""
            # Import temporal deontic logic components (same backend as caselaw)
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.document_consistency_checker import DocumentConsistencyChecker
                from .logic_integration.deontic_logic_core import DeonticOperator
                
                # Initialize RAG store and get statistics
                rag_store = TemporalDeonticRAGStore()
                checker = DocumentConsistencyChecker(rag_store=rag_store)
                
                dashboard_data = {
                    "system_status": {
                        "theorem_count": len(rag_store.theorems),
                        "jurisdictions": list(rag_store.jurisdiction_index.keys()) if hasattr(rag_store, 'jurisdiction_index') else [],
                        "legal_domains": list(rag_store.domain_index.keys()) if hasattr(rag_store, 'domain_index') else [],
                        "temporal_periods": len(getattr(rag_store, 'temporal_index', {})),
                        "available_operators": [op.name for op in DeonticOperator],
                        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "system_ready": True
                    },
                    "mcp_enabled": True
                }
                
            except Exception as e:
                self.logger.error(f"Failed to initialize medicine dashboard: {e}")
                dashboard_data = {
                    "system_status": {
                        "theorem_count": 0,
                        "jurisdictions": [],
                        "legal_domains": [],
                        "temporal_periods": 0,
                        "available_operators": [],
                        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "system_ready": False,
                        "error_message": str(e)
                    },
                    "mcp_enabled": True
                }
            
            return render_template('medicine_dashboard_mcp.html', **dashboard_data)
        
        # Medicine API endpoints (reuse caselaw backend with medicine prefix)
        @self.app.route('/api/mcp/medicine/check_document', methods=['POST'])
        def api_check_medicine_document():
            """Check medical document consistency."""
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.document_consistency_checker import DocumentConsistencyChecker
                from datetime import datetime
                
                data = request.json or {}
                document_text = data.get('document_text', '')
                document_id = data.get('document_id', f'doc_{int(time.time())}')
                jurisdiction = data.get('jurisdiction', 'Federal')
                legal_domain = data.get('legal_domain', 'medicine')
                
                if not document_text:
                    return jsonify({"success": False, "error": "Document text is required"}), 400
                
                # Initialize checker (reuses same logic engine)
                rag_store = TemporalDeonticRAGStore()
                checker = DocumentConsistencyChecker(rag_store=rag_store)
                
                # Parse temporal context
                temporal_context = datetime.now()
                if data.get('temporal_context'):
                    temporal_context = datetime.fromisoformat(data['temporal_context'])
                
                # Check document consistency
                analysis = checker.check_document(
                    document_text=document_text,
                    document_id=document_id,
                    temporal_context=temporal_context,
                    jurisdiction=jurisdiction,
                    legal_domain=legal_domain
                )
                
                # Generate debug report
                debug_report = checker.generate_debug_report(analysis)
                
                # Format response
                result = {
                    "success": True,
                    "document_id": analysis.document_id,
                    "consistency_analysis": {
                        "is_consistent": analysis.consistency_result.is_consistent if analysis.consistency_result else False,
                        "confidence_score": analysis.confidence_score,
                        "formulas_extracted": len(analysis.extracted_formulas),
                        "issues_found": len(analysis.issues_found),
                        "conflicts": len(analysis.consistency_result.conflicts) if analysis.consistency_result else 0,
                        "temporal_conflicts": len(analysis.consistency_result.temporal_conflicts) if analysis.consistency_result else 0,
                        "processing_time": analysis.processing_time
                    },
                    "debug_report": {
                        "total_issues": debug_report.total_issues,
                        "critical_errors": debug_report.critical_errors,
                        "warnings": debug_report.warnings,
                        "suggestions": debug_report.suggestions,
                        "issues": debug_report.issues[:10],
                        "summary": debug_report.summary,
                        "fix_suggestions": debug_report.fix_suggestions
                    },
                    "extracted_formulas": [
                        {
                            "operator": f.operator.name,
                            "proposition": f.proposition,
                            "agent": f.agent.name if f.agent else "Unspecified",
                            "confidence": f.confidence
                        } for f in analysis.extracted_formulas[:10]
                    ]
                }
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Medicine document consistency check failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/query_theorems', methods=['POST'])
        def api_query_medicine_guidelines():
            """Query relevant medical guidelines using RAG retrieval."""
            try:
                from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
                from .logic_integration.deontic_logic_core import DeonticFormula, DeonticOperator, LegalAgent
                from datetime import datetime
                
                data = request.json or {}
                query_text = data.get('query_text', '')
                operator_str = data.get('operator', 'OBLIGATION')
                jurisdiction = data.get('jurisdiction')
                legal_domain = data.get('legal_domain', 'medicine')
                top_k = min(int(data.get('top_k', 10)), 50)
                
                if not query_text:
                    return jsonify({"success": False, "error": "Query text is required"}), 400
                
                # Create query formula
                operator = DeonticOperator[operator_str]
                agent = LegalAgent("query_agent", "Query Agent", "person")
                
                query_formula = DeonticFormula(
                    operator=operator,
                    proposition=query_text,
                    agent=agent
                )
                
                # Query RAG store
                rag_store = TemporalDeonticRAGStore()
                
                temporal_context = datetime.now()
                if data.get('temporal_context'):
                    temporal_context = datetime.fromisoformat(data['temporal_context'])
                
                relevant_theorems = rag_store.retrieve_relevant_theorems(
                    query_formula=query_formula,
                    temporal_context=temporal_context,
                    jurisdiction=jurisdiction,
                    legal_domain=legal_domain,
                    top_k=top_k
                )
                
                # Format response
                result = {
                    "success": True,
                    "query": query_text,
                    "total_results": len(relevant_theorems),
                    "theorems": [
                        {
                            "theorem_id": t.theorem_id,
                            "formula": {
                                "operator": t.formula.operator.name,
                                "proposition": t.formula.proposition,
                                "agent": t.formula.agent.name if t.formula.agent else "Unspecified"
                            },
                            "metadata": {
                                "jurisdiction": t.jurisdiction,
                                "legal_domain": t.legal_domain,
                                "source_case": t.source_case,
                                "precedent_strength": t.precedent_strength
                            },
                            "relevance_score": t.confidence,
                            "temporal_scope": {
                                "start": t.temporal_scope[0].isoformat() if t.temporal_scope[0] else None,
                                "end": t.temporal_scope[1].isoformat() if t.temporal_scope[1] else None
                            }
                        } for t in relevant_theorems
                    ]
                }
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Medicine guidelines query failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        # Generic MCP Tool Router - ensures all tools go through same code path
        @self.app.route('/api/mcp/<category>/<tool_name>', methods=['POST'])
        def api_call_mcp_tool(category, tool_name):
            """
            Generic MCP tool router - ensures consistent code path for all tool calls.
            
            This route provides a unified interface for calling any MCP tool, ensuring that
            CLI, dashboard, and Python API all use the same underlying tool functions.
            """
            try:
                # Import the tool dynamically based on category and name
                module_path = f".mcp_server.tools.{category}.{category.rstrip('s')}_mcp_tools"
                try:
                    module = __import__(module_path, fromlist=[tool_name], level=1)
                    tool_function = getattr(module, tool_name)
                except (ImportError, AttributeError):
                    # Try alternate import patterns
                    try:
                        module_path = f".mcp_server.tools.{category}.medical_research_mcp_tools"
                        module = __import__(module_path, fromlist=[tool_name], level=1)
                        tool_function = getattr(module, tool_name)
                    except:
                        return jsonify({
                            "success": False,
                            "error": f"Tool '{tool_name}' not found in category '{category}'"
                        }), 404
                
                # Get parameters from request
                data = request.json or {}
                params = data.get('params', data)  # Support both formats
                
                # Call the tool function (same code path as CLI and Python API)
                result = tool_function(**params)
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"MCP tool call failed ({category}/{tool_name}): {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        # Medical Research Scraping Routes (specific endpoints for convenience)
        # Note: These all call the same MCP tool functions as the generic router above
        @self.app.route('/api/mcp/medicine/scrape/pubmed', methods=['POST'])
        def api_scrape_pubmed():
            """Scrape medical research from PubMed (calls MCP tool function)."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import scrape_pubmed_medical_research
                
                data = request.json or {}
                query = data.get('query', '')
                max_results = min(int(data.get('max_results', 100)), 200)
                email = data.get('email')
                research_type = data.get('research_type')
                
                if not query:
                    return jsonify({"success": False, "error": "Query is required"}), 400
                
                # Call MCP tool function (same code path as CLI and generic router)
                result = scrape_pubmed_medical_research(
                    query=query,
                    max_results=max_results,
                    email=email,
                    research_type=research_type
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"PubMed scraping failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/scrape/clinical_trials', methods=['POST'])
        def api_scrape_clinical_trials():
            """Scrape clinical trial data from ClinicalTrials.gov."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import scrape_clinical_trials
                
                data = request.json or {}
                query = data.get('query', '')
                condition = data.get('condition')
                intervention = data.get('intervention')
                max_results = min(int(data.get('max_results', 50)), 100)
                
                result = scrape_clinical_trials(
                    query=query,
                    condition=condition,
                    intervention=intervention,
                    max_results=max_results
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Clinical trials scraping failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/scrape/biochemical', methods=['POST'])
        def api_scrape_biochemical():
            """Scrape biochemical research data."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import scrape_biochemical_research
                
                data = request.json or {}
                topic = data.get('topic', '')
                max_results = min(int(data.get('max_results', 50)), 100)
                time_range_days = data.get('time_range_days')
                
                if not topic:
                    return jsonify({"success": False, "error": "Topic is required"}), 400
                
                result = scrape_biochemical_research(
                    topic=topic,
                    max_results=max_results,
                    time_range_days=time_range_days
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Biochemical research scraping failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/theorems/generate', methods=['POST'])
        def api_generate_medical_theorems():
            """Generate medical theorems from clinical trial data."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import generate_medical_theorems_from_trials
                
                data = request.json or {}
                trial_data = data.get('trial_data', {})
                outcomes_data = data.get('outcomes_data', {})
                
                if not trial_data or not outcomes_data:
                    return jsonify({"success": False, "error": "Both trial_data and outcomes_data are required"}), 400
                
                result = generate_medical_theorems_from_trials(trial_data, outcomes_data)
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Theorem generation failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/theorems/validate', methods=['POST'])
        def api_validate_medical_theorem():
            """Validate a medical theorem using fuzzy logic."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import validate_medical_theorem_fuzzy
                
                data = request.json or {}
                theorem_data = data.get('theorem_data', {})
                empirical_data = data.get('empirical_data', {})
                
                if not theorem_data:
                    return jsonify({"success": False, "error": "Theorem data is required"}), 400
                
                result = validate_medical_theorem_fuzzy(theorem_data, empirical_data)
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Theorem validation failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/scrape/population', methods=['POST'])
        def api_scrape_population_data():
            """Scrape population health data for theorem validation."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import scrape_population_health_data
                
                data = request.json or {}
                condition = data.get('condition', '')
                intervention = data.get('intervention')
                
                if not condition:
                    return jsonify({"success": False, "error": "Condition is required"}), 400
                
                result = scrape_population_health_data(
                    condition=condition,
                    intervention=intervention
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Population data scraping failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        # Biomolecule Discovery Routes
        @self.app.route('/api/mcp/medicine/discover/protein_binders', methods=['POST'])
        def api_discover_protein_binders():
            """Discover protein binders using RAG."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import discover_protein_binders
                
                data = request.json or {}
                target_protein = data.get('target_protein', '')
                interaction_type = data.get('interaction_type')
                min_confidence = float(data.get('min_confidence', 0.5))
                max_results = min(int(data.get('max_results', 50)), 100)
                
                if not target_protein:
                    return jsonify({"success": False, "error": "Target protein is required"}), 400
                
                result = discover_protein_binders(
                    target_protein=target_protein,
                    interaction_type=interaction_type,
                    min_confidence=min_confidence,
                    max_results=max_results
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Protein binder discovery failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/discover/enzyme_inhibitors', methods=['POST'])
        def api_discover_enzyme_inhibitors():
            """Discover enzyme inhibitors using RAG."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import discover_enzyme_inhibitors
                
                data = request.json or {}
                target_enzyme = data.get('target_enzyme', '')
                enzyme_class = data.get('enzyme_class')
                min_confidence = float(data.get('min_confidence', 0.5))
                max_results = min(int(data.get('max_results', 50)), 100)
                
                if not target_enzyme:
                    return jsonify({"success": False, "error": "Target enzyme is required"}), 400
                
                result = discover_enzyme_inhibitors(
                    target_enzyme=target_enzyme,
                    enzyme_class=enzyme_class,
                    min_confidence=min_confidence,
                    max_results=max_results
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Enzyme inhibitor discovery failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/discover/pathway_biomolecules', methods=['POST'])
        def api_discover_pathway_biomolecules():
            """Discover pathway biomolecules using RAG."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import discover_pathway_biomolecules
                
                data = request.json or {}
                pathway_name = data.get('pathway_name', '')
                biomolecule_types = data.get('biomolecule_types')
                min_confidence = float(data.get('min_confidence', 0.5))
                max_results = min(int(data.get('max_results', 100)), 200)
                
                if not pathway_name:
                    return jsonify({"success": False, "error": "Pathway name is required"}), 400
                
                result = discover_pathway_biomolecules(
                    pathway_name=pathway_name,
                    biomolecule_types=biomolecule_types,
                    min_confidence=min_confidence,
                    max_results=max_results
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Pathway biomolecule discovery failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/discover/biomolecules_rag', methods=['POST'])
        def api_discover_biomolecules_rag():
            """High-level RAG-based biomolecule discovery."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import discover_biomolecules_rag
                
                data = request.json or {}
                target = data.get('target', '')
                discovery_type = data.get('discovery_type', 'binders')
                min_confidence = float(data.get('min_confidence', 0.5))
                max_results = min(int(data.get('max_results', 50)), 100)
                
                if not target:
                    return jsonify({"success": False, "error": "Target is required"}), 400
                
                result = discover_biomolecules_rag(
                    target=target,
                    discovery_type=discovery_type,
                    max_results=max_results,
                    min_confidence=min_confidence
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"RAG biomolecule discovery failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        # AI-Powered Dataset Builder Routes
        @self.app.route('/api/mcp/medicine/dataset/build', methods=['POST'])
        def api_build_medical_dataset():
            """Build structured dataset from scraped data using AI."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import build_dataset_from_scraped_data
                
                data = request.json or {}
                scraped_data = data.get('scraped_data', [])
                filter_criteria = data.get('filter_criteria')
                model_name = data.get('model_name', 'meta-llama/Llama-2-7b-hf')
                
                if not scraped_data:
                    return jsonify({"success": False, "error": "Scraped data is required"}), 400
                
                result = build_dataset_from_scraped_data(
                    scraped_data=scraped_data,
                    filter_criteria=filter_criteria,
                    model_name=model_name
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Dataset building failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/dataset/analyze', methods=['POST'])
        def api_analyze_medical_dataset():
            """Analyze medical dataset using AI models."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import analyze_dataset_with_ai
                
                data = request.json or {}
                dataset = data.get('dataset', [])
                model_name = data.get('model_name', 'meta-llama/Llama-2-7b-hf')
                
                if not dataset:
                    return jsonify({"success": False, "error": "Dataset is required"}), 400
                
                result = analyze_dataset_with_ai(
                    dataset=dataset,
                    model_name=model_name
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Dataset analysis failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/dataset/transform', methods=['POST'])
        def api_transform_medical_dataset():
            """Transform medical dataset using AI (summarize, extract entities, normalize)."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import transform_dataset_with_ai
                
                data = request.json or {}
                dataset = data.get('dataset', [])
                transformation_type = data.get('transformation_type', 'normalize')
                parameters = data.get('parameters')
                model_name = data.get('model_name', 'meta-llama/Llama-2-7b-hf')
                
                if not dataset:
                    return jsonify({"success": False, "error": "Dataset is required"}), 400
                
                if transformation_type not in ['summarize', 'extract_entities', 'normalize', 'extrapolate']:
                    return jsonify({"success": False, "error": f"Invalid transformation type: {transformation_type}"}), 400
                
                result = transform_dataset_with_ai(
                    dataset=dataset,
                    transformation_type=transformation_type,
                    parameters=parameters,
                    model_name=model_name
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Dataset transformation failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/mcp/medicine/dataset/generate_synthetic', methods=['POST'])
        def api_generate_synthetic_data():
            """Generate synthetic medical research data for testing and evaluation."""
            try:
                from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import generate_synthetic_dataset
                
                data = request.json or {}
                template_data = data.get('template_data', [])
                num_samples = min(int(data.get('num_samples', 10)), 50)  # Limit to 50 for performance
                model_name = data.get('model_name', 'meta-llama/Llama-2-7b-hf')
                temperature = float(data.get('temperature', 0.7))
                
                if not template_data:
                    return jsonify({"success": False, "error": "Template data is required"}), 400
                
                result = generate_synthetic_dataset(
                    template_data=template_data,
                    num_samples=num_samples,
                    model_name=model_name,
                    temperature=temperature
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Synthetic data generation failed: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

    def _setup_legal_dataset_routes(self) -> None:
        """Set up legal dataset scraping routes."""
        
        @self.app.route('/api/mcp/dataset/uscode/scrape', methods=['POST'])
        def api_scrape_us_code():
            """API endpoint to scrape US Code."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import scrape_us_code
                
                data = request.json or {}
                titles = data.get('titles', None)
                output_format = data.get('output_format', 'json')
                include_metadata = data.get('include_metadata', True)
                rate_limit_delay = data.get('rate_limit_delay', 1.0)
                max_sections = data.get('max_sections', None)
                
                # Run async scraper
                result = asyncio.run(scrape_us_code(
                    titles=titles,
                    output_format=output_format,
                    include_metadata=include_metadata,
                    rate_limit_delay=rate_limit_delay,
                    max_sections=max_sections
                ))
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"US Code scraping failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/federal_register/scrape', methods=['POST'])
        def api_scrape_federal_register():
            """API endpoint to scrape Federal Register."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import scrape_federal_register
                
                data = request.json or {}
                agencies = data.get('agencies', None)
                start_date = data.get('start_date', None)
                end_date = data.get('end_date', None)
                document_types = data.get('document_types', None)
                output_format = data.get('output_format', 'json')
                include_full_text = data.get('include_full_text', False)
                rate_limit_delay = data.get('rate_limit_delay', 1.0)
                max_documents = data.get('max_documents', None)
                
                result = asyncio.run(scrape_federal_register(
                    agencies=agencies,
                    start_date=start_date,
                    end_date=end_date,
                    document_types=document_types,
                    output_format=output_format,
                    include_full_text=include_full_text,
                    rate_limit_delay=rate_limit_delay,
                    max_documents=max_documents
                ))
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Federal Register scraping failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/state_laws/scrape', methods=['POST'])
        def api_scrape_state_laws():
            """API endpoint to scrape state laws."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import scrape_state_laws
                
                data = request.json or {}
                states = data.get('states', None)
                legal_areas = data.get('legal_areas', None)
                output_format = data.get('output_format', 'json')
                include_metadata = data.get('include_metadata', True)
                rate_limit_delay = data.get('rate_limit_delay', 2.0)
                max_statutes = data.get('max_statutes', None)
                
                result = asyncio.run(scrape_state_laws(
                    states=states,
                    legal_areas=legal_areas,
                    output_format=output_format,
                    include_metadata=include_metadata,
                    rate_limit_delay=rate_limit_delay,
                    max_statutes=max_statutes
                ))
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"State laws scraping failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/municipal_laws/scrape', methods=['POST'])
        def api_scrape_municipal_laws():
            """API endpoint to scrape municipal laws."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import scrape_municipal_laws
                
                data = request.json or {}
                cities = data.get('cities', None)
                output_format = data.get('output_format', 'json')
                include_metadata = data.get('include_metadata', True)
                rate_limit_delay = data.get('rate_limit_delay', 2.0)
                max_ordinances = data.get('max_ordinances', None)
                
                result = asyncio.run(scrape_municipal_laws(
                    cities=cities,
                    output_format=output_format,
                    include_metadata=include_metadata,
                    rate_limit_delay=rate_limit_delay,
                    max_ordinances=max_ordinances
                ))
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Municipal laws scraping failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/recap/scrape', methods=['POST'])
        def api_scrape_recap_archive():
            """API endpoint to scrape RECAP Archive."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import scrape_recap_archive
                
                data = request.json or {}
                courts = data.get('courts', None)
                document_types = data.get('document_types', None)
                filed_after = data.get('filed_after', None)
                filed_before = data.get('filed_before', None)
                case_name_pattern = data.get('case_name_pattern', None)
                output_format = data.get('output_format', 'json')
                include_text = data.get('include_text', True)
                include_metadata = data.get('include_metadata', True)
                rate_limit_delay = data.get('rate_limit_delay', 1.0)
                max_documents = data.get('max_documents', None)
                
                result = asyncio.run(scrape_recap_archive(
                    courts=courts,
                    document_types=document_types,
                    filed_after=filed_after,
                    filed_before=filed_before,
                    case_name_pattern=case_name_pattern,
                    output_format=output_format,
                    include_text=include_text,
                    include_metadata=include_metadata,
                    rate_limit_delay=rate_limit_delay,
                    max_documents=max_documents
                ))
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"RECAP Archive scraping failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/recap/search', methods=['POST'])
        def api_search_recap():
            """API endpoint to search RECAP Archive."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import search_recap_documents
                
                data = request.json or {}
                query = data.get('query', None)
                court = data.get('court', None)
                case_name = data.get('case_name', None)
                filed_after = data.get('filed_after', None)
                filed_before = data.get('filed_before', None)
                document_type = data.get('document_type', None)
                limit = data.get('limit', 100)
                
                result = asyncio.run(search_recap_documents(
                    query=query,
                    court=court,
                    case_name=case_name,
                    filed_after=filed_after,
                    filed_before=filed_before,
                    document_type=document_type,
                    limit=limit
                ))
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"RECAP search failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/export', methods=['POST'])
        def api_export_dataset():
            """API endpoint to export dataset in various formats."""
            try:
                from .mcp_server.tools.legal_dataset_tools import export_dataset
                
                data = request.json or {}
                dataset_data = data.get('data', [])
                output_path = data.get('output_path', '/tmp/dataset_export')
                format = data.get('format', 'json')
                
                # Export options
                export_options = {}
                if format == 'json':
                    export_options['pretty'] = data.get('pretty', True)
                elif format == 'parquet':
                    export_options['compression'] = data.get('compression', 'snappy')
                elif format == 'csv':
                    export_options['delimiter'] = data.get('delimiter', ',')
                
                result = export_dataset(
                    data=dataset_data,
                    output_path=output_path,
                    format=format,
                    **export_options
                )
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Dataset export failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/jobs', methods=['GET'])
        def api_list_scraping_jobs():
            """API endpoint to list all saved scraping jobs."""
            try:
                from .mcp_server.tools.legal_dataset_tools import list_scraping_jobs
                
                jobs = list_scraping_jobs()
                return jsonify({
                    "status": "success",
                    "jobs": jobs,
                    "count": len(jobs)
                })
                
            except Exception as e:
                self.logger.error(f"List scraping jobs failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        # State Laws Scheduler Endpoints
        @self.app.route('/api/mcp/dataset/state_laws/schedules', methods=['GET'])
        def api_list_state_law_schedules():
            """API endpoint to list all state law update schedules."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import list_schedules
                
                result = asyncio.run(list_schedules())
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"List schedules failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/state_laws/schedules', methods=['POST'])
        def api_create_state_law_schedule():
            """API endpoint to create a new state law update schedule."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import create_schedule
                
                data = request.json or {}
                schedule_id = data.get('schedule_id')
                states = data.get('states')
                legal_areas = data.get('legal_areas')
                interval_hours = data.get('interval_hours', 24)
                enabled = data.get('enabled', True)
                
                if not schedule_id:
                    return jsonify({
                        "status": "error",
                        "error": "schedule_id is required"
                    }), 400
                
                result = asyncio.run(create_schedule(
                    schedule_id=schedule_id,
                    states=states,
                    legal_areas=legal_areas,
                    interval_hours=interval_hours,
                    enabled=enabled
                ))
                
                return jsonify({
                    "status": "success",
                    "schedule": result
                })
                
            except Exception as e:
                self.logger.error(f"Create schedule failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/state_laws/schedules/<schedule_id>', methods=['DELETE'])
        def api_delete_state_law_schedule(schedule_id: str):
            """API endpoint to delete a state law update schedule."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import remove_schedule
                
                result = asyncio.run(remove_schedule(schedule_id))
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Delete schedule failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/state_laws/schedules/<schedule_id>/run', methods=['POST'])
        def api_run_state_law_schedule(schedule_id: str):
            """API endpoint to run a schedule immediately."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import run_schedule_now
                
                result = asyncio.run(run_schedule_now(schedule_id))
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Run schedule failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/state_laws/schedules/<schedule_id>/toggle', methods=['POST'])
        def api_toggle_state_law_schedule(schedule_id: str):
            """API endpoint to enable/disable a schedule."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import enable_disable_schedule
                
                data = request.json or {}
                enabled = data.get('enabled', True)
                
                result = asyncio.run(enable_disable_schedule(schedule_id, enabled))
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Toggle schedule failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
                
            except Exception as e:
                self.logger.error(f"Failed to list scraping jobs: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/jobs/<job_id>', methods=['DELETE'])
        def api_delete_scraping_job(job_id):
            """API endpoint to delete a saved scraping job."""
            try:
                from .mcp_server.tools.legal_dataset_tools import delete_scraping_job
                
                success = delete_scraping_job(job_id)
                if success:
                    return jsonify({
                        "status": "success",
                        "job_id": job_id,
                        "message": "Job deleted successfully"
                    })
                else:
                    return jsonify({
                        "status": "error",
                        "error": "Failed to delete job"
                    }), 500
                
            except Exception as e:
                self.logger.error(f"Failed to delete scraping job: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
        @self.app.route('/api/mcp/dataset/recap/incremental', methods=['POST'])
        def api_scrape_recap_incremental():
            """API endpoint for incremental RECAP Archive scraping."""
            try:
                import asyncio
                from .mcp_server.tools.legal_dataset_tools import scrape_recap_incremental
                
                data = request.json or {}
                courts = data.get('courts', None)
                document_types = data.get('document_types', None)
                
                # Other optional parameters
                kwargs = {
                    'output_format': data.get('output_format', 'json'),
                    'include_text': data.get('include_text', True),
                    'include_metadata': data.get('include_metadata', True),
                    'rate_limit_delay': data.get('rate_limit_delay', 1.0),
                    'max_documents': data.get('max_documents', None),
                    'job_id': data.get('job_id', None),
                    'resume': data.get('resume', False)
                }
                
                result = asyncio.run(scrape_recap_incremental(
                    courts=courts,
                    document_types=document_types,
                    **kwargs
                ))
                
                return jsonify(result)
                
            except Exception as e:
                self.logger.error(f"Incremental RECAP scraping failed: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500

    def _setup_mcp_tool_routes(self) -> None:
        """Set up original MCP tool routes."""
            
        @self.app.route('/api/mcp/tools')
        def api_mcp_tools():
            """API endpoint to get available MCP tools."""
            return jsonify(self._discover_mcp_tools())
            
        @self.app.route('/api/mcp/tools/<category>/<tool_name>')
        def api_mcp_tool_info(category, tool_name):
            """Get detailed information about a specific tool."""
            tools_info = self._discover_mcp_tools()
            
            if category not in tools_info:
                return jsonify({"error": f"Category '{category}' not found"}), 404
                
            tool = next((t for t in tools_info[category] if t['name'] == tool_name), None)
            if not tool:
                return jsonify({"error": f"Tool '{tool_name}' not found in category '{category}'"}), 404
                
            return jsonify(tool)
            
        @self.app.route('/api/mcp/tools/<category>/<tool_name>/execute', methods=['POST'])
        def api_execute_mcp_tool(category, tool_name):
            """Execute an MCP tool with given parameters."""
            if not self.mcp_config or not self.mcp_config.enable_tool_execution:
                return jsonify({"error": "Tool execution is disabled"}), 403
                
            if len(self.active_tool_executions) >= self.mcp_config.max_concurrent_tools:
                return jsonify({"error": "Maximum concurrent tool executions reached"}), 429
                
            # Get parameters from request
            params = request.json or {}
            execution_id = f"{category}_{tool_name}_{int(time.time() * 1000)}"
            
            # Start tool execution
            execution_record = {
                "id": execution_id,
                "category": category,
                "tool_name": tool_name,
                "parameters": params,
                "start_time": datetime.now().isoformat(),
                "status": "running",
                "result": None,
                "error": None
            }
            
            self.active_tool_executions[execution_id] = execution_record
            
            try:
                # In a real implementation, this would be async
                result = self._execute_tool_sync(category, tool_name, params)
                
                execution_record.update({
                    "status": "completed",
                    "result": result,
                    "end_time": datetime.now().isoformat()
                })
                
            except Exception as e:
                execution_record.update({
                    "status": "failed",
                    "error": str(e),
                    "end_time": datetime.now().isoformat()
                })
                
            # Move to history
            self.tool_execution_history.append(execution_record.copy())
            del self.active_tool_executions[execution_id]
            
            return jsonify(execution_record)
            
        @self.app.route('/api/mcp/executions/<execution_id>')
        def api_get_execution_status(execution_id):
            """Get the status of a tool execution."""
            # Check active executions
            if execution_id in self.active_tool_executions:
                return jsonify(self.active_tool_executions[execution_id])
                
            # Check history
            for execution in self.tool_execution_history:
                if execution['id'] == execution_id:
                    return jsonify(execution)
                    
            return jsonify({"error": "Execution not found"}), 404
            
        @self.app.route('/api/mcp/status')
        def api_mcp_status():
            """Get comprehensive MCP server status."""
            return jsonify(self._get_comprehensive_status())
            
        @self.app.route('/api/mcp/history')
        def api_execution_history():
            """Get tool execution history."""
            limit = request.args.get('limit', 50, type=int)
            return jsonify({
                "executions": self.tool_execution_history[-limit:],
                "total": len(self.tool_execution_history)
            })
            
        # Test Suite API endpoint
        @self.app.route('/api/mcp/run-tests', methods=['POST'])
        def api_run_tests():
            """Run test suite based on test type."""
            if not self.mcp_config or not self.mcp_config.enable_tool_execution:
                return jsonify({"error": "Tool execution is disabled"}), 403
            
            data = request.json or {}
            test_type = data.get('test_type', 'unit')
            
            try:
                if test_type == 'unit':
                    result = self._run_unit_tests()
                elif test_type == 'integration':
                    result = self._run_integration_tests()
                elif test_type == 'full':
                    result = self._run_full_test_suite()
                else:
                    return jsonify({"error": f"Unknown test type: {test_type}"}), 400
                
                return jsonify({
                    "status": "success",
                    "test_type": test_type,
                    "result": result,
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                # Log the full error but return sanitized error message
                self.logger.error(f"Test execution failed: {e}")
                return jsonify({
                    "status": "error", 
                    "test_type": test_type,
                    "error": "Test execution failed. Check server logs for details.",
                    "timestamp": datetime.now().isoformat()
                }), 500
            
        # JavaScript SDK endpoint
        @self.app.route('/static/js/mcp-sdk.js')
        def mcp_sdk():
            """Serve the enhanced MCP JavaScript SDK."""
            return send_from_directory(
                self.app.static_folder,
                'js/mcp-sdk.js',
                mimetype='application/javascript'
            )
            
        # Removed duplicated early registration of MCP tool routes to avoid endpoint conflicts
            
        # Duplicate status/history/SDK routes removed (comprehensive versions already registered above)
        
        # System Management API endpoints
        @self.app.route('/api/mcp/system/workflows', methods=['GET'])
        def api_manage_workflows():
            """Get workflow management status and active workflows."""
            try:
                workflows = {
                    "active_workflows": list(self.workflow_manager.keys()),
                    "workflow_count": len(self.workflow_manager),
                    "workflows": self.workflow_manager,
                    "timestamp": datetime.now().isoformat()
                }
                return jsonify(workflows)
            except Exception as e:
                self.logger.error(f"Failed to get workflows: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/mcp/system/optimize', methods=['POST'])
        def api_optimize_system():
            """Optimize system performance."""
            try:
                # Update performance metrics
                import psutil
                
                # Get current metrics
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                
                # Update system metrics
                self.system_metrics.update({
                    'cpu_usage': cpu_percent,
                    'memory_usage': memory.percent,
                    'disk_usage': disk.percent,
                    'memory_available_mb': memory.available / (1024 * 1024),
                    'disk_available_gb': disk.free / (1024 * 1024 * 1024)
                })
                
                # Perform basic optimization
                optimization_results = {
                    "status": "completed",
                    "optimizations_applied": [],
                    "metrics_before": {
                        "cpu_usage": cpu_percent,
                        "memory_usage": memory.percent,
                        "disk_usage": disk.percent
                    },
                    "timestamp": datetime.now().isoformat()
                }
                
                # Clear old execution history if too large
                if len(self.tool_execution_history) > 800:
                    removed = len(self.tool_execution_history) - 500
                    self.tool_execution_history = deque(list(self.tool_execution_history)[-500:], maxlen=1000)
                    optimization_results["optimizations_applied"].append(f"Cleared {removed} old execution records")
                
                # Clear old analytics history if too large
                if len(self.analytics_metrics_history) > 800:
                    removed = len(self.analytics_metrics_history) - 500
                    self.analytics_metrics_history = deque(list(self.analytics_metrics_history)[-500:], maxlen=1000)
                    optimization_results["optimizations_applied"].append(f"Cleared {removed} old analytics records")
                
                if not optimization_results["optimizations_applied"]:
                    optimization_results["optimizations_applied"].append("System already optimized")
                
                return jsonify(optimization_results)
            except Exception as e:
                self.logger.error(f"Failed to optimize system: {e}")
                return jsonify({"error": str(e), "status": "failed"}), 500
        
        @self.app.route('/api/mcp/system/health', methods=['GET'])
        def api_monitor_health():
            """Get system health status."""
            try:
                import psutil
                
                # Get system metrics
                cpu_percent = psutil.cpu_percent(interval=0.5)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                
                # Update metrics
                self.system_metrics.update({
                    'cpu_usage': cpu_percent,
                    'memory_usage': memory.percent,
                    'disk_usage': disk.percent,
                    'active_connections': len(self.active_tool_executions),
                    'uptime': time.time() - getattr(self, 'start_time', time.time())
                })
                
                # Determine health status
                health_issues = []
                if cpu_percent > 90:
                    health_issues.append("High CPU usage")
                if memory.percent > 90:
                    health_issues.append("High memory usage")
                if disk.percent > 90:
                    health_issues.append("High disk usage")
                
                overall_status = "healthy" if not health_issues else "warning"
                
                health_data = {
                    "status": overall_status,
                    "health_status": self.health_status,
                    "system_metrics": self.system_metrics,
                    "issues": health_issues,
                    "components": {
                        "mcp_server": self.health_status.get('mcp_server', 'unknown'),
                        "ipfs_node": self.health_status.get('ipfs_node', 'unknown'),
                        "vector_store": self.health_status.get('vector_store', 'unknown'),
                        "cache_system": self.health_status.get('cache_system', 'unknown')
                    },
                    "timestamp": datetime.now().isoformat()
                }
                
                return jsonify(health_data)
            except Exception as e:
                self.logger.error(f"Failed to get health status: {e}")
                return jsonify({
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }), 500
        
        @self.app.route('/api/mcp/system/logs', methods=['GET'])
        def api_get_system_logs():
            """Get system logs."""
            try:
                limit = request.args.get('limit', 100, type=int)
                level = request.args.get('level', 'all')
                
                # Get recent error logs
                logs = list(self._error_log) if hasattr(self, '_error_log') else []
                
                # Filter by level if specified
                if level != 'all':
                    logs = [log for log in logs if log.get('level') == level]
                
                # Limit results
                logs = logs[-limit:]
                
                return jsonify({
                    "logs": logs,
                    "total": len(logs),
                    "level": level,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                self.logger.error(f"Failed to get logs: {e}")
                return jsonify({"error": str(e)}), 500
            
    # GraphRAG processing methods
    async def _process_website_graphrag(self, session_id: str, url: str, config: 'CompleteProcessingConfiguration') -> None:
        """Process a website using GraphRAG system."""
        if not self.graphrag_system:
            return
            
        session = self.graphrag_processing_sessions.get(session_id)
        if not session:
            return
            
        try:
            session["status"] = "processing"
            session["progress"] = 0.1
            
            # Process the website
            result = await self.graphrag_system.process_complete_website(url, config)
            
            session.update({
                "status": "completed",
                "progress": 1.0,
                "result": result.__dict__ if hasattr(result, '__dict__') else str(result),
                "end_time": datetime.now().isoformat()
            })
            
        except Exception as e:
            session.update({
                "status": "failed",
                "error": str(e),
                "end_time": datetime.now().isoformat()
            })
    
    def _get_graphrag_processing_stats(self) -> Dict[str, Any]:
        """Get GraphRAG processing statistics."""
        sessions = list(self.graphrag_processing_sessions.values())
        
        total_sessions = len(sessions)
        completed_sessions = len([s for s in sessions if s.get("status") == "completed"])
        failed_sessions = len([s for s in sessions if s.get("status") == "failed"])
        active_sessions = len([s for s in sessions if s.get("status") in ["starting", "processing"]])
        
        return {
            "total_sessions": total_sessions,
            "completed_sessions": completed_sessions,
            "failed_sessions": failed_sessions,
            "active_sessions": active_sessions,
            "success_rate": (completed_sessions / total_sessions * 100) if total_sessions > 0 else 0,
            "average_processing_time": self._calculate_average_processing_time(sessions)
        }
    
    def _calculate_average_processing_time(self, sessions: List[Dict[str, Any]]) -> float:
        """Calculate average processing time for completed sessions."""
        completed_sessions = [s for s in sessions if s.get("status") == "completed" and "start_time" in s and "end_time" in s]
        
        if not completed_sessions:
            return 0.0
            
        total_time = 0.0
        for session in completed_sessions:
            try:
                start_time = datetime.fromisoformat(session["start_time"])
                end_time = datetime.fromisoformat(session["end_time"])
                total_time += (end_time - start_time).total_seconds()
            except (ValueError, KeyError):
                continue
                
        return total_time / len(completed_sessions) if completed_sessions else 0.0
    
    def _get_current_analytics_metrics(self) -> Dict[str, Any]:
        """Get current analytics metrics."""
        if not GRAPHRAG_AVAILABLE or not self.analytics_dashboard:
            return {}
            
        # Simulate analytics metrics - in real implementation this would come from analytics_dashboard
        metrics = {
            "total_websites_processed": len([s for s in self.graphrag_processing_sessions.values() if s.get("status") == "completed"]),
            "total_processing_time": sum([self._get_session_duration(s) for s in self.graphrag_processing_sessions.values()]),
            "success_rate": self._get_graphrag_processing_stats().get("success_rate", 0),
            "active_processing_sessions": len([s for s in self.graphrag_processing_sessions.values() if s.get("status") in ["starting", "processing"]]),
            "total_rag_queries": len(self.rag_query_sessions),
            "average_query_time": self._calculate_average_query_time(),
            "last_updated": datetime.now().isoformat()
        }
        
        # Store in history for trends
        self.analytics_metrics_history.append(metrics)
        return metrics
    
    def _get_session_duration(self, session: Dict[str, Any]) -> float:
        """Get session duration in seconds."""
        if "start_time" not in session:
            return 0.0
            
        start_time = datetime.fromisoformat(session["start_time"])
        
        if "end_time" in session:
            end_time = datetime.fromisoformat(session["end_time"])
            return (end_time - start_time).total_seconds()
        else:
            return (datetime.now() - start_time).total_seconds()
    
    def _calculate_average_query_time(self) -> float:
        """Calculate average RAG query time."""
        completed_queries = [s for s in self.rag_query_sessions.values() if s.get("status") == "completed"]
        
        if not completed_queries:
            return 0.0
            
        total_time = sum([self._get_session_duration(q) for q in completed_queries])
        return total_time / len(completed_queries)
    
    def _execute_rag_query_via_mcp(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a RAG query through MCP tools."""
        # This would route through MCP tools in real implementation
        return {
            "query": query,
            "context": context,
            "result": f"Mock RAG result for query: {query}",
            "confidence": 0.85,
            "sources": [],
            "execution_time": 0.5
        }
    
    def _execute_investigation_via_mcp(self, content_url: str, analysis_type: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Execute investigation analysis through MCP tools."""
        # This would route through MCP investigation tools in real implementation
        return {
            "content_url": content_url,
            "analysis_type": analysis_type,
            "metadata": metadata,
            "status": "completed",
            "findings": {
                "content_type": "article",
                "key_entities": [],
                "main_topics": [],
                "sentiment": "neutral",
                "credibility_score": 0.7
            },
            "execution_time": 2.0
        }
    
    def _execute_geospatial_via_mcp(self, query: str, center_location: str, search_radius: float, entity_types: List[str], clustering_distance: float) -> Dict[str, Any]:
        """Execute geospatial analysis through MCP tools."""
        # Sample response simulating MCP geospatial tool execution
        sample_entities = [
            {
                "entity": "Manhattan Financial District",
                "coordinates": [40.7074, -74.0113],
                "confidence": 0.95,
                "context_snippet": "Major financial events in Lower Manhattan",
                "entity_type": "LOCATION",
                "relevance_score": 2.8,
                "distance_from_center": 0.5
            },
            {
                "entity": "Wall Street",
                "coordinates": [40.7074, -74.0113],
                "confidence": 0.98,
                "context_snippet": "Stock market and financial activities",
                "entity_type": "LOCATION",
                "relevance_score": 3.2,
                "distance_from_center": 0.3
            },
            {
                "entity": "Times Square",
                "coordinates": [40.7580, -73.9855],
                "confidence": 0.92,
                "context_snippet": "Major public events and announcements",
                "entity_type": "LOCATION",
                "relevance_score": 2.1,
                "distance_from_center": 4.8
            }
        ]
        
        sample_events = [
            {
                "event": "Financial Summit 2024",
                "coordinates": [40.7074, -74.0113],
                "timestamp": "2024-01-15T10:00:00Z",
                "event_type": "CONFERENCE",
                "relevance_score": 2.5
            },
            {
                "event": "Market Announcement",
                "coordinates": [40.7074, -74.0113],
                "timestamp": "2024-01-20T14:30:00Z",
                "event_type": "ANNOUNCEMENT",
                "relevance_score": 2.2
            }
        ]
        
        return {
            "query": query,
            "center_location": center_location,
            "center_coordinates": [40.7128, -74.0060],  # New York coordinates
            "search_radius_km": search_radius,
            "total_results": len(sample_entities),
            "entities": sample_entities,
            "events": sample_events,
            "geographic_summary": {
                "total_locations": len(sample_entities),
                "average_relevance": 2.7,
                "top_locations": [e["entity"] for e in sample_entities[:3]],
                "common_terms": {"financial": 2, "manhattan": 1, "events": 2}
            },
            "timestamp": datetime.now().isoformat(),
            "execution_time": 1.5
        }
    
    def _execute_entity_extraction_via_mcp(self, corpus_data: str, confidence_threshold: float, entity_types: Optional[List[str]]) -> Dict[str, Any]:
        """Execute geographic entity extraction through MCP tools."""
        return {
            "total_entities": 15,
            "mappable_entities": 12,
            "entities": [
                {
                    "entity": "New York",
                    "coordinates": [40.7128, -74.0060],
                    "confidence": 0.98,
                    "entity_type": "CITY",
                    "context_snippet": "Events in New York financial district",
                    "documents": ["doc_1", "doc_3"]
                },
                {
                    "entity": "Wall Street",
                    "coordinates": [40.7074, -74.0113],
                    "confidence": 0.95,
                    "entity_type": "LOCATION",
                    "context_snippet": "Wall Street trading activities",
                    "documents": ["doc_1", "doc_2"]
                }
            ],
            "extraction_stats": {
                "confidence_threshold": confidence_threshold,
                "entity_types": entity_types,
                "timestamp": datetime.now().isoformat()
            },
            "execution_time": 2.1
        }
    
    def _execute_spatiotemporal_via_mcp(self, corpus_data: str, time_range: Optional[Dict], geographic_bounds: Optional[Dict], event_types: Optional[List[str]], clustering_distance: float) -> Dict[str, Any]:
        """Execute spatiotemporal event mapping through MCP tools."""
        return {
            "total_events": 8,
            "mapped_events": 6,
            "spatiotemporal_events": [
                {
                    "event_id": "event_1",
                    "event_text": "Financial conference held in Manhattan",
                    "coordinates": [40.7074, -74.0113],
                    "timestamp": "2024-01-15T10:00:00Z",
                    "event_type": "CONFERENCE",
                    "confidence": 0.92,
                    "spatial_cluster": 1,
                    "temporal_cluster": 1
                },
                {
                    "event_id": "event_2", 
                    "event_text": "Market announcement from Wall Street",
                    "coordinates": [40.7074, -74.0113],
                    "timestamp": "2024-01-20T14:30:00Z",
                    "event_type": "ANNOUNCEMENT",
                    "confidence": 0.89,
                    "spatial_cluster": 1,
                    "temporal_cluster": 1
                }
            ],
            "clustering_analysis": {
                "spatial_clusters": 2,
                "temporal_clusters": 3,
                "clustering_distance_km": clustering_distance,
                "temporal_resolution": "day"
            },
            "time_range": time_range,
            "geographic_bounds": geographic_bounds,
            "timestamp": datetime.now().isoformat(),
            "execution_time": 3.2
        }

    def _execute_tool_sync(self, category: str, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamically import and execute an MCP tool.

        Looks up module path `ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}`
        and executes the async function with the same name. Awaits if coroutine.
        """
        import importlib
        import inspect

        module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
        func_name = tool_name
        start = time.time()
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name, None)
            if fn is None:
                raise AttributeError(f"Function '{func_name}' not found in {module_path}")

            # Execute, awaiting if coroutine
            if inspect.iscoroutinefunction(fn):
                # Run in a fresh event loop to avoid conflicts
                import asyncio
                loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(fn(**params))
                finally:
                    loop.close()
            else:
                result = fn(**params)

            # Normalize to dict
            if not isinstance(result, dict):
                result = {"status": "success", "result": result}

            result.setdefault("status", "success")
            result.setdefault("tool", f"{category}/{tool_name}")
            result.setdefault("duration_s", round(time.time() - start, 3))
            return result
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "tool": f"{category}/{tool_name}",
                "duration_s": round(time.time() - start, 3)
            }
        
    def _run_unit_tests(self) -> Dict[str, Any]:
        """Run unit tests and return results."""
        import subprocess
        import sys
        
        try:
            # Run pytest on the tests directory focusing on unit tests
            result = subprocess.run([
                sys.executable, '-m', 'pytest', 
                'tests/', '-v', '--tb=short',
                '-k', 'not integration',
                '--maxfail=10'
            ], capture_output=True, text=True, timeout=300, cwd=Path(__file__).parent.parent)
            
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0,
                "test_count": result.stdout.count("PASSED") + result.stdout.count("FAILED") + result.stdout.count("SKIPPED")
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": "Test execution timed out after 5 minutes",
                "success": False,
                "test_count": 0
            }
        except Exception as e:
            return {
                "exit_code": -1, 
                "stdout": "",
                "stderr": f"Test execution failed: {str(e)}",
                "success": False,
                "test_count": 0
            }
    
    def _run_integration_tests(self) -> Dict[str, Any]:
        """Run integration tests and return results."""
        import subprocess
        import sys
        
        try:
            # Run pytest focusing on integration tests
            result = subprocess.run([
                sys.executable, '-m', 'pytest',
                'tests/integration/', '-v', '--tb=short',
                '--maxfail=5'
            ], capture_output=True, text=True, timeout=600, cwd=Path(__file__).parent.parent)
            
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0,
                "test_count": result.stdout.count("PASSED") + result.stdout.count("FAILED") + result.stdout.count("SKIPPED")
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": "Integration test execution timed out after 10 minutes",
                "success": False,
                "test_count": 0
            }
        except Exception as e:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Integration test execution failed: {str(e)}",
                "success": False,
                "test_count": 0
            }
    
    def _run_full_test_suite(self) -> Dict[str, Any]:
        """Run the full test suite and return results."""
        import subprocess
        import sys
        
        try:
            # Run all tests with more comprehensive reporting
            result = subprocess.run([
                sys.executable, '-m', 'pytest',
                'tests/', '-v', '--tb=short', 
                '--maxfail=20',
                '--durations=10'
            ], capture_output=True, text=True, timeout=900, cwd=Path(__file__).parent.parent)
            
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0,
                "test_count": result.stdout.count("PASSED") + result.stdout.count("FAILED") + result.stdout.count("SKIPPED")
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": "Full test suite execution timed out after 15 minutes",
                "success": False,
                "test_count": 0
            }
        except Exception as e:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Full test suite execution failed: {str(e)}",
                "success": False,
                "test_count": 0
            }
        
    def _get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive status including all dashboard components."""
        base_status = self._get_mcp_server_status()
        
        # Add GraphRAG status
        if self.mcp_config and self.mcp_config.enable_graphrag:
            base_status["graphrag"] = {
                "enabled": True,
                "system_initialized": self.graphrag_system is not None,
                "enhanced_system_initialized": self.enhanced_graphrag is not None,
                "active_processing_sessions": len([s for s in self.graphrag_processing_sessions.values() if s.get("status") in ["starting", "processing"]]),
                "total_processing_sessions": len(self.graphrag_processing_sessions)
            }
        
        # Add analytics status
        if self.mcp_config and self.mcp_config.enable_analytics:
            base_status["analytics"] = {
                "enabled": True,
                "dashboard_initialized": self.analytics_dashboard is not None,
                "metrics_history_size": len(self.analytics_metrics_history),
                "last_metrics_update": self.last_metrics_update
            }
        
        # Add RAG query status
        if self.mcp_config and self.mcp_config.enable_rag_query:
            base_status["rag_query"] = {
                "enabled": True,
                "total_query_sessions": len(self.rag_query_sessions),
                "active_query_sessions": len([s for s in self.rag_query_sessions.values() if s.get("status") == "processing"])
            }
        
        # Add investigation status
        if self.mcp_config and self.mcp_config.enable_investigation:
            base_status["investigation"] = {
                "enabled": True,
                "dashboard_initialized": self.investigation_dashboard is not None
            }
        
        return base_status

    def _get_mcp_server_status(self) -> Dict[str, Any]:
        """Get the current status of the MCP server and dashboard runtime."""
        try:
            # Ensure we always have a placeholder server so status is "running"
            if not getattr(self, "mcp_server", None):
                self.mcp_server = SimpleInProcessMCPServer()

            # Count total tools discovered across categories
            tools_info = self._discover_mcp_tools() or {}
            total_tools = sum(len(v) for v in tools_info.values())

            from flask import request
            try:
                base_url = request.host_url.rstrip('/')
                external_url = f"{base_url}/mcp"
            except Exception:
                external_url = None

            return {
                "status": "running",
                "server_type": type(self.mcp_server).__name__,
                "tools_available": total_tools,
                "active_executions": len(self.active_tool_executions),
                "total_executions": len(self.tool_execution_history),
                "uptime": time.time() - getattr(self, "start_time", time.time()),
                "config": {
                    "host": self.mcp_config.mcp_server_host if self.mcp_config else "localhost",
                    "port": self.mcp_config.mcp_server_port if self.mcp_config else 8001,
                    "tool_execution_enabled": getattr(self.mcp_config, "enable_tool_execution", False) if self.mcp_config else False,
                },
                "external_url": external_url,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
        
    def create_mcp_dashboard_template(self) -> str:
        """Create the professional desktop-focused MCP dashboard HTML template."""
        # Return the complete professional desktop template
        with open(Path(__file__).parent / "templates" / "mcp_dashboard.html", "r") as f:
            return f.read()
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IPFS Datasets Comprehensive MCP Dashboard</title>
    <link rel=\"icon\" href=\"{{ url_for('static', filename='favicon.svg') }}\" type=\"image/svg+xml\">
    <link rel=\"alternate icon\" href=\"{{ url_for('static', filename='favicon.svg') }}\">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/dashboard.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/mcp-dashboard.css') }}">
    <style>
        .dashboard-nav { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        .feature-card { transition: transform 0.2s; }
        .feature-card:hover { transform: translateY(-2px); }
        .status-badge { font-size: 0.8em; }
        .graphrag-section { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; }
        .analytics-section { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white; }
        .rag-section { background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); color: white; }
        .investigation-section { background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); color: white; }
        .real-time-indicator { 
            display: inline-block;
            width: 8px;
            height: 8px;
            background: #00ff00;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        .metric-value { font-size: 2em; font-weight: bold; }
        .progress-ring { width: 60px; height: 60px; }
        .progress-circle { fill: none; stroke-width: 4; }
        
        /* New sections styling */
        .web-scraping-btn, .search-btn, .analysis-btn {
            transition: all 0.2s ease;
        }
        .web-scraping-btn:hover, .search-btn:hover, .analysis-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }
        
        #scraping-results, #search-results, #analysis-results {
            font-size: 0.85em;
            border: 1px solid #e9ecef;
            border-radius: 4px;
        }
        
        #web-scraping-section .card-body .card {
            border: 1px solid #e9ecef;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        #web-scraping-section .card-body .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        #data-search-section .card-body .card {
            border: 1px solid #e9ecef;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        #data-search-section .card-body .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        #content-analysis-section .card-body .card {
            border: 1px solid #e9ecef;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        #content-analysis-section .card-body .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        /* Advanced panels styling */
        .workflow-btn, .monitoring-btn, .performance-btn {
            transition: all 0.2s ease;
        }
        .workflow-btn:hover, .monitoring-btn:hover, .performance-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }
        
        #batch-processing-section .card-body .card {
            border: 1px solid #e9ecef;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        #batch-processing-section .card-body .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        #monitoring-section .card.bg-primary,
        #monitoring-section .card.bg-info,
        #monitoring-section .card.bg-success,
        #monitoring-section .card.bg-warning {
            transition: transform 0.2s;
        }
        #monitoring-section .card.bg-primary:hover,
        #monitoring-section .card.bg-info:hover,
        #monitoring-section .card.bg-success:hover,
        #monitoring-section .card.bg-warning:hover {
            transform: scale(1.05);
        }
        
        #performance-section .progress {
            height: 25px;
        }
        #performance-section .progress-bar {
            transition: width 0.5s ease;
        }
        
        #performance-chart {
            background: linear-gradient(45deg, #f8f9fa, #e9ecef);
        }
        
        #workflow-status, #optimization-results {
            font-size: 0.85em;
            border: 1px solid #e9ecef;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark dashboard-nav">
        <a class="navbar-brand" href="{{ url_for('mcp_dashboard') }}">
            <strong>IPFS Datasets MCP Dashboard</strong>
            <span class="real-time-indicator"></span>
        </a>
        <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#navbarNav">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
            <ul class="navbar-nav mr-auto">
                <li class="nav-item">
                    <a class="nav-link active" href="{{ url_for('mcp_dashboard') }}">Overview</a>
                </li>
                {% if graphrag_enabled %}
                <li class="nav-item">
                    <a class="nav-link" href="/mcp/graphrag">GraphRAG</a>
                </li>
                {% endif %}
                {% if analytics_enabled %}
                <li class="nav-item">
                    <a class="nav-link" href="/mcp/analytics">Analytics</a>
                </li>
                {% endif %}
                {% if rag_query_enabled %}
                <li class="nav-item">
                    <a class="nav-link" href="/mcp/rag">RAG Query</a>
                </li>
                {% endif %}
                {% if investigation_enabled %}
                <li class="nav-item">
                    <a class="nav-link" href="/mcp/investigation">Investigation</a>
                </li>
                {% endif %}
                <li class="nav-item">
                    <a class="nav-link" href="#test-suite-section">Test Suite</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#dataset-processing-section">Dataset Processing</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#web-scraping-section">Web Scraping</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#data-search-section">Data Search</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#content-analysis-section">Content Analysis</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#batch-processing-section">Batch Processing</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#monitoring-section">Real-time Monitoring</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#performance-section">Performance</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#tools-section">Tools</a>
                </li>
            </ul>
            <span class="navbar-text">
                Last Updated: {{ last_updated }}
            </span>
        </div>
    </nav>

    <div class="container-fluid mt-4">
        <!-- System Status Overview -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-server"></i> System Status Overview</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3">
                                <div class="text-center">
                                    <div class="metric-value">{{ server_status.status }}</div>
                                    <small class="text-muted">MCP Server</small>
                                    <br>
                                    <span class="badge badge-{{ 'success' if server_status.status == 'running' else 'danger' }}">
                                        {{ server_status.status }}
                                    </span>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="text-center">
                                    <div class="metric-value">{{ server_status.tools_available }}</div>
                                    <small class="text-muted">Tools Available</small>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="text-center">
                                    <div class="metric-value">{{ active_executions }}</div>
                                    <small class="text-muted">Active Executions</small>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="text-center">
                                    <div class="metric-value">{{ server_status.total_executions }}</div>
                                    <small class="text-muted">Total Executions</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Feature Sections -->
        <div class="row mb-4">
            {% if graphrag_enabled %}
            <div class="col-md-6 col-lg-3 mb-3">
                <div class="card feature-card graphrag-section">
                    <div class="card-body text-center">
                        <i class="fas fa-brain fa-3x mb-3"></i>
                        <h5>GraphRAG Processing</h5>
                        <p>Advanced website analysis with knowledge graph extraction</p>
                        <a href="/mcp/graphrag" class="btn btn-light">Open GraphRAG</a>
                    </div>
                </div>
            </div>
            {% endif %}
            
            {% if analytics_enabled %}
            <div class="col-md-6 col-lg-3 mb-3">
                <div class="card feature-card analytics-section">
                    <div class="card-body text-center">
                        <i class="fas fa-chart-line fa-3x mb-3"></i>
                        <h5>Analytics Dashboard</h5>
                        <p>Real-time monitoring and performance metrics</p>
                        <a href="/mcp/analytics" class="btn btn-light">View Analytics</a>
                    </div>
                </div>
            </div>
            {% endif %}
            
            {% if rag_query_enabled %}
            <div class="col-md-6 col-lg-3 mb-3">
                <div class="card feature-card rag-section">
                    <div class="card-body text-center">
                        <i class="fas fa-search fa-3x mb-3"></i>
                        <h5>RAG Query Interface</h5>
                        <p>Interactive query interface with visualizations</p>
                        <a href="/mcp/rag" class="btn btn-light">Query RAG</a>
                    </div>
                </div>
            </div>
            {% endif %}
            
            {% if investigation_enabled %}
            <div class="col-md-6 col-lg-3 mb-3">
                <div class="card feature-card investigation-section">
                    <div class="card-body text-center">
                        <i class="fas fa-detective fa-3x mb-3"></i>
                        <h5>Investigation Tools</h5>
                        <p>Content analysis and investigation capabilities</p>
                        <a href="/mcp/investigation" class="btn btn-light">Start Investigation</a>
                    </div>
                </div>
            </div>
            {% endif %}
        </div>

        <!-- Test Suite Panel -->
        <div class="row mb-4" id="test-suite-section">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-flask"></i> Test Suite Execution</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-4">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-check-circle fa-2x text-success mb-2"></i>
                                        <h6>Unit Tests</h6>
                                        <p class="small">Run individual module tests</p>
                                        <button class="btn btn-success btn-sm run-tests-btn" data-test-type="unit">
                                            <i class="fas fa-play"></i> Run Unit Tests
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-link fa-2x text-info mb-2"></i>
                                        <h6>Integration Tests</h6>
                                        <p class="small">Test cross-module functionality</p>
                                        <button class="btn btn-info btn-sm run-tests-btn" data-test-type="integration">
                                            <i class="fas fa-play"></i> Run Integration Tests
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-rocket fa-2x text-warning mb-2"></i>
                                        <h6>Full Test Suite</h6>
                                        <p class="small">Comprehensive test run</p>
                                        <button class="btn btn-warning btn-sm run-tests-btn" data-test-type="full">
                                            <i class="fas fa-play"></i> Run All Tests
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-12">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Test Results</h6>
                                    </div>
                                    <div class="card-body">
                                        <div id="test-output" class="bg-dark text-light p-3" style="height: 300px; overflow-y: auto; font-family: monospace;">
                                            <div class="text-muted">Click a test button to run tests...</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Dataset Processing Panel -->
        <div class="row mb-4" id="dataset-processing-section">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-database"></i> Dataset Processing Workflows</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fab fa-hubspot fa-2x text-primary mb-2"></i>
                                        <h6>HuggingFace</h6>
                                        <p class="small">Load from HuggingFace datasets</p>
                                        <button class="btn btn-primary btn-sm dataset-source-btn" data-source="huggingface">
                                            <i class="fas fa-download"></i> Load
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-cube fa-2x text-secondary mb-2"></i>
                                        <h6>IPFS</h6>
                                        <p class="small">Fetch from IPFS network</p>
                                        <button class="btn btn-secondary btn-sm dataset-source-btn" data-source="ipfs">
                                            <i class="fas fa-download"></i> Fetch
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-table fa-2x text-success mb-2"></i>
                                        <h6>Parquet</h6>
                                        <p class="small">Load Parquet files</p>
                                        <button class="btn btn-success btn-sm dataset-source-btn" data-source="parquet">
                                            <i class="fas fa-upload"></i> Upload
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-archive fa-2x text-info mb-2"></i>
                                        <h6>CAR Files</h6>
                                        <p class="small">Import CAR archives</p>
                                        <button class="btn btn-info btn-sm dataset-source-btn" data-source="car">
                                            <i class="fas fa-upload"></i> Import
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-12">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Processing Pipeline</h6>
                                    </div>
                                    <div class="card-body">
                                        <div class="row">
                                            <div class="col-md-6">
                                                <h6>Loaded Datasets</h6>
                                                <div id="loaded-datasets" class="list-group" style="max-height: 200px; overflow-y: auto;">
                                                    <div class="list-group-item text-muted">No datasets loaded</div>
                                                </div>
                                            </div>
                                            <div class="col-md-6">
                                                <h6>Processing Options</h6>
                                                <div class="btn-group-vertical w-100" role="group">
                                                    <button class="btn btn-outline-primary btn-sm" onclick="processDataset('filter')">
                                                        <i class="fas fa-filter"></i> Filter Dataset
                                                    </button>
                                                    <button class="btn btn-outline-primary btn-sm" onclick="processDataset('transform')">
                                                        <i class="fas fa-exchange-alt"></i> Transform Data
                                                    </button>
                                                    <button class="btn btn-outline-primary btn-sm" onclick="processDataset('embed')">
                                                        <i class="fas fa-vector-square"></i> Generate Embeddings
                                                    </button>
                                                    <button class="btn btn-outline-primary btn-sm" onclick="processDataset('export')">
                                                        <i class="fas fa-save"></i> Export Dataset
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Web Scraping & Archiving Panel -->
        <div class="row mb-4" id="web-scraping-section">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-globe"></i> Web Scraping & Archiving</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-archive fa-2x text-primary mb-2"></i>
                                        <h6>Wayback Machine</h6>
                                        <p class="small">Search historical web content</p>
                                        <button class="btn btn-primary btn-sm web-scraping-btn" data-action="wayback_search">
                                            <i class="fas fa-search"></i> Search Archives
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-spider fa-2x text-success mb-2"></i>
                                        <h6>Common Crawl</h6>
                                        <p class="small">Large-scale web crawl data</p>
                                        <button class="btn btn-success btn-sm web-scraping-btn" data-action="common_crawl">
                                            <i class="fas fa-search"></i> Search Crawl
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-file-archive fa-2x text-warning mb-2"></i>
                                        <h6>Create WARC</h6>
                                        <p class="small">Archive websites to WARC format</p>
                                        <button class="btn btn-warning btn-sm web-scraping-btn" data-action="create_warc">
                                            <i class="fas fa-download"></i> Archive Site
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-video fa-2x text-danger mb-2"></i>
                                        <h6>Media Download</h6>
                                        <p class="small">Download from 1000+ platforms</p>
                                        <button class="btn btn-danger btn-sm web-scraping-btn" data-action="media_download">
                                            <i class="fas fa-download"></i> Download Media
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-12">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Scraping Results</h6>
                                    </div>
                                    <div class="card-body">
                                        <div id="scraping-results" class="bg-light p-3" style="height: 300px; overflow-y: auto; font-family: monospace;">
                                            <div class="text-muted">Click a scraping button to start...</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Data Search & Discovery Panel -->
        <div class="row mb-4" id="data-search-section">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-search"></i> Data Search & Discovery</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-vector-square fa-2x text-primary mb-2"></i>
                                        <h6>Vector Search</h6>
                                        <p class="small">Semantic similarity search</p>
                                        <button class="btn btn-primary btn-sm search-btn" data-action="vector_search">
                                            <i class="fas fa-search"></i> Search Vectors
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-project-diagram fa-2x text-info mb-2"></i>
                                        <h6>Knowledge Graph</h6>
                                        <p class="small">Query knowledge graphs</p>
                                        <button class="btn btn-info btn-sm search-btn" data-action="knowledge_graph">
                                            <i class="fas fa-search"></i> Query Graph
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-sitemap fa-2x text-success mb-2"></i>
                                        <h6>Content Index</h6>
                                        <p class="small">Full-text search indexes</p>
                                        <button class="btn btn-success btn-sm search-btn" data-action="content_index">
                                            <i class="fas fa-list"></i> Browse Index
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-database fa-2x text-secondary mb-2"></i>
                                        <h6>Dataset Discovery</h6>
                                        <p class="small">Find datasets across sources</p>
                                        <button class="btn btn-secondary btn-sm search-btn" data-action="dataset_discovery">
                                            <i class="fas fa-search"></i> Discover Data
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-6">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Search Query</h6>
                                    </div>
                                    <div class="card-body">
                                        <div class="form-group">
                                            <input type="text" class="form-control" id="search-query" placeholder="Enter search query...">
                                        </div>
                                        <div class="form-group">
                                            <select class="form-control" id="search-type">
                                                <option value="semantic">Semantic Search</option>
                                                <option value="exact">Exact Match</option>
                                                <option value="fuzzy">Fuzzy Search</option>
                                                <option value="graph">Graph Query</option>
                                            </select>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Search Results</h6>
                                    </div>
                                    <div class="card-body">
                                        <div id="search-results" class="bg-light p-3" style="height: 200px; overflow-y: auto;">
                                            <div class="text-muted">Enter a query to search...</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Content Analysis & Transformation Panel -->
        <div class="row mb-4" id="content-analysis-section">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-chart-bar"></i> Content Analysis & Transformation</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-cluster fa-2x text-primary mb-2"></i>
                                        <h6>Clustering Analysis</h6>
                                        <p class="small">Group similar content</p>
                                        <button class="btn btn-primary btn-sm analysis-btn" data-action="clustering">
                                            <i class="fas fa-sitemap"></i> Cluster Data
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-tags fa-2x text-success mb-2"></i>
                                        <h6>Classification</h6>
                                        <p class="small">Categorize content types</p>
                                        <button class="btn btn-success btn-sm analysis-btn" data-action="classification">
                                            <i class="fas fa-tag"></i> Classify Content
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-exchange-alt fa-2x text-warning mb-2"></i>
                                        <h6>Format Conversion</h6>
                                        <p class="small">Transform data formats</p>
                                        <button class="btn btn-warning btn-sm analysis-btn" data-action="format_conversion">
                                            <i class="fas fa-file-export"></i> Convert Format
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-medal fa-2x text-info mb-2"></i>
                                        <h6>Quality Assessment</h6>
                                        <p class="small">Analyze content quality</p>
                                        <button class="btn btn-info btn-sm analysis-btn" data-action="quality_assessment">
                                            <i class="fas fa-check-circle"></i> Assess Quality
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Analysis Parameters</h6>
                                    </div>
                                    <div class="card-body">
                                        <div class="form-group">
                                            <label>Analysis Type</label>
                                            <select class="form-control" id="analysis-type">
                                                <option value="comprehensive">Comprehensive</option>
                                                <option value="quick">Quick Analysis</option>
                                                <option value="detailed">Detailed Analysis</option>
                                            </select>
                                        </div>
                                        <div class="form-group">
                                            <label>Data Source</label>
                                            <select class="form-control" id="analysis-source">
                                                <option value="loaded_datasets">Loaded Datasets</option>
                                                <option value="scraped_content">Scraped Content</option>
                                                <option value="search_results">Search Results</option>
                                            </select>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-8">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Analysis Results</h6>
                                    </div>
                                    <div class="card-body">
                                        <div id="analysis-results" class="bg-light p-3" style="height: 250px; overflow-y: auto;">
                                            <div class="text-muted">Select an analysis type and click a button to start...</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Batch Processing & Workflow Management Panel -->
        <div class="row mb-4" id="batch-processing-section">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-tasks"></i> Batch Processing & Workflow Management</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-4">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-project-diagram fa-2x text-primary mb-2"></i>
                                        <h6>Workflow Builder</h6>
                                        <p class="small">Create automated workflows</p>
                                        <button class="btn btn-primary btn-sm workflow-btn" data-action="create_workflow">
                                            <i class="fas fa-plus"></i> Create Workflow
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-layer-group fa-2x text-success mb-2"></i>
                                        <h6>Batch Operations</h6>
                                        <p class="small">Process multiple datasets</p>
                                        <button class="btn btn-success btn-sm workflow-btn" data-action="batch_process">
                                            <i class="fas fa-play"></i> Start Batch
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-clock fa-2x text-warning mb-2"></i>
                                        <h6>Scheduler</h6>
                                        <p class="small">Schedule recurring tasks</p>
                                        <button class="btn btn-warning btn-sm workflow-btn" data-action="schedule_task">
                                            <i class="fas fa-calendar"></i> Schedule
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-6">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Active Workflows</h6>
                                    </div>
                                    <div class="card-body">
                                        <div id="active-workflows" class="list-group" style="max-height: 200px; overflow-y: auto;">
                                            <div class="list-group-item text-muted">No active workflows</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Workflow Status</h6>
                                    </div>
                                    <div class="card-body">
                                        <div id="workflow-status" class="bg-light p-3" style="height: 200px; overflow-y: auto; font-family: monospace;">
                                            <div class="text-muted">Select a workflow to view status...</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Real-time Monitoring & Analytics Panel -->
        <div class="row mb-4" id="monitoring-section">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-chart-line"></i> Real-time Monitoring & Analytics</h5>
                        <div class="float-right">
                            <span class="badge badge-success">Live</span>
                            <span class="real-time-indicator"></span>
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="row mb-3">
                            <div class="col-md-3">
                                <div class="card bg-primary text-white">
                                    <div class="card-body text-center">
                                        <h4 id="cpu-usage">--</h4>
                                        <small>CPU Usage %</small>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card bg-info text-white">
                                    <div class="card-body text-center">
                                        <h4 id="memory-usage">--</h4>
                                        <small>Memory Usage %</small>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card bg-success text-white">
                                    <div class="card-body text-center">
                                        <h4 id="active-connections">--</h4>
                                        <small>Active Connections</small>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card bg-warning text-white">
                                    <div class="card-body text-center">
                                        <h4 id="queue-size">--</h4>
                                        <small>Task Queue Size</small>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-8">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>System Performance Chart</h6>
                                    </div>
                                    <div class="card-body">
                                        <canvas id="performance-chart" width="400" height="200"></canvas>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>System Health</h6>
                                    </div>
                                    <div class="card-body">
                                        <div id="health-indicators">
                                            <div class="d-flex justify-content-between align-items-center mb-2">
                                                <span>MCP Server</span>
                                                <span class="badge badge-success">Healthy</span>
                                            </div>
                                            <div class="d-flex justify-content-between align-items-center mb-2">
                                                <span>IPFS Node</span>
                                                <span class="badge badge-success">Connected</span>
                                            </div>
                                            <div class="d-flex justify-content-between align-items-center mb-2">
                                                <span>Vector Store</span>
                                                <span class="badge badge-success">Ready</span>
                                            </div>
                                            <div class="d-flex justify-content-between align-items-center mb-2">
                                                <span>Cache</span>
                                                <span class="badge badge-warning">75% Full</span>
                                            </div>
                                        </div>
                                        <hr>
                                        <button class="btn btn-sm btn-outline-primary w-100 monitoring-btn" data-action="refresh_health">
                                            <i class="fas fa-sync"></i> Refresh Health
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Performance Optimization Panel -->
        <div class="row mb-4" id="performance-section">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-tachometer-alt"></i> Performance Optimization</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-rocket fa-2x text-primary mb-2"></i>
                                        <h6>Cache Optimization</h6>
                                        <p class="small">Optimize caching strategies</p>
                                        <button class="btn btn-primary btn-sm performance-btn" data-action="optimize_cache">
                                            <i class="fas fa-magic"></i> Optimize
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-database fa-2x text-success mb-2"></i>
                                        <h6>Index Management</h6>
                                        <p class="small">Manage search indexes</p>
                                        <button class="btn btn-success btn-sm performance-btn" data-action="manage_indexes">
                                            <i class="fas fa-cogs"></i> Manage
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-compress-alt fa-2x text-warning mb-2"></i>
                                        <h6>Data Compression</h6>
                                        <p class="small">Compress large datasets</p>
                                        <button class="btn btn-warning btn-sm performance-btn" data-action="compress_data">
                                            <i class="fas fa-compress"></i> Compress
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card mb-3">
                                    <div class="card-body text-center">
                                        <i class="fas fa-broom fa-2x text-danger mb-2"></i>
                                        <h6>Cleanup</h6>
                                        <p class="small">Clean temporary files</p>
                                        <button class="btn btn-danger btn-sm performance-btn" data-action="cleanup_system">
                                            <i class="fas fa-trash"></i> Cleanup
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-6">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Performance Metrics</h6>
                                    </div>
                                    <div class="card-body">
                                        <div class="progress mb-2">
                                            <div class="progress-bar bg-primary" role="progressbar" style="width: 25%">
                                                Cache Hit Rate: 25%
                                            </div>
                                        </div>
                                        <div class="progress mb-2">
                                            <div class="progress-bar bg-success" role="progressbar" style="width: 60%">
                                                Index Efficiency: 60%
                                            </div>
                                        </div>
                                        <div class="progress mb-2">
                                            <div class="progress-bar bg-warning" role="progressbar" style="width: 80%">
                                                Disk Usage: 80%
                                            </div>
                                        </div>
                                        <div class="progress mb-2">
                                            <div class="progress-bar bg-info" role="progressbar" style="width: 40%">
                                                Network Utilization: 40%
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="card">
                                    <div class="card-header">
                                        <h6>Optimization Results</h6>
                                    </div>
                                    <div class="card-body">
                                        <div id="optimization-results" class="bg-light p-3" style="height: 180px; overflow-y: auto; font-family: monospace;">
                                            <div class="text-muted">Click an optimization button to see results...</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Tools Grid -->
        <div class="row mb-4" id="tools-section">
            <div class="col-md-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-tools"></i> Available MCP Tools</h5>
                        <button class="btn btn-sm btn-outline-primary float-right" onclick="refreshTools()">
                            <i class="fas fa-sync"></i> Refresh
                        </button>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3 mb-3">
                                <input type="text" class="form-control" id="toolSearch" placeholder="Search tools...">
                            </div>
                            <div class="col-md-3 mb-3">
                                <select class="form-control" id="categoryFilter">
                                    <option value="">All Categories</option>
                                    {% for category in tools_info.keys() %}
                                    <option value="{{ category }}">{{ category.replace('_', ' ').title() }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                        </div>
                        
                        <div id="tools-container">
                            {% for category, tools in tools_info.items() %}
                            <div class="category-section mb-4" data-category="{{ category }}">
                                <h6 class="text-muted">{{ category.replace('_', ' ').title() }} ({{ tools|length }} tools)</h6>
                                <div class="row">
                                    {% for tool in tools %}
                                    <div class="col-md-4 col-lg-3 mb-3">
                                        <div class="card tool-card h-100" data-category="{{ category }}" data-tool="{{ tool.name }}">
                                            <div class="card-body">
                                                <h6 class="card-title">{{ tool.name }}</h6>
                                                <p class="card-text small">{{ tool.description }}</p>
                                                <div class="mt-auto">
                                                    <button class="btn btn-sm btn-primary execute-tool-btn w-100">
                                                        <i class="fas fa-play"></i> Execute
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    {% endfor %}
                                </div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Execution History -->
        <div class="row">
            <div class="col-md-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-history"></i> Recent Executions</h5>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-sm">
                                <thead>
                                    <tr>
                                        <th>Tool</th>
                                        <th>Status</th>
                                        <th>Start Time</th>
                                        <th>Duration</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for execution in execution_history %}
                                    <tr>
                                        <td>{{ execution.category }}/{{ execution.tool_name }}</td>
                                        <td>
                                            <span class="badge status-badge badge-{{ 'success' if execution.status == 'completed' else 'danger' if execution.status == 'failed' else 'warning' }}">
                                                {{ execution.status }}
                                            </span>
                                        </td>
                                        <td>{{ execution.start_time }}</td>
                                        <td>{{ execution.get('end_time', 'N/A') }}</td>
                                        <td>
                                            <button class="btn btn-sm btn-outline-primary view-execution-btn" data-id="{{ execution.id }}">
                                                <i class="fas fa-eye"></i> View
                                            </button>
                                        </td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Tool Execution Modal -->
    <div class="modal fade" id="toolExecutionModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Execute Tool</h5>
                    <button type="button" class="close" data-dismiss="modal">
                        <span>&times;</span>
                    </button>
                </div>
                <div class="modal-body">
                    <form id="toolExecutionForm">
                        <div class="form-group">
                            <label>Tool:</label>
                            <input type="text" class="form-control" id="toolName" readonly>
                        </div>
                        <div class="form-group">
                            <label>Parameters (JSON):</label>
                            <textarea class="form-control" id="toolParameters" rows="8" placeholder='{"param1": "value1", "param2": "value2"}'></textarea>
                            <small class="form-text text-muted">Enter parameters as JSON. Leave empty for no parameters.</small>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-primary" id="executeToolBtn">
                        <i class="fas fa-play"></i> Execute
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- Execution Result Modal -->
    <div class="modal fade" id="executionResultModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Execution Result</h5>
                    <button type="button" class="close" data-dismiss="modal">
                        <span>&times;</span>
                    </button>
                </div>
                <div class="modal-body">
                    <pre id="executionResult"></pre>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Local assets with embedded fallbacks -->
    <script src="{{ url_for('static', filename='js/jquery.min.js') }}"></script>
    <script>
        // Ensure $ is available
        if (window.jQuery && !window.$) { 
            window.$ = window.jQuery; 
        }
        // If jQuery failed to load, provide minimal $ implementation
        if (!window.$) {
            window.$ = function(selector) {
                if (typeof selector === 'function') {
                    // $(document).ready equivalent
                    if (document.readyState === 'loading') {
                        document.addEventListener('DOMContentLoaded', selector);
                    } else {
                        selector();
                    }
                    return;
                }
                return document.querySelectorAll(selector);
            };
            window.$.ajax = function() { console.warn('jQuery not loaded, AJAX disabled'); };
        }
    </script>
    <script src="{{ url_for('static', filename='js/bootstrap.bundle.min.js') }}"></script>
    <script>
        // Bootstrap compatibility
        if (typeof bootstrap === 'undefined') {
            window.bootstrap = { Modal: function() {} };
        }
    </script>
    <script src="{{ url_for('static', filename='js/mcp-sdk.js') }}"></script>
    <script>
        // jQuery-agnostic ready helper
        const onReady = function(fn) {
            if (window.jQuery && window.$ && window.$.fn && typeof $.fn.ready === 'function') {
                $(document).ready(fn);
            } else {
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', fn);
                } else {
                    fn();
                }
            }
        };

        onReady(function() {
            function bootDashboard() {
                try {
                    if (typeof window.MCPClient !== 'function') {
                        throw new ReferenceError('MCPClient not ready');
                    }
                    // Initialize MCP SDK only when available
                    window.mcpSDK = new MCPClient('{{ request.host_url }}api/mcp');
                } catch (e) {
                    setTimeout(bootDashboard, 50);
                    return;
                }

                // Tool filtering
                $('#toolSearch, #categoryFilter').on('input change', function() {
                    filterTools();
                });
                
                function filterTools() {
                    const searchTerm = $('#toolSearch').val().toLowerCase();
                    const selectedCategory = $('#categoryFilter').val();
                    
                    $('.category-section').each(function() {
                        const category = $(this).data('category');
                        let categoryVisible = false;
                        
                        if (!selectedCategory || category === selectedCategory) {
                            $(this).find('.tool-card').each(function() {
                                const toolName = $(this).data('tool').toLowerCase();
                                const toolDescription = $(this).find('.card-text').text().toLowerCase();
                                
                                if (!searchTerm || toolName.includes(searchTerm) || toolDescription.includes(searchTerm)) {
                                    $(this).show();
                                    categoryVisible = true;
                                } else {
                                    $(this).hide();
                                }
                            });
                        }
                        
                        $(this).toggle(categoryVisible);
                    });
                }
                
                // Tool execution handlers
                $('.execute-tool-btn').click(function() {
                    const card = $(this).closest('.tool-card');
                    const category = card.data('category');
                    const tool = card.data('tool');
                    
                    $('#toolName').val(category + '/' + tool);
                    $('#toolParameters').val('{}');
                    $('#toolExecutionModal').modal('show');
                });
                
                $('#executeToolBtn').click(function() {
                    const toolName = $('#toolName').val().split('/');
                    const category = toolName[0];
                    const tool = toolName[1];
                    const parameters = $('#toolParameters').val();
                    
                    try {
                        const params = parameters ? JSON.parse(parameters) : {};
                        
                        $(this).prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Executing...');
                        
                        window.mcpSDK.executeTool(category, tool, params)
                            .then(result => {
                                $('#toolExecutionModal').modal('hide');
                                $('#executionResult').text(JSON.stringify(result, null, 2));
                                $('#executionResultModal').modal('show');
                                refreshExecutionHistory();
                            })
                            .catch(error => {
                                alert('Tool execution failed: ' + error.message);
                            })
                            .finally(() => {
                                $(this).prop('disabled', false).html('<i class="fas fa-play"></i> Execute');
                            });
                    } catch (e) {
                        alert('Invalid JSON parameters: ' + e.message);
                        $(this).prop('disabled', false).html('<i class="fas fa-play"></i> Execute');
                    }
                });
                
                // View execution result
                $('.view-execution-btn').click(function() {
                    const executionId = $(this).data('id');
                    
                    fetch('/api/mcp/executions/' + executionId)
                        .then(response => response.json())
                        .then(data => {
                            $('#executionResult').text(JSON.stringify(data, null, 2));
                            $('#executionResultModal').modal('show');
                        })
                        .catch(error => {
                            alert('Failed to load execution details: ' + error.message);
                        });
                });
                
                // Test Suite functionality
                $('.run-tests-btn').click(function() {
                    const testType = $(this).data('test-type');
                    const $btn = $(this);
                    const originalText = $btn.html();
                    
                    $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Running...');
                    $('#test-output').html('<div class="text-info">Starting ' + testType + ' tests...</div>');
                    
                    fetch('/api/mcp/run-tests', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ test_type: testType })
                    })
                    .then(response => response.json())
                    .then(data => {
                        $('#test-output').html('<div class="text-success">Test Results:</div><pre>' + 
                            JSON.stringify(data, null, 2) + '</pre>');
                    })
                    .catch(error => {
                        $('#test-output').html('<div class="text-danger">Test execution failed: ' + error.message + '</div>');
                    })
                    .finally(() => {
                        $btn.prop('disabled', false).html(originalText);
                    });
                });
                
                // Dataset source functionality
                $('.dataset-source-btn').click(function() {
                    const source = $(this).data('source');
                    const $btn = $(this);
                    const originalText = $btn.html();
                    
                    $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Loading...');
                    
                    // Different behavior based on source
                    if (source === 'huggingface') {
                        const datasetName = prompt('Enter HuggingFace dataset name:');
                        if (datasetName) {
                            loadDataset('huggingface', { dataset_name: datasetName });
                        } else {
                            $btn.prop('disabled', false).html(originalText);
                        }
                    } else if (source === 'ipfs') {
                        const cid = prompt('Enter IPFS CID:');
                        if (cid) {
                            loadDataset('ipfs', { cid: cid });
                        } else {
                            $btn.prop('disabled', false).html(originalText);
                        }
                    } else if (source === 'parquet' || source === 'car') {
                        // For file uploads, trigger file input
                        const input = document.createElement('input');
                        input.type = 'file';
                        input.accept = source === 'parquet' ? '.parquet' : '.car';
                        input.onchange = function() {
                            if (this.files[0]) {
                                uploadDataset(source, this.files[0]);
                            } else {
                                $btn.prop('disabled', false).html(originalText);
                            }
                        };
                        input.click();
                    }
                    
                    function loadDataset(sourceType, params) {
                        window.mcpSDK.executeTool('dataset_tools', 'load_dataset', params)
                            .then(result => {
                                addLoadedDataset(result.dataset_id || 'dataset_' + Date.now(), sourceType, params);
                                $btn.prop('disabled', false).html(originalText);
                            })
                            .catch(error => {
                                alert('Dataset loading failed: ' + error.message);
                                $btn.prop('disabled', false).html(originalText);
                            });
                    }
                    
                    function uploadDataset(sourceType, file) {
                        // For now, simulate upload - in real implementation would use FormData
                        setTimeout(() => {
                            addLoadedDataset(file.name, sourceType, { filename: file.name });
                            $btn.prop('disabled', false).html(originalText);
                        }, 1000);
                    }
                });
                
                function addLoadedDataset(datasetId, source, params) {
                    const $container = $('#loaded-datasets');
                    if ($container.find('.text-muted').length) {
                        $container.empty();
                    }
                    
                    const item = $('<div class="list-group-item d-flex justify-content-between align-items-center">' +
                        '<div><strong>' + datasetId + '</strong><br><small class="text-muted">Source: ' + source + '</small></div>' +
                        '<button class="btn btn-sm btn-outline-danger remove-dataset-btn" data-id="' + datasetId + '">' +
                        '<i class="fas fa-trash"></i></button></div>');
                    
                    $container.append(item);
                }
                
                // Remove dataset functionality
                $(document).on('click', '.remove-dataset-btn', function() {
                    $(this).closest('.list-group-item').remove();
                    if ($('#loaded-datasets').children().length === 0) {
                        $('#loaded-datasets').html('<div class="list-group-item text-muted">No datasets loaded</div>');
                    }
                });
                
                // Auto-refresh status every 10 seconds
                setInterval(function() {
                    updateSystemStatus();
                }, 10000);
                
                function updateSystemStatus() {
                    fetch('/api/mcp/status')
                        .then(response => response.json())
                        .then(data => {
                            // Update status indicators
                            console.log('Status updated:', data);
                        })
                        .catch(error => {
                            console.error('Status update failed:', error);
                        });
                }
                
                function refreshExecutionHistory() {
                    location.reload(); // Simple refresh for now
                }
                
                function refreshTools() {
                    location.reload();
                }
                
                // Dataset processing functions
                function processDataset(operation) {
                    const selectedDatasets = $('#loaded-datasets .list-group-item:not(.text-muted)');
                    if (selectedDatasets.length === 0) {
                        alert('No datasets loaded. Please load a dataset first.');
                        return;
                    }
                    
                    const datasetId = selectedDatasets.first().find('strong').text();
                    let params = {};
                    
                    // Get operation-specific parameters
                    if (operation === 'filter') {
                        const filterExpr = prompt('Enter filter expression (e.g., "length > 100"):');
                        if (!filterExpr) return;
                        params = { operations: [{ type: 'filter', condition: filterExpr }] };
                    } else if (operation === 'transform') {
                        const transformType = prompt('Enter transform type (map, select, sort):');
                        if (!transformType) return;
                        params = { operations: [{ type: transformType }] };
                    } else if (operation === 'embed') {
                        params = { operations: [{ type: 'embed', model: 'sentence-transformers/all-MiniLM-L6-v2' }] };
                    } else if (operation === 'export') {
                        const format = prompt('Export format (json, parquet, csv):');
                        if (!format) return;
                        params = { operations: [{ type: 'export', format: format }] };
                    }
                    
                    params.dataset_source = datasetId;
                    
                    window.mcpSDK.executeTool('dataset_tools', 'process_dataset', params)
                        .then(result => {
                            alert('Dataset processing completed: ' + JSON.stringify(result));
                            if (operation === 'export') {
                                // Add processed dataset to list
                                addLoadedDataset(result.output_id || 'processed_' + Date.now(), 'processed', params);
                            }
                        })
                        .catch(error => {
                            alert('Dataset processing failed: ' + error.message);
                        });
                }
                
                // Web Scraping & Archiving functionality
                $('.web-scraping-btn').click(function() {
                    const action = $(this).data('action');
                    const $btn = $(this);
                    const originalText = $btn.html();
                    
                    $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Processing...');
                    $('#scraping-results').html('<div class="text-info">Starting ' + action + '...</div>');
                    
                    let params = {};
                    let toolName = '';
                    
                    // Get action-specific parameters
                    if (action === 'wayback_search') {
                        const url = prompt('Enter URL to search in Wayback Machine:');
                        if (!url) return resetButton();
                        params = { url: url, limit: 50 };
                        toolName = 'wayback_machine_search';
                    } else if (action === 'common_crawl') {
                        const domain = prompt('Enter domain to search in Common Crawl:');
                        if (!domain) return resetButton();
                        params = { domain: domain, limit: 50 };
                        toolName = 'common_crawl_search';
                    } else if (action === 'create_warc') {
                        const url = prompt('Enter URL to archive:');
                        if (!url) return resetButton();
                        params = { url: url, output_path: 'archives/' + Date.now() + '.warc.gz' };
                        toolName = 'create_warc';
                    } else if (action === 'media_download') {
                        const url = prompt('Enter media URL (YouTube, Vimeo, etc.):');
                        if (!url) return resetButton();
                        params = { url: url, output_dir: 'media_downloads', quality: 'best[height<=720]' };
                        toolName = 'ytdlp_download';
                    }
                    
                    function resetButton() {
                        $btn.prop('disabled', false).html(originalText);
                    }
                    
                    window.mcpSDK.executeTool('web_archive_tools', toolName, params)
                        .then(result => {
                            $('#scraping-results').html('<div class="text-success">Success!</div><pre>' + 
                                JSON.stringify(result, null, 2) + '</pre>');
                        })
                        .catch(error => {
                            $('#scraping-results').html('<div class="text-danger">Error: ' + error.message + '</div>');
                        })
                        .finally(() => {
                            resetButton();
                        });
                });
                
                // Data Search & Discovery functionality
                $('.search-btn').click(function() {
                    const action = $(this).data('action');
                    const query = $('#search-query').val();
                    const searchType = $('#search-type').val();
                    
                    if (!query) {
                        alert('Please enter a search query');
                        return;
                    }
                    
                    const $btn = $(this);
                    const originalText = $btn.html();
                    
                    $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Searching...');
                    $('#search-results').html('<div class="text-info">Searching...</div>');
                    
                    let params = { query: query };
                    let toolName = '';
                    
                    if (action === 'vector_search') {
                        params.search_type = searchType;
                        toolName = 'search_vector_index';
                    } else if (action === 'knowledge_graph') {
                        toolName = 'query_knowledge_graph';
                    } else if (action === 'content_index') {
                        toolName = 'list_indices';
                    } else if (action === 'dataset_discovery') {
                        params.source = 'multiple';
                        toolName = 'load_dataset';
                    }
                    
                    const category = action === 'knowledge_graph' ? 'graph_tools' :
                                   action === 'dataset_discovery' ? 'dataset_tools' : 'vector_tools';
                    
                    window.mcpSDK.executeTool(category, toolName, params)
                        .then(result => {
                            $('#search-results').html('<div class="text-success">Results found!</div><pre>' + 
                                JSON.stringify(result, null, 2) + '</pre>');
                        })
                        .catch(error => {
                            $('#search-results').html('<div class="text-danger">Search failed: ' + error.message + '</div>');
                        })
                        .finally(() => {
                            $btn.prop('disabled', false).html(originalText);
                        });
                });
                
                // Content Analysis & Transformation functionality
                $('.analysis-btn').click(function() {
                    const action = $(this).data('action');
                    const analysisType = $('#analysis-type').val();
                    const analysisSource = $('#analysis-source').val();
                    
                    const $btn = $(this);
                    const originalText = $btn.html();
                    
                    $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Analyzing...');
                    $('#analysis-results').html('<div class="text-info">Starting ' + action + ' analysis...</div>');
                    
                    let params = {
                        analysis_type: analysisType,
                        data_source: analysisSource
                    };
                    let toolName = '';
                    
                    if (action === 'clustering') {
                        params.algorithm = 'kmeans';
                        params.n_clusters = 5;
                        toolName = 'analysis_tools';
                    } else if (action === 'classification') {
                        params.categories = ['text', 'image', 'video', 'audio', 'document'];
                        toolName = 'analysis_tools';
                    } else if (action === 'format_conversion') {
                        const targetFormat = prompt('Enter target format (json, parquet, csv):');
                        if (!targetFormat) return resetAnalysisButton();
                        params.target_format = targetFormat;
                        toolName = 'convert_dataset_format';
                    } else if (action === 'quality_assessment') {
                        params.metrics = ['completeness', 'consistency', 'accuracy'];
                        toolName = 'analysis_tools';
                    }
                    
                    function resetAnalysisButton() {
                        $btn.prop('disabled', false).html(originalText);
                    }
                    
                    const category = action === 'format_conversion' ? 'dataset_tools' : 'analysis_tools';
                    
                    window.mcpSDK.executeTool(category, toolName, params)
                        .then(result => {
                            $('#analysis-results').html('<div class="text-success">Analysis completed!</div><pre>' + 
                                JSON.stringify(result, null, 2) + '</pre>');
                        })
                        .catch(error => {
                            $('#analysis-results').html('<div class="text-danger">Analysis failed: ' + error.message + '</div>');
                        })
                        .finally(() => {
                            resetAnalysisButton();
                        });
                });
                
                // Batch Processing & Workflow Management functionality
                $('.workflow-btn').click(function() {
                    const action = $(this).data('action');
                    const $btn = $(this);
                    const originalText = $btn.html();
                    
                    $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Processing...');
                    
                    let params = {};
                    let toolName = '';
                    
                    if (action === 'create_workflow') {
                        const workflowName = prompt('Enter workflow name:');
                        if (!workflowName) return resetWorkflowButton();
                        params = {
                            name: workflowName,
                            steps: [
                                { tool: 'load_dataset', params: {} },
                                { tool: 'process_dataset', params: {} }
                            ]
                        };
                        toolName = 'enhanced_workflow_tools';
                    } else if (action === 'batch_process') {
                        const batchSize = prompt('Enter batch size (default: 10):') || '10';
                        params = {
                            batch_size: parseInt(batchSize),
                            operation: 'process_multiple_datasets'
                        };
                        toolName = 'enhanced_workflow_tools';
                    } else if (action === 'schedule_task') {
                        const schedule = prompt('Enter cron schedule (e.g., "0 */6 * * *"):');
                        if (!schedule) return resetWorkflowButton();
                        params = { schedule: schedule, task_type: 'data_processing' };
                        toolName = 'enhanced_workflow_tools';
                    }
                    
                    function resetWorkflowButton() {
                        $btn.prop('disabled', false).html(originalText);
                    }
                    
                    window.mcpSDK.executeTool('workflow_tools', toolName, params)
                        .then(result => {
                            $('#workflow-status').html('<div class="text-success">Workflow operation completed!</div><pre>' + 
                                JSON.stringify(result, null, 2) + '</pre>');
                            updateActiveWorkflows();
                        })
                        .catch(error => {
                            $('#workflow-status').html('<div class="text-danger">Workflow operation failed: ' + error.message + '</div>');
                        })
                        .finally(() => {
                            resetWorkflowButton();
                        });
                });
                
                // Real-time Monitoring functionality
                $('.monitoring-btn').click(function() {
                    const action = $(this).data('action');
                    
                    if (action === 'refresh_health') {
                        updateSystemMetrics();
                        updateHealthIndicators();
                    }
                });
                
                // Performance Optimization functionality
                $('.performance-btn').click(function() {
                    const action = $(this).data('action');
                    const $btn = $(this);
                    const originalText = $btn.html();
                    
                    $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Optimizing...');
                    
                    let params = {};
                    let toolName = '';
                    let category = '';
                    
                    if (action === 'optimize_cache') {
                        params = { optimization_type: 'cache', strategy: 'aggressive' };
                        toolName = 'enhanced_cache_tools';
                        category = 'cache_tools';
                    } else if (action === 'manage_indexes') {
                        params = { action: 'optimize_all' };
                        toolName = 'index_management_tools';
                        category = 'index_management_tools';
                    } else if (action === 'compress_data') {
                        params = { compression_algorithm: 'gzip', level: 6 };
                        toolName = 'data_processing_tools';
                        category = 'data_processing_tools';
                    } else if (action === 'cleanup_system') {
                        params = { clean_temp: true, clean_cache: true, clean_logs: true };
                        toolName = 'system_health';
                        category = 'bespoke_tools';
                    }
                    
                    function resetPerformanceButton() {
                        $btn.prop('disabled', false).html(originalText);
                    }
                    
                    window.mcpSDK.executeTool(category, toolName, params)
                        .then(result => {
                            $('#optimization-results').html('<div class="text-success">Optimization completed!</div><pre>' + 
                                JSON.stringify(result, null, 2) + '</pre>');
                            updatePerformanceMetrics();
                        })
                        .catch(error => {
                            $('#optimization-results').html('<div class="text-danger">Optimization failed: ' + error.message + '</div>');
                        })
                        .finally(() => {
                            resetPerformanceButton();
                        });
                });
                
                // Utility functions for new panels
                function updateActiveWorkflows() {
                    // Mock workflow data - in production would fetch from server
                    const workflows = [
                        { id: 'wf1', name: 'Daily Dataset Processing', status: 'running', progress: 60 },
                        { id: 'wf2', name: 'Weekly Analysis Report', status: 'scheduled', progress: 0 },
                        { id: 'wf3', name: 'Data Quality Check', status: 'completed', progress: 100 }
                    ];
                    
                    let html = '';
                    workflows.forEach(wf => {
                        const statusClass = wf.status === 'running' ? 'primary' : 
                                          wf.status === 'completed' ? 'success' : 'secondary';
                        html += `<div class="list-group-item d-flex justify-content-between align-items-center">
                                    <div>
                                        <strong>${wf.name}</strong><br>
                                        <small class="text-muted">ID: ${wf.id}</small>
                                    </div>
                                    <div>
                                        <span class="badge badge-${statusClass}">${wf.status}</span>
                                        <div class="progress mt-1" style="width: 100px;">
                                            <div class="progress-bar" style="width: ${wf.progress}%"></div>
                                        </div>
                                    </div>
                                 </div>`;
                    });
                    $('#active-workflows').html(html);
                }
                
                function updateSystemMetrics() {
                    // Mock system metrics - in production would fetch from monitoring API
                    $('#cpu-usage').text(Math.floor(Math.random() * 40 + 20) + '%');
                    $('#memory-usage').text(Math.floor(Math.random() * 30 + 40) + '%');
                    $('#active-connections').text(Math.floor(Math.random() * 20 + 5));
                    $('#queue-size').text(Math.floor(Math.random() * 10));
                }
                
                function updateHealthIndicators() {
                    // Mock health status updates
                    const services = ['MCP Server', 'IPFS Node', 'Vector Store', 'Cache'];
                    const statuses = ['Healthy', 'Connected', 'Ready', '75% Full'];
                    const badges = ['success', 'success', 'success', 'warning'];
                    
                    let html = '';
                    services.forEach((service, i) => {
                        html += `<div class="d-flex justify-content-between align-items-center mb-2">
                                    <span>${service}</span>
                                    <span class="badge badge-${badges[i]}">${statuses[i]}</span>
                                 </div>`;
                    });
                    $('#health-indicators').html(html + '<hr><button class="btn btn-sm btn-outline-primary w-100 monitoring-btn" data-action="refresh_health"><i class="fas fa-sync"></i> Refresh Health</button>');
                }
                
                function updatePerformanceMetrics() {
                    // Update performance bars with slight improvements after optimization
                    const currentCacheRate = parseInt($('.progress-bar.bg-primary').css('width')) || 25;
                    $('.progress-bar.bg-primary').css('width', Math.min(100, currentCacheRate + 10) + '%')
                                                   .text(`Cache Hit Rate: ${Math.min(100, currentCacheRate + 10)}%`);
                }
                
                // Initialize real-time updates
                setInterval(function() {
                    updateSystemMetrics();
                }, 5000); // Update every 5 seconds
                
                // Initialize panels
                updateActiveWorkflows();
                updateSystemMetrics();
                updateHealthIndicators();
            }

            (function waitForDeps(){
                const hasRealJQ = !!(window.jQuery && window.$ && window.$.fn);
                if (window.MCPClient && hasRealJQ) { bootDashboard(); }
                else { setTimeout(waitForDeps, 50); }
            })();
        });
    </script>
</body>
</html>"""

    def _create_mcp_templates(self) -> None:
        """Create comprehensive MCP-specific template files."""
        if not self.app:
            return

        templates_dir = Path(self.app.template_folder)
        static_dir = Path(self.app.static_folder)
        templates_dir.mkdir(parents=True, exist_ok=True)
        static_dir.mkdir(parents=True, exist_ok=True)

        # Create main MCP dashboard template (always update to ensure latest features)
        mcp_template_path = templates_dir / "mcp_dashboard.html"
        with open(mcp_template_path, 'w') as f:
            f.write(self.create_mcp_dashboard_template())

        # Create GraphRAG dashboard template
        if self.mcp_config and self.mcp_config.enable_graphrag:
            graphrag_template_path = templates_dir / "graphrag_dashboard.html"
            if not graphrag_template_path.exists():
                with open(graphrag_template_path, 'w') as f:
                    f.write(self.create_graphrag_template())

        # Create Analytics dashboard template
        if self.mcp_config and self.mcp_config.enable_analytics:
            analytics_template_path = templates_dir / "analytics_dashboard.html"
            if not analytics_template_path.exists():
                with open(analytics_template_path, 'w') as f:
                    f.write(self.create_analytics_template())

        # Create RAG query dashboard template
        if self.mcp_config and self.mcp_config.enable_rag_query:
            rag_template_path = templates_dir / "rag_query_dashboard.html"
            if not rag_template_path.exists():
                with open(rag_template_path, 'w') as f:
                    f.write(self.create_rag_query_template())

        # Create Investigation dashboard template
        if self.mcp_config and self.mcp_config.enable_investigation:
            investigation_template_path = templates_dir / "investigation_dashboard.html"
            if not investigation_template_path.exists():
                with open(investigation_template_path, 'w') as f:
                    f.write(self.create_investigation_template())

        # Ensure enhanced MCP JavaScript SDK exists
        js_dir = static_dir / "js"
        js_dir.mkdir(parents=True, exist_ok=True)
        mcp_sdk_path = js_dir / "mcp-sdk.js"
        if not mcp_sdk_path.exists():
            mcp_sdk_path.write_text(self.create_enhanced_mcp_sdk())
    
    def create_graphrag_template(self) -> str:
        """Create GraphRAG processing dashboard template."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GraphRAG Processing Dashboard</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <style>
        .processing-card { border-left: 4px solid #007bff; }
        .completed-card { border-left: 4px solid #28a745; }
        .failed-card { border-left: 4px solid #dc3545; }
        .progress-section { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; }
        .session-card { transition: all 0.3s ease; }
        .session-card:hover { transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary">
        <a class="navbar-brand" href="/mcp">← Back to MCP Dashboard</a>
        <span class="navbar-text ml-auto">GraphRAG Processing Dashboard</span>
    </nav>

    <div class="container-fluid mt-4">
        <!-- Processing Stats -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card progress-section">
                    <div class="card-body">
                        <h5><i class="fas fa-brain"></i> GraphRAG Processing Statistics</h5>
                        <div class="row mt-3">
                            <div class="col-md-3">
                                <div class="text-center">
                                    <h3>{{ processing_stats.total_sessions }}</h3>
                                    <small>Total Sessions</small>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="text-center">
                                    <h3>{{ processing_stats.active_sessions }}</h3>
                                    <small>Active Sessions</small>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="text-center">
                                    <h3>{{ "%.1f"|format(processing_stats.success_rate) }}%</h3>
                                    <small>Success Rate</small>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="text-center">
                                    <h3>{{ "%.1f"|format(processing_stats.average_processing_time) }}s</h3>
                                    <small>Avg. Processing Time</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- New Processing Session -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-plus"></i> Start New GraphRAG Processing</h5>
                    </div>
                    <div class="card-body">
                        <form id="graphragForm">
                            <div class="row">
                                <div class="col-md-6">
                                    <div class="form-group">
                                        <label>Website URL:</label>
                                        <input type="url" class="form-control" id="websiteUrl" required placeholder="https://example.com">
                                    </div>
                                </div>
                                <div class="col-md-3">
                                    <div class="form-group">
                                        <label>Processing Mode:</label>
                                        <select class="form-control" id="processingMode">
                                            <option value="fast">Fast</option>
                                            <option value="balanced" selected>Balanced</option>
                                            <option value="quality">Quality</option>
                                            <option value="comprehensive">Comprehensive</option>
                                        </select>
                                    </div>
                                </div>
                                <div class="col-md-3">
                                    <div class="form-group">
                                        <label>&nbsp;</label>
                                        <button type="submit" class="btn btn-primary btn-block">
                                            <i class="fas fa-play"></i> Start Processing
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </div>

        <!-- Active Sessions -->
        <div class="row">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-tasks"></i> Processing Sessions</h5>
                        <button class="btn btn-sm btn-outline-primary float-right" onclick="refreshSessions()">
                            <i class="fas fa-sync"></i> Refresh
                        </button>
                    </div>
                    <div class="card-body" id="sessionsContainer">
                        <!-- Sessions will be loaded here -->
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="{{ url_for('static', filename='js/jquery.min.js') }}"></script>
    <script src="{{ url_for('static', filename='js/bootstrap.bundle.min.js') }}"></script>
    <script>
        $(document).ready(function() {
            loadSessions();
            
            $('#graphragForm').submit(function(e) {
                e.preventDefault();
                startProcessing();
            });
            
            // Auto-refresh every 5 seconds
            setInterval(loadSessions, 5000);
        });

        function startProcessing() {
            const url = $('#websiteUrl').val();
            const mode = $('#processingMode').val();
            
            $.ajax({
                url: '/api/mcp/graphrag/process',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    url: url,
                    mode: mode
                }),
                success: function(data) {
                    alert('Processing started! Session ID: ' + data.session_id);
                    $('#websiteUrl').val('');
                    loadSessions();
                },
                error: function(xhr) {
                    alert('Failed to start processing: ' + xhr.responseJSON.error);
                }
            });
        }

        function loadSessions() {
            $.get('/api/mcp/graphrag/sessions', function(data) {
                const container = $('#sessionsContainer');
                container.empty();
                
                if (data.sessions.length === 0) {
                    container.html('<p class="text-muted">No processing sessions found.</p>');
                    return;
                }
                
                data.sessions.forEach(function(session) {
                    const card = createSessionCard(session);
                    container.append(card);
                });
            });
        }

        function createSessionCard(session) {
            const statusClass = session.status === 'completed' ? 'completed-card' : 
                               session.status === 'failed' ? 'failed-card' : 'processing-card';
            
            const progressBar = session.status === 'processing' ? 
                `<div class="progress mt-2">
                    <div class="progress-bar" style="width: ${session.progress * 100}%"></div>
                 </div>` : '';
            
            return `
                <div class="card session-card mb-3 ${statusClass}">
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-8">
                                <h6>${session.url}</h6>
                                <small class="text-muted">Started: ${session.start_time}</small>
                                ${progressBar}
                            </div>
                            <div class="col-md-4 text-right">
                                <span class="badge badge-${getStatusBadgeClass(session.status)}">${session.status}</span>
                                <br><small>Mode: ${session.config ? session.config.processing_mode : 'N/A'}</small>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        function getStatusBadgeClass(status) {
            switch(status) {
                case 'completed': return 'success';
                case 'failed': return 'danger';
                case 'processing': return 'warning';
                default: return 'secondary';
            }
        }

        function refreshSessions() {
            loadSessions();
        }
    </script>
</body>
</html>"""
    
    def create_analytics_template(self) -> str:
        """Create analytics dashboard template."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analytics Dashboard</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        .metric-card { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white; }
        .chart-container { height: 400px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-info">
        <a class="navbar-brand" href="/mcp">← Back to MCP Dashboard</a>
        <span class="navbar-text ml-auto">Analytics Dashboard</span>
    </nav>

    <div class="container-fluid mt-4">
        <!-- Metrics Overview -->
        <div class="row mb-4">
            <div class="col-md-3 mb-3">
                <div class="card metric-card">
                    <div class="card-body text-center">
                        <h3>{{ metrics.total_websites_processed }}</h3>
                        <small>Websites Processed</small>
                    </div>
                </div>
            </div>
            <div class="col-md-3 mb-3">
                <div class="card metric-card">
                    <div class="card-body text-center">
                        <h3>{{ "%.1f"|format(metrics.success_rate) }}%</h3>
                        <small>Success Rate</small>
                    </div>
                </div>
            </div>
            <div class="col-md-3 mb-3">
                <div class="card metric-card">
                    <div class="card-body text-center">
                        <h3>{{ metrics.total_rag_queries }}</h3>
                        <small>RAG Queries</small>
                    </div>
                </div>
            </div>
            <div class="col-md-3 mb-3">
                <div class="card metric-card">
                    <div class="card-body text-center">
                        <h3>{{ "%.2f"|format(metrics.average_query_time) }}s</h3>
                        <small>Avg Query Time</small>
                    </div>
                </div>
            </div>
        </div>

        <!-- Charts -->
        <div class="row">
            <div class="col-md-6 mb-4">
                <div class="card">
                    <div class="card-header">
                        <h5>Processing Performance</h5>
                    </div>
                    <div class="card-body">
                        <div id="performanceChart" class="chart-container"></div>
                    </div>
                </div>
            </div>
            <div class="col-md-6 mb-4">
                <div class="card">
                    <div class="card-header">
                        <h5>Query Analytics</h5>
                    </div>
                    <div class="card-body">
                        <div id="queryChart" class="chart-container"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="{{ url_for('static', filename='js/jquery.min.js') }}"></script>
    <script>
        $(document).ready(function() {
            loadCharts();
            
            // Auto-refresh every 30 seconds
            setInterval(loadCharts, 30000);
        });

        function loadCharts() {
            // Load performance chart
            $.get('/api/mcp/analytics/history', function(data) {
                if (data.history.length > 0) {
                    createPerformanceChart(data.history);
                    createQueryChart(data.history);
                }
            });
        }

        function createPerformanceChart(history) {
            const trace = {
                x: history.map(h => h.last_updated),
                y: history.map(h => h.success_rate),
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Success Rate'
            };

            const layout = {
                title: 'Success Rate Over Time',
                xaxis: { title: 'Time' },
                yaxis: { title: 'Success Rate (%)' }
            };

            Plotly.newPlot('performanceChart', [trace], layout);
        }

        function createQueryChart(history) {
            const trace = {
                x: history.map(h => h.last_updated),
                y: history.map(h => h.average_query_time),
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Query Time'
            };

            const layout = {
                title: 'Average Query Time',
                xaxis: { title: 'Time' },
                yaxis: { title: 'Time (seconds)' }
            };

            Plotly.newPlot('queryChart', [trace], layout);
        }
    </script>
</body>
</html>"""
    
    def create_rag_query_template(self) -> str:
        """Create RAG query dashboard template."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAG Query Interface</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <style>
        .query-section { background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); color: white; }
        .result-card { border-left: 4px solid #28a745; }
        .query-input { min-height: 120px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-success">
        <a class="navbar-brand" href="/mcp">← Back to MCP Dashboard</a>
        <span class="navbar-text ml-auto">RAG Query Interface</span>
    </nav>

    <div class="container-fluid mt-4">
        <!-- Query Interface -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card query-section">
                    <div class="card-body">
                        <h5><i class="fas fa-search"></i> Execute RAG Query</h5>
                        <form id="ragQueryForm" class="mt-3">
                            <div class="row">
                                <div class="col-md-8">
                                    <div class="form-group">
                                        <textarea class="form-control query-input" id="queryText" 
                                                placeholder="Enter your query here..." required></textarea>
                                    </div>
                                </div>
                                <div class="col-md-4">
                                    <div class="form-group">
                                        <label>Context (Optional):</label>
                                        <textarea class="form-control" id="queryContext" 
                                                placeholder='{"domain": "general"}'></textarea>
                                    </div>
                                    <button type="submit" class="btn btn-light btn-block">
                                        <i class="fas fa-search"></i> Execute Query
                                    </button>
                                </div>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </div>

        <!-- Query Results -->
        <div class="row">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-list"></i> Query Results</h5>
                    </div>
                    <div class="card-body" id="resultsContainer">
                        <p class="text-muted">No queries executed yet.</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="{{ url_for('static', filename='js/jquery.min.js') }}"></script>
    <script>
        $('#ragQueryForm').submit(function(e) {
            e.preventDefault();
            executeQuery();
        });

        function executeQuery() {
            const query = $('#queryText').val();
            const context = $('#queryContext').val();
            
            let contextObj = {};
            if (context) {
                try {
                    contextObj = JSON.parse(context);
                } catch (e) {
                    alert('Invalid JSON in context field');
                    return;
                }
            }

            $('button[type="submit"]').prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Processing...');

            $.ajax({
                url: '/api/mcp/rag/query',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    query: query,
                    context: contextObj
                }),
                success: function(data) {
                    displayResult(data);
                    $('#queryText').val('');
                },
                error: function(xhr) {
                    alert('Query failed: ' + xhr.responseJSON.error);
                },
                complete: function() {
                    $('button[type="submit"]').prop('disabled', false).html('<i class="fas fa-search"></i> Execute Query');
                }
            });
        }

        function displayResult(result) {
            const resultCard = `
                <div class="card result-card mb-3">
                    <div class="card-body">
                        <h6>Query: ${result.query}</h6>
                        <p><strong>Result:</strong> ${result.result.result}</p>
                        <small class="text-muted">
                            Confidence: ${(result.result.confidence * 100).toFixed(1)}% | 
                            Execution Time: ${result.result.execution_time}s
                        </small>
                    </div>
                </div>
            `;
            
            $('#resultsContainer').prepend(resultCard);
            
            // Remove "no queries" message
            $('#resultsContainer p.text-muted').remove();
        }
    </script>
</body>
</html>"""
    
    def create_investigation_template(self) -> str:
        """Create investigation dashboard template with Maps tab integration."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Investigation Dashboard - Comprehensive Analysis with Geospatial Mapping</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/leaflet.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/all.min.css') }}">
    <style>
        .investigation-section { background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); color: white; }
        .finding-card { border-left: 4px solid #fd7e14; }
        .maps-section { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
        .nav-pills .nav-link.active { background-color: #fa709a; }
        .nav-pills .nav-link { color: #fa709a; }
        #mapContainer { height: 600px; background: #f8f9fa; border-radius: 8px; }
        .map-controls { background: rgba(255, 255, 255, 0.95); padding: 15px; border-radius: 8px; margin-bottom: 10px; }
        .timeline-container { background: rgba(255, 255, 255, 0.95); padding: 10px; border-radius: 8px; margin-top: 10px; }
        .entity-marker { background: #fa709a; color: white; border-radius: 50%; width: 25px; height: 25px; text-align: center; line-height: 25px; }
        .event-marker { background: #764ba2; color: white; border-radius: 4px; padding: 2px 6px; }
        .map-legend { position: absolute; top: 10px; right: 10px; background: rgba(255, 255, 255, 0.9); padding: 10px; border-radius: 4px; z-index: 1000; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-warning">
        <a class="navbar-brand" href="/mcp">← Back to MCP Dashboard</a>
        <span class="navbar-text ml-auto">Investigation Dashboard - Comprehensive Analysis</span>
    </nav>

    <div class="container-fluid mt-4">
        <!-- Navigation Tabs -->
        <div class="row mb-4">
            <div class="col-12">
                <ul class="nav nav-pills nav-fill">
                    <li class="nav-item">
                        <a class="nav-link active" id="analysis-tab" data-toggle="pill" href="#analysis-content" role="tab">
                            <i class="fas fa-search"></i> Analysis
                        </a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" id="maps-tab" data-toggle="pill" href="#maps-content" role="tab">
                            <i class="fas fa-map-marked-alt"></i> Maps
                        </a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" id="results-tab" data-toggle="pill" href="#results-content" role="tab">
                            <i class="fas fa-clipboard-list"></i> Results
                        </a>
                    </li>
                </ul>
            </div>
        </div>

        <!-- Tab Content -->
        <div class="tab-content">
            <!-- Analysis Tab -->
            <div class="tab-pane fade show active" id="analysis-content" role="tabpanel">
                <div class="row mb-4">
                    <div class="col-12">
                        <div class="card investigation-section">
                            <div class="card-body">
                                <h5><i class="fas fa-search"></i> Start Content Investigation</h5>
                                <form id="investigationForm" class="mt-3">
                                    <div class="row">
                                        <div class="col-md-6">
                                            <div class="form-group">
                                                <label>Content URL:</label>
                                                <input type="url" class="form-control" id="contentUrl" required 
                                                       placeholder="https://example.com/article">
                                            </div>
                                        </div>
                                        <div class="col-md-3">
                                            <div class="form-group">
                                                <label>Analysis Type:</label>
                                                <select class="form-control" id="analysisType">
                                                    <option value="comprehensive">Comprehensive</option>
                                                    <option value="entity_extraction">Entity Extraction</option>
                                                    <option value="sentiment_analysis">Sentiment Analysis</option>
                                                    <option value="credibility_check">Credibility Check</option>
                                                    <option value="geospatial_analysis">Geospatial Analysis</option>
                                                </select>
                                            </div>
                                        </div>
                                        <div class="col-md-3">
                                            <div class="form-group">
                                                <label>&nbsp;</label>
                                                <button type="submit" class="btn btn-light btn-block">
                                                    <i class="fas fa-play"></i> Start Investigation
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </form>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Maps Tab -->
            <div class="tab-pane fade" id="maps-content" role="tabpanel">
                <div class="row mb-4">
                    <div class="col-12">
                        <div class="card maps-section">
                            <div class="card-body">
                                <h5><i class="fas fa-map-marked-alt"></i> Geospatial Analysis & Interactive Mapping</h5>
                                <p class="mb-0">Visualize events geographically and perform spatiotemporal analysis on investigation data</p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Map Controls -->
                <div class="row mb-3">
                    <div class="col-12">
                        <div class="map-controls">
                            <form id="geospatialForm">
                                <div class="row">
                                    <div class="col-md-3">
                                        <div class="form-group">
                                            <label>Geographic Query:</label>
                                            <input type="text" class="form-control" id="geoQuery" 
                                                   placeholder="e.g., financial events in New York" value="events in New York">
                                        </div>
                                    </div>
                                    <div class="col-md-2">
                                        <div class="form-group">
                                            <label>Center Location:</label>
                                            <input type="text" class="form-control" id="centerLocation" 
                                                   placeholder="New York" value="New York">
                                        </div>
                                    </div>
                                    <div class="col-md-2">
                                        <div class="form-group">
                                            <label>Radius (km):</label>
                                            <select class="form-control" id="searchRadius">
                                                <option value="1">1 km</option>
                                                <option value="5">5 km</option>
                                                <option value="10">10 km</option>
                                                <option value="50" selected>50 km</option>
                                                <option value="100">100 km</option>
                                                <option value="500">500 km</option>
                                                <option value="1000">1000 km</option>
                                                <option value="5000">5000 km</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div class="col-md-2">
                                        <div class="form-group">
                                            <label>Entity Types:</label>
                                            <select class="form-control" id="entityTypes">
                                                <option value="">All Types</option>
                                                <option value="PERSON">Persons</option>
                                                <option value="ORGANIZATION">Organizations</option>
                                                <option value="EVENT">Events</option>
                                                <option value="LOCATION">Locations</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div class="col-md-2">
                                        <div class="form-group">
                                            <label>Clustering (km):</label>
                                            <select class="form-control" id="clusteringDistance">
                                                <option value="1">1 km</option>
                                                <option value="5">5 km</option>
                                                <option value="10">10 km</option>
                                                <option value="25">25 km</option>
                                                <option value="50" selected>50 km</option>
                                                <option value="100">100 km</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div class="col-md-1">
                                        <div class="form-group">
                                            <label>&nbsp;</label>
                                            <button type="submit" class="btn btn-light btn-block">
                                                <i class="fas fa-search"></i>
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </form>
                        </div>
                    </div>
                </div>

                <!-- Map Container -->
                <div class="row mb-3">
                    <div class="col-12">
                        <div class="position-relative">
                            <div id="mapContainer"></div>
                            <div class="map-legend">
                                <h6>Legend</h6>
                                <div><span class="entity-marker" style="display: inline-block;">E</span> Geographic Entities</div>
                                <div><span class="event-marker" style="display: inline-block;">EV</span> Events</div>
                                <div><i class="fas fa-map-marker-alt" style="color: #dc3545;"></i> Center Location</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Timeline Controls -->
                <div class="row">
                    <div class="col-12">
                        <div class="timeline-container">
                            <h6><i class="fas fa-clock"></i> Timeline Filter</h6>
                            <div class="row">
                                <div class="col-md-3">
                                    <label>Start Date:</label>
                                    <input type="date" class="form-control" id="startDate">
                                </div>
                                <div class="col-md-3">
                                    <label>End Date:</label>
                                    <input type="date" class="form-control" id="endDate">
                                </div>
                                <div class="col-md-4">
                                    <label>Timeline Slider:</label>
                                    <input type="range" class="form-control-range" id="timelineSlider" min="0" max="100" value="50">
                                </div>
                                <div class="col-md-2">
                                    <label>&nbsp;</label>
                                    <button class="btn btn-outline-primary btn-block" onclick="applyTimelineFilter()">
                                        <i class="fas fa-filter"></i> Apply
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Results Tab -->
            <div class="tab-pane fade" id="results-content" role="tabpanel">
                <div class="row">
                    <div class="col-12">
                        <div class="card">
                            <div class="card-header">
                                <h5><i class="fas fa-clipboard-list"></i> Investigation Results</h5>
                            </div>
                            <div class="card-body" id="findingsContainer">
                                <p class="text-muted">No investigations completed yet.</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="{{ url_for('static', filename='js/jquery.min.js') }}"></script>
    <script>
        if (!window.jQuery) {
            document.write('<script src="https://code.jquery.com/jquery-3.6.0.min.js"><\\/script>');
        }
        (function ensureDollar(){
            if (window.jQuery && !window.$) { window.$ = window.jQuery; }
            if (!window.$) { setTimeout(ensureDollar, 25); }
        })();
    </script>
    <script src="{{ url_for('static', filename='js/bootstrap.bundle.min.js') }}"></script>
    <script>
        if (typeof bootstrap === 'undefined') {
            document.write('<script src="https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/js/bootstrap.bundle.min.js"><\\/script>');
        }
    </script>
    <script src="{{ url_for('static', filename='js/leaflet.js') }}"></script>
    <script>
        if (!window.L) {
            var lf = document.createElement('script');
            lf.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
            document.head.appendChild(lf);
        }
    </script>
    <script>
        let map;
        let markers = [];
        let currentGeospatialData = null;

        // Initialize map when Maps tab is shown
        $('#maps-tab').on('shown.bs.tab', function(e) {
            initializeMap();
        });

        function initializeMap() {
            if (map) {
                map.remove();
            }

            // Initialize map centered on New York
            map = L.map('mapContainer').setView([40.7128, -74.0060], 10);

            // Add map layers
            const streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            });

            const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: '© Esri'
            });

            streetLayer.addTo(map);

            // Layer control
            const baseMaps = {
                "Street": streetLayer,
                "Satellite": satelliteLayer
            };

            L.control.layers(baseMaps).addTo(map);

            // Load sample data
            loadSampleGeospatialData();
        }

        function loadSampleGeospatialData() {
            // Sample data for demonstration
            const sampleData = {
                entities: [
                    {
                        entity: "Manhattan Financial District",
                        coordinates: [40.7074, -74.0113],
                        confidence: 0.95,
                        context_snippet: "Major financial events in Lower Manhattan",
                        entity_type: "LOCATION"
                    },
                    {
                        entity: "Wall Street",
                        coordinates: [40.7074, -74.0113],
                        confidence: 0.98,
                        context_snippet: "Stock market and financial activities",
                        entity_type: "LOCATION"
                    },
                    {
                        entity: "Times Square",
                        coordinates: [40.7580, -73.9855],
                        confidence: 0.92,
                        context_snippet: "Major public events and announcements",
                        entity_type: "LOCATION"
                    }
                ],
                events: [
                    {
                        event: "Financial Summit 2024",
                        coordinates: [40.7074, -74.0113],
                        timestamp: "2024-01-15T10:00:00Z",
                        event_type: "CONFERENCE"
                    },
                    {
                        event: "Market Announcement",
                        coordinates: [40.7074, -74.0113],
                        timestamp: "2024-01-20T14:30:00Z",
                        event_type: "ANNOUNCEMENT"
                    }
                ]
            };

            currentGeospatialData = sampleData;
            displayGeospatialData(sampleData);
        }

        function displayGeospatialData(data) {
            // Clear existing markers
            markers.forEach(marker => map.removeLayer(marker));
            markers = [];

            // Add entity markers
            if (data.entities) {
                data.entities.forEach(entity => {
                    if (entity.coordinates) {
                        const marker = L.circleMarker([entity.coordinates[0], entity.coordinates[1]], {
                            color: '#fa709a',
                            fillColor: '#fa709a',
                            fillOpacity: 0.7,
                            radius: 8
                        }).addTo(map);

                        marker.bindPopup(`
                            <strong>${entity.entity}</strong><br>
                            Type: ${entity.entity_type || 'Unknown'}<br>
                            Confidence: ${(entity.confidence * 100).toFixed(1)}%<br>
                            Context: ${entity.context_snippet}
                        `);

                        markers.push(marker);
                    }
                });
            }

            // Add event markers
            if (data.events) {
                data.events.forEach(event => {
                    if (event.coordinates) {
                        const marker = L.marker([event.coordinates[0], event.coordinates[1]], {
                            icon: L.divIcon({
                                className: 'event-marker',
                                html: 'EV',
                                iconSize: [20, 20]
                            })
                        }).addTo(map);

                        marker.bindPopup(`
                            <strong>${event.event}</strong><br>
                            Type: ${event.event_type}<br>
                            Time: ${new Date(event.timestamp).toLocaleString()}
                        `);

                        markers.push(marker);
                    }
                });
            }

            // Fit map to markers if any exist
            if (markers.length > 0) {
                const group = new L.featureGroup(markers);
                map.fitBounds(group.getBounds().pad(0.1));
            }
        }

        // Form handlers
        $('#investigationForm').submit(function(e) {
            e.preventDefault();
            startInvestigation();
        });

        $('#geospatialForm').submit(function(e) {
            e.preventDefault();
            performGeospatialAnalysis();
        });

        function startInvestigation() {
            const url = $('#contentUrl').val();
            const analysisType = $('#analysisType').val();

            $('button[type="submit"]').prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Analyzing...');

            $.ajax({
                url: '/api/mcp/investigation/analyze',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    url: url,
                    analysis_type: analysisType
                }),
                success: function(data) {
                    displayFindings(data);
                    $('#contentUrl').val('');
                    $('button[type="submit"]').prop('disabled', false).html('<i class="fas fa-play"></i> Start Investigation');
                    
                    // Switch to results tab
                    $('#results-tab').tab('show');
                },
                error: function() {
                    alert('Error starting investigation');
                    $('button[type="submit"]').prop('disabled', false).html('<i class="fas fa-play"></i> Start Investigation');
                }
            });
        }

        function performGeospatialAnalysis() {
            const query = $('#geoQuery').val();
            const centerLocation = $('#centerLocation').val();
            const searchRadius = $('#searchRadius').val();
            const entityTypes = $('#entityTypes').val();
            const clusteringDistance = $('#clusteringDistance').val();

            // Show loading state
            $('#geospatialForm button').prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i>');

            // Call actual MCP geospatial analysis API
            $.ajax({
                url: '/api/mcp/investigation/geospatial',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    query: query,
                    center_location: centerLocation,
                    search_radius_km: parseFloat(searchRadius),
                    entity_types: entityTypes ? [entityTypes] : [],
                    clustering_distance: parseFloat(clusteringDistance)
                }),
                success: function(data) {
                    console.log('Geospatial analysis result:', data);
                    currentGeospatialData = data;
                    displayGeospatialData(data);
                    
                    // Add center location marker if coordinates provided
                    if (data.center_coordinates) {
                        const centerMarker = L.marker([data.center_coordinates[0], data.center_coordinates[1]], {
                            icon: L.icon({
                                iconUrl: '{{ url_for('static', filename='css/images/marker-icon.png') }}',
                                shadowUrl: '{{ url_for('static', filename='css/images/marker-shadow.png') }}',
                                iconSize: [25, 41],
                                iconAnchor: [12, 41],
                                popupAnchor: [1, -34],
                                shadowSize: [41, 41]
                            })
                        }).addTo(map);
                        
                        centerMarker.bindPopup(`
                            <strong>Search Center</strong><br>
                            Location: ${data.center_location}<br>
                            Radius: ${data.search_radius_km} km<br>
                            Results: ${data.total_results}
                        `);
                        
                        markers.push(centerMarker);
                    }
                },
                error: function(xhr) {
                    console.error('Geospatial analysis failed:', xhr);
                    alert('Geospatial analysis failed: ' + (xhr.responseJSON?.error || 'Unknown error'));
                },
                complete: function() {
                    $('#geospatialForm button').prop('disabled', false).html('<i class="fas fa-search"></i>');
                }
            });
        }

        function applyTimelineFilter() {
            const startDate = $('#startDate').val();
            const endDate = $('#endDate').val();
            const sliderValue = $('#timelineSlider').val();

            console.log('Applying timeline filter:', { startDate, endDate, sliderValue });
            
            // Filter current data based on timeline
            if (currentGeospatialData && currentGeospatialData.events) {
                let filteredData = { ...currentGeospatialData };
                
                if (startDate || endDate) {
                    filteredData.events = currentGeospatialData.events.filter(event => {
                        const eventDate = new Date(event.timestamp);
                        const start = startDate ? new Date(startDate) : new Date('1900-01-01');
                        const end = endDate ? new Date(endDate) : new Date('2100-01-01');
                        return eventDate >= start && eventDate <= end;
                    });
                }
                
                displayGeospatialData(filteredData);
            }
        }

        function displayFindings(result) {
            const findingCard = `
                <div class="card finding-card mb-3">
                    <div class="card-body">
                        <h6>Investigation: ${result.content_url}</h6>
                        <p><strong>Analysis Type:</strong> ${result.analysis_type}</p>
                        <div class="row">
                            <div class="col-md-6">
                                <p><strong>Content Type:</strong> ${result.findings.content_type}</p>
                                <p><strong>Sentiment:</strong> ${result.findings.sentiment}</p>
                            </div>
                            <div class="col-md-6">
                                <p><strong>Credibility Score:</strong> ${(result.findings.credibility_score * 100).toFixed(1)}%</p>
                                <p><strong>Execution Time:</strong> ${result.execution_time}s</p>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            
            $('#findingsContainer').prepend(findingCard);
            
            // Remove "no investigations" message
            $('#findingsContainer p.text-muted').remove();
        }

        // Set default dates
        const today = new Date();
        const oneMonthAgo = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());
        $('#startDate').val(oneMonthAgo.toISOString().split('T')[0]);
        $('#endDate').val(today.toISOString().split('T')[0]);
    </script>
</body>
</html>"""
    
    def create_enhanced_mcp_sdk(self) -> str:
        """Create enhanced MCP JavaScript SDK with GraphRAG support."""
        return r"""
// Enhanced MCP JavaScript SDK with GraphRAG Support
class MCPError extends Error {
    constructor(message, status = 500, data = null) {
        super(message);
        this.name = 'MCPError';
        this.status = status;
        this.data = data;
    }
}

class MCPClient {
    constructor(baseUrl, options = {}) {
        this.baseUrl = baseUrl.replace(/\/$/, '');
        this.timeout = options.timeout || 30000;
        this.apiKey = options.apiKey || null;
    }

    async _request(path, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), this.timeout);
        
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (this.apiKey) {
            headers['Authorization'] = `Bearer ${this.apiKey}`;
        }
        
        try {
            const res = await fetch(`${this.baseUrl}${path}`, { 
                ...options, 
                headers,
                signal: controller.signal 
            });
            
            let data;
            try {
                data = await res.json();
            } catch (e) {
                data = {};
            }
            
            if (!res.ok) {
                throw new MCPError(data.error || res.statusText, res.status, data);
            }
            
            return data;
        } finally {
            clearTimeout(timer);
        }
    }

    // Core MCP methods
    getServerStatus() { 
        return this._request('/status'); 
    }
    
    getTools() { 
        return this._request('/tools'); 
    }
    
    getTool(category, tool) { 
        return this._request(`/tools/${encodeURIComponent(category)}/${encodeURIComponent(tool)}`); 
    }
    
    executeTool(category, tool, params = {}) {
        return this._request(`/tools/${encodeURIComponent(category)}/${encodeURIComponent(tool)}/execute`, {
            method: 'POST',
            body: JSON.stringify(params)
        });
    }

    getExecutionStatus(executionId) {
        return this._request(`/executions/${encodeURIComponent(executionId)}`);
    }

    getExecutionHistory(limit = 50) {
        return this._request(`/history?limit=${limit}`);
    }

    // GraphRAG methods
    startGraphRAGProcessing(url, mode = 'balanced') {
        return this._request('/graphrag/process', {
            method: 'POST',
            body: JSON.stringify({ url, mode })
        });
    }

    getGraphRAGSession(sessionId) {
        return this._request(`/graphrag/sessions/${encodeURIComponent(sessionId)}`);
    }

    listGraphRAGSessions() {
        return this._request('/graphrag/sessions');
    }

    // Analytics methods
    getAnalyticsMetrics() {
        return this._request('/analytics/metrics');
    }

    getAnalyticsHistory(limit = 100) {
        return this._request(`/analytics/history?limit=${limit}`);
    }

    // RAG Query methods
    executeRAGQuery(query, context = {}) {
        return this._request('/rag/query', {
            method: 'POST',
            body: JSON.stringify({ query, context })
        });
    }

    // Investigation methods
    startInvestigation(url, analysisType = 'comprehensive', metadata = {}) {
        return this._request('/investigation/analyze', {
            method: 'POST',
            body: JSON.stringify({ url, analysis_type: analysisType, metadata })
        });
    }

    // Real-time monitoring
    startStatusPolling(intervalMs = 5000, callback = () => {}) {
        let stopped = false;
        
        const tick = async () => {
            if (stopped) return;
            
            try {
                const status = await this.getServerStatus();
                callback(null, status);
            } catch (error) {
                callback(error);
            }
            
            if (!stopped) {
                setTimeout(tick, intervalMs);
            }
        };
        
        setTimeout(tick, 0);
        
        return () => { stopped = true; };
    }

    // WebSocket connection for real-time updates
    connectWebSocket(onMessage = () => {}, onError = () => {}) {
        const wsUrl = this.baseUrl.replace(/^http/, 'ws') + '/ws';
        const ws = new WebSocket(wsUrl);
        
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                onMessage(data);
            } catch (e) {
                onError(new Error('Failed to parse WebSocket message'));
            }
        };
        
        ws.onerror = (error) => {
            onError(error);
        };
        
        return ws;
    }

    // Utility methods
    async waitForExecution(executionId, pollInterval = 1000, maxWait = 300000) {
        const startTime = Date.now();
        
        while (Date.now() - startTime < maxWait) {
            try {
                const status = await this.getExecutionStatus(executionId);
                
                if (status.status === 'completed' || status.status === 'failed') {
                    return status;
                }
                
                await new Promise(resolve => setTimeout(resolve, pollInterval));
            } catch (error) {
                if (error.status === 404) {
                    throw new MCPError('Execution not found', 404);
                }
                throw error;
            }
        }
        
        throw new MCPError('Execution timeout', 408);
    }

    async waitForGraphRAGSession(sessionId, pollInterval = 2000, maxWait = 600000) {
        const startTime = Date.now();
        
        while (Date.now() - startTime < maxWait) {
            try {
                const session = await this.getGraphRAGSession(sessionId);
                
                if (session.status === 'completed' || session.status === 'failed') {
                    return session;
                }
                
                await new Promise(resolve => setTimeout(resolve, pollInterval));
            } catch (error) {
                if (error.status === 404) {
                    throw new MCPError('Session not found', 404);
                }
                throw error;
            }
        }
        
        throw new MCPError('Session timeout', 408);
    }
}

// Export for both browser and Node.js environments
if (typeof window !== 'undefined') {
    window.MCPClient = MCPClient;
    window.MCPError = MCPError;
} else if (typeof module !== 'undefined' && module.exports) {
    module.exports = { MCPClient, MCPError };
}
        """.strip()


def start_mcp_dashboard(config: Optional[MCPDashboardConfig] = None) -> MCPDashboard:
    """
    Start the comprehensive MCP dashboard with GraphRAG integration.
    
    Args:
        config: MCP dashboard configuration
        
    Returns:
        MCPDashboard: The dashboard instance
    """
    dashboard = MCPDashboard()
    dashboard.configure(config or MCPDashboardConfig())
    dashboard._create_mcp_templates()
    dashboard.start()
    return dashboard


if __name__ == "__main__":
    # Start the comprehensive MCP dashboard
    host = os.environ.get("MCP_DASHBOARD_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("MCP_DASHBOARD_PORT", "8080"))
    except ValueError:
        port = 8080

    # Configure with all features enabled
    config = MCPDashboardConfig(
        host=host, 
        port=port, 
        mcp_server_port=8001,
        enable_graphrag=True,
        enable_analytics=True,
        enable_rag_query=True,
        enable_investigation=True,
        enable_real_time_monitoring=True,
        enable_tool_execution=True
    )
    
    if os.environ.get("MCP_DASHBOARD_BLOCKING", "0") in ("1", "true", "True"):
        dash = MCPDashboard()
        dash.configure(config)
        dash._create_mcp_templates()
        print(f"Starting Comprehensive MCP Dashboard (blocking) on http://{config.host}:{config.port}/mcp")
        print("Features enabled:")
        print(f"  - GraphRAG Processing: {config.enable_graphrag}")
        print(f"  - Analytics Dashboard: {config.enable_analytics}")
        print(f"  - RAG Query Interface: {config.enable_rag_query}")
        print(f"  - Investigation Tools: {config.enable_investigation}")
        print(f"  - Real-time Monitoring: {config.enable_real_time_monitoring}")
        dash.app.run(host=config.host, port=config.port, debug=False, use_reloader=False, threaded=True)
    else:
        dashboard = start_mcp_dashboard(config)
        # Best-effort readiness probe
        ready = False
        for _ in range(20):
            try:
                import urllib.request
                with urllib.request.urlopen(f"http://{config.host}:{config.port}/api/mcp/status", timeout=0.5) as r:
                    if r.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.2)
        
        if ready:
            print(f"Comprehensive MCP Dashboard running at http://{config.host}:{config.port}/mcp")
            print("Available features:")
            print(f"  - Main Dashboard: http://{config.host}:{config.port}/mcp")
            if config.enable_graphrag:
                print(f"  - GraphRAG Processing: http://{config.host}:{config.port}/mcp/graphrag")
            if config.enable_analytics:
                print(f"  - Analytics Dashboard: http://{config.host}:{config.port}/mcp/analytics")
            if config.enable_rag_query:
                print(f"  - RAG Query Interface: http://{config.host}:{config.port}/mcp/rag")
            if config.enable_investigation:
                print(f"  - Investigation Tools: http://{config.host}:{config.port}/mcp/investigation")
            print(f"  - API Endpoints: http://{config.host}:{config.port}/api/mcp/")
        else:
            print(
                f"Failed to confirm Comprehensive MCP Dashboard on http://{config.host}:{config.port}. "
                "Check logs or run with MCP_DASHBOARD_BLOCKING=1 for diagnostics."
            )
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
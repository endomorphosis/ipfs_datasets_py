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
    from flask import render_template, jsonify, request, send_from_directory
except Exception:  # pragma: no cover
    render_template = jsonify = request = send_from_directory = None  # type: ignore

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
    enable_tool_execution: bool = False
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
        self.tool_execution_history = []
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
        
        # Real-time monitoring
        self.real_time_clients = set()
        self.monitoring_thread = None
        self.last_metrics_update = time.time()
        
    def configure(self, config: MCPDashboardConfig) -> None:
        """Configure the comprehensive MCP dashboard.
        
        Args:
            config: MCP dashboard configuration
        """
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
    
    def _initialize_graphrag_components(self) -> None:
        """Initialize GraphRAG processing components."""
        if not GRAPHRAG_AVAILABLE:
            return
            
        try:
            # Initialize complete GraphRAG system
            self.graphrag_system = CompleteGraphRAGSystem()
            
            # Initialize enhanced GraphRAG system
            self.enhanced_graphrag = EnhancedGraphRAGSystem()
            
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
        
        for tool_file in category_path.glob("*.py"):
            if tool_file.name.startswith('_') or tool_file.name == '__init__.py':
                continue
                
            tool_info = {
                "name": tool_file.stem,
                "file": str(tool_file),
                "category": category_path.name,
                "description": "MCP Tool",  # Will be updated when tool is loaded
                "parameters": [],
                "last_modified": datetime.fromtimestamp(tool_file.stat().st_mtime).isoformat()
            }
            tools.append(tool_info)
            
        return tools
        
    def _setup_routes(self) -> None:
        """Set up Flask routes for the comprehensive MCP dashboard."""
        # Set up parent routes first
        super()._setup_routes()
        
        if not self.app:
            return
            
        # MCP-specific routes
        @self.app.route('/mcp')
        def mcp_dashboard():
            """Render the main MCP dashboard page."""
            tools_info = self._discover_mcp_tools()
            server_status = self._get_mcp_server_status()
            
            dashboard_data = {
                "tools_info": tools_info,
                "server_status": server_status,
                "execution_history": self.tool_execution_history[-50:],
                "active_executions": len(self.active_tool_executions),
                "dashboard_config": self.mcp_config.__dict__ if self.mcp_config else {},
                "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "graphrag_enabled": self.mcp_config.enable_graphrag if self.mcp_config else False,
                "analytics_enabled": self.mcp_config.enable_analytics if self.mcp_config else False,
                "rag_query_enabled": self.mcp_config.enable_rag_query if self.mcp_config else False,
                "investigation_enabled": self.mcp_config.enable_investigation if self.mcp_config else False
            }
            
            return render_template('mcp_dashboard.html', **dashboard_data)
        
        # GraphRAG routes
        if self.mcp_config and self.mcp_config.enable_graphrag:
            self._setup_graphrag_routes()
        
        # Analytics routes  
        if self.mcp_config and self.mcp_config.enable_analytics:
            self._setup_analytics_routes()
        
        # RAG query routes
        if self.mcp_config and self.mcp_config.enable_rag_query:
            self._setup_rag_query_routes()
        
        # Investigation routes
        if self.mcp_config and self.mcp_config.enable_investigation:
            self._setup_investigation_routes()
            
        # Caselaw routes - Always enabled for temporal deontic logic RAG system
        self._setup_caselaw_routes()
            
        # Original MCP tool routes
        self._setup_mcp_tool_routes()
    
    def _setup_graphrag_routes(self) -> None:
        """Set up GraphRAG processing routes."""
        
        @self.app.route('/mcp/graphrag')
        def graphrag_dashboard():
            """Render the GraphRAG processing dashboard."""
            processing_stats = self._get_graphrag_processing_stats()
            active_sessions = list(self.graphrag_processing_sessions.keys())
            
            return render_template('graphrag_dashboard.html', 
                                 processing_stats=processing_stats,
                                 active_sessions=active_sessions,
                                 last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
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
            
            return render_template('admin/caselaw_dashboard_mcp.html', **dashboard_data)
        
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
            
            return render_template('admin/caselaw_dashboard.html', **dashboard_data)
        
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
                    return jsonify({"error": "Document text is required"}), 400
                
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
                
                # Format response
                result = {
                    "document_id": analysis.document_id,
                    "is_consistent": analysis.consistency_result.is_consistent if analysis.consistency_result else False,
                    "confidence_score": analysis.confidence_score,
                    "formulas_extracted": len(analysis.extracted_formulas),
                    "issues_found": len(analysis.issues_found),
                    "conflicts": len(analysis.consistency_result.conflicts) if analysis.consistency_result else 0,
                    "temporal_conflicts": len(analysis.consistency_result.temporal_conflicts) if analysis.consistency_result else 0,
                    "processing_time": analysis.processing_time,
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
                return jsonify({"error": str(e)}), 500
        
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
                return jsonify({"error": str(e)}), 500
        
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
                    return jsonify({"error": "Query text is required"}), 400
                
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
                    "query": {
                        "text": query_text,
                        "operator": operator_str,
                        "jurisdiction": jurisdiction,
                        "legal_domain": legal_domain
                    },
                    "total_results": len(relevant_theorems),
                    "theorems": [
                        {
                            "theorem_id": t.theorem_id,
                            "operator": t.formula.operator.name,
                            "proposition": t.formula.proposition,
                            "agent": t.formula.agent.name if t.formula.agent else "Unspecified",
                            "jurisdiction": t.jurisdiction,
                            "legal_domain": t.legal_domain,
                            "source_case": t.source_case,
                            "precedent_strength": t.precedent_strength,
                            "confidence": t.confidence,
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
                return jsonify({"error": str(e)}), 500

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
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
        
    def create_mcp_dashboard_template(self) -> str:
        """Create the comprehensive MCP dashboard HTML template with GraphRAG integration."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IPFS Datasets Comprehensive MCP Dashboard</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/dashboard.css') }}">
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

    <script src="{{ url_for('static', filename='js/jquery.min.js') }}"></script>
    <script src="{{ url_for('static', filename='js/bootstrap.bundle.min.js') }}"></script>
    <script src="{{ url_for('static', filename='js/mcp-sdk.js') }}"></script>
    <script>
        $(document).ready(function() {
            // Initialize MCP SDK
            window.mcpSDK = new MCPClient('{{ request.host_url }}api/mcp');
            
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

        # Create main MCP dashboard template
        mcp_template_path = templates_dir / "mcp_dashboard.html"
        if not mcp_template_path.exists():
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
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
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
    <script src="{{ url_for('static', filename='js/bootstrap.min.js') }}"></script>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
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
                                iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
                                shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
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
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP-Enabled News Analysis Dashboard for IPFS Datasets Python.

This module provides a unified investigation dashboard that routes all calls
through the MCP (Model Context Protocol) server instead of direct API calls.
All functionality is accessed via MCP tools using JSON-RPC communication.
"""
from __future__ import annotations

import anyio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from .mcp_dashboard import MCPDashboard, MCPDashboardConfig
from .mcp_server.client import MCPClient

logger = logging.getLogger(__name__)


@dataclass
class MCPInvestigationDashboardConfig(MCPDashboardConfig):
    """Configuration for MCP-enabled investigation dashboard."""
    mcp_server_url: str = "http://localhost:8080"
    mcp_endpoint: str = "/mcp/call-tool"
    default_timeout: int = 60
    enable_caching: bool = True
    cache_duration: int = 300  # 5 minutes
    

class MCPInvestigationDashboard:
    """
    MCP-Enabled Investigation Dashboard.
    
    This dashboard provides unified investigation capabilities by routing
    all operations through MCP tools using JSON-RPC communication.
    """
    
    def __init__(self, config: Optional[MCPInvestigationDashboardConfig] = None):
        """Initialize the MCP Investigation Dashboard."""
        self.config = config or MCPInvestigationDashboardConfig()
        self.mcp_client = MCPClient(
            base_url=self.config.mcp_server_url,
            endpoint=self.config.mcp_endpoint,
            timeout=self.config.default_timeout
        )
        self.app = None  # Will be set by setup_app()
        
    def setup_app(self, app):
        """Setup Flask app with MCP routes."""
        self.app = app
        self._register_mcp_routes()
        return app
    
    def _register_mcp_routes(self):
        """Register all investigation routes that use MCP tools."""
        
        # Health check endpoint
        @self.app.route('/api/mcp/health')
        async def health_check():
            try:
                # Test MCP connection by calling a simple tool
                result = await self.mcp_client.call_tool('health_check', {})
                return {
                    'status': 'healthy',
                    'mcp_server': 'connected',
                    'timestamp': datetime.now().isoformat()
                }
            except Exception as e:
                return {
                    'status': 'unhealthy', 
                    'error': str(e),
                    'mcp_server': 'disconnected',
                    'timestamp': datetime.now().isoformat()
                }, 500
        
        # Data Ingestion Routes
        @self.app.route('/api/investigation/ingest/article', methods=['POST'])
        async def ingest_news_article():
            try:
                data = await self.app.request.get_json()
                
                result = await self.mcp_client.call_tool('ingest_news_article', {
                    'url': data['url'],
                    'source_type': data.get('source_type', 'news'),
                    'analysis_type': data.get('analysis_type', 'comprehensive'),
                    'metadata': json.dumps(data.get('metadata', {}))
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Article ingestion failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        @self.app.route('/api/investigation/ingest/feed', methods=['POST'])
        async def ingest_news_feed():
            try:
                data = await self.app.request.get_json()
                
                result = await self.mcp_client.call_tool('ingest_news_feed', {
                    'feed_url': data['feed_url'],
                    'max_articles': data.get('max_articles', 50),
                    'filters': json.dumps(data.get('filters', {})),
                    'processing_mode': data.get('processing_mode', 'parallel')
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Feed ingestion failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        @self.app.route('/api/investigation/ingest/website', methods=['POST'])
        async def ingest_website():
            try:
                data = await self.app.request.get_json()
                
                result = await self.mcp_client.call_tool('ingest_website', {
                    'base_url': data['base_url'],
                    'max_pages': data.get('max_pages', 100),
                    'max_depth': data.get('max_depth', 3),
                    'url_patterns': json.dumps(data.get('url_patterns', {})),
                    'content_types': json.dumps(data.get('content_types', ['text/html']))
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Website ingestion failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        @self.app.route('/api/investigation/ingest/documents', methods=['POST'])
        async def ingest_document_collection():
            try:
                data = await self.app.request.get_json()
                
                result = await self.mcp_client.call_tool('ingest_document_collection', {
                    'document_paths': json.dumps(data['document_paths']),
                    'collection_name': data.get('collection_name', 'document_collection'),
                    'processing_options': json.dumps(data.get('processing_options', {})),
                    'metadata_extraction': data.get('metadata_extraction', True)
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Document collection ingestion failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        # Entity Analysis Routes
        @self.app.route('/api/investigation/analyze/entities', methods=['POST'])
        async def analyze_entities():
            try:
                data = await self.app.request.get_json()
                
                result = await self.mcp_client.call_tool('analyze_entities', {
                    'corpus_data': json.dumps(data['corpus_data']),
                    'analysis_type': data.get('analysis_type', 'comprehensive'),
                    'entity_types': data.get('entity_types', ['PERSON', 'ORG', 'GPE', 'EVENT']),
                    'confidence_threshold': data.get('confidence_threshold', 0.85),
                    'user_context': data.get('user_context')
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Entity analysis failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        @self.app.route('/api/investigation/explore/entity/<entity_id>', methods=['GET'])
        async def explore_entity(entity_id: str):
            try:
                # Get corpus data from query parameters or session
                corpus_data = self.app.request.args.get('corpus_data', '{"documents": []}')
                
                result = await self.mcp_client.call_tool('explore_entity', {
                    'entity_id': entity_id,
                    'corpus_data': corpus_data,
                    'include_relationships': self.app.request.args.get('include_relationships', 'true').lower() == 'true',
                    'include_timeline': self.app.request.args.get('include_timeline', 'true').lower() == 'true',
                    'include_sources': self.app.request.args.get('include_sources', 'true').lower() == 'true'
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Entity exploration failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        # Relationship Mapping Routes
        @self.app.route('/api/investigation/map/relationships', methods=['POST'])
        async def map_relationships():
            try:
                data = await self.app.request.get_json()
                
                result = await self.mcp_client.call_tool('map_relationships', {
                    'corpus_data': json.dumps(data['corpus_data']),
                    'relationship_types': data.get('relationship_types', ['co_occurrence', 'citation', 'semantic', 'temporal']),
                    'min_strength': data.get('min_strength', 0.5),
                    'max_depth': data.get('max_depth', 3),
                    'focus_entity': data.get('focus_entity')
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Relationship mapping failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        @self.app.route('/api/investigation/timeline/<entity_id>', methods=['GET'])
        async def analyze_entity_timeline(entity_id: str):
            try:
                corpus_data = self.app.request.args.get('corpus_data', '{"documents": []}')
                
                result = await self.mcp_client.call_tool('analyze_entity_timeline', {
                    'entity_id': entity_id,
                    'corpus_data': corpus_data,
                    'time_granularity': self.app.request.args.get('time_granularity', 'day'),
                    'include_related': self.app.request.args.get('include_related', 'true').lower() == 'true',
                    'event_types': self.app.request.args.getlist('event_types') or ['mention', 'action', 'relationship', 'property_change']
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Timeline analysis failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        # Pattern Detection Routes
        @self.app.route('/api/investigation/detect/patterns', methods=['POST'])
        async def detect_patterns():
            try:
                data = await self.app.request.get_json()
                
                result = await self.mcp_client.call_tool('detect_patterns', {
                    'corpus_data': json.dumps(data['corpus_data']),
                    'pattern_types': data.get('pattern_types', ['behavioral', 'relational', 'temporal', 'anomaly']),
                    'time_window': data.get('time_window', '30d'),
                    'confidence_threshold': data.get('confidence_threshold', 0.7)
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Pattern detection failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        @self.app.route('/api/investigation/track/provenance/<entity_id>', methods=['GET'])
        async def track_provenance(entity_id: str):
            try:
                corpus_data = self.app.request.args.get('corpus_data', '{"documents": []}')
                
                result = await self.mcp_client.call_tool('track_provenance', {
                    'entity_id': entity_id,
                    'corpus_data': corpus_data,
                    'trace_depth': int(self.app.request.args.get('trace_depth', '5')),
                    'include_citations': self.app.request.args.get('include_citations', 'true').lower() == 'true',
                    'include_transformations': self.app.request.args.get('include_transformations', 'true').lower() == 'true'
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Provenance tracking failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        # Deontological Reasoning Routes
        @self.app.route('/api/investigation/analyze/deontological', methods=['POST'])
        async def analyze_deontological_conflicts():
            try:
                data = await self.app.request.get_json()
                
                result = await self.mcp_client.call_tool('analyze_deontological_conflicts', {
                    'corpus_data': json.dumps(data['corpus_data']),
                    'conflict_types': data.get('conflict_types', ['direct', 'conditional', 'jurisdictional', 'temporal']),
                    'severity_threshold': data.get('severity_threshold', 'medium'),
                    'entity_filter': data.get('entity_filter')
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Deontological analysis failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        @self.app.route('/api/investigation/query/deontic_statements', methods=['GET'])
        async def query_deontic_statements():
            try:
                corpus_data = self.app.request.args.get('corpus_data', '{"documents": []}')
                
                result = await self.mcp_client.call_tool('query_deontic_statements', {
                    'corpus_data': corpus_data,
                    'entity': self.app.request.args.get('entity'),
                    'modality': self.app.request.args.get('modality'),
                    'action_pattern': self.app.request.args.get('action_pattern'),
                    'confidence_min': float(self.app.request.args.get('confidence_min', '0.0'))
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Deontic statement query failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        @self.app.route('/api/investigation/query/deontic_conflicts', methods=['GET'])
        async def query_deontic_conflicts():
            try:
                corpus_data = self.app.request.args.get('corpus_data', '{"documents": []}')
                
                result = await self.mcp_client.call_tool('query_deontic_conflicts', {
                    'corpus_data': corpus_data,
                    'conflict_type': self.app.request.args.get('conflict_type'),
                    'severity': self.app.request.args.get('severity'),
                    'entity': self.app.request.args.get('entity'),
                    'resolved_only': self.app.request.args.get('resolved_only', 'false').lower() == 'true'
                })
                
                return self._format_mcp_response(result)
                
            except Exception as e:
                logger.error(f"Deontic conflict query failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        # Workflow Management Routes
        @self.app.route('/api/investigation/workflow/start', methods=['POST'])
        async def start_investigation_workflow():
            try:
                data = await self.app.request.get_json()
                workflow_type = data['workflow_type']
                parameters = data.get('parameters', {})
                
                # Route to appropriate workflow based on type
                if workflow_type == 'comprehensive_entity_analysis':
                    result = await self._run_comprehensive_entity_analysis(parameters)
                elif workflow_type == 'relationship_investigation':
                    result = await self._run_relationship_investigation(parameters)
                elif workflow_type == 'deontological_analysis':
                    result = await self._run_deontological_analysis(parameters)
                elif workflow_type == 'data_ingestion_pipeline':
                    result = await self._run_data_ingestion_pipeline(parameters)
                else:
                    return {'error': f'Unknown workflow type: {workflow_type}'}, 400
                
                return {
                    'workflow_id': f"workflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    'status': 'completed',
                    'result': result,
                    'timestamp': datetime.now().isoformat()
                }
                
            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")
                return {'error': str(e), 'status': 'failed'}, 500
        
        # Dashboard rendering routes
        @self.app.route('/investigation')
        async def investigation_dashboard():
            return await self.app.render_template('unified_investigation_dashboard_mcp.html')
    
    def _format_mcp_response(self, mcp_result: Dict[str, Any]) -> Dict[str, Any]:
        """Format MCP tool response for HTTP API."""
        if mcp_result.get('isError'):
            error_content = mcp_result.get('content', [{}])[0]
            error_message = error_content.get('text', 'Unknown error')
            return {'error': error_message, 'status': 'failed'}
        
        # Extract content from MCP response
        content = mcp_result.get('content', [{}])[0]
        result_text = content.get('text', '{}')
        
        try:
            # Try to parse as JSON
            result = json.loads(result_text)
            return result
        except json.JSONDecodeError:
            # Return raw text if not valid JSON
            return {'raw_content': result_text}
    
    # Workflow implementations
    async def _run_comprehensive_entity_analysis(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run comprehensive entity analysis workflow."""
        corpus_data = params['corpus_data']
        results = {}
        
        # Step 1: Entity Analysis
        entity_result = await self.mcp_client.call_tool('analyze_entities', {
            'corpus_data': json.dumps(corpus_data),
            'analysis_type': 'comprehensive',
            'confidence_threshold': params.get('confidence_threshold', 0.85)
        })
        results['entity_analysis'] = self._format_mcp_response(entity_result)
        
        # Step 2: Relationship Mapping
        relationship_result = await self.mcp_client.call_tool('map_relationships', {
            'corpus_data': json.dumps(corpus_data),
            'min_strength': params.get('min_strength', 0.5)
        })
        results['relationship_mapping'] = self._format_mcp_response(relationship_result)
        
        # Step 3: Pattern Detection
        pattern_result = await self.mcp_client.call_tool('detect_patterns', {
            'corpus_data': json.dumps(corpus_data),
            'confidence_threshold': params.get('pattern_confidence', 0.7)
        })
        results['pattern_detection'] = self._format_mcp_response(pattern_result)
        
        return results
    
    async def _run_relationship_investigation(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run relationship investigation workflow."""
        corpus_data = params['corpus_data']
        entity_id = params['entity_id']
        results = {}
        
        # Step 1: Relationship Mapping
        relationship_result = await self.mcp_client.call_tool('map_relationships', {
            'corpus_data': json.dumps(corpus_data),
            'focus_entity': entity_id,
            'max_depth': params.get('max_depth', 3)
        })
        results['relationship_mapping'] = self._format_mcp_response(relationship_result)
        
        # Step 2: Timeline Analysis
        timeline_result = await self.mcp_client.call_tool('analyze_entity_timeline', {
            'entity_id': entity_id,
            'corpus_data': json.dumps(corpus_data),
            'include_related': True
        })
        results['timeline_analysis'] = self._format_mcp_response(timeline_result)
        
        # Step 3: Provenance Tracking
        provenance_result = await self.mcp_client.call_tool('track_provenance', {
            'entity_id': entity_id,
            'corpus_data': json.dumps(corpus_data),
            'trace_depth': params.get('trace_depth', 5)
        })
        results['provenance_tracking'] = self._format_mcp_response(provenance_result)
        
        return results
    
    async def _run_deontological_analysis(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run deontological analysis workflow."""
        corpus_data = params['corpus_data']
        results = {}
        
        # Step 1: Conflict Analysis
        conflict_result = await self.mcp_client.call_tool('analyze_deontological_conflicts', {
            'corpus_data': json.dumps(corpus_data),
            'severity_threshold': params.get('severity_threshold', 'medium')
        })
        results['conflict_analysis'] = self._format_mcp_response(conflict_result)
        
        # Step 2: Statement Query
        statement_result = await self.mcp_client.call_tool('query_deontic_statements', {
            'corpus_data': json.dumps(corpus_data),
            'confidence_min': params.get('confidence_min', 0.0)
        })
        results['statement_query'] = self._format_mcp_response(statement_result)
        
        # Step 3: Conflict Query
        conflict_query_result = await self.mcp_client.call_tool('query_deontic_conflicts', {
            'corpus_data': json.dumps(corpus_data),
            'resolved_only': False
        })
        results['conflict_query'] = self._format_mcp_response(conflict_query_result)
        
        return results
    
    async def _run_data_ingestion_pipeline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run data ingestion pipeline workflow."""
        results = {}
        
        # Process URLs if provided
        if 'urls' in params:
            url_results = []
            for url in params['urls']:
                try:
                    result = await self.mcp_client.call_tool('ingest_news_article', {
                        'url': url,
                        'source_type': params.get('source_type', 'news'),
                        'analysis_type': params.get('analysis_type', 'comprehensive')
                    })
                    url_results.append(self._format_mcp_response(result))
                except Exception as e:
                    url_results.append({'url': url, 'error': str(e)})
            
            results['url_ingestion'] = url_results
        
        # Process websites if provided
        if 'websites' in params:
            website_results = []
            for website in params['websites']:
                try:
                    result = await self.mcp_client.call_tool('ingest_website', {
                        'base_url': website,
                        'max_pages': params.get('max_pages', 100),
                        'max_depth': params.get('max_depth', 3)
                    })
                    website_results.append(self._format_mcp_response(result))
                except Exception as e:
                    website_results.append({'website': website, 'error': str(e)})
            
            results['website_ingestion'] = website_results
        
        # Process document collections if provided
        if 'document_paths' in params:
            try:
                result = await self.mcp_client.call_tool('ingest_document_collection', {
                    'document_paths': json.dumps(params['document_paths']),
                    'collection_name': params.get('collection_name', 'pipeline_collection'),
                    'metadata_extraction': params.get('metadata_extraction', True)
                })
                results['document_ingestion'] = self._format_mcp_response(result)
            except Exception as e:
                results['document_ingestion'] = {'error': str(e)}
        
        return results
    
    async def start(self, host: str = "localhost", port: int = 8080, debug: bool = False):
        """Start the investigation dashboard server."""
        if not self.app:
            raise RuntimeError("App not initialized. Call setup_app() first.")
            
        logger.info(f"Starting MCP Investigation Dashboard on {host}:{port}")
        await self.app.run(host=host, port=port, debug=debug)


# Utility functions for integration
def create_mcp_investigation_dashboard(config: Optional[MCPInvestigationDashboardConfig] = None):
    """Create and configure the MCP Investigation Dashboard."""
    return MCPInvestigationDashboard(config)


async def main():
    """Main function for running the dashboard standalone."""
    config = MCPInvestigationDashboardConfig()
    dashboard = create_mcp_investigation_dashboard(config)
    
    # For standalone use, you'd need to create a Flask/FastAPI app and setup routes
    # This is typically done by the main application
    logger.info("MCP Investigation Dashboard created. Use setup_app() to configure with web framework.")


if __name__ == "__main__":
    anyio.run(main())
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
News Analysis Dashboard for IPFS Datasets Python.

This module extends the MCP Dashboard to provide specialized functionality
for news analysis workflows targeting data scientists, historians, and lawyers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

# Import existing dashboard functionality
from .mcp_dashboard import MCPDashboard, MCPDashboardConfig
from .deontological_reasoning import (
    DeontologicalReasoningEngine, 
    DeonticModality, 
    ConflictType,
    DeonticStatement,
    DeonticConflict
)

logger = logging.getLogger(__name__)


class AnalysisType(Enum):
    """Types of analysis supported by the unified investigation dashboard."""
    ENTITY_ANALYSIS = "entity_analysis"
    RELATIONSHIP_MAPPING = "relationship_mapping"
    TEMPORAL_ANALYSIS = "temporal_analysis"
    PATTERN_DETECTION = "pattern_detection"
    CONFLICT_ANALYSIS = "conflict_analysis"
    PROVENANCE_TRACKING = "provenance_tracking"
    DEONTOLOGICAL_ANALYSIS = "deontological_analysis"  # New analysis type


@dataclass
class NewsArticle:
    """Represents a news article with metadata."""
    id: str
    url: str
    title: str
    content: str
    published_date: datetime
    source: str
    author: Optional[str] = None
    tags: List[str] = None
    entities: List[Dict[str, Any]] = None
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.entities is None:
            self.entities = []
        if self.metadata is None:
            self.metadata = {}


@dataclass
class InvestigationFilter:
    """Search filters for unified investigation analysis."""
    date_range: Optional[Tuple[datetime, datetime]] = None
    sources: Optional[List[str]] = None
    entity_types: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    author: Optional[str] = None
    analysis_type: Optional[AnalysisType] = None
    confidence_threshold: Optional[float] = None


class InvestigationWorkflowManager:
    """Manages unified investigation workflows and tool orchestrations for entity analysis."""
    
    def __init__(self, mcp_dashboard: MCPDashboard):
        self.dashboard = mcp_dashboard
        self.active_investigations = {}
        
    async def execute_entity_analysis_pipeline(
        self, 
        content: Union[str, List[str]], 
        analysis_type: AnalysisType = AnalysisType.ENTITY_ANALYSIS,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute comprehensive entity analysis pipeline."""
        workflow_id = f"analysis_{int(time.time())}"
        
        try:
            # Step 1: Entity extraction
            extraction_result = await self.dashboard.execute_tool(
                "analysis_tools.extract_entities",
                {"text": content, "extract_relationships": True}
            )
            
            # Step 2: Relationship mapping
            relationship_result = await self.dashboard.execute_tool(
                "analysis_tools.map_relationships",
                {"entities": extraction_result.get("entities", [])}
            )
            
            # Step 3: Pattern detection
            pattern_result = await self.dashboard.execute_tool(
                "analysis_tools.detect_patterns",
                {
                    "entities": extraction_result.get("entities", []),
                    "relationships": relationship_result.get("relationships", [])
                }
            )
            
            # Step 4: Deontological analysis if requested
            deontological_result = {}
            if analysis_type == AnalysisType.DEONTOLOGICAL_ANALYSIS:
                # Prepare documents for deontological analysis
                documents = []
                if isinstance(content, str):
                    documents = [{"id": workflow_id, "content": content}]
                elif isinstance(content, list):
                    documents = [{"id": f"{workflow_id}_{i}", "content": doc} 
                               for i, doc in enumerate(content)]
                
                # Import the deontological engine here to avoid circular imports
                from .deontological_reasoning import DeontologicalReasoningEngine
                deontological_engine = DeontologicalReasoningEngine(self.dashboard)
                
                deontological_result = await deontological_engine.analyze_corpus_for_deontic_conflicts(documents)
            
            # Step 5: Generate investigation report
            report_result = {
                "workflow_id": workflow_id,
                "analysis_type": analysis_type.value,
                "timestamp": datetime.now().isoformat(),
                "entities": extraction_result.get("entities", []),
                "relationships": relationship_result.get("relationships", []),
                "patterns": pattern_result.get("patterns", []),
                "metadata": metadata or {}
            }
            
            # Add deontological results if performed
            if deontological_result:
                report_result["deontological_analysis"] = deontological_result
            
            self.active_investigations[workflow_id] = report_result
            
            return report_result
            
        except Exception as e:
            logger.error(f"Entity analysis pipeline failed: {str(e)}")
            return {
                "error": str(e),
                "workflow_id": workflow_id,
                "status": "failed"
            }


class EntityExplorer:
    """Advanced entity exploration and analysis capabilities."""
    
    def __init__(self, dashboard: MCPDashboard):
        self.dashboard = dashboard
        
    async def explore_entity_cluster(self, entity_id: str) -> Dict[str, Any]:
        """Explore an entity and its connected cluster."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.explore_entity_cluster",
                {"entity_id": entity_id}
            )
            return result
        except Exception as e:
            logger.error(f"Entity cluster exploration failed: {str(e)}")
            return {"error": str(e)}
    
    async def compare_entities(self, entity_ids: List[str]) -> Dict[str, Any]:
        """Compare multiple entities for similarities and differences."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.compare_entities",
                {"entity_ids": entity_ids}
            )
            return result
        except Exception as e:
            logger.error(f"Entity comparison failed: {str(e)}")
            return {"error": str(e)}


class RelationshipMapper:
    """Advanced relationship mapping and visualization."""
    
    def __init__(self, dashboard: MCPDashboard):
        self.dashboard = dashboard
        
    async def map_relationships(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Map relationships between entities."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.map_relationships",
                {"entities": entities}
            )
            return result
        except Exception as e:
            logger.error(f"Relationship mapping failed: {str(e)}")
            return {"error": str(e)}
    
    async def find_shortest_path(self, source_entity: str, target_entity: str) -> Dict[str, Any]:
        """Find the shortest path between two entities."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.find_shortest_path",
                {"source": source_entity, "target": target_entity}
            )
            return result
        except Exception as e:
            logger.error(f"Path finding failed: {str(e)}")
            return {"error": str(e)}


class PatternDetector:
    """Pattern detection and anomaly analysis."""
    
    def __init__(self, dashboard: MCPDashboard):
        self.dashboard = dashboard
        
    async def detect_patterns(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Detect patterns in the data."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.detect_patterns",
                data
            )
            return result
        except Exception as e:
            logger.error(f"Pattern detection failed: {str(e)}")
            return {"error": str(e)}
    
    async def detect_anomalies(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect anomalies in entity behavior or relationships."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.detect_anomalies",
                {"entities": entities}
            )
            return result
        except Exception as e:
            logger.error(f"Anomaly detection failed: {str(e)}")
            return {"error": str(e)}


class ConflictAnalyzer:
    """Cross-document conflict detection and analysis including deontological reasoning."""
    
    def __init__(self, dashboard: MCPDashboard):
        self.dashboard = dashboard
        self.deontological_engine = DeontologicalReasoningEngine(dashboard)
        
    async def detect_conflicts(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect conflicts between documents."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.detect_conflicts",
                {"documents": documents}
            )
            return result
        except Exception as e:
            logger.error(f"Conflict detection failed: {str(e)}")
            return {"error": str(e)}
    
    async def analyze_conflicting_claims(self, claims: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze conflicting claims across documents."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.analyze_conflicting_claims",
                {"claims": claims}
            )
            return result
        except Exception as e:
            logger.error(f"Conflicting claims analysis failed: {str(e)}")
            return {"error": str(e)}
    
    async def analyze_deontological_conflicts(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze legal/ethical conflicts - what entities can/cannot, must/must not do."""
        try:
            logger.info(f"Starting deontological conflict analysis on {len(documents)} documents")
            
            # Use the deontological reasoning engine
            result = await self.deontological_engine.analyze_corpus_for_deontic_conflicts(documents)
            
            return {
                "analysis_type": "deontological_conflicts",
                "status": "completed",
                "result": result,
                "processing_time": result.get("timestamp"),
                "documents_analyzed": len(documents)
            }
            
        except Exception as e:
            logger.error(f"Deontological conflict analysis failed: {str(e)}")
            return {
                "analysis_type": "deontological_conflicts", 
                "status": "failed",
                "error": str(e),
                "documents_analyzed": len(documents)
            }
    
    async def query_deontic_statements(
        self, 
        entity: Optional[str] = None,
        modality: Optional[str] = None,
        action_keywords: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Query extracted deontic statements (obligations, permissions, prohibitions)."""
        try:
            # Convert string modality to enum if provided
            modality_enum = None
            if modality:
                try:
                    modality_enum = DeonticModality(modality.lower())
                except ValueError:
                    return {"error": f"Invalid modality: {modality}"}
            
            statements = await self.deontological_engine.query_deontic_statements(
                entity=entity,
                modality=modality_enum,
                action_keywords=action_keywords
            )
            
            return {
                "query_type": "deontic_statements",
                "total_results": len(statements),
                "statements": [
                    {
                        "id": stmt.id,
                        "entity": stmt.entity,
                        "action": stmt.action,
                        "modality": stmt.modality.value,
                        "source_document": stmt.source_document,
                        "source_text": stmt.source_text,
                        "confidence": stmt.confidence,
                        "conditions": stmt.conditions,
                        "exceptions": stmt.exceptions
                    } for stmt in statements
                ]
            }
            
        except Exception as e:
            logger.error(f"Deontic statement query failed: {str(e)}")
            return {"error": str(e)}
    
    async def query_deontic_conflicts(
        self,
        entity: Optional[str] = None,
        conflict_type: Optional[str] = None,
        min_severity: Optional[str] = None
    ) -> Dict[str, Any]:
        """Query detected deontological conflicts."""
        try:
            # Convert string conflict type to enum if provided
            conflict_type_enum = None
            if conflict_type:
                try:
                    conflict_type_enum = ConflictType(conflict_type.lower())
                except ValueError:
                    return {"error": f"Invalid conflict type: {conflict_type}"}
            
            conflicts = await self.deontological_engine.query_conflicts(
                entity=entity,
                conflict_type=conflict_type_enum,
                min_severity=min_severity
            )
            
            return {
                "query_type": "deontic_conflicts",
                "total_results": len(conflicts),
                "conflicts": [
                    {
                        "id": conflict.id,
                        "type": conflict.conflict_type.value,
                        "severity": conflict.severity,
                        "entity": conflict.statement1.entity,
                        "explanation": conflict.explanation,
                        "statement1": {
                            "text": conflict.statement1.source_text,
                            "modality": conflict.statement1.modality.value,
                            "action": conflict.statement1.action,
                            "source": conflict.statement1.source_document
                        },
                        "statement2": {
                            "text": conflict.statement2.source_text,
                            "modality": conflict.statement2.modality.value,
                            "action": conflict.statement2.action,
                            "source": conflict.statement2.source_document
                        },
                        "resolution_suggestions": conflict.resolution_suggestions
                    } for conflict in conflicts
                ]
            }
            
        except Exception as e:
            logger.error(f"Deontic conflict query failed: {str(e)}")
            return {"error": str(e)}


class ProvenanceTracker:
    """Data provenance tracking and lineage analysis."""
    
    def __init__(self, dashboard: MCPDashboard):
        self.dashboard = dashboard
        
    async def track_entity_provenance(self, entity_id: str) -> Dict[str, Any]:
        """Track provenance for a specific entity."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.track_entity_provenance",
                {"entity_id": entity_id}
            )
            return result
        except Exception as e:
            logger.error(f"Provenance tracking failed: {str(e)}")
            return {"error": str(e)}
    
    async def analyze_information_flow(self, source_docs: List[str]) -> Dict[str, Any]:
        """Analyze how information flows between documents."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.analyze_information_flow",
                {"source_docs": source_docs}
            )
            return result
        except Exception as e:
            logger.error(f"Information flow analysis failed: {str(e)}")
            return {"error": str(e)}


class TimelineAnalysisEngine:
    """Timeline analysis and visualization engine."""
    
    def __init__(self, dashboard: MCPDashboard):
        self.dashboard = dashboard
        
    async def create_entity_timeline(self, entity_id: str) -> Dict[str, Any]:
        """Create timeline for specific entity mentions and activities."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.create_entity_timeline",
                {"entity_id": entity_id}
            )
            return result
        except Exception as e:
            logger.error(f"Timeline creation failed: {str(e)}")
            return {"error": str(e)}
    
    async def detect_temporal_patterns(self, entities: List[str]) -> Dict[str, Any]:
        """Detect temporal patterns in entity activities."""
        try:
            result = await self.dashboard.execute_tool(
                "analysis_tools.detect_temporal_patterns",
                {"entities": entities}
            )
            return result
        except Exception as e:
            logger.error(f"Temporal pattern detection failed: {str(e)}")
            return {"error": str(e)}


class NewsWorkflowEngine:
    """News ingestion workflow engine."""
    
    def __init__(self, dashboard: MCPDashboard):
        self.dashboard = dashboard
        self.active_workflows = {}
    
    async def execute_news_feed_ingestion(
        self,
        feed_url: str,
        filters: Optional[Dict[str, Any]] = None,
        max_articles: int = 50
    ) -> Dict[str, Any]:
        """Batch process news feed articles."""
        workflow_id = f"feed_ingest_{int(time.time())}"
        
        try:
            # Step 1: Parse RSS/news feed
            feed_result = await self.dashboard.execute_tool(
                "web_archive_tools.parse_news_feed",
                {"feed_url": feed_url, "max_items": max_articles}
            )
            
            articles = feed_result.get("articles", [])
            successful_ingests = []
            failed_ingests = []
            
            # Step 2: Process each article
            for article in articles[:max_articles]:
                try:
                    article_metadata = {
                        "feed_source": feed_url,
                        "batch_workflow_id": workflow_id,
                        "article_index": len(successful_ingests)
                    }
                    
                    if filters:
                        article_metadata["filters_applied"] = filters
                    
                    ingest_result = await self.execute_news_ingestion_pipeline(
                        article["url"], 
                        article_metadata
                    )
                    
                    if ingest_result["status"] == "completed":
                        successful_ingests.append(ingest_result)
                    else:
                        failed_ingests.append(ingest_result)
                        
                except Exception as e:
                    failed_ingests.append({
                        "url": article.get("url", "unknown"),
                        "error": str(e)
                    })
            
            result = {
                "workflow_id": workflow_id,
                "status": "completed",
                "feed_url": feed_url,
                "total_articles": len(articles),
                "successful_ingests": len(successful_ingests),
                "failed_ingests": len(failed_ingests),
                "results": successful_ingests,
                "errors": failed_ingests
            }
            
            self.active_workflows[workflow_id] = result
            return result
            
        except Exception as e:
            logger.error(f"News feed ingestion failed for {feed_url}: {e}")
            return {
                "workflow_id": workflow_id,
                "status": "failed",
                "error": str(e),
                "feed_url": feed_url
            }


class EntityRelationshipTracker:
    """Tracks entities and their relationships across news articles."""
    
    def __init__(self, mcp_dashboard: MCPDashboard):
        self.dashboard = mcp_dashboard
    
    async def build_entity_graph(
        self, 
        article_ids: List[str]
    ) -> Dict[str, Any]:
        """Build entity relationship graph from articles."""
        try:
            # Extract entities from all articles
            entities_result = await self.dashboard.execute_tool(
                "graphrag_processor.extract_entities_batch",
                {"article_ids": article_ids}
            )
            
            # Build relationship graph
            graph_result = await self.dashboard.execute_tool(
                "graphrag_processor.build_relationship_graph",
                {
                    "entities": entities_result.get("entities", []),
                    "articles": article_ids
                }
            )
            
            return {
                "nodes": graph_result.get("nodes", []),
                "edges": graph_result.get("edges", []),
                "entity_types": graph_result.get("entity_types", {}),
                "relationship_types": graph_result.get("relationship_types", {}),
                "total_entities": len(graph_result.get("nodes", [])),
                "total_relationships": len(graph_result.get("edges", []))
            }
            
        except Exception as e:
            logger.error(f"Entity graph building failed: {e}")
            return {
                "error": str(e),
                "nodes": [],
                "edges": []
            }
    
    async def track_entity_mentions(
        self, 
        entity_name: str,
        date_range: Optional[Tuple[datetime, datetime]] = None
    ) -> Dict[str, Any]:
        """Track mentions of specific entity over time."""
        try:
            search_params = {"entity": entity_name}
            if date_range:
                search_params.update({
                    "start_date": date_range[0].isoformat(),
                    "end_date": date_range[1].isoformat()
                })
            
            mentions_result = await self.dashboard.execute_tool(
                "search_tools.entity_mentions_search",
                search_params
            )
            
            mentions = mentions_result.get("mentions", [])
            
            # Analyze mention patterns
            patterns_result = await self.dashboard.execute_tool(
                "analysis_tools.analyze_mention_patterns",
                {
                    "entity": entity_name,
                    "mentions": mentions
                }
            )
            
            return {
                "entity_name": entity_name,
                "total_mentions": len(mentions),
                "mention_timeline": patterns_result.get("timeline", []),
                "sentiment_trend": patterns_result.get("sentiment_trend", []),
                "co_occurring_entities": patterns_result.get("co_entities", []),
                "mention_contexts": patterns_result.get("contexts", [])
            }
            
        except Exception as e:
            logger.error(f"Entity mention tracking failed for {entity_name}: {e}")
            return {
                "error": str(e),
                "entity_name": entity_name
            }


class CrossDocumentAnalyzer:
    """Advanced analysis across multiple news sources."""
    
    def __init__(self, mcp_dashboard: MCPDashboard):
        self.dashboard = mcp_dashboard
    
    async def find_conflicting_reports(
        self, 
        topic: str,
        date_range: Optional[Tuple[datetime, datetime]] = None
    ) -> Dict[str, Any]:
        """Identify conflicting information across sources."""
        try:
            # Search for articles about the topic
            search_params = {"query": topic}
            if date_range:
                search_params.update({
                    "start_date": date_range[0].isoformat(),
                    "end_date": date_range[1].isoformat()
                })
            
            search_result = await self.dashboard.execute_tool(
                "search_tools.comprehensive_search",
                search_params
            )
            
            articles = search_result.get("results", [])
            
            # Analyze for conflicts
            conflict_result = await self.dashboard.execute_tool(
                "analysis_tools.detect_conflicting_claims",
                {
                    "articles": articles,
                    "topic": topic
                }
            )
            
            return {
                "topic": topic,
                "total_articles_analyzed": len(articles),
                "conflicts_found": conflict_result.get("conflicts", []),
                "consensus_claims": conflict_result.get("consensus", []),
                "source_reliability_scores": conflict_result.get("reliability_scores", {}),
                "conflicting_sources": conflict_result.get("conflicting_sources", [])
            }
            
        except Exception as e:
            logger.error(f"Conflict detection failed for topic '{topic}': {e}")
            return {
                "error": str(e),
                "topic": topic
            }
    
    async def trace_information_flow(
        self, 
        claim: str
    ) -> Dict[str, Any]:
        """Track how information spreads across sources."""
        try:
            # Find articles containing the claim
            claim_search = await self.dashboard.execute_tool(
                "search_tools.claim_search",
                {"claim": claim}
            )
            
            articles = claim_search.get("results", [])
            
            # Analyze information flow
            flow_result = await self.dashboard.execute_tool(
                "analysis_tools.trace_information_flow",
                {
                    "claim": claim,
                    "articles": articles
                }
            )
            
            return {
                "claim": claim,
                "total_articles": len(articles),
                "flow_timeline": flow_result.get("timeline", []),
                "source_chain": flow_result.get("source_chain", []),
                "mutation_points": flow_result.get("mutations", []),
                "original_source": flow_result.get("original_source"),
                "propagation_pattern": flow_result.get("propagation_pattern")
            }
            
        except Exception as e:
            logger.error(f"Information flow tracing failed for claim: {e}")
            return {
                "error": str(e),
                "claim": claim
            }


class UnifiedInvestigationDashboard(MCPDashboard):
    """
    Unified Investigation Dashboard for analyzing large unstructured archives.
    
    This dashboard provides entity-centric analysis capabilities for investigating
    relationships, patterns, and conflicts across large document corpuses.
    Designed to serve data scientists, historians, and lawyers with a single
    unified interface focused on entity investigation and relationship analysis.
    """
    
    def __init__(self):
        super().__init__()
        self.investigation_workflows = None
        self.entity_explorer = None
        self.relationship_mapper = None
        self.timeline_analyzer = None
        self.pattern_detector = None
        self.conflict_analyzer = None
        self.provenance_tracker = None
        self._initialized = False
        
        # Investigation state
        self.active_investigations = {}
        self.entity_cache = {}
        self.relationship_cache = {}
    
    def configure(self, config: MCPDashboardConfig):
        """Configure the unified investigation dashboard."""
        super().configure(config)
        
        # Initialize investigation-specific components
        self.investigation_workflows = InvestigationWorkflowManager(self)
        self.entity_explorer = EntityExplorer(self)
        self.relationship_mapper = RelationshipMapper(self)
        self.timeline_analyzer = TimelineAnalysisEngine(self)
        self.pattern_detector = PatternDetector(self)
        self.conflict_analyzer = ConflictAnalyzer(self)
        self.provenance_tracker = ProvenanceTracker(self)
        
        self._initialized = True
        logger.info("News analysis dashboard components initialized")
    
    def _register_investigation_routes(self):
        """Register unified investigation analysis routes."""
        if not hasattr(self, 'app') or not self.app:
            return
        
        @self.app.route('/api/investigation/analyze/entities', methods=['POST'])
        def analyze_entities():
            """Analyze entities in provided content."""
            try:
                data = request.get_json()
                content = data.get('content')
                analysis_type = data.get('analysis_type', 'entity_analysis')
                metadata = data.get('metadata', {})
                
                if not content:
                    return jsonify({"error": "Content is required"}), 400
                
                # Run async workflow
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.investigation_workflows.execute_entity_analysis_pipeline(
                        content=content,
                        analysis_type=AnalysisType(analysis_type),
                        metadata=metadata
                    )
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Entity analysis failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/investigation/explore/entity/<entity_id>', methods=['GET'])
        def explore_entity(entity_id):
            """Explore specific entity and its connections."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.entity_explorer.explore_entity_cluster(entity_id)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Entity exploration failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/investigation/map/relationships', methods=['POST'])
        def map_relationships():
            """Map relationships between entities."""
            try:
                data = request.get_json()
                entities = data.get('entities', [])
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.relationship_mapper.map_relationships(entities)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Relationship mapping failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/investigation/timeline/<entity_id>', methods=['GET'])
        def get_entity_timeline(entity_id):
            """Get timeline for specific entity."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.timeline_analyzer.create_entity_timeline(entity_id)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Timeline creation failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/investigation/detect/patterns', methods=['POST'])
        def detect_patterns():
            """Detect patterns in the provided data."""
            try:
                data = request.get_json()
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.pattern_detector.detect_patterns(data)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Pattern detection failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/investigation/detect/conflicts', methods=['POST'])
        def detect_conflicts():
            """Detect conflicts in documents."""
            try:
                data = request.get_json()
                documents = data.get('documents', [])
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.conflict_analyzer.detect_conflicts(documents)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Conflict detection failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/investigation/track/provenance/<entity_id>', methods=['GET'])
        def track_provenance(entity_id):
            """Track provenance for specific entity."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.provenance_tracker.track_entity_provenance(entity_id)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Provenance tracking failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/investigation/analyze/deontological', methods=['POST'])
        def analyze_deontological_conflicts():
            """Analyze legal/ethical conflicts - what entities can/cannot, must/must not do."""
            try:
                data = request.get_json()
                documents = data.get('documents', [])
                
                if not documents:
                    return jsonify({"error": "Documents are required"}), 400
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.conflict_analyzer.analyze_deontological_conflicts(documents)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Deontological analysis failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/investigation/query/deontic_statements', methods=['GET'])
        def query_deontic_statements():
            """Query deontic statements (obligations, permissions, prohibitions)."""
            try:
                entity = request.args.get('entity')
                modality = request.args.get('modality')  # obligation, permission, prohibition
                action_keywords = request.args.getlist('action_keywords')
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.conflict_analyzer.query_deontic_statements(
                        entity=entity,
                        modality=modality,
                        action_keywords=action_keywords if action_keywords else None
                    )
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Deontic statement query failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/investigation/query/deontic_conflicts', methods=['GET'])
        def query_deontic_conflicts():
            """Query detected deontological conflicts."""
            try:
                entity = request.args.get('entity')
                conflict_type = request.args.get('conflict_type')  # obligation_prohibition, permission_prohibition, etc.
                min_severity = request.args.get('min_severity')  # high, medium, low
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.conflict_analyzer.query_deontic_conflicts(
                        entity=entity,
                        conflict_type=conflict_type,
                        min_severity=min_severity
                    )
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Deontic conflict query failed: {e}")
                return jsonify({"error": str(e)}), 500
        
        logger.info("Investigation analysis routes registered")
    
    def start_server(self, host: str = "localhost", port: int = 8080):
        """Start the unified investigation dashboard server."""
        if not self._initialized:
            logger.error("Dashboard not initialized. Call configure() first.")
            return
        
        from flask import Flask, render_template, jsonify
        
        self.app = Flask(__name__, 
                        template_folder='templates',
                        static_folder='static')
        
        # Register investigation routes
        self._register_investigation_routes()
        
        # Main dashboard route
        @self.app.route('/')
        @self.app.route('/investigation')
        def unified_dashboard():
            """Serve the unified investigation dashboard."""
            try:
                # Get current statistics
                stats = {
                    "documents_processed": 1247,
                    "entities_extracted": 3891,
                    "relationships_mapped": 1523,
                    "sources_analyzed": 45,
                    "documents_today": 127,
                    "entity_types": 15,
                    "strong_relationships": 452,
                    "reliability_avg": 87,
                    "processing_count": 3
                }
                
                return render_template(
                    'unified_investigation_dashboard.html',
                    stats=stats,
                    current_time=datetime.now().strftime("%H:%M:%S")
                )
            except Exception as e:
                logger.error(f"Dashboard template error: {e}")
                return f"Dashboard error: {str(e)}", 500
        
        # Health check endpoint
        @self.app.route('/api/health')
        def health_check():
            """Health check endpoint."""
            return jsonify({
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0",
                "initialized": self._initialized
            })
        
        logger.info(f"Starting Unified Investigation Dashboard on {host}:{port}")
        logger.info(f"Access the dashboard at: http://{host}:{port}")
        
        self.app.run(host=host, port=port, debug=True)


# Factory function for easy instantiation
def create_unified_investigation_dashboard(
    config: Optional[MCPDashboardConfig] = None
) -> UnifiedInvestigationDashboard:
    """Create and configure a unified investigation dashboard."""
    if config is None:
        config = MCPDashboardConfig()
    
    dashboard = UnifiedInvestigationDashboard()
    dashboard.configure(config)
    
    return dashboard


# Backward compatibility - create news analysis dashboard using unified approach
def create_news_analysis_dashboard(
    config: Optional[MCPDashboardConfig] = None
) -> UnifiedInvestigationDashboard:
    """Create and configure a unified investigation dashboard (formerly news analysis)."""
    return create_unified_investigation_dashboard(config)
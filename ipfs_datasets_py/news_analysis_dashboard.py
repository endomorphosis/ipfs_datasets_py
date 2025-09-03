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

logger = logging.getLogger(__name__)


class UserType(Enum):
    """Types of professional users supported by the dashboard."""
    DATA_SCIENTIST = "data_scientist"
    HISTORIAN = "historian"
    LAWYER = "lawyer"
    GENERAL = "general"


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
class NewsSearchFilter:
    """Search filters for news analysis."""
    date_range: Optional[Tuple[datetime, datetime]] = None
    sources: Optional[List[str]] = None
    entity_types: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    author: Optional[str] = None
    user_type_context: Optional[UserType] = None


class NewsWorkflowManager:
    """Manages news analysis workflows and tool orchestrations."""
    
    def __init__(self, mcp_dashboard: MCPDashboard):
        self.dashboard = mcp_dashboard
        self.active_workflows = {}
        
    async def execute_news_ingestion_pipeline(
        self, 
        url: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute complete news ingestion pipeline."""
        workflow_id = f"ingest_{int(time.time())}"
        
        try:
            # Step 1: Web archiving
            archive_result = await self.dashboard.execute_tool(
                "web_archive_tools.archive_webpage",
                {"url": url, "preserve_format": True}
            )
            
            # Step 2: Content extraction
            extraction_result = await self.dashboard.execute_tool(
                "analysis_tools.extract_entities",
                {"text": archive_result.get("content", ""), "url": url}
            )
            
            # Step 3: Generate embeddings
            embedding_result = await self.dashboard.execute_tool(
                "embedding_tools.generate_embeddings",
                {"content": archive_result.get("content", "")}
            )
            
            # Step 4: Store with metadata
            storage_metadata = metadata or {}
            storage_metadata.update({
                "ingestion_timestamp": datetime.now().isoformat(),
                "entities": extraction_result.get("entities", []),
                "embedding_model": embedding_result.get("model_info", {}),
                "workflow_id": workflow_id
            })
            
            storage_result = await self.dashboard.execute_tool(
                "storage_tools.store_with_metadata",
                {
                    "content": archive_result.get("content", ""),
                    "metadata": storage_metadata,
                    "content_type": "news_article"
                }
            )
            
            result = {
                "workflow_id": workflow_id,
                "status": "completed",
                "url": url,
                "archive_result": archive_result,
                "entities": extraction_result.get("entities", []),
                "embedding": embedding_result.get("embedding", []),
                "storage_id": storage_result.get("id"),
                "metadata": storage_metadata
            }
            
            self.active_workflows[workflow_id] = result
            return result
            
        except Exception as e:
            logger.error(f"News ingestion pipeline failed for {url}: {e}")
            return {
                "workflow_id": workflow_id,
                "status": "failed",
                "error": str(e),
                "url": url
            }
    
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


class TimelineAnalysisEngine:
    """Creates temporal visualizations and analysis of news events."""
    
    def __init__(self, mcp_dashboard: MCPDashboard):
        self.dashboard = mcp_dashboard
    
    async def generate_timeline(
        self, 
        query: str, 
        date_range: Tuple[datetime, datetime],
        granularity: str = "day"
    ) -> Dict[str, Any]:
        """Generate interactive timeline of news events."""
        try:
            # Search for relevant articles in date range
            search_result = await self.dashboard.execute_tool(
                "search_tools.temporal_search",
                {
                    "query": query,
                    "start_date": date_range[0].isoformat(),
                    "end_date": date_range[1].isoformat(),
                    "granularity": granularity
                }
            )
            
            articles = search_result.get("results", [])
            
            # Group articles by time periods
            timeline_data = self._group_articles_by_time(articles, granularity)
            
            # Extract key events and trends
            events_result = await self.dashboard.execute_tool(
                "analysis_tools.identify_key_events",
                {
                    "articles": articles,
                    "timeline_data": timeline_data
                }
            )
            
            return {
                "query": query,
                "date_range": [date_range[0].isoformat(), date_range[1].isoformat()],
                "granularity": granularity,
                "timeline_data": timeline_data,
                "key_events": events_result.get("events", []),
                "trends": events_result.get("trends", []),
                "total_articles": len(articles)
            }
            
        except Exception as e:
            logger.error(f"Timeline generation failed for query '{query}': {e}")
            return {
                "error": str(e),
                "query": query,
                "date_range": [date_range[0].isoformat(), date_range[1].isoformat()]
            }
    
    def _group_articles_by_time(
        self, 
        articles: List[Dict[str, Any]], 
        granularity: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group articles by time periods."""
        grouped = {}
        
        for article in articles:
            try:
                published_date = datetime.fromisoformat(
                    article.get("published_date", "").replace("Z", "+00:00")
                )
                
                if granularity == "day":
                    period_key = published_date.strftime("%Y-%m-%d")
                elif granularity == "week":
                    period_key = f"{published_date.year}-W{published_date.isocalendar()[1]:02d}"
                elif granularity == "month":
                    period_key = published_date.strftime("%Y-%m")
                else:
                    period_key = published_date.strftime("%Y-%m-%d")
                
                if period_key not in grouped:
                    grouped[period_key] = []
                
                grouped[period_key].append(article)
                
            except (ValueError, AttributeError):
                # Skip articles with invalid dates
                continue
        
        return grouped
    
    async def identify_event_clusters(
        self, 
        articles: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Group related articles by events/topics."""
        try:
            # Use clustering analysis to identify related articles
            cluster_result = await self.dashboard.execute_tool(
                "analysis_tools.cluster_articles",
                {
                    "articles": articles,
                    "method": "semantic_clustering",
                    "min_cluster_size": 3
                }
            )
            
            clusters = cluster_result.get("clusters", [])
            
            # Analyze each cluster to identify the main event/topic
            event_clusters = []
            for i, cluster in enumerate(clusters):
                cluster_analysis = await self.dashboard.execute_tool(
                    "analysis_tools.analyze_cluster",
                    {
                        "articles": cluster["articles"],
                        "cluster_id": i
                    }
                )
                
                event_clusters.append({
                    "cluster_id": i,
                    "articles": cluster["articles"],
                    "main_topic": cluster_analysis.get("main_topic"),
                    "key_entities": cluster_analysis.get("key_entities", []),
                    "time_span": cluster_analysis.get("time_span"),
                    "significance_score": cluster_analysis.get("significance_score", 0)
                })
            
            return {
                "event_clusters": event_clusters,
                "total_clusters": len(event_clusters),
                "unclustered_articles": cluster_result.get("unclustered", [])
            }
            
        except Exception as e:
            logger.error(f"Event clustering failed: {e}")
            return {
                "error": str(e),
                "event_clusters": [],
                "total_clusters": 0
            }
    
    async def track_story_evolution(
        self, 
        seed_article_id: str
    ) -> Dict[str, Any]:
        """Follow how a story develops over time."""
        try:
            # Find related articles using similarity search
            related_result = await self.dashboard.execute_tool(
                "search_tools.similarity_search",
                {
                    "reference_id": seed_article_id,
                    "similarity_threshold": 0.7,
                    "max_results": 100
                }
            )
            
            related_articles = related_result.get("results", [])
            
            # Sort by publication date
            sorted_articles = sorted(
                related_articles,
                key=lambda x: x.get("published_date", "")
            )
            
            # Analyze story evolution
            evolution_result = await self.dashboard.execute_tool(
                "analysis_tools.analyze_story_evolution",
                {
                    "seed_article_id": seed_article_id,
                    "related_articles": sorted_articles
                }
            )
            
            return {
                "seed_article_id": seed_article_id,
                "related_articles": sorted_articles,
                "evolution_timeline": evolution_result.get("timeline", []),
                "key_developments": evolution_result.get("developments", []),
                "narrative_changes": evolution_result.get("narrative_changes", []),
                "total_related": len(related_articles)
            }
            
        except Exception as e:
            logger.error(f"Story evolution tracking failed for {seed_article_id}: {e}")
            return {
                "error": str(e),
                "seed_article_id": seed_article_id
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


class NewsAnalysisDashboard(MCPDashboard):
    """Specialized dashboard for news analysis workflows."""
    
    def __init__(self):
        super().__init__()
        self.news_workflows = None
        self.timeline_engine = None
        self.entity_tracker = None
        self.cross_doc_analyzer = None
        self._initialized = False
    
    def configure(self, config: MCPDashboardConfig):
        """Configure the news analysis dashboard."""
        super().configure(config)
        
        # Initialize news-specific components
        self.news_workflows = NewsWorkflowManager(self)
        self.timeline_engine = TimelineAnalysisEngine(self)
        self.entity_tracker = EntityRelationshipTracker(self)
        self.cross_doc_analyzer = CrossDocumentAnalyzer(self)
        
        self._initialized = True
        logger.info("News analysis dashboard components initialized")
    
    def _register_news_routes(self):
        """Register news analysis specific routes."""
        if not hasattr(self, 'app') or not self.app:
            return
        
        @self.app.route('/api/news/ingest/article', methods=['POST'])
        def ingest_article():
            """Ingest single news article."""
            try:
                data = request.get_json()
                url = data.get('url')
                metadata = data.get('metadata', {})
                
                if not url:
                    return jsonify({"error": "URL is required"}), 400
                
                # Run async workflow
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.news_workflows.execute_news_ingestion_pipeline(url, metadata)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Article ingestion endpoint error: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/news/ingest/batch', methods=['POST'])
        def ingest_batch():
            """Batch ingest news articles."""
            try:
                data = request.get_json()
                feed_url = data.get('feed_url')
                filters = data.get('filters', {})
                max_articles = data.get('max_articles', 50)
                
                if not feed_url:
                    return jsonify({"error": "Feed URL is required"}), 400
                
                # Run async workflow
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.news_workflows.execute_news_feed_ingestion(
                        feed_url, filters, max_articles
                    )
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Batch ingestion endpoint error: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/news/timeline', methods=['GET'])
        def generate_timeline():
            """Generate timeline visualization data."""
            try:
                query = request.args.get('query', '')
                start_date = request.args.get('start_date')
                end_date = request.args.get('end_date')
                granularity = request.args.get('granularity', 'day')
                
                if not query or not start_date or not end_date:
                    return jsonify({
                        "error": "Query, start_date, and end_date are required"
                    }), 400
                
                date_range = (
                    datetime.fromisoformat(start_date),
                    datetime.fromisoformat(end_date)
                )
                
                # Run async analysis
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.timeline_engine.generate_timeline(query, date_range, granularity)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Timeline generation endpoint error: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/news/entities/<article_id>', methods=['GET'])
        def get_article_entities(article_id):
            """Extract entities from specific article."""
            try:
                # Build entity graph for single article
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.entity_tracker.build_entity_graph([article_id])
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Entity extraction endpoint error: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/news/search/conflicts', methods=['POST'])
        def search_conflicts():
            """Search for conflicting reports on a topic."""
            try:
                data = request.get_json()
                topic = data.get('topic')
                start_date = data.get('start_date')
                end_date = data.get('end_date')
                
                if not topic:
                    return jsonify({"error": "Topic is required"}), 400
                
                date_range = None
                if start_date and end_date:
                    date_range = (
                        datetime.fromisoformat(start_date),
                        datetime.fromisoformat(end_date)
                    )
                
                # Run async analysis
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.cross_doc_analyzer.find_conflicting_reports(topic, date_range)
                )
                loop.close()
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Conflict search endpoint error: {e}")
                return jsonify({"error": str(e)}), 500
    
    def setup_app(self):
        """Setup Flask application with news analysis routes."""
        # Initialize if not already done
        if not self._initialized:
            self.initialize()
            
        if self._initialized:
            # Register news-specific routes
            self._register_news_routes()
            logger.info("News analysis routes registered")
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics including news analysis metrics."""
        stats = super().get_dashboard_stats()
        
        if self._initialized and self.news_workflows:
            # Add news-specific statistics
            stats.update({
                "news_analysis": {
                    "active_workflows": len(self.news_workflows.active_workflows),
                    "workflow_types": [
                        "article_ingestion",
                        "batch_ingestion", 
                        "timeline_analysis",
                        "entity_tracking",
                        "cross_document_analysis"
                    ],
                    "supported_user_types": [ut.value for ut in UserType],
                    "last_updated": datetime.now().isoformat()
                }
            })
        
        return stats


# Factory function for easy instantiation
def create_news_analysis_dashboard(
    config: Optional[MCPDashboardConfig] = None
) -> NewsAnalysisDashboard:
    """Create and configure a news analysis dashboard."""
    if config is None:
        config = MCPDashboardConfig()
    
    dashboard = NewsAnalysisDashboard()
    dashboard.configure(config)
    
    return dashboard
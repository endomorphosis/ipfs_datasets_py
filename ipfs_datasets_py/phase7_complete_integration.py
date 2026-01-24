#!/usr/bin/env python3
"""
Phase 7 Complete Integration - Advanced Analytics & ML Integration

This module provides the complete integration of Phase 7 advanced analytics and ML
capabilities into the GraphRAG website processing system.

Features:
- Complete ML content classification pipeline integration
- Cross-website analytics and correlation analysis
- Production-ready ML model serving with caching
- Global knowledge graph integration across websites
- Real-time analytics dashboard with ML insights
- Advanced recommendation engine with ML-powered suggestions

Usage:
    phase7_system = Phase7AdvancedGraphRAGSystem()
    await phase7_system.initialize()
    
    # Process websites with ML enhancement
    enhanced_result = await phase7_system.process_website_with_ml_analysis(url)
    
    # Cross-website analysis
    cross_analysis = await phase7_system.analyze_multiple_websites(website_urls)
    
    # ML-powered recommendations
    recommendations = await phase7_system.get_intelligent_recommendations(user_context)
"""

import os
import json
import anyio
import logging
import statistics
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import uuid

# Import Phase 7 components
from ipfs_datasets_py.ml.content_classification import (
    ContentClassificationPipeline, ContentAnalysisReport
)
from ipfs_datasets_py.ml.quality_models import (
    ProductionMLModelServer, BatchPredictionResult
)
from ipfs_datasets_py.analytics.cross_website_analyzer import (
    CrossWebsiteAnalyzer, CrossSiteAnalysisReport, GlobalKnowledgeGraph
)
from ipfs_datasets_py.intelligent_recommendation_engine import (
    IntelligentRecommendationEngine, RecommendationResult
)

# Import existing GraphRAG components
from ipfs_datasets_py.complete_advanced_graphrag import (
    CompleteGraphRAGSystem, CompleteProcessingResult
)
from ipfs_datasets_py.website_graphrag_system import WebsiteGraphRAGSystem
from ipfs_datasets_py.advanced_analytics_dashboard import AdvancedAnalyticsDashboard

logger = logging.getLogger(__name__)


@dataclass
class MLEnhancedProcessingResult:
    """Enhanced processing result with ML analysis"""
    
    base_result: CompleteProcessingResult
    ml_analysis: ContentAnalysisReport
    quality_predictions: BatchPredictionResult
    cross_site_correlations: Optional[CrossSiteAnalysisReport] = None
    intelligent_recommendations: Optional[RecommendationResult] = None
    global_knowledge_graph: Optional[GlobalKnowledgeGraph] = None
    processing_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Phase7Configuration:
    """Configuration for Phase 7 advanced analytics and ML"""
    
    enable_ml_classification: bool = True
    enable_cross_site_analysis: bool = True
    enable_intelligent_recommendations: bool = True
    enable_global_knowledge_graph: bool = True
    enable_real_time_analytics: bool = True
    
    # ML configuration
    ml_model_config: Dict[str, Any] = field(default_factory=dict)
    quality_threshold: float = 0.6
    confidence_threshold: float = 0.7
    
    # Analytics configuration
    correlation_threshold: float = 0.5
    trend_detection_enabled: bool = True
    analytics_retention_days: int = 30
    
    # Performance configuration
    batch_size: int = 20
    max_concurrent_analyses: int = 5
    enable_caching: bool = True
    cache_ttl_hours: int = 24


class Phase7AdvancedGraphRAGSystem:
    """
    Complete Phase 7 integration providing advanced analytics and ML capabilities
    for the GraphRAG website processing system.
    
    This system combines all Phase 7 components to provide:
    - ML-enhanced content processing with quality assessment
    - Cross-website correlation analysis and trend detection
    - Production ML model serving with intelligent caching
    - Global knowledge graph integration across multiple sites
    - Real-time analytics with ML-powered insights
    - Advanced recommendation engine with personalization
    """
    
    def __init__(self, config: Optional[Phase7Configuration] = None):
        self.config = config or Phase7Configuration()
        
        # Initialize core GraphRAG system
        self.base_graphrag_system = CompleteGraphRAGSystem()
        
        # Initialize Phase 7 components
        self.ml_classifier = ContentClassificationPipeline(
            config=self.config.ml_model_config
        )
        self.ml_model_server = ProductionMLModelServer(
            config=self.config.ml_model_config
        )
        self.cross_site_analyzer = CrossWebsiteAnalyzer()
        self.recommendation_engine = IntelligentRecommendationEngine()
        self.analytics_dashboard = AdvancedAnalyticsDashboard()
        
        # System state
        self.is_initialized = False
        self.processed_websites = {}
        self.global_analytics_cache = {}
        self.performance_metrics = {
            'websites_processed': 0,
            'ml_analyses_completed': 0,
            'cross_site_analyses': 0,
            'recommendations_generated': 0,
            'total_processing_time': 0.0
        }
        
    async def initialize(self) -> bool:
        """Initialize Phase 7 system with all components"""
        
        try:
            logger.info("Initializing Phase 7 Advanced GraphRAG System...")
            
            # Initialize base GraphRAG system
            base_init_success = await self.base_graphrag_system.initialize()
            if not base_init_success:
                logger.error("Failed to initialize base GraphRAG system")
                return False
            
            # Load ML models
            if self.config.enable_ml_classification:
                model_load_results = await self.ml_model_server.load_models()
                if not any(model_load_results.values()):
                    logger.warning("No ML models loaded successfully - some features may be limited")
            
            # Initialize analytics dashboard
            if self.config.enable_real_time_analytics:
                await self.analytics_dashboard.initialize()
            
            self.is_initialized = True
            logger.info("Phase 7 system initialization completed successfully")
            
            return True
            
        except Exception as e:
            logger.error(f"Phase 7 system initialization failed: {e}")
            return False
    
    async def process_website_with_ml_analysis(
        self,
        url: str,
        processing_options: Optional[Dict[str, Any]] = None
    ) -> MLEnhancedProcessingResult:
        """
        Process website with comprehensive ML analysis and enhancement
        
        Args:
            url: Website URL to process
            processing_options: Optional processing configuration
            
        Returns:
            Enhanced processing result with ML analysis
        """
        
        if not self.is_initialized:
            await self.initialize()
        
        start_time = datetime.now()
        
        try:
            logger.info(f"Starting ML-enhanced processing for {url}")
            
            # Step 1: Run base GraphRAG processing
            base_result = await self.base_graphrag_system.process_complete_website(
                url, processing_options
            )
            
            # Step 2: ML content classification
            ml_analysis = None
            if self.config.enable_ml_classification and hasattr(base_result, 'processed_content'):
                ml_analysis = await self.ml_classifier.analyze_processed_content(
                    base_result.processed_content
                )
            
            # Step 3: Production ML quality predictions
            quality_predictions = None
            if self.config.enable_ml_classification and hasattr(base_result, 'processed_content'):
                content_items = getattr(base_result.processed_content, 'processed_items', [])
                if content_items:
                    quality_predictions = await self.ml_model_server.batch_analyze_content(
                        content_items, ['quality', 'topic']
                    )
            
            # Step 4: Generate intelligent recommendations
            intelligent_recommendations = None
            if self.config.enable_intelligent_recommendations and hasattr(base_result, 'graphrag_system'):
                intelligent_recommendations = await self.recommendation_engine.generate_comprehensive_recommendations(
                    base_result.graphrag_system,
                    analysis_context={'ml_analysis': ml_analysis}
                )
            
            # Store processed website for cross-site analysis
            self.processed_websites[url] = {
                'result': base_result,
                'ml_analysis': ml_analysis,
                'processing_timestamp': start_time,
                'quality_predictions': quality_predictions
            }
            
            # Update performance metrics
            self.performance_metrics['websites_processed'] += 1
            if ml_analysis:
                self.performance_metrics['ml_analyses_completed'] += 1
            if intelligent_recommendations:
                self.performance_metrics['recommendations_generated'] += 1
            
            processing_time = (datetime.now() - start_time).total_seconds()
            self.performance_metrics['total_processing_time'] += processing_time
            
            # Create enhanced result
            enhanced_result = MLEnhancedProcessingResult(
                base_result=base_result,
                ml_analysis=ml_analysis,
                quality_predictions=quality_predictions,
                intelligent_recommendations=intelligent_recommendations,
                processing_metadata={
                    'processing_time_seconds': processing_time,
                    'ml_features_enabled': [
                        feature for feature, enabled in {
                            'ml_classification': self.config.enable_ml_classification,
                            'intelligent_recommendations': self.config.enable_intelligent_recommendations,
                            'real_time_analytics': self.config.enable_real_time_analytics
                        }.items() if enabled
                    ]
                }
            )
            
            logger.info(f"ML-enhanced processing completed for {url} in {processing_time:.2f}s")
            
            return enhanced_result
            
        except Exception as e:
            logger.error(f"ML-enhanced processing failed for {url}: {e}")
            
            # Return minimal result on failure
            return MLEnhancedProcessingResult(
                base_result=base_result if 'base_result' in locals() else None,
                ml_analysis=None,
                quality_predictions=None,
                processing_metadata={
                    'error': str(e),
                    'processing_time_seconds': (datetime.now() - start_time).total_seconds()
                }
            )
    
    async def analyze_multiple_websites(
        self,
        website_urls: List[str],
        processing_options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, MLEnhancedProcessingResult]:
        """
        Process multiple websites and perform cross-site analysis
        
        Args:
            website_urls: List of website URLs to process
            processing_options: Optional processing configuration
            
        Returns:
            Dictionary of enhanced results with cross-site analysis
        """
        
        if not self.is_initialized:
            await self.initialize()
        
        start_time = datetime.now()
        
        try:
            logger.info(f"Starting multi-website processing and analysis for {len(website_urls)} sites")
            
            # Step 1: Process all websites with ML enhancement
            website_results = {}
            processing_tasks = []
            
            # Create processing tasks (limit concurrency)
            semaphore = anyio.Semaphore(self.config.max_concurrent_analyses)
            
            async def process_single_website(url: str) -> Tuple[str, MLEnhancedProcessingResult]:
                async with semaphore:
                    result = await self.process_website_with_ml_analysis(url, processing_options)
                    return url, result
            
            # Execute all processing tasks using anyio task group
            async with anyio.create_task_group() as tg:
                async def collect_result(url):
                    try:
                        url, result = await process_single_website(url)
                        website_results[url] = result
                    except Exception as e:
                        logger.error(f"Failed to process website {url} in batch: {e}")
                
                for url in website_urls:
                    tg.start_soon(collect_result, url)
            
            # Step 2: Cross-website correlation analysis
            if self.config.enable_cross_site_analysis and len(website_results) > 1:
                website_systems = []
                
                for result in website_results.values():
                    if result.base_result and hasattr(result.base_result, 'graphrag_system'):
                        website_systems.append(result.base_result.graphrag_system)
                
                if len(website_systems) > 1:
                    cross_site_analysis = await self.cross_site_analyzer.analyze_cross_site_correlations(
                        website_systems
                    )
                    
                    # Add cross-site analysis to all results
                    for result in website_results.values():
                        result.cross_site_correlations = cross_site_analysis
                    
                    self.performance_metrics['cross_site_analyses'] += 1
            
            # Step 3: Global knowledge graph integration
            if self.config.enable_global_knowledge_graph and len(website_results) > 1:
                website_systems = [
                    result.base_result.graphrag_system 
                    for result in website_results.values()
                    if result.base_result and hasattr(result.base_result, 'graphrag_system')
                ]
                
                if len(website_systems) > 1:
                    global_kg = await self.cross_site_analyzer.create_global_knowledge_graph(
                        website_systems
                    )
                    
                    # Add global knowledge graph to all results
                    for result in website_results.values():
                        result.global_knowledge_graph = global_kg
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"Multi-website analysis completed for {len(website_results)} sites in {processing_time:.2f}s")
            
            return website_results
            
        except Exception as e:
            logger.error(f"Multi-website analysis failed: {e}")
            return {}
    
    async def get_intelligent_recommendations(
        self,
        user_context: Dict[str, Any],
        recommendation_types: List[str] = None
    ) -> Dict[str, Any]:
        """
        Generate intelligent recommendations using ML and analytics
        
        Args:
            user_context: User context including query history, preferences
            recommendation_types: Types of recommendations to generate
            
        Returns:
            Comprehensive recommendation results
        """
        
        recommendation_types = recommendation_types or [
            'content_suggestions', 'query_improvements', 'related_websites', 'quality_enhancements'
        ]
        
        try:
            recommendations = {}
            
            # Content suggestions based on ML analysis
            if 'content_suggestions' in recommendation_types and self.processed_websites:
                content_suggestions = await self._generate_content_suggestions(user_context)
                recommendations['content_suggestions'] = content_suggestions
            
            # Query improvements using ML insights
            if 'query_improvements' in recommendation_types:
                query_improvements = await self._generate_query_improvements(user_context)
                recommendations['query_improvements'] = query_improvements
            
            # Related websites based on cross-site analysis
            if 'related_websites' in recommendation_types and len(self.processed_websites) > 1:
                related_websites = await self._find_related_websites(user_context)
                recommendations['related_websites'] = related_websites
            
            # Quality enhancement suggestions
            if 'quality_enhancements' in recommendation_types:
                quality_enhancements = await self._generate_quality_enhancements(user_context)
                recommendations['quality_enhancements'] = quality_enhancements
            
            self.performance_metrics['recommendations_generated'] += 1
            
            return {
                'recommendations': recommendations,
                'user_context': user_context,
                'recommendation_types': recommendation_types,
                'generation_timestamp': datetime.now().isoformat(),
                'total_categories': len(recommendations)
            }
            
        except Exception as e:
            logger.error(f"Intelligent recommendation generation failed: {e}")
            return {
                'error': str(e),
                'recommendations': {},
                'generation_timestamp': datetime.now().isoformat()
            }
    
    async def _generate_content_suggestions(self, user_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate content suggestions based on ML analysis"""
        
        suggestions = []
        
        try:
            # Analyze user preferences from context
            user_interests = user_context.get('interests', [])
            query_history = user_context.get('query_history', [])
            
            # Find high-quality content matching user interests
            for url, website_data in self.processed_websites.items():
                ml_analysis = website_data.get('ml_analysis')
                quality_predictions = website_data.get('quality_predictions')
                
                if ml_analysis and quality_predictions:
                    # Calculate content relevance score
                    relevance_score = self._calculate_content_relevance(
                        ml_analysis, user_interests, query_history
                    )
                    
                    # Get average quality from ML predictions
                    quality_scores = [
                        pred.prediction.get('quality_score', 0.5)
                        for pred in quality_predictions.predictions
                        if 'quality_score' in pred.prediction
                    ]
                    avg_quality = statistics.mean(quality_scores) if quality_scores else 0.5
                    
                    # Only suggest high-quality, relevant content
                    if relevance_score > 0.6 and avg_quality > self.config.quality_threshold:
                        suggestion = {
                            'website_url': url,
                            'relevance_score': relevance_score,
                            'quality_score': avg_quality,
                            'suggested_queries': self._extract_suggested_queries(ml_analysis),
                            'content_highlights': self._extract_content_highlights(ml_analysis),
                            'recommendation_reason': f"High quality content ({avg_quality:.2f}) with good relevance ({relevance_score:.2f})"
                        }
                        suggestions.append(suggestion)
            
            # Sort by combined relevance and quality
            suggestions.sort(
                key=lambda x: x['relevance_score'] * x['quality_score'], 
                reverse=True
            )
            
            return suggestions[:10]  # Top 10 suggestions
            
        except Exception as e:
            logger.error(f"Content suggestion generation failed: {e}")
            return []
    
    async def _generate_query_improvements(self, user_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate query improvement suggestions using ML insights"""
        
        improvements = []
        
        try:
            query_history = user_context.get('query_history', [])
            
            if not query_history:
                return []
            
            # Analyze recent queries for improvement opportunities
            recent_queries = query_history[-5:]  # Last 5 queries
            
            for query in recent_queries:
                # Use recommendation engine for query analysis
                query_analysis = await self.recommendation_engine.analyze_query_intent(query)
                
                # Generate improvements based on ML analysis
                improvements_for_query = {
                    'original_query': query,
                    'suggested_improvements': [],
                    'expansion_suggestions': [],
                    'refinement_suggestions': []
                }
                
                # Add ML-based improvements
                if hasattr(query_analysis, 'intent_confidence') and query_analysis.intent_confidence < 0.7:
                    improvements_for_query['suggested_improvements'].append(
                        "Query intent unclear - consider adding more specific terms"
                    )
                
                # Add expansion suggestions based on processed content
                content_topics = self._extract_related_topics_from_processed_content(query)
                if content_topics:
                    improvements_for_query['expansion_suggestions'] = [
                        f"Consider expanding with: {topic}" for topic in content_topics[:3]
                    ]
                
                improvements.append(improvements_for_query)
            
            return improvements
            
        except Exception as e:
            logger.error(f"Query improvement generation failed: {e}")
            return []
    
    async def _find_related_websites(self, user_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find related websites based on cross-site analysis"""
        
        try:
            if len(self.processed_websites) < 2:
                return []
            
            # Get user's preferred topics/interests
            user_interests = user_context.get('interests', [])
            current_website = user_context.get('current_website')
            
            related_sites = []
            
            # Use cross-site correlations to find related websites
            for url, website_data in self.processed_websites.items():
                if url == current_website:
                    continue
                
                ml_analysis = website_data.get('ml_analysis')
                if ml_analysis:
                    # Calculate relevance to user interests
                    site_topics = self._extract_site_topics(ml_analysis)
                    relevance = self._calculate_topic_relevance(site_topics, user_interests)
                    
                    if relevance > 0.4:
                        related_sites.append({
                            'website_url': url,
                            'relevance_score': relevance,
                            'shared_topics': [
                                topic for topic in site_topics 
                                if any(interest.lower() in topic.lower() for interest in user_interests)
                            ],
                            'quality_score': ml_analysis.aggregate_metrics.get('average_quality_score', 0.5)
                        })
            
            # Sort by relevance
            related_sites.sort(key=lambda x: x['relevance_score'], reverse=True)
            
            return related_sites[:5]  # Top 5 related sites
            
        except Exception as e:
            logger.error(f"Related website finding failed: {e}")
            return []
    
    async def _generate_quality_enhancements(self, user_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate quality enhancement suggestions based on ML analysis"""
        
        enhancements = []
        
        try:
            current_website = user_context.get('current_website')
            
            if current_website and current_website in self.processed_websites:
                website_data = self.processed_websites[current_website]
                ml_analysis = website_data.get('ml_analysis')
                quality_predictions = website_data.get('quality_predictions')
                
                if ml_analysis and quality_predictions:
                    # Analyze quality patterns
                    low_quality_items = [
                        pred for pred in quality_predictions.predictions
                        if pred.prediction.get('quality_score', 1.0) < self.config.quality_threshold
                    ]
                    
                    if low_quality_items:
                        enhancements.append({
                            'enhancement_type': 'content_quality_improvement',
                            'description': f"Found {len(low_quality_items)} content items below quality threshold",
                            'specific_suggestions': [
                                f"Improve content at {pred.model_id}" for pred in low_quality_items[:3]
                            ],
                            'priority': 'high' if len(low_quality_items) > 5 else 'medium'
                        })
                    
                    # Add recommendations from ML analysis
                    ml_recommendations = ml_analysis.recommendations
                    if ml_recommendations:
                        enhancements.append({
                            'enhancement_type': 'ml_recommendations',
                            'description': 'ML-powered content improvement suggestions',
                            'specific_suggestions': ml_recommendations[:5],
                            'priority': 'medium'
                        })
            
            return enhancements
            
        except Exception as e:
            logger.error(f"Quality enhancement generation failed: {e}")
            return []
    
    def _calculate_content_relevance(
        self,
        ml_analysis: ContentAnalysisReport,
        user_interests: List[str],
        query_history: List[str]
    ) -> float:
        """Calculate content relevance based on ML analysis and user context"""
        
        try:
            # Extract topics from ML analysis
            site_topics = []
            for analysis in ml_analysis.analysis_results.values():
                site_topics.extend(analysis.topics)
            
            # Calculate topic relevance
            topic_relevance = self._calculate_topic_relevance(site_topics, user_interests)
            
            # Calculate query relevance
            query_relevance = 0.0
            if query_history:
                # Simple keyword matching between queries and content
                all_query_terms = ' '.join(query_history).lower().split()
                site_topic_terms = ' '.join(site_topics).lower().split()
                
                common_terms = set(all_query_terms).intersection(set(site_topic_terms))
                query_relevance = len(common_terms) / max(1, len(set(all_query_terms)))
            
            # Combine relevance scores
            combined_relevance = (topic_relevance * 0.7) + (query_relevance * 0.3)
            
            return min(1.0, combined_relevance)
            
        except Exception as e:
            logger.error(f"Content relevance calculation failed: {e}")
            return 0.3  # Default low relevance
    
    def _calculate_topic_relevance(self, site_topics: List[str], user_interests: List[str]) -> float:
        """Calculate topic relevance between site and user interests"""
        
        if not user_interests or not site_topics:
            return 0.0
        
        # Count matches between user interests and site topics
        matches = 0
        total_comparisons = 0
        
        for interest in user_interests:
            for topic in site_topics:
                total_comparisons += 1
                if interest.lower() in topic.lower() or topic.lower() in interest.lower():
                    matches += 1
        
        return matches / max(1, total_comparisons)
    
    def _extract_suggested_queries(self, ml_analysis: ContentAnalysisReport) -> List[str]:
        """Extract suggested queries from ML analysis"""
        
        try:
            # Get top topics across all content
            all_topics = []
            for analysis in ml_analysis.analysis_results.values():
                all_topics.extend(analysis.topics)
            
            topic_counts = Counter(all_topics)
            top_topics = [topic for topic, count in topic_counts.most_common(5)]
            
            # Generate query suggestions
            suggestions = []
            for topic in top_topics:
                suggestions.append(f"What is {topic}?")
                suggestions.append(f"How does {topic} work?")
                suggestions.append(f"Examples of {topic}")
            
            return suggestions[:8]  # Limit to 8 suggestions
            
        except Exception as e:
            logger.error(f"Suggested query extraction failed: {e}")
            return []
    
    def _extract_content_highlights(self, ml_analysis: ContentAnalysisReport) -> List[str]:
        """Extract content highlights from ML analysis"""
        
        try:
            highlights = []
            
            # Find high-quality, high-confidence content
            for url, analysis in ml_analysis.analysis_results.items():
                if analysis.quality_score > 0.8 and analysis.confidence > 0.7:
                    primary_topic = analysis.topics[0] if analysis.topics else 'content'
                    highlights.append(f"High-quality {primary_topic} content at {url}")
            
            # Add aggregate insights
            avg_quality = ml_analysis.aggregate_metrics.get('average_quality_score', 0.0)
            if avg_quality > 0.7:
                highlights.append(f"Excellent overall content quality ({avg_quality:.2f})")
            
            most_common_topic = ml_analysis.aggregate_metrics.get('most_common_topic', '')
            if most_common_topic:
                highlights.append(f"Primary focus area: {most_common_topic}")
            
            return highlights[:5]  # Top 5 highlights
            
        except Exception as e:
            logger.error(f"Content highlight extraction failed: {e}")
            return []
    
    def _extract_site_topics(self, ml_analysis: ContentAnalysisReport) -> List[str]:
        """Extract all topics from site ML analysis"""
        
        all_topics = []
        for analysis in ml_analysis.analysis_results.values():
            all_topics.extend(analysis.topics)
        
        # Return unique topics
        return list(set(all_topics))
    
    def _extract_related_topics_from_processed_content(self, query: str) -> List[str]:
        """Extract topics related to query from processed content"""
        
        related_topics = []
        
        try:
            query_lower = query.lower()
            
            # Look through processed websites for related topics
            for website_data in self.processed_websites.values():
                ml_analysis = website_data.get('ml_analysis')
                if ml_analysis:
                    for analysis in ml_analysis.analysis_results.values():
                        for topic in analysis.topics:
                            # Check if topic is related to query
                            if any(word in topic.lower() for word in query_lower.split()):
                                related_topics.append(topic)
            
            # Return unique topics
            return list(set(related_topics))[:5]
            
        except Exception as e:
            logger.error(f"Related topic extraction failed: {e}")
            return []
    
    async def get_phase7_system_status(self) -> Dict[str, Any]:
        """Get comprehensive Phase 7 system status"""
        
        try:
            # Model server performance
            ml_performance = {}
            if hasattr(self.ml_model_server, 'get_model_performance_summary'):
                ml_performance = self.ml_model_server.get_model_performance_summary()
            
            # Cross-site analytics summary
            cross_site_analytics = {}
            if hasattr(self.cross_site_analyzer, 'get_cross_site_analytics_summary'):
                cross_site_analytics = self.cross_site_analyzer.get_cross_site_analytics_summary()
            
            # ML classification analytics
            ml_classification_analytics = {}
            if hasattr(self.ml_classifier, 'get_analytics_summary'):
                ml_classification_analytics = self.ml_classifier.get_analytics_summary()
            
            return {
                'phase7_initialization_status': self.is_initialized,
                'configuration': {
                    'ml_classification_enabled': self.config.enable_ml_classification,
                    'cross_site_analysis_enabled': self.config.enable_cross_site_analysis,
                    'intelligent_recommendations_enabled': self.config.enable_intelligent_recommendations,
                    'global_knowledge_graph_enabled': self.config.enable_global_knowledge_graph,
                    'real_time_analytics_enabled': self.config.enable_real_time_analytics
                },
                'processing_metrics': self.performance_metrics,
                'ml_model_performance': ml_performance,
                'cross_site_analytics': cross_site_analytics,
                'ml_classification_analytics': ml_classification_analytics,
                'processed_websites_count': len(self.processed_websites),
                'system_health': self._assess_system_health(),
                'status_timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"System status collection failed: {e}")
            return {
                'error': str(e),
                'status_timestamp': datetime.now().isoformat()
            }
    
    def _assess_system_health(self) -> Dict[str, Any]:
        """Assess overall system health"""
        
        health_indicators = {
            'overall_status': 'healthy',
            'component_status': {},
            'performance_indicators': {},
            'warnings': [],
            'errors': []
        }
        
        try:
            # Check component status
            health_indicators['component_status'] = {
                'base_graphrag': self.base_graphrag_system is not None,
                'ml_classifier': self.ml_classifier is not None,
                'ml_model_server': self.ml_model_server.get_model_performance_summary().get('loaded_models', []) != [],
                'cross_site_analyzer': self.cross_site_analyzer is not None,
                'recommendation_engine': self.recommendation_engine is not None
            }
            
            # Check performance indicators
            total_websites = self.performance_metrics['websites_processed']
            if total_websites > 0:
                avg_processing_time = self.performance_metrics['total_processing_time'] / total_websites
                health_indicators['performance_indicators'] = {
                    'average_processing_time_per_website': avg_processing_time,
                    'ml_analysis_success_rate': self.performance_metrics['ml_analyses_completed'] / total_websites,
                    'recommendation_generation_rate': self.performance_metrics['recommendations_generated'] / total_websites
                }
                
                # Add warnings based on performance
                if avg_processing_time > 300:  # 5 minutes
                    health_indicators['warnings'].append("High average processing time detected")
                
                ml_success_rate = self.performance_metrics['ml_analyses_completed'] / total_websites
                if ml_success_rate < 0.8:
                    health_indicators['warnings'].append("Low ML analysis success rate")
            
            # Determine overall status
            component_failures = sum(1 for status in health_indicators['component_status'].values() if not status)
            if component_failures > 2:
                health_indicators['overall_status'] = 'degraded'
            elif health_indicators['warnings']:
                health_indicators['overall_status'] = 'warning'
            
        except Exception as e:
            health_indicators['errors'].append(f"Health assessment failed: {str(e)}")
            health_indicators['overall_status'] = 'error'
        
        return health_indicators
    
    async def export_phase7_analytics(self, output_format: str = 'json') -> str:
        """Export comprehensive Phase 7 analytics data"""
        
        try:
            # Collect all analytics data
            analytics_data = {
                'export_timestamp': datetime.now().isoformat(),
                'system_status': await self.get_phase7_system_status(),
                'processed_websites': {
                    url: {
                        'processing_timestamp': data['processing_timestamp'].isoformat(),
                        'ml_analysis_summary': {
                            'total_items_analyzed': data['ml_analysis'].total_items_analyzed if data.get('ml_analysis') else 0,
                            'average_quality_score': data['ml_analysis'].aggregate_metrics.get('average_quality_score', 0) if data.get('ml_analysis') else 0,
                            'most_common_topic': data['ml_analysis'].aggregate_metrics.get('most_common_topic', 'unknown') if data.get('ml_analysis') else 'unknown'
                        },
                        'quality_predictions_summary': {
                            'total_predictions': data['quality_predictions'].total_items if data.get('quality_predictions') else 0,
                            'successful_predictions': data['quality_predictions'].successful_predictions if data.get('quality_predictions') else 0,
                            'average_confidence': data['quality_predictions'].average_confidence if data.get('quality_predictions') else 0
                        }
                    }
                    for url, data in self.processed_websites.items()
                },
                'performance_summary': self.performance_metrics
            }
            
            # Export to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"phase7_analytics_export_{timestamp}.{output_format}"
            output_path = Path(f"/tmp/{filename}")
            
            if output_format == 'json':
                with open(output_path, 'w') as f:
                    json.dump(analytics_data, f, indent=2, default=str)
            else:
                raise ValueError(f"Unsupported export format: {output_format}")
            
            logger.info(f"Phase 7 analytics exported to {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Analytics export failed: {e}")
            return f"Export failed: {str(e)}"


# Convenience functions for Phase 7 integration
async def process_website_with_advanced_ml(
    url: str,
    config: Optional[Phase7Configuration] = None
) -> MLEnhancedProcessingResult:
    """
    Convenience function for processing single website with Phase 7 ML enhancement
    
    Args:
        url: Website URL to process
        config: Optional Phase 7 configuration
        
    Returns:
        ML-enhanced processing result
    """
    
    system = Phase7AdvancedGraphRAGSystem(config)
    await system.initialize()
    
    return await system.process_website_with_ml_analysis(url)


async def analyze_multiple_websites_with_ml(
    urls: List[str],
    config: Optional[Phase7Configuration] = None
) -> Dict[str, MLEnhancedProcessingResult]:
    """
    Convenience function for processing multiple websites with cross-site analysis
    
    Args:
        urls: List of website URLs to process
        config: Optional Phase 7 configuration
        
    Returns:
        Dictionary of ML-enhanced results with cross-site analysis
    """
    
    system = Phase7AdvancedGraphRAGSystem(config)
    await system.initialize()
    
    return await system.analyze_multiple_websites(urls)


# Example usage and testing
async def main():
    """Example usage of Phase 7 advanced GraphRAG system"""
    
    # Initialize Phase 7 system
    config = Phase7Configuration(
        enable_ml_classification=True,
        enable_cross_site_analysis=True,
        enable_intelligent_recommendations=True,
        quality_threshold=0.6
    )
    
    system = Phase7AdvancedGraphRAGSystem(config)
    await system.initialize()
    
    # Example single website processing
    print("🚀 Phase 7 Advanced GraphRAG System Demo")
    print("=" * 50)
    
    # Process single website with ML enhancement
    test_url = "https://example.com"
    print(f"\n📄 Processing website with ML enhancement: {test_url}")
    
    # Note: This would normally process a real website
    # For demo, we'll show the system status
    
    status = await system.get_phase7_system_status()
    print(f"\n📊 Phase 7 System Status:")
    print(f"  Initialization: {status['phase7_initialization_status']}")
    print(f"  ML Classification: {status['configuration']['ml_classification_enabled']}")
    print(f"  Cross-site Analysis: {status['configuration']['cross_site_analysis_enabled']}")
    print(f"  Intelligent Recommendations: {status['configuration']['intelligent_recommendations_enabled']}")
    print(f"  Websites Processed: {status['processed_websites_count']}")
    print(f"  System Health: {status['system_health']['overall_status']}")
    
    print(f"\n✅ Phase 7 Advanced Analytics & ML Integration is ready for production!")


if __name__ == '__main__':
    anyio.run(main())
#!/usr/bin/env python3
"""
Cross-Website Analytics Engine - Advanced multi-site content correlation and analysis

This module provides comprehensive analytics capabilities for analyzing patterns,
trends, and correlations across multiple websites processed by the GraphRAG system.

Features:
- Cross-website content correlation and similarity analysis
- Global trend detection and pattern recognition
- Multi-site knowledge graph integration and entity linking
- Comparative quality assessment across websites
- User behavior analysis across different sites
- Real-time analytics dashboard with cross-site insights
- Global content recommendation engine

Usage:
    analyzer = CrossWebsiteAnalyzer()
    correlations = await analyzer.analyze_cross_site_correlations(website_systems)
    trends = await analyzer.detect_global_trends(analysis_history)
"""

import os
import json
import asyncio
import logging
import math
import statistics
from typing import Dict, List, Optional, Any, Union, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import uuid
import re
from collections import defaultdict, Counter, deque
from itertools import combinations

# ML and analytics imports
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans, DBSCAN
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

# Import GraphRAG and ML components
try:
    from ipfs_datasets_py.website_graphrag_system import WebsiteGraphRAGSystem
    from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraph, Entity, Relationship
    from ipfs_datasets_py.ml.content_classification import ContentAnalysisReport, ContentAnalysis
    from ipfs_datasets_py.enhanced_multimodal_processor import ProcessedContent
except ImportError:
    # Fallback for testing
    WebsiteGraphRAGSystem = Any
    KnowledgeGraph = Any
    ContentAnalysisReport = Any
    ContentAnalysis = Any
    ProcessedContent = Any

logger = logging.getLogger(__name__)


@dataclass
class WebsiteCorrelation:
    """Correlation analysis between two websites"""
    
    website_a: str
    website_b: str
    similarity_score: float  # 0.0 to 1.0
    correlation_type: str  # topic, entity, quality, content
    shared_entities: List[str] = field(default_factory=list)
    shared_topics: List[str] = field(default_factory=list)
    content_overlap: float = 0.0
    quality_similarity: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GlobalTrend:
    """Detected global trend across websites"""
    
    trend_id: str
    trend_type: str  # topic, quality, entity, sentiment
    trend_name: str
    trend_strength: float  # 0.0 to 1.0
    affected_websites: List[str]
    trend_data: Dict[str, Any]
    detection_timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 0.0


@dataclass
class CrossSiteAnalysisReport:
    """Comprehensive cross-website analysis report"""
    
    analysis_id: str
    websites_analyzed: List[str]
    correlations: List[WebsiteCorrelation]
    detected_trends: List[GlobalTrend]
    global_metrics: Dict[str, float]
    cluster_analysis: Dict[str, Any]
    recommendations: List[str]
    processing_timestamp: datetime = field(default_factory=datetime.now)
    processing_time_seconds: float = 0.0


@dataclass
class GlobalKnowledgeGraph:
    """Global knowledge graph spanning multiple websites"""
    
    graph_id: str
    participating_websites: List[str]
    global_entities: Dict[str, Any]  # Entity ID -> Entity with cross-site references
    global_relationships: List[Dict[str, Any]]  # Cross-site relationships
    entity_clusters: Dict[str, List[str]]  # Topic clusters -> Entity IDs
    cross_site_connections: List[Dict[str, Any]]  # Connections between websites
    quality_score: float = 0.0
    last_updated: datetime = field(default_factory=datetime.now)


class CrossWebsiteAnalyzer:
    """
    Advanced analytics engine for multi-website content correlation and analysis.
    
    This analyzer provides sophisticated capabilities for understanding patterns,
    trends, and relationships across multiple websites processed by GraphRAG.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or self._default_config()
        
        # Initialize analytics components
        self.similarity_analyzer = ContentSimilarityAnalyzer()
        self.trend_detector = TrendDetectionEngine()
        self.knowledge_graph_integrator = GlobalKnowledgeGraphIntegrator()
        self.cluster_analyzer = ContentClusterAnalyzer()
        
        # Analytics storage
        self.analytics_store = self._initialize_analytics_store()
        
    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for cross-website analyzer"""
        return {
            'similarity_threshold': 0.6,
            'trend_detection_window_days': 30,
            'min_websites_for_trend': 3,
            'max_clusters': 20,
            'enable_real_time_analysis': True,
            'store_detailed_correlations': True,
            'correlation_cache_size': 1000
        }
    
    def _initialize_analytics_store(self) -> Dict[str, Any]:
        """Initialize analytics data storage"""
        return {
            'correlation_history': deque(maxlen=self.config.get('correlation_cache_size', 1000)),
            'trend_history': deque(maxlen=500),
            'global_metrics': {},
            'website_profiles': {},
            'entity_cross_references': defaultdict(set),
            'topic_evolution': defaultdict(list)
        }
    
    async def analyze_cross_site_correlations(
        self,
        website_systems: List[WebsiteGraphRAGSystem],
        analysis_types: List[str] = None
    ) -> CrossSiteAnalysisReport:
        """
        Analyze correlations and patterns across multiple websites
        
        Args:
            website_systems: List of processed website systems
            analysis_types: Types of analysis to perform ['topic', 'entity', 'quality', 'content']
            
        Returns:
            Comprehensive cross-site analysis report
        """
        start_time = datetime.now()
        analysis_id = str(uuid.uuid4())
        
        analysis_types = analysis_types or ['topic', 'entity', 'quality', 'content']
        
        try:
            logger.info(f"Starting cross-site analysis of {len(website_systems)} websites")
            
            # Extract website data for analysis
            website_data = await self._extract_website_data(website_systems)
            
            # Calculate pairwise correlations
            correlations = await self._calculate_pairwise_correlations(
                website_data, analysis_types
            )
            
            # Detect global trends
            trends = await self._detect_global_trends(website_data)
            
            # Perform cluster analysis
            cluster_analysis = await self._perform_cluster_analysis(website_data)
            
            # Calculate global metrics
            global_metrics = self._calculate_global_metrics(website_data, correlations)
            
            # Generate recommendations
            recommendations = self._generate_cross_site_recommendations(
                correlations, trends, global_metrics
            )
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            report = CrossSiteAnalysisReport(
                analysis_id=analysis_id,
                websites_analyzed=[system.url for system in website_systems],
                correlations=correlations,
                detected_trends=trends,
                global_metrics=global_metrics,
                cluster_analysis=cluster_analysis,
                recommendations=recommendations,
                processing_time_seconds=processing_time
            )
            
            # Store analysis results
            await self._store_cross_site_analysis(report)
            
            return report
            
        except Exception as e:
            logger.error(f"Cross-site analysis failed: {e}")
            return CrossSiteAnalysisReport(
                analysis_id=analysis_id,
                websites_analyzed=[system.url for system in website_systems],
                correlations=[],
                detected_trends=[],
                global_metrics={'error': 1.0},
                cluster_analysis={},
                recommendations=[f"Analysis failed: {str(e)}"],
                processing_time_seconds=(datetime.now() - start_time).total_seconds()
            )
    
    async def _extract_website_data(
        self, 
        website_systems: List[WebsiteGraphRAGSystem]
    ) -> Dict[str, Dict[str, Any]]:
        """Extract relevant data from website systems for analysis"""
        
        website_data = {}
        
        for system in website_systems:
            try:
                # Extract content overview
                overview = system.get_content_overview()
                
                # Extract processed content
                processed_content = getattr(system, 'processed_content', None)
                content_items = getattr(processed_content, 'processed_items', []) if processed_content else []
                
                # Extract knowledge graph
                knowledge_graph = getattr(system, 'knowledge_graph', None)
                entities = getattr(knowledge_graph, 'entities', []) if knowledge_graph else []
                relationships = getattr(knowledge_graph, 'relationships', []) if knowledge_graph else []
                
                # Combine all text content for analysis
                all_text = ' '.join([
                    getattr(item, 'text_content', '') or '' 
                    for item in content_items
                ])
                
                website_data[system.url] = {
                    'overview': overview,
                    'content_items': content_items,
                    'all_text': all_text,
                    'entities': entities,
                    'relationships': relationships,
                    'content_count': len(content_items),
                    'entity_count': len(entities),
                    'relationship_count': len(relationships),
                    'total_text_length': len(all_text)
                }
                
            except Exception as e:
                logger.error(f"Failed to extract data from {system.url}: {e}")
                website_data[system.url] = {
                    'overview': {},
                    'content_items': [],
                    'all_text': '',
                    'entities': [],
                    'relationships': [],
                    'content_count': 0,
                    'entity_count': 0,
                    'relationship_count': 0,
                    'total_text_length': 0
                }
        
        return website_data
    
    async def _calculate_pairwise_correlations(
        self,
        website_data: Dict[str, Dict[str, Any]],
        analysis_types: List[str]
    ) -> List[WebsiteCorrelation]:
        """Calculate correlations between all website pairs"""
        
        correlations = []
        website_urls = list(website_data.keys())
        
        # Calculate correlations for all pairs
        for url_a, url_b in combinations(website_urls, 2):
            data_a = website_data[url_a]
            data_b = website_data[url_b]
            
            try:
                correlation = await self._calculate_website_correlation(
                    url_a, data_a, url_b, data_b, analysis_types
                )
                correlations.append(correlation)
            except Exception as e:
                logger.error(f"Failed to calculate correlation between {url_a} and {url_b}: {e}")
        
        return correlations
    
    async def _calculate_website_correlation(
        self,
        url_a: str, data_a: Dict[str, Any],
        url_b: str, data_b: Dict[str, Any],
        analysis_types: List[str]
    ) -> WebsiteCorrelation:
        """Calculate correlation between two specific websites"""
        
        correlations = {}
        shared_entities = []
        shared_topics = []
        
        # Topic correlation
        if 'topic' in analysis_types:
            correlations['topic'] = await self._calculate_topic_correlation(data_a, data_b)
        
        # Entity correlation
        if 'entity' in analysis_types:
            entity_corr, shared_ents = await self._calculate_entity_correlation(data_a, data_b)
            correlations['entity'] = entity_corr
            shared_entities = shared_ents
        
        # Content correlation
        if 'content' in analysis_types:
            content_corr, content_overlap = await self._calculate_content_correlation(data_a, data_b)
            correlations['content'] = content_corr
        else:
            content_overlap = 0.0
        
        # Quality correlation
        if 'quality' in analysis_types:
            correlations['quality'] = await self._calculate_quality_correlation(data_a, data_b)
        
        # Calculate overall similarity
        overall_similarity = statistics.mean(correlations.values()) if correlations else 0.0
        
        # Determine primary correlation type
        correlation_type = max(correlations.items(), key=lambda x: x[1])[0] if correlations else 'unknown'
        
        return WebsiteCorrelation(
            website_a=url_a,
            website_b=url_b,
            similarity_score=overall_similarity,
            correlation_type=correlation_type,
            shared_entities=shared_entities,
            shared_topics=shared_topics,
            content_overlap=content_overlap,
            quality_similarity=correlations.get('quality', 0.0),
            metadata={
                'detailed_correlations': correlations,
                'analysis_timestamp': datetime.now().isoformat()
            }
        )
    
    async def _calculate_topic_correlation(
        self, 
        data_a: Dict[str, Any], 
        data_b: Dict[str, Any]
    ) -> float:
        """Calculate topic-based correlation between websites"""
        
        try:
            text_a = data_a.get('all_text', '')
            text_b = data_b.get('all_text', '')
            
            if not text_a or not text_b:
                return 0.0
            
            # Use TF-IDF to find content similarity
            vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
            
            try:
                tfidf_matrix = vectorizer.fit_transform([text_a, text_b])
                similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                return float(similarity)
            except:
                # Fallback to simple word overlap
                words_a = set(text_a.lower().split())
                words_b = set(text_b.lower().split())
                
                if not words_a or not words_b:
                    return 0.0
                
                overlap = len(words_a.intersection(words_b))
                union = len(words_a.union(words_b))
                
                return overlap / union if union > 0 else 0.0
                
        except Exception as e:
            logger.error(f"Topic correlation calculation failed: {e}")
            return 0.0
    
    async def _calculate_entity_correlation(
        self, 
        data_a: Dict[str, Any], 
        data_b: Dict[str, Any]
    ) -> Tuple[float, List[str]]:
        """Calculate entity-based correlation between websites"""
        
        try:
            entities_a = data_a.get('entities', [])
            entities_b = data_b.get('entities', [])
            
            # Extract entity names/labels
            entity_names_a = set()
            entity_names_b = set()
            
            for entity in entities_a:
                if hasattr(entity, 'label'):
                    entity_names_a.add(entity.label.lower())
                elif isinstance(entity, dict):
                    entity_names_a.add(entity.get('label', '').lower())
                else:
                    entity_names_a.add(str(entity).lower())
            
            for entity in entities_b:
                if hasattr(entity, 'label'):
                    entity_names_b.add(entity.label.lower())
                elif isinstance(entity, dict):
                    entity_names_b.add(entity.get('label', '').lower())
                else:
                    entity_names_b.add(str(entity).lower())
            
            # Calculate overlap
            shared_entities = list(entity_names_a.intersection(entity_names_b))
            total_unique_entities = len(entity_names_a.union(entity_names_b))
            
            if total_unique_entities == 0:
                return 0.0, []
            
            correlation = len(shared_entities) / total_unique_entities
            
            return correlation, shared_entities
            
        except Exception as e:
            logger.error(f"Entity correlation calculation failed: {e}")
            return 0.0, []
    
    async def _calculate_content_correlation(
        self, 
        data_a: Dict[str, Any], 
        data_b: Dict[str, Any]
    ) -> Tuple[float, float]:
        """Calculate content-based correlation between websites"""
        
        try:
            content_items_a = data_a.get('content_items', [])
            content_items_b = data_b.get('content_items', [])
            
            # Extract content types and analyze distribution
            types_a = Counter(getattr(item, 'content_type', 'unknown') for item in content_items_a)
            types_b = Counter(getattr(item, 'content_type', 'unknown') for item in content_items_b)
            
            # Calculate content type similarity
            all_types = set(types_a.keys()).union(set(types_b.keys()))
            
            if not all_types:
                return 0.0, 0.0
            
            # Calculate cosine similarity of content type distributions
            vector_a = np.array([types_a.get(t, 0) for t in all_types])
            vector_b = np.array([types_b.get(t, 0) for t in all_types])
            
            # Normalize vectors
            norm_a = np.linalg.norm(vector_a)
            norm_b = np.linalg.norm(vector_b)
            
            if norm_a == 0 or norm_b == 0:
                return 0.0, 0.0
            
            similarity = np.dot(vector_a, vector_b) / (norm_a * norm_b)
            
            # Calculate content overlap (simple metric)
            total_content_a = data_a.get('content_count', 0)
            total_content_b = data_b.get('content_count', 0)
            
            if total_content_a == 0 or total_content_b == 0:
                content_overlap = 0.0
            else:
                # Simple overlap based on content counts
                min_content = min(total_content_a, total_content_b)
                max_content = max(total_content_a, total_content_b)
                content_overlap = min_content / max_content
            
            return float(similarity), content_overlap
            
        except Exception as e:
            logger.error(f"Content correlation calculation failed: {e}")
            return 0.0, 0.0
    
    async def _calculate_quality_correlation(
        self, 
        data_a: Dict[str, Any], 
        data_b: Dict[str, Any]
    ) -> float:
        """Calculate quality-based correlation between websites"""
        
        try:
            # Extract quality metrics from overview data
            overview_a = data_a.get('overview', {})
            overview_b = data_b.get('overview', {})
            
            # Use content counts as proxy for quality
            metrics_a = {
                'content_count': overview_a.get('total_pages', 0),
                'entity_count': data_a.get('entity_count', 0),
                'relationship_count': data_a.get('relationship_count', 0),
                'text_length': data_a.get('total_text_length', 0)
            }
            
            metrics_b = {
                'content_count': overview_b.get('total_pages', 0),
                'entity_count': data_b.get('entity_count', 0),
                'relationship_count': data_b.get('relationship_count', 0),
                'text_length': data_b.get('total_text_length', 0)
            }
            
            # Calculate correlation between quality metrics
            values_a = np.array(list(metrics_a.values()))
            values_b = np.array(list(metrics_b.values()))
            
            # Normalize values to prevent scale bias
            if np.max(values_a) > 0:
                values_a = values_a / np.max(values_a)
            if np.max(values_b) > 0:
                values_b = values_b / np.max(values_b)
            
            # Calculate cosine similarity
            norm_a = np.linalg.norm(values_a)
            norm_b = np.linalg.norm(values_b)
            
            if norm_a == 0 or norm_b == 0:
                return 0.0
            
            similarity = np.dot(values_a, values_b) / (norm_a * norm_b)
            
            return float(similarity)
            
        except Exception as e:
            logger.error(f"Quality correlation calculation failed: {e}")
            return 0.0
    
    async def _detect_global_trends(
        self, 
        website_data: Dict[str, Dict[str, Any]]
    ) -> List[GlobalTrend]:
        """Detect global trends across all websites"""
        
        trends = []
        
        try:
            # Topic trends
            topic_trends = await self._detect_topic_trends(website_data)
            trends.extend(topic_trends)
            
            # Quality trends
            quality_trends = await self._detect_quality_trends(website_data)
            trends.extend(quality_trends)
            
            # Entity trends
            entity_trends = await self._detect_entity_trends(website_data)
            trends.extend(entity_trends)
            
            return trends
            
        except Exception as e:
            logger.error(f"Global trend detection failed: {e}")
            return []
    
    async def _detect_topic_trends(self, website_data: Dict[str, Dict[str, Any]]) -> List[GlobalTrend]:
        """Detect trending topics across websites"""
        
        # Combine all text from all websites
        all_texts = []
        website_texts = {}
        
        for url, data in website_data.items():
            text = data.get('all_text', '')
            if text:
                all_texts.append(text)
                website_texts[url] = text
        
        if len(all_texts) < 2:
            return []
        
        try:
            # Use TF-IDF to find common topics
            vectorizer = TfidfVectorizer(max_features=100, stop_words='english')
            tfidf_matrix = vectorizer.fit_transform(all_texts)
            
            # Get top terms
            feature_names = vectorizer.get_feature_names_out()
            term_scores = np.mean(tfidf_matrix.toarray(), axis=0)
            
            # Find top trending terms
            top_terms_indices = np.argsort(term_scores)[-10:]  # Top 10 terms
            trending_topics = []
            
            for idx in top_terms_indices:
                term = feature_names[idx]
                score = term_scores[idx]
                
                # Find websites containing this term
                affected_websites = []
                for url, text in website_texts.items():
                    if term in text.lower():
                        affected_websites.append(url)
                
                # Only consider as trend if appears in multiple websites
                if len(affected_websites) >= self.config.get('min_websites_for_trend', 3):
                    trend = GlobalTrend(
                        trend_id=str(uuid.uuid4()),
                        trend_type='topic',
                        trend_name=f"trending_topic_{term}",
                        trend_strength=float(score),
                        affected_websites=affected_websites,
                        trend_data={
                            'term': term,
                            'tfidf_score': float(score),
                            'website_count': len(affected_websites)
                        },
                        confidence=min(1.0, len(affected_websites) / len(website_data))
                    )
                    trending_topics.append(trend)
            
            return trending_topics
            
        except Exception as e:
            logger.error(f"Topic trend detection failed: {e}")
            return []
    
    async def _detect_quality_trends(self, website_data: Dict[str, Dict[str, Any]]) -> List[GlobalTrend]:
        """Detect quality-related trends across websites"""
        
        # Analyze quality distributions
        quality_metrics = []
        
        for url, data in website_data.items():
            metrics = {
                'url': url,
                'content_density': data.get('total_text_length', 0) / max(1, data.get('content_count', 1)),
                'entity_density': data.get('entity_count', 0) / max(1, data.get('content_count', 1)),
                'relationship_density': data.get('relationship_count', 0) / max(1, data.get('entity_count', 1))
            }
            quality_metrics.append(metrics)
        
        trends = []
        
        if len(quality_metrics) >= 3:
            # Detect high-quality content trend
            high_quality_sites = [
                m['url'] for m in quality_metrics
                if m['content_density'] > 1000 and m['entity_density'] > 5
            ]
            
            if len(high_quality_sites) >= 3:
                trend = GlobalTrend(
                    trend_id=str(uuid.uuid4()),
                    trend_type='quality',
                    trend_name='high_quality_content_cluster',
                    trend_strength=len(high_quality_sites) / len(quality_metrics),
                    affected_websites=high_quality_sites,
                    trend_data={
                        'average_content_density': statistics.mean([
                            m['content_density'] for m in quality_metrics if m['url'] in high_quality_sites
                        ]),
                        'average_entity_density': statistics.mean([
                            m['entity_density'] for m in quality_metrics if m['url'] in high_quality_sites
                        ])
                    },
                    confidence=0.8
                )
                trends.append(trend)
        
        return trends
    
    async def _detect_entity_trends(self, website_data: Dict[str, Dict[str, Any]]) -> List[GlobalTrend]:
        """Detect entity-related trends across websites"""
        
        # Count entity occurrences across all websites
        entity_counts = defaultdict(int)
        entity_websites = defaultdict(set)
        
        for url, data in website_data.items():
            entities = data.get('entities', [])
            
            for entity in entities:
                if hasattr(entity, 'label'):
                    entity_name = entity.label.lower()
                elif isinstance(entity, dict):
                    entity_name = entity.get('label', '').lower()
                else:
                    entity_name = str(entity).lower()
                
                if entity_name:
                    entity_counts[entity_name] += 1
                    entity_websites[entity_name].add(url)
        
        # Find trending entities (appear in multiple websites)
        trending_entities = []
        min_websites = self.config.get('min_websites_for_trend', 3)
        
        for entity_name, count in entity_counts.items():
            websites_with_entity = list(entity_websites[entity_name])
            
            if len(websites_with_entity) >= min_websites:
                trend = GlobalTrend(
                    trend_id=str(uuid.uuid4()),
                    trend_type='entity',
                    trend_name=f"trending_entity_{entity_name}",
                    trend_strength=count / len(website_data),
                    affected_websites=websites_with_entity,
                    trend_data={
                        'entity_name': entity_name,
                        'total_occurrences': count,
                        'website_count': len(websites_with_entity)
                    },
                    confidence=min(1.0, len(websites_with_entity) / len(website_data))
                )
                trending_entities.append(trend)
        
        # Sort by trend strength and return top trends
        trending_entities.sort(key=lambda x: x.trend_strength, reverse=True)
        return trending_entities[:10]  # Top 10 trending entities
    
    async def _perform_cluster_analysis(
        self, 
        website_data: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform clustering analysis on websites"""
        
        try:
            urls = list(website_data.keys())
            
            if len(urls) < 3:
                return {'message': 'Insufficient websites for clustering'}
            
            # Create feature vectors for clustering
            feature_vectors = []
            feature_names = ['content_count', 'entity_count', 'relationship_count', 'total_text_length']
            
            for url in urls:
                data = website_data[url]
                vector = [
                    data.get('content_count', 0),
                    data.get('entity_count', 0), 
                    data.get('relationship_count', 0),
                    math.log10(max(1, data.get('total_text_length', 1)))  # Log scale for text length
                ]
                feature_vectors.append(vector)
            
            # Normalize features
            scaler = StandardScaler()
            normalized_vectors = scaler.fit_transform(feature_vectors)
            
            # Perform K-means clustering
            n_clusters = min(len(urls) // 2, self.config.get('max_clusters', 5))
            if n_clusters < 2:
                n_clusters = 2
            
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            cluster_labels = kmeans.fit_predict(normalized_vectors)
            
            # Organize results
            clusters = defaultdict(list)
            for i, url in enumerate(urls):
                clusters[f"cluster_{cluster_labels[i]}"].append(url)
            
            # Calculate cluster characteristics
            cluster_characteristics = {}
            for cluster_name, cluster_urls in clusters.items():
                cluster_data = [website_data[url] for url in cluster_urls]
                
                characteristics = {
                    'websites': cluster_urls,
                    'size': len(cluster_urls),
                    'average_content_count': statistics.mean([d.get('content_count', 0) for d in cluster_data]),
                    'average_entity_count': statistics.mean([d.get('entity_count', 0) for d in cluster_data]),
                    'total_text_length': sum([d.get('total_text_length', 0) for d in cluster_data])
                }
                
                cluster_characteristics[cluster_name] = characteristics
            
            return {
                'cluster_count': n_clusters,
                'clusters': dict(clusters),
                'cluster_characteristics': cluster_characteristics,
                'silhouette_score': self._calculate_silhouette_score(normalized_vectors, cluster_labels)
            }
            
        except Exception as e:
            logger.error(f"Cluster analysis failed: {e}")
            return {'error': f"Clustering failed: {str(e)}"}
    
    def _calculate_silhouette_score(self, vectors: np.ndarray, labels: np.ndarray) -> float:
        """Calculate silhouette score for cluster quality assessment"""
        try:
            from sklearn.metrics import silhouette_score
            return float(silhouette_score(vectors, labels))
        except:
            # Fallback calculation
            return 0.5  # Default moderate score
    
    def _calculate_global_metrics(
        self,
        website_data: Dict[str, Dict[str, Any]],
        correlations: List[WebsiteCorrelation]
    ) -> Dict[str, float]:
        """Calculate global metrics across all websites"""
        
        if not website_data:
            return {}
        
        # Content metrics
        total_content = sum(data.get('content_count', 0) for data in website_data.values())
        total_entities = sum(data.get('entity_count', 0) for data in website_data.values())
        total_relationships = sum(data.get('relationship_count', 0) for data in website_data.values())
        total_text_length = sum(data.get('total_text_length', 0) for data in website_data.values())
        
        # Correlation metrics
        correlation_scores = [corr.similarity_score for corr in correlations]
        
        # Quality metrics
        avg_content_per_site = total_content / len(website_data)
        avg_entities_per_site = total_entities / len(website_data)
        avg_relationships_per_site = total_relationships / len(website_data)
        
        return {
            'total_websites_analyzed': len(website_data),
            'total_content_items': total_content,
            'total_entities_extracted': total_entities,
            'total_relationships_found': total_relationships,
            'total_text_processed_mb': total_text_length / (1024 * 1024),
            'average_content_per_website': avg_content_per_site,
            'average_entities_per_website': avg_entities_per_site,
            'average_relationships_per_website': avg_relationships_per_site,
            'average_cross_site_correlation': statistics.mean(correlation_scores) if correlation_scores else 0.0,
            'max_correlation_found': max(correlation_scores) if correlation_scores else 0.0,
            'content_density_variance': self._calculate_content_density_variance(website_data),
            'knowledge_graph_connectivity': total_relationships / max(1, total_entities)
        }
    
    def _calculate_content_density_variance(self, website_data: Dict[str, Dict[str, Any]]) -> float:
        """Calculate variance in content density across websites"""
        
        densities = []
        for data in website_data.values():
            content_count = data.get('content_count', 0)
            text_length = data.get('total_text_length', 0)
            
            if content_count > 0:
                density = text_length / content_count
                densities.append(density)
        
        if len(densities) > 1:
            return statistics.stdev(densities)
        else:
            return 0.0
    
    def _generate_cross_site_recommendations(
        self,
        correlations: List[WebsiteCorrelation],
        trends: List[GlobalTrend],
        global_metrics: Dict[str, float]
    ) -> List[str]:
        """Generate recommendations based on cross-site analysis"""
        
        recommendations = []
        
        # Correlation-based recommendations
        avg_correlation = global_metrics.get('average_cross_site_correlation', 0.0)
        if avg_correlation > 0.7:
            recommendations.append("High cross-site correlation detected - consider creating unified knowledge base")
        elif avg_correlation < 0.3:
            recommendations.append("Low cross-site correlation - websites appear to cover distinct topics")
        
        # Trend-based recommendations
        if len(trends) > 5:
            recommendations.append(f"Multiple trends detected ({len(trends)}) - consider trend-based content optimization")
        
        strong_trends = [t for t in trends if t.trend_strength > 0.6]
        if strong_trends:
            recommendations.append(f"Strong trends detected: {', '.join([t.trend_name for t in strong_trends[:3]])}")
        
        # Quality-based recommendations
        avg_entities = global_metrics.get('average_entities_per_website', 0.0)
        if avg_entities < 10:
            recommendations.append("Low average entity extraction - consider improving content quality or extraction methods")
        
        knowledge_connectivity = global_metrics.get('knowledge_graph_connectivity', 0.0)
        if knowledge_connectivity < 0.5:
            recommendations.append("Low knowledge graph connectivity - consider improving relationship extraction")
        
        # Content diversity recommendations
        content_variance = global_metrics.get('content_density_variance', 0.0)
        if content_variance > 10000:
            recommendations.append("High content density variance - websites have very different content structures")
        
        if not recommendations:
            recommendations.append("Cross-site analysis shows balanced content distribution with good correlation")
        
        return recommendations[:7]  # Limit to top 7 recommendations
    
    async def _store_cross_site_analysis(self, report: CrossSiteAnalysisReport):
        """Store cross-site analysis results for trend tracking"""
        
        analysis_summary = {
            'analysis_id': report.analysis_id,
            'timestamp': report.processing_timestamp.isoformat(),
            'websites_count': len(report.websites_analyzed),
            'correlations_count': len(report.correlations),
            'trends_count': len(report.detected_trends),
            'global_metrics': report.global_metrics
        }
        
        # Store in analytics store
        self.analytics_store['correlation_history'].append(analysis_summary)
        
        # Update website profiles
        for url in report.websites_analyzed:
            if url not in self.analytics_store['website_profiles']:
                self.analytics_store['website_profiles'][url] = {
                    'first_analyzed': analysis_summary['timestamp'],
                    'analysis_count': 0,
                    'correlation_scores': [],
                    'trend_participations': []
                }
            
            profile = self.analytics_store['website_profiles'][url]
            profile['analysis_count'] += 1
            profile['last_analyzed'] = analysis_summary['timestamp']
    
    async def create_global_knowledge_graph(
        self,
        website_systems: List[WebsiteGraphRAGSystem]
    ) -> GlobalKnowledgeGraph:
        """Create global knowledge graph spanning multiple websites"""
        
        return await self.knowledge_graph_integrator.integrate_knowledge_graphs(website_systems)
    
    def get_cross_site_analytics_summary(self) -> Dict[str, Any]:
        """Get summary of cross-site analytics data"""
        
        history = list(self.analytics_store['correlation_history'])
        
        if not history:
            return {'message': 'No cross-site analytics data available'}
        
        recent_analyses = history[-5:]  # Last 5 analyses
        
        return {
            'total_cross_site_analyses': len(history),
            'websites_analyzed_count': len(self.analytics_store['website_profiles']),
            'average_correlations_per_analysis': statistics.mean([
                analysis['correlations_count'] for analysis in recent_analyses
            ]) if recent_analyses else 0.0,
            'average_trends_per_analysis': statistics.mean([
                analysis['trends_count'] for analysis in recent_analyses  
            ]) if recent_analyses else 0.0,
            'most_analyzed_websites': [
                (url, profile['analysis_count'])
                for url, profile in sorted(
                    self.analytics_store['website_profiles'].items(),
                    key=lambda x: x[1]['analysis_count'],
                    reverse=True
                )[:5]
            ]
        }


class ContentSimilarityAnalyzer:
    """Specialized component for content similarity analysis"""
    
    def __init__(self):
        self.vectorizer = TfidfVectorizer(max_features=5000, stop_words='english')
        self.similarity_cache = {}
    
    async def calculate_content_similarity(
        self, 
        content_a: str, 
        content_b: str
    ) -> float:
        """Calculate similarity between two content strings"""
        
        cache_key = hash((content_a[:100], content_b[:100]))  # Cache based on first 100 chars
        
        if cache_key in self.similarity_cache:
            return self.similarity_cache[cache_key]
        
        try:
            if not content_a or not content_b:
                similarity = 0.0
            else:
                tfidf_matrix = self.vectorizer.fit_transform([content_a, content_b])
                similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                similarity = float(similarity)
            
            self.similarity_cache[cache_key] = similarity
            return similarity
            
        except Exception as e:
            logger.error(f"Content similarity calculation failed: {e}")
            return 0.0


class TrendDetectionEngine:
    """Specialized engine for detecting trends across time and websites"""
    
    def __init__(self):
        self.trend_cache = deque(maxlen=100)
        self.trend_patterns = self._initialize_trend_patterns()
    
    def _initialize_trend_patterns(self) -> List[Dict[str, Any]]:
        """Initialize patterns for trend detection"""
        return [
            {
                'name': 'topic_emergence',
                'pattern': 'new_topic_across_sites',
                'threshold': 0.6,
                'min_sites': 3
            },
            {
                'name': 'quality_improvement',
                'pattern': 'increasing_quality_scores',
                'threshold': 0.1,  # 10% improvement
                'min_sites': 2
            },
            {
                'name': 'content_type_shift',
                'pattern': 'changing_content_distribution',
                'threshold': 0.2,  # 20% change
                'min_sites': 3
            }
        ]
    
    async def detect_temporal_trends(
        self,
        analysis_history: List[Dict[str, Any]],
        trend_window_days: int = 30
    ) -> List[GlobalTrend]:
        """Detect trends over time from analysis history"""
        
        if len(analysis_history) < 2:
            return []
        
        trends = []
        
        # Sort history by timestamp
        sorted_history = sorted(analysis_history, key=lambda x: x.get('timestamp', ''))
        
        # Analyze trends in different metrics
        time_series_data = self._extract_time_series_data(sorted_history)
        
        for metric_name, values in time_series_data.items():
            if len(values) >= 3:  # Need at least 3 data points
                trend = self._detect_metric_trend(metric_name, values)
                if trend:
                    trends.append(trend)
        
        return trends
    
    def _extract_time_series_data(self, history: List[Dict[str, Any]]) -> Dict[str, List[float]]:
        """Extract time series data from analysis history"""
        
        time_series = defaultdict(list)
        
        for analysis in history:
            metrics = analysis.get('global_metrics', {})
            
            for metric_name, value in metrics.items():
                if isinstance(value, (int, float)):
                    time_series[metric_name].append(value)
        
        return dict(time_series)
    
    def _detect_metric_trend(self, metric_name: str, values: List[float]) -> Optional[GlobalTrend]:
        """Detect trend in a specific metric"""
        
        if len(values) < 3:
            return None
        
        # Calculate trend direction (simple linear trend)
        x = list(range(len(values)))
        y = values
        
        # Calculate correlation coefficient for trend strength
        if len(set(y)) == 1:  # All values the same
            return None
        
        try:
            correlation = np.corrcoef(x, y)[0, 1]
            
            # Only consider significant trends
            if abs(correlation) > 0.6:
                trend_direction = 'increasing' if correlation > 0 else 'decreasing'
                
                return GlobalTrend(
                    trend_id=str(uuid.uuid4()),
                    trend_type='temporal',
                    trend_name=f"{metric_name}_{trend_direction}",
                    trend_strength=abs(correlation),
                    affected_websites=[],  # Temporal trends affect all sites
                    trend_data={
                        'metric_name': metric_name,
                        'trend_direction': trend_direction,
                        'correlation_coefficient': correlation,
                        'value_range': [min(values), max(values)],
                        'recent_value': values[-1],
                        'change_percentage': ((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0
                    },
                    confidence=abs(correlation)
                )
        except:
            pass
        
        return None


class GlobalKnowledgeGraphIntegrator:
    """Integrates knowledge graphs from multiple websites into global graph"""
    
    def __init__(self):
        self.entity_matcher = EntityMatcher()
        self.relationship_merger = RelationshipMerger()
    
    async def integrate_knowledge_graphs(
        self,
        website_systems: List[WebsiteGraphRAGSystem]
    ) -> GlobalKnowledgeGraph:
        """Integrate knowledge graphs from multiple websites"""
        
        graph_id = str(uuid.uuid4())
        participating_websites = [system.url for system in website_systems]
        
        try:
            # Extract all entities and relationships
            all_entities = {}
            all_relationships = []
            
            for system in website_systems:
                kg = getattr(system, 'knowledge_graph', None)
                if kg:
                    entities = getattr(kg, 'entities', [])
                    relationships = getattr(kg, 'relationships', [])
                    
                    # Process entities
                    for entity in entities:
                        entity_id = self._generate_entity_id(entity, system.url)
                        all_entities[entity_id] = {
                            'entity': entity,
                            'source_website': system.url,
                            'cross_site_refs': []
                        }
                    
                    # Process relationships
                    for rel in relationships:
                        relationship_data = {
                            'relationship': rel,
                            'source_website': system.url
                        }
                        all_relationships.append(relationship_data)
            
            # Find cross-site entity matches
            cross_site_connections = await self._find_cross_site_entity_matches(all_entities)
            
            # Create entity clusters
            entity_clusters = await self._create_entity_clusters(all_entities, cross_site_connections)
            
            # Calculate quality score
            quality_score = self._calculate_global_graph_quality(
                all_entities, all_relationships, cross_site_connections
            )
            
            return GlobalKnowledgeGraph(
                graph_id=graph_id,
                participating_websites=participating_websites,
                global_entities=all_entities,
                global_relationships=all_relationships,
                entity_clusters=entity_clusters,
                cross_site_connections=cross_site_connections,
                quality_score=quality_score
            )
            
        except Exception as e:
            logger.error(f"Global knowledge graph integration failed: {e}")
            return GlobalKnowledgeGraph(
                graph_id=graph_id,
                participating_websites=participating_websites,
                global_entities={},
                global_relationships=[],
                entity_clusters={},
                cross_site_connections=[],
                quality_score=0.0
            )
    
    def _generate_entity_id(self, entity: Any, website_url: str) -> str:
        """Generate unique ID for entity"""
        if hasattr(entity, 'label'):
            entity_name = entity.label
        elif isinstance(entity, dict):
            entity_name = entity.get('label', entity.get('name', 'unknown'))
        else:
            entity_name = str(entity)
        
        # Create deterministic ID
        return f"{website_url}#{entity_name.lower().replace(' ', '_')}"
    
    async def _find_cross_site_entity_matches(
        self, 
        all_entities: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Find entities that appear across multiple websites"""
        
        cross_site_connections = []
        entity_names = defaultdict(list)
        
        # Group entities by name
        for entity_id, entity_data in all_entities.items():
            entity = entity_data['entity']
            if hasattr(entity, 'label'):
                name = entity.label.lower()
            elif isinstance(entity, dict):
                name = entity.get('label', '').lower()
            else:
                name = str(entity).lower()
            
            if name:
                entity_names[name].append((entity_id, entity_data))
        
        # Find cross-site matches
        for name, entity_list in entity_names.items():
            if len(entity_list) > 1:
                # Check if entities are from different websites
                websites = set(data['source_website'] for _, data in entity_list)
                
                if len(websites) > 1:
                    connection = {
                        'entity_name': name,
                        'matched_entities': [entity_id for entity_id, _ in entity_list],
                        'participating_websites': list(websites),
                        'connection_strength': len(entity_list) / len(websites),
                        'connection_type': 'exact_match'
                    }
                    cross_site_connections.append(connection)
        
        return cross_site_connections
    
    async def _create_entity_clusters(
        self,
        all_entities: Dict[str, Dict[str, Any]],
        cross_site_connections: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """Create topical clusters of entities"""
        
        # Simple clustering based on entity co-occurrence patterns
        clusters = defaultdict(list)
        
        # Create topic-based clusters
        topic_keywords = {
            'technology': ['ai', 'artificial', 'intelligence', 'machine', 'learning', 'software', 'computer'],
            'business': ['company', 'business', 'market', 'finance', 'economy', 'revenue', 'profit'],
            'science': ['research', 'study', 'experiment', 'theory', 'data', 'analysis', 'scientific'],
            'education': ['university', 'college', 'education', 'student', 'professor', 'academic'],
            'health': ['health', 'medical', 'medicine', 'doctor', 'patient', 'treatment']
        }
        
        for entity_id, entity_data in all_entities.items():
            entity = entity_data['entity']
            
            # Get entity name
            if hasattr(entity, 'label'):
                entity_name = entity.label.lower()
            elif isinstance(entity, dict):
                entity_name = entity.get('label', '').lower()
            else:
                entity_name = str(entity).lower()
            
            # Classify into topic clusters
            best_topic = 'general'
            best_score = 0
            
            for topic, keywords in topic_keywords.items():
                score = sum(1 for keyword in keywords if keyword in entity_name)
                if score > best_score:
                    best_score = score
                    best_topic = topic
            
            clusters[best_topic].append(entity_id)
        
        return dict(clusters)
    
    def _calculate_global_graph_quality(
        self,
        entities: Dict[str, Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        cross_site_connections: List[Dict[str, Any]]
    ) -> float:
        """Calculate quality score for global knowledge graph"""
        
        if not entities:
            return 0.0
        
        # Calculate various quality factors
        entity_count = len(entities)
        relationship_count = len(relationships)
        cross_site_count = len(cross_site_connections)
        
        # Quality factors
        connectivity = relationship_count / max(1, entity_count)
        cross_site_ratio = cross_site_count / max(1, entity_count)
        
        # Normalize and combine factors
        quality_score = (
            min(1.0, connectivity / 2.0) * 0.4 +  # Connectivity factor
            min(1.0, cross_site_ratio * 10.0) * 0.4 +  # Cross-site factor
            min(1.0, entity_count / 100.0) * 0.2  # Scale factor
        )
        
        return quality_score


class ContentClusterAnalyzer:
    """Specialized analyzer for content clustering across websites"""
    
    def __init__(self):
        self.clustering_cache = {}
    
    async def cluster_websites_by_content(
        self,
        website_data: Dict[str, Dict[str, Any]],
        n_clusters: Optional[int] = None
    ) -> Dict[str, Any]:
        """Cluster websites based on content characteristics"""
        
        urls = list(website_data.keys())
        
        if len(urls) < 2:
            return {'message': 'Insufficient websites for clustering'}
        
        try:
            # Create feature matrix
            features = []
            feature_names = ['content_count', 'entity_count', 'text_length_log']
            
            for url in urls:
                data = website_data[url]
                feature_vector = [
                    data.get('content_count', 0),
                    data.get('entity_count', 0),
                    math.log10(max(1, data.get('total_text_length', 1)))
                ]
                features.append(feature_vector)
            
            # Normalize features
            scaler = StandardScaler()
            normalized_features = scaler.fit_transform(features)
            
            # Determine optimal number of clusters
            if n_clusters is None:
                n_clusters = min(len(urls) // 2, 5)
                n_clusters = max(2, n_clusters)
            
            # Perform clustering
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            labels = kmeans.fit_predict(normalized_features)
            
            # Organize results
            clusters = defaultdict(list)
            for i, url in enumerate(urls):
                clusters[f"cluster_{labels[i]}"].append(url)
            
            return {
                'clusters': dict(clusters),
                'cluster_centers': kmeans.cluster_centers_.tolist(),
                'feature_names': feature_names,
                'n_clusters': n_clusters
            }
            
        except Exception as e:
            logger.error(f"Website clustering failed: {e}")
            return {'error': f"Clustering failed: {str(e)}"}


class EntityMatcher:
    """Matches entities across different websites"""
    
    def __init__(self):
        self.matching_cache = {}
    
    async def find_entity_matches(
        self,
        entities_a: List[Any],
        entities_b: List[Any]
    ) -> List[Tuple[Any, Any, float]]:
        """Find matching entities between two entity lists"""
        
        matches = []
        
        for entity_a in entities_a:
            for entity_b in entities_b:
                similarity = await self._calculate_entity_similarity(entity_a, entity_b)
                
                if similarity > 0.8:  # High similarity threshold
                    matches.append((entity_a, entity_b, similarity))
        
        return matches
    
    async def _calculate_entity_similarity(self, entity_a: Any, entity_b: Any) -> float:
        """Calculate similarity between two entities"""
        
        # Extract entity names
        name_a = self._extract_entity_name(entity_a)
        name_b = self._extract_entity_name(entity_b)
        
        if not name_a or not name_b:
            return 0.0
        
        # Simple string similarity
        name_a_lower = name_a.lower()
        name_b_lower = name_b.lower()
        
        # Exact match
        if name_a_lower == name_b_lower:
            return 1.0
        
        # Partial match
        if name_a_lower in name_b_lower or name_b_lower in name_a_lower:
            return 0.8
        
        # Word overlap
        words_a = set(name_a_lower.split())
        words_b = set(name_b_lower.split())
        
        if not words_a or not words_b:
            return 0.0
        
        overlap = len(words_a.intersection(words_b))
        union = len(words_a.union(words_b))
        
        return overlap / union if union > 0 else 0.0
    
    def _extract_entity_name(self, entity: Any) -> str:
        """Extract name from entity object"""
        if hasattr(entity, 'label'):
            return entity.label
        elif isinstance(entity, dict):
            return entity.get('label', entity.get('name', ''))
        else:
            return str(entity)


class RelationshipMerger:
    """Merges relationships from multiple knowledge graphs"""
    
    async def merge_relationships(
        self,
        relationship_lists: List[List[Any]]
    ) -> List[Dict[str, Any]]:
        """Merge relationships from multiple sources"""
        
        merged_relationships = []
        relationship_signatures = set()
        
        for relationships in relationship_lists:
            for rel in relationships:
                signature = self._create_relationship_signature(rel)
                
                if signature not in relationship_signatures:
                    relationship_signatures.add(signature)
                    merged_relationships.append({
                        'relationship': rel,
                        'signature': signature,
                        'sources': 1
                    })
                else:
                    # Find existing relationship and increment sources
                    for merged_rel in merged_relationships:
                        if merged_rel['signature'] == signature:
                            merged_rel['sources'] += 1
                            break
        
        return merged_relationships
    
    def _create_relationship_signature(self, relationship: Any) -> str:
        """Create unique signature for relationship"""
        if hasattr(relationship, 'source') and hasattr(relationship, 'target'):
            return f"{relationship.source}_{relationship.target}_{getattr(relationship, 'relation_type', 'unknown')}"
        elif isinstance(relationship, dict):
            source = relationship.get('source', '')
            target = relationship.get('target', '')
            rel_type = relationship.get('type', relationship.get('relation_type', 'unknown'))
            return f"{source}_{target}_{rel_type}"
        else:
            return str(relationship)


# Convenience functions for quick analysis
async def analyze_multiple_websites(
    website_systems: List[WebsiteGraphRAGSystem],
    config: Optional[Dict[str, Any]] = None
) -> CrossSiteAnalysisReport:
    """
    Convenience function for quick cross-website analysis
    
    Args:
        website_systems: List of processed website systems
        config: Optional configuration for analysis
        
    Returns:
        Comprehensive cross-site analysis report
    """
    
    analyzer = CrossWebsiteAnalyzer(config)
    return await analyzer.analyze_cross_site_correlations(website_systems)


async def create_global_knowledge_graph(
    website_systems: List[WebsiteGraphRAGSystem]
) -> GlobalKnowledgeGraph:
    """
    Create global knowledge graph from multiple websites
    
    Args:
        website_systems: List of processed website systems
        
    Returns:
        Integrated global knowledge graph
    """
    
    analyzer = CrossWebsiteAnalyzer()
    return await analyzer.create_global_knowledge_graph(website_systems)


# Example usage and testing
async def main():
    """Example usage of cross-website analytics"""
    
    # Mock website systems for testing
    mock_system_1 = type('MockWebsiteSystem', (), {
        'url': 'https://tech-blog.example.com',
        'get_content_overview': lambda: {
            'total_pages': 25,
            'total_pdfs': 3,
            'total_media': 5
        }
    })()
    
    mock_system_2 = type('MockWebsiteSystem', (), {
        'url': 'https://ai-research.example.com', 
        'get_content_overview': lambda: {
            'total_pages': 15,
            'total_pdfs': 8,
            'total_media': 2
        }
    })()
    
    # Run cross-site analysis
    analyzer = CrossWebsiteAnalyzer()
    report = await analyzer.analyze_cross_site_correlations([mock_system_1, mock_system_2])
    
    print("🌐 Cross-Website Analytics Results:")
    print(f"Websites analyzed: {len(report.websites_analyzed)}")
    print(f"Correlations found: {len(report.correlations)}")
    print(f"Global trends detected: {len(report.detected_trends)}")
    print(f"Processing time: {report.processing_time_seconds:.2f}s")
    
    print("\n📊 Global Metrics:")
    for metric, value in report.global_metrics.items():
        print(f"  {metric}: {value}")
    
    print(f"\n💡 Recommendations:")
    for i, rec in enumerate(report.recommendations, 1):
        print(f"  {i}. {rec}")


if __name__ == '__main__':
    asyncio.run(main())
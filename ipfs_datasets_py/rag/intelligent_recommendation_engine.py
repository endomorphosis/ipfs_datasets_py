#!/usr/bin/env python3
"""
Intelligent Recommendation Engine - Advanced content discovery and query suggestions

This module provides an intelligent recommendation system for GraphRAG content discovery
with machine learning-powered suggestions, personalized recommendations, and cross-content
correlation analysis.

Features:
- Intelligent query suggestions based on content analysis
- Personalized recommendations using user behavior
- Cross-content correlation and discovery
- Semantic similarity matching for related content
- Trend analysis and content popularity tracking
- Real-time recommendation optimization
- Multilingual support for global content

Usage:
    engine = IntelligentRecommendationEngine()
    suggestions = await engine.generate_query_suggestions(query, context)
    related_content = await engine.discover_related_content(content_item)
"""

import os
import json
import anyio
import logging
from typing import Dict, List, Optional, Any, Union, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import uuid
import re
from collections import defaultdict, Counter, deque
import math

# Import GraphRAG components
from ipfs_datasets_py.website_graphrag_system import WebsiteGraphRAGSystem
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import KnowledgeGraph, Entity, Relationship

logger = logging.getLogger(__name__)


@dataclass
class QuerySuggestion:
    """Query suggestion with relevance and context"""
    
    query_text: str
    relevance_score: float
    suggestion_type: str  # related, expansion, refinement, trending
    context: str
    expected_results: int
    confidence: float
    
    # Supporting information
    related_entities: List[str] = field(default_factory=list)
    related_topics: List[str] = field(default_factory=list)
    estimated_quality: float = 0.8


@dataclass 
class ContentRecommendation:
    """Content recommendation with similarity and relevance metrics"""
    
    content_id: str
    content_type: str  # html, pdf, audio, video, entity
    title: str
    url: str
    similarity_score: float
    relevance_score: float
    
    # Content metadata
    content_summary: str = ""
    key_entities: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    content_quality: float = 0.8
    
    # Recommendation reasoning
    recommendation_reason: str = ""
    related_queries: List[str] = field(default_factory=list)


@dataclass
class UserProfile:
    """User behavior profile for personalized recommendations"""
    
    user_id: str
    
    # Query patterns
    frequent_topics: List[str] = field(default_factory=list)
    query_complexity: str = "medium"  # simple, medium, complex
    preferred_content_types: List[str] = field(default_factory=list)
    
    # Behavior patterns
    session_duration: float = 0.0
    queries_per_session: int = 0
    exploration_depth: str = "medium"  # shallow, medium, deep
    
    # Preferences
    language_preference: str = "en"
    domain_expertise: List[str] = field(default_factory=list)
    
    # Analytics
    total_queries: int = 0
    last_active: datetime = field(default_factory=datetime.now)
    success_rate: float = 0.8


class QueryAnalyzer:
    """Advanced query analysis for intent detection and expansion"""
    
    def __init__(self):
        self.query_patterns = {
            "definition": [r"what is", r"define", r"meaning of"],
            "comparison": [r"vs", r"versus", r"compare", r"difference"],
            "how_to": [r"how to", r"how do", r"steps to"],
            "research": [r"research", r"study", r"analysis", r"findings"],
            "technical": [r"algorithm", r"implementation", r"code", r"technical"],
            "temporal": [r"recent", r"latest", r"current", r"new", r"trends"]
        }
        
        self.technical_domains = {
            "ai": ["artificial intelligence", "machine learning", "deep learning", "neural networks"],
            "tech": ["software", "programming", "development", "engineering"],
            "science": ["research", "study", "experiment", "analysis", "findings"],
            "business": ["strategy", "market", "business", "economic", "financial"]
        }
    
    async def analyze_intent(self, query: str) -> Dict[str, Any]:
        """Analyze query intent and characteristics"""
        
        query_lower = query.lower()
        
        # Detect query type
        query_type = self._detect_query_type(query_lower)
        
        # Detect domain
        domain = self._detect_domain(query_lower)
        
        # Extract key terms
        key_terms = self._extract_key_terms(query)
        
        # Assess complexity
        complexity = self._assess_query_complexity(query)
        
        # Detect entities mentioned
        mentioned_entities = self._detect_entities(query)
        
        return {
            "original_query": query,
            "query_type": query_type,
            "domain": domain,
            "key_terms": key_terms,
            "complexity": complexity,
            "mentioned_entities": mentioned_entities,
            "intent_confidence": self._calculate_intent_confidence(query_type, domain)
        }
    
    def _detect_query_type(self, query: str) -> str:
        """Detect the type/intent of the query"""
        
        for query_type, patterns in self.query_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query):
                    return query_type
        
        return "general"
    
    def _detect_domain(self, query: str) -> str:
        """Detect the domain/field of the query"""
        
        for domain, keywords in self.technical_domains.items():
            for keyword in keywords:
                if keyword in query:
                    return domain
        
        return "general"
    
    def _extract_key_terms(self, query: str) -> List[str]:
        """Extract key terms from query"""
        
        # Simple keyword extraction (in production, use NLP libraries)
        terms = re.findall(r'\b[a-zA-Z]{3,}\b', query.lower())
        
        # Filter stop words
        stop_words = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her", "was", "one", "our", "out", "day", "get", "has", "him", "his", "how", "man", "new", "now", "old", "see", "two", "way", "who", "boy", "did", "its", "let", "put", "say", "she", "too", "use"}
        
        filtered_terms = [term for term in terms if term not in stop_words]
        
        # Return most relevant terms
        return filtered_terms[:10]
    
    def _assess_query_complexity(self, query: str) -> str:
        """Assess query complexity"""
        
        word_count = len(query.split())
        has_operators = any(op in query.lower() for op in ["and", "or", "not", "near"])
        has_quotes = '"' in query
        
        if word_count <= 3 and not has_operators:
            return "simple"
        elif word_count <= 8 and (has_operators or has_quotes):
            return "medium"
        else:
            return "complex"
    
    def _detect_entities(self, query: str) -> List[str]:
        """Detect potential entities mentioned in query"""
        
        # Simple entity detection (in production, use NER)
        entities = []
        
        # Check for capitalized words (potential proper nouns)
        words = query.split()
        for word in words:
            if word[0].isupper() and len(word) > 2:
                entities.append(word)
        
        return entities
    
    def _calculate_intent_confidence(self, query_type: str, domain: str) -> float:
        """Calculate confidence in intent detection"""
        
        confidence = 0.5  # Base confidence
        
        if query_type != "general":
            confidence += 0.3
        
        if domain != "general":
            confidence += 0.2
        
        return min(confidence, 1.0)


class ContentSimilarityEngine:
    """Content similarity calculation and related content discovery"""
    
    def __init__(self):
        self.similarity_cache = {}
        self.content_vectors = {}  # Cache content vectors for efficiency
    
    async def calculate_content_similarity(
        self,
        content1: Dict[str, Any],
        content2: Dict[str, Any]
    ) -> float:
        """Calculate similarity between two content items"""
        
        cache_key = f"{content1.get('id', '')}:{content2.get('id', '')}"
        if cache_key in self.similarity_cache:
            return self.similarity_cache[cache_key]
        
        # Extract text content
        text1 = content1.get("text_content", "")
        text2 = content2.get("text_content", "")
        
        # Calculate similarity using multiple methods
        text_similarity = self._calculate_text_similarity(text1, text2)
        entity_similarity = self._calculate_entity_similarity(content1, content2)
        topic_similarity = self._calculate_topic_similarity(content1, content2)
        
        # Weighted combination
        overall_similarity = (
            text_similarity * 0.5 +
            entity_similarity * 0.3 +
            topic_similarity * 0.2
        )
        
        # Cache result
        self.similarity_cache[cache_key] = overall_similarity
        
        return overall_similarity
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity using TF-IDF cosine similarity"""
        
        if not text1 or not text2:
            return 0.0
        
        # Simple TF-IDF implementation
        def tokenize(text):
            return re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        
        tokens1 = tokenize(text1)
        tokens2 = tokenize(text2)
        
        # Create vocabulary
        vocab = set(tokens1 + tokens2)
        
        if not vocab:
            return 0.0
        
        # Calculate TF-IDF vectors
        def calculate_tf_idf(tokens, vocab):
            tf = Counter(tokens)
            total_tokens = len(tokens)
            
            tf_idf = {}
            for word in vocab:
                tf_score = tf[word] / total_tokens if total_tokens > 0 else 0
                # Simple IDF (in production, use proper document frequency)
                idf_score = math.log(2 / (1 + (1 if word in tokens else 0)))
                tf_idf[word] = tf_score * idf_score
            
            return tf_idf
        
        vec1 = calculate_tf_idf(tokens1, vocab)
        vec2 = calculate_tf_idf(tokens2, vocab)
        
        # Calculate cosine similarity
        dot_product = sum(vec1[word] * vec2[word] for word in vocab)
        magnitude1 = math.sqrt(sum(vec1[word] ** 2 for word in vocab))
        magnitude2 = math.sqrt(sum(vec2[word] ** 2 for word in vocab))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        
        return dot_product / (magnitude1 * magnitude2)
    
    def _calculate_entity_similarity(self, content1: Dict[str, Any], content2: Dict[str, Any]) -> float:
        """Calculate similarity based on shared entities"""
        
        entities1 = set(content1.get("entities", []))
        entities2 = set(content2.get("entities", []))
        
        if not entities1 and not entities2:
            return 0.5  # Both have no entities
        
        if not entities1 or not entities2:
            return 0.0  # One has no entities
        
        # Jaccard similarity
        intersection = len(entities1.intersection(entities2))
        union = len(entities1.union(entities2))
        
        return intersection / union if union > 0 else 0.0
    
    def _calculate_topic_similarity(self, content1: Dict[str, Any], content2: Dict[str, Any]) -> float:
        """Calculate similarity based on topics/categories"""
        
        topics1 = set(content1.get("topics", []))
        topics2 = set(content2.get("topics", []))
        
        if not topics1 and not topics2:
            return 0.5  # Both have no topics
        
        if not topics1 or not topics2:
            return 0.0  # One has no topics
        
        # Jaccard similarity
        intersection = len(topics1.intersection(topics2))
        union = len(topics1.union(topics2))
        
        return intersection / union if union > 0 else 0.0


class TrendAnalyzer:
    """Analyze content trends and popularity patterns"""
    
    def __init__(self):
        self.query_history = deque(maxlen=10000)  # Keep last 10k queries
        self.content_access_patterns = defaultdict(list)
        self.trending_topics = deque(maxlen=100)
    
    def record_query(self, query: str, results: List[Dict[str, Any]], user_id: str = None):
        """Record query for trend analysis"""
        
        query_record = {
            "timestamp": datetime.now(),
            "query": query,
            "results_count": len(results),
            "user_id": user_id or "anonymous"
        }
        
        self.query_history.append(query_record)
        
        # Track content access patterns
        for result in results:
            content_id = result.get("id", "unknown")
            self.content_access_patterns[content_id].append(datetime.now())
    
    def get_trending_queries(self, time_window: int = 24) -> List[Dict[str, Any]]:
        """Get trending queries in the last N hours"""
        
        cutoff_time = datetime.now() - timedelta(hours=time_window)
        recent_queries = [
            q for q in self.query_history
            if q["timestamp"] > cutoff_time
        ]
        
        # Count query frequency
        query_counts = Counter(q["query"].lower() for q in recent_queries)
        
        # Calculate trend scores
        trending = []
        for query, count in query_counts.most_common(20):
            # Calculate trend score based on frequency and recency
            recent_count = sum(
                1 for q in recent_queries[-100:]  # Last 100 queries
                if q["query"].lower() == query
            )
            
            trend_score = count + (recent_count * 2)  # Weight recent queries more
            
            trending.append({
                "query": query,
                "frequency": count,
                "trend_score": trend_score,
                "last_seen": max(q["timestamp"] for q in recent_queries if q["query"].lower() == query).isoformat()
            })
        
        return sorted(trending, key=lambda x: x["trend_score"], reverse=True)[:10]
    
    def get_trending_topics(self, knowledge_graph: KnowledgeGraph = None) -> List[Dict[str, Any]]:
        """Extract trending topics from queries and content"""
        
        # Extract topics from recent queries
        recent_queries = list(self.query_history)[-200:]  # Last 200 queries
        all_query_text = " ".join(q["query"] for q in recent_queries)
        
        # Simple topic extraction (in production, use topic modeling)
        topics = self._extract_topics_from_text(all_query_text)
        
        # If knowledge graph available, include entity trends
        if knowledge_graph:
            entity_trends = self._analyze_entity_trends(knowledge_graph)
            topics.extend(entity_trends)
        
        # Score and rank topics
        topic_scores = self._score_topics(topics)
        
        return [
            {
                "topic": topic,
                "score": score,
                "trend": "rising" if score > 5 else "stable",
                "related_queries": self._find_related_queries(topic)[:3]
            }
            for topic, score in topic_scores[:10]
        ]
    
    def _extract_topics_from_text(self, text: str) -> List[str]:
        """Extract topics from text using keyword analysis"""
        
        # Extract meaningful terms
        terms = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        
        # Count term frequency
        term_counts = Counter(terms)
        
        # Filter to get topics (remove common words)
        stop_words = {"that", "this", "with", "from", "they", "been", "have", "were", "said", "each", "which", "their", "time", "will", "about", "would", "there", "could", "other", "after", "first", "well", "many", "some", "what", "know", "while", "here", "more", "very", "when", "much", "more"}
        
        topics = [
            term for term, count in term_counts.most_common(20)
            if term not in stop_words and count > 1
        ]
        
        return topics
    
    def _analyze_entity_trends(self, knowledge_graph: KnowledgeGraph) -> List[str]:
        """Analyze trending entities from knowledge graph"""
        
        # Mock implementation - in production, analyze entity mention frequency
        if hasattr(knowledge_graph, 'entities'):
            entity_names = [entity.name for entity in knowledge_graph.entities[:10]]
            return entity_names
        
        return []
    
    def _score_topics(self, topics: List[str]) -> List[Tuple[str, float]]:
        """Score topics based on various factors"""
        
        topic_scores = []
        
        for topic in topics:
            # Base score from frequency in queries
            query_mentions = sum(
                1 for q in self.query_history
                if topic in q["query"].lower()
            )
            
            # Recent activity boost
            recent_mentions = sum(
                1 for q in list(self.query_history)[-50:]  # Last 50 queries
                if topic in q["query"].lower()
            )
            
            # Calculate final score
            score = query_mentions + (recent_mentions * 2)
            topic_scores.append((topic, score))
        
        return sorted(topic_scores, key=lambda x: x[1], reverse=True)
    
    def _find_related_queries(self, topic: str) -> List[str]:
        """Find queries related to a topic"""
        
        related = [
            q["query"] for q in self.query_history
            if topic in q["query"].lower()
        ]
        
        return list(set(related))[:5]


class PersonalizationEngine:
    """Personalized recommendation engine based on user behavior"""
    
    def __init__(self):
        self.user_profiles: Dict[str, UserProfile] = {}
        self.collaborative_patterns = defaultdict(list)
    
    def update_user_profile(
        self,
        user_id: str,
        query: str,
        results: List[Dict[str, Any]],
        interaction_data: Dict[str, Any] = None
    ):
        """Update user profile based on query and interaction"""
        
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = UserProfile(user_id=user_id)
        
        profile = self.user_profiles[user_id]
        
        # Update query statistics
        profile.total_queries += 1
        profile.last_active = datetime.now()
        
        # Extract topics from query
        query_topics = self._extract_query_topics(query)
        profile.frequent_topics.extend(query_topics)
        
        # Keep only most recent topics (sliding window)
        profile.frequent_topics = profile.frequent_topics[-50:]
        
        # Update content type preferences
        if results:
            content_types = [r.get("content_type", "unknown") for r in results]
            profile.preferred_content_types.extend(content_types)
            profile.preferred_content_types = profile.preferred_content_types[-20:]
        
        # Update complexity preference
        complexity = self._assess_query_complexity(query)
        if complexity == "complex":
            profile.query_complexity = "complex"
        elif complexity == "simple" and profile.query_complexity == "complex":
            profile.query_complexity = "medium"  # Moderate down
    
    def get_personalized_suggestions(
        self,
        user_id: str,
        current_query: str,
        context: Dict[str, Any] = None
    ) -> List[QuerySuggestion]:
        """Generate personalized query suggestions"""
        
        if user_id not in self.user_profiles:
            return self._get_default_suggestions(current_query, context)
        
        profile = self.user_profiles[user_id]
        
        suggestions = []
        
        # Suggestions based on frequent topics
        for topic in set(profile.frequent_topics):
            if topic not in current_query.lower():
                suggestion = QuerySuggestion(
                    query_text=f"{current_query} {topic}",
                    relevance_score=0.8,
                    suggestion_type="expansion",
                    context=f"Based on your interest in {topic}",
                    expected_results=15,
                    confidence=0.7,
                    related_topics=[topic]
                )
                suggestions.append(suggestion)
        
        # Suggestions based on preferred content types
        if profile.preferred_content_types:
            most_common_type = Counter(profile.preferred_content_types).most_common(1)[0][0]
            suggestion = QuerySuggestion(
                query_text=current_query,
                relevance_score=0.9,
                suggestion_type="refinement",
                context=f"Filter by {most_common_type} content",
                expected_results=12,
                confidence=0.8,
                related_topics=[]
            )
            suggestions.append(suggestion)
        
        # Collaborative filtering suggestions
        similar_users = self._find_similar_users(user_id)
        for similar_user_id in similar_users[:2]:
            similar_profile = self.user_profiles[similar_user_id]
            for topic in similar_profile.frequent_topics[:3]:
                if topic not in current_query.lower():
                    suggestion = QuerySuggestion(
                        query_text=f"{current_query} {topic}",
                        relevance_score=0.7,
                        suggestion_type="related",
                        context=f"Users with similar interests also search for {topic}",
                        expected_results=10,
                        confidence=0.6,
                        related_topics=[topic]
                    )
                    suggestions.append(suggestion)
        
        # Sort by relevance and return top suggestions
        suggestions.sort(key=lambda x: x.relevance_score, reverse=True)
        return suggestions[:8]
    
    def _get_default_suggestions(self, query: str, context: Dict[str, Any] = None) -> List[QuerySuggestion]:
        """Generate default suggestions for new users"""
        
        suggestions = []
        
        # Query expansion suggestions
        common_expansions = {
            "ai": ["machine learning", "deep learning", "neural networks"],
            "machine learning": ["algorithms", "models", "training"],
            "research": ["methodology", "findings", "analysis"],
            "technology": ["innovation", "development", "trends"]
        }
        
        query_lower = query.lower()
        for term, expansions in common_expansions.items():
            if term in query_lower:
                for expansion in expansions:
                    suggestion = QuerySuggestion(
                        query_text=f"{query} {expansion}",
                        relevance_score=0.7,
                        suggestion_type="expansion",
                        context=f"Related to {term}",
                        expected_results=12,
                        confidence=0.6,
                        related_topics=[expansion]
                    )
                    suggestions.append(suggestion)
        
        return suggestions[:5]
    
    def _extract_query_topics(self, query: str) -> List[str]:
        """Extract topics from a query"""
        
        # Simple topic extraction
        words = re.findall(r'\b[a-zA-Z]{4,}\b', query.lower())
        
        # Filter meaningful terms
        stop_words = {"that", "this", "with", "from", "what", "where", "when", "how"}
        topics = [word for word in words if word not in stop_words]
        
        return topics[:5]
    
    def _assess_query_complexity(self, query: str) -> str:
        """Assess query complexity"""
        
        word_count = len(query.split())
        
        if word_count <= 3:
            return "simple"
        elif word_count <= 8:
            return "medium"
        else:
            return "complex"
    
    def _find_similar_users(self, user_id: str) -> List[str]:
        """Find users with similar interests using collaborative filtering"""
        
        if user_id not in self.user_profiles:
            return []
        
        target_profile = self.user_profiles[user_id]
        target_topics = set(target_profile.frequent_topics)
        
        similarities = []
        
        for other_user_id, other_profile in self.user_profiles.items():
            if other_user_id == user_id:
                continue
            
            other_topics = set(other_profile.frequent_topics)
            
            # Calculate topic similarity
            intersection = len(target_topics.intersection(other_topics))
            union = len(target_topics.union(other_topics))
            
            similarity = intersection / union if union > 0 else 0.0
            
            if similarity > 0.3:  # Similarity threshold
                similarities.append((other_user_id, similarity))
        
        # Return most similar users
        similarities.sort(key=lambda x: x[1], reverse=True)
        return [user_id for user_id, _ in similarities[:5]]


class IntelligentRecommendationEngine:
    """
    Advanced recommendation engine for GraphRAG content discovery.
    
    Provides intelligent query suggestions, personalized content recommendations,
    and cross-content correlation analysis using machine learning and behavioral analysis.
    """
    
    def __init__(self):
        self.query_analyzer = QueryAnalyzer()
        self.similarity_engine = ContentSimilarityEngine()
        self.trend_analyzer = TrendAnalyzer()
        self.personalization_engine = PersonalizationEngine()
        
        # Recommendation cache
        self.suggestion_cache = {}
        self.recommendation_cache = {}
        
        # Analytics
        self.recommendation_metrics = {
            "total_suggestions_generated": 0,
            "total_recommendations_generated": 0,
            "click_through_rate": 0.0,
            "user_satisfaction_score": 0.0
        }
    
    async def generate_query_suggestions(
        self,
        current_query: str,
        website_system: WebsiteGraphRAGSystem,
        user_id: str = None,
        context: Dict[str, Any] = None
    ) -> List[QuerySuggestion]:
        """
        Generate intelligent query suggestions based on current query and context.
        
        Args:
            current_query: The user's current query
            website_system: GraphRAG system with processed content
            user_id: Optional user ID for personalization
            context: Additional context for suggestions
        
        Returns:
            List of intelligent query suggestions with relevance scores
        """
        
        # Check cache first
        cache_key = f"{current_query}:{user_id}:{website_system.url}"
        if cache_key in self.suggestion_cache:
            cached_result = self.suggestion_cache[cache_key]
            if datetime.now() - cached_result["timestamp"] < timedelta(minutes=5):
                return cached_result["suggestions"]
        
        suggestions = []
        
        # Analyze current query
        query_analysis = await self.query_analyzer.analyze_intent(current_query)
        
        # Generate different types of suggestions
        
        # 1. Expansion suggestions based on knowledge graph
        expansion_suggestions = await self._generate_expansion_suggestions(
            current_query, query_analysis, website_system.knowledge_graph
        )
        suggestions.extend(expansion_suggestions)
        
        # 2. Refinement suggestions based on content
        refinement_suggestions = await self._generate_refinement_suggestions(
            current_query, query_analysis, website_system
        )
        suggestions.extend(refinement_suggestions)
        
        # 3. Related content suggestions
        related_suggestions = await self._generate_related_suggestions(
            current_query, query_analysis, website_system
        )
        suggestions.extend(related_suggestions)
        
        # 4. Trending suggestions
        trending_suggestions = self._generate_trending_suggestions(current_query)
        suggestions.extend(trending_suggestions)
        
        # 5. Personalized suggestions (if user provided)
        if user_id:
            personalized_suggestions = self.personalization_engine.get_personalized_suggestions(
                user_id, current_query, context
            )
            suggestions.extend(personalized_suggestions)
        
        # Remove duplicates and rank by relevance
        unique_suggestions = self._deduplicate_suggestions(suggestions)
        ranked_suggestions = sorted(unique_suggestions, key=lambda x: x.relevance_score, reverse=True)
        
        # Take top suggestions
        final_suggestions = ranked_suggestions[:10]
        
        # Cache results
        self.suggestion_cache[cache_key] = {
            "timestamp": datetime.now(),
            "suggestions": final_suggestions
        }
        
        # Update metrics
        self.recommendation_metrics["total_suggestions_generated"] += len(final_suggestions)
        
        return final_suggestions
    
    async def discover_related_content(
        self,
        source_content: Dict[str, Any],
        website_system: WebsiteGraphRAGSystem,
        max_recommendations: int = 10
    ) -> List[ContentRecommendation]:
        """
        Discover content related to the source content using similarity analysis.
        
        Args:
            source_content: Source content item to find related content for
            website_system: GraphRAG system with all processed content
            max_recommendations: Maximum number of recommendations to return
        
        Returns:
            List of content recommendations with similarity scores
        """
        
        recommendations = []
        
        # Get all available content for comparison
        all_content = self._get_all_content_items(website_system)
        
        # Calculate similarities
        for content_item in all_content:
            if content_item.get("id") == source_content.get("id"):
                continue  # Skip self
            
            # Calculate similarity
            similarity = await self.similarity_engine.calculate_content_similarity(
                source_content, content_item
            )
            
            if similarity > 0.3:  # Similarity threshold
                
                # Calculate relevance score
                relevance = self._calculate_content_relevance(source_content, content_item)
                
                # Generate recommendation reason
                reason = self._generate_recommendation_reason(
                    source_content, content_item, similarity
                )
                
                recommendation = ContentRecommendation(
                    content_id=content_item.get("id", str(uuid.uuid4())),
                    content_type=content_item.get("content_type", "unknown"),
                    title=content_item.get("title", "Untitled"),
                    url=content_item.get("url", ""),
                    similarity_score=similarity,
                    relevance_score=relevance,
                    content_summary=content_item.get("summary", "")[:200],
                    key_entities=content_item.get("entities", [])[:5],
                    topics=content_item.get("topics", [])[:3],
                    recommendation_reason=reason
                )
                
                recommendations.append(recommendation)
        
        # Sort by combined similarity and relevance score
        recommendations.sort(
            key=lambda x: (x.similarity_score + x.relevance_score) / 2,
            reverse=True
        )
        
        # Update metrics
        self.recommendation_metrics["total_recommendations_generated"] += len(recommendations)
        
        return recommendations[:max_recommendations]
    
    async def _generate_expansion_suggestions(
        self,
        query: str,
        analysis: Dict[str, Any],
        knowledge_graph: KnowledgeGraph
    ) -> List[QuerySuggestion]:
        """Generate query expansion suggestions based on knowledge graph"""
        
        suggestions = []
        key_terms = analysis["key_terms"]
        
        # Find related entities in knowledge graph
        related_entities = self._find_related_entities(key_terms, knowledge_graph)
        
        for entity in related_entities[:3]:
            suggestion = QuerySuggestion(
                query_text=f"{query} {entity}",
                relevance_score=0.8,
                suggestion_type="expansion",
                context=f"Related entity: {entity}",
                expected_results=12,
                confidence=0.7,
                related_entities=[entity]
            )
            suggestions.append(suggestion)
        
        return suggestions
    
    async def _generate_refinement_suggestions(
        self,
        query: str,
        analysis: Dict[str, Any],
        website_system: WebsiteGraphRAGSystem
    ) -> List[QuerySuggestion]:
        """Generate query refinement suggestions"""
        
        suggestions = []
        
        # Content type refinements
        content_types = ["html", "pdf", "audio", "video"]
        for content_type in content_types:
            suggestion = QuerySuggestion(
                query_text=query,
                relevance_score=0.7,
                suggestion_type="refinement",
                context=f"Search only {content_type} content",
                expected_results=8,
                confidence=0.6
            )
            suggestions.append(suggestion)
        
        # Temporal refinements
        if analysis["query_type"] != "temporal":
            suggestion = QuerySuggestion(
                query_text=f"recent {query}",
                relevance_score=0.6,
                suggestion_type="refinement", 
                context="Focus on recent content",
                expected_results=6,
                confidence=0.5
            )
            suggestions.append(suggestion)
        
        return suggestions
    
    async def _generate_related_suggestions(
        self,
        query: str,
        analysis: Dict[str, Any],
        website_system: WebsiteGraphRAGSystem
    ) -> List[QuerySuggestion]:
        """Generate suggestions for related content"""
        
        suggestions = []
        domain = analysis["domain"]
        
        # Domain-specific suggestions
        domain_suggestions = {
            "ai": ["machine learning algorithms", "neural network architectures", "AI ethics"],
            "tech": ["software development", "programming languages", "system architecture"],
            "science": ["research methodology", "experimental design", "data analysis"],
            "business": ["market analysis", "business strategy", "competitive intelligence"]
        }
        
        if domain in domain_suggestions:
            for related_term in domain_suggestions[domain]:
                if related_term.lower() not in query.lower():
                    suggestion = QuerySuggestion(
                        query_text=related_term,
                        relevance_score=0.6,
                        suggestion_type="related",
                        context=f"Related {domain} topic",
                        expected_results=10,
                        confidence=0.5,
                        related_topics=[related_term]
                    )
                    suggestions.append(suggestion)
        
        return suggestions[:3]
    
    def _generate_trending_suggestions(self, query: str) -> List[QuerySuggestion]:
        """Generate suggestions based on trending topics"""
        
        trending_queries = self.trend_analyzer.get_trending_queries(time_window=6)
        suggestions = []
        
        for trending in trending_queries[:3]:
            if trending["query"] != query.lower():
                suggestion = QuerySuggestion(
                    query_text=trending["query"],
                    relevance_score=0.5 + (trending["trend_score"] / 100),
                    suggestion_type="trending",
                    context=f"Trending query ({trending['frequency']} searches)",
                    expected_results=15,
                    confidence=0.4
                )
                suggestions.append(suggestion)
        
        return suggestions
    
    def _find_related_entities(self, terms: List[str], knowledge_graph: KnowledgeGraph) -> List[str]:
        """Find entities related to query terms"""
        
        related_entities = []
        
        if hasattr(knowledge_graph, 'entities'):
            for entity in knowledge_graph.entities:
                entity_name_lower = entity.name.lower()
                for term in terms:
                    if term.lower() in entity_name_lower or entity_name_lower in term.lower():
                        related_entities.append(entity.name)
        
        return list(set(related_entities))[:5]
    
    def _get_all_content_items(self, website_system: WebsiteGraphRAGSystem) -> List[Dict[str, Any]]:
        """Get all content items from website system for comparison"""
        
        # Mock implementation - in production, query the actual content
        content_items = []
        
        # Add mock content items based on system metadata
        for i in range(20):  # Mock 20 content items
            content_items.append({
                "id": f"content_{i}",
                "content_type": ["html", "pdf", "audio", "video"][i % 4],
                "title": f"Content Item {i}",
                "url": f"{website_system.url}/content/{i}",
                "text_content": f"This is sample content about topic {i % 5}",
                "entities": [f"Entity_{i}", f"Entity_{(i+1)%10}"],
                "topics": [f"Topic_{i%3}", f"Topic_{(i+2)%5}"],
                "summary": f"Summary of content item {i}"
            })
        
        return content_items
    
    def _calculate_content_relevance(
        self,
        source_content: Dict[str, Any],
        target_content: Dict[str, Any]
    ) -> float:
        """Calculate content relevance score"""
        
        # Factors for relevance calculation
        content_type_bonus = 0.1 if source_content.get("content_type") == target_content.get("content_type") else 0.0
        entity_overlap = len(set(source_content.get("entities", [])).intersection(set(target_content.get("entities", [])))) * 0.2
        topic_overlap = len(set(source_content.get("topics", [])).intersection(set(target_content.get("topics", [])))) * 0.15
        
        base_relevance = 0.5
        relevance = base_relevance + content_type_bonus + entity_overlap + topic_overlap
        
        return min(relevance, 1.0)
    
    def _generate_recommendation_reason(
        self,
        source_content: Dict[str, Any],
        target_content: Dict[str, Any],
        similarity: float
    ) -> str:
        """Generate human-readable reason for recommendation"""
        
        # Check for shared entities
        shared_entities = set(source_content.get("entities", [])).intersection(
            set(target_content.get("entities", []))
        )
        
        # Check for shared topics
        shared_topics = set(source_content.get("topics", [])).intersection(
            set(target_content.get("topics", []))
        )
        
        if shared_entities:
            return f"Shares entities: {', '.join(list(shared_entities)[:2])}"
        elif shared_topics:
            return f"Similar topics: {', '.join(list(shared_topics)[:2])}"
        elif similarity > 0.7:
            return "High content similarity"
        elif target_content.get("content_type") == source_content.get("content_type"):
            return f"Same content type ({target_content.get('content_type')})"
        else:
            return "Related content"
    
    def _deduplicate_suggestions(self, suggestions: List[QuerySuggestion]) -> List[QuerySuggestion]:
        """Remove duplicate suggestions"""
        
        seen_queries = set()
        unique_suggestions = []
        
        for suggestion in suggestions:
            query_key = suggestion.query_text.lower().strip()
            if query_key not in seen_queries:
                seen_queries.add(query_key)
                unique_suggestions.append(suggestion)
        
        return unique_suggestions
    
    def track_recommendation_interaction(
        self,
        user_id: str,
        suggestion: QuerySuggestion,
        action: str,  # clicked, ignored, modified
        outcome: Dict[str, Any] = None
    ):
        """Track user interaction with recommendations for learning"""
        
        interaction = {
            "timestamp": datetime.now(),
            "user_id": user_id,
            "suggestion": suggestion,
            "action": action,
            "outcome": outcome or {}
        }
        
        # Update personalization engine
        if action == "clicked" and outcome:
            self.personalization_engine.update_user_profile(
                user_id, suggestion.query_text, outcome.get("results", [])
            )
        
        # Update recommendation quality metrics
        if action == "clicked":
            self.recommendation_metrics["click_through_rate"] = (
                self.recommendation_metrics["click_through_rate"] * 0.9 + 1.0 * 0.1
            )
        elif action == "ignored":
            self.recommendation_metrics["click_through_rate"] *= 0.95
    
    async def get_recommendation_analytics(self) -> Dict[str, Any]:
        """Get analytics about recommendation engine performance"""
        
        trending_queries = self.trend_analyzer.get_trending_queries()
        trending_topics = self.trend_analyzer.get_trending_topics()
        
        return {
            "engine_metrics": self.recommendation_metrics,
            "trending_analysis": {
                "trending_queries": trending_queries,
                "trending_topics": trending_topics
            },
            "user_patterns": {
                "total_users": len(self.personalization_engine.user_profiles),
                "active_users": len([
                    p for p in self.personalization_engine.user_profiles.values()
                    if p.last_active > datetime.now() - timedelta(days=7)
                ])
            },
            "cache_statistics": {
                "suggestion_cache_size": len(self.suggestion_cache),
                "recommendation_cache_size": len(self.recommendation_cache),
                "similarity_cache_size": len(self.similarity_engine.similarity_cache)
            }
        }
    
    async def optimize_recommendations(self):
        """Optimize recommendation algorithms based on usage patterns"""
        
        logger.info("Optimizing recommendation algorithms...")
        
        # Clear old cache entries
        current_time = datetime.now()
        
        # Clean suggestion cache (keep entries < 1 hour old)
        self.suggestion_cache = {
            key: value for key, value in self.suggestion_cache.items()
            if current_time - value["timestamp"] < timedelta(hours=1)
        }
        
        # Optimize similarity cache (keep most frequently used)
        if len(self.similarity_engine.similarity_cache) > 1000:
            # Keep only recent calculations
            self.similarity_engine.similarity_cache.clear()
        
        logger.info("Recommendation optimization completed")


# Demo and testing functions
async def demo_recommendation_engine():
    """Demonstration of intelligent recommendation engine"""
    
    print("🧠 Intelligent Recommendation Engine - Comprehensive Demo")
    print("=" * 65)
    
    # Create recommendation engine
    engine = IntelligentRecommendationEngine()
    
    # Create mock website system
    from ipfs_datasets_py.website_graphrag_system import WebsiteGraphRAGSystem
    from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import KnowledgeGraph, Entity
    
    # Mock knowledge graph
    entities = [
        Entity(name="Machine Learning", entity_type="field", confidence=0.9),
        Entity(name="Deep Learning", entity_type="field", confidence=0.85),
        Entity(name="Neural Networks", entity_type="concept", confidence=0.8),
        Entity(name="OpenAI", entity_type="organization", confidence=0.9),
        Entity(name="Geoffrey Hinton", entity_type="person", confidence=0.95)
    ]
    
    knowledge_graph = KnowledgeGraph()
    knowledge_graph.entities = entities
    
    # Mock website system
    mock_system = WebsiteGraphRAGSystem(
        url="https://ai-research.example.com",
        content_manifest=None,
        processed_content=None,
        knowledge_graph=knowledge_graph
    )
    
    # Test query suggestions
    print("\n🔍 Testing Query Suggestions:")
    print("-" * 40)
    
    test_queries = [
        "machine learning",
        "artificial intelligence research",
        "deep learning algorithms"
    ]
    
    for query in test_queries:
        print(f"\n📝 Query: '{query}'")
        suggestions = await engine.generate_query_suggestions(query, mock_system, "demo_user")
        
        if suggestions:
            print(f"   💡 Generated {len(suggestions)} suggestions:")
            for i, suggestion in enumerate(suggestions[:3], 1):
                print(f"   {i}. {suggestion.query_text}")
                print(f"      Type: {suggestion.suggestion_type} | Relevance: {suggestion.relevance_score:.2f}")
                print(f"      Context: {suggestion.context}")
        else:
            print("   No suggestions generated")
    
    # Test related content discovery
    print("\n\n🔗 Testing Related Content Discovery:")
    print("-" * 45)
    
    # Mock source content
    source_content = {
        "id": "source_1",
        "content_type": "html",
        "title": "Introduction to Machine Learning",
        "url": "https://ai-research.example.com/ml-intro",
        "text_content": "Machine learning is a subset of artificial intelligence that focuses on algorithms.",
        "entities": ["Machine Learning", "Artificial Intelligence"],
        "topics": ["AI", "Algorithms", "Technology"]
    }
    
    print(f"📄 Source content: {source_content['title']}")
    
    related_content = await engine.discover_related_content(source_content, mock_system, max_recommendations=5)
    
    if related_content:
        print(f"   🔗 Found {len(related_content)} related items:")
        for i, rec in enumerate(related_content, 1):
            print(f"   {i}. {rec.title}")
            print(f"      Similarity: {rec.similarity_score:.2f} | Relevance: {rec.relevance_score:.2f}")
            print(f"      Reason: {rec.recommendation_reason}")
            print(f"      Topics: {', '.join(rec.topics)}")
    else:
        print("   No related content found")
    
    # Test personalization
    print("\n\n👤 Testing Personalization:")
    print("-" * 35)
    
    # Simulate user interactions
    mock_results = [{"id": "result_1", "content_type": "html"}]
    engine.personalization_engine.update_user_profile(
        "demo_user", "machine learning algorithms", mock_results
    )
    
    # Generate personalized suggestions
    personalized = engine.personalization_engine.get_personalized_suggestions(
        "demo_user", "artificial intelligence", {}
    )
    
    if personalized:
        print(f"   🎯 Generated {len(personalized)} personalized suggestions:")
        for i, suggestion in enumerate(personalized[:3], 1):
            print(f"   {i}. {suggestion.query_text}")
            print(f"      Context: {suggestion.context}")
    
    # Test analytics
    print("\n\n📊 Recommendation Analytics:")
    print("-" * 35)
    
    analytics = await engine.get_recommendation_analytics()
    print(f"   Total suggestions generated: {analytics['engine_metrics']['total_suggestions_generated']}")
    print(f"   Total recommendations generated: {analytics['engine_metrics']['total_recommendations_generated']}")
    print(f"   Click-through rate: {analytics['engine_metrics']['click_through_rate']:.1%}")
    print(f"   Total users: {analytics['user_patterns']['total_users']}")
    print(f"   Active users: {analytics['user_patterns']['active_users']}")
    
    # Test trending analysis
    trending_topics = analytics["trending_analysis"]["trending_topics"]
    if trending_topics:
        print(f"\n📈 Trending Topics:")
        for topic in trending_topics[:3]:
            print(f"   • {topic['topic']} (score: {topic['score']}, trend: {topic['trend']})")
    
    print("\n✅ Intelligent Recommendation Engine demonstration completed!")
    
    return {
        "suggestions_tested": len(test_queries),
        "related_content_found": len(related_content),
        "personalized_suggestions": len(personalized),
        "analytics": analytics
    }


if __name__ == "__main__":
    import anyio
    
    # Run recommendation engine demo
    anyio.run(demo_recommendation_engine())
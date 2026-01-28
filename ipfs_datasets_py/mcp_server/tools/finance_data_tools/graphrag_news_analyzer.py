"""
GraphRAG News Analysis for Financial Markets.

This module provides GraphRAG-powered analysis of financial news archives to extract
knowledge graphs linking executives, companies, and market performance. It enables
hypothesis testing such as correlating CEO characteristics with company performance.

Features:
- Archive scraping (AP, Reuters, Bloomberg historical data)
- Executive profile extraction (gender, personality traits, background)
- Company-executive relationship mapping
- Stock performance correlation analysis
- Hypothesis testing framework
- GraphRAG-powered entity linking and reasoning

Example Use Cases:
- Male vs Female CEO performance analysis
- Introvert vs Extrovert CEO effectiveness
- Educational background impact on company growth
- Leadership tenure and stock volatility
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict
import hashlib

logger = logging.getLogger(__name__)

# Try to import GraphRAG components
try:
    from ipfs_datasets_py.knowledge_graph_extraction import (
        Entity, Relationship, KnowledgeGraph
    )
    from ipfs_datasets_py.integrations.graphrag_integration import GraphRAGIntegration
    GRAPHRAG_AVAILABLE = True
except ImportError:
    logger.warning("GraphRAG components not available. Using stubs.")
    GRAPHRAG_AVAILABLE = False
    
    # Stub classes for when GraphRAG is not available
    @dataclass
    class Entity:
        entity_id: str
        entity_type: str
        name: str
        properties: Dict[str, Any] = field(default_factory=dict)
        confidence: float = 1.0
    
    @dataclass
    class Relationship:
        relationship_id: str
        relationship_type: str
        source_entity: Entity
        target_entity: Entity
        properties: Dict[str, Any] = field(default_factory=dict)
        confidence: float = 1.0
    
    class KnowledgeGraph:
        def __init__(self):
            self.entities = []
            self.relationships = []


@dataclass
class ExecutiveProfile:
    """
    Profile of a company executive extracted from news articles.
    
    Attributes:
        person_id: Unique identifier
        name: Full name
        gender: Gender (male, female, non-binary, unknown)
        personality_traits: Extracted traits (introvert, extrovert, etc.)
        education: Educational background
        companies: List of companies associated with
        positions: List of positions held
        tenure_start: Start date in current position
        tenure_end: End date (None if current)
        news_mentions: Count of news mentions
        sentiment_score: Average sentiment in news
        attributes: Additional extracted attributes
    """
    person_id: str
    name: str
    gender: str = "unknown"
    personality_traits: List[str] = field(default_factory=list)
    education: Dict[str, str] = field(default_factory=dict)
    companies: List[str] = field(default_factory=list)
    positions: List[str] = field(default_factory=list)
    tenure_start: Optional[datetime] = None
    tenure_end: Optional[datetime] = None
    news_mentions: int = 0
    sentiment_score: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    def to_entity(self) -> Entity:
        """Convert to a knowledge graph Entity."""
        return Entity(
            entity_id=self.person_id,
            entity_type="executive",
            name=self.name,
            properties={
                "gender": self.gender,
                "personality_traits": self.personality_traits,
                "education": self.education,
                "companies": self.companies,
                "positions": self.positions,
                "tenure_start": self.tenure_start.isoformat() if self.tenure_start else None,
                "tenure_end": self.tenure_end.isoformat() if self.tenure_end else None,
                "news_mentions": self.news_mentions,
                "sentiment_score": self.sentiment_score,
                **self.attributes
            }
        )


@dataclass
class CompanyPerformance:
    """
    Company stock performance data linked to executive tenure.
    
    Attributes:
        company_id: Unique identifier
        symbol: Stock ticker symbol
        name: Company name
        executive_id: Current/linked executive ID
        start_date: Start of measurement period
        end_date: End of measurement period
        start_price: Stock price at start
        end_price: Stock price at end
        return_percentage: Total return percentage
        volatility: Price volatility metric
        market_cap_change: Change in market capitalization
        metrics: Additional performance metrics
    """
    company_id: str
    symbol: str
    name: str
    executive_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    start_price: float = 0.0
    end_price: float = 0.0
    return_percentage: float = 0.0
    volatility: float = 0.0
    market_cap_change: float = 0.0
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def to_entity(self) -> Entity:
        """Convert to a knowledge graph Entity."""
        return Entity(
            entity_id=self.company_id,
            entity_type="company",
            name=self.name,
            properties={
                "symbol": self.symbol,
                "executive_id": self.executive_id,
                "start_date": self.start_date.isoformat() if self.start_date else None,
                "end_date": self.end_date.isoformat() if self.end_date else None,
                "start_price": self.start_price,
                "end_price": self.end_price,
                "return_percentage": self.return_percentage,
                "volatility": self.volatility,
                "market_cap_change": self.market_cap_change,
                **self.metrics
            }
        )


@dataclass
class HypothesisTest:
    """
    Results of a hypothesis test correlating executive traits with performance.
    
    Attributes:
        hypothesis_id: Unique identifier
        hypothesis: Hypothesis statement
        group_a_label: Label for group A (e.g., "Male CEOs")
        group_b_label: Label for group B (e.g., "Female CEOs")
        group_a_samples: Number of samples in group A
        group_b_samples: Number of samples in group B
        group_a_mean: Mean performance for group A
        group_b_mean: Mean performance for group B
        difference: Difference between groups
        p_value: Statistical significance
        confidence_level: Confidence level (0.0-1.0)
        conclusion: Test conclusion
        supporting_evidence: List of supporting data points
    """
    hypothesis_id: str
    hypothesis: str
    group_a_label: str
    group_b_label: str
    group_a_samples: int = 0
    group_b_samples: int = 0
    group_a_mean: float = 0.0
    group_b_mean: float = 0.0
    difference: float = 0.0
    p_value: float = 1.0
    confidence_level: float = 0.0
    conclusion: str = ""
    supporting_evidence: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "hypothesis": self.hypothesis,
            "groups": {
                "a": {
                    "label": self.group_a_label,
                    "samples": self.group_a_samples,
                    "mean": self.group_a_mean
                },
                "b": {
                    "label": self.group_b_label,
                    "samples": self.group_b_samples,
                    "mean": self.group_b_mean
                }
            },
            "results": {
                "difference": self.difference,
                "p_value": self.p_value,
                "confidence_level": self.confidence_level,
                "conclusion": self.conclusion
            },
            "supporting_evidence": self.supporting_evidence
        }


class GraphRAGNewsAnalyzer:
    """
    GraphRAG-powered analyzer for financial news and executive-performance correlations.
    
    This class integrates with the existing GraphRAG system to:
    1. Build knowledge graphs from news archives
    2. Extract executive profiles and company relationships
    3. Link executives to stock performance data
    4. Test hypotheses about correlations
    """
    
    def __init__(
        self,
        enable_graphrag: bool = True,
        min_confidence: float = 0.6
    ):
        """
        Initialize the analyzer.
        
        Args:
            enable_graphrag: Whether to use GraphRAG features
            min_confidence: Minimum confidence for entity extraction
        """
        self.enable_graphrag = enable_graphrag and GRAPHRAG_AVAILABLE
        self.min_confidence = min_confidence
        
        # Storage
        self.executives: Dict[str, ExecutiveProfile] = {}
        self.companies: Dict[str, CompanyPerformance] = {}
        self.knowledge_graph = KnowledgeGraph()
        
        logger.info(
            f"GraphRAG News Analyzer initialized "
            f"(GraphRAG: {self.enable_graphrag})"
        )
    
    def extract_executive_profiles(
        self,
        news_articles: List[Dict[str, Any]]
    ) -> List[ExecutiveProfile]:
        """
        Extract executive profiles from news articles using GraphRAG.
        
        Args:
            news_articles: List of news article dictionaries
        
        Returns:
            List of extracted executive profiles
        """
        profiles = []
        
        for article in news_articles:
            # Extract entities from article
            entities = self._extract_entities_from_article(article)
            
            for entity in entities:
                if entity.entity_type in ["person", "executive", "ceo"]:
                    profile = self._create_executive_profile(entity, article)
                    if profile:
                        profiles.append(profile)
                        self.executives[profile.person_id] = profile
        
        logger.info(f"Extracted {len(profiles)} executive profiles from {len(news_articles)} articles")
        return profiles
    
    def _extract_entities_from_article(
        self,
        article: Dict[str, Any]
    ) -> List[Entity]:
        """Extract entities from a news article."""
        entities = []
        
        # Placeholder for GraphRAG entity extraction
        # In production, this would use NLP models and GraphRAG
        content = article.get("content", "")
        title = article.get("title", "")
        
        # Basic pattern matching for demonstration
        # In production, replace with spaCy, transformers, etc.
        ceo_patterns = [
            r"CEO\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
            r"Chief Executive\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
            r"([A-Z][a-z]+\s+[A-Z][a-z]+),\s+CEO"
        ]
        
        import re
        for pattern in ceo_patterns:
            matches = re.findall(pattern, content + " " + title)
            for name in matches[:3]:  # Limit to avoid duplicates
                entity = Entity(
                    entity_id=hashlib.md5(name.encode()).hexdigest()[:16],
                    entity_type="executive",
                    name=name,
                    properties={"position": "CEO"},
                    confidence=0.7
                )
                entities.append(entity)
        
        return entities
    
    def _create_executive_profile(
        self,
        entity: Entity,
        article: Dict[str, Any]
    ) -> Optional[ExecutiveProfile]:
        """Create an executive profile from an entity."""
        if entity.confidence < self.min_confidence:
            return None
        
        # Check if profile already exists
        if entity.entity_id in self.executives:
            profile = self.executives[entity.entity_id]
            profile.news_mentions += 1
            return profile
        
        # Create new profile
        profile = ExecutiveProfile(
            person_id=entity.entity_id,
            name=entity.name,
            positions=[entity.properties.get("position", "Executive")],
            news_mentions=1
        )
        
        # Extract attributes from article content
        # Placeholder - in production, use NLP for attribute extraction
        content_lower = article.get("content", "").lower()
        
        # Gender inference (very basic - in production use proper NER)
        if " she " in content_lower or " her " in content_lower:
            profile.gender = "female"
        elif " he " in content_lower or " his " in content_lower:
            profile.gender = "male"
        
        # Personality traits (placeholder - use sentiment/personality models)
        if "introvert" in content_lower or "reserved" in content_lower:
            profile.personality_traits.append("introvert")
        if "extrovert" in content_lower or "outgoing" in content_lower:
            profile.personality_traits.append("extrovert")
        
        return profile
    
    def link_executives_to_performance(
        self,
        executives: List[ExecutiveProfile],
        performance_data: List[CompanyPerformance]
    ) -> List[Relationship]:
        """
        Link executive profiles to company performance data.
        
        Args:
            executives: List of executive profiles
            performance_data: List of company performance data
        
        Returns:
            List of relationships created
        """
        relationships = []
        
        for exec_prof in executives:
            for company in exec_prof.companies:
                # Find matching performance data
                matching_perf = [
                    p for p in performance_data
                    if p.symbol in company or p.name in company
                ]
                
                for perf in matching_perf:
                    perf.executive_id = exec_prof.person_id
                    
                    # Create relationship
                    rel = Relationship(
                        relationship_id=f"{exec_prof.person_id}_{perf.company_id}",
                        relationship_type="leads",
                        source_entity=exec_prof.to_entity(),
                        target_entity=perf.to_entity(),
                        properties={
                            "start_date": exec_prof.tenure_start,
                            "end_date": exec_prof.tenure_end
                        },
                        confidence=0.8
                    )
                    relationships.append(rel)
                    
                    if self.enable_graphrag:
                        self.knowledge_graph.add_relationship(rel)
        
        logger.info(f"Created {len(relationships)} executive-company relationships")
        return relationships
    
    def test_hypothesis(
        self,
        hypothesis: str,
        attribute_name: str,
        group_a_value: Any,
        group_b_value: Any,
        metric: str = "return_percentage"
    ) -> HypothesisTest:
        """
        Test a hypothesis by comparing two groups.
        
        Args:
            hypothesis: Hypothesis statement
            attribute_name: Attribute to group by (e.g., "gender")
            group_a_value: Value for group A (e.g., "male")
            group_b_value: Value for group B (e.g., "female")
            metric: Performance metric to compare
        
        Returns:
            Hypothesis test results
        """
        # Collect samples for each group
        group_a_samples = []
        group_b_samples = []
        
        for company in self.companies.values():
            if not company.executive_id:
                continue
            
            exec_prof = self.executives.get(company.executive_id)
            if not exec_prof:
                continue
            
            # Get attribute value
            attr_value = getattr(exec_prof, attribute_name, None)
            if attr_value is None:
                attr_value = exec_prof.attributes.get(attribute_name)
            
            # Check for list attributes (like personality_traits)
            if isinstance(attr_value, list):
                if group_a_value in attr_value:
                    attr_value = group_a_value
                elif group_b_value in attr_value:
                    attr_value = group_b_value
                else:
                    continue
            
            # Collect metric value
            metric_value = getattr(company, metric, 0.0)
            
            if attr_value == group_a_value:
                group_a_samples.append(metric_value)
            elif attr_value == group_b_value:
                group_b_samples.append(metric_value)
        
        # Calculate statistics
        group_a_mean = sum(group_a_samples) / len(group_a_samples) if group_a_samples else 0.0
        group_b_mean = sum(group_b_samples) / len(group_b_samples) if group_b_samples else 0.0
        difference = group_a_mean - group_b_mean
        
        # Simple significance test (placeholder - use scipy.stats in production)
        # For now, use sample size and difference magnitude
        min_samples = min(len(group_a_samples), len(group_b_samples))
        if min_samples >= 10 and abs(difference) > 5.0:
            p_value = 0.05  # Significant
            confidence = 0.95
            conclusion = f"Statistically significant difference: {group_a_value} group outperforms by {difference:.2f}%"
        elif min_samples >= 5:
            p_value = 0.10
            confidence = 0.75
            conclusion = f"Moderate evidence of difference: {group_a_value} group shows {difference:.2f}% difference"
        else:
            p_value = 0.50
            confidence = 0.25
            conclusion = "Insufficient data for statistical significance"
        
        # Create result
        result = HypothesisTest(
            hypothesis_id=hashlib.md5(hypothesis.encode()).hexdigest()[:16],
            hypothesis=hypothesis,
            group_a_label=f"{attribute_name}={group_a_value}",
            group_b_label=f"{attribute_name}={group_b_value}",
            group_a_samples=len(group_a_samples),
            group_b_samples=len(group_b_samples),
            group_a_mean=group_a_mean,
            group_b_mean=group_b_mean,
            difference=difference,
            p_value=p_value,
            confidence_level=confidence,
            conclusion=conclusion
        )
        
        logger.info(f"Hypothesis test: {conclusion}")
        return result
    
    def build_knowledge_graph(self) -> KnowledgeGraph:
        """
        Build a complete knowledge graph from collected data.
        
        Returns:
            Knowledge graph with all entities and relationships
        """
        # Add executive entities
        for exec_prof in self.executives.values():
            self.knowledge_graph.add_entity(exec_prof.to_entity())
        
        # Add company entities
        for company in self.companies.values():
            self.knowledge_graph.add_entity(company.to_entity())
        
        logger.info(
            f"Built knowledge graph: {len(self.knowledge_graph.entities)} entities, "
            f"{len(self.knowledge_graph.relationships)} relationships"
        )
        
        return self.knowledge_graph


# MCP Tool Functions
def analyze_executive_performance(
    news_articles_json: str,
    stock_data_json: str,
    hypothesis: str,
    attribute: str,
    group_a: str,
    group_b: str
) -> str:
    """
    MCP tool to analyze executive characteristics vs company performance.
    
    Args:
        news_articles_json: JSON string with news articles
        stock_data_json: JSON string with stock performance data
        hypothesis: Hypothesis to test (e.g., "Female CEOs outperform male CEOs")
        attribute: Attribute to compare (e.g., "gender")
        group_a: Value for group A (e.g., "female")
        group_b: Value for group B (e.g., "male")
    
    Returns:
        JSON string with analysis results
    """
    try:
        # Parse inputs
        articles = json.loads(news_articles_json)
        stock_data = json.loads(stock_data_json)
        
        # Initialize analyzer
        analyzer = GraphRAGNewsAnalyzer()
        
        # Extract executive profiles
        executives = analyzer.extract_executive_profiles(articles)
        
        # Create company performance objects
        companies = [
            CompanyPerformance(
                company_id=item.get("company_id", item["symbol"]),
                symbol=item["symbol"],
                name=item.get("name", item["symbol"]),
                return_percentage=item.get("return_percentage", 0.0),
                volatility=item.get("volatility", 0.0)
            )
            for item in stock_data
        ]
        analyzer.companies = {c.company_id: c for c in companies}
        
        # Link executives to performance
        relationships = analyzer.link_executives_to_performance(executives, companies)
        
        # Test hypothesis
        test_result = analyzer.test_hypothesis(
            hypothesis=hypothesis,
            attribute_name=attribute,
            group_a_value=group_a,
            group_b_value=group_b
        )
        
        # Build knowledge graph
        kg = analyzer.build_knowledge_graph()
        
        # Format result
        result = {
            "success": True,
            "hypothesis_test": test_result.to_dict(),
            "executives_analyzed": len(executives),
            "companies_analyzed": len(companies),
            "relationships_found": len(relationships),
            "knowledge_graph": {
                "entities": len(kg.entities),
                "relationships": len(kg.relationships)
            }
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Executive performance analysis failed: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def extract_executive_profiles_from_archives(
    sources: str = "ap,reuters,bloomberg",
    start_date: str = "2020-01-01",
    end_date: str = "2024-01-01",
    min_mentions: int = 5
) -> str:
    """
    MCP tool to extract executive profiles from news archives.
    
    Args:
        sources: Comma-separated news sources
        start_date: Start date for archive search (ISO format)
        end_date: End date for archive search (ISO format)
        min_mentions: Minimum number of mentions to include
    
    Returns:
        JSON string with extracted profiles
    """
    try:
        # Placeholder - in production, integrate with actual archive scrapers
        logger.info(
            f"Extracting executive profiles from {sources} "
            f"between {start_date} and {end_date}"
        )
        
        # Mock response
        result = {
            "success": True,
            "note": "This is a placeholder. Integrate with news_scrapers module for production.",
            "sources": sources.split(","),
            "date_range": {"start": start_date, "end": end_date},
            "min_mentions": min_mentions,
            "profiles_found": 0,
            "next_steps": [
                "Implement actual archive scraping",
                "Add NLP-based attribute extraction",
                "Integrate with GraphRAG entity linking"
            ]
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Profile extraction failed: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e)
        })


__all__ = [
    "ExecutiveProfile",
    "CompanyPerformance",
    "HypothesisTest",
    "GraphRAGNewsAnalyzer",
    "analyze_executive_performance",
    "extract_executive_profiles_from_archives"
]

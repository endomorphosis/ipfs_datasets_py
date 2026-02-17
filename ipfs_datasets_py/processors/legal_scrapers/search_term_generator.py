"""Search Term Generator for Legal Brave Search.

This module generates optimized search terms for Brave Search API based on:
- Natural language query intent
- Legal entity knowledge base
- Search strategy patterns

It combines query entities with knowledge base data to create multiple candidate
search term combinations, ranked by expected relevance.
"""

import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from itertools import product

from .query_processor import QueryIntent
from .knowledge_base_loader import LegalKnowledgeBase, FederalEntity, StateEntity, MunicipalEntity

logger = logging.getLogger(__name__)


@dataclass
class SearchTerm:
    """A single search term with metadata."""
    term: str
    priority: int  # 1 (highest) to 5 (lowest)
    category: str  # federal, state, local, general
    source_entities: List[str] = field(default_factory=list)
    
    def __repr__(self) -> str:
        return f"SearchTerm('{self.term}', priority={self.priority}, category={self.category})"


@dataclass
class SearchStrategy:
    """Collection of search terms with strategy metadata."""
    terms: List[SearchTerm]
    intent: QueryIntent
    total_combinations: int
    recommended_limit: int = 10
    
    def get_top_terms(self, limit: Optional[int] = None) -> List[str]:
        """Get top N search terms by priority.
        
        Args:
            limit: Maximum number of terms to return (default: recommended_limit)
            
        Returns:
            List of search term strings
        """
        if limit is None:
            limit = self.recommended_limit
        
        # Sort by priority (lower number = higher priority)
        sorted_terms = sorted(self.terms, key=lambda t: (t.priority, len(t.term)))
        return [t.term for t in sorted_terms[:limit]]
    
    def get_by_category(self, category: str) -> List[SearchTerm]:
        """Get search terms for a specific category.
        
        Args:
            category: Category name (federal, state, local, general)
            
        Returns:
            List of SearchTerm objects for that category
        """
        return [t for t in self.terms if t.category == category]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'terms': [
                {
                    'term': t.term,
                    'priority': t.priority,
                    'category': t.category,
                    'source_entities': t.source_entities
                }
                for t in self.terms
            ],
            'total_combinations': self.total_combinations,
            'recommended_limit': self.recommended_limit,
            'intent_summary': str(self.intent)
        }


class SearchTermGenerator:
    """Generate optimized search terms for Brave Search API.
    
    This generator creates multiple search term combinations by:
    1. Matching query entities to knowledge base entries
    2. Combining entities with topics and legal concepts
    3. Generating variations and synonyms
    4. Prioritizing by expected relevance
    
    Example:
        >>> generator = SearchTermGenerator(knowledge_base)
        >>> intent = QueryIntent(original_query="EPA water regulations")
        >>> strategy = generator.generate(intent)
        >>> print(strategy.get_top_terms(5))
        ['EPA water regulations', 'Environmental Protection Agency water quality', ...]
    """
    
    def __init__(self, knowledge_base: LegalKnowledgeBase):
        """Initialize the search term generator.
        
        Args:
            knowledge_base: Loaded LegalKnowledgeBase instance
        """
        self.kb = knowledge_base
    
    def generate(self, intent: QueryIntent, max_terms: int = 50) -> SearchStrategy:
        """Generate search terms from query intent.
        
        Args:
            intent: Parsed query intent
            max_terms: Maximum number of search terms to generate
            
        Returns:
            SearchStrategy with prioritized search terms
        """
        terms: List[SearchTerm] = []
        
        # Generate base terms from original query
        terms.extend(self._generate_base_terms(intent))
        
        # Generate federal entity terms
        if intent.scope in ['federal', 'mixed'] or intent.agencies:
            terms.extend(self._generate_federal_terms(intent))
        
        # Generate state entity terms
        if intent.scope in ['state', 'mixed'] or intent.jurisdictions:
            terms.extend(self._generate_state_terms(intent))
        
        # Generate municipal terms
        if intent.scope in ['local', 'mixed'] or intent.municipalities:
            terms.extend(self._generate_municipal_terms(intent))
        
        # Generate topic-specific terms
        terms.extend(self._generate_topic_terms(intent))
        
        # Generate legal concept terms
        terms.extend(self._generate_legal_concept_terms(intent))
        
        # Deduplicate
        unique_terms = self._deduplicate_terms(terms)
        
        # Limit to max_terms
        if len(unique_terms) > max_terms:
            # Keep highest priority terms
            unique_terms = sorted(unique_terms, key=lambda t: (t.priority, len(t.term)))[:max_terms]
        
        return SearchStrategy(
            terms=unique_terms,
            intent=intent,
            total_combinations=len(unique_terms),
            recommended_limit=min(10, len(unique_terms))
        )
    
    def _generate_base_terms(self, intent: QueryIntent) -> List[SearchTerm]:
        """Generate base search terms from the original query.
        
        Args:
            intent: Query intent
            
        Returns:
            List of base SearchTerm objects
        """
        terms = []
        
        # Original query (highest priority)
        terms.append(SearchTerm(
            term=intent.original_query,
            priority=1,
            category='general',
            source_entities=['original_query']
        ))
        
        # Add "regulations" if not present and relevant
        if 'regulation' not in intent.original_query.lower():
            terms.append(SearchTerm(
                term=f"{intent.original_query} regulations",
                priority=2,
                category='general',
                source_entities=['original_query']
            ))
        
        # Add "rules" variant
        if 'rule' not in intent.original_query.lower():
            terms.append(SearchTerm(
                term=f"{intent.original_query} rules",
                priority=2,
                category='general',
                source_entities=['original_query']
            ))
        
        return terms
    
    def _generate_federal_terms(self, intent: QueryIntent) -> List[SearchTerm]:
        """Generate search terms for federal entities.
        
        Args:
            intent: Query intent
            
        Returns:
            List of federal SearchTerm objects
        """
        terms = []
        
        # Search knowledge base for matching entities
        for agency_name in intent.agencies:
            entities = self.kb.search_federal(agency_name)
            
            for entity in entities[:3]:  # Top 3 matches
                # Entity + topics
                for topic in intent.topics[:2]:  # Top 2 topics
                    terms.append(SearchTerm(
                        term=f"{entity.name} {topic}",
                        priority=2,
                        category='federal',
                        source_entities=[entity.id]
                    ))
                
                # Entity + legal concepts
                for concept in intent.legal_concepts[:2]:
                    terms.append(SearchTerm(
                        term=f"{entity.name} {concept}",
                        priority=2,
                        category='federal',
                        source_entities=[entity.id]
                    ))
                
                # Entity + original query keywords
                keywords = self._extract_keywords(intent.original_query)
                for keyword in keywords[:2]:
                    terms.append(SearchTerm(
                        term=f"{entity.name} {keyword}",
                        priority=3,
                        category='federal',
                        source_entities=[entity.id]
                    ))
        
        # If no agencies mentioned, search by topics
        if not intent.agencies:
            for topic in intent.topics[:2]:
                # Search for entities related to topic
                topic_entities = self._search_entities_by_topic(topic, 'federal')
                for entity in topic_entities[:2]:
                    terms.append(SearchTerm(
                        term=f"{entity.name} {topic}",
                        priority=3,
                        category='federal',
                        source_entities=[entity.id]
                    ))
        
        return terms
    
    def _generate_state_terms(self, intent: QueryIntent) -> List[SearchTerm]:
        """Generate search terms for state entities.
        
        Args:
            intent: Query intent
            
        Returns:
            List of state SearchTerm objects
        """
        terms = []
        
        # Get state jurisdictions (excluding 'federal')
        state_jurisdictions = [j for j in intent.jurisdictions if j != 'federal']
        
        for jurisdiction in state_jurisdictions:
            # Search for state entities
            for topic in intent.topics[:2]:
                entities = self.kb.search_state(topic, jurisdiction)
                
                for entity in entities[:3]:
                    terms.append(SearchTerm(
                        term=f"{entity.agency_name} {topic} {entity.state_name}",
                        priority=2,
                        category='state',
                        source_entities=[f"{entity.jurisdiction}:{entity.agency_name}"]
                    ))
            
            # General state + topic terms
            for topic in intent.topics[:2]:
                from .query_processor import US_STATES
                state_name = US_STATES.get(jurisdiction, jurisdiction)
                terms.append(SearchTerm(
                    term=f"{state_name} {topic} regulations",
                    priority=3,
                    category='state',
                    source_entities=[jurisdiction]
                ))
        
        return terms
    
    def _generate_municipal_terms(self, intent: QueryIntent) -> List[SearchTerm]:
        """Generate search terms for municipal entities.
        
        Args:
            intent: Query intent
            
        Returns:
            List of municipal SearchTerm objects
        """
        terms = []
        
        for municipality in intent.municipalities:
            # Search knowledge base
            entities = self.kb.search_municipal(municipality)
            
            for entity in entities[:2]:
                # Municipality + topics
                for topic in intent.topics[:2]:
                    terms.append(SearchTerm(
                        term=f"{entity.place_name} {topic}",
                        priority=2,
                        category='local',
                        source_entities=[str(entity.gnis)]
                    ))
                
                # Municipality + "ordinance"
                for topic in intent.topics[:1]:
                    terms.append(SearchTerm(
                        term=f"{entity.place_name} {topic} ordinance",
                        priority=3,
                        category='local',
                        source_entities=[str(entity.gnis)]
                    ))
                
                # Municipality + "code"
                for topic in intent.topics[:1]:
                    terms.append(SearchTerm(
                        term=f"{entity.place_name} municipal code {topic}",
                        priority=3,
                        category='local',
                        source_entities=[str(entity.gnis)]
                    ))
        
        return terms
    
    def _generate_topic_terms(self, intent: QueryIntent) -> List[SearchTerm]:
        """Generate topic-based search terms.
        
        Args:
            intent: Query intent
            
        Returns:
            List of topic SearchTerm objects
        """
        terms = []
        
        # Combine topics with legal domains
        for topic in intent.topics[:3]:
            for domain in intent.legal_domains[:2]:
                terms.append(SearchTerm(
                    term=f"{topic} {domain} law",
                    priority=4,
                    category='general',
                    source_entities=['topics']
                ))
        
        # Topics with jurisdiction
        for topic in intent.topics[:2]:
            if 'federal' in intent.jurisdictions:
                terms.append(SearchTerm(
                    term=f"federal {topic}",
                    priority=3,
                    category='general',
                    source_entities=['topics']
                ))
        
        return terms
    
    def _generate_legal_concept_terms(self, intent: QueryIntent) -> List[SearchTerm]:
        """Generate terms based on legal concepts.
        
        Args:
            intent: Query intent
            
        Returns:
            List of legal concept SearchTerm objects
        """
        terms = []
        
        for concept in intent.legal_concepts[:3]:
            # Concept + jurisdiction
            for jurisdiction in intent.jurisdictions[:2]:
                if jurisdiction != 'federal':
                    from .query_processor import US_STATES
                    state_name = US_STATES.get(jurisdiction, jurisdiction)
                    terms.append(SearchTerm(
                        term=f"{concept} {state_name}",
                        priority=4,
                        category='general',
                        source_entities=['legal_concepts']
                    ))
                else:
                    terms.append(SearchTerm(
                        term=f"{concept} federal law",
                        priority=4,
                        category='general',
                        source_entities=['legal_concepts']
                    ))
        
        return terms
    
    def _search_entities_by_topic(self, topic: str, entity_type: str) -> List[Any]:
        """Search for entities related to a topic.
        
        Args:
            topic: Topic to search for
            entity_type: 'federal', 'state', or 'municipal'
            
        Returns:
            List of matching entities
        """
        if entity_type == 'federal':
            return self.kb.search_federal(topic)
        elif entity_type == 'state':
            return self.kb.search_state(topic)
        elif entity_type == 'municipal':
            return self.kb.search_municipal(topic)
        return []
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text.
        
        Args:
            text: Text to extract keywords from
            
        Returns:
            List of keywords
        """
        # Simple keyword extraction (could be enhanced with NLP)
        words = text.lower().split()
        
        # Filter out common words
        stop_words = {
            'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'about', 'as', 'into', 'through', 'during',
            'what', 'where', 'when', 'why', 'how', 'which', 'who', 'whom', 'i', 'am',
            'are', 'is', 'was', 'were', 'be', 'been', 'being'
        }
        
        keywords = [w for w in words if w not in stop_words and len(w) > 3]
        return keywords[:5]  # Top 5
    
    def _deduplicate_terms(self, terms: List[SearchTerm]) -> List[SearchTerm]:
        """Remove duplicate search terms, keeping highest priority.
        
        Args:
            terms: List of SearchTerm objects
            
        Returns:
            Deduplicated list of SearchTerm objects
        """
        seen = {}
        
        for term in terms:
            normalized = term.term.lower().strip()
            if normalized not in seen or term.priority < seen[normalized].priority:
                seen[normalized] = term
        
        return list(seen.values())

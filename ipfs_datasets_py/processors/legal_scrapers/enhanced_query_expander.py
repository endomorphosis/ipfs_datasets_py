"""
Enhanced Query Expansion for Legal Search.

This module extends the base QueryExpander with legal-specific synonym databases,
relationship mappings, and contextual expansion strategies.

Features:
- Legal synonym database (200+ legal terms)
- Term relationship mapping (broader/narrower/related)
- Expansion strategy selector (aggressive/moderate/conservative)
- Contextual expansion based on legal domain
- Quality scoring and filtering
- Integration with llm_router

Usage:
    from ipfs_datasets_py.processors.legal_scrapers import EnhancedQueryExpander
    
    expander = EnhancedQueryExpander(strategy="moderate")
    expanded = expander.expand_query("EPA water pollution regulations")
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field

from .query_expander import QueryExpander, ExpandedQuery

logger = logging.getLogger(__name__)


@dataclass
class EnhancedExpandedQuery(ExpandedQuery):
    """Enhanced expanded query with additional metadata."""
    broader_terms: List[str] = field(default_factory=list)
    narrower_terms: List[str] = field(default_factory=list)
    domain: Optional[str] = None
    expansion_strategy: str = "moderate"
    quality_score: float = 1.0


class EnhancedQueryExpander(QueryExpander):
    """
    Enhanced query expander with legal synonym database and relationship mapping.
    
    Extends the base QueryExpander with:
    - 200+ legal term synonyms
    - Broader/narrower/related term relationships
    - Legal domain detection (environmental, employment, consumer, etc.)
    - Expansion strategy selection (aggressive/moderate/conservative)
    - Quality scoring and filtering
    - Contextual expansion based on detected domain
    
    Example:
        >>> expander = EnhancedQueryExpander(strategy="moderate")
        >>> result = expander.expand_query("EPA water regulations California")
        >>> print(f"Domain: {result.domain}")
        >>> print(f"Alternatives: {result.alternatives}")
        >>> print(f"Related: {result.related_concepts}")
    """
    
    def __init__(
        self,
        llm_provider: Optional[str] = None,
        model: Optional[str] = None,
        cache_dir: Optional[str] = None,
        max_alternatives: int = 5,
        use_llm: bool = True,
        strategy: str = "moderate",
        data_dir: Optional[str] = None
    ):
        """Initialize enhanced query expander.
        
        Args:
            llm_provider: LLM provider to use
            model: Model name
            cache_dir: Cache directory
            max_alternatives: Maximum alternatives to generate
            use_llm: Whether to use LLM
            strategy: Expansion strategy (aggressive/moderate/conservative)
            data_dir: Directory containing legal_synonyms.json and legal_relationships.json
        """
        super().__init__(llm_provider, model, cache_dir, max_alternatives, use_llm)
        
        self.strategy = strategy
        
        # Load legal databases
        if data_dir is None:
            data_dir = Path(__file__).parent
        else:
            data_dir = Path(data_dir)
        
        self.synonyms = self._load_json(data_dir / "legal_synonyms.json")
        self.relationships = self._load_json(data_dir / "legal_relationships.json")
        
        # Get strategy config
        self.strategy_config = self.relationships.get("expansion_strategies", {}).get(
            strategy,
            self.relationships.get("expansion_strategies", {}).get("moderate", {})
        )
        
        logger.info(f"Enhanced query expander initialized with strategy: {strategy}")
    
    def _load_json(self, file_path: Path) -> Dict:
        """Load JSON data file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load {file_path}: {e}")
            return {}
    
    def expand_query(
        self,
        query: str,
        use_cache: bool = True,
        include_synonyms: bool = True,
        include_concepts: bool = True,
        strategy: Optional[str] = None
    ) -> EnhancedExpandedQuery:
        """
        Expand query with legal-specific enhancements.
        
        Args:
            query: Original query
            use_cache: Whether to use cache
            include_synonyms: Include synonym expansions
            include_concepts: Include related concepts
            strategy: Override default expansion strategy
            
        Returns:
            EnhancedExpandedQuery with comprehensive expansions
        """
        # Use provided strategy or default
        strategy = strategy or self.strategy
        strategy_config = self.relationships.get("expansion_strategies", {}).get(
            strategy,
            self.strategy_config
        )
        
        # Check cache
        cache_key = f"{query}:{strategy}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        
        # Detect legal domain
        domain = self._detect_domain(query)
        
        # Get base expansion
        base_expansion = super().expand_query(
            query,
            use_cache=False,
            include_synonyms=include_synonyms,
            include_concepts=include_concepts
        )
        
        # Enhance with legal-specific expansions
        alternatives = list(base_expansion.alternatives)
        synonyms = dict(base_expansion.synonyms)
        related_concepts = list(base_expansion.related_concepts)
        broader_terms = []
        narrower_terms = []
        
        # Apply legal synonym expansions
        if include_synonyms:
            legal_alternatives, legal_synonyms = self._expand_with_synonyms(
                query,
                strategy_config
            )
            alternatives.extend(legal_alternatives)
            synonyms.update(legal_synonyms)
        
        # Apply relationship-based expansions
        if include_concepts:
            related, broader, narrower = self._expand_with_relationships(
                query,
                domain,
                strategy_config
            )
            related_concepts.extend(related)
            broader_terms.extend(broader)
            narrower_terms.extend(narrower)
        
        # Apply domain-specific context
        if domain:
            domain_concepts = self._expand_with_domain_context(query, domain, strategy_config)
            related_concepts.extend(domain_concepts)
        
        # Remove duplicates while preserving order
        alternatives = self._deduplicate(alternatives)
        related_concepts = self._deduplicate(related_concepts)
        broader_terms = self._deduplicate(broader_terms)
        narrower_terms = self._deduplicate(narrower_terms)
        
        # Limit results based on strategy
        max_alts = strategy_config.get("max_alternatives", self.max_alternatives)
        alternatives = alternatives[:max_alts]
        related_concepts = related_concepts[:max_alts]
        
        # Calculate quality score
        quality_score = self._calculate_quality_score(
            len(alternatives),
            len(related_concepts),
            domain is not None
        )
        
        result = EnhancedExpandedQuery(
            original=query,
            alternatives=alternatives,
            synonyms=synonyms,
            related_concepts=related_concepts,
            broader_terms=broader_terms,
            narrower_terms=narrower_terms,
            domain=domain,
            expansion_strategy=strategy,
            quality_score=quality_score,
            confidence=min(base_expansion.confidence + 0.1, 1.0)  # Boost confidence
        )
        
        # Cache result
        if use_cache:
            self._cache[cache_key] = result
        
        return result
    
    def _detect_domain(self, query: str) -> Optional[str]:
        """Detect legal domain from query."""
        query_lower = query.lower()
        
        domains = self.relationships.get("legal_domains", {})
        domain_scores = {}
        
        for domain_name, domain_data in domains.items():
            score = 0
            
            # Check key concepts
            for concept in domain_data.get("key_concepts", []):
                if concept.lower() in query_lower:
                    score += 2
            
            # Check key agencies
            for agency in domain_data.get("key_agencies", []):
                if agency.lower() in query_lower:
                    score += 3
            
            # Check key laws
            for law in domain_data.get("key_laws", []):
                if law.lower() in query_lower:
                    score += 2
            
            if score > 0:
                domain_scores[domain_name] = score
        
        if domain_scores:
            return max(domain_scores, key=domain_scores.get)
        
        return None
    
    def _expand_with_synonyms(
        self,
        query: str,
        strategy_config: Dict
    ) -> Tuple[List[str], Dict[str, List[str]]]:
        """Expand query using legal synonym database."""
        alternatives = []
        synonyms = {}
        
        query_lower = query.lower()
        
        # Get synonym depth from strategy
        max_depth = strategy_config.get("synonym_depth", 3)
        
        # Expand acronyms
        acronyms = self.synonyms.get("legal_acronyms", {})
        for acronym, expansion in acronyms.items():
            if acronym in query or acronym.lower() in query_lower:
                alt = query.replace(acronym, expansion)
                if alt != query:
                    alternatives.append(alt)
                synonyms[acronym] = [expansion]
        
        # Expand legal terms
        legal_terms = self.synonyms.get("legal_synonyms", {})
        for term, term_synonyms in legal_terms.items():
            if term in query_lower:
                for synonym in term_synonyms[:max_depth]:
                    alt = query_lower.replace(term, synonym)
                    if alt != query_lower:
                        alternatives.append(alt)
                synonyms[term] = term_synonyms[:max_depth]
        
        return alternatives, synonyms
    
    def _expand_with_relationships(
        self,
        query: str,
        domain: Optional[str],
        strategy_config: Dict
    ) -> Tuple[List[str], List[str], List[str]]:
        """Expand query using term relationships."""
        related_concepts = []
        broader_terms = []
        narrower_terms = []
        
        query_lower = query.lower()
        
        # Get relationship terms
        broader_map = self.relationships.get("broader_terms", {})
        narrower_map = self.relationships.get("narrower_terms", {})
        related_map = self.relationships.get("related_terms", {})
        
        # Find matching terms
        query_words = set(query_lower.split())
        
        # Broader terms
        if strategy_config.get("include_broader", False):
            for term, broader_list in broader_map.items():
                if term.lower() in query_lower or term.replace("_", " ").lower() in query_lower:
                    broader_terms.extend(broader_list)
        
        # Narrower terms
        if strategy_config.get("include_narrower", False):
            for term, narrower_list in narrower_map.items():
                if term.lower() in query_lower or term.replace("_", " ").lower() in query_lower:
                    narrower_terms.extend(narrower_list)
        
        # Related terms
        if strategy_config.get("include_related", True):
            for term, related_list in related_map.items():
                if term.lower() in query_lower or term.replace("_", " ").lower() in query_lower:
                    # Add related terms to query
                    for related_term in related_list[:3]:
                        related_concepts.append(f"{query} {related_term}")
        
        return related_concepts, broader_terms, narrower_terms
    
    def _expand_with_domain_context(
        self,
        query: str,
        domain: str,
        strategy_config: Dict
    ) -> List[str]:
        """Add domain-specific context terms."""
        concepts = []
        
        domains = self.relationships.get("legal_domains", {})
        domain_data = domains.get(domain, {})
        
        if not domain_data:
            return concepts
        
        # Add key concepts from domain
        context_terms = self.synonyms.get("legal_context_terms", {}).get(domain, [])
        
        for term in context_terms[:3]:
            concepts.append(f"{query} {term}")
        
        return concepts
    
    def _deduplicate(self, items: List[str]) -> List[str]:
        """Remove duplicates while preserving order."""
        seen = set()
        result = []
        for item in items:
            item_lower = item.lower().strip()
            if item_lower not in seen:
                seen.add(item_lower)
                result.append(item)
        return result
    
    def _calculate_quality_score(
        self,
        num_alternatives: int,
        num_concepts: int,
        has_domain: bool
    ) -> float:
        """Calculate quality score for expansion."""
        score = 0.5  # Base score
        
        # More alternatives = higher score
        if num_alternatives > 0:
            score += min(num_alternatives * 0.05, 0.2)
        
        # More concepts = higher score
        if num_concepts > 0:
            score += min(num_concepts * 0.05, 0.2)
        
        # Domain detection = higher score
        if has_domain:
            score += 0.1
        
        return min(score, 1.0)
    
    def get_strategy_info(self, strategy: Optional[str] = None) -> Dict:
        """Get information about an expansion strategy.
        
        Args:
            strategy: Strategy name (or use default)
            
        Returns:
            Dictionary with strategy configuration
        """
        strategy = strategy or self.strategy
        return self.relationships.get("expansion_strategies", {}).get(strategy, {})
    
    def list_available_strategies(self) -> List[str]:
        """List all available expansion strategies."""
        return list(self.relationships.get("expansion_strategies", {}).keys())

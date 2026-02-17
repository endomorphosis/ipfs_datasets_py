"""
Query Expansion Module for Legal Search.

This module provides LLM-based query expansion to improve search coverage
by generating alternative phrasings and related queries.

Features:
- Generate synonyms and alternative phrasings
- Expand queries with related legal concepts
- Create multiple search variations
- Support multiple LLM providers (OpenAI, Anthropic, local models)
- Cache expanded queries for performance

Usage:
    from ipfs_datasets_py.processors.legal_scrapers import QueryExpander
    
    expander = QueryExpander(llm_provider="openai")
    expanded = expander.expand_query("EPA water pollution regulations")
    # Returns: ["EPA water pollution regulations", 
    #           "Environmental Protection Agency water quality rules",
    #           "EPA clean water standards", ...]
"""

import logging
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import json

logger = logging.getLogger(__name__)

# Optional LLM dependencies
try:
    import openai
    HAVE_OPENAI = True
except ImportError:
    HAVE_OPENAI = False
    logger.debug("OpenAI not available for query expansion")

try:
    import anthropic
    HAVE_ANTHROPIC = True
except ImportError:
    HAVE_ANTHROPIC = False
    logger.debug("Anthropic not available for query expansion")


@dataclass
class ExpandedQuery:
    """Result of query expansion."""
    original: str
    alternatives: List[str] = field(default_factory=list)
    synonyms: Dict[str, List[str]] = field(default_factory=dict)
    related_concepts: List[str] = field(default_factory=list)
    confidence: float = 1.0
    
    def all_variations(self) -> List[str]:
        """Get all query variations including original."""
        return [self.original] + self.alternatives + self.related_concepts


class QueryExpander:
    """
    Expand legal search queries using LLM-based techniques.
    
    Supports multiple expansion strategies:
    1. Synonym expansion - Replace terms with legal synonyms
    2. Concept expansion - Add related legal concepts
    3. Phrasing variations - Rephrase in different ways
    4. Abbreviation expansion - Expand acronyms (EPA -> Environmental Protection Agency)
    
    Args:
        llm_provider: LLM provider to use ("openai", "anthropic", "local", None)
        api_key: API key for the provider (optional, can use env vars)
        model: Model name (e.g., "gpt-4", "claude-3-opus")
        cache_dir: Directory to cache expanded queries
        max_alternatives: Maximum number of alternative queries to generate
    """
    
    def __init__(
        self,
        llm_provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        cache_dir: Optional[str] = None,
        max_alternatives: int = 5
    ):
        self.llm_provider = llm_provider or os.getenv("LLM_PROVIDER", "openai")
        self.api_key = api_key or self._get_api_key()
        self.model = model or self._get_default_model()
        self.cache_dir = cache_dir
        self.max_alternatives = max_alternatives
        self._cache = {}
        
        # Initialize LLM client
        self._client = None
        if self.llm_provider and self.api_key:
            self._initialize_client()
    
    def _get_api_key(self) -> Optional[str]:
        """Get API key from environment."""
        if self.llm_provider == "openai":
            return os.getenv("OPENAI_API_KEY")
        elif self.llm_provider == "anthropic":
            return os.getenv("ANTHROPIC_API_KEY")
        return None
    
    def _get_default_model(self) -> str:
        """Get default model for provider."""
        if self.llm_provider == "openai":
            return "gpt-3.5-turbo"
        elif self.llm_provider == "anthropic":
            return "claude-3-sonnet-20240229"
        return "default"
    
    def _initialize_client(self):
        """Initialize the LLM client."""
        if self.llm_provider == "openai" and HAVE_OPENAI:
            openai.api_key = self.api_key
            self._client = openai
        elif self.llm_provider == "anthropic" and HAVE_ANTHROPIC:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        else:
            logger.warning(f"LLM provider {self.llm_provider} not available")
    
    def expand_query(
        self,
        query: str,
        use_cache: bool = True,
        include_synonyms: bool = True,
        include_concepts: bool = True
    ) -> ExpandedQuery:
        """
        Expand a query with alternatives and related concepts.
        
        Args:
            query: Original query string
            use_cache: Whether to use cached results
            include_synonyms: Include synonym-based expansions
            include_concepts: Include related concept expansions
            
        Returns:
            ExpandedQuery with alternatives and related terms
        """
        # Check cache first
        if use_cache and query in self._cache:
            return self._cache[query]
        
        # If no LLM available, use rule-based expansion
        if not self._client:
            result = self._rule_based_expansion(query)
        else:
            result = self._llm_based_expansion(
                query, 
                include_synonyms=include_synonyms,
                include_concepts=include_concepts
            )
        
        # Cache result
        if use_cache:
            self._cache[query] = result
        
        return result
    
    def _rule_based_expansion(self, query: str) -> ExpandedQuery:
        """
        Simple rule-based query expansion without LLM.
        
        Performs basic expansions like:
        - Acronym expansion (EPA -> Environmental Protection Agency)
        - Common legal term substitutions
        - Adding "rules", "regulations", "law" variations
        """
        alternatives = []
        synonyms = {}
        related_concepts = []
        
        # Common acronym expansions
        acronym_map = {
            "EPA": "Environmental Protection Agency",
            "OSHA": "Occupational Safety and Health Administration",
            "FDA": "Food and Drug Administration",
            "SEC": "Securities and Exchange Commission",
            "FTC": "Federal Trade Commission",
            "DOJ": "Department of Justice",
            "HHS": "Department of Health and Human Services",
            "DOL": "Department of Labor",
            "HUD": "Department of Housing and Urban Development",
        }
        
        # Expand acronyms
        query_lower = query
        for acronym, expansion in acronym_map.items():
            if acronym in query:
                alternatives.append(query.replace(acronym, expansion))
                synonyms[acronym] = [expansion]
        
        # Add common legal term variations
        legal_variations = [
            ("regulations", ["rules", "standards", "requirements", "provisions"]),
            ("law", ["statute", "act", "legislation", "code"]),
            ("compliance", ["adherence", "conformity", "observance"]),
            ("violation", ["breach", "infringement", "noncompliance"]),
        ]
        
        for term, variations in legal_variations:
            if term in query_lower.lower():
                for variation in variations[:2]:  # Limit variations
                    alt = query_lower.lower().replace(term, variation)
                    if alt != query_lower.lower():
                        alternatives.append(alt)
                synonyms[term] = variations
        
        # Add related search terms
        if "regulations" in query_lower.lower() or "rules" in query_lower.lower():
            related_concepts.append(f"{query} compliance")
            related_concepts.append(f"{query} enforcement")
        
        return ExpandedQuery(
            original=query,
            alternatives=alternatives[:self.max_alternatives],
            synonyms=synonyms,
            related_concepts=related_concepts[:3],
            confidence=0.7  # Lower confidence for rule-based
        )
    
    def _llm_based_expansion(
        self, 
        query: str,
        include_synonyms: bool = True,
        include_concepts: bool = True
    ) -> ExpandedQuery:
        """
        LLM-based query expansion using configured provider.
        
        Generates more sophisticated expansions using natural language understanding.
        """
        prompt = self._build_expansion_prompt(query, include_synonyms, include_concepts)
        
        try:
            if self.llm_provider == "openai":
                response = self._openai_expand(prompt)
            elif self.llm_provider == "anthropic":
                response = self._anthropic_expand(prompt)
            else:
                # Fallback to rule-based
                return self._rule_based_expansion(query)
            
            return self._parse_llm_response(query, response)
        
        except Exception as e:
            logger.warning(f"LLM expansion failed: {e}, falling back to rule-based")
            return self._rule_based_expansion(query)
    
    def _build_expansion_prompt(
        self, 
        query: str,
        include_synonyms: bool,
        include_concepts: bool
    ) -> str:
        """Build prompt for LLM-based expansion."""
        prompt = f"""You are a legal search expert. Expand the following legal search query to improve search coverage.

Original Query: "{query}"

Please provide:
"""
        if include_synonyms:
            prompt += "1. Alternative phrasings using legal synonyms and terminology\n"
        if include_concepts:
            prompt += "2. Related legal concepts and search terms\n"
        
        prompt += """
Return your response as a JSON object with this structure:
{
  "alternatives": ["alternative phrasing 1", "alternative phrasing 2", ...],
  "related_concepts": ["related concept 1", "related concept 2", ...]
}

Generate up to 5 alternatives. Focus on legal terminology and concepts relevant to regulatory and statutory search."""
        
        return prompt
    
    def _openai_expand(self, prompt: str) -> str:
        """Expand using OpenAI API."""
        if not HAVE_OPENAI or not self._client:
            raise RuntimeError("OpenAI not available")
        
        response = self._client.ChatCompletion.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a legal search expert."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        return response.choices[0].message.content
    
    def _anthropic_expand(self, prompt: str) -> str:
        """Expand using Anthropic API."""
        if not HAVE_ANTHROPIC or not self._client:
            raise RuntimeError("Anthropic not available")
        
        message = self._client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return message.content[0].text
    
    def _parse_llm_response(self, original: str, response: str) -> ExpandedQuery:
        """Parse LLM response into ExpandedQuery."""
        try:
            # Try to parse JSON response
            data = json.loads(response.strip().strip("```json").strip("```").strip())
            
            return ExpandedQuery(
                original=original,
                alternatives=data.get("alternatives", [])[:self.max_alternatives],
                synonyms={},
                related_concepts=data.get("related_concepts", [])[:3],
                confidence=0.9  # High confidence for LLM-based
            )
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON, using rule-based fallback")
            return self._rule_based_expansion(original)
    
    def clear_cache(self):
        """Clear the query expansion cache."""
        self._cache.clear()
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            "cached_queries": len(self._cache),
            "cache_size_bytes": sum(len(str(v)) for v in self._cache.values())
        }


# Convenience function for quick expansion
def expand_query(
    query: str,
    llm_provider: Optional[str] = None,
    max_alternatives: int = 5
) -> List[str]:
    """
    Quick query expansion function.
    
    Returns a list of query variations including the original.
    
    Args:
        query: Original query string
        llm_provider: LLM provider to use (None for rule-based)
        max_alternatives: Maximum number of alternatives
        
    Returns:
        List of query variations
    """
    expander = QueryExpander(
        llm_provider=llm_provider,
        max_alternatives=max_alternatives
    )
    result = expander.expand_query(query)
    return result.all_variations()

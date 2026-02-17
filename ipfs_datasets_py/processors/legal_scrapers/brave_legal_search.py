"""Brave Legal Search - Natural Language Search for Legal Rules and Regulations.

This module provides the main interface for searching legal rules and regulations
using natural language queries. It combines:
- Query processing (natural language understanding)
- Knowledge base lookup (federal/state/local entities)
- Search term generation (optimized for Brave Search API)
- Result aggregation and filtering
- Query result caching for performance

Example:
    >>> from ipfs_datasets_py.processors.legal_scrapers.brave_legal_search import BraveLegalSearch
    >>> 
    >>> # Initialize
    >>> searcher = BraveLegalSearch(api_key="your_brave_api_key")
    >>> 
    >>> # Search with natural language (uses cache if available)
    >>> results = searcher.search("EPA regulations on water pollution in California")
    >>> 
    >>> # View results
    >>> for result in results['results'][:5]:
    ...     print(f"{result['title']}: {result['url']}")
"""

import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
import json
import os
import hashlib
import time

logger = logging.getLogger(__name__)

# Import our components
from .knowledge_base_loader import LegalKnowledgeBase, load_knowledge_base
from .query_processor import QueryProcessor, QueryIntent
from .search_term_generator import SearchTermGenerator, SearchStrategy

# Import Brave Search client
try:
    from ipfs_datasets_py.web_archiving.brave_search_client import BraveSearchClient
    HAVE_BRAVE_CLIENT = True
except ImportError:
    HAVE_BRAVE_CLIENT = False
    BraveSearchClient = None
    logger.warning("BraveSearchClient not available - install web_archiving dependencies")


class BraveLegalSearch:
    """Natural language search interface for legal rules and regulations.
    
    This class provides a complete pipeline from natural language query to
    relevant legal search results using Brave Search API.
    
    Attributes:
        knowledge_base: Loaded legal entity knowledge base
        query_processor: Natural language query processor
        term_generator: Search term generator
        brave_client: Brave Search API client (if available)
    
    Example:
        >>> searcher = BraveLegalSearch()
        >>> results = searcher.search("OSHA workplace safety requirements")
        >>> print(f"Found {len(results['results'])} results")
        >>> print(f"Search terms used: {results['search_terms']}")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        knowledge_base_dir: Optional[str] = None,
        cache_enabled: bool = True,
        cache_ttl: int = 3600  # 1 hour default
    ):
        """Initialize the Brave Legal Search system.
        
        Args:
            api_key: Brave Search API key (or set BRAVE_API_KEY env var)
            knowledge_base_dir: Directory containing JSONL files (default: same as this module)
            cache_enabled: Whether to enable query result caching (default: True)
            cache_ttl: Cache time-to-live in seconds (default: 3600 = 1 hour)
        """
        # Initialize knowledge base
        if knowledge_base_dir is None:
            knowledge_base_dir = str(Path(__file__).parent)
        
        self.knowledge_base = LegalKnowledgeBase()
        try:
            self.knowledge_base.load_from_directory(knowledge_base_dir)
            logger.info("Knowledge base loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load knowledge base: {e}")
            raise
        
        # Initialize query processor
        self.query_processor = QueryProcessor()
        
        # Initialize search term generator
        self.term_generator = SearchTermGenerator(self.knowledge_base)
        
        # Initialize Brave Search client
        self.brave_client = None
        if HAVE_BRAVE_CLIENT:
            self.api_key = api_key or os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY")
            if self.api_key:
                try:
                    self.brave_client = BraveSearchClient(
                        api_key=self.api_key,
                        cache_enabled=cache_enabled
                    )
                    logger.info("Brave Search client initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize Brave Search client: {e}")
        else:
            logger.warning("Brave Search client not available - limited functionality")
        
        # Initialize query result cache
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self._query_cache: Dict[str, Dict[str, Any]] = {}
    
    def search(
        self,
        query: str,
        max_results: int = 20,
        country: str = "US",
        lang: str = "en",
        execute_search: bool = True
    ) -> Dict[str, Any]:
        """Search for legal rules and regulations using natural language.
        
        Args:
            query: Natural language query (e.g., "EPA water pollution regulations California")
            max_results: Maximum number of results to return per search term
            country: Country code for search localization
            lang: Language code for search results
            execute_search: Whether to execute the search (False = only generate terms)
            
        Returns:
            Dict containing:
                - query: Original query
                - intent: Parsed query intent
                - search_terms: Generated search terms
                - results: Search results (if execute_search=True)
                - metadata: Additional metadata
                - cache_hit: Whether results came from cache
        """
        logger.info(f"Processing query: {query}")
        
        # Check cache first
        cache_key = None
        if self.cache_enabled and execute_search:
            cache_key = self._generate_cache_key(query, max_results, country, lang)
            cached_result = self._get_from_cache(cache_key)
            if cached_result:
                logger.info(f"Cache hit for query: {query}")
                cached_result['cache_hit'] = True
                return cached_result
        
        # Step 1: Process query intent
        intent = self.query_processor.process(query)
        logger.debug(f"Query intent: {intent}")
        
        # Step 2: Generate search terms
        strategy = self.term_generator.generate(intent)
        search_terms = strategy.get_top_terms(limit=5)  # Top 5 search terms
        logger.info(f"Generated {len(search_terms)} search terms")
        
        result = {
            'query': query,
            'intent': {
                'topics': intent.topics,
                'legal_concepts': intent.legal_concepts,
                'jurisdictions': intent.jurisdictions,
                'agencies': intent.agencies,
                'municipalities': intent.municipalities,
                'legal_domains': intent.legal_domains,
                'scope': intent.scope,
                'confidence': intent.confidence
            },
            'search_terms': search_terms,
            'strategy': strategy.to_dict(),
            'results': [],
            'metadata': {
                'kb_stats': self.knowledge_base.get_statistics(),
                'brave_client_available': self.brave_client is not None
            },
            'cache_hit': False
        }
        
        # Step 3: Execute search if requested and client available
        if execute_search and self.brave_client:
            all_results = []
            seen_urls = set()
            
            for term in search_terms:
                try:
                    logger.debug(f"Searching for: {term}")
                    search_results = self.brave_client.search(
                        query=term,
                        count=max_results,
                        country=country,
                        search_lang=lang
                    )
                    
                    # Extract and deduplicate results
                    if 'web' in search_results and 'results' in search_results['web']:
                        for item in search_results['web']['results']:
                            url = item.get('url', '')
                            if url and url not in seen_urls:
                                all_results.append({
                                    'title': item.get('title', ''),
                                    'url': url,
                                    'description': item.get('description', ''),
                                    'search_term': term,
                                    'relevance_score': self._calculate_relevance(item, intent)
                                })
                                seen_urls.add(url)
                
                except Exception as e:
                    logger.error(f"Error searching for term '{term}': {e}")
            
            # Sort by relevance score
            all_results.sort(key=lambda x: x['relevance_score'], reverse=True)
            result['results'] = all_results[:max_results]  # Limit total results
            result['metadata']['total_results'] = len(all_results)
            result['metadata']['unique_urls'] = len(seen_urls)
        
        elif execute_search and not self.brave_client:
            result['error'] = "Brave Search client not available - set BRAVE_API_KEY environment variable"
        
        # Cache the result if caching is enabled
        if self.cache_enabled and execute_search and cache_key:
            self._add_to_cache(cache_key, result)
        
        return result
    
    def _calculate_relevance(self, search_result: Dict[str, Any], intent: QueryIntent) -> float:
        """Calculate relevance score for a search result.
        
        Args:
            search_result: Search result from Brave API
            intent: Original query intent
            
        Returns:
            Relevance score (0.0 to 1.0)
        """
        score = 0.5  # Base score
        
        title = search_result.get('title', '').lower()
        description = search_result.get('description', '').lower()
        url = search_result.get('url', '').lower()
        
        # Check for jurisdiction matches
        for jurisdiction in intent.jurisdictions:
            if jurisdiction.lower() in title or jurisdiction.lower() in description or jurisdiction.lower() in url:
                score += 0.1
        
        # Check for agency matches
        for agency in intent.agencies:
            if agency.lower() in title or agency.lower() in description:
                score += 0.15
        
        # Check for topic matches
        for topic in intent.topics:
            if topic.lower() in title:
                score += 0.1
            elif topic.lower() in description:
                score += 0.05
        
        # Check for legal concept matches
        for concept in intent.legal_concepts:
            if concept.lower() in title or concept.lower() in description:
                score += 0.08
        
        # Prefer .gov domains
        if '.gov' in url:
            score += 0.2
        elif '.org' in url:
            score += 0.05
        
        return min(1.0, score)
    
    def generate_search_terms(self, query: str) -> List[str]:
        """Generate search terms without executing search.
        
        Args:
            query: Natural language query
            
        Returns:
            List of generated search terms
        """
        result = self.search(query, execute_search=False)
        return result['search_terms']
    
    def explain_query(self, query: str) -> Dict[str, Any]:
        """Explain how a query would be processed.
        
        Args:
            query: Natural language query
            
        Returns:
            Dict with detailed explanation of query processing
        """
        intent = self.query_processor.process(query)
        strategy = self.term_generator.generate(intent)
        
        return {
            'query': query,
            'intent': str(intent),
            'intent_details': {
                'topics': intent.topics,
                'legal_concepts': intent.legal_concepts,
                'jurisdictions': intent.jurisdictions,
                'agencies': intent.agencies,
                'municipalities': intent.municipalities,
                'branches': intent.branches,
                'legal_domains': intent.legal_domains,
                'scope': intent.scope,
                'confidence': intent.confidence
            },
            'search_strategy': {
                'total_terms': len(strategy.terms),
                'recommended_limit': strategy.recommended_limit,
                'terms_by_category': {
                    'federal': len(strategy.get_by_category('federal')),
                    'state': len(strategy.get_by_category('state')),
                    'local': len(strategy.get_by_category('local')),
                    'general': len(strategy.get_by_category('general'))
                }
            },
            'top_search_terms': strategy.get_top_terms(10)
        }
    
    def get_knowledge_base_stats(self) -> Dict[str, Any]:
        """Get statistics about the loaded knowledge base.
        
        Returns:
            Dict with knowledge base statistics
        """
        return self.knowledge_base.get_statistics()
    
    def search_entities(
        self,
        query: str,
        entity_type: Optional[str] = None
    ) -> Dict[str, List[Any]]:
        """Search for entities in the knowledge base.
        
        Args:
            query: Search query
            entity_type: Optional type filter ('federal', 'state', 'municipal')
            
        Returns:
            Dict with matching entities by type
        """
        if entity_type == 'federal':
            return {'federal': self.knowledge_base.search_federal(query)}
        elif entity_type == 'state':
            return {'state': self.knowledge_base.search_state(query)}
        elif entity_type == 'municipal':
            return {'municipal': self.knowledge_base.search_municipal(query)}
        else:
            return self.knowledge_base.search_all(query)
    
    def _generate_cache_key(self, query: str, max_results: int, country: str, lang: str) -> str:
        """Generate a cache key for a query.
        
        Args:
            query: Query string
            max_results: Max results
            country: Country code
            lang: Language code
            
        Returns:
            Cache key string
        """
        # Create a unique key based on query parameters
        key_data = f"{query}:{max_results}:{country}:{lang}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get a result from cache if available and not expired.
        
        Args:
            cache_key: Cache key
            
        Returns:
            Cached result or None
        """
        if cache_key not in self._query_cache:
            return None
        
        cached = self._query_cache[cache_key]
        
        # Check if expired
        if time.time() - cached['timestamp'] > self.cache_ttl:
            # Remove expired entry
            del self._query_cache[cache_key]
            return None
        
        return cached['result']
    
    def _add_to_cache(self, cache_key: str, result: Dict[str, Any]) -> None:
        """Add a result to the cache.
        
        Args:
            cache_key: Cache key
            result: Result to cache
        """
        self._query_cache[cache_key] = {
            'result': result,
            'timestamp': time.time()
        }
    
    def clear_cache(self) -> int:
        """Clear the query result cache.
        
        Returns:
            Number of entries cleared
        """
        count = len(self._query_cache)
        self._query_cache.clear()
        logger.info(f"Cleared {count} cache entries")
        return count
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dict with cache statistics
        """
        total_entries = len(self._query_cache)
        expired_entries = 0
        current_time = time.time()
        
        for cached in self._query_cache.values():
            if current_time - cached['timestamp'] > self.cache_ttl:
                expired_entries += 1
        
        return {
            'enabled': self.cache_enabled,
            'total_entries': total_entries,
            'expired_entries': expired_entries,
            'active_entries': total_entries - expired_entries,
            'cache_ttl': self.cache_ttl
        }


def create_legal_search(
    api_key: Optional[str] = None,
    knowledge_base_dir: Optional[str] = None
) -> BraveLegalSearch:
    """Factory function to create a BraveLegalSearch instance.
    
    Args:
        api_key: Brave Search API key
        knowledge_base_dir: Directory containing JSONL files
        
    Returns:
        Configured BraveLegalSearch instance
    """
    return BraveLegalSearch(api_key=api_key, knowledge_base_dir=knowledge_base_dir)


# CLI-friendly function
def search_legal(query: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """Simple function for CLI/scripting use.
    
    Args:
        query: Natural language query
        api_key: Brave Search API key
        
    Returns:
        Search results dict
    """
    searcher = create_legal_search(api_key=api_key)
    return searcher.search(query)

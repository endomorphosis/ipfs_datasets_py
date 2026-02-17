"""
Enhanced Query Expansion MCP Tool.

This tool exposes the EnhancedQueryExpander which provides sophisticated
query expansion with 200+ legal synonyms, relationship mapping, and
domain-specific expansion strategies.

Core implementation: ipfs_datasets_py.processors.legal_scrapers.enhanced_query_expander
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


async def expand_legal_query(
    query: str,
    strategy: str = "balanced",
    max_expansions: int = 10,
    include_synonyms: bool = True,
    include_related: bool = True,
    include_acronyms: bool = True,
    domains: Optional[List[str]] = None,
    min_confidence: float = 0.5
) -> Dict[str, Any]:
    """
    Expand a legal query using sophisticated NLP and domain knowledge.
    
    This is a thin wrapper around EnhancedQueryExpander from the processors module.
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.enhanced_query_expander
    
    Features:
    - 200+ legal term synonyms
    - 40+ common acronyms
    - Relationship mapping (hierarchical, procedural, domain-specific)
    - 5 domain categories (administrative, criminal, civil, environmental, labor)
    - 3 expansion strategies (conservative, balanced, aggressive)
    
    Args:
        query: Legal query to expand (e.g., "EPA regulations on water quality")
        strategy: Expansion strategy - "conservative", "balanced", or "aggressive" (default: "balanced")
        max_expansions: Maximum number of expanded queries to generate (default: 10)
        include_synonyms: Include synonym-based expansions (default: True)
        include_related: Include related term expansions (default: True)
        include_acronyms: Include acronym expansions (default: True)
        domains: Specific legal domains to focus on (e.g., ["environmental", "administrative"])
        min_confidence: Minimum confidence score for expansions (0.0-1.0, default: 0.5)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - original_query: The input query
        - expanded_queries: List of expanded query variations
        - terms_expanded: Terms that were expanded
        - expansion_metadata: Details about the expansion process
        - strategy_used: The expansion strategy applied
        - total_expansions: Number of expansions generated
    
    Example:
        >>> result = await expand_legal_query(
        ...     query="EPA water regulations",
        ...     strategy="balanced",
        ...     max_expansions=5
        ... )
        >>> print(f"Generated {len(result['expanded_queries'])} query variations")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import EnhancedQueryExpander
        
        # Validate input
        if not query or not isinstance(query, str):
            return {
                "status": "error",
                "message": "Query must be a non-empty string"
            }
        
        if strategy not in ["conservative", "balanced", "aggressive"]:
            return {
                "status": "error",
                "message": "Strategy must be 'conservative', 'balanced', or 'aggressive'"
            }
        
        if max_expansions < 1 or max_expansions > 50:
            return {
                "status": "error",
                "message": "max_expansions must be between 1 and 50"
            }
        
        if not 0 <= min_confidence <= 1:
            return {
                "status": "error",
                "message": "min_confidence must be between 0.0 and 1.0"
            }
        
        if domains:
            valid_domains = ["administrative", "criminal", "civil", "environmental", "labor"]
            for domain in domains:
                if domain not in valid_domains:
                    return {
                        "status": "error",
                        "message": f"Invalid domain '{domain}'. Must be one of: {valid_domains}"
                    }
        
        # Initialize query expander
        expander = EnhancedQueryExpander()
        
        # Configure expansion options
        expansion_config = {
            "strategy": strategy,
            "max_expansions": max_expansions,
            "include_synonyms": include_synonyms,
            "include_related": include_related,
            "include_acronyms": include_acronyms,
            "min_confidence": min_confidence
        }
        
        if domains:
            expansion_config["domains"] = domains
        
        # Expand query
        result = expander.expand_query(query, **expansion_config)
        
        # Add MCP-specific metadata
        result["mcp_tool"] = "expand_legal_query"
        result["expansion_config"] = expansion_config
        
        return result
        
    except ImportError as e:
        logger.error(f"Import error in expand_legal_query: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal]"
        }
    except Exception as e:
        logger.error(f"Error in expand_legal_query MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "original_query": query
        }


async def get_legal_synonyms(
    term: Optional[str] = None,
    category: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get legal term synonyms and related terms from the knowledge base.
    
    Args:
        term: Specific legal term to get synonyms for (optional)
        category: Category to filter by (e.g., "regulation", "compliance", "enforcement")
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - synonyms: Dictionary mapping terms to their synonyms
        - total_terms: Total number of terms in the knowledge base
        - categories: Available categories
    
    Example:
        >>> result = await get_legal_synonyms(term="regulation")
        >>> print(result['synonyms']['regulation'])
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import EnhancedQueryExpander
        
        expander = EnhancedQueryExpander()
        
        if term:
            # Get synonyms for specific term
            synonyms = expander.get_synonyms(term)
            return {
                "status": "success",
                "term": term,
                "synonyms": synonyms,
                "count": len(synonyms)
            }
        else:
            # Get all synonyms or by category
            all_synonyms = expander.get_all_synonyms(category=category)
            return {
                "status": "success",
                "synonyms": all_synonyms,
                "total_terms": len(all_synonyms),
                "category": category,
                "message": f"Retrieved {len(all_synonyms)} legal terms"
            }
        
    except Exception as e:
        logger.error(f"Error getting legal synonyms: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


async def get_legal_relationships(
    term: Optional[str] = None,
    relationship_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get legal term relationships (hierarchical, procedural, domain-specific).
    
    Args:
        term: Specific legal term to get relationships for (optional)
        relationship_type: Type of relationship - "hierarchical", "procedural", or "domain"
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - relationships: Term relationships
        - relationship_types: Available relationship types
    
    Example:
        >>> result = await get_legal_relationships(term="regulation", relationship_type="hierarchical")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import EnhancedQueryExpander
        
        expander = EnhancedQueryExpander()
        
        if term:
            relationships = expander.get_relationships(term, relationship_type=relationship_type)
            return {
                "status": "success",
                "term": term,
                "relationships": relationships,
                "relationship_type": relationship_type
            }
        else:
            all_relationships = expander.get_all_relationships(relationship_type=relationship_type)
            return {
                "status": "success",
                "relationships": all_relationships,
                "total_terms": len(all_relationships),
                "relationship_type": relationship_type
            }
        
    except Exception as e:
        logger.error(f"Error getting legal relationships: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

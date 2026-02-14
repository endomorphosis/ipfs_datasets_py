"""
Deontological Reasoning Utilities

This module provides utility functions and pattern definitions for the
Deontological Reasoning system, including pattern matching and conflict detection.

Extracted from deontological_reasoning.py to improve modularity.
"""

import re
from typing import List, Set


class DeonticPatterns:
    """
    Patterns for extracting deontic statements from text.
    
    This class contains regex patterns for identifying different types
    of deontic modalities (obligations, permissions, prohibitions, etc.)
    in natural language text.
    """

    # Obligation patterns (must, shall, required)
    OBLIGATION_PATTERNS = [
        r'(\w+(?:\s+\w+)*)\s+(?:must|shall|are required to|have to|need to|are obligated to)\s+([^.!?]+)',
        r'(\w+(?:\s+\w+)*)\s+(?:has a duty to|has an obligation to|is responsible for)\s+([^.!?]+)',
        r'it is (?:mandatory|required|necessary) (?:for|that)\s+(\w+(?:\s+\w+)*)\s+(?:to\s+)?([^.!?]+)',
        r'(\w+(?:\s+\w+)*)\s+(?:is|are) (?:required|obligated|mandated) to\s+([^.!?]+)'
    ]

    # Permission patterns (may, can, allowed)
    PERMISSION_PATTERNS = [
        r'(\w+(?:\s+\w+)*)\s+(?:may|can|are allowed to|are permitted to|have the right to)\s+([^.!?]+)',
        r'(\w+(?:\s+\w+)*)\s+(?:is|are) (?:allowed|permitted|authorized) to\s+([^.!?]+)',
        r'it is (?:permissible|acceptable) (?:for|that)\s+(\w+(?:\s+\w+)*)\s+(?:to\s+)?([^.!?]+)'
    ]

    # Prohibition patterns (must not, cannot, forbidden)
    PROHIBITION_PATTERNS = [
        r'(\w+(?:\s+\w+)*)\s+(?:must not|cannot|shall not|are not allowed to|are forbidden to|are prohibited from)\s+([^.!?]+)',
        r'(\w+(?:\s+\w+)*)\s+(?:is|are) (?:forbidden|prohibited|banned) (?:from|to)\s+([^.!?]+)',
        r'it is (?:forbidden|prohibited|illegal) (?:for|that)\s+(\w+(?:\s+\w+)*)\s+(?:to\s+)?([^.!?]+)',
        r'no\s+(\w+(?:\s+\w+)*)\s+(?:may|can|shall)\s+([^.!?]+)'
    ]

    # Conditional patterns (if/then statements)
    CONDITIONAL_PATTERNS = [
        r'if\s+([^,]+),?\s+(?:then\s+)?(\w+(?:\s+\w+)*)\s+(must|shall|may|cannot|must not)\s+([^.!?]+)',
        r'when\s+([^,]+),?\s+(\w+(?:\s+\w+)*)\s+(must|shall|may|cannot|must not)\s+([^.!?]+)',
        r'in case of\s+([^,]+),?\s+(\w+(?:\s+\w+)*)\s+(must|shall|may|cannot|must not)\s+([^.!?]+)'
    ]

    # Exception patterns (unless, except)
    EXCEPTION_PATTERNS = [
        r'(\w+(?:\s+\w+)*)\s+(must|shall|may|cannot|must not)\s+([^,]+),?\s+(?:unless|except when|except if)\s+([^.!?]+)',
        r'(\w+(?:\s+\w+)*)\s+(must|shall|may|cannot|must not)\s+([^,]+),?\s+(?:but not when|but not if)\s+([^.!?]+)'
    ]


def extract_keywords(text: str) -> Set[str]:
    """
    Extract keywords from text for comparison.
    
    Tokenizes text and extracts meaningful keywords for similarity
    comparison between deontic statements.
    
    Args:
        text: Text to extract keywords from
        
    Returns:
        Set of extracted keywords
        
    Example:
        >>> keywords = extract_keywords("must pay taxes")
        >>> "pay" in keywords and "taxes" in keywords
        True
    """
    # Remove common stop words and extract meaningful terms
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
    words = re.findall(r'\b\w+\b', text.lower())
    return {word for word in words if word not in stop_words and len(word) > 2}


def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two texts using keyword overlap.
    
    Uses Jaccard similarity (intersection over union) to measure
    how similar two texts are based on their keywords.
    
    Args:
        text1: First text to compare
        text2: Second text to compare
        
    Returns:
        Similarity score between 0.0 and 1.0
        
    Example:
        >>> similarity = calculate_text_similarity("pay taxes", "pay bills")
        >>> 0.0 < similarity < 1.0
        True
    """
    keywords1 = extract_keywords(text1)
    keywords2 = extract_keywords(text2)
    
    if not keywords1 or not keywords2:
        return 0.0
    
    intersection = keywords1.intersection(keywords2)
    union = keywords1.union(keywords2)
    
    return len(intersection) / len(union) if union else 0.0


def are_entities_similar(entity1: str, entity2: str, threshold: float = 0.7) -> bool:
    """
    Check if two entity names are similar enough to be considered the same.
    
    Uses text similarity to determine if two entity names refer to the
    same or similar entities.
    
    Args:
        entity1: First entity name
        entity2: Second entity name
        threshold: Similarity threshold (default: 0.7)
        
    Returns:
        True if entities are similar, False otherwise
        
    Example:
        >>> are_entities_similar("citizen", "citizens")
        True
        >>> are_entities_similar("citizen", "corporation")
        False
    """
    # Direct match
    if entity1.lower() == entity2.lower():
        return True
    
    # Check for substring matches (handle plurals, etc.)
    e1 = entity1.lower()
    e2 = entity2.lower()
    if e1 in e2 or e2 in e1:
        return True
    
    # Check keyword similarity
    similarity = calculate_text_similarity(entity1, entity2)
    return similarity >= threshold


def are_actions_similar(action1: str, action2: str, threshold: float = 0.6) -> bool:
    """
    Check if two action descriptions are similar enough to be considered the same.
    
    Uses text similarity to determine if two action descriptions refer to
    the same or similar actions.
    
    Args:
        action1: First action description
        action2: Second action description
        threshold: Similarity threshold (default: 0.6)
        
    Returns:
        True if actions are similar, False otherwise
        
    Example:
        >>> are_actions_similar("pay taxes", "pay annual taxes")
        True
        >>> are_actions_similar("pay taxes", "file returns")
        False
    """
    # Direct match
    if action1.lower() == action2.lower():
        return True
    
    # Check for substring matches
    a1 = action1.lower()
    a2 = action2.lower()
    if a1 in a2 or a2 in a1:
        return True
    
    # Check keyword similarity
    similarity = calculate_text_similarity(action1, action2)
    return similarity >= threshold


def normalize_entity(entity: str) -> str:
    """
    Normalize entity name for consistent comparison.
    
    Args:
        entity: Entity name to normalize
        
    Returns:
        Normalized entity name
        
    Example:
        >>> normalize_entity("  CITIZEN  ")
        'citizen'
    """
    return entity.lower().strip()


def normalize_action(action: str) -> str:
    """
    Normalize action description for consistent comparison.
    
    Args:
        action: Action description to normalize
        
    Returns:
        Normalized action description
        
    Example:
        >>> normalize_action("  PAY TAXES  ")
        'pay taxes'
    """
    return action.lower().strip()


def extract_conditions_from_text(text: str) -> List[str]:
    """
    Extract conditional clauses from text.
    
    Identifies if/when/unless clauses that define conditions for
    deontic statements.
    
    Args:
        text: Text to extract conditions from
        
    Returns:
        List of extracted conditions
        
    Example:
        >>> conditions = extract_conditions_from_text("if employed, must pay")
        >>> len(conditions) > 0
        True
    """
    conditions = []
    
    # Match if/when/unless patterns
    patterns = [
        r'if\s+([^,]+)',
        r'when\s+([^,]+)',
        r'unless\s+([^,]+)',
        r'except when\s+([^,]+)',
        r'provided that\s+([^,]+)'
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        conditions.extend([m.strip() for m in matches])
    
    return conditions


def extract_exceptions_from_text(text: str) -> List[str]:
    """
    Extract exception clauses from text.
    
    Identifies unless/except clauses that define exceptions to
    deontic statements.
    
    Args:
        text: Text to extract exceptions from
        
    Returns:
        List of extracted exceptions
        
    Example:
        >>> exceptions = extract_exceptions_from_text("must pay unless exempt")
        >>> len(exceptions) > 0
        True
    """
    exceptions = []
    
    # Match unless/except patterns
    patterns = [
        r'unless\s+([^,]+)',
        r'except when\s+([^,]+)',
        r'except if\s+([^,]+)',
        r'but not when\s+([^,]+)'
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        exceptions.extend([m.strip() for m in matches])
    
    return exceptions


# Export utility functions
__all__ = [
    'DeonticPatterns',
    'extract_keywords',
    'calculate_text_similarity',
    'are_entities_similar',
    'are_actions_similar',
    'normalize_entity',
    'normalize_action',
    'extract_conditions_from_text',
    'extract_exceptions_from_text',
]

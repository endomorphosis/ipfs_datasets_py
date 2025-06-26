# ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/predicate_extractor.py
"""
Predicate extraction utilities for natural language to logic conversion.
"""
import re
from typing import List, Dict, Tuple, Any
from collections import defaultdict

def extract_predicates(text: str, nlp_doc: Any = None) -> Dict[str, List[str]]:
    """
    Extract predicates from natural language text.
    
    Args:
        text: Input text
        nlp_doc: Optional spaCy document for advanced parsing
        
    Returns:
        Dictionary with predicate types and extracted predicates
    """
    predicates = {
        "nouns": [],
        "verbs": [],
        "adjectives": [],
        "relations": []
    }
    
    # Basic pattern-based extraction for now
    # In a full implementation, this would use spaCy's dependency parsing
    
    # Extract noun phrases (potential unary predicates)
    noun_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b'
    nouns = re.findall(noun_pattern, text)
    predicates["nouns"] = [normalize_predicate(noun) for noun in set(nouns)]
    
    # Extract verbs (potential binary predicates)
    verb_pattern = r'\b(?:is|are|was|were|has|have|can|will|should|must)\s+(\w+)\b'
    verbs = re.findall(verb_pattern, text.lower())
    predicates["verbs"] = [normalize_predicate(verb) for verb in set(verbs)]
    
    # Extract adjectives (potential unary predicates)
    adj_pattern = r'\b(?:is|are|was|were)\s+(\w+)(?:\s|$|\.)'
    adjectives = re.findall(adj_pattern, text.lower())
    predicates["adjectives"] = [normalize_predicate(adj) for adj in set(adjectives)]
    
    return predicates

def normalize_predicate(predicate: str) -> str:
    """
    Normalize a predicate name for logical representation.
    
    Args:
        predicate: Raw predicate string
        
    Returns:
        Normalized predicate name
    """
    # Remove articles and common words
    words = predicate.strip().split()
    filtered_words = [w for w in words if w.lower() not in ['the', 'a', 'an', 'of', 'in', 'on', 'at']]
    
    # Capitalize first letter of each word and join
    normalized = ''.join(word.capitalize() for word in filtered_words)
    
    # Ensure it starts with uppercase letter
    if normalized and not normalized[0].isupper():
        normalized = normalized[0].upper() + normalized[1:]
    
    return normalized or "UnknownPredicate"

def extract_logical_relations(text: str) -> List[Dict[str, Any]]:
    """
    Extract logical relationships from text.
    
    Args:
        text: Input text
        
    Returns:
        List of relation dictionaries
    """
    relations = []
    
    # Implication patterns
    if_then_pattern = r'if\s+(.+?)\s+then\s+(.+?)(?:\.|$)'
    matches = re.findall(if_then_pattern, text.lower(), re.IGNORECASE)
    for premise, conclusion in matches:
        relations.append({
            "type": "implication",
            "premise": premise.strip(),
            "conclusion": conclusion.strip()
        })
    
    # Universal quantification patterns
    all_pattern = r'all\s+(\w+)\s+(?:are|is|have|has)\s+(.+?)(?:\.|$)'
    matches = re.findall(all_pattern, text.lower(), re.IGNORECASE)
    for subject, predicate in matches:
        relations.append({
            "type": "universal",
            "subject": subject.strip(),
            "predicate": predicate.strip()
        })
    
    # Existential quantification patterns
    some_pattern = r'(?:some|there (?:is|are))\s+(\w+)\s+(?:are|is|have|has)\s+(.+?)(?:\.|$)'
    matches = re.findall(some_pattern, text.lower(), re.IGNORECASE)
    for subject, predicate in matches:
        relations.append({
            "type": "existential", 
            "subject": subject.strip(),
            "predicate": predicate.strip()
        })
    
    return relations

def extract_variables(predicates: Dict[str, List[str]]) -> List[str]:
    """
    Generate appropriate variable names for predicates.
    
    Args:
        predicates: Dictionary of extracted predicates
        
    Returns:
        List of variable names
    """
    # Standard logic variable names
    standard_vars = ['x', 'y', 'z', 'u', 'v', 'w']
    
    # Count unique predicates to determine number of variables needed
    unique_count = len(set(
        predicates.get("nouns", []) + 
        predicates.get("verbs", []) + 
        predicates.get("adjectives", [])
    ))
    
    # Return appropriate number of variables
    return standard_vars[:max(1, unique_count)]

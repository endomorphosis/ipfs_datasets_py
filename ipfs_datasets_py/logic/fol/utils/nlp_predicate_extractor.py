"""
NLP-enhanced predicate extraction using spaCy.

This module provides advanced predicate extraction using spaCy's
linguistic analysis, including:
- Named Entity Recognition (NER)
- Part-of-Speech (POS) tagging
- Dependency parsing
- Semantic Role Labeling (SRL)

Falls back to regex-based extraction if spaCy is not available.
"""

import logging
from typing import Any, Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)

# Try to import spaCy
try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    logger.warning("spaCy not available. Install with: pip install spacy")

# Global spaCy model cache
_SPACY_MODEL: Optional[Any] = None


def get_spacy_model(model_name: str = "en_core_web_sm") -> Optional[Any]:
    """
    Get or load spaCy model (cached).
    
    Args:
        model_name: Name of spaCy model to load
        
    Returns:
        Loaded spaCy model or None if unavailable
    """
    global _SPACY_MODEL
    
    if not SPACY_AVAILABLE:
        return None
    
    if _SPACY_MODEL is None:
        try:
            _SPACY_MODEL = spacy.load(model_name)
            logger.info(f"Loaded spaCy model: {model_name}")
        except OSError:
            logger.warning(
                f"spaCy model '{model_name}' not found. "
                f"Install with: python -m spacy download {model_name}"
            )
            return None
    
    return _SPACY_MODEL


def extract_predicates_nlp(
    text: str,
    use_spacy: bool = True,
    spacy_model: str = "en_core_web_sm"
) -> Dict[str, List[str]]:
    """
    Extract predicates using NLP (spaCy) with regex fallback.
    
    Args:
        text: Natural language text to analyze
        use_spacy: Whether to attempt spaCy extraction
        spacy_model: Name of spaCy model to use
        
    Returns:
        Dictionary with categorized predicates
    """
    if use_spacy and SPACY_AVAILABLE:
        nlp = get_spacy_model(spacy_model)
        if nlp:
            try:
                return _extract_predicates_spacy(text, nlp)
            except Exception as e:
                logger.warning(f"spaCy extraction failed: {e}, falling back to regex")
    
    # Fallback to regex-based extraction
    from .predicate_extractor import extract_predicates
    return extract_predicates(text)


def _extract_predicates_spacy(text: str, nlp: Any) -> Dict[str, List[str]]:
    """
    Extract predicates using spaCy's linguistic analysis.
    
    Args:
        text: Text to analyze
        nlp: Loaded spaCy model
        
    Returns:
        Dictionary with categorized predicates
    """
    doc = nlp(text)
    
    predicates: Dict[str, List[str]] = {
        "nouns": [],
        "verbs": [],
        "adjectives": [],
        "relations": [],
        "entities": [],
    }
    
    # Extract nouns (including proper nouns)
    nouns = set()
    for token in doc:
        if token.pos_ in ["NOUN", "PROPN"]:
            # Get compound nouns
            if token.dep_ == "compound":
                head = token.head
                compound = f"{token.text}_{head.text}"
                nouns.add(compound)
            else:
                nouns.add(token.text)
    
    predicates["nouns"] = [_normalize_predicate(n) for n in nouns]
    
    # Extract verbs (main verbs, not auxiliaries)
    verbs = set()
    for token in doc:
        if token.pos_ == "VERB" and token.dep_ in ["ROOT", "xcomp", "ccomp"]:
            verbs.add(token.lemma_)
    
    predicates["verbs"] = [_normalize_predicate(v) for v in verbs]
    
    # Extract adjectives
    adjectives = set()
    for token in doc:
        if token.pos_ == "ADJ":
            adjectives.add(token.lemma_)
    
    predicates["adjectives"] = [_normalize_predicate(a) for a in adjectives]
    
    # Extract named entities
    entities = set()
    for ent in doc.ents:
        entities.add(ent.text)
    
    predicates["entities"] = [_normalize_predicate(e) for e in entities]
    
    # Extract semantic relations using dependency parsing
    relations = _extract_relations_from_dependencies(doc)
    predicates["relations"] = relations
    
    return predicates


def _extract_relations_from_dependencies(doc: Any) -> List[str]:
    """
    Extract semantic relations from dependency parse tree.
    
    Args:
        doc: spaCy Doc object
        
    Returns:
        List of relation descriptions
    """
    relations = []
    
    for token in doc:
        # Subject-Verb-Object relations
        if token.dep_ in ["nsubj", "nsubjpass"]:
            verb = token.head
            # Find object
            for child in verb.children:
                if child.dep_ in ["dobj", "attr", "oprd"]:
                    relation = f"{token.text}_{verb.lemma_}_{child.text}"
                    relations.append(_normalize_predicate(relation))
    
    return relations


def _normalize_predicate(predicate: str) -> str:
    """
    Normalize predicate name for logical representation.
    
    Args:
        predicate: Raw predicate string
        
    Returns:
        Normalized predicate in PascalCase
    """
    # Remove articles and prepositions
    stop_words = {"the", "a", "an", "of", "in", "on", "at", "to", "for"}
    
    words = predicate.strip().replace("_", " ").split()
    filtered = [w for w in words if w.lower() not in stop_words]
    
    if not filtered:
        return "UnknownPredicate"
    
    # Convert to PascalCase
    normalized = "".join(word.capitalize() for word in filtered)
    
    # Ensure starts with uppercase
    if normalized and not normalized[0].isupper():
        normalized = normalized[0].upper() + normalized[1:]
    
    return normalized or "UnknownPredicate"


def extract_semantic_roles(
    text: str,
    use_spacy: bool = True
) -> List[Dict[str, Any]]:
    """
    Extract semantic roles (agent, patient, action) from text.
    
    Args:
        text: Natural language text
        use_spacy: Whether to use spaCy
        
    Returns:
        List of semantic role structures
    """
    if not use_spacy or not SPACY_AVAILABLE:
        return []
    
    nlp = get_spacy_model()
    if not nlp:
        return []
    
    try:
        doc = nlp(text)
        roles = []
        
        for sent in doc.sents:
            # Find main verb (predicate)
            verb = None
            for token in sent:
                if token.pos_ == "VERB" and token.dep_ == "ROOT":
                    verb = token
                    break
            
            if not verb:
                continue
            
            role = {
                "action": verb.lemma_,
                "agent": None,
                "patient": None,
                "location": None,
                "time": None,
            }
            
            # Find arguments
            for child in verb.children:
                if child.dep_ in ["nsubj", "nsubjpass"]:
                    role["agent"] = child.text
                elif child.dep_ in ["dobj", "attr", "oprd"]:
                    role["patient"] = child.text
                elif child.dep_ in ["prep"]:
                    for prep_child in child.children:
                        if prep_child.dep_ == "pobj":
                            if child.text in ["in", "at", "on"]:
                                role["location"] = prep_child.text
                            elif child.text in ["during", "when", "before", "after"]:
                                role["time"] = prep_child.text
            
            roles.append(role)
        
        return roles
    
    except Exception as e:
        logger.warning(f"Semantic role extraction failed: {e}")
        return []


def extract_logical_relations_nlp(
    text: str,
    use_spacy: bool = True
) -> List[Dict[str, Any]]:
    """
    Extract logical relationships using NLP with regex fallback.
    
    Args:
        text: Natural language text
        use_spacy: Whether to attempt spaCy extraction
        
    Returns:
        List of logical relations
    """
    if use_spacy and SPACY_AVAILABLE:
        nlp = get_spacy_model()
        if nlp:
            try:
                return _extract_relations_spacy(text, nlp)
            except Exception as e:
                logger.warning(f"spaCy relation extraction failed: {e}")
    
    # Fallback to regex
    from .predicate_extractor import extract_logical_relations
    return extract_logical_relations(text)


def _extract_relations_spacy(text: str, nlp: Any) -> List[Dict[str, Any]]:
    """
    Extract logical relations using spaCy dependency parsing.
    
    Args:
        text: Text to analyze
        nlp: spaCy model
        
    Returns:
        List of relation dictionaries
    """
    doc = nlp(text)
    relations = []
    
    for sent in doc.sents:
        sent_text = sent.text.lower()
        
        # Check for conditional (if-then)
        if "if" in sent_text and "then" in sent_text:
            parts = sent_text.split("then", 1)
            if len(parts) == 2:
                premise = parts[0].replace("if", "").strip()
                conclusion = parts[1].strip()
                relations.append({
                    "type": "implication",
                    "premise": premise,
                    "conclusion": conclusion
                })
        
        # Check for universal quantification
        for token in sent:
            if token.text.lower() in ["all", "every", "each"]:
                # Find subject and predicate
                subject = None
                predicate = None
                
                for child in token.head.children:
                    if child.dep_ in ["nsubj", "attr"]:
                        subject = child.text
                    elif child.dep_ in ["acomp", "attr"]:
                        predicate = child.text
                
                if subject:
                    relations.append({
                        "type": "universal",
                        "subject": subject,
                        "predicate": predicate or sent.text
                    })
                break
        
        # Check for existential quantification
        for token in sent:
            if token.text.lower() in ["some", "there"]:
                subject = None
                predicate = None
                
                for child in token.head.children:
                    if child.dep_ in ["nsubj", "attr"]:
                        subject = child.text
                    elif child.dep_ in ["acomp", "attr"]:
                        predicate = child.text
                
                if subject:
                    relations.append({
                        "type": "existential",
                        "subject": subject,
                        "predicate": predicate or sent.text
                    })
                break
    
    return relations


def get_extraction_stats() -> Dict[str, Any]:
    """
    Get statistics about NLP extraction capabilities.
    
    Returns:
        Dictionary with availability and model info
    """
    stats = {
        "spacy_available": SPACY_AVAILABLE,
        "model_loaded": _SPACY_MODEL is not None,
        "fallback_mode": not SPACY_AVAILABLE,
    }
    
    if _SPACY_MODEL:
        stats["model_name"] = _SPACY_MODEL.meta.get("name", "unknown")
        stats["model_lang"] = _SPACY_MODEL.meta.get("lang", "unknown")
    
    return stats


__all__ = [
    "extract_predicates_nlp",
    "extract_semantic_roles",
    "extract_logical_relations_nlp",
    "get_extraction_stats",
    "get_spacy_model",
]

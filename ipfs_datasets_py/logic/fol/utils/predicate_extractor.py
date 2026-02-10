"""Predicate extraction utilities for natural language to logic conversion."""

import re
from collections import defaultdict
from typing import Any, Dict, List


def extract_predicates(text: str, nlp_doc: Any = None) -> Dict[str, List[str]]:
    """Extract predicates from natural language text."""
    predicates: Dict[str, List[str]] = {
        "nouns": [],
        "verbs": [],
        "adjectives": [],
        "relations": [],
    }

    noun_pattern = r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b"
    nouns = re.findall(noun_pattern, text)
    predicates["nouns"] = [normalize_predicate(noun) for noun in set(nouns)]

    verb_pattern = r"\b(?:is|are|was|were|has|have|can|will|should|must)\s+(\w+)\b"
    verbs = re.findall(verb_pattern, text.lower())
    predicates["verbs"] = [normalize_predicate(verb) for verb in set(verbs)]

    adj_pattern = r"\b(?:is|are|was|were)\s+(\w+)(?:\s|$|\.)"
    adjectives = re.findall(adj_pattern, text.lower())
    predicates["adjectives"] = [normalize_predicate(adj) for adj in set(adjectives)]

    return predicates


def normalize_predicate(predicate: str) -> str:
    """Normalize a predicate name for logical representation."""
    words = predicate.strip().split()
    filtered_words = [w for w in words if w.lower() not in ["the", "a", "an", "of", "in", "on", "at"]]
    normalized = "".join(word.capitalize() for word in filtered_words)
    if normalized and not normalized[0].isupper():
        normalized = normalized[0].upper() + normalized[1:]
    return normalized or "UnknownPredicate"


def extract_logical_relations(text: str) -> List[Dict[str, Any]]:
    """Extract logical relationships from text."""
    relations: List[Dict[str, Any]] = []

    if_then_pattern = r"if\s+(.+?)\s+then\s+(.+?)(?:\.|$)"
    matches = re.findall(if_then_pattern, text.lower(), re.IGNORECASE)
    for premise, conclusion in matches:
        relations.append({"type": "implication", "premise": premise.strip(), "conclusion": conclusion.strip()})

    all_pattern = r"all\s+(\w+)\s+(?:are|is|have|has)\s+(.+?)(?:\.|$)"
    matches = re.findall(all_pattern, text.lower(), re.IGNORECASE)
    for subject, predicate in matches:
        relations.append({"type": "universal", "subject": subject.strip(), "predicate": predicate.strip()})

    some_pattern = r"(?:some|there (?:is|are))\s+(\w+)\s+(?:are|is|have|has)\s+(.+?)(?:\.|$)"
    matches = re.findall(some_pattern, text.lower(), re.IGNORECASE)
    for subject, predicate in matches:
        relations.append({"type": "existential", "subject": subject.strip(), "predicate": predicate.strip()})

    return relations


def extract_variables(predicates: Dict[str, List[str]]) -> List[str]:
    """Generate appropriate variable names for predicates."""
    standard_vars = ["x", "y", "z", "u", "v", "w"]
    unique_count = len(
        set(predicates.get("nouns", []) + predicates.get("verbs", []) + predicates.get("adjectives", []))
    )
    return standard_vars[: max(1, unique_count)]

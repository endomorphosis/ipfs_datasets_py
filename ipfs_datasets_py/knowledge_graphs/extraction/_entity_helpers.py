"""
Entity extraction helper functions.

These pure-function utilities are used by :class:`KnowledgeGraphExtractor` and
can also be imported directly for lightweight rule-based extraction work without
instantiating the full extractor class.

Extracted from ``extractor.py`` as part of Workstream I (reduce god modules).
All public names are re-exported from ``extractor.py`` for backward compatibility.
"""

import re
from typing import List

from .entities import Entity

__all__ = [
    "_map_spacy_entity_type",
    "_map_transformers_entity_type",
    "_rule_based_entity_extraction",
    "_string_similarity",
]


def _map_spacy_entity_type(spacy_type: str) -> str:
    """Map spaCy entity labels to our normalized entity types."""
    mapping = {
        'PERSON': 'person',
        'PER': 'person',
        'ORG': 'organization',
        'GPE': 'location',
        'LOC': 'location',
        'FAC': 'location',
        'DATE': 'date',
        'TIME': 'time',
        'EVENT': 'event',
        'PRODUCT': 'product',
        'WORK_OF_ART': 'work',
        'LAW': 'law',
        'LANGUAGE': 'language',
        'PERCENT': 'number',
        'MONEY': 'number',
        'QUANTITY': 'number',
        'ORDINAL': 'number',
        'CARDINAL': 'number',
        'NORP': 'group',
    }
    return mapping.get(spacy_type, 'entity')


def _map_transformers_entity_type(transformers_type: str) -> str:
    """Map HuggingFace NER tags (e.g. B-PER/I-ORG) to normalized entity types."""
    tag = transformers_type
    if '-' in tag:
        tag = tag.split('-', 1)[1]

    tag = tag.upper()
    mapping = {
        'PER': 'person',
        'PERSON': 'person',
        'ORG': 'organization',
        'GPE': 'location',
        'LOC': 'location',
        'DATE': 'date',
        'TIME': 'time',
        'MISC': 'entity',
    }
    return mapping.get(tag, 'entity')


def _rule_based_entity_extraction(text: str) -> List[Entity]:
    """Extract entities using lightweight regex patterns.

    This is the default extraction path when spaCy/transformers are unavailable.
    """
    entities: List[Entity] = []
    entity_names_seen: set[tuple[str, str]] = set()

    patterns: List[tuple[str, str, float]] = [
        # Simple full names (e.g. "Marie Curie")
        (r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", 'person', 0.8),
        # Titles
        (r"(?:Dr\.|Prof\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})(?=\s|$|[.,;:])", 'person', 0.9),
        # Person names
        (r"Principal\s+Investigator:\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", 'person', 0.95),
        # Organizations (AI)
        (r"(Google\s+DeepMind|OpenAI|Anthropic|Microsoft\s+Research|Meta\s+AI|IBM\s+Research)", 'organization', 0.95),
        (r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Institute|Research|Lab|Laboratory|Center|University)", 'organization', 0.85),
        # Fields / techniques
        (r"\b((?:artificial\s+intelligence|machine\s+learning|deep\s+learning|neural\s+networks?|computer\s+vision|natural\s+language\s+processing|reinforcement\s+learning))\b", 'field', 0.95),
        (r"\b((?:transformer\s+architectures?|attention\s+mechanisms?|self-supervised\s+learning|few-shot\s+learning|cross-modal\s+reasoning))\b", 'field', 0.9),
        (r"\b((?:physics-informed\s+neural\s+networks?|graph\s+neural\s+networks?|generative\s+models?))\b", 'field', 0.9),
        # Technology/tools (heuristic)
        (r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:framework|platform|system|technology|tool|algorithm)s?\b", 'technology', 0.8),
        # Projects
        (r"Project\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?):?\s+", 'project', 0.9),
        # Medical/healthcare
        (r"\b((?:medical\s+)?(?:image\s+analysis|radiology|pathology|healthcare|diagnosis|medical\s+AI))\b", 'field', 0.9),
        # Conferences
        (r"\b(NeurIPS|ICML|ICLR|AAAI|IJCAI|NIPS)\b", 'conference', 0.95),
        # Years/timeframes
        (r"\b(20[0-9]{2}(?:-20[0-9]{2})?)\b", 'date', 0.8),
        # Locations
        (r"\b(?:in|at|from|to|headquartered\s+in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:,\s*[A-Z][A-Z])?)\b", 'location', 0.8),
    ]

    for pattern, entity_type, confidence in patterns:
        flags = re.IGNORECASE if entity_type in ['field', 'technology'] else 0

        for match in re.finditer(pattern, text, flags):
            name = match.group(1).strip()

            name = re.sub(r'\s+', ' ', name)
            name = name.strip('.,;:')

            if not name or len(name) < 2:
                continue

            name_key = (name.lower(), entity_type)
            if name_key in entity_names_seen:
                continue
            entity_names_seen.add(name_key)

            if name.lower() in {'timeline', 'the', 'and', 'our', 'this', 'that', 'with', 'from'}:
                continue

            start_pos = max(0, match.start() - 20)
            end_pos = min(len(text), match.end() + 20)
            source_snippet = text[start_pos:end_pos].replace('\\n', ' ').strip()

            entities.append(
                Entity(
                    entity_type=entity_type,
                    name=name,
                    confidence=confidence,
                    source_text=source_snippet,
                )
            )

    return entities


def _string_similarity(str1: str, str2: str) -> float:
    """Calculate similarity between two strings using Jaccard word overlap.

    Args:
        str1: First string
        str2: Second string

    Returns:
        Similarity score in [0, 1].
    """
    words1 = set(str1.lower().split())
    words2 = set(str2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = words1.intersection(words2)
    union = words1.union(words2)

    return len(intersection) / len(union)

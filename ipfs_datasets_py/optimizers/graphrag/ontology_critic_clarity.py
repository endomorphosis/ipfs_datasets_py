"""Clarity dimension evaluation for OntologyCritic."""

from __future__ import annotations

from typing import Any, Dict


def evaluate_clarity(ontology: Dict[str, Any], context: Any) -> float:
    """Evaluate clarity of entity definitions and naming conventions.

    Scores based on:
    - property completeness (entities with >= 1 property)
    - naming convention consistency (camelCase / snake_case / PascalCase)
    - non-empty text field
    - short-name penalty (entity texts < 3 chars suggest poor extraction)
    - confidence coverage (entities with explicit confidence > 0)
    """
    import re as _re

    entities = ontology.get("entities", [])

    if not entities:
        return 0.0

    # Sub-score 1: property completeness (entities with >= 1 property)
    with_props = sum(1 for e in entities if isinstance(e, dict) and e.get("properties"))
    prop_score = with_props / len(entities)

    # Sub-score 2: naming convention consistency (all camelCase OR all snake_case)
    names = [e.get("text", "") or e.get("id", "") for e in entities if isinstance(e, dict)]
    camel = sum(1 for n in names if _re.match(r"^[a-z][a-zA-Z0-9]*$", n))
    snake = sum(1 for n in names if _re.match(r"^[a-z][a-z0-9_]*$", n))
    pascal = sum(1 for n in names if _re.match(r"^[A-Z][a-zA-Z0-9]*$", n))
    dominant = max(camel, snake, pascal)
    naming_score = dominant / max(len(names), 1)

    # Sub-score 3: non-empty text field
    with_text = sum(1 for e in entities if isinstance(e, dict) and e.get("text"))
    text_score = with_text / len(entities)

    # Sub-score 4: short-name penalty -- texts with < 3 chars suggest noisy extraction
    short_names = sum(
        1 for e in entities
        if isinstance(e, dict) and len((e.get("text") or e.get("id") or "").strip()) < 3
    )
    short_penalty = short_names / len(entities)

    # Sub-score 5: confidence coverage -- fraction with explicit confidence > 0
    with_confidence = sum(
        1 for e in entities
        if isinstance(e, dict) and isinstance(e.get("confidence"), (int, float)) and e["confidence"] > 0
    )
    confidence_score = with_confidence / len(entities)

    score = (
        prop_score * 0.3
        + naming_score * 0.2
        + text_score * 0.2
        + confidence_score * 0.2
        - short_penalty * 0.1
    )
    return round(min(max(score, 0.0), 1.0), 4)

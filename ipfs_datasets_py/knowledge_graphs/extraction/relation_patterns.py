"""Relation pattern defaults for rule-based extraction.

This module exists to keep `extractor.py` smaller and to make the default
pattern set easier to test and evolve independently.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _default_relation_patterns() -> List[Dict[str, Any]]:
    """Create default relation extraction patterns.

    Returns:
        List[Dict]: List of relation patterns
    """
    return [
        # Enhanced patterns for AI research content
        {
            "name": "expert_in",
            "pattern": r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+is\s+(?:a\s+)?(?:leading\s+)?expert\s+in\s+([a-z][a-z\s]+)",
            "source_type": "person",
            "target_type": "field",
            "confidence": 0.9,
        },
        {
            "name": "focuses_on",
            "pattern": r"(Project\s+[A-Z][a-z]+)\s+focus(?:es)?\s+on\s+([a-z][a-z\s]+)",
            "source_type": "project",
            "target_type": "field",
            "confidence": 0.8,
        },
        {
            "name": "contributed_to",
            "pattern": r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+contributed\s+to\s+([a-z][a-z\s]+)",
            "source_type": "person",
            "target_type": "field",
            "confidence": 0.85,
        },
        {
            "name": "works_at_org",
            "pattern": r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:works?\s+at|is\s+at|joined)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.9,
        },
        # Original comprehensive patterns
        {
            "name": "founded_by",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:was|were)\s+founded\s+by\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "person",
            "confidence": 0.8,
        },
        {
            "name": "works_for",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+works\s+(?:for|at)\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.8,
        },
        {
            "name": "part_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+(?:a\s+)?part\s+of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "entity",
            "target_type": "entity",
            "confidence": 0.7,
        },
        {
            "name": "located_in",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:is|are)\s+(?:located|based)\s+in\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "entity",
            "target_type": "location",
            "confidence": 0.8,
        },
        {
            "name": "created",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+created\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "entity",
            "confidence": 0.8,
        },
        {
            "name": "developed",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+developed\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "entity",
            "confidence": 0.8,
        },
        {
            "name": "acquired",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+acquired\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "organization",
            "confidence": 0.9,
        },
        {
            "name": "parent_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+(?:the\s+)?parent\s+(?:company\s+)?of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "organization",
            "confidence": 0.9,
        },
        {
            "name": "subsidiary_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+(?:a\s+)?subsidiary\s+of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "organization",
            "confidence": 0.9,
        },
        {
            "name": "headquartered_in",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+headquartered\s+in\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "location",
            "confidence": 0.9,
        },
        {
            "name": "founded_in",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:was|were)\s+founded\s+in\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "location",
            "confidence": 0.8,
        },
        {
            "name": "CEO_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+(?:is|was)\s+(?:the\s+)?CEO\s+of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.8,
        },
        {
            "name": "partnered_with",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+partnered\s+with\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "organization",
            "confidence": 0.8,
        },
        {
            "name": "collaborated_with",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+collaborated\s+with\s+(\b\w+(?:\s+\w+){0,3}?)\b",
            "source_type": "person",
            "target_type": "person",
            "confidence": 0.7,
        },
        {
            "name": "met_with",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+met\s+with\s+(\b\w+(?:\s+\w+){0,3}?)\b",
            "source_type": "person",
            "target_type": "person",
            "confidence": 0.7,
        },
        {
            "name": "attended",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+attended\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "event",
            "confidence": 0.7,
        },
        {
            "name": "graduated_from",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+graduated\s+from\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.8,
        },
        {
            "name": "studied_at",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+studied\s+at\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.8,
        },
        {
            "name": "published",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+published\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "work",
            "confidence": 0.7,
        },
        {
            "name": "wrote",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+wrote\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "work",
            "confidence": 0.7,
        },
        {
            "name": "won",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+won\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "award",
            "confidence": 0.7,
        },
        {
            "name": "received",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+received\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "award",
            "confidence": 0.7,
        },
        {
            "name": "known_for",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+is\s+known\s+for\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "work",
            "confidence": 0.8,
        },
        {
            "name": "invented",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+invented\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "entity",
            "confidence": 0.8,
        },
        {
            "name": "pioneered",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+pioneered\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "field",
            "confidence": 0.9,
        },
        {
            "name": "leads",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+leads\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.8,
        },
        {
            "name": "works_at",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+works\s+at\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.8,
        },
    ]

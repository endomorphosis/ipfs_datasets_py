#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Biomolecule Discovery MCP tool wrapper.
(Business logic lives in biomolecule_engine.py)

MCP tool functions:
- discover_biomolecules_for_target
"""

from typing import Any, Dict, List, Optional

from .biomolecule_engine import (  # noqa: F401  (re-export for backward compat)
    BiomoleculeCandidate,
    BiomoleculeDiscoveryEngine,
    BiomoleculeType,
    InteractionType,
)


def discover_biomolecules_for_target(
    target: str,
    discovery_type: str = "binders",
    max_results: int = 50,
    min_confidence: float = 0.5,
) -> List[Dict[str, Any]]:
    """Discover biomolecule candidates for a given target via RAG.

    Provides a simple interface for RAG-based biomolecule discovery that can
    be easily integrated with generative protein binder design workflows.

    Args:
        target: Target protein, enzyme, or pathway name.
        discovery_type: One of ``"binders"``, ``"inhibitors"``, or ``"pathway"``.
        max_results: Maximum number of candidates to return.
        min_confidence: Minimum confidence threshold (0–1).

    Returns:
        List of biomolecule candidate dictionaries.

    Example::

        candidates = discover_biomolecules_for_target(
            "SARS-CoV-2 spike protein",
            discovery_type="binders",
            max_results=20,
        )
        for c in candidates:
            print(f"{c['name']}: {c['confidence_score']:.2f}")
    """
    engine = BiomoleculeDiscoveryEngine(use_rag=True)

    if discovery_type == "binders":
        candidates = engine.discover_protein_binders(
            target_protein=target, min_confidence=min_confidence, max_results=max_results
        )
    elif discovery_type == "inhibitors":
        candidates = engine.discover_enzyme_inhibitors(
            target_enzyme=target, min_confidence=min_confidence, max_results=max_results
        )
    elif discovery_type == "pathway":
        candidates = engine.discover_pathway_biomolecules(
            pathway_name=target, min_confidence=min_confidence, max_results=max_results
        )
    else:
        raise ValueError(f"Unknown discovery_type: {discovery_type!r}")

    return [
        {
            "name": c.name,
            "biomolecule_type": c.biomolecule_type.value,
            "uniprot_id": c.uniprot_id,
            "pubchem_id": c.pubchem_id,
            "sequence": c.sequence,
            "structure": c.structure,
            "function": c.function,
            "interactions": c.interactions,
            "therapeutic_relevance": c.therapeutic_relevance,
            "confidence_score": c.confidence_score,
            "evidence_sources": c.evidence_sources,
            "metadata": c.metadata,
        }
        for c in candidates
    ]


__all__ = [
    "BiomoleculeType",
    "InteractionType",
    "BiomoleculeCandidate",
    "BiomoleculeDiscoveryEngine",
    "discover_biomolecules_for_target",
]

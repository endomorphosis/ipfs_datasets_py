"""Batch 312: strict snapshot regression for known-good OntologyCritic scores."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic


def _reference_ontology() -> dict:
    return {
        "entities": [
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9, "properties": {"role": "engineer"}},
            {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85, "properties": {"role": "manager"}},
            {"id": "e3", "text": "Acme Corp", "type": "Organization", "confidence": 0.95, "properties": {"industry": "tech"}},
            {"id": "e4", "text": "London", "type": "Location", "confidence": 0.88, "properties": {"country": "UK"}},
            {"id": "e5", "text": "Software", "type": "Concept", "confidence": 0.7, "properties": {"domain": "technology"}},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e3", "type": "worksAt", "confidence": 0.85},
            {"id": "r2", "source_id": "e2", "target_id": "e3", "type": "manages", "confidence": 0.8},
            {"id": "r3", "source_id": "e1", "target_id": "e4", "type": "locatedIn", "confidence": 0.7},
            {"id": "r4", "source_id": "e3", "target_id": "e5", "type": "produces", "confidence": 0.75},
        ],
    }


def test_critic_score_matches_frozen_snapshot() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "fixtures"
        / "optimizers"
        / "graphrag"
        / "golden_critic_score_reference.json"
    )
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    critic = OntologyCritic(use_llm=False)
    score = critic.evaluate_ontology(_reference_ontology(), SimpleNamespace(domain="general"))

    actual = {
        "overall": round(float(score.overall), 6),
        "completeness": round(float(score.completeness), 6),
        "consistency": round(float(score.consistency), 6),
        "clarity": round(float(score.clarity), 6),
        "granularity": round(float(score.granularity), 6),
        "relationship_coherence": round(float(score.relationship_coherence), 6),
        "domain_alignment": round(float(score.domain_alignment), 6),
    }

    assert actual == pytest.approx(expected, abs=1e-6)

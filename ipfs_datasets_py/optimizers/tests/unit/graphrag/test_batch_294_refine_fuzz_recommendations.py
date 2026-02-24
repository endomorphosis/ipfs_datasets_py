"""Fuzz-style robustness checks for OntologyMediator.refine_ontology()."""

from __future__ import annotations

import random
import string
from types import SimpleNamespace
from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


def _feedback(recommendations: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        recommendations=recommendations,
        overall=0.5,
        completeness=0.5,
        consistency=0.5,
        clarity=0.5,
        granularity=0.5,
        relationship_coherence=0.5,
        domain_alignment=0.5,
    )


def test_refine_ontology_handles_random_recommendation_strings() -> None:
    mediator = OntologyMediator(generator=Mock(), critic=Mock())
    rng = random.Random(11)
    alphabet = string.ascii_letters + string.digits + " _-:;.,!?"

    ontology = {
        "entities": [
            {"id": "e1", "text": "alice", "type": "person"},
            {"id": "e2", "text": "bob", "type": "person"},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "works_with"},
        ],
    }
    ctx = SimpleNamespace(domain="general")

    for _ in range(30):
        rec_count = rng.randint(1, 8)
        recommendations = [
            "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 60)))
            for _ in range(rec_count)
        ]
        refined = mediator.refine_ontology(ontology, _feedback(recommendations), ctx)

        assert isinstance(refined, dict)
        assert "entities" in refined
        assert "relationships" in refined
        assert "metadata" in refined
        assert isinstance(refined["metadata"].get("refinement_actions", []), list)

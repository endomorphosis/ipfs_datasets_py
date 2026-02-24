"""Cleanup coverage for stale unchecked TODO helper/test items."""

from __future__ import annotations

import random
import string
from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def test_learning_adapter_reset_feedback_clears_history_and_returns_count() -> None:
    adapter = OntologyLearningAdapter()
    adapter.apply_feedback(0.2, actions=[])
    adapter.apply_feedback(0.8, actions=[])

    cleared = adapter.reset_feedback()

    assert cleared == 2
    assert adapter.has_feedback() is False


def test_mediator_peek_undo_returns_top_without_popping() -> None:
    mediator = OntologyMediator(generator=Mock(), critic=Mock())
    mediator.stash({"entities": [{"id": "e1"}], "relationships": []})
    mediator.stash({"entities": [{"id": "e2"}], "relationships": []})

    top = mediator.peek_undo()

    assert top is not None
    assert top["entities"][0]["id"] == "e2"
    assert mediator.get_undo_depth() == 2


def test_pipeline_domain_setter_updates_runtime_domain() -> None:
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    assert pipeline.domain == "general"

    pipeline.domain = "legal"

    assert pipeline.domain == "legal"


def test_entity_roundtrip_property_via_from_dict() -> None:
    rng = random.Random(7)
    alphabet = string.ascii_letters

    for _ in range(50):
        entity_id = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
        entity_type = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
        entity_text = "".join(rng.choice(alphabet + " ") for _ in range(rng.randint(1, 16))).strip() or "x"
        confidence = rng.random()
        properties = {
            f"k{i}": rng.choice([rng.randint(0, 100), round(rng.random(), 6), "".join(rng.choice(alphabet) for _ in range(3))])
            for i in range(rng.randint(0, 4))
        }

        entity = Entity(
            id=entity_id,
            type=entity_type,
            text=entity_text,
            confidence=confidence,
            properties=properties,
        )
        restored = Entity.from_dict(entity.to_dict())
        assert restored == entity

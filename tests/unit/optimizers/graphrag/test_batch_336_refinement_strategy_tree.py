"""Batch 336: decision tree visualization tests for refinement strategy logic."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic


def _mediator() -> OntologyMediator:
    return OntologyMediator(generator=OntologyGenerator(), critic=OntologyCritic())


def test_render_refinement_strategy_tree_mermaid_contains_key_nodes() -> None:
    mediator = _mediator()

    rendered = mediator.render_refinement_strategy_tree("mermaid")

    assert rendered.startswith("flowchart TD")
    assert "converged" in rendered
    assert "merge_duplicates" in rendered
    assert "add_missing_relationships" in rendered
    assert "normalize_names" in rendered


def test_render_refinement_strategy_tree_ascii_contains_key_nodes() -> None:
    mediator = _mediator()

    rendered = mediator.render_refinement_strategy_tree("ascii")

    assert "Start: score + recommendations" in rendered
    assert "add_missing_properties" in rendered
    assert "split_entity" in rendered
    assert "converged/no-op" in rendered


def test_render_refinement_strategy_tree_rejects_unknown_format() -> None:
    mediator = _mediator()

    with pytest.raises(ValueError, match="Unsupported format"):
        mediator.render_refinement_strategy_tree("json")

"""Batch 334: tests for predefined refinement playbook system in OntologyMediator."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


@pytest.fixture
def mediator() -> OntologyMediator:
    return OntologyMediator(generator=OntologyGenerator(), critic=OntologyCritic())


def test_default_playbooks_are_registered(mediator: OntologyMediator) -> None:
    playbooks = mediator.list_refinement_playbooks()
    assert "clarity_first" in playbooks
    assert "consistency_first" in playbooks
    assert "coverage_first" in playbooks
    assert playbooks["clarity_first"]["actions"] == [
        "add_missing_properties",
        "normalize_names",
    ]


def test_register_playbook_accepts_known_actions(mediator: OntologyMediator) -> None:
    mediator.register_refinement_playbook(
        "custom_cleanup",
        ["merge_duplicates", "normalize_names"],
        description="Deduplicate entities then normalize naming.",
    )

    playbooks = mediator.list_refinement_playbooks()
    assert "custom_cleanup" in playbooks
    assert playbooks["custom_cleanup"]["actions"] == ["merge_duplicates", "normalize_names"]


def test_register_playbook_rejects_unknown_actions(mediator: OntologyMediator) -> None:
    with pytest.raises(ValueError, match="unknown refinement action"):
        mediator.register_refinement_playbook("invalid", ["not_an_action"])


def test_run_refinement_playbook_rejects_unknown_name(mediator: OntologyMediator) -> None:
    with pytest.raises(KeyError, match="unknown playbook"):
        mediator.run_refinement_playbook("missing", ontology={"entities": [], "relationships": []}, context=None)


def test_run_refinement_playbook_applies_clarity_first_sequence(mediator: OntologyMediator) -> None:
    ontology = {
        "entities": [
            {"id": "e1", "type": "some_concept", "text": "alpha"},
            {"id": "e2", "type": "other_concept", "text": "beta"},
        ],
        "relationships": [],
        "metadata": {},
    }

    refined = mediator.run_refinement_playbook("clarity_first", ontology, context=None)

    for entity in refined["entities"]:
        assert entity.get("properties"), "clarity_first should add missing properties"
        assert entity["type"] in {"SomeConcept", "OtherConcept"}

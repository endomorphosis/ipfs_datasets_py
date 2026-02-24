"""Coverage for remaining unchecked GraphRAG P3 helper methods."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def test_logic_validator_max_path_length_aliases_shortest_path_length() -> None:
    validator = LogicValidator(use_cache=False)
    ontology = {
        "entities": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
        "relationships": [
            {"source_id": "e1", "target_id": "e2"},
            {"source_id": "e2", "target_id": "e3"},
        ],
    }
    assert validator.max_path_length(ontology, "e1", "e3") == 2
    assert validator.max_path_length(ontology, "e3", "e1") == 2
    assert validator.max_path_length(ontology, "e1", "missing") == -1


def test_pipeline_reset_to_initial_clears_runtime_state() -> None:
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=2)
    pipeline._run_history = [SimpleNamespace(score=SimpleNamespace(overall=0.4))]  # type: ignore[attr-defined]
    pipeline._last_refinement_state = SimpleNamespace(round=1)  # type: ignore[attr-defined]
    pipeline._adapter.apply_feedback(0.9, actions=[])  # type: ignore[attr-defined]

    cleared = pipeline.reset_to_initial()

    assert cleared == 1
    assert pipeline._run_history == []  # type: ignore[attr-defined]
    assert pipeline._last_refinement_state is None  # type: ignore[attr-defined]
    assert pipeline._adapter.has_feedback() is False  # type: ignore[attr-defined]


def test_mediator_undo_stack_summary_formats_labels() -> None:
    mediator = OntologyMediator(generator=Mock(), critic=Mock())
    mediator._undo_stack = [  # type: ignore[attr-defined]
        {"action": "snapshot:before"},
        {"entities": [], "relationships": []},
        "manual-note",
    ]

    assert mediator.undo_stack_summary() == [
        "snapshot:before",
        "{'entities': [], 'relationships': []}",
        "manual-note",
    ]

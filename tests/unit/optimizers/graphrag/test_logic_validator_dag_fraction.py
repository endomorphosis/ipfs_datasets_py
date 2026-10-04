"""Tests for LogicValidator.dag_fraction()."""

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


def test_dag_fraction_empty_is_one() -> None:
    """Empty ontology currently counts as fully acyclic."""
    lv = LogicValidator()
    assert lv.dag_fraction({"entities": [], "relationships": []}) == 1.0


def test_dag_fraction_simple_dag_is_one() -> None:
    lv = LogicValidator()
    ontology = {
        "entities": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
        "relationships": [
            {"source_id": "e1", "target_id": "e2"},
            {"source_id": "e2", "target_id": "e3"},
        ],
    }
    assert lv.dag_fraction(ontology) == 1.0


def test_dag_fraction_full_cycle_is_zero() -> None:
    lv = LogicValidator()
    ontology = {
        "entities": [{"id": "e1"}, {"id": "e2"}],
        "relationships": [
            {"source_id": "e1", "target_id": "e2"},
            {"source_id": "e2", "target_id": "e1"},
        ],
    }
    assert lv.dag_fraction(ontology) == 0.0

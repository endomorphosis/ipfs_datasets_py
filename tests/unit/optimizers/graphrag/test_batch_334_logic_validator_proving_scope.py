"""Batch 334: explicit proving-scope behavior for LogicValidator."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


def test_proving_scope_reports_structural_subset_when_tdfol_available() -> None:
    validator = LogicValidator(use_cache=False)
    validator._tdfol_available = True

    scope = validator.proving_scope()

    assert scope["scope"] == "structural_tdfol_subset"
    assert scope["full_tdfol_proving"] is False
    assert scope["backend"] == "structural_checker"


def test_proving_scope_reports_basic_fallback_when_tdfol_unavailable() -> None:
    validator = LogicValidator(use_cache=False)
    validator._tdfol_available = False

    scope = validator.proving_scope()

    assert scope["scope"] == "basic_structural_fallback"
    assert scope["full_tdfol_proving"] is False
    assert scope["backend"] == "basic_structural"


def test_check_consistency_includes_scope_metadata_on_basic_path() -> None:
    validator = LogicValidator(use_cache=False)
    validator._tdfol_available = False

    ontology = {
        "entities": [{"id": "e1"}],
        "relationships": [{"id": "r1", "source_id": "e1", "target_id": "missing", "type": "rel"}],
    }

    result = validator.check_consistency(ontology)

    assert result.metadata["scope"] == "basic_structural_fallback"
    assert result.metadata["full_tdfol_proving"] is False


def test_check_consistency_includes_scope_metadata_on_structural_tdfol_path() -> None:
    validator = LogicValidator(use_cache=False)
    validator._tdfol_available = True

    ontology = {
        "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
        "relationships": [],
    }

    result = validator.check_consistency(ontology)

    assert result.metadata["scope"] == "structural_tdfol_subset"
    assert result.metadata["full_tdfol_proving"] is False

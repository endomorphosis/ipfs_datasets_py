"""UIR-020: formal ontology and compiler contracts."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir.formalize.contracts import (
    CoverageDisposition,
    FormalView,
    ResultAuthority,
    default_compiler_contracts,
    validate_compiler_contract,
)
from ipfs_datasets_py.logic.ui_ux_ir.formalize.ontology import (
    REQUIRED_SYMBOL_KINDS,
    SymbolKind,
    default_ui_formal_ontology,
    validate_ontology,
)


def test_default_ontology_covers_required_symbol_kinds() -> None:
    ontology = default_ui_formal_ontology()
    validated = validate_ontology(ontology)
    kinds = {symbol.kind for symbol in validated.symbols}
    assert kinds == REQUIRED_SYMBOL_KINDS
    assert SymbolKind.COMPONENT in kinds
    assert SymbolKind.PROGRAM_REF in kinds
    # Every symbol has explicit coverage dispositions.
    for symbol in validated.symbols:
        assert symbol.view_coverage
        assert all(isinstance(v, FormalView) for v in symbol.view_coverage)
        assert all(isinstance(d, CoverageDisposition) for d in symbol.view_coverage.values())


def test_source_semantics_have_explicit_coverage_including_out_of_scope() -> None:
    ontology = default_ui_formal_ontology()
    by_id = {c.source_semantic_id: c for c in ontology.source_coverage}
    assert "source.semantic.raw_emg" in by_id
    raw = by_id["source.semantic.raw_emg"]
    assert all(d is CoverageDisposition.OUT_OF_SCOPE for d in raw.dispositions.values())
    destructive = by_id["source.semantic.destructive_action"]
    assert destructive.dispositions[FormalView.TDFOL] is CoverageDisposition.FULL


def test_compiler_contracts_declare_backend_bounds_and_authority() -> None:
    contracts = default_compiler_contracts()
    assert {c.view for c in contracts} >= {
        FormalView.FLOGIC,
        FormalView.EVENT_CALCULUS,
        FormalView.TDFOL,
        FormalView.DCEC,
    }
    for contract in contracts:
        validated = validate_compiler_contract(contract)
        assert validated.backend_bounds
        assert validated.result_authority in set(ResultAuthority)
        assert validated.input_symbol_kinds

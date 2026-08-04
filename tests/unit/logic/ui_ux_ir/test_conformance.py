"""UIR-062: cross-language golden corpus and Python conformance harness."""

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.logic.ui_ux_ir.canonicalize import ui_ir_sha256
from ipfs_datasets_py.logic.ui_ux_ir.conformance import (
    UIIR_CROSS_LANGUAGE_PARITY_INTERFACE,
    default_golden_path,
    evaluate_vector,
    load_golden_vectors,
    run_conformance,
)
from ipfs_datasets_py.logic.ui_ux_ir.decoder import decode_ui_ir

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "ui_ux_ir"
    / "v1"
    / "golden_vectors.json"
)


def test_golden_fixture_exists() -> None:
    assert FIXTURE.is_file(), f"missing {FIXTURE}"
    data = load_golden_vectors(FIXTURE)
    assert data["interface"] == UIIR_CROSS_LANGUAGE_PARITY_INTERFACE
    assert data["vectors"]
    kinds = {v["kind"] for v in data["vectors"]}
    assert "valid_document" in kinds
    assert "invalid_document" in kinds
    assert "decision" in kinds
    assert "receipt" in kinds


def test_python_conformance_suite_passes() -> None:
    report = run_conformance(FIXTURE)
    assert report.passed is True, report.to_dict()
    assert report.interface == UIIR_CROSS_LANGUAGE_PARITY_INTERFACE
    assert all(r.passed for r in report.results)


def test_valid_vector_digest_stable() -> None:
    data = load_golden_vectors(FIXTURE)
    valid = next(v for v in data["vectors"] if v["kind"] == "valid_document")
    decoded = decode_ui_ir(valid["document"])
    assert ui_ir_sha256(decoded) == valid["canonical_sha256"]
    result = evaluate_vector(valid)
    assert result.passed is True
    assert result.canonical_sha256 == valid["canonical_sha256"]


def test_invalid_vectors_fail_closed() -> None:
    data = load_golden_vectors(FIXTURE)
    for vector in data["vectors"]:
        if vector["kind"] != "invalid_document":
            continue
        result = evaluate_vector(vector)
        assert result.passed is True, result.detail


def test_decision_and_receipt_semantics() -> None:
    data = load_golden_vectors(FIXTURE)
    for vector in data["vectors"]:
        if vector["kind"] in {"decision", "receipt"}:
            assert evaluate_vector(vector).passed is True


def test_default_golden_path_resolves() -> None:
    path = default_golden_path(FIXTURE.parents[3])  # tests/
    # parents: test file -> unit/logic/ui_ux_ir -> unit/logic -> unit -> tests
    # FIXTURE.parents[3] is tests/
    assert path.name == "golden_vectors.json"

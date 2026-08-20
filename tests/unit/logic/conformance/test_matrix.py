"""Unit tests for LogicCapabilityMatrix@1 baseline materialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.conformance.matrix import (
    DEFAULT_MATRIX,
    DOMAIN_IDS,
    INTERFACE,
    MATERIALIZATION_TARGET,
    PROVIDER_AXES,
    SCHEMA_VERSION,
    AuthorityCeiling,
    AvailabilityStatus,
    CapabilityCell,
    CapabilityMatrixError,
    SourceEvidence,
    SupportStatus,
    build_default_matrix,
    cell_id,
    default_baseline_path,
    ensure_baseline_seal,
    load_matrix_baseline,
    materialize_capability_matrix,
    render_matrix_json,
    render_matrix_seal_json,
    to_matrix_seal_dict,
    write_matrix_baseline,
)

DATASETS_ROOT = Path(__file__).resolve().parents[4]
BASELINE_PATH = (
    DATASETS_ROOT
    / "docs"
    / "architecture"
    / "logic"
    / "logic_parser_baseline"
    / "capability_matrix.json"
)

REQUIRED_PROVIDERS = {
    "z3",
    "cvc5",
    "tla_tlc",
    "apalache",
    "datalog_secpal",
    "proverif",
    "tamarin",
    "hyperltl_autohyper_mchyper",
    "vampire",
    "eprover",
    "hammer",
    "lean",
    "rocq",
    "isabelle",
    "runtime_mtl",
    "ergoai",
    "symbolicai",
}

SUPPORT_VALUES = {status.value for status in SupportStatus}
AVAILABILITY_VALUES = {status.value for status in AvailabilityStatus}
AUTHORITY_VALUES = {status.value for status in AuthorityCeiling}


def test_default_matrix_covers_required_axes() -> None:
    matrix = build_default_matrix()
    assert matrix.interface == INTERFACE
    assert matrix.schema_version == SCHEMA_VERSION
    assert tuple(matrix.domains) == tuple(sorted(DOMAIN_IDS))
    assert set(matrix.provider_ids) == REQUIRED_PROVIDERS
    assert len(matrix.formal_views) >= 30
    assert len(matrix.cells) == len(matrix.formal_views) * len(matrix.providers)
    assert len(matrix.cells) > 0


def test_support_availability_authority_are_independent_axes() -> None:
    matrix = DEFAULT_MATRIX
    observed_support = {cell.support for cell in matrix.cells}
    observed_availability = {cell.availability for cell in matrix.cells}
    observed_authority = {cell.authority_ceiling for cell in matrix.cells}

    assert SupportStatus.NATIVE in observed_support
    assert (
        SupportStatus.TRANSLATED in observed_support
        or SupportStatus.BOUNDED in observed_support
    )
    assert SupportStatus.ADVISORY in observed_support
    assert SupportStatus.DECLARATION_ONLY in observed_support
    assert SupportStatus.UNSUPPORTED in observed_support

    assert AvailabilityStatus.SOURCE_MISSING in observed_availability
    assert AvailabilityStatus.NOT_PROBED in observed_availability
    assert AvailabilityStatus.DECLARED in observed_availability
    assert AvailabilityStatus.NOT_DECLARED in observed_availability

    assert AuthorityCeiling.EXACT in observed_authority
    assert AuthorityCeiling.KERNEL in observed_authority
    assert AuthorityCeiling.ADVISORY in observed_authority
    assert AuthorityCeiling.NONE in observed_authority

    # A supported semantic edge still leaves availability unprobed.
    native_unprobed = [
        cell
        for cell in matrix.cells
        if cell.support is SupportStatus.NATIVE
        and cell.availability is AvailabilityStatus.NOT_PROBED
    ]
    assert native_unprobed, "native support must not imply a live availability claim"

    # Advisory support cannot claim kernel authority.
    for cell in matrix.cells:
        if cell.support is SupportStatus.ADVISORY:
            assert cell.authority_ceiling in {
                AuthorityCeiling.ADVISORY,
                AuthorityCeiling.CANDIDATE,
                AuthorityCeiling.NONE,
            }


def test_every_cell_has_exact_source_evidence() -> None:
    for cell in DEFAULT_MATRIX.cells:
        assert cell.evidence, f"{cell.id} missing evidence"
        for item in cell.evidence:
            assert item.path
            assert ".." not in item.path
            assert not item.path.startswith("/")
            assert item.kind


def test_unknown_and_unimplemented_cells_are_exposed_for_refill() -> None:
    matrix = DEFAULT_MATRIX
    unknown = matrix.unknown_cells()
    refill = matrix.refill_cells()
    assert matrix.support_histogram()[SupportStatus.UNKNOWN.value] == len(
        [cell for cell in matrix.cells if cell.support is SupportStatus.UNKNOWN]
    )
    assert tuple(cell.id for cell in unknown) == tuple(
        sorted(cell.id for cell in unknown)
    )
    # UI domain must fully appear as declaration-only refill work.
    ui_cells = matrix.cells_for_domain("ui_ux_ir")
    assert ui_cells
    assert all(cell.support is SupportStatus.DECLARATION_ONLY for cell in ui_cells)
    assert all(
        cell.availability is AvailabilityStatus.SOURCE_MISSING for cell in ui_cells
    )
    assert all(cell.refill_eligible for cell in ui_cells)
    assert {cell.id for cell in ui_cells}.issubset({cell.id for cell in refill})
    # Unknown/unimplemented coordinates remain addressable by stable ids.
    for cell in unknown:
        assert cell.id == cell_id(
            cell.domain_id,
            cell.formal_view_id,
            cell.family_id,
            cell.profile_id,
            cell.provider_id,
        )
    unimplemented = matrix.unimplemented_cells()
    assert unimplemented
    # Seal surface exposes unknown, unimplemented, and refill coordinates.
    seal = to_matrix_seal_dict(matrix)
    assert seal["unknown_cells"] == [cell.id for cell in unknown]
    assert seal["unimplemented_cells"] == [cell.id for cell in unimplemented]
    assert seal["refill_cells"] == [cell.id for cell in refill]
    assert seal["unknown_count"] == len(unknown)
    assert seal["unimplemented_count"] == len(unimplemented)
    assert seal["refill_count"] == len(refill)
    assert set(seal["unknown_cells"]).issubset(set(seal["refill_cells"]))
    assert set(seal["unimplemented_cells"]).issubset(set(seal["refill_cells"]))


def test_provider_evidence_subset_from_plan_is_present() -> None:
    provider_ids = set(DEFAULT_MATRIX.provider_ids)
    for required in REQUIRED_PROVIDERS:
        assert required in provider_ids
        cells = DEFAULT_MATRIX.cells_for_provider(required)
        assert cells
        assert any(cell.evidence for cell in cells)


def test_z3_security_claim_is_native_exact_and_not_probed() -> None:
    target = cell_id(
        "security_ir",
        "security-ir-view/claim/v1",
        "first_order",
        "verification_condition",
        "z3",
    )
    cell = DEFAULT_MATRIX.get_cell(target)
    assert cell is not None
    assert cell.support is SupportStatus.NATIVE
    assert cell.authority_ceiling is AuthorityCeiling.EXACT
    assert cell.availability is AvailabilityStatus.NOT_PROBED
    assert any("z3" in item.path for item in cell.evidence)


def test_ergoai_and_symbolicai_remain_advisory() -> None:
    ergo = DEFAULT_MATRIX.cells_for_provider("ergoai")
    assert any(cell.support is SupportStatus.ADVISORY for cell in ergo)
    for cell in ergo:
        if cell.support is SupportStatus.ADVISORY:
            assert cell.authority_ceiling is AuthorityCeiling.ADVISORY
            assert cell.availability is AvailabilityStatus.NOT_DECLARED

    symai = DEFAULT_MATRIX.cells_for_provider("symbolicai")
    assert symai
    for cell in symai:
        if cell.domain_id == "ui_ux_ir":
            assert cell.support is SupportStatus.DECLARATION_ONLY
            assert cell.availability is AvailabilityStatus.SOURCE_MISSING
            assert cell.authority_ceiling is AuthorityCeiling.NONE
            continue
        assert cell.support in {
            SupportStatus.ADVISORY,
            SupportStatus.UNSUPPORTED,
        }
        if cell.support is SupportStatus.ADVISORY:
            assert cell.authority_ceiling is AuthorityCeiling.CANDIDATE


def test_histograms_cover_closed_vocabularies() -> None:
    matrix = DEFAULT_MATRIX
    assert set(matrix.support_histogram()) == SUPPORT_VALUES
    assert set(matrix.availability_histogram()) == AVAILABILITY_VALUES
    assert set(matrix.authority_histogram()) == AUTHORITY_VALUES
    assert sum(matrix.support_histogram().values()) == len(matrix.cells)
    assert sum(matrix.availability_histogram().values()) == len(matrix.cells)
    assert sum(matrix.authority_histogram().values()) == len(matrix.cells)


def test_round_trip_dict_and_json(tmp_path: Path) -> None:
    matrix = build_default_matrix()
    restored = type(matrix).from_dict(matrix.to_dict())
    assert restored.to_dict() == matrix.to_dict()
    assert restored.content_digest() == matrix.content_digest()

    full_path = tmp_path / "capability_matrix.full.json"
    write_matrix_baseline(matrix, full_path, full_cells=True)
    loaded_full = load_matrix_baseline(full_path)
    assert loaded_full.to_dict() == matrix.to_dict()
    payload = json.loads(full_path.read_text(encoding="utf-8"))
    assert payload["interface"] == INTERFACE
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["content_digest_sha256"] == matrix.content_digest()
    assert payload["unknown_count"] == len(matrix.unknown_cells())
    assert payload["refill_count"] == len(matrix.refill_cells())
    assert payload["unknown_cells"] == [cell.id for cell in matrix.unknown_cells()]
    assert payload["refill_cells"] == [cell.id for cell in matrix.refill_cells()]

    seal_path = tmp_path / "capability_matrix.seal.json"
    write_matrix_baseline(matrix, seal_path, full_cells=False)
    loaded_seal = load_matrix_baseline(seal_path)
    assert loaded_seal.to_dict() == matrix.to_dict()
    seal_payload = json.loads(seal_path.read_text(encoding="utf-8"))
    assert seal_payload["materialization"] == MATERIALIZATION_TARGET
    assert seal_payload["cell_count"] == len(matrix.cells)
    assert "cells" not in seal_payload
    assert seal_payload == to_matrix_seal_dict(matrix)
    assert seal_path.read_text(encoding="utf-8") == render_matrix_seal_json(matrix)


def test_sealed_baseline_matches_default_matrix(tmp_path: Path) -> None:
    assert BASELINE_PATH.is_file(), f"missing baseline report: {BASELINE_PATH}"
    seal = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert seal["interface"] == INTERFACE
    assert seal["schema_version"] == SCHEMA_VERSION
    assert seal["materialization"] == MATERIALIZATION_TARGET
    assert seal["version"] == "1.0.0"
    assert "evidence_subset" in seal["metadata"]
    assert set(seal["metadata"]["evidence_subset"]) == REQUIRED_PROVIDERS

    # Materialization pointer loads the full live matrix.
    on_disk = load_matrix_baseline(BASELINE_PATH)
    expected = build_default_matrix()
    assert on_disk.to_dict() == expected.to_dict()
    assert BASELINE_PATH.read_text(encoding="utf-8") == render_matrix_seal_json(
        expected
    )
    assert default_baseline_path(datasets_root=DATASETS_ROOT) == BASELINE_PATH

    # Full compact seal (axes + unknown/unimplemented/refill) is deterministic.
    refreshed = tmp_path / "capability_matrix.seal.json"
    ensure_baseline_seal(refreshed)
    assert refreshed.read_text(encoding="utf-8") == render_matrix_seal_json(expected)
    loaded = load_matrix_baseline(refreshed)
    assert loaded.to_dict() == expected.to_dict()
    full_seal = json.loads(refreshed.read_text(encoding="utf-8"))
    assert full_seal["content_digest_sha256"] == expected.content_digest()
    assert full_seal["unknown_cells"] == [cell.id for cell in expected.unknown_cells()]
    assert full_seal["unimplemented_cells"] == [
        cell.id for cell in expected.unimplemented_cells()
    ]
    assert full_seal["refill_cells"] == [cell.id for cell in expected.refill_cells()]
    assert full_seal["dimensions"] == expected.to_baseline_dict()["dimensions"]


def test_cell_validation_rejects_authority_support_contradictions() -> None:
    with pytest.raises(CapabilityMatrixError):
        CapabilityCell(
            domain_id="security_ir",
            formal_view_id="security-ir-view/claim/v1",
            family_id="first_order",
            provider_id="z3",
            support=SupportStatus.UNSUPPORTED,
            availability=AvailabilityStatus.DECLARED,
            authority_ceiling=AuthorityCeiling.EXACT,
            evidence=(
                SourceEvidence(
                    path="docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md"
                ),
            ),
        )
    with pytest.raises(CapabilityMatrixError):
        CapabilityCell(
            domain_id="security_ir",
            formal_view_id="security-ir-view/claim/v1",
            family_id="first_order",
            provider_id="z3",
            support=SupportStatus.ADVISORY,
            availability=AvailabilityStatus.NOT_DECLARED,
            authority_ceiling=AuthorityCeiling.KERNEL,
            evidence=(
                SourceEvidence(
                    path="docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md"
                ),
            ),
        )
    with pytest.raises(CapabilityMatrixError):
        CapabilityCell(
            domain_id="ui_ux_ir",
            formal_view_id="ui-ux-ir-view/ontology/v1",
            family_id="frame_logic",
            provider_id="z3",
            support=SupportStatus.NATIVE,
            availability=AvailabilityStatus.SOURCE_MISSING,
            authority_ceiling=AuthorityCeiling.EXACT,
            evidence=(
                SourceEvidence(
                    path="docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md"
                ),
            ),
        )


def test_materialize_is_deterministic_and_side_effect_free() -> None:
    first = materialize_capability_matrix()
    second = materialize_capability_matrix()
    assert first.to_dict() == second.to_dict()
    assert first.content_digest() == second.content_digest()
    assert {item.provider_id for item in PROVIDER_AXES} == REQUIRED_PROVIDERS
    assert DEFAULT_MATRIX.provider("tlc").provider_id == "tla_tlc"
    assert DEFAULT_MATRIX.provider("symai").provider_id == "symbolicai"
    # Full expansion remains available without writing the seal.
    assert "cells" in json.loads(render_matrix_json(first))


def test_cells_are_sorted_unique_and_complete_for_views() -> None:
    matrix = DEFAULT_MATRIX
    ids = [cell.id for cell in matrix.cells]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    expected = {
        cell_id(
            view.domain_id,
            view.formal_view_id,
            view.family_id,
            view.profile_id,
            provider.provider_id,
        )
        for view in matrix.formal_views
        for provider in matrix.providers
    }
    assert set(ids) == expected

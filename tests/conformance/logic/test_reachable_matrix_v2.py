"""Conformance: reachable matrix and hard-zero floors (LFP2-047).

Interfaces: ``ReachableConformanceMatrix@2``, ``LogicConformanceReport@2``

Acceptance (fail-closed):

* Zero unexplained reachable gap
* Zero silent node drop/loss
* Zero raw ingress
* Zero family drift
* Zero false capability
* Zero authority escalation
* Zero kernel trust escape

Evidence subset: reachable matrix domain translation provider replay hard zero
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.conformance.matrix import AuthorityCeiling
from ipfs_datasets_py.logic.conformance.matrix_v2 import (
    CELL_SCHEMA,
    DEFAULT_LOGIC_CONFORMANCE_REPORT_V2,
    DEFAULT_REACHABLE_CONFORMANCE_MATRIX,
    DEFAULT_SEAL_RELATIVE_PATH,
    GOAL_ID,
    HARD_ZERO_FLOOR_NAMES,
    HARD_ZERO_FLOORS_SCHEMA,
    LOGIC_CONFORMANCE_REPORT_INTERFACE,
    LOGIC_CONFORMANCE_REPORT_SCHEMA,
    MATERIALIZATION_TARGET,
    MATRIX_VERSION,
    PROGRAM_ID,
    REACHABLE_CONFORMANCE_MATRIX_INTERFACE,
    REACHABLE_CONFORMANCE_MATRIX_SCHEMA,
    REQUIRED_EVIDENCE_SUBSET,
    REQUIRED_JOIN_DIMENSIONS,
    TASK_ID,
    CellDisposition,
    DomainSourceKind,
    ExecutionDisposition,
    HardZeroFloorError,
    HardZeroFloors,
    LogicConformanceReportV2,
    MatrixV2Error,
    ReachableConformanceCell,
    ReachableConformanceMatrix,
    ReplayDisposition,
    UnexplainedReachableGapError,
    assert_matrix_acceptance,
    build_default_reachable_conformance_matrix,
    build_logic_conformance_report_v2,
    build_reachable_conformance_matrix,
    cell_id,
    default_seal_path,
    ensure_seal_matches_live,
    evaluate_hard_zero_floors,
    load_reachable_matrix_seal,
    write_reachable_matrix_seal,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import SupportStatus

DATASETS_ROOT = Path(__file__).resolve().parents[3]
SEAL_PATH = DATASETS_ROOT / DEFAULT_SEAL_RELATIVE_PATH


# ---------------------------------------------------------------------------
# Interface / identity
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert REACHABLE_CONFORMANCE_MATRIX_INTERFACE == "ReachableConformanceMatrix@2"
    assert LOGIC_CONFORMANCE_REPORT_INTERFACE == "LogicConformanceReport@2"
    assert TASK_ID == "LFP2-047"
    assert GOAL_ID == "LFP2-G080"
    assert PROGRAM_ID == "ipfs-datasets-logic-family-parser-v2"
    matrix = DEFAULT_REACHABLE_CONFORMANCE_MATRIX
    assert matrix.interface == REACHABLE_CONFORMANCE_MATRIX_INTERFACE
    assert matrix.schema_version == REACHABLE_CONFORMANCE_MATRIX_SCHEMA
    assert matrix.version == MATRIX_VERSION
    report = DEFAULT_LOGIC_CONFORMANCE_REPORT_V2
    assert report.interface == LOGIC_CONFORMANCE_REPORT_INTERFACE
    assert report.schema_version == LOGIC_CONFORMANCE_REPORT_SCHEMA


def test_task_and_goal_binding() -> None:
    matrix = build_default_reachable_conformance_matrix()
    assert matrix.task_id == TASK_ID
    assert matrix.goal_id == GOAL_ID
    assert matrix.program_id == PROGRAM_ID
    report = build_logic_conformance_report_v2(matrix)
    assert report.task_id == TASK_ID
    assert report.goal_id == GOAL_ID


def test_required_evidence_subset_complete() -> None:
    matrix = build_default_reachable_conformance_matrix()
    for required in (
        "reachable",
        "matrix",
        "domain",
        "translation",
        "provider",
        "replay",
        "hard_zero",
    ):
        assert required in matrix.evidence_subset
        assert required in REQUIRED_EVIDENCE_SUBSET


# ---------------------------------------------------------------------------
# Sparse join
# ---------------------------------------------------------------------------


def test_cell_id_is_stable() -> None:
    assert cell_id(
        "legal_ir",
        "normative_defeasible",
        "ext:normative_to_legal_overlay",
        "datalog_secpal",
        "authorization_query",
    ) == (
        "legal_ir::normative_defeasible::ext:normative_to_legal_overlay::"
        "datalog_secpal::authorization_query"
    )


def test_every_cell_has_all_join_dimensions() -> None:
    matrix = build_default_reachable_conformance_matrix()
    assert matrix.cells
    for cell in matrix.cells:
        dims = cell.join_dimensions()
        for name in REQUIRED_JOIN_DIMENSIONS:
            assert name in dims, f"{cell.cell_id} missing {name}"
            assert dims[name], f"{cell.cell_id} empty {name}"
        assert cell.rationale.strip()
        assert cell.schema_version == CELL_SCHEMA


def test_matrix_is_sparse_and_joins_sources() -> None:
    matrix = build_default_reachable_conformance_matrix()
    assert matrix.summary["sparse"] is True
    assert matrix.summary["cell_count"] == len(matrix.cells)
    assert matrix.summary["domain_count"] >= 1
    assert matrix.summary["provider_count"] >= 1
    # Domain bindings must contribute cells.
    domain_sources = {
        (
            cell.domain_source_kind.value
            if isinstance(cell.domain_source_kind, DomainSourceKind)
            else str(cell.domain_source_kind)
        )
        for cell in matrix.cells
    }
    assert DomainSourceKind.DOMAIN_BINDING.value in domain_sources
    assert DomainSourceKind.REACHABLE_GRAPH.value in domain_sources
    assert DomainSourceKind.VERTICAL_SLICE.value in domain_sources
    # Joined source identities are recorded.
    assert "domain_family_bindings" in matrix.source_identities
    assert "reachable_capability_graph" in matrix.source_identities
    assert "family_extension_routes" in matrix.source_identities
    assert "logic_family_registry" in matrix.source_identities
    assert "logic_evidence_replay" in matrix.source_identities
    # Every required join dimension is non-empty on every cell.
    for cell in matrix.cells:
        dims = cell.join_dimensions()
        assert set(dims) >= set(REQUIRED_JOIN_DIMENSIONS)


def test_content_addressing_is_deterministic() -> None:
    first = build_default_reachable_conformance_matrix()
    second = build_default_reachable_conformance_matrix()
    assert first.content_sha256 == second.content_sha256
    assert first.content_id == second.content_id
    assert first.content_id == f"sha256:{first.content_sha256}"
    assert first.to_json() == second.to_json()
    report_a = build_logic_conformance_report_v2(first)
    report_b = build_logic_conformance_report_v2(second)
    assert report_a.content_id == report_b.content_id
    assert report_a.to_json() == report_b.to_json()


# ---------------------------------------------------------------------------
# Hard-zero floors
# ---------------------------------------------------------------------------


def test_hard_zero_floors_are_all_zero() -> None:
    matrix = build_default_reachable_conformance_matrix()
    floors = matrix.hard_zero_floors
    assert floors.schema_version == HARD_ZERO_FLOORS_SCHEMA
    assert floors.all_clear is True
    for name in HARD_ZERO_FLOOR_NAMES:
        assert getattr(floors, name) == 0, name
    floors.assert_clear()
    assert matrix.summary["hard_zero_floors_clear"] is True
    assert matrix.acceptance_holds() is True
    assert_matrix_acceptance(matrix)


def test_hard_zero_names_match_acceptance_surface() -> None:
    expected = {
        "unexplained_reachable_gap",
        "silent_node_drop",
        "silent_node_loss",
        "raw_ingress",
        "family_drift",
        "false_capability",
        "authority_escalation",
        "kernel_trust_escape",
    }
    assert set(HARD_ZERO_FLOOR_NAMES) == expected


def _base_cell(**overrides: Any) -> ReachableConformanceCell:
    payload: dict[str, Any] = {
        "cell_id": cell_id(
            "software_verification",
            "default",
            "smtlib_identity",
            "z3",
            "smt_assert",
        ),
        "domain_id": "software_verification",
        "domain_source_kind": DomainSourceKind.VERTICAL_SLICE,
        "domain_source_id": "slice:test",
        "family_id": "first_order",
        "profile_id": "default",
        "translation_path_id": "smtlib_identity",
        "provider_id": "z3",
        "provider_feature": "smt_assert",
        "execution": ExecutionDisposition.PINNED_BINARY,
        "replay": ReplayDisposition.REPLAYED,
        "disposition": CellDisposition.NATIVE,
        "authority_ceiling": AuthorityCeiling.EXACT.value,
        "support": SupportStatus.NATIVE.value,
        "rationale": "Test cell with complete join dimensions.",
        "raw_ingress": False,
        "node_map_complete": True,
        "family_canonical": True,
        "executable_claim": True,
        "kernel_claim": False,
        "independent_replay_or_reconstruction": True,
    }
    payload.update(overrides)
    if "cell_id" not in overrides:
        payload["cell_id"] = cell_id(
            str(payload["domain_id"]),
            str(payload["profile_id"]),
            str(payload["translation_path_id"]),
            str(payload["provider_id"]),
            str(payload["provider_feature"]),
        )
    return ReachableConformanceCell(**payload)


def test_unexplained_reachable_gap_is_hard_zero() -> None:
    # Construction already forbids empty rationale; evaluate path for drop.
    good = _base_cell()
    floors = evaluate_hard_zero_floors((good,))
    assert floors.unexplained_reachable_gap == 0
    with pytest.raises(MatrixV2Error, match="rationale"):
        _base_cell(rationale="")


def test_silent_node_drop_and_loss_are_hard_zero() -> None:
    cell = _base_cell(node_map_complete=False)
    floors = evaluate_hard_zero_floors((cell,))
    assert floors.silent_node_drop == 1
    assert floors.silent_node_loss == 1
    assert floors.all_clear is False
    with pytest.raises(HardZeroFloorError, match="silent_node"):
        floors.assert_clear()


def test_raw_ingress_is_hard_zero() -> None:
    cell = _base_cell(raw_ingress=True)
    floors = evaluate_hard_zero_floors((cell,))
    assert floors.raw_ingress == 1
    with pytest.raises(HardZeroFloorError, match="raw_ingress"):
        floors.assert_clear()


def test_family_drift_is_hard_zero() -> None:
    cell = _base_cell(
        family_id="TotallyFreeFormFamily",
        family_canonical=False,
        translation_path_id="free_form_path",
        provider_feature="free_form_feature",
    )
    floors = evaluate_hard_zero_floors((cell,))
    assert floors.family_drift == 1


def test_false_capability_is_hard_zero() -> None:
    cell = _base_cell(
        execution=ExecutionDisposition.HERMETIC_ONLY,
        executable_claim=True,
        support=SupportStatus.ADVISORY.value,
        independent_replay_or_reconstruction=False,
        authority_ceiling=AuthorityCeiling.ADVISORY.value,
        replay=ReplayDisposition.CEILING_RETAINED,
        disposition=CellDisposition.ADVISORY,
    )
    floors = evaluate_hard_zero_floors((cell,))
    assert floors.false_capability >= 1


def test_authority_escalation_is_hard_zero() -> None:
    cell = _base_cell(
        provider_id="symbolicai",
        provider_feature="advisor_suggest",
        execution=ExecutionDisposition.NOT_CLAIMED,
        executable_claim=False,
        authority_ceiling=AuthorityCeiling.KERNEL.value,
        independent_replay_or_reconstruction=False,
        replay=ReplayDisposition.CEILING_RETAINED,
        disposition=CellDisposition.ADVISORY,
        support=SupportStatus.ADVISORY.value,
    )
    floors = evaluate_hard_zero_floors((cell,))
    assert floors.authority_escalation >= 1


def test_kernel_trust_escape_is_hard_zero() -> None:
    cell = _base_cell(
        provider_id="z3",
        provider_feature="smt_assert",
        kernel_claim=True,
        authority_ceiling=AuthorityCeiling.KERNEL.value,
        independent_replay_or_reconstruction=False,
        execution=ExecutionDisposition.HERMETIC_ONLY,
        executable_claim=False,
        replay=ReplayDisposition.CEILING_RETAINED,
    )
    floors = evaluate_hard_zero_floors((cell,))
    assert floors.kernel_trust_escape >= 1


def test_default_matrix_rejects_hard_zero_violations_on_assert() -> None:
    matrix = build_default_reachable_conformance_matrix()
    # Mutate floors via a synthetic matrix with a bad cell population.
    bad_cell = _base_cell(raw_ingress=True)
    floors = evaluate_hard_zero_floors((bad_cell,))
    with pytest.raises(HardZeroFloorError):
        floors.assert_clear()
    with pytest.raises(MatrixV2Error):
        ReachableConformanceMatrix(
            cells=(bad_cell,),
            hard_zero_floors=HardZeroFloors(),  # lying clear floors
            summary={"acceptance_holds": True},
        )
    # Correct floors on a bad population still fail acceptance assert.
    bad_matrix = ReachableConformanceMatrix(
        cells=(bad_cell,),
        hard_zero_floors=floors,
        summary={
            "acceptance_holds": False,
            "hard_zero_floors_clear": False,
        },
    )
    with pytest.raises(HardZeroFloorError):
        assert_matrix_acceptance(bad_matrix)


# ---------------------------------------------------------------------------
# Report + seal
# ---------------------------------------------------------------------------


def test_logic_conformance_report_v2_joins_matrix() -> None:
    report = build_logic_conformance_report_v2()
    assert report.interface == "LogicConformanceReport@2"
    assert report.matrix.interface == "ReachableConformanceMatrix@2"
    assert report.hard_zero_floors.all_clear is True
    assert report.acceptance_holds() is True
    assert report.summary["matrix_content_id"] == report.matrix.content_id
    wire = json.loads(report.to_json())
    assert wire["interface"] == "LogicConformanceReport@2"
    assert wire["hard_zero_floors"]["all_clear"] is True
    assert wire["matrix"]["interface"] == "ReachableConformanceMatrix@2"


def test_seal_path_and_materialization_target() -> None:
    assert default_seal_path(DATASETS_ROOT) == SEAL_PATH
    assert "matrix_v2:build_default_reachable_conformance_matrix" in (
        MATERIALIZATION_TARGET
    )


def test_write_and_load_seal(tmp_path: Path) -> None:
    target = tmp_path / "reachable_matrix_v2.json"
    matrix = write_reachable_matrix_seal(target)
    assert target.is_file()
    seal = load_reachable_matrix_seal(target)
    assert seal["interface"] == REACHABLE_CONFORMANCE_MATRIX_INTERFACE
    assert seal["live_matrix_content_id"] == matrix.content_id
    assert seal["live_matrix_content_sha256"] == matrix.content_sha256
    assert seal["cell_count"] == len(matrix.cells)
    assert seal["hard_zero_floors"]["all_clear"] is True
    for name in HARD_ZERO_FLOOR_NAMES:
        assert seal["hard_zero_floors"][name] == 0
    assert seal["materialization"] == MATERIALIZATION_TARGET
    assert "conformance_report" in seal
    assert seal["conformance_report"]["interface"] == (
        LOGIC_CONFORMANCE_REPORT_INTERFACE
    )
    ensure_seal_matches_live(target, matrix=matrix)


def test_durable_seal_matches_live_when_present() -> None:
    """When the declared seal artifact exists, it must match live materialization."""

    assert SEAL_PATH.is_file(), f"missing declared seal: {SEAL_PATH}"
    matrix = ensure_seal_matches_live(SEAL_PATH)
    assert matrix.hard_zero_floors.all_clear is True
    seal = load_reachable_matrix_seal(SEAL_PATH)
    assert seal["task_id"] == TASK_ID
    assert seal["goal_id"] == GOAL_ID
    assert seal["acceptance"]["hard_zero_floors_clear"] is True
    for name in HARD_ZERO_FLOOR_NAMES:
        assert seal["hard_zero_floors"][name] == 0
        assert seal["acceptance"][name] == 0


def test_default_exports_accept() -> None:
    assert_matrix_acceptance(DEFAULT_REACHABLE_CONFORMANCE_MATRIX)
    assert DEFAULT_LOGIC_CONFORMANCE_REPORT_V2.acceptance_holds() is True
    assert isinstance(DEFAULT_LOGIC_CONFORMANCE_REPORT_V2, LogicConformanceReportV2)


def test_cell_round_trip_dict() -> None:
    cell = DEFAULT_REACHABLE_CONFORMANCE_MATRIX.cells[0]
    restored = ReachableConformanceCell.from_dict(cell.to_dict())
    assert restored.cell_id == cell.cell_id
    assert restored.to_dict() == cell.to_dict()


def test_missing_join_dimension_raises_on_acceptance() -> None:
    matrix = build_default_reachable_conformance_matrix()
    # Acceptance path for unexplained gap via empty rationale is construction-time.
    with pytest.raises((MatrixV2Error, UnexplainedReachableGapError)):
        ReachableConformanceCell(
            cell_id=cell_id("d", "p", "t", "prov", "feat"),
            domain_id="d",
            domain_source_kind=DomainSourceKind.REACHABLE_GRAPH,
            domain_source_id="r1",
            family_id="first_order",
            profile_id="p",
            translation_path_id="t",
            provider_id="prov",
            provider_feature="feat",
            execution=ExecutionDisposition.NOT_CLAIMED,
            replay=ReplayDisposition.NOT_REQUIRED,
            disposition=CellDisposition.EXCLUDED,
            authority_ceiling=AuthorityCeiling.NONE.value,
            rationale="",
        )
    assert_matrix_acceptance(matrix)


def test_build_without_graph_routes_still_has_domain_cells() -> None:
    matrix = build_reachable_conformance_matrix(include_graph_routes=False)
    assert matrix.cells
    kinds = {
        (
            cell.domain_source_kind.value
            if isinstance(cell.domain_source_kind, DomainSourceKind)
            else str(cell.domain_source_kind)
        )
        for cell in matrix.cells
    }
    assert DomainSourceKind.DOMAIN_BINDING.value in kinds
    assert DomainSourceKind.REACHABLE_GRAPH.value not in kinds
    # Execution/replay join cells remain even without the graph projection.
    assert DomainSourceKind.VERTICAL_SLICE.value in kinds
    floors = evaluate_hard_zero_floors(matrix.cells)
    assert floors.all_clear is True

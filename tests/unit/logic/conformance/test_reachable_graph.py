"""Unit tests for ReachableCapabilityGraph@1 (LFP2-003).

Acceptance:

* Every admitted route is explainable.
* Every unreachable cell is excluded with a typed reason.
* Full Cartesian unsupported cells do not become work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.conformance.matrix import (
    DEFAULT_MATRIX,
    AuthorityCeiling,
    AvailabilityStatus,
    CapabilityCell,
    SourceEvidence,
    SupportStatus,
    build_default_matrix,
    cell_id,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    ADMITTED_SUPPORT_STATUSES,
    DEFAULT_BASELINE_RELATIVE_PATH,
    DEFAULT_GRAPH,
    GOAL_ID,
    GRAPH_VERSION,
    LIFECYCLE_STAGES,
    MATERIALIZATION_TARGET,
    PROGRAM_ID,
    REACHABLE_CAPABILITY_GRAPH_INTERFACE,
    REACHABLE_CAPABILITY_GRAPH_SCHEMA,
    REQUIRED_EVIDENCE_DIMENSIONS,
    TASK_ID,
    AdmittedRoute,
    EvidenceKind,
    ExcludedCell,
    ExclusionReason,
    LifecycleStage,
    ReachableCapabilityGraph,
    ReachableCapabilityGraphError,
    RouteDisposition,
    RouteExplanation,
    TranslationPathKind,
    assert_graph_acceptance,
    build_default_graph,
    build_reachable_graph,
    default_baseline_path,
    default_datasets_repo_root,
    ensure_baseline_seal,
    explain_cell,
    load_graph_baseline,
    main as reachable_graph_main,
    project_cell,
    render_graph_json,
    render_graph_seal_json,
    route_id,
    to_graph_seal_dict,
    write_graph_baseline,
)

DATASETS_ROOT = Path(__file__).resolve().parents[4]
BASELINE_PATH = (
    DATASETS_ROOT
    / "docs"
    / "architecture"
    / "logic"
    / "logic_parser_v2_baseline"
    / "reachable_capability_graph.json"
)

_PLAN_EVIDENCE = (
    SourceEvidence(
        path="docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md"
    ),
)


def _native_cell(**overrides: object) -> CapabilityCell:
    payload: dict[str, object] = {
        "domain_id": "security_ir",
        "formal_view_id": "security-ir-view/claim/v1",
        "family_id": "first_order",
        "provider_id": "z3",
        "support": SupportStatus.NATIVE,
        "availability": AvailabilityStatus.NOT_PROBED,
        "authority_ceiling": AuthorityCeiling.EXACT,
        "profile_id": "verification_condition",
        "evidence": _PLAN_EVIDENCE,
        "notes": "Native SMT route.",
        "unimplemented": False,
    }
    payload.update(overrides)
    return CapabilityCell(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pure contract helpers
# ---------------------------------------------------------------------------


def test_route_id_matches_matrix_cell_id() -> None:
    assert route_id(
        "security_ir",
        "security-ir-view/claim/v1",
        "first_order",
        "verification_condition",
        "z3",
    ) == cell_id(
        "security_ir",
        "security-ir-view/claim/v1",
        "first_order",
        "verification_condition",
        "z3",
    )


def test_admitted_support_statuses_are_closed() -> None:
    assert SupportStatus.NATIVE in ADMITTED_SUPPORT_STATUSES
    assert SupportStatus.TRANSLATED in ADMITTED_SUPPORT_STATUSES
    assert SupportStatus.UNSUPPORTED not in ADMITTED_SUPPORT_STATUSES
    assert SupportStatus.UNKNOWN not in ADMITTED_SUPPORT_STATUSES
    assert SupportStatus.DECLARATION_ONLY not in ADMITTED_SUPPORT_STATUSES


def test_explain_cell_requires_admitted_support() -> None:
    unsupported = _native_cell(
        support=SupportStatus.UNSUPPORTED,
        authority_ceiling=AuthorityCeiling.NONE,
        availability=AvailabilityStatus.DECLARED,
        notes="No route.",
    )
    with pytest.raises(ReachableCapabilityGraphError, match="not admitted"):
        explain_cell(unsupported)


def test_explain_cell_joins_all_dimensions() -> None:
    cell = _native_cell()
    explanation = explain_cell(cell)
    assert explanation.domain_id == cell.domain_id
    assert explanation.formal_view_id == cell.formal_view_id
    assert explanation.family_id == cell.family_id
    assert explanation.profile_id == cell.profile_id
    assert explanation.provider_id == cell.provider_id
    assert explanation.translation_path_kind is TranslationPathKind.NATIVE
    assert explanation.translation_path_id.startswith("native:")
    assert explanation.evidence_kind is EvidenceKind.NATIVE_SOLVER
    assert explanation.lifecycle_stage is LifecycleStage.COMPILABLE
    assert explanation.authority_ceiling is AuthorityCeiling.EXACT
    assert explanation.rationale
    assert "first_order" in explanation.rationale
    assert "z3" in explanation.rationale


def test_project_unsupported_is_exclusion_not_work() -> None:
    cell = _native_cell(
        support=SupportStatus.UNSUPPORTED,
        authority_ceiling=AuthorityCeiling.NONE,
        availability=AvailabilityStatus.DECLARED,
        notes="No native or reviewed translated route from family X to provider Y.",
    )
    projected = project_cell(cell)
    assert isinstance(projected, ExcludedCell)
    assert projected.disposition is RouteDisposition.EXCLUDED
    assert projected.work_eligible is False
    assert projected.reason is ExclusionReason.NO_NATIVE_OR_TRANSLATED_ROUTE
    assert projected.detail


def test_project_native_is_admitted_explainable() -> None:
    cell = _native_cell()
    projected = project_cell(cell)
    assert isinstance(projected, AdmittedRoute)
    assert projected.disposition is RouteDisposition.ADMITTED
    assert projected.work_eligible is False  # implemented native
    assert projected.explanation.rationale
    assert projected.route_id == cell.id


def test_project_translated_is_work_eligible() -> None:
    cell = _native_cell(
        support=SupportStatus.TRANSLATED,
        authority_ceiling=AuthorityCeiling.BOUNDED,
        notes="Requires explicit translation edge.",
        unimplemented=True,
    )
    projected = project_cell(cell)
    assert isinstance(projected, AdmittedRoute)
    assert projected.work_eligible is True
    assert projected.explanation.translation_path_kind is TranslationPathKind.TRANSLATED
    assert projected.explanation.lifecycle_stage is LifecycleStage.TRANSLATABLE
    assert projected.explanation.evidence_kind is EvidenceKind.TRANSLATION_RECEIPT


def test_excluded_cell_rejects_unsupported_work() -> None:
    with pytest.raises(ReachableCapabilityGraphError, match="cannot be work-eligible"):
        ExcludedCell(
            cell_id=route_id(
                "security_ir",
                "security-ir-view/claim/v1",
                "first_order",
                "default",
                "tamarin",
            ),
            domain_id="security_ir",
            formal_view_id="security-ir-view/claim/v1",
            family_id="first_order",
            profile_id="default",
            provider_id="tamarin",
            support=SupportStatus.UNSUPPORTED,
            reason=ExclusionReason.PROVIDER_FAMILY_INCOMPATIBLE,
            detail="incompatible",
            work_eligible=True,
        )


def test_admitted_route_rejects_non_admitted_support() -> None:
    with pytest.raises(ReachableCapabilityGraphError, match="non-admitted support"):
        AdmittedRoute(
            route_id=route_id(
                "security_ir",
                "security-ir-view/claim/v1",
                "first_order",
                "default",
                "z3",
            ),
            domain_id="security_ir",
            formal_view_id="security-ir-view/claim/v1",
            family_id="first_order",
            profile_id="default",
            provider_id="z3",
            support=SupportStatus.UNSUPPORTED,
            availability=AvailabilityStatus.DECLARED,
            authority_ceiling=AuthorityCeiling.NONE,
            explanation=RouteExplanation(
                domain_id="security_ir",
                formal_view_id="security-ir-view/claim/v1",
                family_id="first_order",
                profile_id="default",
                translation_path_kind=TranslationPathKind.NATIVE,
                translation_path_id="native:first_order->z3",
                provider_id="z3",
                provider_feature="z3:native",
                evidence_kind=EvidenceKind.NATIVE_SOLVER,
                lifecycle_stage=LifecycleStage.COMPILABLE,
                authority_ceiling=AuthorityCeiling.NONE,
                support=SupportStatus.NATIVE,
                rationale="should fail before explanation support check on route",
            ),
            work_eligible=False,
        )


# ---------------------------------------------------------------------------
# Default graph materialization
# ---------------------------------------------------------------------------


def test_default_graph_is_sparse_partition_of_matrix() -> None:
    graph = build_default_graph()
    matrix = build_default_matrix()
    total = graph.admitted_count + graph.excluded_count
    assert total == len(matrix.cells)
    assert graph.cartesian_cell_count == len(matrix.cells)
    assert graph.admitted_count < len(matrix.cells)
    assert graph.admitted_count > 0
    assert graph.excluded_count > 0
    assert graph.interface == REACHABLE_CAPABILITY_GRAPH_INTERFACE
    assert graph.schema_version == REACHABLE_CAPABILITY_GRAPH_SCHEMA
    assert graph.version == GRAPH_VERSION


def test_every_admitted_route_is_explainable() -> None:
    graph = DEFAULT_GRAPH
    assert graph.routes
    for route in graph.routes:
        assert route.disposition is RouteDisposition.ADMITTED
        assert route.support in ADMITTED_SUPPORT_STATUSES
        explanation = route.explanation
        assert explanation.rationale.strip()
        assert explanation.domain_id == route.domain_id
        assert explanation.formal_view_id == route.formal_view_id
        assert explanation.family_id == route.family_id
        assert explanation.profile_id == route.profile_id
        assert explanation.provider_id == route.provider_id
        assert explanation.translation_path_id
        assert explanation.provider_feature
        assert explanation.evidence_kind in EvidenceKind
        assert explanation.lifecycle_stage in LifecycleStage
        assert explanation.authority_ceiling in AuthorityCeiling
        # Join dimensions required by LFP2-003.
        assert explanation.domain_id
        assert explanation.formal_view_id
        assert explanation.family_id
        assert explanation.profile_id
        assert explanation.translation_path_kind in TranslationPathKind
        assert explanation.provider_id


def test_every_unreachable_cell_has_typed_exclusion_reason() -> None:
    graph = DEFAULT_GRAPH
    assert graph.exclusions
    reasons = set()
    for exclusion in graph.exclusions:
        assert exclusion.disposition is RouteDisposition.EXCLUDED
        assert exclusion.support not in ADMITTED_SUPPORT_STATUSES
        assert isinstance(exclusion.reason, ExclusionReason)
        assert exclusion.detail.strip()
        reasons.add(exclusion.reason)
    # At least the dominant Cartesian unsupported path is present.
    assert ExclusionReason.NO_NATIVE_OR_TRANSLATED_ROUTE in reasons or (
        ExclusionReason.PROVIDER_FAMILY_INCOMPATIBLE in reasons
    )


def test_unsupported_cartesian_cells_are_not_work() -> None:
    graph = DEFAULT_GRAPH
    unsupported = graph.unsupported_exclusions()
    assert unsupported, "expected unsupported Cartesian exclusions"
    for exclusion in unsupported:
        assert exclusion.work_eligible is False
        assert exclusion.support is SupportStatus.UNSUPPORTED

    work_ids = {item.route_id for item in graph.work_items()}
    unsupported_ids = {item.cell_id for item in unsupported}
    assert work_ids.isdisjoint(unsupported_ids)

    summary = graph.summary()
    assert summary["unsupported_work_eligible_count"] == 0
    assert summary["work_eligible_count"] == len(graph.work_items())
    for route_id_value in summary["work_eligible_route_ids"]:
        assert graph.get_route(route_id_value) is not None
        assert graph.get_exclusion(route_id_value) is None


def test_work_items_are_subset_of_admitted_routes() -> None:
    graph = DEFAULT_GRAPH
    work = graph.work_items()
    admitted_ids = {item.route_id for item in graph.routes}
    for item in work:
        assert item.route_id in admitted_ids
        assert item.work_eligible is True
        assert item.support in ADMITTED_SUPPORT_STATUSES
        # Work is incomplete admitted routes (translated / unimplemented).
        assert item.unimplemented or item.support is SupportStatus.TRANSLATED


def test_no_coordinate_is_both_admitted_and_excluded() -> None:
    graph = DEFAULT_GRAPH
    route_ids = {item.route_id for item in graph.routes}
    exclusion_ids = {item.cell_id for item in graph.exclusions}
    assert not (route_ids & exclusion_ids)


def test_matrix_cells_are_fully_classified() -> None:
    graph = DEFAULT_GRAPH
    matrix = DEFAULT_MATRIX
    classified = {item.route_id for item in graph.routes} | {
        item.cell_id for item in graph.exclusions
    }
    matrix_ids = {cell.id for cell in matrix.cells}
    assert classified == matrix_ids


def test_ui_ux_cells_are_typed_exclusions_not_work() -> None:
    graph = DEFAULT_GRAPH
    ui_routes = graph.routes_for_domain("ui_ux_ir")
    assert ui_routes == ()
    ui_exclusions = [
        item for item in graph.exclusions if item.domain_id == "ui_ux_ir"
    ]
    assert ui_exclusions
    for item in ui_exclusions:
        assert item.work_eligible is False
        assert item.reason in {
            ExclusionReason.DECLARATION_ONLY_DOMAIN,
            ExclusionReason.SOURCE_MISSING,
            ExclusionReason.DECLARATION_ONLY_FAMILY,
        }
        assert item.support is SupportStatus.DECLARATION_ONLY


def test_known_native_z3_security_route_is_admitted() -> None:
    target = route_id(
        "security_ir",
        "security-ir-view/claim/v1",
        "first_order",
        "verification_condition",
        "z3",
    )
    route = DEFAULT_GRAPH.get_route(target)
    assert route is not None
    assert route.support is SupportStatus.NATIVE
    assert route.authority_ceiling is AuthorityCeiling.EXACT
    assert route.explanation.translation_path_kind is TranslationPathKind.NATIVE
    assert route.explanation.evidence_kind is EvidenceKind.NATIVE_SOLVER
    assert DEFAULT_GRAPH.get_exclusion(target) is None


def test_assert_graph_acceptance_passes_default() -> None:
    assert_graph_acceptance(DEFAULT_GRAPH)
    assert_graph_acceptance(build_default_graph())


def test_materialization_is_deterministic_and_side_effect_free(
    tmp_path: Path,
) -> None:
    before = {path for path in tmp_path.rglob("*") if path.is_file()}
    first = build_default_graph()
    second = build_reachable_graph(build_default_matrix())
    after = {path for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after
    assert first.to_dict() == second.to_dict()
    assert first.content_digest() == second.content_digest()
    assert first.summary() == second.summary()


def test_round_trip_dict_and_json(tmp_path: Path) -> None:
    graph = build_default_graph()
    restored = ReachableCapabilityGraph.from_dict(graph.to_dict())
    assert restored.to_dict() == graph.to_dict()
    assert restored.content_digest() == graph.content_digest()

    full_path = tmp_path / "reachable_capability_graph.full.json"
    write_graph_baseline(graph, full_path, full_routes=True)
    loaded_full = load_graph_baseline(full_path)
    assert loaded_full.to_dict() == graph.to_dict()
    full_payload = json.loads(full_path.read_text(encoding="utf-8"))
    assert full_payload["interface"] == REACHABLE_CAPABILITY_GRAPH_INTERFACE
    assert full_payload["schema_version"] == REACHABLE_CAPABILITY_GRAPH_SCHEMA
    assert full_payload["materialization"] == MATERIALIZATION_TARGET
    assert full_payload["task_id"] == TASK_ID
    assert full_payload["goal_id"] == GOAL_ID
    assert full_payload["program_id"] == PROGRAM_ID
    assert full_payload["required_evidence_dimensions"] == list(
        REQUIRED_EVIDENCE_DIMENSIONS
    )
    assert full_payload["lifecycle_stages"] == list(LIFECYCLE_STAGES)
    assert "content_digest" in full_payload
    assert full_path.read_text(encoding="utf-8") == render_graph_json(graph)

    seal_path = tmp_path / "reachable_capability_graph.seal.json"
    write_graph_baseline(graph, seal_path, full_routes=False)
    loaded_seal = load_graph_baseline(seal_path)
    assert loaded_seal.to_dict() == graph.to_dict()
    seal_payload = json.loads(seal_path.read_text(encoding="utf-8"))
    assert seal_payload["materialization"] == MATERIALIZATION_TARGET
    assert "routes" not in seal_payload
    assert seal_payload == to_graph_seal_dict(graph)
    assert seal_path.read_text(encoding="utf-8") == render_graph_seal_json(graph)
    assert seal_payload["unsupported_work_eligible_count"] == 0
    assert seal_payload["acceptance"]["unsupported_cartesian_cells_are_not_work"]


def test_sealed_baseline_matches_default_graph() -> None:
    expected = build_default_graph()
    assert_graph_acceptance(expected)
    assert BASELINE_PATH.is_file(), f"missing baseline report: {BASELINE_PATH}"

    sealed = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert sealed["interface"] == REACHABLE_CAPABILITY_GRAPH_INTERFACE
    assert sealed["schema_version"] == REACHABLE_CAPABILITY_GRAPH_SCHEMA
    assert sealed["materialization"] == MATERIALIZATION_TARGET
    assert sealed["task_id"] == TASK_ID
    assert sealed["goal_id"] == GOAL_ID
    assert sealed["program_id"] == PROGRAM_ID
    assert sealed["version"] == GRAPH_VERSION
    assert set(sealed["required_evidence_dimensions"]) == set(
        REQUIRED_EVIDENCE_DIMENSIONS
    )
    assert set(sealed["admitted_support_statuses"]) == {
        status.value for status in ADMITTED_SUPPORT_STATUSES
    }
    assert sealed["lifecycle_stages"] == list(LIFECYCLE_STAGES)
    assert sealed["acceptance"]["admitted_routes_explainable"] is True
    assert sealed["acceptance"]["unreachable_cells_typed_exclusion"] is True
    assert sealed["acceptance"]["unsupported_cartesian_cells_are_not_work"] is True
    assert "routes" not in sealed

    # Compact seal re-materializes the live sparse graph.
    on_disk = load_graph_baseline(BASELINE_PATH)
    assert [item.to_dict() for item in on_disk.routes] == [
        item.to_dict() for item in expected.routes
    ]
    assert [item.to_dict() for item in on_disk.exclusions] == [
        item.to_dict() for item in expected.exclusions
    ]
    assert on_disk.summary() == expected.summary()
    assert on_disk.summary()["unsupported_work_eligible_count"] == 0
    assert default_baseline_path(datasets_root=DATASETS_ROOT) == BASELINE_PATH
    assert default_baseline_path().as_posix().endswith(DEFAULT_BASELINE_RELATIVE_PATH)

    live = ensure_baseline_seal(BASELINE_PATH, datasets_root=DATASETS_ROOT)
    assert live.summary() == expected.summary()

    # Full quantitative seal still round-trips against live materialization.
    full_seal = to_graph_seal_dict(expected)
    assert full_seal["unsupported_work_eligible_count"] == 0
    assert full_seal["admitted_count"] == expected.admitted_count
    assert full_seal["excluded_count"] == expected.excluded_count
    assert full_seal["content_digest"] == expected.content_digest()
    assert render_graph_seal_json(expected) == (
        json.dumps(full_seal, ensure_ascii=True, indent=2, sort_keys=False, allow_nan=False)
        + "\n"
    )

def test_default_datasets_root_resolves() -> None:
    root = default_datasets_repo_root()
    assert (root / "ipfs_datasets_py" / "logic").is_dir()
    baseline = default_baseline_path(datasets_root=root)
    assert baseline.as_posix().endswith(DEFAULT_BASELINE_RELATIVE_PATH)


def test_cli_writes_baseline(tmp_path: Path) -> None:
    target = tmp_path / "reachable_capability_graph.json"
    rc = reachable_graph_main(["--output", str(target)])
    assert rc == 0
    assert target.is_file()
    loaded = load_graph_baseline(target)
    assert_graph_acceptance(loaded)
    assert loaded.admitted_count == DEFAULT_GRAPH.admitted_count
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert "routes" not in payload
    assert payload["materialization"] == MATERIALIZATION_TARGET


def test_summary_sparsity_and_histograms() -> None:
    summary = DEFAULT_GRAPH.summary()
    assert summary["admitted_count"] == DEFAULT_GRAPH.admitted_count
    assert summary["excluded_count"] == DEFAULT_GRAPH.excluded_count
    assert 0.0 < summary["sparsity_ratio"] < 1.0
    assert sum(summary["exclusion_reason_histogram"].values()) == (
        DEFAULT_GRAPH.excluded_count
    )
    assert sum(summary["route_support_histogram"].values()) == (
        DEFAULT_GRAPH.admitted_count
    )
    # Only admitted supports appear on routes.
    for status, count in summary["route_support_histogram"].items():
        if count:
            assert SupportStatus(status) in ADMITTED_SUPPORT_STATUSES


def test_ensure_baseline_seal_detects_drift(tmp_path: Path) -> None:
    target = tmp_path / "reachable_capability_graph.json"
    write_graph_baseline(DEFAULT_GRAPH, target, full_routes=False)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["admitted_count"] = int(payload["admitted_count"]) + 999
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ReachableCapabilityGraphError, match="disagrees"):
        ensure_baseline_seal(target, datasets_root=DATASETS_ROOT)

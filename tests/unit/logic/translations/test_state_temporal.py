"""Unit tests for StateTemporalTranslationEdges@1."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import (
    PreservationRelation,
    TranslationAssumptionSet,
)
from ipfs_datasets_py.logic.translations.planner import (
    TranslationPathPlanner,
    TranslationPathPlannerError,
    TranslationPathRequest,
)
from ipfs_datasets_py.logic.translations.state_temporal import (
    STATE_TEMPORAL_EDGES_INTERFACE,
    STATE_TEMPORAL_EDGES_SCHEMA_VERSION,
    ClockKind,
    FairnessKind,
    RefinementDirection,
    RouteKind,
    StateTemporalEdge,
    StateTemporalSemanticReceipt,
    StateTemporalTranslationEdges,
    StateTemporalTranslationError,
    TraceKind,
    build_state_temporal_edges,
    require_semantic_receipts,
    state_temporal_contracts,
)


# ---------------------------------------------------------------------------
# Catalog surface
# ---------------------------------------------------------------------------


def test_reviewed_catalog_interface_and_identity() -> None:
    catalog = build_state_temporal_edges()
    assert catalog.interface == STATE_TEMPORAL_EDGES_INTERFACE
    assert catalog.schema_version == STATE_TEMPORAL_EDGES_SCHEMA_VERSION
    assert catalog.interface == "StateTemporalTranslationEdges@1"
    assert catalog.catalog_content_id.startswith("bafkrei")
    assert catalog.content_id == catalog.catalog_content_id
    assert len(catalog) >= 8
    assert catalog.edge_ids() == tuple(sorted(catalog.edge_ids()))


def test_catalog_covers_transition_concurrency_refinement_temporal() -> None:
    catalog = build_state_temporal_edges()
    kinds = {edge.receipt.route_kind for edge in catalog}
    assert kinds == {
        RouteKind.TRANSITION,
        RouteKind.CONCURRENCY,
        RouteKind.REFINEMENT,
        RouteKind.TEMPORAL,
    }
    assert catalog.by_route_kind(RouteKind.TRANSITION)
    assert catalog.by_route_kind(RouteKind.CONCURRENCY)
    assert catalog.by_route_kind(RouteKind.REFINEMENT)
    assert catalog.by_route_kind(RouteKind.TEMPORAL)


def test_catalog_maps_to_tla_smt_runtime_mtl_and_hyperltl() -> None:
    catalog = build_state_temporal_edges()
    edge_ids = set(catalog.edge_ids())
    assert "transition_system_to_tla_plus" in edge_ids
    assert "concurrency_to_tla_plus" in edge_ids
    assert "temporal_ltl_to_tla_plus" in edge_ids
    assert "transition_system_to_bounded_smt" in edge_ids
    assert "concurrency_to_bounded_smt" in edge_ids
    assert "temporal_to_bounded_smt" in edge_ids
    assert "refinement_forward_to_bounded_smt" in edge_ids
    assert "temporal_mtl_to_runtime_mtl" in edge_ids
    assert "temporal_to_hyperltl" in edge_ids

    tla = catalog.by_target_family("transition_system", profile_id="tla_plus")
    assert {edge.edge_id for edge in tla} >= {
        "transition_system_to_tla_plus",
        "concurrency_to_tla_plus",
        "temporal_ltl_to_tla_plus",
    }

    smt = catalog.by_target_family("first_order")
    assert any("smt" in edge.edge_id for edge in smt)

    mtl = catalog.get("temporal_mtl_to_runtime_mtl")
    assert mtl.contract.target.profile_id == "runtime_mtl"

    hyper = catalog.get("temporal_to_hyperltl")
    assert hyper.contract.target.family_id == "hyperproperty"
    assert hyper.contract.target.profile_id == "hyperltl"


def test_catalog_round_trip() -> None:
    catalog = build_state_temporal_edges()
    restored = StateTemporalTranslationEdges.from_dict(catalog.to_dict())
    assert restored == catalog
    assert restored.to_dict() == catalog.to_dict()


def test_catalog_is_immutable() -> None:
    catalog = build_state_temporal_edges()
    with pytest.raises(FrozenInstanceError):
        catalog.description = "mutated"  # type: ignore[misc]


def test_catalog_identity_is_deterministic() -> None:
    a = build_state_temporal_edges()
    b = StateTemporalTranslationEdges.reviewed()
    assert a.catalog_content_id == b.catalog_content_id
    assert a.edge_ids() == b.edge_ids()
    assert [e.edge_content_id for e in a] == [e.edge_content_id for e in b]


def test_state_temporal_contracts_matches_catalog() -> None:
    catalog = build_state_temporal_edges()
    contracts = state_temporal_contracts()
    assert len(contracts) == len(catalog)
    assert {c.contract_id for c in contracts} == set(catalog.edge_ids())


# ---------------------------------------------------------------------------
# Mandatory receipts: cannot be omitted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    [
        "trace_kind",
        "fairness",
        "refinement_direction",
        "clock",
        "bounds",
        "route_kind",
    ],
)
def test_semantic_receipt_rejects_omitted_fields(field_name: str) -> None:
    payload: dict[str, object] = {
        "trace_kind": TraceKind.FINITE.value,
        "fairness": FairnessKind.NONE.value,
        "refinement_direction": RefinementDirection.NOT_APPLICABLE.value,
        "clock": ClockKind.LOGICAL.value,
        "bounds": ["bound:bmc_depth_8"],
        "route_kind": RouteKind.TEMPORAL.value,
    }
    payload[field_name] = None
    with pytest.raises(StateTemporalTranslationError, match="cannot be omitted"):
        StateTemporalSemanticReceipt.from_dict(payload)


@pytest.mark.parametrize(
    "field_name",
    [
        "trace_kind",
        "fairness",
        "refinement_direction",
        "clock",
        "bounds",
        "route_kind",
    ],
)
def test_semantic_receipt_rejects_missing_keys(field_name: str) -> None:
    payload: dict[str, object] = {
        "trace_kind": TraceKind.INFINITE.value,
        "fairness": FairnessKind.WEAK.value,
        "refinement_direction": RefinementDirection.NOT_APPLICABLE.value,
        "clock": ClockKind.DISCRETE.value,
        "bounds": ["bound:unbounded"],
        "route_kind": RouteKind.TRANSITION.value,
    }
    del payload[field_name]
    with pytest.raises(StateTemporalTranslationError, match="cannot be omitted"):
        StateTemporalSemanticReceipt.from_dict(payload)


def test_semantic_receipt_rejects_empty_bounds() -> None:
    with pytest.raises(StateTemporalTranslationError, match="cannot be omitted"):
        StateTemporalSemanticReceipt(
            trace_kind=TraceKind.FINITE,
            fairness=FairnessKind.NONE,
            refinement_direction=RefinementDirection.NOT_APPLICABLE,
            clock=ClockKind.LOGICAL,
            bounds=(),
            route_kind=RouteKind.TEMPORAL,
        )


def test_require_semantic_receipts_helper() -> None:
    receipt = require_semantic_receipts(
        trace_kind="finite",
        fairness="none",
        refinement_direction="not_applicable",
        clock="discrete",
        bounds=("bound:bmc_depth_4",),
        route_kind="temporal",
    )
    assert receipt.trace_kind is TraceKind.FINITE
    assert receipt.fairness is FairnessKind.NONE
    assert receipt.clock is ClockKind.DISCRETE
    assert receipt.bounds == ("bound:bmc_depth_4",)


def test_every_catalog_edge_declares_all_mandatory_receipts() -> None:
    catalog = build_state_temporal_edges()
    for edge in catalog:
        receipt = edge.receipt
        assert isinstance(receipt.trace_kind, TraceKind)
        assert isinstance(receipt.fairness, FairnessKind)
        assert isinstance(receipt.refinement_direction, RefinementDirection)
        assert isinstance(receipt.clock, ClockKind)
        assert receipt.bounds  # non-empty
        # Projected into contract assumptions (fairness/trace/bound receipts).
        assumptions = edge.contract.assumptions
        assert any(item.startswith("fairness:") for item in assumptions.fairness)
        assert any(item.startswith("trace:") for item in assumptions.domain_changes)
        assert any(
            item.startswith("refinement_direction:")
            for item in assumptions.domain_changes
        )
        assert any(item.startswith("clock:") for item in assumptions.domain_changes)
        assert assumptions.bounds
        assert set(receipt.bounds).issubset(set(assumptions.bounds))


def test_finite_and_infinite_trace_kinds_both_present() -> None:
    catalog = build_state_temporal_edges()
    kinds = {edge.receipt.trace_kind for edge in catalog}
    assert TraceKind.FINITE in kinds
    assert TraceKind.INFINITE in kinds
    assert TraceKind.FINITE_PREFIX in kinds


def test_refinement_edges_require_explicit_direction() -> None:
    catalog = build_state_temporal_edges()
    refinement = catalog.by_route_kind(RouteKind.REFINEMENT)
    assert refinement
    for edge in refinement:
        assert edge.receipt.refinement_direction is not RefinementDirection.NOT_APPLICABLE
        token = (
            f"refinement_direction:{edge.receipt.refinement_direction.value}"
        )
        assert token in edge.contract.assumptions.domain_changes


def test_refinement_route_rejects_not_applicable_direction() -> None:
    with pytest.raises(
        StateTemporalTranslationError, match="refinement routes require"
    ):
        StateTemporalSemanticReceipt(
            trace_kind=TraceKind.INFINITE,
            fairness=FairnessKind.WEAK,
            refinement_direction=RefinementDirection.NOT_APPLICABLE,
            clock=ClockKind.DISCRETE,
            bounds=("bound:unbounded",),
            route_kind=RouteKind.REFINEMENT,
        )


def test_bounded_edges_require_concrete_bounds() -> None:
    catalog = build_state_temporal_edges()
    bounded = [
        edge
        for edge in catalog
        if edge.contract.preservation is PreservationRelation.BOUNDED
    ]
    assert bounded
    for edge in bounded:
        assert edge.contract.authority_ceiling is EvidenceAuthority.BOUNDED
        concrete = [b for b in edge.receipt.bounds if b != "bound:unbounded"]
        assert concrete, edge.edge_id
        assert edge.contract.assumptions.bounds


def test_runtime_mtl_edge_declares_clock_and_finite_prefix() -> None:
    edge = build_state_temporal_edges().get("temporal_mtl_to_runtime_mtl")
    assert edge.receipt.trace_kind is TraceKind.FINITE_PREFIX
    assert edge.receipt.clock is ClockKind.DENSE
    assert any(b.startswith("bound:clock") for b in edge.receipt.bounds)
    assert edge.contract.preservation is PreservationRelation.BOUNDED
    assert edge.contract.proof_safe is False
    assert edge.contract.counterexample_safe is True


def test_tla_edges_declare_fairness_and_infinite_trace() -> None:
    catalog = build_state_temporal_edges()
    for edge_id in (
        "transition_system_to_tla_plus",
        "concurrency_to_tla_plus",
        "temporal_ltl_to_tla_plus",
    ):
        edge = catalog.get(edge_id)
        assert edge.receipt.trace_kind is TraceKind.INFINITE
        assert edge.receipt.fairness is FairnessKind.WEAK
        assert "fairness:weak" in edge.contract.assumptions.fairness


# ---------------------------------------------------------------------------
# Edge integrity / fail-closed construction
# ---------------------------------------------------------------------------


def test_edge_rejects_mismatched_edge_and_contract_ids() -> None:
    catalog = build_state_temporal_edges()
    base = catalog.get("temporal_to_bounded_smt")
    with pytest.raises(StateTemporalTranslationError, match="edge_id"):
        StateTemporalEdge(
            edge_id="not_the_contract_id",
            contract=base.contract,
            receipt=base.receipt,
        )


def test_edge_rejects_contract_missing_receipt_assumptions() -> None:
    catalog = build_state_temporal_edges()
    base = catalog.get("temporal_to_bounded_smt")
    # Rebuild contract without projected assumptions.
    stripped = base.contract.to_dict()
    stripped["assumptions"] = TranslationAssumptionSet(
        bounds=("bound:bmc_depth_64",)
    ).to_dict()
    stripped["contract_content_id"] = ""
    with pytest.raises(
        StateTemporalTranslationError, match="omit mandatory semantic receipts"
    ):
        StateTemporalEdge(
            edge_id=base.edge_id,
            contract=stripped,  # type: ignore[arg-type]
            receipt=base.receipt,
        )


def test_edge_round_trip() -> None:
    edge = build_state_temporal_edges().get("concurrency_to_tla_plus")
    restored = StateTemporalEdge.from_dict(edge.to_dict())
    assert restored == edge
    assert restored.edge_content_id == edge.edge_content_id


def test_mismatched_catalog_content_id_rejected() -> None:
    catalog = build_state_temporal_edges()
    payload = catalog.to_dict()
    payload["catalog_content_id"] = "bafkreinot-the-real-catalog-content-id-xxxxx"
    with pytest.raises(StateTemporalTranslationError, match="catalog_content_id"):
        StateTemporalTranslationEdges.from_dict(payload)


def test_unknown_edge_id_raises() -> None:
    catalog = build_state_temporal_edges()
    with pytest.raises(StateTemporalTranslationError, match="unknown edge_id"):
        catalog.get("does_not_exist")


# ---------------------------------------------------------------------------
# Planner integration
# ---------------------------------------------------------------------------


def test_register_with_planner_selects_transition_to_tla() -> None:
    catalog = build_state_temporal_edges()
    planner = catalog.register_with_planner()
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="transition_system",
            target_family_id="transition_system",
            source_profile_id="transition_system_default",
            target_profile_id="tla_plus",
            features=(
                "feat_transition_init",
                "feat_transition_next",
                "feat_state_invariant",
                "feat_fairness",
            ),
        )
    )
    assert "transition_system_to_tla_plus" in receipt.edge_contract_ids
    assert receipt.preservation is PreservationRelation.TRACE_PRESERVING
    assert any(item.startswith("fairness:") for item in receipt.assumptions.fairness)
    assert any(item.startswith("trace:") for item in receipt.assumptions.domain_changes)


def test_planner_selects_temporal_to_runtime_mtl() -> None:
    catalog = build_state_temporal_edges()
    planner = catalog.register_with_planner()
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="temporal",
            target_family_id="temporal",
            source_profile_id="mtl_finite",
            target_profile_id="runtime_mtl",
            features=(
                "feat_temporal_always",
                "feat_temporal_eventually",
                "feat_metric_interval",
                "feat_finite_trace",
                "feat_clock",
            ),
            claimed_preservation=PreservationRelation.BOUNDED,
            claimed_authority=EvidenceAuthority.BOUNDED,
        )
    )
    assert receipt.edge_contract_ids == ("temporal_mtl_to_runtime_mtl",)
    assert receipt.authority_ceiling is EvidenceAuthority.BOUNDED
    assert any("bound:clock" in b for b in receipt.assumptions.bounds)


def test_planner_selects_refinement_forward_route() -> None:
    catalog = build_state_temporal_edges()
    planner = catalog.register_with_planner()
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="refinement",
            target_family_id="transition_system",
            features=(
                "feat_refinement_forward",
                "feat_simulation_relation",
                "feat_abstract_system",
                "feat_concrete_system",
            ),
        )
    )
    assert receipt.edge_contract_ids == (
        "refinement_forward_to_transition_system",
    )
    assert any(
        "refinement_direction:forward" in item
        for item in receipt.assumptions.domain_changes
    )


def test_planner_rejects_unsupported_hyper_alternation() -> None:
    catalog = build_state_temporal_edges()
    planner = catalog.register_with_planner()
    with pytest.raises(
        TranslationPathPlannerError,
        match="unsupported features fail before compilation|unsupported",
    ):
        planner.plan(
            TranslationPathRequest(
                source_family_id="temporal",
                target_family_id="hyperproperty",
                features=(
                    "feat_temporal_always",
                    "feat_temporal_eventually",
                    "feat_infinite_trace",
                    "feat_hyper_alternation",
                ),
            )
        )


def test_planner_rejects_authority_laundering_on_bounded_smt() -> None:
    catalog = build_state_temporal_edges()
    planner = catalog.register_with_planner()
    with pytest.raises(
        TranslationPathPlannerError,
        match="authority laundering|laundering fails before compilation",
    ):
        planner.plan(
            TranslationPathRequest(
                source_family_id="transition_system",
                target_family_id="first_order",
                features=(
                    "feat_transition_init",
                    "feat_transition_next",
                    "feat_state_invariant",
                    "feat_finite_domain",
                ),
                claimed_authority=EvidenceAuthority.AUTHORITATIVE,
            )
        )


def test_concurrency_to_bounded_smt_is_feature_total() -> None:
    catalog = build_state_temporal_edges()
    planner = catalog.register_with_planner(TranslationPathPlanner())
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="concurrency",
            target_family_id="first_order",
            features=(
                "feat_component_step",
                "feat_environment_step",
                "feat_interference",
                "feat_bounded_schedule",
            ),
            claimed_preservation=PreservationRelation.BOUNDED,
        )
    )
    assert receipt.edge_contract_ids == ("concurrency_to_bounded_smt",)
    assert "bound:schedule_length_16" in receipt.assumptions.bounds
    assert receipt.counterexample_safe is True


def test_hyperltl_route_exposes_quantifier_bounds() -> None:
    edge = build_state_temporal_edges().get("temporal_to_hyperltl")
    assert "bound:trace_quantifiers_1" in edge.receipt.bounds
    assert "bound:system_copies_1" in edge.receipt.bounds
    planner = build_state_temporal_edges().register_with_planner()
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="temporal",
            target_family_id="hyperproperty",
            features=(
                "feat_temporal_always",
                "feat_temporal_eventually",
                "feat_infinite_trace",
            ),
        )
    )
    assert receipt.edge_contract_ids == ("temporal_to_hyperltl",)
    assert "bound:trace_quantifiers_1" in receipt.assumptions.bounds

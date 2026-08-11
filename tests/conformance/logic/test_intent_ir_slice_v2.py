"""Conformance: Intent IR base goals, guards, workflows, and policy slices (LFP2-024).

Acceptance:

* Safety/liveness remain properties and VC remains a view role
* Advisor confidence cannot establish intent correctness
* Goals, guards, skill effects, workflows, policy/modal views, authorization,
  and tool invocation constraints connect through base/common families with
  source-span-to-result lineage
* Normative and full BDI/agency overlays remain deferred (LFP2-044 after
  LFP2-037 / LFP2-040)

Interfaces: IntentLogicSlice@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.evidence_v2 import (
    ExecutionRecordKind,
    ReplayDisposition,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import DomainSliceStatus
from ipfs_datasets_py.logic.intent_ir.formalize.logic_slice_v2 import (
    ASSUMPTION_CATEGORIES,
    DEFERRED_ROUTE_KINDS,
    DOMAIN_ID,
    EVIDENCE_SUBSET,
    INTENT_LOGIC_SLICE_INTERFACE,
    LINEAGE_STAGES,
    PROPERTY_KIND_ROUTE_KINDS,
    SUPPORTED_ROUTE_KINDS,
    VIEW_ROLE_ROUTE_KINDS,
    AdvisorConfidenceAsCorrectnessError,
    ExplicitAssumptions,
    IntentLogicSlice,
    IntentRouteKind,
    IntentRouteNamespace,
    ObligationLineageBundle,
    UnsupportedRouteError,
    connect_all_intent_routes,
    connect_intent_obligation,
    connect_intent_route,
    default_obligation_routes,
    reject_advisor_confidence_as_correctness,
    validate_intent_logic_slice,
)
from ipfs_datasets_py.logic.intent_ir.formalize.typed_compiler import (
    NEVER_FAMILY_OPERATION_ROLES,
    NEVER_FAMILY_PROPERTY_KINDS,
    OperationRoleAsFamilyError,
    PropertyAsFamilyError,
    RouteNamespace,
    resolve_intent_route,
)


# ---------------------------------------------------------------------------
# Interface and catalog
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    slice_api = IntentLogicSlice()
    assert slice_api.interface == INTENT_LOGIC_SLICE_INTERFACE
    assert slice_api.interface == "IntentLogicSlice@2"
    assert slice_api.domain_id == DOMAIN_ID == "intent_ir"
    wire = slice_api.to_dict()
    assert wire["interface"] == INTENT_LOGIC_SLICE_INTERFACE
    assert wire["weakens_to_free_form"] is False
    assert wire["advisor_confidence_establishes_correctness"] is False
    assert set(wire["supported_route_kinds"]) == {
        item.value for item in SUPPORTED_ROUTE_KINDS
    }
    assert set(wire["assumption_categories"]) == set(ASSUMPTION_CATEGORIES)
    assert set(wire["evidence_subset"]) == set(EVIDENCE_SUBSET)
    assert set(wire["property_kind_routes"]) == set(PROPERTY_KIND_ROUTE_KINDS)
    assert set(wire["view_role_routes"]) == set(VIEW_ROLE_ROUTE_KINDS)


def test_supported_catalog_covers_evidence_subset() -> None:
    routes = default_obligation_routes()
    expected = {
        "intent",
        "skill",
        "prompt",
        "goal",
        "guard",
        "workflow",
        "authorization",
        "policy",
        "safety",
        "liveness",
        "verification_condition",
    }
    assert {kind.value for kind in routes} == expected
    assert set(IntentLogicSlice().supported_route_kinds()) == expected
    # Evidence subset from the backlog task must be present.
    for required in EVIDENCE_SUBSET:
        assert required in expected
    for required in (
        "intent",
        "skill",
        "prompt",
        "goal",
        "guard",
        "workflow",
        "authorization",
        "policy",
    ):
        assert required in expected


def test_deferred_overlays_fail_closed() -> None:
    slice_api = IntentLogicSlice()
    deferred = set(slice_api.deferred_route_kinds())
    assert deferred == set(DEFERRED_ROUTE_KINDS)
    for kind in (
        "bdi_overlay",
        "agency_overlay",
        "normative_overlay",
        "free_form",
        "graph_projection",
    ):
        assert kind in deferred
        with pytest.raises(UnsupportedRouteError, match="deferred|unsupported"):
            slice_api.connect_route(kind)


# ---------------------------------------------------------------------------
# End-to-end lineage
# ---------------------------------------------------------------------------


def test_every_admitted_route_has_full_lineage() -> None:
    digests = validate_intent_logic_slice()
    assert set(digests) == {item.value for item in SUPPORTED_ROUTE_KINDS}
    for kind, digest in digests.items():
        assert isinstance(digest, str) and len(digest) == 64


def test_connect_all_returns_complete_bundles() -> None:
    bundles = connect_all_intent_routes()
    assert len(bundles) == len(SUPPORTED_ROUTE_KINDS)
    seen: set[str] = set()
    for bundle in bundles:
        assert isinstance(bundle, ObligationLineageBundle)
        complete = bundle.require_complete_lineage()
        kind = complete.obligation_kind.value
        assert kind not in seen
        seen.add(kind)
        for stage in LINEAGE_STAGES:
            assert stage in complete.to_dict()
            assert complete.to_dict()[stage]
        # Typed origin bound to source span and expression digests.
        assert complete.typed_origin.source_digest
        assert complete.typed_origin.expression_digest
        assert complete.typed_origin.document_id
        assert complete.typed_origin.domain_slice_id
        assert complete.typed_origin.source_range is not None
        assert complete.typed_origin.source_range.end > complete.typed_origin.source_range.start
        # Semantics carry typed namespaces.
        assert complete.semantics.family
        assert complete.semantics.profile
        assert complete.semantics.property
        assert complete.semantics.view
        assert complete.semantics.statement
        assert complete.semantics.route_namespace
        # Translation is a reviewed catalog edge.
        assert complete.translation.edge_id
        assert complete.translation.source_family_id
        assert complete.translation.target_family_id
        assert complete.translation.content_id
        # Request / result / replay digests are bound.
        assert complete.request.request_digest
        assert complete.result.parsed_artifact_digest
        assert complete.replay.replay_claimed is True
        assert complete.replay.disposition == ReplayDisposition.REPLAYED.value
        assert (
            complete.replay.record_kind
            == ExecutionRecordKind.HERMETIC_FIXTURE.value
        )
        # Authority lineage covers every stage and never upgrades.
        stage_names = [item.stage for item in complete.authority_lineage.stages]
        assert stage_names == list(LINEAGE_STAGES)
        assert complete.authority_lineage.never_upgrades is True
        assert complete.authority_lineage.terminal_authority
        # Explicit assumption axes are always present.
        assumptions = complete.semantics.assumptions
        assert isinstance(assumptions, ExplicitAssumptions)
        for axis in ASSUMPTION_CATEGORIES:
            assert hasattr(assumptions, axis)
            assert axis in assumptions.to_dict()
        # Advisor confidence cannot establish correctness (declared on every route).
        assert any(
            "confidence_not_correctness" in item or "candidate_only" in item
            for item in assumptions.advisor_scope
        )


@pytest.mark.parametrize("kind", [item.value for item in SUPPORTED_ROUTE_KINDS])
def test_individual_route_lineage(kind: str) -> None:
    bundle = connect_intent_route(kind)
    complete = bundle.require_complete_lineage()
    assert complete.obligation_kind.value == kind
    assert complete.domain_slice.status is DomainSliceStatus.ADMITTED
    assert complete.domain_slice.domain == "intent_ir"
    # Source → request → execution → replay chain.
    assert (
        complete.backend_request.source_digest
        == complete.typed_origin.source_digest
    )
    assert (
        complete.backend_request.expression_digest
        == complete.typed_origin.expression_digest
    )
    assert (
        complete.execution.request_digest
        == complete.backend_request.content_digest
    )
    assert (
        complete.replay_receipt.execution_receipt_digest
        == complete.execution.content_digest
    )
    assert complete.replay_receipt.replay_claimed is True
    # Domain slice admits backend use and retains source span.
    complete.domain_slice.require_admitted()
    complete.domain_slice.validate_against(
        document=complete.document, expression=complete.expression
    )
    assert complete.domain_slice.source_range is not None
    assert complete.compiled.source_map is not None
    assert complete.compiled.source_map.document_id == complete.document.document_id


def test_source_span_to_result_lineage() -> None:
    """Source ranges join claims to typed expressions, requests, and results."""

    for bundle in connect_all_intent_routes():
        origin_range = bundle.typed_origin.source_range
        assert origin_range is not None
        assert origin_range.start == 0
        assert origin_range.end == bundle.document.byte_length
        assert bundle.expression.range is not None
        assert bundle.expression.range.start == origin_range.start
        assert bundle.expression.range.end == origin_range.end
        assert bundle.domain_slice.source_range is not None
        assert bundle.domain_slice.source_range.start == origin_range.start
        assert bundle.domain_slice.source_range.end == origin_range.end
        entries = bundle.compiled.source_map.entries
        assert entries
        assert entries[0].range.start == origin_range.start
        assert entries[0].range.end == origin_range.end
        assert bundle.result.compiled_artifact_digest == bundle.compiled.content_digest
        assert bundle.result.parsed_artifact_digest == bundle.parsed.content_digest


# ---------------------------------------------------------------------------
# Safety / liveness remain properties; VC remains a view role
# ---------------------------------------------------------------------------


def test_safety_and_liveness_remain_properties() -> None:
    for kind in ("safety", "liveness"):
        bundle = connect_intent_route(kind)
        assert bundle.semantics.is_property_kind is True
        assert bundle.semantics.is_semantic_family is False
        assert bundle.semantics.is_view_role is False
        assert bundle.semantics.route_namespace == IntentRouteNamespace.PROPERTY.value
        assert bundle.semantics.property == kind
        assert bundle.semantics.family == "temporal"
        # Formalization compiler dual-read agrees.
        route = resolve_intent_route(kind)
        assert route.is_property_kind is True
        assert route.namespace is RouteNamespace.PROPERTY
        assert route.property_id == kind
        assert route.family_id == "temporal"
        assert kind in NEVER_FAMILY_PROPERTY_KINDS
        assert kind in PROPERTY_KIND_ROUTE_KINDS


def test_verification_condition_remains_view_role() -> None:
    bundle = connect_intent_route("verification_condition")
    assert bundle.semantics.is_view_role is True
    assert bundle.semantics.is_semantic_family is False
    assert bundle.semantics.is_property_kind is False
    assert bundle.semantics.route_namespace == IntentRouteNamespace.VIEW_ROLE.value
    assert bundle.semantics.view == "verification_condition"
    # Underlying typed family for expression identity is program, not VC.
    assert bundle.semantics.family == "program"
    assert bundle.semantics.family != "verification_condition"
    assert "verification_condition" in NEVER_FAMILY_OPERATION_ROLES
    assert "verification_condition" in VIEW_ROLE_ROUTE_KINDS

    formal = resolve_intent_route("verification_condition")
    assert formal.is_operation_role is True
    assert formal.namespace is RouteNamespace.VIEW_ROLE
    assert formal.view_role_id == "verification_condition"
    assert formal.family_id == ""


def test_property_and_view_role_never_route_as_families() -> None:
    slice_api = IntentLogicSlice()
    for label in ("safety", "liveness", "safety_liveness"):
        with pytest.raises(PropertyAsFamilyError):
            slice_api.reject_property_as_family(label)
    for label in (
        "verification_condition",
        "graph_projection",
        "proof_translation",
    ):
        with pytest.raises(OperationRoleAsFamilyError):
            slice_api.reject_view_role_as_family(label)


def test_legacy_aliases_preserve_property_and_view_role() -> None:
    safety = connect_intent_route("safety")
    liveness = connect_intent_route("liveness")
    vc = connect_intent_route("vc")
    assert safety.semantics.is_property_kind is True
    assert liveness.semantics.is_property_kind is True
    assert vc.semantics.is_view_role is True
    assert vc.obligation_kind is IntentRouteKind.VERIFICATION_CONDITION


# ---------------------------------------------------------------------------
# Advisor confidence cannot establish intent correctness
# ---------------------------------------------------------------------------


def test_advisor_confidence_cannot_establish_intent_correctness() -> None:
    slice_api = IntentLogicSlice()
    with pytest.raises(AdvisorConfidenceAsCorrectnessError):
        slice_api.reject_advisor_confidence_as_correctness(
            confidence=1.0,
            claimed_correct=True,
            source_kind="advisor",
        )
    with pytest.raises(AdvisorConfidenceAsCorrectnessError):
        reject_advisor_confidence_as_correctness(confidence=0.99)
    with pytest.raises(AdvisorConfidenceAsCorrectnessError):
        reject_advisor_confidence_as_correctness(
            confidence=1.0,
            source_kind="prompt",
        )


def test_prompt_route_stays_candidate_scoped() -> None:
    bundle = connect_intent_route("prompt")
    assert bundle.request.authority_ceiling == "candidate"
    assert bundle.result.result_authority == "candidate"
    assert any(
        "prompt" in item or "candidate" in item
        for item in bundle.semantics.assumptions.source_grounding
    )
    assert any(
        "confidence_not_correctness" in item
        for item in bundle.semantics.assumptions.advisor_scope
    )


def test_authorization_rejects_confidence_only_tool_authority() -> None:
    bundle = connect_intent_route("authorization")
    assumptions = bundle.semantics.assumptions
    assert assumptions.tool_authority
    assert any(
        "not_from_confidence" in item or "grounded_permission" in item
        for item in assumptions.tool_authority
    )
    assert bundle.translation.edge_id == "authorization_to_secpal"
    assert bundle.request.authority_ceiling == "authorization"
    assert bundle.result.result_authority == "authorization"


# ---------------------------------------------------------------------------
# Base goal / guard / workflow / policy routes
# ---------------------------------------------------------------------------


def test_goal_guard_workflow_policy_routes() -> None:
    goal = connect_intent_route("goal")
    guard = connect_intent_route("guard")
    workflow = connect_intent_route("workflow")
    policy = connect_intent_route("policy")
    skill = connect_intent_route("skill")
    intent = connect_intent_route("intent")

    assert goal.semantics.family == "intention_agency"
    assert goal.translation.edge_id == "intention_to_fol_reified"
    assert goal.semantics.view == "skill_goals"
    assert goal.semantics.is_semantic_family is True

    assert guard.semantics.family == "first_order"
    assert guard.translation.edge_id == "vc_to_smt"
    assert guard.semantics.profile == "guards_effects"
    assert guard.semantics.is_semantic_family is True

    assert workflow.semantics.family == "temporal"
    assert workflow.translation.edge_id == "temporal_ltl_to_tla_plus"
    assert workflow.semantics.assumptions.bound
    assert workflow.semantics.is_semantic_family is True

    assert policy.semantics.family == "deontic"
    assert policy.translation.edge_id == "deontic_to_fol_reified"
    assert policy.semantics.assumptions.policy_authority
    assert policy.semantics.is_semantic_family is True

    assert skill.semantics.family == "program"
    assert skill.translation.edge_id == "program_to_smt"
    assert skill.semantics.profile == "dynamic_hoare"

    assert intent.semantics.family == "first_order"
    assert intent.translation.edge_id == "vc_to_smt"
    assert intent.semantics.view == "facts"


def test_connect_obligation_alias() -> None:
    a = connect_intent_obligation("guard")
    b = connect_intent_route("guard")
    assert a.obligation_kind is b.obligation_kind
    assert a.translation.edge_id == b.translation.edge_id


def test_authority_never_upgrades_along_chain() -> None:
    """Terminal authority must not exceed the request ceiling."""

    rank = {
        "none": 0,
        "advisory": 1,
        "candidate": 2,
        "bounded": 3,
        "finite_trace": 4,
        "authorization": 5,
        "satisfiability": 6,
        "protocol": 7,
        "reconstruction": 8,
        "kernel": 9,
        "attestation": 10,
        "independently_checkable": 6,
        "authoritative": 9,
        "model_check": 4,
        "monitor": 4,
    }
    for bundle in connect_all_intent_routes():
        request_ceiling = bundle.request.authority_ceiling
        terminal = bundle.authority_lineage.terminal_authority
        assert rank.get(terminal, 0) <= rank.get(request_ceiling, 99) or (
            terminal == request_ceiling
        )
        for stage in bundle.authority_lineage.stages:
            if stage.stage == "authority_lineage":
                assert stage.authority_ceiling == terminal


def test_route_aliases_resolve() -> None:
    slice_api = IntentLogicSlice()
    assert slice_api.route_for("goals").kind is IntentRouteKind.GOAL
    assert slice_api.route_for("guards_effects").kind is IntentRouteKind.GUARD
    assert slice_api.route_for("workflows").kind is IntentRouteKind.WORKFLOW
    assert slice_api.route_for("tool_permissions").kind is IntentRouteKind.AUTHORIZATION
    assert slice_api.route_for("norms").kind is IntentRouteKind.POLICY
    assert slice_api.route_for("action_hoare").kind is IntentRouteKind.SKILL
    assert slice_api.route_for("facts").kind is IntentRouteKind.INTENT


def test_unknown_route_fails_closed() -> None:
    with pytest.raises(UnsupportedRouteError):
        connect_intent_route("not_a_real_intent_route")

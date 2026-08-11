"""Conformance: Security IR typed executable logic slice (LFP2-022).

Acceptance:

* Each admitted route has source-span-to-result lineage
* Information-flow, attacker, bound, and policy authority assumptions are explicit
* Free-form origins are rejected; authority never upgrades along the chain

Interfaces: SecurityLogicSlice@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.evidence_v2 import (
    ExecutionRecordKind,
    ReplayDisposition,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import DomainSliceStatus
from ipfs_datasets_py.logic.security_ir.formalization_adapter_v2 import (
    ADMITTED_SECURITY_VIEW_NAMES,
)
from ipfs_datasets_py.logic.security_ir.logic_slice_v2 import (
    ASSUMPTION_CATEGORIES,
    DEFERRED_ROUTE_KINDS,
    DOMAIN_ID,
    LINEAGE_STAGES,
    SECURITY_LOGIC_SLICE_INTERFACE,
    SUPPORTED_ROUTE_KINDS,
    ExplicitAssumptions,
    ObligationLineageBundle,
    ObligationLineageError,
    SecurityLogicSlice,
    SecurityRouteKind,
    UnsupportedRouteError,
    connect_all_security_routes,
    connect_security_obligation,
    connect_security_route,
    default_obligation_routes,
    validate_security_logic_slice,
)


# ---------------------------------------------------------------------------
# Interface and catalog
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    slice_api = SecurityLogicSlice()
    assert slice_api.interface == SECURITY_LOGIC_SLICE_INTERFACE
    assert slice_api.interface == "SecurityLogicSlice@2"
    assert slice_api.domain_id == DOMAIN_ID == "security_ir"
    wire = slice_api.to_dict()
    assert wire["interface"] == SECURITY_LOGIC_SLICE_INTERFACE
    assert wire["weakens_to_free_form"] is False
    assert set(wire["supported_route_kinds"]) == {
        item.value for item in SUPPORTED_ROUTE_KINDS
    }
    assert set(wire["assumption_categories"]) == set(ASSUMPTION_CATEGORIES)


def test_supported_catalog_matches_admitted_views() -> None:
    routes = default_obligation_routes()
    expected = set(ADMITTED_SECURITY_VIEW_NAMES)
    assert {kind.value for kind in routes} == expected
    assert set(SecurityLogicSlice().supported_route_kinds()) == expected
    # Evidence subset from the backlog task must be present.
    for required in (
        "claim",
        "threat",
        "authorization",
        "temporal",
        "protocol",
        "separation",
        "noninterference",
    ):
        assert required in expected


def test_deferred_operation_roles_fail_closed() -> None:
    slice_api = SecurityLogicSlice()
    deferred = set(slice_api.deferred_route_kinds())
    assert deferred == set(DEFERRED_ROUTE_KINDS)
    for kind in ("verification_condition", "graph_projection", "proof_translation"):
        assert kind in deferred
        with pytest.raises(UnsupportedRouteError, match="deferred|unsupported"):
            slice_api.connect_route(kind)


# ---------------------------------------------------------------------------
# End-to-end lineage
# ---------------------------------------------------------------------------


def test_every_admitted_route_has_full_lineage() -> None:
    digests = validate_security_logic_slice()
    assert set(digests) == {item.value for item in SUPPORTED_ROUTE_KINDS}
    for kind, digest in digests.items():
        assert isinstance(digest, str) and len(digest) == 64


def test_connect_all_returns_complete_bundles() -> None:
    bundles = connect_all_security_routes()
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


@pytest.mark.parametrize("kind", [item.value for item in SUPPORTED_ROUTE_KINDS])
def test_individual_route_lineage(kind: str) -> None:
    bundle = connect_security_route(kind)
    complete = bundle.require_complete_lineage()
    assert complete.obligation_kind.value == kind
    assert complete.domain_slice.status is DomainSliceStatus.ADMITTED
    assert complete.domain_slice.domain == "security_ir"
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

    for bundle in connect_all_security_routes():
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
        # Compiled artifact source map preserves the same document identity.
        entries = bundle.compiled.source_map.entries
        assert entries
        assert entries[0].range.start == origin_range.start
        assert entries[0].range.end == origin_range.end
        # Result digests are bound to the compiled/parsed chain.
        assert bundle.result.compiled_artifact_digest == bundle.compiled.content_digest
        assert bundle.result.parsed_artifact_digest == bundle.parsed.content_digest


# ---------------------------------------------------------------------------
# Explicit assumption axes
# ---------------------------------------------------------------------------


def test_information_flow_assumptions_explicit_on_noninterference() -> None:
    bundle = connect_security_route("noninterference")
    assumptions = bundle.semantics.assumptions
    assert assumptions.information_flow
    assert any("high_low" in item or "information_flow" in item for item in assumptions.information_flow)
    assert any("bound" in item or "alternation" in item for item in assumptions.bound)
    assert "noninterference_to_self_composition" == bundle.translation.edge_id
    assert bundle.semantics.property == "noninterference"
    assert bundle.result.result_authority == "hyperproperty"


def test_attacker_assumptions_explicit_on_protocol_and_threat() -> None:
    protocol = connect_security_route("protocol")
    threat = connect_security_route("threat")
    assert protocol.semantics.assumptions.attacker
    assert any("dolev_yao" in item for item in protocol.semantics.assumptions.attacker)
    assert protocol.translation.edge_id == "symbolic_protocol_to_proverif_applied_pi"
    assert protocol.request.authority_ceiling == "protocol"
    assert protocol.result.result_authority == "protocol"

    assert threat.semantics.assumptions.attacker
    assert any("attacker" in item for item in threat.semantics.assumptions.attacker)
    assert threat.semantics.assumptions.bound
    assert threat.request.authority_ceiling == "bounded"


def test_bound_assumptions_explicit_on_state_temporal_concurrency() -> None:
    for kind in ("state", "temporal", "concurrency", "threat", "noninterference"):
        bundle = connect_security_route(kind)
        assert bundle.semantics.assumptions.bound, f"{kind} missing bound assumptions"
        assert any(
            item.startswith("bound:") or "bound" in item or "finite" in item
            for item in bundle.semantics.assumptions.bound
        ), kind


def test_policy_authority_assumptions_explicit_on_authorization() -> None:
    bundle = connect_security_route("authorization")
    assumptions = bundle.semantics.assumptions
    assert assumptions.policy_authority
    assert any(
        "policy_authority" in item or "delegation" in item or "principal" in item
        for item in assumptions.policy_authority
    )
    assert bundle.translation.edge_id == "authorization_to_secpal"
    assert bundle.request.authority_ceiling == "authorization"
    assert bundle.result.result_authority == "authorization"
    assert bundle.request.provider == "datalog_secpal"


def test_every_route_declares_all_assumption_axes() -> None:
    for kind, route in default_obligation_routes().items():
        axes = route.assumptions.to_dict()
        assert set(axes) == set(ASSUMPTION_CATEGORIES)
        # Flattened assumption ids appear on the route and domain slice.
        bundle = connect_security_route(kind)
        for assumption_id in route.assumption_ids:
            assert assumption_id in bundle.domain_slice.assumption_ids
            assert assumption_id in bundle.semantics.assumption_ids


# ---------------------------------------------------------------------------
# Route-specific translation edges
# ---------------------------------------------------------------------------


def test_claim_uses_vc_to_smt_edge() -> None:
    claim = connect_security_route("claim")
    assert claim.translation.edge_id == "vc_to_smt"
    assert claim.translation.family_key == "program"
    assert claim.semantics.family == "first_order"
    assert claim.request.authority_ceiling == "satisfiability"


def test_separation_and_concurrency_routes() -> None:
    separation = connect_security_route("separation")
    concurrency = connect_security_route("concurrency")
    assert separation.translation.edge_id == "separation_to_smt"
    assert concurrency.translation.edge_id == "concurrency_to_bounded_smt"
    assert "frame" in separation.semantics.property or separation.semantics.property == "frame"
    assert concurrency.semantics.property == "rely_guarantee"
    assert concurrency.semantics.assumptions.bound


def test_temporal_uses_tla_edge() -> None:
    temporal = connect_security_route("temporal")
    assert temporal.translation.edge_id == "temporal_ltl_to_tla_plus"
    assert temporal.request.authority_ceiling == "bounded"
    assert temporal.result.result_authority == "model_check"
    assert temporal.semantics.assumptions.bound


# ---------------------------------------------------------------------------
# Authority discipline
# ---------------------------------------------------------------------------


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
        # EvidenceAuthority wire values that may appear on translation edges.
        "independently_checkable": 6,
        "authoritative": 9,
    }
    for bundle in connect_all_security_routes():
        request_ceiling = bundle.request.authority_ceiling
        terminal = bundle.authority_lineage.terminal_authority
        assert rank[terminal] <= rank[request_ceiling] or terminal == request_ceiling
        for stage in bundle.authority_lineage.stages:
            if stage.stage == "authority_lineage":
                assert stage.authority_ceiling == terminal


def test_unknown_route_fails_closed() -> None:
    with pytest.raises(UnsupportedRouteError):
        connect_security_route("not_a_real_route")
    with pytest.raises(UnsupportedRouteError):
        SecurityLogicSlice().route_for("boolean_receipt")
    with pytest.raises(UnsupportedRouteError):
        connect_security_obligation("free_form")


def test_lineage_bundle_rejects_broken_authority() -> None:
    bundle = connect_security_route("claim")
    with pytest.raises(ObligationLineageError, match="missing stage|authority"):
        broken = ObligationLineageBundle(
            obligation_kind=bundle.obligation_kind,
            typed_origin=bundle.typed_origin,
            semantics=bundle.semantics,
            translation=bundle.translation,
            request=bundle.request,
            result=bundle.result,
            replay=bundle.replay,
            authority_lineage=type(bundle.authority_lineage)(
                stages=(),
                terminal_authority=bundle.authority_lineage.terminal_authority,
            ),
            domain_slice=bundle.domain_slice,
            obligation=bundle.obligation,
            backend_request=bundle.backend_request,
            compiled=bundle.compiled,
            parsed=bundle.parsed,
            execution=bundle.execution,
            replay_receipt=bundle.replay_receipt,
            expression=bundle.expression,
            document=bundle.document,
        )
        broken.require_complete_lineage()


def test_module_helpers_match_class_api() -> None:
    via_class = SecurityLogicSlice().connect_route(SecurityRouteKind.PROTOCOL)
    via_helper = connect_security_route("protocol")
    via_obligation = connect_security_obligation("protocol")
    assert via_class.obligation_kind == via_helper.obligation_kind
    assert via_class.translation.edge_id == via_helper.translation.edge_id
    assert via_class.typed_origin.source_digest == via_helper.typed_origin.source_digest
    assert via_obligation.translation.edge_id == via_helper.translation.edge_id

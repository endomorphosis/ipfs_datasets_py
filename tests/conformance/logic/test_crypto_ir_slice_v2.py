"""Conformance: Crypto IR typed executable logic slice (LFP2-023).

Acceptance:

* Network/chain model, arithmetic domain, adversary, trace, finality, and
  approximation assumptions are never implicit
* Ledger, consensus, finality, protocol, arithmetic, and hyperproperty routes
  connect through base/common families with source-span-to-result lineage
* Finite-field / ZK overlays remain deferred (LFP2-044 after LFP2-042)
* Free-form origins are rejected; authority never upgrades along the chain

Interfaces: CryptoLogicSlice@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.evidence_v2 import (
    ExecutionRecordKind,
    ReplayDisposition,
)
from ipfs_datasets_py.logic.crypto_ir.formalization.logic_slice_v2 import (
    ASSUMPTION_CATEGORIES,
    CRYPTO_LOGIC_SLICE_INTERFACE,
    DEFERRED_ROUTE_KINDS,
    DOMAIN_ID,
    EVIDENCE_SUBSET,
    LINEAGE_STAGES,
    SUPPORTED_ROUTE_KINDS,
    CryptoLogicSlice,
    CryptoRouteKind,
    ExplicitAssumptions,
    ObligationLineageBundle,
    ObligationLineageError,
    UnsupportedRouteError,
    adapt_and_connect,
    connect_all_crypto_routes,
    connect_crypto_obligation,
    connect_crypto_route,
    default_obligation_routes,
    validate_crypto_logic_slice,
)
from ipfs_datasets_py.logic.crypto_ir.formalization.typed_adapter import (
    CryptoNetworkViewKind,
    NetworkAssumptionKind,
    REQUIRED_ASSUMPTION_KINDS,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import DomainSliceStatus


# ---------------------------------------------------------------------------
# Interface and catalog
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    slice_api = CryptoLogicSlice()
    assert slice_api.interface == CRYPTO_LOGIC_SLICE_INTERFACE
    assert slice_api.interface == "CryptoLogicSlice@2"
    assert slice_api.domain_id == DOMAIN_ID == "crypto_ir"
    wire = slice_api.to_dict()
    assert wire["interface"] == CRYPTO_LOGIC_SLICE_INTERFACE
    assert wire["weakens_to_free_form"] is False
    assert set(wire["supported_route_kinds"]) == {
        item.value for item in SUPPORTED_ROUTE_KINDS
    }
    assert set(wire["assumption_categories"]) == set(ASSUMPTION_CATEGORIES)
    assert set(wire["evidence_subset"]) == set(EVIDENCE_SUBSET)


def test_supported_catalog_covers_evidence_subset() -> None:
    routes = default_obligation_routes()
    expected = {
        "ledger",
        "balances",
        "consensus",
        "finality",
        "bridges",
        "wallets",
        "authorization",
        "protocol",
        "arithmetic",
        "hyperproperty",
    }
    assert {kind.value for kind in routes} == expected
    assert set(CryptoLogicSlice().supported_route_kinds()) == expected
    # Evidence subset from the backlog task must be present.
    for required in EVIDENCE_SUBSET:
        assert required in expected
    for required in (
        "ledger",
        "consensus",
        "finality",
        "protocol",
        "arithmetic",
        "hyperproperty",
    ):
        assert required in expected


def test_deferred_finite_field_and_zk_fail_closed() -> None:
    slice_api = CryptoLogicSlice()
    deferred = set(slice_api.deferred_route_kinds())
    assert deferred == set(DEFERRED_ROUTE_KINDS)
    for kind in (
        "finite_field",
        "zk",
        "zk_constraint",
        "zero_knowledge",
        "probabilistic",
    ):
        assert kind in deferred
        with pytest.raises(UnsupportedRouteError, match="deferred|unsupported"):
            slice_api.connect_route(kind)


# ---------------------------------------------------------------------------
# End-to-end lineage
# ---------------------------------------------------------------------------


def test_every_admitted_route_has_full_lineage() -> None:
    digests = validate_crypto_logic_slice()
    assert set(digests) == {item.value for item in SUPPORTED_ROUTE_KINDS}
    for kind, digest in digests.items():
        assert isinstance(digest, str) and len(digest) == 64


def test_connect_all_returns_complete_bundles() -> None:
    bundles = connect_all_crypto_routes()
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
        assert complete.semantics.network_view
        assert complete.semantics.network_view_id.startswith("crypto-ir-view/")
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
    bundle = connect_crypto_route(kind)
    complete = bundle.require_complete_lineage()
    assert complete.obligation_kind.value == kind
    assert complete.domain_slice.status is DomainSliceStatus.ADMITTED
    assert complete.domain_slice.domain == "crypto_ir"
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
    complete.domain_slice.require_admitted()
    complete.domain_slice.validate_against(
        document=complete.document, expression=complete.expression
    )
    assert complete.domain_slice.source_range is not None
    assert complete.compiled.source_map is not None
    assert complete.compiled.source_map.document_id == complete.document.document_id


def test_source_span_to_result_lineage() -> None:
    """Source ranges join claims to typed expressions, requests, and results."""

    for bundle in connect_all_crypto_routes():
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
# Explicit assumption axes (never implicit)
# ---------------------------------------------------------------------------


def test_assumption_categories_match_acceptance() -> None:
    assert set(ASSUMPTION_CATEGORIES) == {
        "network_chain",
        "arithmetic_domain",
        "adversary",
        "trace",
        "finality",
        "approximation",
    }


def test_every_route_declares_all_assumption_axes() -> None:
    for kind, route in default_obligation_routes().items():
        axes = route.assumptions.to_dict()
        assert set(axes) == set(ASSUMPTION_CATEGORIES), kind
        # Every axis is declared (values may be not_applicable, never omitted).
        for axis, values in axes.items():
            assert isinstance(values, list), f"{kind}.{axis}"
            assert values, f"{kind} must populate {axis} (never implicit)"
        bundle = connect_crypto_route(kind)
        for assumption_id in route.assumption_ids:
            assert assumption_id in bundle.domain_slice.assumption_ids
            assert assumption_id in bundle.semantics.assumption_ids


def test_network_chain_assumptions_explicit_on_ledger_consensus_finality() -> None:
    for kind in ("ledger", "consensus", "finality", "bridges"):
        bundle = connect_crypto_route(kind)
        network = bundle.semantics.assumptions.network_chain
        assert network, f"{kind} missing network_chain assumptions"
        assert any(
            "network_chain" in item or "consensus" in item or "fork" in item
            for item in network
        ), kind


def test_arithmetic_domain_assumptions_explicit() -> None:
    arithmetic = connect_crypto_route("arithmetic")
    domain = arithmetic.semantics.assumptions.arithmetic_domain
    assert domain
    assert any("linear_integer" in item or "arithmetic" in item for item in domain)
    assert any("bitvector" in item or "linear_integer" in item for item in domain)

    balances = connect_crypto_route("balances")
    assert balances.semantics.assumptions.arithmetic_domain
    assert any(
        "linear_integer" in item for item in balances.semantics.assumptions.arithmetic_domain
    )


def test_adversary_assumptions_explicit_on_protocol_and_consensus() -> None:
    protocol = connect_crypto_route("protocol")
    assert protocol.semantics.assumptions.adversary
    assert any(
        "dolev_yao" in item for item in protocol.semantics.assumptions.adversary
    )
    assert protocol.translation.edge_id == "symbolic_protocol_to_proverif_applied_pi"
    assert protocol.request.authority_ceiling == "protocol"
    assert protocol.result.result_authority == "protocol"

    consensus = connect_crypto_route("consensus")
    assert consensus.semantics.assumptions.adversary
    assert any(
        "byzantine" in item or "adversary" in item
        for item in consensus.semantics.assumptions.adversary
    )

    bridges = connect_crypto_route("bridges")
    assert any("dolev_yao" in item for item in bridges.semantics.assumptions.adversary)


def test_trace_assumptions_explicit() -> None:
    for kind in ("ledger", "consensus", "finality", "protocol", "hyperproperty"):
        bundle = connect_crypto_route(kind)
        assert bundle.semantics.assumptions.trace, f"{kind} missing trace"
        assert any(
            "trace" in item or "finite" in item
            for item in bundle.semantics.assumptions.trace
        ), kind


def test_finality_assumptions_explicit() -> None:
    finality = connect_crypto_route("finality")
    assert finality.semantics.assumptions.finality
    assert any(
        "depth" in item or "checkpoint" in item or "finality" in item
        for item in finality.semantics.assumptions.finality
    )
    ledger = connect_crypto_route("ledger")
    assert any(
        "observation_bound" in item or "finality" in item
        for item in ledger.semantics.assumptions.finality
    )
    bridges = connect_crypto_route("bridges")
    assert any(
        "source_finality" in item or "finality" in item
        for item in bridges.semantics.assumptions.finality
    )


def test_approximation_assumptions_explicit() -> None:
    for kind in SUPPORTED_ROUTE_KINDS:
        bundle = connect_crypto_route(kind)
        approx = bundle.semantics.assumptions.approximation
        assert approx, f"{kind.value} missing approximation assumptions"
        assert any(
            item.startswith("assumption:approximation:")
            or item.startswith("bound:")
            or "bound" in item
            or "finite" in item
            or "approx" in item
            for item in approx
        ), kind.value


def test_network_adapter_assumptions_aligned() -> None:
    """Slice routes remain aligned with CryptoNetworkFormalizationAdapter@1."""

    adapter_required = set(REQUIRED_ASSUMPTION_KINDS)
    assert adapter_required == {
        "attacker",
        "consensus",
        "finality",
        "bound",
        "arithmetic",
        "trace",
    }
    slice_api = CryptoLogicSlice()
    for kind in SUPPORTED_ROUTE_KINDS:
        route = slice_api.route_for(kind)
        network = slice_api.network_adapter.route_for(route.network_view)
        kinds = {item.kind.value for item in network.assumptions}
        assert kinds == adapter_required
        for n_kind in NetworkAssumptionKind:
            assumption = network.assumption(n_kind)
            assert assumption.statement
            assert assumption.value


# ---------------------------------------------------------------------------
# Route-specific translation edges and network views
# ---------------------------------------------------------------------------


def test_ledger_and_finality_use_state_temporal_edges() -> None:
    ledger = connect_crypto_route("ledger")
    finality = connect_crypto_route("finality")
    consensus = connect_crypto_route("consensus")
    assert ledger.translation.edge_id == "transition_system_to_bounded_smt"
    assert ledger.translation.family_key == "state_temporal"
    assert ledger.semantics.family == "transition_system"
    assert ledger.semantics.network_view == "transactions"
    assert finality.translation.edge_id == "transition_system_to_tla_plus"
    assert finality.semantics.network_view == "reorg_finality"
    assert consensus.translation.edge_id == "transition_system_to_tla_plus"
    assert consensus.semantics.network_view == "consensus"


def test_protocol_and_bridges_use_protocol_target_edges() -> None:
    protocol = connect_crypto_route("protocol")
    bridges = connect_crypto_route("bridges")
    assert protocol.translation.edge_id == "symbolic_protocol_to_proverif_applied_pi"
    assert protocol.translation.family_key == "protocol_target"
    assert protocol.semantics.network_view == "symbolic_protocols"
    assert bridges.translation.edge_id == "symbolic_protocol_to_proverif_applied_pi"
    assert bridges.semantics.network_view == "bridges"


def test_arithmetic_and_balances_use_program_vc_edges() -> None:
    arithmetic = connect_crypto_route("arithmetic")
    balances = connect_crypto_route("balances")
    assert arithmetic.translation.edge_id == "vc_to_smt"
    assert arithmetic.translation.family_key == "program"
    assert arithmetic.semantics.family == "first_order"
    assert arithmetic.semantics.network_view == "arithmetic"
    assert arithmetic.semantics.network_view_id == "crypto-ir-view/smt/v1"
    assert balances.translation.edge_id == "vc_to_smt"
    assert balances.request.authority_ceiling == "satisfiability"


def test_authorization_and_wallets_use_secpal_edge() -> None:
    authorization = connect_crypto_route("authorization")
    wallets = connect_crypto_route("wallets")
    assert authorization.translation.edge_id == "authorization_to_secpal"
    assert authorization.request.authority_ceiling == "authorization"
    assert authorization.result.result_authority == "authorization"
    assert authorization.semantics.network_view == "permissions"
    assert wallets.translation.edge_id == "authorization_to_secpal"
    assert wallets.semantics.network_view == "wallets"


def test_hyperproperty_privacy_route() -> None:
    privacy = connect_crypto_route("hyperproperty")
    assert privacy.translation.edge_id == "noninterference_to_self_composition"
    assert privacy.translation.family_key == "hyper"
    assert privacy.semantics.family == "hyperproperty"
    assert privacy.semantics.property == "noninterference"
    assert privacy.semantics.network_view == "privacy"
    assert privacy.semantics.network_view_id == "crypto-ir-view/hyperproperty/v1"
    assert privacy.result.result_authority == "hyperproperty"
    assert any(
        "not_computational_zk" in item or "zk" in item
        for item in privacy.semantics.assumptions.approximation
    )


def test_network_view_aliases_resolve() -> None:
    assert connect_crypto_route("transactions").obligation_kind is CryptoRouteKind.LEDGER
    assert (
        connect_crypto_route("reorg_finality").obligation_kind is CryptoRouteKind.FINALITY
    )
    assert (
        connect_crypto_route("symbolic_protocols").obligation_kind
        is CryptoRouteKind.PROTOCOL
    )
    assert connect_crypto_route("privacy").obligation_kind is CryptoRouteKind.HYPERPROPERTY
    assert (
        connect_crypto_route("permissions").obligation_kind
        is CryptoRouteKind.AUTHORIZATION
    )


def test_adapt_and_connect_helper() -> None:
    bundle = adapt_and_connect(CryptoNetworkViewKind.ARITHMETIC)
    assert bundle.obligation_kind is CryptoRouteKind.ARITHMETIC
    via_str = adapt_and_connect("reorg_finality")
    assert via_str.obligation_kind is CryptoRouteKind.FINALITY


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
        "independently_checkable": 6,
        "authoritative": 9,
    }
    for bundle in connect_all_crypto_routes():
        request_ceiling = bundle.request.authority_ceiling
        terminal = bundle.authority_lineage.terminal_authority
        assert rank[terminal] <= rank[request_ceiling] or terminal == request_ceiling
        for stage in bundle.authority_lineage.stages:
            if stage.stage == "authority_lineage":
                assert stage.authority_ceiling == terminal


def test_unknown_route_fails_closed() -> None:
    with pytest.raises(UnsupportedRouteError):
        connect_crypto_route("not_a_real_route")
    with pytest.raises(UnsupportedRouteError):
        CryptoLogicSlice().route_for("boolean_receipt")
    with pytest.raises(UnsupportedRouteError):
        connect_crypto_obligation("free_form")
    with pytest.raises(UnsupportedRouteError):
        connect_crypto_route("finite_field")


def test_lineage_bundle_rejects_broken_authority() -> None:
    bundle = connect_crypto_route("arithmetic")
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
    via_class = CryptoLogicSlice().connect_route(CryptoRouteKind.PROTOCOL)
    via_helper = connect_crypto_route("protocol")
    via_obligation = connect_crypto_obligation("protocol")
    assert via_class.obligation_kind == via_helper.obligation_kind
    assert via_class.translation.edge_id == via_helper.translation.edge_id
    assert via_class.typed_origin.source_digest == via_helper.typed_origin.source_digest
    assert via_obligation.translation.edge_id == via_helper.translation.edge_id


def test_source_text_mentions_all_assumption_axes() -> None:
    """Default source text documents every acceptance assumption axis."""

    for kind in SUPPORTED_ROUTE_KINDS:
        bundle = connect_crypto_route(kind)
        text = bundle.document.text
        for axis in ASSUMPTION_CATEGORIES:
            assert axis in text, f"{kind.value} source missing axis {axis}"
        assert "crypto_ir" in text
        assert kind.value in text

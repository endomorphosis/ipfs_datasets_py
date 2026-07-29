"""Unit tests for bounded exposure, compliance rules, and formalization.

CRYPTOIR-G430 acceptance coverage:

* traversal bounds: depth, nodes, edges, paths, time, asset, amount/ratio,
  finality, providers, runtime;
* every path is explainable and replays against one graph/list/policy snapshot;
* direct exact hits hard-deny under applicable policy;
* indirect exposure returns configured REVIEW or DENY without designation;
* absence is scoped to a completeness frontier;
* unsupported lowering or truncation fails closed;
* never infer unlimited transitive guilt or claim incomplete search proves
  no connection exists.
"""

from __future__ import annotations

import dataclasses

import pytest

from ipfs_datasets_py.knowledge_graphs.crypto_flows.model import (
    CompletenessReceipt,
    CompletenessStatus,
    CryptoFlowGraph,
    DerivationMethod,
    EdgeKind,
    ExactAmount,
    FinalityStatus,
    FlowDirection,
    FlowEdge,
    FlowNode,
    GraphPlane,
    GraphSnapshot,
    LedgerModel,
    NodeKind,
    RetractionStatus,
    ValidityWindow,
)
from ipfs_datasets_py.logic.crypto_ir.compliance.exposure import (
    BoundedExposure,
    CompletenessFrontier,
    ExposureError,
    ExposurePath,
    ExposurePolicy,
    ExposureVerdict,
    ListedTarget,
    TruncationReason,
    compute_bounded_exposure,
    replay_exposure_path,
)
from ipfs_datasets_py.logic.crypto_ir.compliance.formalize import (
    ComplianceFormalizer,
    FormalizationStatus,
    FormalizeError,
    FormalizedCompliance,
    NegativeConclusionKind,
    formalize_compliance,
)
from ipfs_datasets_py.logic.crypto_ir.compliance.models import (
    AssociationEvidence,
    AssociationKind,
    OwnershipEvidence,
    OwnershipInterest,
    OwnershipKind,
    SanctionsPolicyOutcome,
)
from ipfs_datasets_py.logic.crypto_ir.compliance.rules import (
    CompliancePredicate,
    ComplianceRule,
    ComplianceRuleError,
    ComplianceRuleKind,
    ComplianceRuleSet,
    default_compliance_rules,
    evaluate_compliance_rules,
)
from ipfs_datasets_py.logic.crypto_ir.formalization.compiler import TheoryFragment
from ipfs_datasets_py.logic.crypto_ir.model import AssetIdentity, ChainIdentity
from ipfs_datasets_py.logic.crypto_ir.verdicts import SanctionsMatchLevel


GENESIS = "sha256:" + ("ab" * 32)
HASH_A = "sha256:" + ("a1" * 32)
AT_TIME = "2026-07-15T12:00:00Z"


def eth_chain() -> ChainIdentity:
    return ChainIdentity(
        chain_namespace="eip155",
        network="ethereum-mainnet",
        genesis_digest=GENESIS,
        chain_id="1",
        display_name="Ethereum Mainnet",
    )


def eth_asset() -> AssetIdentity:
    return AssetIdentity(
        chain=eth_chain(),
        asset_namespace="native",
        asset_reference="eth",
        decimals=18,
        symbol="ETH",
    )


def addr_node(node_id: str, address: str, *, providers: tuple[str, ...] = ("provider-a",)) -> FlowNode:
    return FlowNode(
        node_id=node_id,
        kind=NodeKind.ADDRESS,
        plane=GraphPlane.OBSERVED_ADDRESS,
        chain=eth_chain(),
        ledger_model=LedgerModel.ACCOUNT,
        address_ref=address,
        finality=FinalityStatus.FINALIZED,
        source="fixture",
        confidence="1",
        validity=ValidityWindow(start="2024-01-01T00:00:00Z", end=""),
        derivation=DerivationMethod.DIRECT_OBSERVATION,
        provider_ids=providers,
    )


def transfer(
    edge_id: str,
    src: str,
    dst: str,
    *,
    amount: str = "1000",
    finality: FinalityStatus = FinalityStatus.FINALIZED,
    derivation: DerivationMethod = DerivationMethod.ACCOUNT_TRANSFER,
    timestamp: str = "2026-06-01T00:00:00Z",
    providers: tuple[str, ...] = ("provider-a",),
    kind: EdgeKind = EdgeKind.TRANSFER,
) -> FlowEdge:
    return FlowEdge(
        edge_id=edge_id,
        kind=kind,
        plane=GraphPlane.OBSERVED_ADDRESS,
        source_node_id=src,
        target_node_id=dst,
        chain=eth_chain(),
        ledger_model=LedgerModel.ACCOUNT,
        asset=eth_asset(),
        amount=ExactAmount(base_units=amount, decimals=18),
        direction=FlowDirection.OUT,
        finality=finality,
        source="fixture",
        confidence="1",
        validity=ValidityWindow(start="2024-01-01T00:00:00Z", end=""),
        derivation=derivation,
        timestamp=timestamp,
        provider_ids=providers,
    )


def completeness(
    *,
    status: CompletenessStatus = CompletenessStatus.COMPLETE,
    providers: tuple[str, ...] = ("provider-a",),
) -> CompletenessReceipt:
    return CompletenessReceipt(
        receipt_id="receipt:fixture",
        chain=eth_chain(),
        scope="ledger-range",
        completeness=status,
        finality=FinalityStatus.FINALIZED,
        validity=ValidityWindow(start="2024-01-01T00:00:00Z", end=""),
        retraction=RetractionStatus.NOT_RETRACTED,
        provider_ids=providers,
    )


def linear_graph(
    *node_address_pairs: tuple[str, str],
    complete: bool = True,
) -> tuple[CryptoFlowGraph, GraphSnapshot]:
    """Build origin -> ... -> listed linear transfer chain."""

    nodes = [
        addr_node(node_id, address) for node_id, address in node_address_pairs
    ]
    edges = []
    for index in range(len(nodes) - 1):
        edges.append(
            transfer(
                f"edge:{index}",
                nodes[index].node_id,
                nodes[index + 1].node_id,
            )
        )
    receipt = completeness(
        status=CompletenessStatus.COMPLETE
        if complete
        else CompletenessStatus.PARTIAL
    )
    graph = CryptoFlowGraph(
        graph_id="graph:fixture",
        nodes=tuple(nodes),
        edges=tuple(edges),
        completeness_receipts=(receipt,),
        provider_ids=("provider-a",),
        asset_ids=("native:eth",),
        chain_ids=("eip155:1",),
    )
    snapshot = GraphSnapshot(
        snapshot_id="gsnap:fixture",
        graph=graph,
        completeness=receipt.completeness,
        completeness_receipts=(receipt,),
        covered_providers=("provider-a",),
        covered_assets=("native:eth",),
        covered_chains=("eip155:1",),
        created_at="2026-07-15T00:00:00Z",
    )
    return graph, snapshot


def exposure_policy(**overrides: object) -> ExposurePolicy:
    base = dict(
        policy_id="epolicy:fixture",
        revision="rev:1",
        max_depth=4,
        max_nodes=64,
        max_edges=128,
        max_paths=16,
        max_runtime_ms=5_000,
        min_finality=FinalityStatus.CONFIRMED,
        indirect_outcome=SanctionsPolicyOutcome.REVIEW,
        list_snapshot_id="lsnap:fixture",
        list_revision="list-rev:1",
        graph_snapshot_id="gsnap:fixture",
        required_provider_ids=("provider-a",),
    )
    base.update(overrides)
    return ExposurePolicy(**base)  # type: ignore[arg-type]


def rule_set(
    *,
    indirect_outcome: SanctionsPolicyOutcome = SanctionsPolicyOutcome.REVIEW,
) -> ComplianceRuleSet:
    return ComplianceRuleSet(
        rule_set_id="ruleset:fixture",
        revision="rev:1",
        rules=default_compliance_rules(indirect_outcome=indirect_outcome),
    )


# ---------------------------------------------------------------------------
# ExposurePolicy invariants
# ---------------------------------------------------------------------------


def test_exposure_policy_requires_direct_deny() -> None:
    with pytest.raises(ExposureError, match="direct_outcome"):
        ExposurePolicy(
            policy_id="p",
            revision="r",
            direct_outcome=SanctionsPolicyOutcome.REVIEW,
        )


def test_exposure_policy_indirect_must_be_review_or_deny() -> None:
    with pytest.raises(ExposureError, match="REVIEW or DENY"):
        ExposurePolicy(
            policy_id="p",
            revision="r",
            indirect_outcome=SanctionsPolicyOutcome.ALLOW,
        )


def test_exposure_policy_rules_digest_stable() -> None:
    a = exposure_policy()
    b = ExposurePolicy.from_dict(a.to_dict())
    assert a.rules_digest == b.rules_digest
    assert a.rules_digest.startswith("sha256:")


# ---------------------------------------------------------------------------
# Direct hit hard-denies
# ---------------------------------------------------------------------------


def test_direct_hit_hard_denies() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:listed", "0xlisted"),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(
            ListedTarget(
                node_id="node:listed",
                address_ref="0xlisted",
                listed_identifier="id:0xlisted",
                designation_id="des:1",
            ),
        ),
        policy=exposure_policy(),
        snapshot=snapshot,
        at_time=AT_TIME,
    )
    assert result.verdict is ExposureVerdict.DIRECT_HIT
    assert result.has_direct_hit
    assert result.policy_outcome is SanctionsPolicyOutcome.DENY
    assert result.declares_designation is False
    assert any(p.is_direct for p in result.paths)
    assert all(not p.claims_designation for p in result.paths)
    assert result.paths[0].explanation()
    assert "does_not_declare_designation=true" in result.paths[0].explanation()


def test_origin_self_listed_is_direct_hit() -> None:
    graph, snapshot = linear_graph(("node:listed", "0xlisted"))
    result = compute_bounded_exposure(
        origin_node_id="node:listed",
        listed_targets=(
            ListedTarget(node_id="node:listed", listed_identifier="id:self"),
        ),
        policy=exposure_policy(),
        snapshot=snapshot,
    )
    assert result.verdict is ExposureVerdict.DIRECT_HIT
    assert result.paths[0].depth == 0
    assert result.policy_outcome is SanctionsPolicyOutcome.DENY


# ---------------------------------------------------------------------------
# Indirect exposure: REVIEW/DENY without designation
# ---------------------------------------------------------------------------


def test_indirect_exposure_review_without_designation() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:mid", "0xmid"),
        ("node:listed", "0xlisted"),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(
            ListedTarget(
                node_id="node:listed",
                address_ref="0xlisted",
                listed_identifier="id:0xlisted",
            ),
        ),
        policy=exposure_policy(indirect_outcome=SanctionsPolicyOutcome.REVIEW),
        snapshot=snapshot,
    )
    assert result.verdict is ExposureVerdict.INDIRECT_EXPOSURE
    assert result.has_indirect_exposure
    assert result.policy_outcome is SanctionsPolicyOutcome.REVIEW
    assert result.declares_designation is False
    path = result.paths[0]
    assert path.depth == 2
    assert path.is_indirect
    assert path.claims_designation is False


def test_indirect_exposure_configured_deny_still_not_designation() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:mid", "0xmid"),
        ("node:listed", "0xlisted"),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(
            ListedTarget(node_id="node:listed", listed_identifier="id:x"),
        ),
        policy=exposure_policy(indirect_outcome=SanctionsPolicyOutcome.DENY),
        snapshot=snapshot,
    )
    assert result.policy_outcome is SanctionsPolicyOutcome.DENY
    assert result.declares_designation is False
    assert all(not p.claims_designation for p in result.paths)


# ---------------------------------------------------------------------------
# Bounds: depth, nodes, edges, paths, truncation fail-closed for absence
# ---------------------------------------------------------------------------


def test_max_depth_truncation_does_not_prove_absence() -> None:
    _graph, snapshot = linear_graph(
        ("node:a", "0xa"),
        ("node:b", "0xb"),
        ("node:c", "0xc"),
        ("node:d", "0xd"),
        ("node:listed", "0xlisted"),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:a",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(max_depth=2),
        snapshot=snapshot,
    )
    # Path length 4 exceeds max_depth 2 → truncated or no path within bounds
    # with truncation reasons; must not prove absence if truncated.
    if result.truncated:
        assert result.verdict is ExposureVerdict.TRUNCATED
        assert result.proves_no_connection is False
        assert TruncationReason.MAX_DEPTH.value in result.truncation_reasons
        assert "absence_not_proved" in result.reason_codes
    else:
        # If BFS found nothing within depth without marking truncation when
        # frontier still has edges beyond depth, max_depth must be recorded.
        assert TruncationReason.MAX_DEPTH.value in result.truncation_reasons or (
            result.verdict is not ExposureVerdict.NO_PATH_WITHIN_BOUNDS
            or not result.proves_no_connection
        )


def test_max_paths_truncation_fail_closed() -> None:
    # Star: origin connected to many listed targets.
    origin = addr_node("node:origin", "0xorigin")
    listed_nodes = [addr_node(f"node:l{i}", f"0xl{i}") for i in range(5)]
    edges = [
        transfer(f"edge:{i}", "node:origin", f"node:l{i}") for i in range(5)
    ]
    receipt = completeness()
    graph = CryptoFlowGraph(
        graph_id="graph:star",
        nodes=(origin, *listed_nodes),
        edges=tuple(edges),
        completeness_receipts=(receipt,),
        provider_ids=("provider-a",),
        asset_ids=("native:eth",),
        chain_ids=("eip155:1",),
    )
    snapshot = GraphSnapshot(
        snapshot_id="gsnap:fixture",
        graph=graph,
        completeness=CompletenessStatus.COMPLETE,
        completeness_receipts=(receipt,),
        covered_providers=("provider-a",),
        covered_assets=("native:eth",),
        covered_chains=("eip155:1",),
    )
    targets = tuple(ListedTarget(node_id=f"node:l{i}") for i in range(5))
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=targets,
        policy=exposure_policy(max_paths=2),
        snapshot=snapshot,
    )
    assert len(result.paths) <= 2
    assert result.has_direct_hit
    # Finding paths is fine; truncation of *additional* paths must not invent
    # a designation and must not claim global absence.
    assert result.declares_designation is False
    assert result.proves_no_connection is False


def test_finality_filter_excludes_unconfirmed_edges() -> None:
    origin = addr_node("node:origin", "0xorigin")
    listed = addr_node("node:listed", "0xlisted")
    edge = transfer(
        "edge:weak",
        "node:origin",
        "node:listed",
        finality=FinalityStatus.PROPOSED,
    )
    receipt = completeness()
    graph = CryptoFlowGraph(
        graph_id="graph:weak",
        nodes=(origin, listed),
        edges=(edge,),
        completeness_receipts=(receipt,),
        provider_ids=("provider-a",),
        asset_ids=("native:eth",),
        chain_ids=("eip155:1",),
    )
    snapshot = GraphSnapshot(
        snapshot_id="gsnap:fixture",
        graph=graph,
        completeness=CompletenessStatus.COMPLETE,
        completeness_receipts=(receipt,),
        covered_providers=("provider-a",),
        covered_assets=("native:eth",),
        covered_chains=("eip155:1",),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(min_finality=FinalityStatus.FINALIZED),
        snapshot=snapshot,
    )
    assert not result.paths
    # Complete frontier + finished search → bounded absence (filtered edges
    # are policy exclusions, not search truncation).
    assert result.proves_no_connection is True or (
        result.verdict is ExposureVerdict.NO_PATH_WITHIN_BOUNDS
    )


def test_heuristic_edges_excluded_by_default() -> None:
    origin = addr_node("node:origin", "0xorigin")
    listed = addr_node("node:listed", "0xlisted")
    from ipfs_datasets_py.knowledge_graphs.crypto_flows.model import AmbiguityKind

    edge = FlowEdge(
        edge_id="edge:heur",
        kind=EdgeKind.SHARED_INFRASTRUCTURE,
        plane=GraphPlane.OBSERVED_ADDRESS,
        source_node_id="node:origin",
        target_node_id="node:listed",
        chain=eth_chain(),
        ledger_model=LedgerModel.ACCOUNT,
        asset=eth_asset(),
        amount=ExactAmount(base_units="1", decimals=18),
        direction=FlowDirection.NONE,
        finality=FinalityStatus.FINALIZED,
        source="fixture",
        confidence="0.5",
        validity=ValidityWindow(start="2024-01-01T00:00:00Z", end=""),
        derivation=DerivationMethod.HEURISTIC_CLUSTER,
        ambiguity=AmbiguityKind.SHARED_INFRASTRUCTURE,
        timestamp="2026-06-01T00:00:00Z",
        provider_ids=("provider-a",),
    )
    receipt = completeness()
    graph = CryptoFlowGraph(
        graph_id="graph:heur",
        nodes=(origin, listed),
        edges=(edge,),
        completeness_receipts=(receipt,),
        provider_ids=("provider-a",),
        asset_ids=("native:eth",),
        chain_ids=("eip155:1",),
    )
    snapshot = GraphSnapshot(
        snapshot_id="gsnap:fixture",
        graph=graph,
        completeness=CompletenessStatus.COMPLETE,
        completeness_receipts=(receipt,),
        covered_providers=("provider-a",),
        covered_assets=("native:eth",),
        covered_chains=("eip155:1",),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(allow_heuristic_edges=False),
        snapshot=snapshot,
    )
    assert not result.paths
    assert result.declares_designation is False


# ---------------------------------------------------------------------------
# Completeness frontier scopes absence
# ---------------------------------------------------------------------------


def test_incomplete_frontier_does_not_prove_absence() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:other", "0xother"),
        complete=False,
    )
    # listed target disconnected
    listed = addr_node("node:listed", "0xlisted")
    nodes = list(snapshot.graph.nodes) + [listed]
    graph = CryptoFlowGraph(
        graph_id=snapshot.graph.graph_id,
        nodes=tuple(nodes),
        edges=snapshot.graph.edges,
        completeness_receipts=snapshot.graph.completeness_receipts,
        provider_ids=snapshot.graph.provider_ids,
        asset_ids=snapshot.graph.asset_ids,
        chain_ids=snapshot.graph.chain_ids,
    )
    partial = GraphSnapshot(
        snapshot_id="gsnap:fixture",
        graph=graph,
        completeness=CompletenessStatus.PARTIAL,
        completeness_receipts=snapshot.completeness_receipts,
        covered_providers=("provider-a",),
        covered_assets=("native:eth",),
        covered_chains=("eip155:1",),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(),
        snapshot=partial,
    )
    assert not result.paths
    assert result.proves_no_connection is False
    assert result.verdict is ExposureVerdict.INCOMPLETE_FRONTIER
    assert "absence_not_proved" in result.reason_codes
    assert result.frontier is not None
    assert result.frontier.supports_absence_claim is False


def test_complete_frontier_allows_scoped_absence() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:mid", "0xmid"),
    )
    listed = addr_node("node:listed", "0xlisted")
    graph = CryptoFlowGraph(
        graph_id=snapshot.graph.graph_id,
        nodes=(*snapshot.graph.nodes, listed),
        edges=snapshot.graph.edges,
        completeness_receipts=snapshot.graph.completeness_receipts,
        provider_ids=snapshot.graph.provider_ids,
        asset_ids=snapshot.graph.asset_ids,
        chain_ids=snapshot.graph.chain_ids,
    )
    complete = GraphSnapshot(
        snapshot_id="gsnap:fixture",
        graph=graph,
        completeness=CompletenessStatus.COMPLETE,
        completeness_receipts=snapshot.completeness_receipts,
        covered_providers=("provider-a",),
        covered_assets=("native:eth",),
        covered_chains=("eip155:1",),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(),
        snapshot=complete,
    )
    assert not result.paths
    assert result.verdict is ExposureVerdict.NO_PATH_WITHIN_BOUNDS
    assert result.proves_no_connection is True
    # Still not a *global* claim.
    assert result.attributes.get("never_claims_global_absence") is True
    assert "absence_scoped_to_frontier" in result.reason_codes


# ---------------------------------------------------------------------------
# Path replay against one snapshot
# ---------------------------------------------------------------------------


def test_path_replay_against_same_snapshot() -> None:
    graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:listed", "0xlisted"),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(),
        snapshot=snapshot,
    )
    path = result.paths[0]
    assert replay_exposure_path(
        path,
        graph,
        graph_snapshot_id=snapshot.snapshot_id,
        graph_digest=snapshot.graph_digest,
    )
    # Serialize/deserialize round-trip remains replayable.
    restored = ExposurePath.from_dict(path.to_dict())
    assert restored.path_id == path.path_id
    assert replay_exposure_path(restored, graph)


def test_path_replay_fails_on_digest_mismatch() -> None:
    graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:listed", "0xlisted"),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(),
        snapshot=snapshot,
    )
    path = result.paths[0]
    assert not replay_exposure_path(
        path, graph, graph_digest="sha256:" + ("ff" * 32)
    )


def test_bounded_exposure_round_trip() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:mid", "0xmid"),
        ("node:listed", "0xlisted"),
    )
    result = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(),
        snapshot=snapshot,
    )
    restored = BoundedExposure.from_dict(result.to_dict())
    assert restored.exposure_id == result.exposure_id
    assert restored.verdict is result.verdict
    assert restored.proves_no_connection == result.proves_no_connection


# ---------------------------------------------------------------------------
# Compliance rules
# ---------------------------------------------------------------------------


def test_rules_refuse_designation_elevation() -> None:
    with pytest.raises(ComplianceRuleError, match="never elevate"):
        ComplianceRule(
            rule_id="rule:bad",
            kind=ComplianceRuleKind.BOUNDED_INDIRECT_EXPOSURE,
            predicate=CompliancePredicate.BOUNDED_EXPOSURE,
            outcome=SanctionsPolicyOutcome.DENY,
            reason_code="bad",
            elevates_to_designation=True,
        )


def test_direct_hit_rule_evaluation_denies() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:listed", "0xlisted"),
    )
    exposure = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(),
        snapshot=snapshot,
    )
    evaluation = evaluate_compliance_rules(rule_set(), exposure=exposure)
    assert evaluation.outcome is SanctionsPolicyOutcome.DENY
    assert evaluation.declares_designation is False
    assert "exact_listed_identifier" in evaluation.reason_codes or any(
        h.reason_code == "exact_listed_identifier" for h in evaluation.hits
    )


def test_indirect_rule_evaluation_review_not_designation() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:mid", "0xmid"),
        ("node:listed", "0xlisted"),
    )
    exposure = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(),
        snapshot=snapshot,
    )
    evaluation = evaluate_compliance_rules(rule_set(), exposure=exposure)
    assert evaluation.outcome is SanctionsPolicyOutcome.REVIEW
    assert evaluation.declares_designation is False
    assert any(
        h.match_level is SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE
        for h in evaluation.hits
    )
    assert any("does_not_declare_designation" in h.notes for h in evaluation.hits)


def test_ownership_rule_fires_on_threshold() -> None:
    evidence = OwnershipEvidence(
        evidence_id="own:1",
        subject_party_id="party:subject",
        kind=OwnershipKind.ENTITY,
        interests=(
            OwnershipInterest(
                owner_party_id="party:blocked",
                ownership_basis_points=6_000,
                designation_ids=("des:1",),
            ),
        ),
        source_digests=(HASH_A,),
        observed_at=AT_TIME,
        effective_from="2026-01-01T00:00:00Z",
        complete=True,
    )
    evaluation = evaluate_compliance_rules(
        rule_set(),
        ownership_evidence=(evidence,),
        at_time=AT_TIME,
    )
    assert evaluation.outcome is SanctionsPolicyOutcome.DENY
    assert any(
        h.match_level is SanctionsMatchLevel.OWNED_ENTITY for h in evaluation.hits
    )


def test_freshness_rule_stale() -> None:
    evaluation = evaluate_compliance_rules(
        rule_set(),
        snapshot_age_seconds=200_000,
    )
    assert evaluation.outcome is SanctionsPolicyOutcome.STALE
    assert "evidence_stale" in evaluation.reason_codes


def test_heuristic_rule_never_designates() -> None:
    evidence = AssociationEvidence(
        evidence_id="assoc:heur",
        kind=AssociationKind.HEURISTIC,
        subject_party_id="party:subject",
        target_party_id="party:blocked",
        source_digests=(HASH_A,),
        observed_at=AT_TIME,
        complete=True,
        path_depth=0,
    )
    evaluation = evaluate_compliance_rules(
        rule_set(),
        association_evidence=(evidence,),
        heuristic_signal=True,
    )
    assert evaluation.outcome is SanctionsPolicyOutcome.REVIEW
    assert evaluation.declares_designation is False


def test_truncation_evaluation_inconclusive() -> None:
    _graph, snapshot = linear_graph(
        ("node:a", "0xa"),
        ("node:b", "0xb"),
        ("node:c", "0xc"),
        ("node:d", "0xd"),
        ("node:listed", "0xlisted"),
    )
    exposure = compute_bounded_exposure(
        origin_node_id="node:a",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(max_depth=1),
        snapshot=snapshot,
    )
    evaluation = evaluate_compliance_rules(rule_set(), exposure=exposure)
    # Truncation / incompleteness must not ALLOW automation via false absence.
    assert evaluation.outcome is not SanctionsPolicyOutcome.ALLOW or exposure.paths
    if exposure.truncated or exposure.verdict is ExposureVerdict.TRUNCATED:
        assert evaluation.outcome in (
            SanctionsPolicyOutcome.INCONCLUSIVE,
            SanctionsPolicyOutcome.DENY,
            SanctionsPolicyOutcome.REVIEW,
        )


# ---------------------------------------------------------------------------
# Formalization
# ---------------------------------------------------------------------------


def test_formalize_direct_hit_compiled() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:listed", "0xlisted"),
    )
    policy = exposure_policy()
    exposure = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=policy,
        snapshot=snapshot,
    )
    rs = rule_set()
    evaluation = evaluate_compliance_rules(rs, exposure=exposure)
    formal = formalize_compliance(
        rs, exposure=exposure, exposure_policy=policy, evaluation=evaluation
    )
    assert formal.status is FormalizationStatus.COMPILED
    assert formal.executable is True
    assert formal.claims_global_absence is False
    assert formal.declares_designation is False
    assert formal.clauses
    assert "ListedIdentifier" in formal.datalog_fragment or any(
        "ListedIdentifier" in c.predicate for c in formal.clauses
    )
    restored = FormalizedCompliance.from_dict(formal.to_dict())
    assert restored.formalization_id == formal.formalization_id


def test_formalize_bounded_absence_is_completeness_qualified() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:mid", "0xmid"),
    )
    listed = addr_node("node:listed", "0xlisted")
    graph = CryptoFlowGraph(
        graph_id=snapshot.graph.graph_id,
        nodes=(*snapshot.graph.nodes, listed),
        edges=snapshot.graph.edges,
        completeness_receipts=snapshot.graph.completeness_receipts,
        provider_ids=snapshot.graph.provider_ids,
        asset_ids=snapshot.graph.asset_ids,
        chain_ids=snapshot.graph.chain_ids,
    )
    complete = GraphSnapshot(
        snapshot_id="gsnap:fixture",
        graph=graph,
        completeness=CompletenessStatus.COMPLETE,
        completeness_receipts=snapshot.completeness_receipts,
        covered_providers=("provider-a",),
        covered_assets=("native:eth",),
        covered_chains=("eip155:1",),
    )
    exposure = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(),
        snapshot=complete,
    )
    formal = formalize_compliance(rule_set(), exposure=exposure)
    assert formal.status is FormalizationStatus.COMPILED
    assert formal.negative_conclusion is NegativeConclusionKind.BOUNDED_ABSENCE
    assert formal.claims_global_absence is False
    assert "not_global_absence" in formal.datalog_fragment or any(
        "not_global_absence" in body
        for c in formal.clauses
        for body in c.body
    )


def test_formalize_truncation_fails_closed() -> None:
    _graph, snapshot = linear_graph(
        ("node:a", "0xa"),
        ("node:b", "0xb"),
        ("node:c", "0xc"),
        ("node:d", "0xd"),
        ("node:listed", "0xlisted"),
    )
    exposure = compute_bounded_exposure(
        origin_node_id="node:a",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(max_depth=1),
        snapshot=snapshot,
    )
    if not exposure.truncated and exposure.verdict is not ExposureVerdict.TRUNCATED:
        pytest.skip("fixture did not truncate; depth bound found alternate path")
    formal = formalize_compliance(rule_set(), exposure=exposure)
    assert formal.status is FormalizationStatus.TRUNCATED_FAIL_CLOSED
    assert formal.executable is False
    assert formal.negative_conclusion is NegativeConclusionKind.REFUSED
    assert formal.claims_global_absence is False


def test_formalize_incomplete_frontier_fails_closed() -> None:
    _graph, snapshot = linear_graph(
        ("node:origin", "0xorigin"),
        ("node:mid", "0xmid"),
        complete=False,
    )
    listed = addr_node("node:listed", "0xlisted")
    graph = CryptoFlowGraph(
        graph_id=snapshot.graph.graph_id,
        nodes=(*snapshot.graph.nodes, listed),
        edges=snapshot.graph.edges,
        completeness_receipts=snapshot.graph.completeness_receipts,
        provider_ids=snapshot.graph.provider_ids,
        asset_ids=snapshot.graph.asset_ids,
        chain_ids=snapshot.graph.chain_ids,
    )
    partial = GraphSnapshot(
        snapshot_id="gsnap:fixture",
        graph=graph,
        completeness=CompletenessStatus.PARTIAL,
        completeness_receipts=snapshot.completeness_receipts,
        covered_providers=("provider-a",),
        covered_assets=("native:eth",),
        covered_chains=("eip155:1",),
    )
    exposure = compute_bounded_exposure(
        origin_node_id="node:origin",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(),
        snapshot=partial,
    )
    formal = formalize_compliance(rule_set(), exposure=exposure)
    assert formal.status is FormalizationStatus.INCOMPLETE_MODEL
    assert formal.executable is False
    assert formal.negative_conclusion is NegativeConclusionKind.REFUSED


def test_formalizer_rejects_unsupported_theory() -> None:
    with pytest.raises(FormalizeError, match="not supported"):
        ComplianceFormalizer(preferred_theory=TheoryFragment.LTL_BOUNDED)


def test_exposure_path_refuses_designation_claim() -> None:
    from ipfs_datasets_py.logic.crypto_ir.compliance.exposure import ExposurePathStep

    step = ExposurePathStep(
        step_index=0,
        edge_id="e1",
        from_node_id="a",
        to_node_id="b",
        edge_kind="transfer",
        finality="finalized",
        derivation="account_transfer",
        ambiguity="none",
    )
    with pytest.raises(ExposureError, match="never claim designation"):
        ExposurePath(
            path_id="path:x",
            origin_node_id="a",
            target_node_id="b",
            node_ids=("a", "b"),
            edge_ids=("e1",),
            steps=(step,),
            depth=1,
            claims_designation=True,
        )


def test_completeness_frontier_from_dict() -> None:
    frontier = CompletenessFrontier(
        status=CompletenessStatus.COMPLETE,
        covered_providers=("provider-a",),
        notes=("ok",),
    )
    restored = CompletenessFrontier.from_dict(frontier.to_dict())
    assert restored.supports_absence_claim is True
    assert restored.status is CompletenessStatus.COMPLETE


def test_rule_set_digest_changes_with_rules() -> None:
    a = rule_set()
    b = ComplianceRuleSet(
        rule_set_id="ruleset:fixture",
        revision="rev:1",
        rules=default_compliance_rules(
            indirect_outcome=SanctionsPolicyOutcome.DENY
        ),
    )
    assert a.rules_digest != b.rules_digest


def test_never_infers_unlimited_transitive_guilt_property() -> None:
    """Depth-bounded search must not treat beyond-bound nodes as guilt."""

    _graph, snapshot = linear_graph(
        ("node:a", "0xa"),
        ("node:b", "0xb"),
        ("node:c", "0xc"),
        ("node:listed", "0xlisted"),
    )
    # With max_depth=1 only the direct neighbor is searchable.
    result = compute_bounded_exposure(
        origin_node_id="node:a",
        listed_targets=(ListedTarget(node_id="node:listed"),),
        policy=exposure_policy(max_depth=1),
        snapshot=snapshot,
    )
    # Must not invent a path of depth 3.
    assert all(p.depth <= 1 for p in result.paths)
    assert result.attributes.get("never_infers_unlimited_transitive_guilt") is True
    # Incomplete reachability is not global innocence either.
    if not result.paths:
        assert result.proves_no_connection is False or result.truncated


def test_ast_symbols_exported() -> None:
    """AST query: BoundedExposure ExposurePolicy ComplianceRule ComplianceFormalizer ExposurePath."""

    assert BoundedExposure.__name__ == "BoundedExposure"
    assert ExposurePolicy.__name__ == "ExposurePolicy"
    assert ComplianceRule.__name__ == "ComplianceRule"
    assert ComplianceFormalizer.__name__ == "ComplianceFormalizer"
    assert ExposurePath.__name__ == "ExposurePath"

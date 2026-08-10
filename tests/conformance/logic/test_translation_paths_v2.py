"""Conformance: composed translation paths (LogicTranslationGraph@3).

Acceptance (LFP2-021):

* All registered paths are feature-total and loss-receipted
* Protocol equations, roles/rules, channels, attacker semantics, and query
  identities remain dialect-specific
* Target theories are compilation candidates until official kernels accept them

Interfaces: LogicTranslationGraph@3, ProtocolTargetTranslationEdges@1,
KernelTargetCompiler@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.translations.catalog import (
    FAMILY_HYPERPROPERTY,
    FAMILY_KERNEL_TARGET,
    FAMILY_POLICY_MODAL,
    FAMILY_PROGRAM,
    FAMILY_PROTOCOL_TARGET,
    FAMILY_STATE_TEMPORAL,
    JOINED_FAMILY_KEYS,
    LOGIC_TRANSLATION_GRAPH_INTERFACE,
    LogicTranslationGraph,
    LogicTranslationGraphError,
    build_joined_planner,
    build_logic_translation_graph,
    kernel_compiler_from_graph,
    logic_translation_contracts,
    plan_feature_total_path,
)
from ipfs_datasets_py.logic.translations.kernel_targets import (
    KERNEL_TARGET_COMPILER_INTERFACE,
    CompilationStatus,
    KernelTargetKind,
    TargetTheoryArtifact,
)
from ipfs_datasets_py.logic.translations.planner import (
    FeatureSet,
    TranslationPathPlannerError,
    TranslationPathRequest,
    path_is_feature_total,
)
from ipfs_datasets_py.logic.translations.protocol_targets import (
    FEAT_APPLIED_PI_PROCESS,
    FEAT_ATTACKER_DOLEV_YAO,
    FEAT_COMPUTATIONAL_SOUNDNESS,
    FEAT_LEMMA_IDENTITY,
    FEAT_MULTISET_FACTS,
    FEAT_MULTISET_RULES,
    FEAT_PERFECT_CRYPTO,
    FEAT_PROTOCOL_AUTHENTICATION,
    FEAT_PROTOCOL_CHANNELS,
    FEAT_PROTOCOL_CLAIMS,
    FEAT_PROTOCOL_EQUATIONS,
    FEAT_PROTOCOL_EVENTS,
    FEAT_PROTOCOL_PROCESSES,
    FEAT_PROTOCOL_REACHABILITY,
    FEAT_PROTOCOL_ROLES,
    FEAT_PROTOCOL_SECRECY,
    FEAT_PUBLIC_CHANNEL,
    FEAT_QUERY_IDENTITY,
    PROTOCOL_TARGET_EDGES_INTERFACE,
    SOURCE_SYMBOLIC_PROTOCOL,
    TARGET_PROVERIF,
    TARGET_TAMARIN,
    ProtocolDialect,
    ProtocolTargetTranslationEdges,
    lower_protocol_obligation,
    ProtocolObligation,
    ObligationKind,
)


# ---------------------------------------------------------------------------
# Graph surface
# ---------------------------------------------------------------------------


def test_logic_translation_graph_interface() -> None:
    graph = build_logic_translation_graph()
    assert graph.interface == LOGIC_TRANSLATION_GRAPH_INTERFACE
    assert graph.interface == "LogicTranslationGraph@3"
    assert graph.graph_content_id.startswith("bafkrei")
    assert len(graph) > 0
    assert graph.all_paths_loss_receipted()


def test_graph_joins_all_required_families() -> None:
    graph = LogicTranslationGraph.reviewed()
    keys = {bundle.family_key for bundle in graph.families}
    assert keys == set(JOINED_FAMILY_KEYS)
    for key in (
        FAMILY_PROGRAM,
        FAMILY_STATE_TEMPORAL,
        FAMILY_POLICY_MODAL,
        FAMILY_HYPERPROPERTY,
        FAMILY_PROTOCOL_TARGET,
        FAMILY_KERNEL_TARGET,
    ):
        bundle = graph.family(key)
        assert bundle.edge_count > 0
        assert bundle.all_loss_receipted
        assert bundle.loss_ids
        assert bundle.contract_ids


def test_all_registered_contracts_have_features_and_losses() -> None:
    graph = build_logic_translation_graph()
    graph.assert_all_registered_paths_ready()
    for contract in graph.contracts:
        assert contract.feature_preconditions or contract.unsupported_constructs
        # Authority never exceeds what preservation allows pre-kernel.
        if contract.target.family_id in {"lean", "rocq", "isabelle"}:
            assert contract.authority_ceiling is not EvidenceAuthority.AUTHORITATIVE


def test_protocol_family_is_dialect_specific() -> None:
    graph = build_logic_translation_graph()
    protocol = graph.family(FAMILY_PROTOCOL_TARGET)
    assert protocol.interface == PROTOCOL_TARGET_EDGES_INTERFACE
    catalog = ProtocolTargetTranslationEdges.reviewed()
    proverif = catalog.get("symbolic_protocol_to_proverif_applied_pi")
    tamarin = catalog.get("symbolic_protocol_to_tamarin_multiset_rewriting")

    # Equations / roles-rules / channels / attacker / queries remain dialect-specific.
    assert proverif.dialect is ProtocolDialect.PROVERIF_APPLIED_PI
    assert tamarin.dialect is ProtocolDialect.TAMARIN_MULTISET_REWRITING
    assert set(proverif.dialect_receipt.equations) != set(
        tamarin.dialect_receipt.equations
    ) or set(proverif.dialect_receipt.roles_or_rules).isdisjoint(
        set(tamarin.dialect_receipt.roles_or_rules)
    )
    assert set(proverif.dialect_receipt.query_identities).isdisjoint(
        set(tamarin.dialect_receipt.query_identities)
    )
    assert (
        proverif.dialect_receipt.query_identity_kind
        is not tamarin.dialect_receipt.query_identity_kind
    )
    assert (
        proverif.dialect_receipt.role_rule_kind
        is not tamarin.dialect_receipt.role_rule_kind
    )
    # Both declare attacker semantics explicitly.
    assert proverif.dialect_receipt.attacker_assumptions
    assert tamarin.dialect_receipt.attacker_assumptions
    assert proverif.dialect_receipt.channels
    assert tamarin.dialect_receipt.channels


def test_protocol_paths_are_feature_total_and_loss_receipted() -> None:
    graph = build_logic_translation_graph()
    proverif_features = (
        FEAT_PROTOCOL_ROLES,
        FEAT_PROTOCOL_PROCESSES,
        FEAT_PROTOCOL_EQUATIONS,
        FEAT_PROTOCOL_CHANNELS,
        FEAT_PROTOCOL_EVENTS,
        FEAT_PROTOCOL_CLAIMS,
        FEAT_ATTACKER_DOLEV_YAO,
        FEAT_PERFECT_CRYPTO,
        FEAT_PUBLIC_CHANNEL,
        FEAT_APPLIED_PI_PROCESS,
        FEAT_QUERY_IDENTITY,
        FEAT_PROTOCOL_SECRECY,
        FEAT_PROTOCOL_AUTHENTICATION,
    )
    receipt = graph.plan(
        TranslationPathRequest(
            source_family_id=SOURCE_SYMBOLIC_PROTOCOL,
            target_family_id=TARGET_PROVERIF,
            features=FeatureSet.from_features(proverif_features),
        )
    )
    validation = graph.validate_path_receipt(receipt)
    assert validation.feature_total
    assert validation.loss_receipted
    assert validation.accepted
    assert validation.loss_ids

    tamarin_features = (
        FEAT_PROTOCOL_ROLES,
        FEAT_PROTOCOL_EQUATIONS,
        FEAT_PROTOCOL_CHANNELS,
        FEAT_PROTOCOL_EVENTS,
        FEAT_PROTOCOL_CLAIMS,
        FEAT_ATTACKER_DOLEV_YAO,
        FEAT_PERFECT_CRYPTO,
        FEAT_PUBLIC_CHANNEL,
        FEAT_MULTISET_RULES,
        FEAT_MULTISET_FACTS,
        FEAT_LEMMA_IDENTITY,
        FEAT_PROTOCOL_SECRECY,
        FEAT_PROTOCOL_AUTHENTICATION,
        FEAT_PROTOCOL_REACHABILITY,
    )
    receipt_tm = plan_feature_total_path(
        source_family_id=SOURCE_SYMBOLIC_PROTOCOL,
        target_family_id=TARGET_TAMARIN,
        features=tamarin_features,
        graph=graph,
    )
    assert receipt_tm.edge_contract_ids
    assert graph.validate_path_receipt(receipt_tm).accepted


def test_unsupported_protocol_composition_fails_before_dispatch() -> None:
    graph = build_logic_translation_graph()
    # Computational soundness is unsupported on both dialects.
    with pytest.raises((LogicTranslationGraphError, TranslationPathPlannerError)):
        graph.plan(
            TranslationPathRequest(
                source_family_id=SOURCE_SYMBOLIC_PROTOCOL,
                target_family_id=TARGET_PROVERIF,
                features=FeatureSet.from_features(
                    (
                        FEAT_PROTOCOL_ROLES,
                        FEAT_PROTOCOL_PROCESSES,
                        FEAT_PROTOCOL_EQUATIONS,
                        FEAT_PROTOCOL_CHANNELS,
                        FEAT_PROTOCOL_EVENTS,
                        FEAT_PROTOCOL_CLAIMS,
                        FEAT_ATTACKER_DOLEV_YAO,
                        FEAT_PERFECT_CRYPTO,
                        FEAT_PUBLIC_CHANNEL,
                        FEAT_APPLIED_PI_PROCESS,
                        FEAT_QUERY_IDENTITY,
                        FEAT_PROTOCOL_SECRECY,
                        FEAT_PROTOCOL_AUTHENTICATION,
                        FEAT_COMPUTATIONAL_SOUNDNESS,
                    )
                ),
            )
        )


def test_kernel_targets_remain_candidates_until_acceptance() -> None:
    graph = build_logic_translation_graph()
    compiler = kernel_compiler_from_graph(graph)
    assert compiler.interface == KERNEL_TARGET_COMPILER_INTERFACE

    theory = TargetTheoryArtifact.from_statements(
        theory_id="theory:join-candidate",
        name="JoinCandidate",
        theorems=(
            {
                "theorem_id": "thm:join",
                "theorem_name": "join_soundness",
                "statement": "translation preserves validity under assumptions",
            },
        ),
        imports=("Init", "Main"),
        axioms=("reviewed_fragment",),
    )
    for kind in (
        KernelTargetKind.LEAN,
        KernelTargetKind.ROCQ,
        KernelTargetKind.ISABELLE,
    ):
        candidate = compiler.compile(
            theory,
            kernel_target=kind,
            environment={
                "environment_id": f"env:{kind.value}:join",
                "kernel_target": kind.value,
                "toolchain_id": kind.value,
                "toolchain_version": "pinned",
                "session_or_package": "JoinCandidate",
            },
        )
        assert candidate.status is CompilationStatus.CANDIDATE
        assert candidate.kernel_accepted is False
        assert candidate.is_candidate
        assert candidate.imports
        assert candidate.axioms
        assert candidate.source_maps
        assert candidate.loss_ids
        assert "sorry" not in candidate.source
        # Kernel edges in the graph never claim authoritative theorem status.
        edge = graph.get(f"target_theory_to_{kind.value}")
        assert edge.authority_ceiling is not EvidenceAuthority.AUTHORITATIVE


def test_kernel_path_feature_total() -> None:
    graph = build_logic_translation_graph()
    features = (
        "feat_target_theory",
        "feat_imports",
        "feat_theorems",
        "feat_source_maps",
        "feat_kernel_candidate",
        "feat_lean",
    )
    contracts = [graph.get("target_theory_to_lean")]
    total, unhandled, hits = path_is_feature_total(contracts, features)
    assert total
    assert not unhandled
    assert not hits

    receipt = graph.plan(
        TranslationPathRequest(
            source_family_id="target_theory",
            target_family_id="lean",
            features=FeatureSet.from_features(features),
        )
    )
    assert graph.validate_path_receipt(receipt).accepted


def test_joined_planner_registers_all_contracts() -> None:
    planner = build_joined_planner()
    contracts = logic_translation_contracts()
    assert len(planner.registered_edges) == len(contracts)
    assert len(contracts) >= 20  # program+state+policy+hyper+protocol+kernel


def test_graph_round_trip() -> None:
    graph = build_logic_translation_graph()
    wire = graph.to_dict()
    restored = LogicTranslationGraph.from_dict(wire)
    assert restored.contract_ids() == graph.contract_ids()
    assert restored.graph_content_id == graph.graph_content_id
    assert restored.all_paths_loss_receipted()


def test_protocol_lowering_joins_graph_catalog() -> None:
    obligation = ProtocolObligation(
        obligation_id="obl:conformance:secrecy",
        kind=ObligationKind.SECRECY,
        features=(
            FEAT_PROTOCOL_ROLES,
            FEAT_PROTOCOL_PROCESSES,
            FEAT_PROTOCOL_EQUATIONS,
            FEAT_PROTOCOL_CHANNELS,
            FEAT_PROTOCOL_EVENTS,
            FEAT_PROTOCOL_CLAIMS,
            FEAT_ATTACKER_DOLEV_YAO,
            FEAT_PERFECT_CRYPTO,
            FEAT_PUBLIC_CHANNEL,
            FEAT_APPLIED_PI_PROCESS,
            FEAT_QUERY_IDENTITY,
            FEAT_PROTOCOL_SECRECY,
            FEAT_PROTOCOL_AUTHENTICATION,
        ),
        roles=("role:initiator",),
        equations=("eq:sdec_senc",),
        channels=("chan:public",),
        claims=("claim:secrecy",),
        query_identities=("query:secrecy",),
        attacker_assumptions=("attacker:dolev_yao",),
    )
    result = lower_protocol_obligation(
        obligation, "symbolic_protocol_to_proverif_applied_pi"
    )
    assert result.status.value == "supported"
    assert result.loss_ids
    assert result.dialect_receipt is not None
    # Dialect receipt axes all present.
    receipt = result.dialect_receipt
    assert receipt.equations
    assert receipt.roles_or_rules
    assert receipt.channels
    assert receipt.attacker_assumptions
    assert receipt.query_identities


def test_program_path_still_reachable_on_composed_graph() -> None:
    graph = build_logic_translation_graph()
    features = (
        "feat_program_contracts",
        "feat_program_commands",
        "feat_pure_assertions",
        "feat_frame_conditions",
        "feat_equality",
        "feat_arithmetic",
        "feat_quantifiers",
    )
    receipt = graph.plan(
        TranslationPathRequest(
            source_family_id="program",
            target_family_id="first_order",
            features=FeatureSet.from_features(features),
        )
    )
    assert "program_to_first_order" in receipt.edge_contract_ids
    assert graph.validate_path_receipt(receipt).accepted

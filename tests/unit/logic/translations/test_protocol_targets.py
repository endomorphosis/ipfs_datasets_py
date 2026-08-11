"""Unit tests for ProtocolTargetTranslationEdges@1 and KernelTargetCompiler@2."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import PreservationRelation
from ipfs_datasets_py.logic.translations.kernel_targets import (
    KERNEL_TARGET_COMPILER_INTERFACE,
    KERNEL_TARGET_EDGES_INTERFACE,
    CompilationStatus,
    KernelCompilationCandidate,
    KernelTargetCompiler,
    KernelTargetKind,
    KernelTargetTranslationEdges,
    KernelTargetTranslationError,
    TargetTheoryArtifact,
    build_kernel_target_compiler,
    build_kernel_target_translation_edges,
    content_digest,
    is_official_kernel,
    kernel_target_translation_contracts,
    reject_trust_escapes,
    scan_trust_escapes,
)
from ipfs_datasets_py.logic.translations.protocol_targets import (
    DEFAULT_PROTOCOL_TARGET_TRANSLATION_EDGES,
    FEAT_APPLIED_PI_PROCESS,
    FEAT_ATTACKER_DOLEV_YAO,
    FEAT_COMPUTATIONAL_SOUNDNESS,
    FEAT_GLOBAL_STATE,
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
    AttackerSemantics,
    ChannelModel,
    EquationTheoryKind,
    LoweringStatus,
    ObligationKind,
    ProtocolDialect,
    ProtocolDialectReceipt,
    ProtocolLossKind,
    ProtocolObligation,
    ProtocolTargetTranslationEdges,
    ProtocolTargetTranslationError,
    QueryIdentityKind,
    RoleRuleKind,
    build_protocol_target_translation_edges,
    lower_protocol_obligation,
    plan_protocol_path,
    protocol_target_translation_contracts,
    require_dialect_receipt,
)


# ---------------------------------------------------------------------------
# Protocol fixtures
# ---------------------------------------------------------------------------


def _proverif_features() -> tuple[str, ...]:
    return (
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


def _tamarin_features() -> tuple[str, ...]:
    return (
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


def _secrecy_obligation(**overrides: object) -> ProtocolObligation:
    payload: dict[str, object] = {
        "obligation_id": "obl:protocol:secrecy",
        "kind": ObligationKind.SECRECY,
        "source_family_id": SOURCE_SYMBOLIC_PROTOCOL,
        "features": _proverif_features(),
        "roles": ("role:initiator", "role:responder"),
        "equations": ("eq:sdec_senc",),
        "channels": ("chan:public",),
        "claims": ("claim:secrecy_session_key",),
        "events": ("event:Commit", "event:Accept"),
        "query_identities": ("query:secrecy",),
        "attacker_assumptions": ("attacker:dolev_yao",),
        "symbols": ("sym_role", "sym_channel", "sym_query"),
    }
    payload.update(overrides)
    return ProtocolObligation(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Protocol target edges
# ---------------------------------------------------------------------------


def test_protocol_interface_and_reviewed_catalog() -> None:
    catalog = ProtocolTargetTranslationEdges.reviewed()
    assert catalog.interface == PROTOCOL_TARGET_EDGES_INTERFACE
    assert catalog.interface == "ProtocolTargetTranslationEdges@1"
    assert catalog.catalog_content_id.startswith("bafkrei")
    assert len(catalog) == 2
    assert set(catalog.edge_ids()) == set(DEFAULT_PROTOCOL_TARGET_TRANSLATION_EDGES)
    assert catalog.all_loss_receipted()


def test_protocol_edges_cover_proverif_and_tamarin() -> None:
    catalog = ProtocolTargetTranslationEdges.reviewed()
    proverif = catalog.by_dialect(ProtocolDialect.PROVERIF_APPLIED_PI)
    tamarin = catalog.by_dialect(ProtocolDialect.TAMARIN_MULTISET_REWRITING)
    assert len(proverif) == 1
    assert len(tamarin) == 1
    assert proverif[0].target_family_id == TARGET_PROVERIF
    assert tamarin[0].target_family_id == TARGET_TAMARIN
    assert proverif[0].source_family_id == SOURCE_SYMBOLIC_PROTOCOL
    assert tamarin[0].source_family_id == SOURCE_SYMBOLIC_PROTOCOL


def test_protocol_dialect_receipts_are_mandatory_and_specific() -> None:
    catalog = ProtocolTargetTranslationEdges.reviewed()
    for edge in catalog:
        receipt = edge.dialect_receipt
        assert receipt.equations
        assert receipt.roles_or_rules
        assert receipt.channels
        assert receipt.attacker_assumptions
        assert receipt.query_identities
        assert receipt.attacker_semantics is AttackerSemantics.DOLEV_YAO
        wire = receipt.to_dict()
        restored = ProtocolDialectReceipt.from_dict(wire)
        assert restored.dialect is receipt.dialect
        assert restored.query_identities == receipt.query_identities

    proverif = catalog.get("symbolic_protocol_to_proverif_applied_pi")
    assert proverif.dialect_receipt.role_rule_kind is RoleRuleKind.APPLIED_PI_PROCESS
    assert (
        proverif.dialect_receipt.query_identity_kind
        is QueryIdentityKind.PROVERIF_QUERY
    )

    tamarin = catalog.get("symbolic_protocol_to_tamarin_multiset_rewriting")
    assert tamarin.dialect_receipt.role_rule_kind is RoleRuleKind.MULTISET_RULE
    assert (
        tamarin.dialect_receipt.query_identity_kind is QueryIdentityKind.TAMARIN_LEMMA
    )
    # Query identities remain dialect-specific (never shared).
    assert set(proverif.dialect_receipt.query_identities).isdisjoint(
        set(tamarin.dialect_receipt.query_identities)
    )


def test_protocol_edges_are_loss_receipted() -> None:
    for edge in build_protocol_target_translation_edges():
        assert edge.is_loss_receipted
        assert edge.loss_ids
        assert any(
            loss.kind is not ProtocolLossKind.NONE for loss in edge.losses
        )
        assert edge.contract.assumptions.attacker_model
        assert edge.authority_ceiling is not EvidenceAuthority.AUTHORITATIVE
        assert edge.preservation is PreservationRelation.TRACE_PRESERVING


def test_protocol_dialect_mismatch_fails_closed() -> None:
    with pytest.raises(ProtocolTargetTranslationError):
        require_dialect_receipt(
            dialect=ProtocolDialect.PROVERIF_APPLIED_PI,
            equations=("eq:pairing",),
            equation_theory=EquationTheoryKind.FREE,
            role_rule_kind=RoleRuleKind.MULTISET_RULE,  # wrong for ProVerif
            roles_or_rules=("rule:Init",),
            channel_model=ChannelModel.PUBLIC_NETWORK,
            channels=("chan:public",),
            attacker_semantics=AttackerSemantics.DOLEV_YAO,
            attacker_assumptions=("attacker:dolev_yao",),
            query_identity_kind=QueryIdentityKind.PROVERIF_QUERY,
            query_identities=("query:secrecy",),
        )


def test_protocol_empty_axes_rejected() -> None:
    with pytest.raises(ProtocolTargetTranslationError, match="equations"):
        ProtocolDialectReceipt(
            dialect=ProtocolDialect.PROVERIF_APPLIED_PI,
            equations=(),
            equation_theory=EquationTheoryKind.FREE,
            role_rule_kind=RoleRuleKind.APPLIED_PI_PROCESS,
            roles_or_rules=("role:initiator",),
            channel_model=ChannelModel.PUBLIC_NETWORK,
            channels=("chan:public",),
            attacker_semantics=AttackerSemantics.DOLEV_YAO,
            attacker_assumptions=("attacker:dolev_yao",),
            query_identity_kind=QueryIdentityKind.PROVERIF_QUERY,
            query_identities=("query:secrecy",),
        )


def test_lower_supported_proverif_obligation() -> None:
    result = lower_protocol_obligation(
        _secrecy_obligation(),
        "symbolic_protocol_to_proverif_applied_pi",
    )
    assert result.status is LoweringStatus.SUPPORTED
    assert result.dialect is ProtocolDialect.PROVERIF_APPLIED_PI
    assert result.loss_ids
    assert result.dialect_receipt is not None
    assert result.dialect_receipt.query_identity_kind is QueryIdentityKind.PROVERIF_QUERY


def test_lower_supported_tamarin_obligation() -> None:
    result = lower_protocol_obligation(
        _secrecy_obligation(
            features=_tamarin_features(),
            query_identities=("lemma:secrecy",),
        ),
        "symbolic_protocol_to_tamarin_multiset_rewriting",
    )
    assert result.status is LoweringStatus.SUPPORTED
    assert result.dialect is ProtocolDialect.TAMARIN_MULTISET_REWRITING
    assert result.target_family_id == TARGET_TAMARIN


def test_lower_rejects_computational_soundness() -> None:
    result = lower_protocol_obligation(
        _secrecy_obligation(
            features=_proverif_features() + (FEAT_COMPUTATIONAL_SOUNDNESS,),
        ),
        "symbolic_protocol_to_proverif_applied_pi",
    )
    assert result.status is LoweringStatus.UNSUPPORTED
    assert FEAT_COMPUTATIONAL_SOUNDNESS in result.unsupported_constructs


def test_lower_rejects_global_state() -> None:
    result = lower_protocol_obligation(
        _secrecy_obligation(
            features=_proverif_features() + (FEAT_GLOBAL_STATE,),
        ),
        "symbolic_protocol_to_proverif_applied_pi",
    )
    assert result.status is LoweringStatus.UNSUPPORTED


def test_plan_protocol_path_feature_total() -> None:
    receipt = plan_protocol_path(
        target_family_id=TARGET_PROVERIF,
        features=_proverif_features(),
    )
    assert receipt.edge_contract_ids
    assert "symbolic_protocol_to_proverif_applied_pi" in receipt.edge_contract_ids
    assert receipt.authority_ceiling is EvidenceAuthority.INDEPENDENTLY_CHECKABLE


def test_protocol_contracts_register_with_planner() -> None:
    contracts = protocol_target_translation_contracts()
    assert len(contracts) == 2
    catalog = ProtocolTargetTranslationEdges.reviewed()
    planner = catalog.register_with_planner()
    assert len(planner.registered_edges) == 2


def test_protocol_edge_round_trip() -> None:
    catalog = ProtocolTargetTranslationEdges.reviewed()
    wire = catalog.to_dict()
    restored = ProtocolTargetTranslationEdges.from_dict(wire)
    assert restored.edge_ids() == catalog.edge_ids()
    assert restored.catalog_content_id == catalog.catalog_content_id


def test_protocol_edge_frozen() -> None:
    edge = build_protocol_target_translation_edges()[0]
    with pytest.raises(FrozenInstanceError):
        edge.edge_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Kernel target compiler
# ---------------------------------------------------------------------------


def _sample_theory() -> TargetTheoryArtifact:
    return TargetTheoryArtifact.from_statements(
        theory_id="theory:handshake",
        name="Handshake",
        theorems=(
            {
                "theorem_id": "thm:secrecy",
                "theorem_name": "secrecy_session_key",
                "statement": "secret session_key",
            },
            {
                "theorem_id": "thm:auth",
                "theorem_name": "auth_initiator",
                "statement": "injective agreement initiator",
            },
        ),
        imports=("Init",),
        axioms=("perfect_cryptography",),
        source_ref_id="source:handshake",
    )


def test_kernel_interface_identities() -> None:
    assert KERNEL_TARGET_COMPILER_INTERFACE == "KernelTargetCompiler@2"
    assert KERNEL_TARGET_EDGES_INTERFACE == "KernelTargetTranslationEdges@1"
    assert KernelTargetCompiler.interface == KERNEL_TARGET_COMPILER_INTERFACE
    assert is_official_kernel(KernelTargetKind.LEAN)
    assert is_official_kernel("rocq")
    assert is_official_kernel(KernelTargetKind.ISABELLE)


def test_kernel_edges_cover_lean_rocq_isabelle() -> None:
    edges = KernelTargetTranslationEdges.reviewed()
    assert len(edges) == 3
    assert edges.all_loss_receipted()
    targets = {edge.kernel_target for edge in edges}
    assert targets == {
        KernelTargetKind.LEAN,
        KernelTargetKind.ROCQ,
        KernelTargetKind.ISABELLE,
    }
    for edge in edges:
        assert edge.is_loss_receipted
        assert edge.loss_ids
        assert edge.contract.authority_ceiling is not EvidenceAuthority.AUTHORITATIVE
        assert "loss:candidate-until-kernel-acceptance" in edge.loss_ids or any(
            "candidate" in loss_id for loss_id in edge.loss_ids
        )


def test_compile_produces_candidate_not_accepted() -> None:
    compiler = build_kernel_target_compiler()
    theory = _sample_theory()
    candidate = compiler.compile(
        theory,
        kernel_target=KernelTargetKind.LEAN,
        theorem_id="thm:secrecy",
        environment={
            "environment_id": "env:lean:test",
            "kernel_target": "lean",
            "toolchain_id": "lean",
            "toolchain_version": "4.0.0",
        },
    )
    assert isinstance(candidate, KernelCompilationCandidate)
    assert candidate.status is CompilationStatus.CANDIDATE
    assert candidate.kernel_accepted is False
    assert candidate.is_candidate
    assert candidate.encoding == "lean4"
    assert candidate.imports
    assert candidate.axioms == ("perfect_cryptography",)
    assert candidate.source_maps
    assert candidate.loss_ids
    assert "sorry" not in candidate.source
    assert "admit" not in candidate.source.lower()
    assert candidate.source_digest == content_digest(candidate.source)
    assert candidate.statement_digest == content_digest(candidate.statement)


def test_compile_all_kernels() -> None:
    compiler = KernelTargetCompiler()
    theory = _sample_theory()
    for kind in (
        KernelTargetKind.LEAN,
        KernelTargetKind.ROCQ,
        KernelTargetKind.ISABELLE,
    ):
        candidates = compiler.compile_all(
            theory,
            kernel_target=kind,
            environment={
                "environment_id": f"env:{kind.value}:test",
                "kernel_target": kind.value,
                "toolchain_id": kind.value,
                "toolchain_version": "1.0.0",
                "session_or_package": "Handshake",
            },
        )
        assert len(candidates) == 2
        assert all(item.is_candidate for item in candidates)
        assert all(item.kernel_target is kind for item in candidates)


def test_compile_rejects_trust_escapes_in_statement() -> None:
    with pytest.raises(KernelTargetTranslationError):
        TargetTheoryArtifact.from_statements(
            theory_id="theory:bad",
            name="Bad",
            theorems=("True := by sorry",),
        )


def test_compile_rejects_trust_escapes_in_proof_body() -> None:
    compiler = KernelTargetCompiler()
    theory = _sample_theory()
    with pytest.raises(KernelTargetTranslationError, match="trust escapes"):
        compiler.compile(
            theory,
            kernel_target=KernelTargetKind.LEAN,
            proof_body="sorry",
            environment={
                "environment_id": "env:lean:test",
                "kernel_target": "lean",
                "toolchain_id": "lean",
                "toolchain_version": "4.0.0",
            },
        )


def test_scan_and_reject_trust_escapes() -> None:
    assert "sorry" in scan_trust_escapes("theorem t : True := by sorry")
    assert "admit" in scan_trust_escapes("Proof. admit. Qed.")
    with pytest.raises(KernelTargetTranslationError):
        reject_trust_escapes("unsafe def x := 1")


def test_record_kernel_acceptance_requires_matching_environment() -> None:
    compiler = KernelTargetCompiler()
    theory = _sample_theory()
    candidate = compiler.compile(
        theory,
        kernel_target=KernelTargetKind.ROCQ,
        environment={
            "environment_id": "env:rocq:test",
            "kernel_target": "rocq",
            "toolchain_id": "rocq",
            "toolchain_version": "8.18.0",
        },
    )
    assert candidate.is_candidate
    accepted = compiler.record_kernel_acceptance(
        candidate,
        accepted=True,
        environment_id="env:rocq:test",
        theorem_identity_digest=candidate.statement_digest,
        notes="official kernel checked",
    )
    assert accepted.status is CompilationStatus.KERNEL_ACCEPTED
    assert accepted.kernel_accepted is True
    with pytest.raises(KernelTargetTranslationError, match="environment_id"):
        compiler.record_kernel_acceptance(
            candidate,
            accepted=True,
            environment_id="env:wrong",
        )


def test_theory_artifact_records_imports_axioms_source_maps() -> None:
    theory = _sample_theory()
    assert theory.imports == ("Init",)
    assert theory.axioms == ("perfect_cryptography",)
    assert theory.source_maps
    assert theory.document_id.startswith("bafkrei")
    wire = theory.to_dict()
    restored = TargetTheoryArtifact.from_dict(wire)
    assert restored.theory_id == theory.theory_id
    assert restored.theorems[0]["statement_digest"] == content_digest(
        restored.theorems[0]["statement"]
    )


def test_kernel_contracts_for_planner() -> None:
    contracts = kernel_target_translation_contracts()
    assert len(contracts) == 3
    assert {c.target.family_id for c in contracts} == {"lean", "rocq", "isabelle"}


def test_kernel_edge_round_trip() -> None:
    edges = build_kernel_target_translation_edges()
    catalog = KernelTargetTranslationEdges(edges=edges)
    wire = catalog.to_dict()
    restored = KernelTargetTranslationEdges.from_dict(wire)
    assert restored.edge_ids() == catalog.edge_ids()

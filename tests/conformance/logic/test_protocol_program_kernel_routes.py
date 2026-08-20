"""Conformance: join protocol, program, and proof-assistant targets (LFP-033).

Acceptance:

* Official kernels are sole proof authority
* Generated sources reject sorry/admit/trust escapes
* Hammer/ATP suggestions remain candidates until reconstructed
* Exact theorem and environment identities are recorded

Interfaces: TargetTheoryModel@1, KernelTargetGenerator@1, HammerStrategyReceipt@1
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.parsers.kernel_targets import (
    CODE_TRUST_ESCAPE,
    ENVIRONMENT_IDENTITY_SCHEMA,
    HAMMER_STRATEGY_RECEIPT_INTERFACE,
    KERNEL_TARGET_GENERATOR_INTERFACE,
    TARGET_THEORY_MODEL_INTERFACE,
    THEOREM_IDENTITY_SCHEMA,
    AuthorityPromotionError,
    DeclarationKind,
    EnvironmentIdentity,
    HammerStrategyKind,
    HammerStrategyReceipt,
    JoinReceipt,
    KernelGeneratedSource,
    KernelTargetError,
    KernelTargetGenerator,
    KernelTargetKind,
    ProofAuthorityRole,
    ProtocolProgramKernelRoute,
    ReconstructionStatus,
    RouteSurface,
    TargetDeclaration,
    TargetTheoryModel,
    TheoremIdentity,
    TrustEscapeError,
    TrustReceipt,
    content_digest,
    is_official_kernel,
    join_program_route,
    join_protocol_program_kernel_surfaces,
    join_protocol_route,
    record_kernel_acceptance,
    reject_trust_escapes,
    result_authority_for_surface,
    scan_trust_escapes,
    surface_authority_role,
    theory_from_program_obligations,
    theory_from_protocol_claims,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _lean_env(**overrides: object) -> EnvironmentIdentity:
    payload = {
        "environment_id": "env:lean:test-1",
        "kernel_target": KernelTargetKind.LEAN,
        "toolchain_id": "lean",
        "toolchain_version": "4.0.0",
        "source_tree_digest": "a" * 64,
        "session_or_package": "ProtocolProgramJoin",
        "os_name": "linux",
        "architecture": "x86_64",
    }
    payload.update(overrides)
    return EnvironmentIdentity(**payload)  # type: ignore[arg-type]


def _rocq_env() -> EnvironmentIdentity:
    return EnvironmentIdentity(
        environment_id="env:rocq:test-1",
        kernel_target=KernelTargetKind.ROCQ,
        toolchain_id="rocq",
        toolchain_version="8.18.0",
        source_tree_digest="b" * 64,
        session_or_package="ProtocolProgramJoin",
    )


def _isabelle_env() -> EnvironmentIdentity:
    return EnvironmentIdentity(
        environment_id="env:isabelle:test-1",
        kernel_target=KernelTargetKind.ISABELLE,
        toolchain_id="isabelle",
        toolchain_version="2024",
        source_tree_digest="c" * 64,
        session_or_package="ProtocolProgramJoin",
    )


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert TARGET_THEORY_MODEL_INTERFACE == "TargetTheoryModel@1"
    assert KERNEL_TARGET_GENERATOR_INTERFACE == "KernelTargetGenerator@1"
    assert HAMMER_STRATEGY_RECEIPT_INTERFACE == "HammerStrategyReceipt@1"
    assert TargetTheoryModel.INTERFACE == TARGET_THEORY_MODEL_INTERFACE
    assert KernelTargetGenerator.interface == KERNEL_TARGET_GENERATOR_INTERFACE
    assert HammerStrategyReceipt.INTERFACE == HAMMER_STRATEGY_RECEIPT_INTERFACE


def test_official_kernels_are_sole_enumerated_proof_targets() -> None:
    assert is_official_kernel(KernelTargetKind.LEAN)
    assert is_official_kernel("rocq")
    assert is_official_kernel(KernelTargetKind.ISABELLE)
    for surface in (
        RouteSurface.PROTOCOL_PROVERIF,
        RouteSurface.PROTOCOL_TAMARIN,
        RouteSurface.PROGRAM_VC,
        RouteSurface.PROGRAM_SMT,
        RouteSurface.PROGRAM_CHC,
        RouteSurface.RESOURCE_REFINEMENT,
        RouteSurface.HAMMER_STRATEGY,
        RouteSurface.ATP_CANDIDATE,
    ):
        assert surface_authority_role(surface) is not ProofAuthorityRole.OFFICIAL_KERNEL
        assert result_authority_for_surface(surface) is not ResultAuthority.THEOREM


# ---------------------------------------------------------------------------
# TargetTheoryModel
# ---------------------------------------------------------------------------


def test_target_theory_records_imports_axioms_source_maps_and_identity() -> None:
    theory = theory_from_protocol_claims(
        theory_id="theory:handshake",
        name="handshake",
        surface=RouteSurface.PROTOCOL_PROVERIF,
        claims=(
            {
                "claim_id": "claim:secrecy",
                "name": "secrecy_session_key",
                "kind": "secrecy",
                "statement": "secret session_key",
            },
            {
                "claim_id": "claim:auth",
                "name": "auth_initiator",
                "kind": "authentication",
            },
        ),
        imports=("Init", "Protocol.Core"),
        axioms=("perfect_cryptography",),
        upstream_document_id="protocol-doc:handshake",
        source_ref_id="source:handshake",
        environment=_lean_env(),
    )
    assert theory.interface == TARGET_THEORY_MODEL_INTERFACE
    assert theory.document_id == theory.identity.cid
    assert "Init" in theory.imports
    assert "perfect_cryptography" in theory.axioms
    assert len(theory.theorems) == 2
    assert theory.authority_ceiling() is ResultAuthority.PROTOCOL
    assert theory.trust_receipt is not None
    assert theory.trust_receipt.allows_theorem_authority is False
    assert theory.source_maps
    wire = theory.to_dict()
    restored = TargetTheoryModel.from_dict(wire)
    assert restored.document_id == theory.document_id
    assert restored.theorems[0].statement_digest == content_digest(
        restored.theorems[0].statement
    )


def test_program_obligations_never_emit_vc_as_family() -> None:
    theory = theory_from_program_obligations(
        theory_id="theory:counter-vc",
        name="counter_vc",
        surface=RouteSurface.PROGRAM_VC,
        obligations=(
            {
                "obligation_id": "obl:wp-post",
                "name": "wp_postcondition",
                "statement": "x >= 0",
                "rule": "wp",
            },
        ),
        imports=("Init",),
    )
    assert theory.family_id == "target_theory"
    assert theory.authority_ceiling() is ResultAuthority.CANDIDATE
    assert all(item.kind is DeclarationKind.OBLIGATION or item.kind is DeclarationKind.IMPORT
               for item in theory.declarations)


# ---------------------------------------------------------------------------
# Trust escape rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "theorem t : True := by sorry",
        "theorem t : True := by admit",
        "Theorem t : True. Proof. admit. Qed.",
        "theorem t: \"True\" sorry",
        "lemma t: True oops",
        "theorem t : True := by trusted",
        "unsafe def bad : True := trivial",
        "theorem t : True := by cheat",
    ],
)
def test_generated_sources_reject_trust_escapes(source: str) -> None:
    found = scan_trust_escapes(source)
    assert found
    with pytest.raises(TrustEscapeError) as excinfo:
        reject_trust_escapes(source)
    assert excinfo.value.code == CODE_TRUST_ESCAPE
    assert excinfo.value.escapes


def test_declaration_body_rejects_sorry() -> None:
    with pytest.raises(TrustEscapeError):
        TargetDeclaration(
            declaration_id="decl:bad",
            kind=DeclarationKind.THEOREM,
            name="bad",
            statement="True",
            body="sorry",
        )


# ---------------------------------------------------------------------------
# KernelTargetGenerator
# ---------------------------------------------------------------------------


def test_generator_emits_escape_free_lean_rocq_isabelle_with_identities() -> None:
    theory = theory_from_program_obligations(
        theory_id="theory:true-goal",
        name="true_goal",
        obligations=({"obligation_id": "obl:true", "name": "true_goal"},),
        imports=("Init",),
        environment=_lean_env(),
    )
    generator = KernelTargetGenerator(default_environment=_lean_env())

    lean = generator.generate(
        theory,
        kernel_target=KernelTargetKind.LEAN,
        proof_body="exact True.intro",
    )
    assert isinstance(lean, KernelGeneratedSource)
    assert lean.kernel_accepted is False
    assert lean.kernel_target is KernelTargetKind.LEAN
    assert lean.encoding == "lean4"
    assert "sorry" not in lean.source
    assert "admit" not in lean.source.lower()
    assert lean.theorem_identity.schema_version == THEOREM_IDENTITY_SCHEMA
    assert lean.environment.schema_version == ENVIRONMENT_IDENTITY_SCHEMA
    assert lean.theorem_identity_digest == lean.theorem_identity.identity_digest
    assert lean.environment_identity_digest == lean.environment.identity_digest
    assert lean.source_digest == content_digest(lean.source)
    assert lean.proof_authority is ProofAuthorityRole.OFFICIAL_KERNEL

    rocq = generator.generate(
        theory,
        kernel_target=KernelTargetKind.ROCQ,
        environment=_rocq_env(),
        proof_body="exact I.",
    )
    assert rocq.encoding == "rocq"
    assert "Admitted" not in rocq.source
    assert "admit" not in rocq.source.lower()

    isabelle = generator.generate(
        theory,
        kernel_target=KernelTargetKind.ISABELLE,
        environment=_isabelle_env(),
        proof_body='show ?thesis by simp',
    )
    assert isabelle.encoding == "isabelle_hol"
    assert "sorry" not in isabelle.source
    assert "oops" not in isabelle.source


def test_generator_rejects_proof_body_with_admit() -> None:
    theory = theory_from_program_obligations(
        theory_id="theory:body-escape",
        name="body_escape",
        obligations=("goal",),
    )
    generator = KernelTargetGenerator(default_environment=_lean_env())
    with pytest.raises(TrustEscapeError):
        generator.generate(
            theory,
            kernel_target=KernelTargetKind.LEAN,
            proof_body="admit",
        )


def test_generation_never_marks_kernel_accepted() -> None:
    theory = theory_from_protocol_claims(
        theory_id="theory:no-accept",
        name="no_accept",
        surface=RouteSurface.PROTOCOL_TAMARIN,
        claims=("secrecy",),
    )
    generator = KernelTargetGenerator(default_environment=_lean_env())
    generated = generator.generate(theory, kernel_target=KernelTargetKind.LEAN)
    assert generated.kernel_accepted is False
    binding = record_kernel_acceptance(generated, accepted=True)
    assert binding["authority"] == ResultAuthority.THEOREM.value
    assert binding["theorem_identity_digest"] == generated.theorem_identity_digest
    assert binding["environment_identity_digest"] == generated.environment_identity_digest
    # The generated artifact itself remains unaccepted.
    assert generated.kernel_accepted is False


# ---------------------------------------------------------------------------
# HammerStrategyReceipt — candidates until reconstructed
# ---------------------------------------------------------------------------


def test_hammer_suggestions_remain_candidates() -> None:
    theorem = TheoremIdentity.bind(
        theorem_id="thm:goal",
        theorem_name="goal",
        statement="True",
        theory_id="theory:hammer",
        source_surface=RouteSurface.HAMMER_STRATEGY,
        kernel_target=KernelTargetKind.LEAN,
    )
    receipt = HammerStrategyReceipt.from_suggestion(
        receipt_id="hammer:1",
        theorem_identity=theorem,
        candidate_text="by auto using assms",
        strategy_kind=HammerStrategyKind.ATP_CANDIDATE,
        environment=_lean_env(),
        premises=("assms",),
        suggested_tactics=("simp", "auto"),
        solver_id="vampire",
        solver_verdict="proved",
    )
    assert receipt.interface == HAMMER_STRATEGY_RECEIPT_INTERFACE
    assert receipt.is_candidate is True
    assert receipt.kernel_accepted is False
    assert receipt.result_authority is ResultAuthority.CANDIDATE
    assert receipt.result_status is ResultStatus.CANDIDATE
    assert receipt.proof_authority is ProofAuthorityRole.CANDIDATE_ONLY
    assert receipt.reconstruction_status is ReconstructionStatus.NOT_ATTEMPTED
    assert receipt.theorem_identity_digest == theorem.identity_digest
    assert receipt.environment_identity_digest == _lean_env().identity_digest


def test_hammer_cannot_claim_theorem_authority() -> None:
    theorem = TheoremIdentity.bind(
        theorem_id="thm:goal",
        theorem_name="goal",
        statement="True",
        theory_id="theory:hammer",
        source_surface=RouteSurface.ATP_CANDIDATE,
    )
    with pytest.raises(AuthorityPromotionError):
        HammerStrategyReceipt(
            receipt_id="hammer:bad",
            strategy_kind=HammerStrategyKind.ATP_CANDIDATE,
            theorem_identity=theorem,
            environment=None,
            candidate_digest=content_digest("fake proof"),
            proof_authority=ProofAuthorityRole.OFFICIAL_KERNEL,
            result_authority=ResultAuthority.CANDIDATE,
        )
    with pytest.raises(AuthorityPromotionError):
        HammerStrategyReceipt(
            receipt_id="hammer:bad2",
            strategy_kind=HammerStrategyKind.ATP_CANDIDATE,
            theorem_identity=theorem,
            environment=None,
            candidate_digest=content_digest("fake proof"),
            result_authority=ResultAuthority.THEOREM,
        )


def test_hammer_suggested_tactics_reject_sorry() -> None:
    theorem = TheoremIdentity.bind(
        theorem_id="thm:goal",
        theorem_name="goal",
        statement="True",
        theory_id="theory:hammer",
        source_surface=RouteSurface.HAMMER_STRATEGY,
    )
    with pytest.raises(TrustEscapeError):
        HammerStrategyReceipt.from_suggestion(
            receipt_id="hammer:sorry-tactic",
            theorem_identity=theorem,
            candidate_text="try sorry",
            suggested_tactics=("sorry",),
        )


# ---------------------------------------------------------------------------
# Join routes
# ---------------------------------------------------------------------------


def test_join_protocol_and_program_routes_record_identities() -> None:
    protocol_route = join_protocol_route(
        route_id="route:proverif-handshake",
        surface=RouteSurface.PROTOCOL_PROVERIF,
        claims=(
            {"claim_id": "claim:sec", "name": "secrecy", "kind": "secrecy"},
        ),
        kernel_targets=(KernelTargetKind.LEAN, KernelTargetKind.ROCQ),
        environment=_lean_env(),
        imports=("Init",),
        upstream_document_id="protocol:handshake",
        source_ref_id="source:handshake",
        proof_bodies={"thm:claim_sec": "exact True.intro"},
        hammer_suggestions=(
            {
                "theorem_id": "thm:claim_sec",
                "candidate_text": "vampire proof candidate bytes",
                "solver_id": "vampire",
                "solver_verdict": "proved",
                "suggested_tactics": ("simp",),
            },
        ),
    )
    assert isinstance(protocol_route, ProtocolProgramKernelRoute)
    assert protocol_route.authority_ceiling is ResultAuthority.PROTOCOL
    assert len(protocol_route.generated_sources) == 2
    assert all(src.kernel_accepted is False for src in protocol_route.generated_sources)
    assert all(
        src.theorem_identity_digest and src.environment_identity_digest
        for src in protocol_route.generated_sources
    )
    assert len(protocol_route.hammer_receipts) == 1
    assert protocol_route.hammer_receipts[0].is_candidate is True
    assert protocol_route.hammer_receipts[0].result_authority is ResultAuthority.CANDIDATE

    program_route = join_program_route(
        route_id="route:program-vc",
        surface=RouteSurface.PROGRAM_VC,
        obligations=(
            {
                "obligation_id": "obl:invariant",
                "name": "loop_invariant",
                "statement": "i <= n",
            },
        ),
        kernel_targets=(KernelTargetKind.ISABELLE,),
        environment=_isabelle_env(),
        upstream_document_id="program:counter",
        proof_bodies={"thm:obl_invariant": 'show ?thesis by simp'},
    )
    assert program_route.authority_ceiling is ResultAuthority.CANDIDATE
    assert program_route.generated_sources[0].kernel_target is KernelTargetKind.ISABELLE
    assert "sorry" not in program_route.generated_sources[0].source

    join = JoinReceipt(
        join_id="join:protocol-program-1",
        routes=(protocol_route, program_route),
    )
    assert join.official_kernels_sole_proof_authority is True
    assert join.hammer_remains_candidate is True
    assert "sorry" in join.trust_escapes_rejected
    assert "admit" in join.trust_escapes_rejected
    wire = join.to_dict()
    assert wire["official_kernels_sole_proof_authority"] is True
    assert len(wire["routes"]) == 2


def test_join_protocol_program_kernel_surfaces_helper() -> None:
    receipt = join_protocol_program_kernel_surfaces(
        join_id="join:full",
        protocol_routes=(
            {
                "route_id": "route:tamarin",
                "surface": RouteSurface.PROTOCOL_TAMARIN,
                "claims": ("trace_lemma_secret",),
                "kernel_targets": (KernelTargetKind.LEAN,),
                "environment": _lean_env().to_dict(),
                "upstream_document_id": "tamarin:theory",
                "hammer_suggestions": (
                    {
                        "candidate_text": "eprover candidate",
                        "solver_id": "eprover",
                        "suggested_tactics": ("rfl",),
                    },
                ),
            },
        ),
        program_routes=(
            {
                "route_id": "route:smt",
                "surface": RouteSurface.PROGRAM_SMT,
                "obligations": (
                    {"obligation_id": "obl:sat", "name": "unsat_core_goal"},
                ),
                "kernel_targets": (KernelTargetKind.ROCQ,),
                "environment": _rocq_env().to_dict(),
            },
            {
                "route_id": "route:refinement",
                "surface": RouteSurface.RESOURCE_REFINEMENT,
                "obligations": ("refines_concrete",),
                "kernel_targets": (KernelTargetKind.LEAN,),
                "environment": _lean_env().to_dict(),
            },
        ),
    )
    assert isinstance(receipt, JoinReceipt)
    assert len(receipt.routes) == 3
    surfaces = {route.surface for route in receipt.routes}
    assert RouteSurface.PROTOCOL_TAMARIN in surfaces
    assert RouteSurface.PROGRAM_SMT in surfaces
    assert RouteSurface.RESOURCE_REFINEMENT in surfaces
    # Protocol ceiling stays protocol; program/SMT stay non-theorem.
    for route in receipt.routes:
        if route.surface is RouteSurface.PROTOCOL_TAMARIN:
            assert route.authority_ceiling is ResultAuthority.PROTOCOL
        else:
            assert route.authority_ceiling is not ResultAuthority.THEOREM
        for source in route.generated_sources:
            reject_trust_escapes(source.source)
            assert source.theorem_identity.identity_digest
            assert source.environment.identity_digest
        for hammer in route.hammer_receipts:
            assert hammer.is_candidate
            assert hammer.result_authority is ResultAuthority.CANDIDATE


def test_protocol_surface_cannot_set_theorem_authority_ceiling() -> None:
    theory = theory_from_protocol_claims(
        theory_id="theory:auth-fail",
        name="auth_fail",
        surface=RouteSurface.PROTOCOL_PROVERIF,
        claims=("secrecy",),
    )
    with pytest.raises(AuthorityPromotionError):
        ProtocolProgramKernelRoute(
            route_id="route:bad-ceiling",
            surface=RouteSurface.PROTOCOL_PROVERIF,
            theory=theory,
            authority_ceiling=ResultAuthority.THEOREM,
        )


def test_trust_receipt_rejects_theorem_promotion_for_hammer_surface() -> None:
    with pytest.raises(AuthorityPromotionError):
        TrustReceipt(
            receipt_id="trust:bad",
            surface=RouteSurface.HAMMER_STRATEGY,
            disposition="candidate",
            authority_role=ProofAuthorityRole.CANDIDATE_ONLY,
            result_authority=ResultAuthority.CANDIDATE,
            allows_theorem_authority=True,
        )


def test_round_trip_generated_source_dict() -> None:
    theory = theory_from_program_obligations(
        theory_id="theory:roundtrip",
        name="roundtrip",
        obligations=("true_goal",),
    )
    generated = KernelTargetGenerator(default_environment=_lean_env()).generate(
        theory,
        kernel_target=KernelTargetKind.LEAN,
        proof_body="exact True.intro",
    )
    restored = KernelGeneratedSource.from_dict(generated.to_dict())
    assert restored.source_digest == generated.source_digest
    assert restored.theorem_identity_digest == generated.theorem_identity_digest
    assert restored.environment_identity_digest == generated.environment_identity_digest

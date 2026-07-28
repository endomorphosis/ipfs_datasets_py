"""Unit tests for authority-grade proof envelopes and trust policy (LIG-029).

Acceptance:

* Bind statement/assumption/obligation, domain/logic/result authority,
  source/corpus/policy/ontology/adapter/compiler/translation/solver/
  reconstruction, proof/build/source-map CIDs, attestation kind,
  circuit/VK/backend/public inputs/security profile, effective/expiry,
  jurisdiction/tenant/subject/resource scope, coverage, parents,
  supersession/revocation and diagnostics.
* Policy declares exact roots/allowlists/minimums/budgets/open-closed-world/
  conflict rules.
* Direct verification, verifier execution, membership, signature and
  simulation remain non-substitutable.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest

from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.proof_corpus.model import (
    ATTESTED_PROOF_ENVELOPE_INTERFACE,
    ATTESTED_PROOF_ENVELOPE_SCHEMA_VERSION,
    NON_SUBSTITUTABLE_EVIDENCE_KINDS,
    AttestationKind,
    AttestedProofEnvelope,
    AttestedProofIntegrityError,
    AttestedProofModelError,
    CircuitBinding,
    CoverageDeclaration,
    PipelineIdentity,
    ProofResultStatus,
    ScopeBinding,
    TemporalWindow,
    attestation_kind_is_theorem_authoritative,
    build_attested_proof_envelope,
    evidence_kinds_are_non_substitutable,
    parse_attestation_kind,
)
from ipfs_datasets_py.logic.proof_corpus.policy import (
    CORPUS_COVERAGE_POLICY_INTERFACE,
    PROOF_TRUST_POLICY_INTERFACE,
    ConflictRule,
    CorpusCoveragePolicy,
    PolicyBudget,
    ProofTrustPolicy,
    ProofTrustPolicyError,
    ProofTrustPolicyViolation,
    TrustEvaluationStatus,
    WorldMode,
    default_production_trust_policy,
    non_substitutable_evidence_kinds,
)
from ipfs_datasets_py.logic.proof_corpus.schemas import ProofCorpusFamily


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _cid(label: str) -> str:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return cid_v1_from_digest(bytes.fromhex(digest))


def _honest_envelope(**overrides: Any) -> AttestedProofEnvelope:
    """Return a fully bound direct-verification theorem envelope."""

    base: dict[str, Any] = {
        "statement_digest": _digest("statement"),
        "assumption_digest": _digest("assumption"),
        "obligation_digest": _digest("obligation"),
        "domain": "legal",
        "logic_family": "deontic",
        "result_authority": AuthorityKind.THEOREM_PROOF,
        "attestation_kind": AttestationKind.DIRECT_PROOF_VERIFICATION,
        "family": ProofCorpusFamily.LEGAL,
        "result_status": ProofResultStatus.PROVED,
        "proof_artifact_cid": _cid("proof-artifact"),
        "proof_bytes_digest": _digest("proof-bytes"),
        "source_snapshot_cid": _cid("source-snapshot"),
        "corpus_root_cid": _cid("corpus-root"),
        "revocation_root_cid": _cid("revocation-root"),
        "policy_id": "policy-legal-strict",
        "ontology_id": "ontology-us-code",
        "adapter_id": "adapter-legal-v1",
        "compiler_id": "compiler-canonical-v1",
        "translation_id": "translation-none",
        "solver_id": "solver-z3",
        "reconstruction_id": "reconstruction-v1",
        "build_manifest_cid": _cid("build-manifest"),
        "source_map_cid": _cid("source-map"),
        "backend_id": "provekit",
        "security_profile": "legal-strict",
        "public_inputs": {
            "statement_digest": _digest("statement"),
            "corpus_root": _cid("corpus-root"),
        },
        "circuit": CircuitBinding(
            circuit_id="legal_constraint",
            circuit_version=1,
            circuit_digest=_digest("circuit"),
            vk_id="legal_constraint_vk",
            vk_version=1,
            vk_digest=_digest("vk"),
            backend_id="provekit",
            proof_system="groth16",
            public_inputs={
                "statement_digest": _digest("statement"),
                "corpus_root": _cid("corpus-root"),
            },
            security_profile="legal-strict",
        ),
        "pipeline": PipelineIdentity(
            source_id="source-us-code-552",
            corpus_id="corpus-legal-v1",
            policy_id="policy-legal-strict",
            ontology_id="ontology-us-code",
            adapter_id="adapter-legal-v1",
            compiler_id="compiler-canonical-v1",
            translation_id="translation-none",
            solver_id="solver-z3",
            reconstruction_id="reconstruction-v1",
        ),
        "scope": ScopeBinding(
            jurisdiction="us-federal",
            tenant="tenant-a",
            subject_ids=("subject-alice",),
            resource_ids=("resource-records",),
            purpose_ids=("purpose-disclosure",),
        ),
        "temporal": TemporalWindow(
            effective_at="2026-01-01T00:00:00Z",
            expires_at="2027-01-01T00:00:00Z",
        ),
        "coverage": CoverageDeclaration(
            covered_selectors=("jurisdiction", "subject", "resource"),
            complete=True,
        ),
        "parent_cids": (_cid("parent-envelope"),),
        "diagnostics": {"notes": "honest fixture"},
        "producer_id": "lig-029-test",
    }
    base.update(overrides)
    return AttestedProofEnvelope(**base)


def _production_policy(**overrides: Any) -> ProofTrustPolicy:
    base: dict[str, Any] = {
        "policy_id": "trust-production",
        "corpus_roots": (_cid("corpus-root"),),
        "revocation_roots": (_cid("revocation-root"),),
        "policy_roots": (_cid("policy-root"),),
        "vk_registry_roots": (_cid("vk-registry"),),
        "circuit_allowlist": ("legal_constraint", "legal_constraint@v1"),
        "backend_allowlist": ("provekit",),
        "solver_allowlist": ("solver-z3",),
        "compiler_allowlist": ("compiler-canonical-v1",),
        "security_profile_allowlist": ("legal-strict", "zkp-required"),
        "attestation_kind_allowlist": (
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        ),
        "authoritative_attestation_kinds": (
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        ),
        "required_result_authority": AuthorityKind.THEOREM_PROOF,
        "minimum_security_profile": "legal-strict",
        "accept_simulated": False,
        "require_circuit_binding": True,
        "require_vk_binding": True,
        "require_public_inputs": True,
        "world_mode": WorldMode.CLOSED,
        "conflict_rule": ConflictRule.FAIL_CLOSED,
        "budget": PolicyBudget(
            max_candidates=64,
            max_bytes=1_048_576,
            max_graph_depth=16,
            timeout_ms=5_000,
            max_backend_attempts=3,
        ),
        "allowed_jurisdictions": ("us-federal",),
        "allowed_tenants": ("tenant-a",),
        "description": "test production trust policy",
    }
    base.update(overrides)
    return ProofTrustPolicy(**base)


# ---------------------------------------------------------------------------
# Envelope bindings
# ---------------------------------------------------------------------------


def test_attested_envelope_binds_all_authority_fields() -> None:
    envelope = _honest_envelope()
    envelope.verify_integrity()

    assert envelope.interface == ATTESTED_PROOF_ENVELOPE_INTERFACE
    assert envelope.schema_version == ATTESTED_PROOF_ENVELOPE_SCHEMA_VERSION
    assert envelope.statement_digest == _digest("statement")
    assert envelope.assumption_digest == _digest("assumption")
    assert envelope.obligation_digest == _digest("obligation")
    assert envelope.domain == "legal"
    assert envelope.logic_family == "deontic"
    assert envelope.result_authority is AuthorityKind.THEOREM_PROOF
    assert envelope.attestation_kind is AttestationKind.DIRECT_PROOF_VERIFICATION
    assert envelope.family is ProofCorpusFamily.LEGAL
    assert envelope.source_snapshot_cid == _cid("source-snapshot")
    assert envelope.corpus_root_cid == _cid("corpus-root")
    assert envelope.policy_id == "policy-legal-strict"
    assert envelope.ontology_id == "ontology-us-code"
    assert envelope.adapter_id == "adapter-legal-v1"
    assert envelope.compiler_id == "compiler-canonical-v1"
    assert envelope.translation_id == "translation-none"
    assert envelope.solver_id == "solver-z3"
    assert envelope.reconstruction_id == "reconstruction-v1"
    assert envelope.proof_artifact_cid == _cid("proof-artifact")
    assert envelope.build_manifest_cid == _cid("build-manifest")
    assert envelope.source_map_cid == _cid("source-map")
    assert envelope.circuit.circuit_id == "legal_constraint"
    assert envelope.circuit.vk_id == "legal_constraint_vk"
    assert envelope.circuit.backend_id == "provekit"
    assert "statement_digest" in envelope.public_inputs
    assert envelope.security_profile == "legal-strict"
    assert envelope.temporal.effective_at.startswith("2026-")
    assert envelope.temporal.expires_at.startswith("2027-")
    assert envelope.scope.jurisdiction == "us-federal"
    assert envelope.scope.tenant == "tenant-a"
    assert envelope.scope.subject_ids == ("subject-alice",)
    assert envelope.scope.resource_ids == ("resource-records",)
    assert envelope.coverage.complete is True
    assert envelope.parent_cids == (_cid("parent-envelope"),)
    assert envelope.diagnostics["notes"] == "honest fixture"
    assert envelope.content_digest.startswith("sha256:")
    assert envelope.content_cid.startswith("b")
    assert envelope.envelope_cid == envelope.content_cid


def test_envelope_round_trip_preserves_canonical_identity() -> None:
    original = _honest_envelope()
    restored = AttestedProofEnvelope.from_dict(original.to_dict())
    assert restored.content_digest == original.content_digest
    assert restored.envelope_cid == original.envelope_cid
    assert restored.to_dict() == original.to_dict()
    restored.verify_integrity()


def test_envelope_identity_is_mutation_sensitive() -> None:
    honest = _honest_envelope()
    mutated = _honest_envelope(solver_id="solver-vampire")
    assert honest.content_digest != mutated.content_digest
    assert honest.envelope_cid != mutated.envelope_cid


def test_content_digest_drift_fails_closed() -> None:
    honest = _honest_envelope()
    payload = honest.to_dict()
    payload["content_digest"] = _digest("tampered")
    with pytest.raises(AttestedProofIntegrityError, match="content_digest"):
        AttestedProofEnvelope.from_dict(payload)


def test_missing_required_digests_fail_closed() -> None:
    with pytest.raises(AttestedProofModelError):
        AttestedProofEnvelope(
            statement_digest="",
            assumption_digest=_digest("assumption"),
            obligation_digest=_digest("obligation"),
            domain="legal",
            logic_family="deontic",
            result_authority=AuthorityKind.THEOREM_PROOF,
            attestation_kind=AttestationKind.DIRECT_PROOF_VERIFICATION,
        )


def test_unknown_attestation_kind_fails_closed() -> None:
    with pytest.raises(AttestedProofModelError, match="attestation_kind"):
        parse_attestation_kind("theorem-by-vibes")


def test_supersession_and_revocation_bindings() -> None:
    envelope = _honest_envelope(
        supersedes_cid=_cid("older"),
        supersession_cid=_cid("newer"),
        revocation_cid=_cid("revocation-entry"),
    )
    assert envelope.is_superseded()
    assert envelope.is_revoked()
    assert not envelope.is_effective_at("2026-06-01T00:00:00Z")


def test_temporal_window_effectiveness() -> None:
    envelope = _honest_envelope()
    assert envelope.is_effective_at("2026-06-01T00:00:00Z")
    assert not envelope.is_effective_at("2025-12-31T23:59:59Z")
    assert not envelope.is_effective_at("2027-01-01T00:00:00Z")


def test_simulation_cannot_claim_theorem_proved() -> None:
    with pytest.raises(AttestedProofIntegrityError, match="simulation"):
        _honest_envelope(
            attestation_kind=AttestationKind.SIMULATION,
            result_authority=AuthorityKind.THEOREM_PROOF,
            result_status=ProofResultStatus.PROVED,
        )


def test_build_helper_and_pipeline_sync() -> None:
    envelope = build_attested_proof_envelope(
        statement_digest=_digest("s"),
        assumption_digest=_digest("a"),
        obligation_digest=_digest("o"),
        domain="security",
        logic_family="threat_model",
        result_authority=AuthorityKind.THEOREM_PROOF,
        attestation_kind=AttestationKind.DIRECT_PROOF_VERIFICATION,
        family=ProofCorpusFamily.SECURITY,
        pipeline=PipelineIdentity(
            policy_id="p1",
            ontology_id="o1",
            adapter_id="a1",
            compiler_id="c1",
            translation_id="t1",
            solver_id="s1",
            reconstruction_id="r1",
        ),
        circuit=CircuitBinding(
            circuit_id="sec",
            circuit_version=1,
            vk_id="vk",
            vk_digest=_digest("vk"),
            backend_id="backend",
            public_inputs={"k": "v"},
            security_profile="security-lite",
        ),
        public_inputs={"k": "v"},
        security_profile="security-lite",
        backend_id="backend",
    )
    assert envelope.policy_id == "p1"
    assert envelope.solver_id == "s1"
    assert envelope.circuit.circuit_ref == "sec@v1"


# ---------------------------------------------------------------------------
# Non-substitutability
# ---------------------------------------------------------------------------


def test_evidence_kinds_are_non_substitutable_closed_set() -> None:
    kinds = evidence_kinds_are_non_substitutable()
    assert kinds == NON_SUBSTITUTABLE_EVIDENCE_KINDS
    assert kinds == non_substitutable_evidence_kinds()
    assert "direct-proof-verification" in kinds
    assert "verifier-execution" in kinds
    assert "artifact-membership" in kinds
    assert "signature" in kinds
    assert "simulation" in kinds
    # No silent hierarchy / promotion aliases.
    assert "theorem_proof" not in kinds
    assert "proof" not in kinds


@pytest.mark.parametrize(
    ("kind", "authoritative"),
    [
        (AttestationKind.DIRECT_PROOF_VERIFICATION, True),
        (AttestationKind.VERIFIER_EXECUTION, False),
        (AttestationKind.ARTIFACT_MEMBERSHIP, False),
        (AttestationKind.SIMULATION, False),
    ],
)
def test_attestation_kind_theorem_authority(
    kind: AttestationKind, authoritative: bool
) -> None:
    assert attestation_kind_is_theorem_authoritative(kind) is authoritative


def test_membership_envelope_is_not_theorem_authoritative() -> None:
    envelope = _honest_envelope(
        attestation_kind=AttestationKind.ARTIFACT_MEMBERSHIP,
        result_status=ProofResultStatus.READY,
    )
    assert envelope.is_membership_only
    assert not envelope.is_theorem_authoritative()
    assert "artifact-membership" in envelope.non_substitutable_evidence_classes()


def test_simulation_envelope_is_not_theorem_authoritative() -> None:
    envelope = _honest_envelope(
        attestation_kind=AttestationKind.SIMULATION,
        result_status=ProofResultStatus.UNKNOWN,
    )
    assert envelope.is_simulated
    assert not envelope.is_theorem_authoritative()


def test_signature_evidence_is_distinct_from_direct_verification() -> None:
    envelope = _honest_envelope(
        signatures=({"alg": "ed25519", "sig": "00"},),
    )
    assert envelope.has_signature_evidence
    assert "signature" in envelope.non_substitutable_evidence_classes()
    # Signature may accompany direct verification but does not replace it.
    assert envelope.claims_direct_verification
    assert envelope.is_theorem_authoritative()


def test_verifier_execution_does_not_silently_become_direct() -> None:
    envelope = _honest_envelope(
        attestation_kind=AttestationKind.VERIFIER_EXECUTION,
    )
    assert envelope.claims_verifier_execution
    assert not envelope.claims_direct_verification
    assert not envelope.is_theorem_authoritative()
    assert not attestation_kind_is_theorem_authoritative(
        AttestationKind.VERIFIER_EXECUTION
    )


# ---------------------------------------------------------------------------
# Trust policy
# ---------------------------------------------------------------------------


def test_trust_policy_declares_roots_allowlists_minimums_budgets_and_rules() -> None:
    policy = _production_policy()
    payload = policy.to_dict()

    assert policy.interface == PROOF_TRUST_POLICY_INTERFACE
    assert payload["corpus_roots"] == [_cid("corpus-root")]
    assert payload["revocation_roots"] == [_cid("revocation-root")]
    assert payload["policy_roots"] == [_cid("policy-root")]
    assert payload["vk_registry_roots"] == [_cid("vk-registry")]
    assert "legal_constraint" in payload["circuit_allowlist"]
    assert "provekit" in payload["backend_allowlist"]
    assert payload["minimum_security_profile"] == "legal-strict"
    assert payload["budget"]["max_candidates"] == 64
    assert payload["budget"]["timeout_ms"] == 5_000
    assert payload["world_mode"] == WorldMode.CLOSED.value
    assert payload["conflict_rule"] == ConflictRule.FAIL_CLOSED.value
    assert set(payload["non_substitutable_evidence"]) == set(
        NON_SUBSTITUTABLE_EVIDENCE_KINDS
    )
    assert policy.policy_digest().startswith("sha256:")


def test_trust_policy_accepts_honest_direct_verification() -> None:
    policy = _production_policy()
    envelope = _honest_envelope()
    result = policy.evaluate(envelope, at_time="2026-06-01T00:00:00Z")
    assert result.status is TrustEvaluationStatus.ACCEPT
    assert result.accepted
    assert result.accepted_attestation_kind == (
        AttestationKind.DIRECT_PROOF_VERIFICATION.value
    )
    assert not result.reasons


def test_trust_policy_rejects_simulation() -> None:
    policy = _production_policy(
        attestation_kind_allowlist=(
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
            AttestationKind.SIMULATION.value,
        ),
    )
    envelope = _honest_envelope(
        attestation_kind=AttestationKind.SIMULATION,
        result_status=ProofResultStatus.UNKNOWN,
    )
    result = policy.evaluate(envelope, at_time="2026-06-01T00:00:00Z")
    assert result.rejected
    assert any("simulation" in reason for reason in result.reasons)


def test_trust_policy_rejects_membership_as_theorem() -> None:
    policy = _production_policy(
        attestation_kind_allowlist=(
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
            AttestationKind.ARTIFACT_MEMBERSHIP.value,
        ),
    )
    envelope = _honest_envelope(
        attestation_kind=AttestationKind.ARTIFACT_MEMBERSHIP,
        result_status=ProofResultStatus.READY,
    )
    result = policy.evaluate(envelope, at_time="2026-06-01T00:00:00Z")
    assert result.rejected
    assert any("membership" in reason for reason in result.reasons)


def test_trust_policy_rejects_signature_as_theorem_authority_flag() -> None:
    with pytest.raises(ProofTrustPolicyError, match="signature"):
        _production_policy(accept_signature_as_theorem=True)


def test_trust_policy_rejects_membership_as_theorem_flag() -> None:
    with pytest.raises(ProofTrustPolicyError, match="membership"):
        _production_policy(accept_membership_as_theorem=True)


def test_trust_policy_cannot_authorise_membership_or_simulation() -> None:
    with pytest.raises(ProofTrustPolicyError, match="non-substitutable"):
        _production_policy(
            authoritative_attestation_kinds=(
                AttestationKind.DIRECT_PROOF_VERIFICATION.value,
                AttestationKind.ARTIFACT_MEMBERSHIP.value,
            )
        )
    with pytest.raises(ProofTrustPolicyError, match="non-substitutable|simulation"):
        _production_policy(
            authoritative_attestation_kinds=(
                AttestationKind.SIMULATION.value,
            )
        )


def test_trust_policy_requires_direct_verification_in_authoritative_set() -> None:
    with pytest.raises(ProofTrustPolicyError, match="direct-proof-verification"):
        _production_policy(
            authoritative_attestation_kinds=(
                AttestationKind.VERIFIER_EXECUTION.value,
            )
        )


def test_verifier_execution_not_authoritative_unless_allowlisted() -> None:
    policy = _production_policy(
        attestation_kind_allowlist=(
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
            AttestationKind.VERIFIER_EXECUTION.value,
        ),
        # authoritative remains direct-only by default
    )
    envelope = _honest_envelope(
        attestation_kind=AttestationKind.VERIFIER_EXECUTION,
    )
    result = policy.evaluate(envelope, at_time="2026-06-01T00:00:00Z")
    assert result.rejected
    assert any("verifier_execution" in reason for reason in result.reasons)


def test_verifier_execution_may_be_authoritative_when_explicit() -> None:
    policy = _production_policy(
        attestation_kind_allowlist=(
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
            AttestationKind.VERIFIER_EXECUTION.value,
        ),
        authoritative_attestation_kinds=(
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
            AttestationKind.VERIFIER_EXECUTION.value,
        ),
    )
    envelope = _honest_envelope(
        attestation_kind=AttestationKind.VERIFIER_EXECUTION,
    )
    result = policy.evaluate(envelope, at_time="2026-06-01T00:00:00Z")
    assert result.accepted
    # Still distinct from direct verification on the envelope.
    assert not envelope.is_theorem_authoritative()
    assert policy.treats_as_authoritative(AttestationKind.VERIFIER_EXECUTION)


def test_trust_policy_exact_root_mismatch_rejects() -> None:
    policy = _production_policy()
    envelope = _honest_envelope(corpus_root_cid=_cid("wrong-corpus"))
    result = policy.evaluate(envelope, at_time="2026-06-01T00:00:00Z")
    assert result.rejected
    assert any("corpus_root" in reason for reason in result.reasons)


def test_trust_policy_allowlist_and_minimum_profile() -> None:
    policy = _production_policy()
    bad_backend = _honest_envelope(backend_id="unknown-backend")
    # Keep circuit backend in sync for allowlist check path.
    bad_backend = _honest_envelope(
        backend_id="unknown-backend",
        circuit=CircuitBinding(
            circuit_id="legal_constraint",
            circuit_version=1,
            circuit_digest=_digest("circuit"),
            vk_id="legal_constraint_vk",
            vk_version=1,
            vk_digest=_digest("vk"),
            backend_id="unknown-backend",
            proof_system="groth16",
            public_inputs={"statement_digest": _digest("statement")},
            security_profile="legal-strict",
        ),
    )
    result = policy.evaluate(bad_backend, at_time="2026-06-01T00:00:00Z")
    assert result.rejected
    assert any("backend" in reason for reason in result.reasons)


def test_trust_policy_rejects_revoked_and_expired() -> None:
    policy = _production_policy()
    revoked = _honest_envelope(revocation_cid=_cid("revoked"))
    assert policy.evaluate(revoked, at_time="2026-06-01T00:00:00Z").rejected
    expired = _honest_envelope()
    assert policy.evaluate(expired, at_time="2028-01-01T00:00:00Z").rejected


def test_trust_policy_mutation_changes_digest() -> None:
    a = _production_policy()
    b = _production_policy(accept_simulated=True)
    assert a.policy_digest() != b.policy_digest()


def test_trust_policy_round_trip() -> None:
    policy = _production_policy()
    restored = ProofTrustPolicy.from_dict(policy.to_dict())
    assert restored.policy_digest() == policy.policy_digest()
    assert restored.to_dict() == policy.to_dict()


def test_trust_policy_raise_on_reject() -> None:
    policy = _production_policy()
    envelope = _honest_envelope(
        attestation_kind=AttestationKind.SIMULATION,
        result_status=ProofResultStatus.UNKNOWN,
    )
    # simulation not allowlisted -> reject
    with pytest.raises(ProofTrustPolicyViolation):
        policy.evaluate(
            envelope,
            at_time="2026-06-01T00:00:00Z",
            raise_on_reject=True,
        )


def test_default_production_trust_policy_is_fail_closed() -> None:
    policy = default_production_trust_policy(
        corpus_roots=(_cid("corpus-root"),),
        revocation_roots=(_cid("revocation-root"),),
    )
    assert policy.accept_simulated is False
    assert policy.world_mode is WorldMode.CLOSED
    assert policy.conflict_rule is ConflictRule.FAIL_CLOSED
    assert (
        AttestationKind.DIRECT_PROOF_VERIFICATION.value
        in policy.authoritative_attestation_kinds
    )
    honest = _honest_envelope()
    # Default policy requires circuit/vk/public inputs — honest has them.
    # No jurisdiction/tenant allowlists, so broader acceptance on scope.
    result = policy.evaluate(honest)
    assert result.accepted


def test_result_authority_mismatch_rejects() -> None:
    policy = _production_policy()
    envelope = _honest_envelope(
        result_authority=AuthorityKind.SATISFIABILITY,
        result_status=ProofResultStatus.UNSATISFIABLE,
    )
    result = policy.evaluate(envelope, at_time="2026-06-01T00:00:00Z")
    assert result.rejected
    assert any("result_authority_mismatch" in reason for reason in result.reasons)


# ---------------------------------------------------------------------------
# Coverage policy
# ---------------------------------------------------------------------------


def test_corpus_coverage_policy_requires_complete_selectors() -> None:
    policy = CorpusCoveragePolicy(
        policy_id="coverage-legal",
        required_domains=("legal",),
        required_families=("legal",),
        required_selectors=("jurisdiction", "subject", "resource"),
        require_complete=True,
        max_gap_kinds=0,
        minimum_covered_selector_count=3,
        description="legal coverage",
    )
    assert policy.interface == CORPUS_COVERAGE_POLICY_INTERFACE
    envelope = _honest_envelope()
    result = policy.evaluate_envelope(envelope)
    assert result.accepted

    incomplete = _honest_envelope(
        coverage=CoverageDeclaration(
            covered_selectors=("jurisdiction",),
            gap_kinds=("missing_subject",),
            complete=False,
        )
    )
    bad = policy.evaluate_envelope(incomplete)
    assert bad.rejected
    assert any("incomplete" in reason or "missing_selector" in reason for reason in bad.reasons)


def test_coverage_policy_round_trip() -> None:
    policy = CorpusCoveragePolicy(
        policy_id="coverage-a",
        required_selectors=("jurisdiction",),
        require_complete=False,
        max_gap_kinds=2,
        allowed_gap_kinds=("missing_temporal",),
    )
    restored = CorpusCoveragePolicy.from_dict(policy.to_dict())
    assert restored.policy_digest() == policy.policy_digest()


# ---------------------------------------------------------------------------
# Cross-cutting receipts
# ---------------------------------------------------------------------------


def test_authority_separation_receipt() -> None:
    """Evidence subset: authority separation and simulation-rejection receipt."""

    direct = _honest_envelope()
    membership = _honest_envelope(
        attestation_kind=AttestationKind.ARTIFACT_MEMBERSHIP,
        result_status=ProofResultStatus.READY,
    )
    simulation = _honest_envelope(
        attestation_kind=AttestationKind.SIMULATION,
        result_status=ProofResultStatus.UNKNOWN,
    )
    verifier = _honest_envelope(
        attestation_kind=AttestationKind.VERIFIER_EXECUTION,
    )

    policy = _production_policy(
        attestation_kind_allowlist=tuple(
            kind.value for kind in AttestationKind
        ),
    )

    receipt = {
        "direct": policy.evaluate(direct, at_time="2026-06-01T00:00:00Z").to_dict(),
        "membership": policy.evaluate(
            membership, at_time="2026-06-01T00:00:00Z"
        ).to_dict(),
        "simulation": policy.evaluate(
            simulation, at_time="2026-06-01T00:00:00Z"
        ).to_dict(),
        "verifier_execution": policy.evaluate(
            verifier, at_time="2026-06-01T00:00:00Z"
        ).to_dict(),
        "non_substitutable": sorted(non_substitutable_evidence_kinds()),
        "theorem_authoritative": {
            "direct": direct.is_theorem_authoritative(),
            "membership": membership.is_theorem_authoritative(),
            "simulation": simulation.is_theorem_authoritative(),
            "verifier_execution": verifier.is_theorem_authoritative(),
        },
    }

    assert receipt["direct"]["status"] == "accept"
    assert receipt["membership"]["status"] == "reject"
    assert receipt["simulation"]["status"] == "reject"
    assert receipt["verifier_execution"]["status"] == "reject"
    assert receipt["theorem_authoritative"]["direct"] is True
    assert receipt["theorem_authoritative"]["membership"] is False
    assert receipt["theorem_authoritative"]["simulation"] is False
    assert receipt["theorem_authoritative"]["verifier_execution"] is False
    assert receipt["non_substitutable"] == sorted(
        {
            "direct-proof-verification",
            "verifier-execution",
            "artifact-membership",
            "signature",
            "simulation",
        }
    )


def test_canonical_identity_receipt_is_stable() -> None:
    """Evidence subset: proof-envelope canonical identity receipt."""

    a = _honest_envelope()
    b = AttestedProofEnvelope.from_dict(copy.deepcopy(a.to_dict()))
    receipt = {
        "digest_a": a.identity_digest(),
        "digest_b": b.identity_digest(),
        "cid_a": a.envelope_cid,
        "cid_b": b.envelope_cid,
        "equal": a.identity_digest() == b.identity_digest(),
    }
    assert receipt["equal"] is True
    assert receipt["cid_a"] == receipt["cid_b"]


def test_trust_policy_mutation_receipt() -> None:
    """Evidence subset: trust-policy mutation receipt."""

    base = _production_policy()
    mutated = _production_policy(
        circuit_allowlist=("other-circuit",),
        world_mode=WorldMode.OPEN,
        conflict_rule=ConflictRule.REVIEW,
    )
    receipt = {
        "base_digest": base.policy_digest(),
        "mutated_digest": mutated.policy_digest(),
        "world_mode_base": base.world_mode.value,
        "world_mode_mutated": mutated.world_mode.value,
        "conflict_base": base.conflict_rule.value,
        "conflict_mutated": mutated.conflict_rule.value,
    }
    assert receipt["base_digest"] != receipt["mutated_digest"]
    assert receipt["world_mode_mutated"] == "open"
    assert receipt["conflict_mutated"] == "review"

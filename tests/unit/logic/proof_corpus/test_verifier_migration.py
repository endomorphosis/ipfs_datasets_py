"""Unit tests for independent proof verification and legacy quarantine (LIG-032).

Acceptance:

* Verify exact roots and all statement/assumption/obligation/source/build/
  compiler/solver/translation/reconstruction/proof bindings plus approved
  native or ZK proof, circuit spec/VK/public inputs, tenant/scope/time/expiry/
  supersession/revocation/coverage/parents.
* Reject producer claims, cache hits, unknown/downgraded algorithms,
  malformed/underconstrained/forged proofs, real-to-simulation fallback,
  membership-as-theorem, partial fetch and cross-tenant substitution.
* Legacy reader reports every absent binding and never grants authority.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.proof_corpus.migration import (
    LEGACY_AUTHORITY_MANIFEST_INTERFACE,
    LEGACY_PROOF_CORPUS_READER_INTERFACE,
    LegacyDisposition,
    LegacyProofCorpusError,
    LegacyProofCorpusReader,
    LegacyQuarantineRecord,
    LegacyRecordInspection,
    build_legacy_proof_corpus_reader,
    default_legacy_authority_manifest_path,
    inspect_manifest_samples,
    load_legacy_authority_manifest,
    report_absent_bindings,
)
from ipfs_datasets_py.logic.proof_corpus.model import (
    AttestationKind,
    AttestedProofEnvelope,
    CircuitBinding,
    CoverageDeclaration,
    PipelineIdentity,
    ProofResultStatus,
    ScopeBinding,
    TemporalWindow,
)
from ipfs_datasets_py.logic.proof_corpus.policy import (
    ConflictRule,
    PolicyBudget,
    ProofTrustPolicy,
    WorldMode,
)
from ipfs_datasets_py.logic.proof_corpus.schemas import ProofCorpusFamily
from ipfs_datasets_py.logic.proof_corpus.verifier import (
    ATTESTED_PROOF_VERIFIER_INTERFACE,
    REASON_ALGORITHM_DOWNGRADED,
    REASON_CACHE_HIT,
    REASON_CROSS_TENANT,
    REASON_FORGED_PROOF,
    REASON_MALFORMED_PROOF,
    REASON_MEMBERSHIP_THEOREM,
    REASON_MISSING_PROOF,
    REASON_PARTIAL_FETCH,
    REASON_PRODUCER_CLAIM,
    REASON_REAL_TO_SIM,
    REASON_UNDERCONSTRAINED,
    REASON_UNKNOWN_ALGORITHM,
    REQUIRED_AUTHORITY_BINDINGS,
    SELECTED_EVIDENCE_PACK_INTERFACE,
    AttestedProofVerifier,
    ConsumerVerificationReceipt,
    SelectedEvidenceItem,
    SelectedEvidencePack,
    VerificationStatus,
    VerifierContext,
    absent_authority_bindings,
    build_attested_proof_verifier,
    build_selected_evidence_item,
    build_selected_evidence_pack,
    build_verifier_context,
    digest_of_bytes,
    verify_selected_item,
)


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _cid(label: str) -> str:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return cid_v1_from_digest(bytes.fromhex(digest))


def _native_proof(label: str = "honest-native-proof-bytes") -> bytes:
    # At least 8 bytes; digest is bound into the envelope.
    return f"native-proof:{label}".encode("utf-8")


def _honest_envelope(**overrides: Any) -> AttestedProofEnvelope:
    proof_bytes = overrides.pop("proof_bytes", _native_proof())
    if isinstance(proof_bytes, str):
        proof_bytes = proof_bytes.encode("utf-8")
    proof_digest = overrides.pop("proof_bytes_digest", digest_of_bytes(proof_bytes))
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
        "proof_bytes_digest": proof_digest,
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
        "producer_id": "lig-032-test",
    }
    base.update(overrides)
    return AttestedProofEnvelope(**base)


def _parent_envelope() -> AttestedProofEnvelope:
    """Parent envelope whose CID matches the honest parent_cids binding."""

    # Build a distinct envelope and then re-bind the honest envelope to use
    # its CID when needed.  For parent checks we construct a real parent and
    # point honest envelopes at it.
    return _honest_envelope(
        statement_digest=_digest("parent-statement"),
        assumption_digest=_digest("parent-assumption"),
        obligation_digest=_digest("parent-obligation"),
        proof_bytes=_native_proof("parent"),
        parent_cids=(),
        coverage=CoverageDeclaration(
            covered_selectors=("jurisdiction",),
            complete=True,
        ),
        diagnostics={"notes": "parent"},
        producer_id="lig-032-parent",
    )


def _context(**overrides: Any) -> VerifierContext:
    base: dict[str, Any] = {
        "corpus_root_cid": _cid("corpus-root"),
        "revocation_root_cid": _cid("revocation-root"),
        "expected_tenant": "tenant-a",
        "expected_jurisdiction": "us-federal",
        "at_time": "2026-06-01T00:00:00Z",
        "accept_simulated": False,
        "require_native_or_zk": True,
        "require_complete_coverage": True,
    }
    base.update(overrides)
    return VerifierContext(**base)


def _honest_item(**overrides: Any) -> SelectedEvidenceItem:
    parent = overrides.pop("parent", None)
    if parent is None:
        parent = _parent_envelope()
    envelope = overrides.pop("envelope", None)
    proof_bytes = overrides.pop("native_proof_bytes", _native_proof())
    if envelope is None:
        envelope = _honest_envelope(
            parent_cids=(parent.envelope_cid,),
            proof_bytes=proof_bytes,
        )
    base: dict[str, Any] = {
        "envelope": envelope,
        "native_proof_bytes": proof_bytes,
        "parent_envelopes": (parent,),
        "fetch_complete": True,
        "cache_hit": False,
        "producer_claim_status": "",
        "claimed_algorithm": "groth16",
    }
    base.update(overrides)
    return SelectedEvidenceItem(**base)


def _trust_policy() -> ProofTrustPolicy:
    return ProofTrustPolicy(
        policy_id="trust-production",
        corpus_roots=(_cid("corpus-root"),),
        revocation_roots=(_cid("revocation-root"),),
        circuit_allowlist=("legal_constraint", "legal_constraint@v1"),
        backend_allowlist=("provekit",),
        solver_allowlist=("solver-z3",),
        compiler_allowlist=("compiler-canonical-v1",),
        security_profile_allowlist=("legal-strict",),
        attestation_kind_allowlist=(
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        ),
        authoritative_attestation_kinds=(
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        ),
        required_result_authority=AuthorityKind.THEOREM_PROOF,
        minimum_security_profile="legal-strict",
        accept_simulated=False,
        require_circuit_binding=True,
        require_vk_binding=True,
        require_public_inputs=True,
        world_mode=WorldMode.CLOSED,
        conflict_rule=ConflictRule.FAIL_CLOSED,
        budget=PolicyBudget(
            max_candidates=64,
            max_bytes=1_048_576,
            max_graph_depth=16,
            timeout_ms=5_000,
            max_backend_attempts=3,
        ),
        allowed_jurisdictions=("us-federal",),
        allowed_tenants=("tenant-a",),
    )


# ---------------------------------------------------------------------------
# Happy path / bindings
# ---------------------------------------------------------------------------


def test_honest_item_passes_and_grants_authority() -> None:
    item = _honest_item()
    context = _context()
    result = verify_selected_item(item, context)

    assert result.status is VerificationStatus.PASS
    assert result.grants_authority is True
    assert result.reasons == ()
    assert result.absent_bindings == ()
    assert result.evidence_kind in {"native", "both"}


def test_honest_pack_receipt_grants_authority() -> None:
    item = _honest_item()
    context = _context()
    pack = SelectedEvidencePack(items=(item,), context=context)
    verifier = AttestedProofVerifier(context=context)
    bound, receipt = verifier.verify_pack(pack)

    assert receipt.status is VerificationStatus.PASS
    assert receipt.grants_authority is True
    assert receipt.corpus_root_cid == _cid("corpus-root")
    assert receipt.revocation_root_cid == _cid("revocation-root")
    assert bound.receipt is not None
    assert bound.receipt.content_cid == receipt.content_cid
    receipt.verify_integrity()
    bound.verify_integrity()


def test_verifier_binds_all_required_authority_fields() -> None:
    item = _honest_item()
    envelope = item.envelope
    assert isinstance(envelope, AttestedProofEnvelope)
    absent = absent_authority_bindings(envelope)
    assert absent == ()
    for binding in REQUIRED_AUTHORITY_BINDINGS:
        assert binding


def test_selected_pack_interfaces_and_round_trip() -> None:
    item = _honest_item()
    context = _context()
    pack = build_selected_evidence_pack(items=(item,), context=context)
    assert pack.interface == SELECTED_EVIDENCE_PACK_INTERFACE
    restored = SelectedEvidencePack.from_dict(pack.to_dict())
    assert restored.content_digest == pack.content_digest
    restored.verify_integrity()


def test_build_helpers() -> None:
    context = build_verifier_context(
        corpus_root_cid=_cid("corpus-root"),
        expected_tenant="tenant-a",
    )
    verifier = build_attested_proof_verifier(context=context)
    assert verifier.interface == ATTESTED_PROOF_VERIFIER_INTERFACE
    parent = _parent_envelope()
    proof = _native_proof("helper")
    envelope = _honest_envelope(
        parent_cids=(parent.envelope_cid,), proof_bytes=proof
    )
    item = build_selected_evidence_item(
        envelope=envelope,
        native_proof_bytes=proof,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
    )
    assert item.item_id == envelope.envelope_cid


# ---------------------------------------------------------------------------
# Rejection cases (acceptance)
# ---------------------------------------------------------------------------


def test_reject_producer_claim() -> None:
    item = _honest_item(producer_claim_status="proved")
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert result.status is not VerificationStatus.PASS
    assert REASON_PRODUCER_CLAIM in result.reasons


def test_reject_cache_hit() -> None:
    item = _honest_item(cache_hit=True)
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert REASON_CACHE_HIT in result.reasons


def test_reject_unknown_algorithm() -> None:
    item = _honest_item(claimed_algorithm="vibes-prover-9000")
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert REASON_UNKNOWN_ALGORITHM in result.reasons


def test_reject_algorithm_downgrade_to_simulation() -> None:
    item = _honest_item(
        claimed_algorithm="simulated",
        previous_algorithm="groth16",
        real_to_simulation_fallback=True,
    )
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert REASON_ALGORITHM_DOWNGRADED in result.reasons
    assert REASON_REAL_TO_SIM in result.reasons


def test_reject_forged_native_proof() -> None:
    item = _honest_item(native_proof_bytes=b"forged-proof-bytes-XXXX")
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert REASON_FORGED_PROOF in result.reasons or REASON_NATIVE_DIGEST in (
        r for r in result.reasons
    )


def test_reject_malformed_underconstrained_proof() -> None:
    # Short payload is underconstrained; also use explicit marker.
    parent = _parent_envelope()
    proof = b"malformed"
    envelope = _honest_envelope(
        parent_cids=(parent.envelope_cid,),
        proof_bytes=proof,
        public_inputs={},
        circuit=CircuitBinding(
            circuit_id="legal_constraint",
            circuit_version=1,
            circuit_digest=_digest("circuit"),
            vk_id="legal_constraint_vk",
            vk_version=1,
            vk_digest=_digest("vk"),
            backend_id="provekit",
            proof_system="groth16",
            public_inputs={},
            security_profile="legal-strict",
        ),
    )
    item = SelectedEvidenceItem(
        envelope=envelope,
        native_proof_bytes=proof,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
    )
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert (
        REASON_UNDERCONSTRAINED in result.reasons
        or REASON_MALFORMED_PROOF in result.reasons
    )


def test_reject_real_to_simulation_fallback() -> None:
    item = _honest_item(
        real_to_simulation_fallback=True,
        zk_attestation={
            "metadata": {"backend": "simulated", "is_simulated": True},
            "valid": True,
        },
    )
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert REASON_REAL_TO_SIM in result.reasons


def test_reject_membership_as_theorem() -> None:
    parent = _parent_envelope()
    proof = _native_proof("membership")
    envelope = _honest_envelope(
        parent_cids=(parent.envelope_cid,),
        proof_bytes=proof,
        attestation_kind=AttestationKind.ARTIFACT_MEMBERSHIP,
        result_status=ProofResultStatus.READY,
    )
    item = SelectedEvidenceItem(
        envelope=envelope,
        native_proof_bytes=proof,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
    )
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert REASON_MEMBERSHIP_THEOREM in result.reasons


def test_reject_partial_fetch() -> None:
    item = _honest_item(fetch_complete=False)
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert REASON_PARTIAL_FETCH in result.reasons


def test_reject_cross_tenant_substitution() -> None:
    parent = _parent_envelope()
    proof = _native_proof("cross-tenant")
    envelope = _honest_envelope(
        parent_cids=(parent.envelope_cid,),
        proof_bytes=proof,
        scope=ScopeBinding(
            jurisdiction="us-federal",
            tenant="tenant-b",
            subject_ids=("subject-alice",),
            resource_ids=("resource-records",),
        ),
    )
    item = SelectedEvidenceItem(
        envelope=envelope,
        native_proof_bytes=proof,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
        claimed_tenant="tenant-a",
    )
    result = verify_selected_item(item, _context(expected_tenant="tenant-a"))
    assert result.grants_authority is False
    assert REASON_CROSS_TENANT in result.reasons


def test_reject_missing_native_and_zk_proof() -> None:
    parent = _parent_envelope()
    envelope = _honest_envelope(parent_cids=(parent.envelope_cid,))
    item = SelectedEvidenceItem(
        envelope=envelope,
        native_proof_bytes=None,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
    )
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert REASON_MISSING_PROOF in result.reasons


def test_reject_wrong_corpus_root() -> None:
    item = _honest_item()
    result = verify_selected_item(
        item, _context(corpus_root_cid=_cid("other-corpus"))
    )
    assert result.grants_authority is False
    assert any("root_mismatch" in reason for reason in result.reasons)


def test_reject_revoked_and_expired() -> None:
    parent = _parent_envelope()
    proof = _native_proof("revoked")
    envelope = _honest_envelope(
        parent_cids=(parent.envelope_cid,),
        proof_bytes=proof,
        revocation_cid=_cid("revocation-entry"),
        temporal=TemporalWindow(
            effective_at="2020-01-01T00:00:00Z",
            expires_at="2021-01-01T00:00:00Z",
        ),
    )
    item = SelectedEvidenceItem(
        envelope=envelope,
        native_proof_bytes=proof,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
    )
    result = verify_selected_item(item, _context(at_time="2026-06-01T00:00:00Z"))
    assert result.grants_authority is False
    assert "envelope_revoked" in result.reasons
    assert "envelope_not_effective" in result.reasons


def test_reject_superseded() -> None:
    parent = _parent_envelope()
    proof = _native_proof("superseded")
    envelope = _honest_envelope(
        parent_cids=(parent.envelope_cid,),
        proof_bytes=proof,
        supersession_cid=_cid("newer-envelope"),
    )
    item = SelectedEvidenceItem(
        envelope=envelope,
        native_proof_bytes=proof,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
    )
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert "envelope_superseded" in result.reasons


def test_reject_missing_parent_binding() -> None:
    proof = _native_proof("no-parent")
    envelope = _honest_envelope(
        proof_bytes=proof,
        parent_cids=(_cid("missing-parent"),),
    )
    item = SelectedEvidenceItem(
        envelope=envelope,
        native_proof_bytes=proof,
        parent_envelopes=(),
        claimed_algorithm="groth16",
    )
    result = verify_selected_item(item, _context())
    assert result.grants_authority is False
    assert any("parent" in reason for reason in result.reasons)


def test_zk_simulated_rejected_when_not_accepted() -> None:
    parent = _parent_envelope()
    proof = _native_proof("zk-sim")
    envelope = _honest_envelope(parent_cids=(parent.envelope_cid,), proof_bytes=proof)
    item = SelectedEvidenceItem(
        envelope=envelope,
        native_proof_bytes=proof,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
        zk_attestation={
            "metadata": {"backend": "simulated", "is_simulated": True},
            "public_inputs": dict(envelope.public_inputs),
            "valid": True,
        },
    )
    result = verify_selected_item(item, _context(accept_simulated=False))
    assert result.grants_authority is False
    assert any(
        reason in result.reasons
        for reason in (REASON_REAL_TO_SIM, "zk_simulated_rejected")
    )


def test_trust_policy_rejection_surfaces() -> None:
    parent = _parent_envelope()
    proof = _native_proof("policy")
    envelope = _honest_envelope(
        parent_cids=(parent.envelope_cid,),
        proof_bytes=proof,
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
            public_inputs={
                "statement_digest": _digest("statement"),
                "corpus_root": _cid("corpus-root"),
            },
            security_profile="legal-strict",
        ),
    )
    item = SelectedEvidenceItem(
        envelope=envelope,
        native_proof_bytes=proof,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
    )
    context = _context(trust_policy=_trust_policy())
    result = verify_selected_item(item, context)
    assert result.grants_authority is False
    assert any("trust_policy" in reason for reason in result.reasons)


def test_receipt_never_grants_when_any_item_fails() -> None:
    good = _honest_item()
    bad = _honest_item(cache_hit=True, item_id="bad-item")
    # Ensure distinct envelopes.
    parent = _parent_envelope()
    proof = _native_proof("bad")
    bad_env = _honest_envelope(
        parent_cids=(parent.envelope_cid,),
        proof_bytes=proof,
        solver_id="solver-vampire",
    )
    bad = SelectedEvidenceItem(
        envelope=bad_env,
        native_proof_bytes=proof,
        parent_envelopes=(parent,),
        claimed_algorithm="groth16",
        cache_hit=True,
        item_id="bad-item",
    )
    context = _context()
    pack = SelectedEvidencePack(items=(good, bad), context=context)
    verifier = AttestedProofVerifier(context=context)
    _, receipt = verifier.verify_pack(pack)
    assert receipt.grants_authority is False
    assert receipt.status is not VerificationStatus.PASS
    assert len(receipt.item_results) == 2


def test_item_result_cannot_claim_authority_on_reject() -> None:
    from ipfs_datasets_py.logic.proof_corpus.verifier import (
        ItemVerificationResult,
        ProofVerifierError,
    )

    with pytest.raises(ProofVerifierError, match="grants_authority"):
        ItemVerificationResult(
            item_id="x",
            envelope_cid=_cid("env"),
            status=VerificationStatus.REJECT,
            grants_authority=True,
        )


# ---------------------------------------------------------------------------
# Legacy reader / quarantine
# ---------------------------------------------------------------------------


def test_legacy_reader_reports_every_absent_binding() -> None:
    record = {
        "content_cid": _cid("legacy"),
        "producer_status": "proved",
        "cache_hit": True,
    }
    absent = report_absent_bindings(record)
    assert set(absent) == set(REQUIRED_AUTHORITY_BINDINGS)
    reader = LegacyProofCorpusReader()
    inspection = reader.inspect_record(record, record_id="legacy-1")
    assert inspection.grants_authority is False
    assert set(inspection.absent_bindings) == set(REQUIRED_AUTHORITY_BINDINGS)
    assert inspection.disposition is LegacyDisposition.INCOMPLETE
    assert reader.grants_authority_for(record) is False
    assert reader.any_authority_granted() is False


def test_legacy_reader_never_grants_even_if_fields_present() -> None:
    # Fabricate a "complete" legacy shape using aliases.
    record = {
        "statement_digest": _digest("s"),
        "assumption_digest": _digest("a"),
        "obligation_digest": _digest("o"),
        "source_snapshot_cid": _cid("src"),
        "build_manifest_cid": _cid("build"),
        "compiler_id": "c",
        "solver_id": "s",
        "translation_id": "t",
        "reconstruction_id": "r",
        "proof_artifact_cid": _cid("proof"),
        "proof_bytes_digest": _digest("pb"),
        "corpus_root_cid": _cid("corpus"),
        "revocation_root_cid": _cid("rev"),
        "policy_id": "p",
        "attestation_kind": "direct-proof-verification",
        "result_authority": "theorem_proof",
        "circuit_id": "circ",
        "circuit_digest": _digest("cd"),
        "vk_id": "vk",
        "vk_digest": _digest("vd"),
        "public_inputs": {"statement_digest": _digest("s")},
        "tenant": "tenant-a",
        "jurisdiction": "us-federal",
        "effective_at": "2026-01-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z",
        "coverage": {"complete": True},
        "parent_cids": [_cid("parent")],
        "security_profile": "legal-strict",
        "backend_id": "provekit",
    }
    reader = LegacyProofCorpusReader()
    inspection = reader.inspect_record(record, record_id="complete-legacy")
    assert inspection.absent_bindings == ()
    assert inspection.grants_authority is False
    assert inspection.disposition is LegacyDisposition.NON_AUTHORITATIVE
    assert reader.grants_authority_for(record) is False


def test_legacy_quarantine_is_non_destructive() -> None:
    record = {"producer_status": "proved", "family": "legal"}
    original = copy.deepcopy(record)
    reader = build_legacy_proof_corpus_reader()
    quarantine = reader.quarantine_record(record, record_id="q1")
    assert record == original  # source untouched
    assert quarantine.grants_authority is False
    assert quarantine.disposition is LegacyDisposition.AWAITING_REBUILD
    assert quarantine.absent_bindings
    assert quarantine.quarantine_cid.startswith("b")
    restored = LegacyQuarantineRecord.from_dict(quarantine.to_dict())
    assert restored.quarantine_digest == quarantine.quarantine_digest


def test_legacy_inspection_cannot_set_grants_authority() -> None:
    with pytest.raises(LegacyProofCorpusError, match="never grants"):
        LegacyRecordInspection(
            record_id="x",
            absent_bindings=("statement_digest",),
            grants_authority=True,
        )


def test_legacy_authority_manifest_fixture() -> None:
    path = default_legacy_authority_manifest_path()
    assert path.is_file(), f"missing fixture: {path}"
    manifest = load_legacy_authority_manifest(path)
    assert manifest["interface"] == LEGACY_AUTHORITY_MANIFEST_INTERFACE
    assert set(manifest["required_bindings"]) == set(REQUIRED_AUTHORITY_BINDINGS)
    assert manifest["quarantine_policy"]["grants_authority"] is False
    assert manifest["quarantine_policy"]["mutate_source"] is False

    inspections = inspect_manifest_samples(manifest)
    assert len(inspections) == 3
    for inspection in inspections:
        assert inspection.grants_authority is False
        assert inspection.absent_bindings
        assert set(inspection.absent_bindings).issubset(
            set(REQUIRED_AUTHORITY_BINDINGS)
        )


def test_legacy_reader_interface_constant() -> None:
    reader = LegacyProofCorpusReader()
    assert reader.interface == LEGACY_PROOF_CORPUS_READER_INTERFACE
    summary = reader.quarantine_summary()
    assert summary["grants_authority"] is False


def test_legacy_quarantine_many_and_summary() -> None:
    records = [
        {"record_id": "a", "producer_status": "ok"},
        {"record_id": "b", "compiler_id": "only-compiler"},
    ]
    reader = LegacyProofCorpusReader()
    quarantines = reader.quarantine_incomplete(records)
    assert len(quarantines) == 2
    assert all(not q.grants_authority for q in quarantines)
    payload = reader.to_dict()
    assert payload["grants_authority"] is False
    assert payload["quarantine"]


def test_load_manifest_rejects_bad_interface() -> None:
    with pytest.raises(LegacyProofCorpusError, match="interface"):
        load_legacy_authority_manifest(
            payload={
                "interface": "Wrong@1",
                "schema_version": "legacy-authority-manifest/v1",
                "required_bindings": ["statement_digest"],
            }
        )


def test_inspect_path_read_only(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text('{"producer_status":"proved","family":"legal"}', encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    reader = LegacyProofCorpusReader()
    inspection = reader.inspect_path(path)
    after = path.read_text(encoding="utf-8")
    assert before == after
    assert inspection.grants_authority is False
    assert inspection.source_path == str(path)
    assert inspection.absent_bindings


# ---------------------------------------------------------------------------
# Integration: legacy incomplete cannot enter verifier authority
# ---------------------------------------------------------------------------


def test_legacy_incomplete_cannot_construct_authoritative_envelope() -> None:
    """Incomplete legacy rows are not AttestedProofEnvelope authority."""

    with pytest.raises(Exception):
        AttestedProofEnvelope(
            statement_digest="",
            assumption_digest="",
            obligation_digest="",
            domain="legal",
            logic_family="deontic",
            result_authority=AuthorityKind.THEOREM_PROOF,
            attestation_kind=AttestationKind.DIRECT_PROOF_VERIFICATION,
        )


def test_consumer_receipt_round_trip() -> None:
    item = _honest_item()
    context = _context()
    verifier = AttestedProofVerifier(context=context)
    pack = SelectedEvidencePack(items=(item,), context=context)
    _, receipt = verifier.verify_pack(pack)
    restored = ConsumerVerificationReceipt.from_dict(receipt.to_dict())
    assert restored.content_cid == receipt.content_cid
    assert restored.grants_authority is True
    restored.verify_integrity()

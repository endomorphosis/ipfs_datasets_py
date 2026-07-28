"""Unit tests for proof-corpus ZKP attestation verify helper (LIG-013).

Acceptance:

* Honest legal fixture verifies when a ZKP attestation is present (pass).
* Missing ZKP is ``absent``, never ``pass``.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.proof_corpus.attest import (
    PROOF_CORPUS_ATTEST_INTERFACE,
    PROOF_CORPUS_ATTEST_SCHEMA_VERSION,
    AttestationStatus,
    AttestationVerifyResult,
    ProofCorpusAttestError,
    build_legal_statement_for_envelope,
    clear_attestation,
    constraint_payload_for_envelope,
    get_attestation,
    has_attestation,
    prove_legal_envelope_attestation,
    put_attestation,
    verify_attestation,
    verify_attestation_for_envelope,
)
from ipfs_datasets_py.logic.proof_corpus.schemas import (
    ArtifactEnvelope,
    ProofCorpusFamily,
)
from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore
from ipfs_datasets_py.logic.zkp.statements.legal_constraint import (
    LEGAL_CONSTRAINT_ZKP_INTERFACE,
    LegalConstraintAttestation,
    verify_legal_constraint_attestation,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"

INTENT_FIXTURES = FIXTURE_ROOT / "intent_ir" / "admissibility"
LEGAL_FIXTURES = FIXTURE_ROOT / "legal_ir" / "proof_cache"
SECURITY_FIXTURES = FIXTURE_ROOT / "security_ir" / "constraint_cache"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _intent_artifact() -> FormalizationArtifact:
    path = INTENT_FIXTURES / "formal_artifacts" / "benign_skill.json"
    return FormalizationArtifact.from_dict(_load_json(path))


def _intent_profile() -> str:
    case = next(
        item
        for item in _load_json(INTENT_FIXTURES / "manifest.json")["cases"]
        if item["case_id"] == "benign_skill"
    )
    return str(case["profile_id"])


def _legal_record() -> dict[str, Any]:
    return _load_json(LEGAL_FIXTURES / "us_code_552_record.json")


def _security_record() -> dict[str, Any]:
    return _load_json(SECURITY_FIXTURES / "exchange_record.json")


def _legal_envelope() -> ArtifactEnvelope:
    return ArtifactEnvelope.from_legal_record(_legal_record())


def _intent_envelope() -> ArtifactEnvelope:
    return ArtifactEnvelope.from_intent_artifact(
        _intent_artifact(), profile=_intent_profile()
    )


def _security_envelope() -> ArtifactEnvelope:
    return ArtifactEnvelope.from_security_record(_security_record())


def _prove_legal(
    envelope: ArtifactEnvelope, *, seed: bytes | str = "fixture-seed"
) -> LegalConstraintAttestation:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return prove_legal_envelope_attestation(envelope, seed=seed)


def test_attest_interface_and_schema_versions_are_pinned() -> None:
    assert PROOF_CORPUS_ATTEST_INTERFACE == "ProofCorpusAttest@1"
    assert PROOF_CORPUS_ATTEST_SCHEMA_VERSION == "proof-corpus-attest/v1"
    result = AttestationVerifyResult(
        status=AttestationStatus.ABSENT,
        content_cid="bafkreiabsentfixture0000000000000000000001",
        profile="legal-strict",
        reason="zkp_missing",
    )
    assert result.interface == "ProofCorpusAttest@1"
    assert result.schema_version == "proof-corpus-attest/v1"
    assert result.is_absent is True
    assert result.is_pass is False
    assert result.ok is False


def test_missing_zkp_is_absent_not_pass() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    result = verify_attestation(store, legal.content_cid, legal.profile)
    assert result.status is AttestationStatus.ABSENT
    assert result.is_absent is True
    assert result.is_pass is False
    assert result.ok is False
    assert result.reason == "zkp_missing"
    assert result.family == "legal"
    assert result.content_cid == legal.content_cid
    assert result.profile == legal.profile


def test_missing_zkp_for_envelope_helper_is_absent() -> None:
    legal = _legal_envelope()
    result = verify_attestation_for_envelope(legal, legal.profile)
    assert result.status is AttestationStatus.ABSENT
    assert result.ok is False
    assert result.reason == "zkp_missing"


def test_has_attestation_false_when_missing() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    assert has_attestation(store, legal.content_cid) is False
    assert get_attestation(store, legal.content_cid) is None


def test_honest_legal_fixture_verifies_when_present_inline() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    attestation = _prove_legal(legal)
    assert verify_legal_constraint_attestation(attestation) is True
    result = verify_attestation(
        store,
        legal.content_cid,
        legal.profile,
        attestation=attestation,
    )
    assert result.status is AttestationStatus.PASS
    assert result.is_pass is True
    assert result.ok is True
    assert result.family == ProofCorpusFamily.LEGAL.value
    assert result.reason == "zkp_verified"
    assert result.statement_digest == attestation.statement_digest
    assert result.is_simulated is True
    assert result.attestation_interface == LEGAL_CONSTRAINT_ZKP_INTERFACE
    assert result.backend == "simulated"


def test_honest_legal_fixture_verifies_when_present_via_put() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    attestation = _prove_legal(legal)
    put_attestation(store, legal.content_cid, attestation)
    assert has_attestation(store, legal.content_cid) is True
    result = verify_attestation(store, legal.content_cid, legal.profile)
    assert result.status is AttestationStatus.PASS
    assert result.ok is True
    assert result.reason == "zkp_verified"


def test_honest_legal_fixture_verifies_on_disk_store(tmp_path: Path) -> None:
    store = ProofCorpusStore(root=tmp_path)
    legal = store.put(_legal_envelope())
    attestation = _prove_legal(legal)
    put_attestation(store, legal.content_cid, attestation)

    reloaded = ProofCorpusStore(root=tmp_path)
    result = verify_attestation(
        reloaded, legal.content_cid, legal.profile
    )
    assert result.status is AttestationStatus.PASS
    assert result.ok is True
    assert has_attestation(reloaded, legal.content_cid) is True


def test_prove_and_verify_for_envelope_helper() -> None:
    legal = _legal_envelope()
    attestation = _prove_legal(legal)
    result = verify_attestation_for_envelope(
        legal, legal.profile, attestation=attestation
    )
    assert result.status is AttestationStatus.PASS
    assert result.ok is True


def test_tampered_proof_fails() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    attestation = _prove_legal(legal)

    # Corrupt statement_digest embedding region in the simulated proof layout.
    mutated = bytearray(attestation.proof_data)
    mutated[40] ^= 0xFF
    tampered = LegalConstraintAttestation(
        statement=attestation.statement,
        proof_data=bytes(mutated),
        public_inputs=dict(attestation.public_inputs),
        metadata=dict(attestation.metadata),
        statement_digest=attestation.statement_digest,
        timestamp=attestation.timestamp,
    )
    result = verify_attestation(
        store,
        legal.content_cid,
        legal.profile,
        attestation=tampered,
    )
    assert result.status is AttestationStatus.FAIL
    assert result.ok is False
    assert result.reason == "zkp_verify_failed"


def test_profile_mismatch_fails() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    attestation = _prove_legal(legal)
    result = verify_attestation(
        store,
        legal.content_cid,
        "zkp-required",
        attestation=attestation,
    )
    assert result.status is AttestationStatus.FAIL
    assert result.ok is False
    assert result.reason == "profile_envelope_mismatch"


def test_constraint_binding_mismatch_fails() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    other = store.put(_security_envelope())
    attestation = _prove_legal(legal)

    # Honest legal proof against a different legal envelope (constraint drift).
    other_legal = ArtifactEnvelope.from_legal_record(
        _load_json(LEGAL_FIXTURES / "us_code_553_record.json")
    )
    other_legal = store.put(other_legal)
    result = verify_attestation(
        store,
        other_legal.content_cid,
        other_legal.profile,
        attestation=attestation,
    )
    assert result.status is AttestationStatus.FAIL
    assert result.ok is False
    assert "mismatch" in result.reason
    assert result.status is not AttestationStatus.PASS

    # Security family with a legal ZKP present still fails closed.
    sec_result = verify_attestation(
        store,
        other.content_cid,
        other.profile,
        attestation=attestation,
    )
    assert sec_result.status is AttestationStatus.FAIL
    assert sec_result.family is ProofCorpusFamily.SECURITY or (
        sec_result.family == ProofCorpusFamily.SECURITY.value
    )


def test_intent_envelope_with_present_zkp_fails_unsupported_family() -> None:
    store = ProofCorpusStore()
    intent = store.put(_intent_envelope())
    legal = _legal_envelope()
    attestation = _prove_legal(legal)
    result = verify_attestation(
        store,
        intent.content_cid,
        intent.profile,
        attestation=attestation,
    )
    assert result.status is AttestationStatus.FAIL
    assert result.ok is False


def test_unknown_envelope_cid_fails() -> None:
    store = ProofCorpusStore()
    result = verify_attestation(
        store,
        "bafkreimissingenvelope00000000000000000000001",
        "legal-strict",
    )
    assert result.status is AttestationStatus.FAIL
    assert "envelope_not_found" in result.reason


def test_simulated_rejected_when_require_zkp_verify() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    attestation = _prove_legal(legal)
    result = verify_attestation(
        store,
        legal.content_cid,
        legal.profile,
        attestation=attestation,
        require_zkp_verify=True,
        accept_simulated_zkp=False,
    )
    assert result.status is AttestationStatus.FAIL
    assert result.reason == "simulated_zkp_rejected"
    assert result.ok is False


def test_require_zkp_and_accept_simulated_raises() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    with pytest.raises(ProofCorpusAttestError, match="accept_simulated"):
        verify_attestation(
            store,
            legal.content_cid,
            legal.profile,
            require_zkp_verify=True,
            accept_simulated_zkp=True,
        )


def test_missing_still_absent_under_zkp_required_knobs() -> None:
    """Even under zkp-required knobs, missing proof is absent — not fail/pass."""

    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    result = verify_attestation(
        store,
        legal.content_cid,
        legal.profile,
        require_zkp_verify=True,
        accept_simulated_zkp=False,
    )
    assert result.status is AttestationStatus.ABSENT
    assert result.reason == "zkp_missing"
    assert result.ok is False


def test_constraint_payload_is_deterministic() -> None:
    legal = _legal_envelope()
    a = constraint_payload_for_envelope(legal)
    b = constraint_payload_for_envelope(legal.to_dict())
    assert a == b
    assert a["content_cid"] == legal.content_cid
    assert a["source_digest"] == legal.source_digest


def test_build_legal_statement_binds_envelope() -> None:
    legal = _legal_envelope()
    statement, witness = build_legal_statement_for_envelope(legal)
    assert witness.binds_statement(statement)
    assert statement.profile == legal.profile
    assert statement.source_digest == legal.source_digest
    assert statement.artifact_cid == legal.artifact_cid
    assert statement.jurisdiction == legal.jurisdiction


def test_build_legal_statement_rejects_non_legal() -> None:
    intent = _intent_envelope()
    with pytest.raises(ProofCorpusAttestError, match="legal envelope"):
        build_legal_statement_for_envelope(intent)


def test_clear_attestation_restores_absent() -> None:
    store = ProofCorpusStore()
    legal = store.put(_legal_envelope())
    put_attestation(store, legal.content_cid, _prove_legal(legal))
    assert verify_attestation(store, legal.content_cid, legal.profile).ok
    assert clear_attestation(store, legal.content_cid) is True
    result = verify_attestation(store, legal.content_cid, legal.profile)
    assert result.status is AttestationStatus.ABSENT
    assert result.ok is False


def test_result_round_trip_dict() -> None:
    original = AttestationVerifyResult(
        status=AttestationStatus.PASS,
        content_cid="bafkreiverifyresultfixture00000000000000001",
        profile="legal-strict",
        family="legal",
        reason="zkp_verified",
        statement_digest=(
            "sha256:abababababababababababababababab"
            "abababababababababababababababab"
        ),
        is_simulated=True,
        attestation_interface=LEGAL_CONSTRAINT_ZKP_INTERFACE,
        backend="simulated",
    )
    restored = AttestationVerifyResult.from_dict(original.to_dict())
    assert restored.status is AttestationStatus.PASS
    assert restored.content_cid == original.content_cid
    assert restored.statement_digest == original.statement_digest
    assert restored.is_simulated is True

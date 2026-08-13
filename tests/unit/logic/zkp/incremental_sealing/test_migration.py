"""Regression tests for IPS-012 public exports and legacy receipt migration."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing import (
    MIGRATION_SUBSET,
    PUBLIC_API_SUBSET,
    classify_legacy_receipt,
    closed_legacy_assurances,
    closed_legacy_path_families,
    closed_migration_dispositions,
    known_legacy_path_matrix,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.evidence import (
    EvidenceClass,
    IntegrityCommitment,
    SignedExecutionReceipt,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.migration import (
    LEGACY_PATH_FAMILIES,
    LegacyAssurance,
    MigrationDisposition,
    MigrationError,
)

_DIGEST = "sha256:" + ("ab" * 32)
_DIGEST_B = "sha256:" + ("cd" * 32)


# ---------------------------------------------------------------------------
# Public API freeze
# ---------------------------------------------------------------------------


def test_public_api_and_migration_subsets() -> None:
    assert PUBLIC_API_SUBSET == "ips/datasets-public-api@1"
    assert MIGRATION_SUBSET == "ips/legacy-receipt-migration@1"
    assert closed_migration_dispositions() == {"accept", "adapt", "reject"}
    assert "integrity_only" in closed_legacy_assurances()
    assert "simulated" in closed_legacy_assurances()
    assert closed_legacy_path_families() == frozenset(LEGACY_PATH_FAMILIES)
    matrix = known_legacy_path_matrix()
    assert matrix["subset"] == MIGRATION_SUBSET
    assert set(matrix["families"]) == set(LEGACY_PATH_FAMILIES)


def test_lazy_public_exports_resolve() -> None:
    package = importlib.import_module(
        "ipfs_datasets_py.logic.zkp.incremental_sealing"
    )
    assert package.ProofUnit is not None
    assert package.ProofCacheKey is not None
    assert package.VerificationRequirementManifest is not None
    assert package.DirectExecutionStatement is not None
    assert package.RepositoryProofRoot is not None
    assert package.classify_legacy_receipt is classify_legacy_receipt
    with pytest.raises(AttributeError, match="has no attribute"):
        _ = package.not_a_public_export  # type: ignore[attr-defined]


def test_cold_package_import_is_hermetic() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                "assert 'multiformats' not in sys.modules; "
                "assert 'py_ecc' not in sys.modules; "
                "mod = importlib.import_module("
                "'ipfs_datasets_py.logic.zkp.incremental_sealing'"
                "); "
                "assert mod.PUBLIC_API_SUBSET == 'ips/datasets-public-api@1'; "
                "assert mod.MIGRATION_SUBSET == 'ips/legacy-receipt-migration@1'; "
                # Lazy: package import must not pull optional CID provider or provers.
                "assert 'multiformats' not in sys.modules; "
                "assert 'ipfs_datasets_py.logic.software_contracts.content' "
                "not in sys.modules; "
                "assert 'provekit' not in sys.modules; "
                "assert 'py_ecc' not in sys.modules; "
                # Resolving migration stays hermetic.
                "fn = mod.classify_legacy_receipt; "
                "result = fn({'digest': 'sha256:' + ('11' * 32), "
                "'cid': 'sha256:' + ('22' * 32)}); "
                "assert result.disposition.value == 'adapt'; "
                "assert 'multiformats' not in sys.modules; "
                "assert 'provekit' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


# ---------------------------------------------------------------------------
# Canonical accept path
# ---------------------------------------------------------------------------


def test_canonical_integrity_commitment_is_accepted() -> None:
    evidence = IntegrityCommitment(
        digest=_DIGEST,
        cid=_DIGEST_B,
        merkle_inclusion="leaf:0",
        byte_length=32,
    )
    result = classify_legacy_receipt(evidence.to_canonical())
    assert result.disposition is MigrationDisposition.ACCEPT
    assert result.path_family == "incremental_sealing_canonical"
    assert result.assurance is LegacyAssurance.INTEGRITY_ONLY
    assert result.target_evidence_class == EvidenceClass.INTEGRITY_COMMITMENT.value
    assert result.production_seal_allowed is False
    assert result.adapted_payload is not None
    assert result.adapted_payload["evidence_class"] == (
        EvidenceClass.INTEGRITY_COMMITMENT.value
    )


def test_canonical_signed_receipt_is_accepted() -> None:
    evidence = SignedExecutionReceipt(
        signer_id="allowlist/operator-1",
        receipt_digest=_DIGEST,
        signature="ed25519:sig-valid",
        statement="pytest node completed",
    )
    result = classify_legacy_receipt(evidence.to_canonical())
    assert result.disposition is MigrationDisposition.ACCEPT
    assert result.assurance is LegacyAssurance.SIGNED_RECEIPT
    assert result.production_seal_allowed is True


def test_malformed_canonical_claim_is_rejected() -> None:
    result = classify_legacy_receipt(
        {
            "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
            "schema": (
                "ipfs_datasets_py/logic/zkp/incremental_sealing/evidence/"
                "integrity-commitment@1"
            ),
            "digest": "not-a-digest",
        }
    )
    assert result.disposition is MigrationDisposition.REJECT
    assert result.path_family == "incremental_sealing_canonical"
    assert any("failed canonical parse" in reason for reason in result.reasons)


# ---------------------------------------------------------------------------
# Inventory legacy families
# ---------------------------------------------------------------------------


def test_unsigned_test_execution_certificate_is_structural() -> None:
    result = classify_legacy_receipt(
        {
            "interface": "TestProofCertificate@1",
            "schema": "ipfs_accelerate_py/agent-supervisor/test-proof-certificate@1",
            "certificate_id": "cert-1",
            "proof_artifact_cid": _DIGEST,
            "execution_key_cid": _DIGEST_B,
            "verifying_key_cid": _DIGEST,
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.path_family == "test_execution_certificate"
    assert result.assurance is LegacyAssurance.STRUCTURAL
    assert result.production_seal_allowed is False
    assert result.target_evidence_class == EvidenceClass.INTEGRITY_COMMITMENT.value
    assert any("not signed receipts" in reason for reason in result.reasons)


def test_signed_test_execution_certificate_adapts_to_signed_receipt() -> None:
    result = classify_legacy_receipt(
        {
            "interface": "TestProofCertificate@1",
            "certificate_id": "cert-2",
            "proof_artifact_cid": _DIGEST,
            "execution_key_cid": _DIGEST_B,
            "signature": "ed25519:abc",
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.assurance is LegacyAssurance.SIGNED_RECEIPT
    assert result.production_seal_allowed is True


def test_test_pass_statement_is_predicate_only() -> None:
    result = classify_legacy_receipt(
        {
            "interface": "TestPassStatementV1",
            "schema": "test-pass-public-inputs@1",
            "receipt_cid": _DIGEST,
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.path_family == "test_pass_statement"
    assert result.assurance is LegacyAssurance.PREDICATE_ONLY
    assert result.production_seal_allowed is False
    assert result.adapted_payload is not None
    assert result.adapted_payload["zk_circuit_implemented"] is False


def test_proof_receipt_attestation_without_backend_is_structural() -> None:
    result = classify_legacy_receipt(
        {
            "family": "proof_receipt_attestation",
            "module": "logic/bridge/proof_receipt_attestation.py",
            "callback": "attest",
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.path_family == "proof_receipt_attestation"
    assert result.assurance is LegacyAssurance.STRUCTURAL
    assert result.production_seal_allowed is False


def test_proof_receipt_attestation_with_real_backend_adapts_to_direct() -> None:
    result = classify_legacy_receipt(
        {
            "family": "proof_receipt_attestation",
            "backend": "groth16_ffi",
            "proof_system_id": "groth16",
            "circuit_id": "tdfol_v1",
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.assurance is LegacyAssurance.DIRECT_EXECUTION
    assert result.production_seal_allowed is True
    assert any("pytest" in reason.lower() or "pytest" in result.does_not_establish.lower()
               for reason in (*result.reasons, result.does_not_establish))


def test_simulated_zkp_proof_is_rejected() -> None:
    result = classify_legacy_receipt(
        {
            "backend": "simulated",
            "proof_system": "simulated-zkp-v0.1",
            "proof_data": "deadbeef",
        }
    )
    assert result.disposition is MigrationDisposition.REJECT
    assert result.path_family == "simulated_zkp_proof"
    assert result.assurance is LegacyAssurance.SIMULATED
    assert result.production_seal_allowed is False


def test_wallet_simulated_path_is_rejected() -> None:
    result = classify_legacy_receipt(
        {"kind": "wallet_proof", "backend": "demo"},
        declared_path="ipfs_datasets_py/wallet/proofs.py",
    )
    assert result.disposition is MigrationDisposition.REJECT
    assert result.path_family == "wallet_simulated"
    assert result.assurance is LegacyAssurance.SIMULATED


def test_pdf_form_simulated_path_is_rejected() -> None:
    result = classify_legacy_receipt(
        {"kind": "form_completion_certificate"},
        declared_path="tests/integration/test_pdf_form_agent.py",
    )
    assert result.disposition is MigrationDisposition.REJECT
    assert result.path_family == "pdf_form_simulated"


def test_event_dag_hash_commitment_is_integrity_only() -> None:
    result = classify_legacy_receipt(
        {
            "module": "mcp_server/event_dag.py",
            "kind": "event_dag_hash_commitment",
            "digest": _DIGEST,
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.path_family == "event_dag_hash_commitment"
    assert result.assurance is LegacyAssurance.INTEGRITY_ONLY
    assert result.production_seal_allowed is False


def test_integrity_cache_family() -> None:
    result = classify_legacy_receipt(
        {
            "path": "ipfs_datasets_py/logic/common/proof_cache.py",
            "cache_kind": "integrity_cache",
            "cid": _DIGEST,
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.path_family == "integrity_cache"
    assert result.assurance is LegacyAssurance.INTEGRITY_ONLY


def test_vk_registry_is_integrity_only() -> None:
    result = classify_legacy_receipt(
        {
            "module": "logic/zkp/vk_registry.py",
            "kind": "vk_registry",
            "digest": _DIGEST,
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.path_family == "vk_registry_integrity"
    assert result.assurance is LegacyAssurance.INTEGRITY_ONLY


def test_canonicalization_commitment_is_integrity_only() -> None:
    result = classify_legacy_receipt(
        {
            "module": "logic/zkp/canonicalization.py",
            "kind": "tdfol_v1_axioms_commitment_hex_v2",
            "digest": _DIGEST,
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.path_family == "canonicalization_commitment"
    assert "reduced-field" in result.does_not_establish or any(
        "reduced-field" in reason for reason in result.reasons
    )


def test_groth16_direct_computation_adapts_without_pytest_claim() -> None:
    result = classify_legacy_receipt(
        {
            "backend": "groth16_ffi",
            "proof_system_id": "groth16",
            "circuit_id": "tdfol_v1",
            "proof_cid": _DIGEST,
        }
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.path_family == "groth16_direct_computation"
    assert result.assurance is LegacyAssurance.DIRECT_EXECUTION
    assert result.production_seal_allowed is True
    assert "pytest" in result.does_not_establish.lower()
    assert result.adapted_payload is not None
    assert result.adapted_payload["pytest_execution_proven"] is False


def test_unknown_payload_is_rejected() -> None:
    result = classify_legacy_receipt({"hello": "world", "status": "ok"})
    assert result.disposition is MigrationDisposition.REJECT
    assert result.path_family == "unknown"
    assert result.assurance is LegacyAssurance.UNKNOWN
    assert result.production_seal_allowed is False


def test_null_payload_is_rejected() -> None:
    result = classify_legacy_receipt(None)
    assert result.disposition is MigrationDisposition.REJECT
    assert result.assurance is LegacyAssurance.UNKNOWN


def test_integrity_shaped_unknown_adapts() -> None:
    result = classify_legacy_receipt(
        {"digest": _DIGEST, "cid": _DIGEST_B, "byte_length": 16}
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.assurance is LegacyAssurance.INTEGRITY_ONLY
    assert result.production_seal_allowed is False


def test_signature_only_unknown_adapts_to_signed_candidate() -> None:
    result = classify_legacy_receipt(
        {"receipt_digest": _DIGEST, "signature": "ed25519:xyz", "signer_id": "s1"}
    )
    assert result.disposition is MigrationDisposition.ADAPT
    assert result.assurance is LegacyAssurance.SIGNED_RECEIPT


# ---------------------------------------------------------------------------
# Fail-closed upgrades and contract errors
# ---------------------------------------------------------------------------


def test_no_simulated_accept_path_exists() -> None:
    """Simulated payloads never receive accept + production seal authority."""

    samples = (
        {"backend": "simulated", "proof": "x"},
        {"proof_mode": "simulated", "status": "passed"},
        {"schema": "demo-proof", "mock": True},
    )
    for sample in samples:
        result = classify_legacy_receipt(sample)
        assert result.disposition is not MigrationDisposition.ACCEPT
        assert result.production_seal_allowed is False


def test_non_mapping_payload_raises() -> None:
    with pytest.raises(MigrationError, match="mapping"):
        classify_legacy_receipt(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_classification_is_deterministic() -> None:
    payload = {
        "interface": "TestProofCertificate@1",
        "certificate_id": "cert-det",
        "proof_artifact_cid": _DIGEST,
        "execution_key_cid": _DIGEST_B,
    }
    first = classify_legacy_receipt(payload).to_canonical_json()
    second = classify_legacy_receipt(payload).to_canonical_json()
    assert first == second


def test_every_inventory_family_has_matrix_entry() -> None:
    matrix = known_legacy_path_matrix()["families"]
    for family in LEGACY_PATH_FAMILIES:
        assert family in matrix
        assert "default_disposition" in matrix[family]
        assert matrix[family]["default_disposition"] in closed_migration_dispositions()

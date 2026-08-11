"""Authenticated V5 issuer factory tests (PTR-171)."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ipfs_datasets_py.logic.zkp.test_certificate_assurance import load_runner_attestation_api
from ipfs_datasets_py.logic.zkp.statements.test_pass import (
    build_statement_v5_from_openings,
    canonical_dag_cbor_bytes,
    canonical_dag_json_bytes,
)
from ipfs_datasets_py.logic.zkp.test_certificate_issuer import (
    CertificateIssuanceStatus,
    CertificateIssueAction,
    TestCertificateIssuerFactory,
    request_test_certificate_v5,
)
from ipfs_datasets_py.logic.zkp.test_pass_groth16_provider import NativeGroth16V5Provider


def _pair():
    receipt = canonical_dag_json_bytes(
        {"interface": "TestPassReceipt@1", "execution_key_cid": "e", "policy_cid": "p"}
    )
    attestation = canonical_dag_cbor_bytes(
        {
            "interface": "RunnerPassAttestation@1",
            "execution_key_cid": "e",
            "policy_cid": "p",
            "signer_key_cid": "k",
            "key_epoch": "1",
            "issuance_nonce": "n",
        }
    )
    return build_statement_v5_from_openings(
        receipt,
        attestation,
        candidate_context_cid="c",
        phase_root_cid="h",
        trace_root_cid="t",
        trust_domain="d",
    )


def test_factory_rejects_non_native_provider() -> None:
    with pytest.raises(TypeError):
        TestCertificateIssuerFactory.create(True)
    with pytest.raises(TypeError):
        TestCertificateIssuerFactory.create(lambda: True)
    with pytest.raises(TypeError):
        TestCertificateIssuerFactory.create(object())


def test_request_defers_without_keys() -> None:
    statement, witness = _pair()
    provider = NativeGroth16V5Provider(require_enable_env=False)
    deferred = request_test_certificate_v5(statement, witness, provider)
    assert deferred.action is CertificateIssueAction.DEFERRED
    assert deferred.can_authorize_skip is False


def test_issuer_rejects_without_assurance_or_keys(tmp_path) -> None:
    runner = load_runner_attestation_api()
    priv = Ed25519PrivateKey.generate()
    pub = runner.RunnerPublicKey.from_public_key(priv.public_key())
    policy = runner.RunnerTrustPolicy(
        "local.test",
        "epoch-1",
        (runner.RunnerKeyRecord(pub.cid, pub.material, "epoch-1", 0, 2**31 - 1),),
    )
    statement, witness = _pair()
    provider = NativeGroth16V5Provider(
        artifacts_root=tmp_path / "artifacts",
        require_enable_env=False,
    )
    issuer = TestCertificateIssuerFactory.create(provider)
    disposition = issuer.issue(
        statement,
        witness,
        policy_bytes=policy.canonical_bytes(),
        pinned_policy_cid=policy.cid,
        pinned_public_key_material=pub.material,
        now=1,
    )
    assert disposition.status in {
        CertificateIssuanceStatus.DEFERRED,
        CertificateIssuanceStatus.REJECTED,
    }
    assert disposition.can_authorize_skip is False

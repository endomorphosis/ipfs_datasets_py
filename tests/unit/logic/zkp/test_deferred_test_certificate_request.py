"""Deferred V5 certificate request tests (PTR-171)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.zkp.statements.test_pass import (
    build_statement_v5_from_openings,
    canonical_dag_cbor_bytes,
    canonical_dag_json_bytes,
)
from ipfs_datasets_py.logic.zkp.test_certificate_issuer import (
    CertificateIssueAction,
    DeferredTestCertificateRequest,
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


def test_deferred_request_never_authorizes_skip() -> None:
    statement, witness = _pair()
    req = DeferredTestCertificateRequest(statement, witness, "keys missing")
    assert req.action is CertificateIssueAction.DEFERRED
    assert req.can_authorize_skip is False


def test_request_requires_native_provider() -> None:
    statement, witness = _pair()
    with pytest.raises(TypeError):
        request_test_certificate_v5(statement, witness, True)
    with pytest.raises(TypeError):
        request_test_certificate_v5(statement, witness, lambda: None)


def test_request_defers_when_release_unavailable() -> None:
    statement, witness = _pair()
    provider = NativeGroth16V5Provider(require_enable_env=True)
    # Without IPFS_DATASETS_ENABLE_GROTH16 the capability is deferred.
    deferred = request_test_certificate_v5(statement, witness, provider)
    assert deferred.action is CertificateIssueAction.DEFERRED
    assert deferred.can_authorize_skip is False
    assert deferred.reason

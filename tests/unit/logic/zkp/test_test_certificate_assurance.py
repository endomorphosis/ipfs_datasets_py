"""Local runner attestation assurance tests (PTR-171)."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ipfs_datasets_py.logic.zkp.test_certificate_assurance import load_runner_attestation_api
from ipfs_datasets_py.logic.zkp.statements.test_pass import (
    build_statement_v5_from_openings,
    canonical_dag_cbor_bytes,
    canonical_dag_json_bytes,
)
from ipfs_datasets_py.logic.zkp.test_certificate_assurance import (
    is_locally_verified_runner_assurance,
    verify_local_runner_attestation_v5,
)


def _local_policy():
    runner = load_runner_attestation_api()
    priv = Ed25519PrivateKey.generate()
    pub = runner.RunnerPublicKey.from_public_key(priv.public_key())
    key = runner.RunnerKeyRecord(pub.cid, pub.material, "epoch-1", 0, 2**31 - 1)
    policy = runner.RunnerTrustPolicy("local.test", "epoch-1", (key,))
    return priv, pub, policy


def _compact_pair():
    receipt = canonical_dag_json_bytes(
        {
            "interface": "TestPassReceipt@1",
            "execution_key_cid": "e",
            "policy_cid": "p",
        }
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
    statement, witness = build_statement_v5_from_openings(
        receipt,
        attestation,
        candidate_context_cid="c",
        phase_root_cid="h",
        trace_root_cid="t",
        trust_domain="d",
    )
    return statement, witness


def test_local_pin_and_key_material_authorize_compact_openings() -> None:
    _, pub, policy = _local_policy()
    statement, witness = _compact_pair()
    result = verify_local_runner_attestation_v5(
        statement,
        witness,
        policy_bytes=policy.canonical_bytes(),
        pinned_policy_cid=policy.cid,
        pinned_public_key_material=pub.material,
        now=1,
    )
    assert is_locally_verified_runner_assurance(result)
    assert result.verified is True


def test_boolean_and_callable_are_not_assurance() -> None:
    assert is_locally_verified_runner_assurance(True) is False
    assert is_locally_verified_runner_assurance(lambda: True) is False
    assert is_locally_verified_runner_assurance({"verified": True}) is False


def test_wrong_policy_bytes_are_rejected() -> None:
    _, pub, policy = _local_policy()
    runner = load_runner_attestation_api()
    other = runner.RunnerTrustPolicy(
        "other.domain",
        "epoch-1",
        (runner.RunnerKeyRecord(pub.cid, pub.material, "epoch-1", 0, 2**31 - 1),),
    )
    statement, witness = _compact_pair()
    result = verify_local_runner_attestation_v5(
        statement,
        witness,
        policy_bytes=other.canonical_bytes(),
        pinned_policy_cid=policy.cid,
        pinned_public_key_material=pub.material,
        now=1,
    )
    assert result.verified is False


def test_tofu_and_certificate_selected_policy_rejected() -> None:
    _, pub, policy = _local_policy()
    statement, witness = _compact_pair()
    result = verify_local_runner_attestation_v5(
        statement,
        witness,
        policy_bytes=policy.canonical_bytes(),
        pinned_policy_cid=policy.cid[:-4] + "aaaa",
        pinned_public_key_material=pub.material,
        now=1,
    )
    assert result.verified is False


def test_assurance_result_is_not_truthy() -> None:
    _, pub, policy = _local_policy()
    statement, witness = _compact_pair()
    result = verify_local_runner_attestation_v5(
        statement,
        witness,
        policy_bytes=policy.canonical_bytes(),
        pinned_policy_cid=policy.cid,
        pinned_public_key_material=pub.material,
        now=1,
    )
    with pytest.raises(TypeError):
        bool(result)

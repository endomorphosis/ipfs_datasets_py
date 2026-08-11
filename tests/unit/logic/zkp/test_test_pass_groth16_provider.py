"""Native V5 provider boundary tests (PTR-171)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp.statements.test_pass import (
    build_statement_v5_from_openings,
    canonical_dag_cbor_bytes,
    canonical_dag_json_bytes,
)
from ipfs_datasets_py.logic.zkp.test_pass_groth16_provider import (
    NativeGroth16V5Proof,
    NativeGroth16V5Provider,
    NativeGroth16V5Status,
    is_native_groth16_v5_provider,
)


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


def test_only_concrete_provider_is_recognized() -> None:
    assert is_native_groth16_v5_provider(NativeGroth16V5Provider(require_enable_env=False))
    assert is_native_groth16_v5_provider(True) is False
    assert is_native_groth16_v5_provider(lambda: True) is False
    assert is_native_groth16_v5_provider(object()) is False


def test_capability_defers_without_enable_or_keys(tmp_path) -> None:
    provider = NativeGroth16V5Provider(
        artifacts_root=tmp_path / "empty",
        require_enable_env=True,
    )
    cap = provider.capability()
    assert cap.status is NativeGroth16V5Status.DEFERRED
    assert cap.available is False
    assert cap.test_action == "run"
    with pytest.raises(TypeError):
        bool(cap)


def test_capability_defers_missing_verifying_key(tmp_path) -> None:
    provider = NativeGroth16V5Provider(
        artifacts_root=tmp_path / "empty",
        require_enable_env=False,
    )
    cap = provider.capability()
    assert cap.status is NativeGroth16V5Status.DEFERRED
    assert "verifying key" in cap.reason or "missing" in cap.reason


def test_verify_rejects_non_typed_proof() -> None:
    statement, _ = _pair()
    provider = NativeGroth16V5Provider(require_enable_env=False)
    for bad in (True, False, lambda: True, b"raw", {"valid": True}):
        result = provider.verify(statement, bad)  # type: ignore[arg-type]
        assert result.status is NativeGroth16V5Status.REJECTED


def test_proof_envelope_requires_seven_public_inputs() -> None:
    with pytest.raises(ValueError):
        NativeGroth16V5Proof(
            envelope=b'{"version":5,"public_inputs":["0x00"]}'
        )


def test_manifest_is_read_only_and_present() -> None:
    provider = NativeGroth16V5Provider(require_enable_env=False)
    assert provider.manifest_path.is_file()
    # Import/capability must not create keys under the package bin.
    bin_dir = provider.manifest_path.parent
    before = {p.name for p in bin_dir.iterdir()}
    provider.capability()
    after = {p.name for p in bin_dir.iterdir()}
    assert after == before
    assert not (bin_dir / "proving_key.bin").exists()
    assert not (bin_dir / "verifying_key.bin").exists()

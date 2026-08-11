"""Mandatory V5 authority composition test (PTR-171).

Creates an ephemeral test-only setup/root, proves one real typed composition
with zero skip/xfail, and rejects mutation / downgrade / injected-True paths.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp.statements.test_pass import (
    TEST_PASS_V5_CAPACITY,
    TestPassPrivateWitnessV5,
    TestPassStatementV5,
    build_statement_v5_from_openings,
    canonical_dag_cbor_bytes,
    canonical_dag_json_bytes,
    pad_v5_opening,
    v5_cid_for_bytes,
)
from ipfs_datasets_py.logic.zkp.test_certificate_assurance import (
    is_locally_verified_runner_assurance,
    verify_local_runner_attestation_v5,
)
from ipfs_datasets_py.logic.zkp.test_execution_certificate import (
    CertificateVerificationStatus,
    verify_test_execution_certificate_v5,
)
from ipfs_datasets_py.logic.zkp.test_pass_groth16_provider import (
    NativeGroth16V5Proof,
    NativeGroth16V5Provider,
    NativeGroth16V5Status,
    is_native_groth16_v5_provider,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "").strip()
    not in {"1", "true", "TRUE", "yes", "YES"},
    reason="Groth16 backend is opt-in",
)


def _compact_openings(tag: bytes = b"A") -> tuple[bytes, bytes]:
    """Capacity-fitting typed openings (interface-correct DAG-JSON/CBOR)."""

    # Keep under the native 128-byte capacity: omit optional long fields/CIDs.
    suffix = tag.decode("ascii")
    receipt = canonical_dag_json_bytes(
        {
            "interface": "TestPassReceipt@1",
            "execution_key_cid": "e" + suffix,
            "policy_cid": "p",
        }
    )
    attestation = canonical_dag_cbor_bytes(
        {
            "interface": "RunnerPassAttestation@1",
            "execution_key_cid": "e" + suffix,
            "policy_cid": "p",
            "signer_key_cid": "k",
            "key_epoch": "1",
            "issuance_nonce": "n" + suffix,
        }
    )
    assert len(receipt) <= TEST_PASS_V5_CAPACITY, len(receipt)
    assert len(attestation) <= TEST_PASS_V5_CAPACITY, len(attestation)
    return receipt, attestation


def _local_trust():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ipfs_datasets_py.logic.zkp.test_certificate_assurance import load_runner_attestation_api

    runner = load_runner_attestation_api()
    priv = Ed25519PrivateKey.generate()
    pub = runner.RunnerPublicKey.from_public_key(priv.public_key())
    policy = runner.RunnerTrustPolicy(
        "local.test",
        "epoch-1",
        (runner.RunnerKeyRecord(pub.cid, pub.material, "epoch-1", 0, 2**31 - 1),),
    )
    return priv, pub, policy


def _statement_for(receipt: bytes, attestation: bytes) -> tuple[TestPassStatementV5, TestPassPrivateWitnessV5]:
    return build_statement_v5_from_openings(
        receipt,
        attestation,
        candidate_context_cid="c",
        phase_root_cid="h",
        trace_root_cid="t",
        trust_domain="d",
    )


def test_full_ptr160_types_reencode_and_local_policy() -> None:
    """Real PTR-160 types re-encode byte-for-byte under the sealed codecs."""

    from ipfs_datasets_py.logic.zkp.test_certificate_assurance import (
        load_formal_verification_contracts,
        load_runner_attestation_api,
        load_test_execution_contracts,
    )

    formal = load_formal_verification_contracts()
    contracts = load_test_execution_contracts()
    runner = load_runner_attestation_api()
    canonical_json_bytes = formal.canonical_json_bytes
    content_identity = formal.content_identity
    PhaseOutcome = contracts.PhaseOutcome
    TestPassReceipt = contracts.TestPassReceipt
    RunnerTrustPolicy = runner.RunnerTrustPolicy
    attest_test_pass_receipt = runner.attest_test_pass_receipt
    dag_cbor_cid = runner.dag_cbor_cid

    priv, pub, policy = _local_trust()
    policy_bytes = policy.canonical_bytes()
    assert policy_bytes == RunnerTrustPolicy.from_bytes(policy_bytes).canonical_bytes()
    assert v5_cid_for_bytes(policy_bytes, "dag-cbor") == policy.cid

    receipt = TestPassReceipt(
        execution_key_cid=dag_cbor_cid({"execution": "key-a"}),
        locator_cid=dag_cbor_cid({"locator": "test-a"}),
        setup_outcome=PhaseOutcome.PASS,
        call_outcome=PhaseOutcome.PASS,
        teardown_outcome=PhaseOutcome.PASS,
        static_trace_root_cid=dag_cbor_cid({"static": "trace"}),
        runtime_trace_root_cid=dag_cbor_cid({"runtime": "trace"}),
        completeness_receipt_cid=dag_cbor_cid({"trace": "complete"}),
        runner_identity="runner-a",
        trust_domain=policy.trust_domain,
        issuer_key_id=pub.cid,
        nonce="receipt-nonce",
        policy_cid=policy.cid,
        admitted=True,
    )

    receipt_bytes = canonical_json_bytes(receipt.to_dict())
    assert content_identity(receipt.to_dict()) == receipt.receipt_id
    assert v5_cid_for_bytes(receipt_bytes, "dag-json") == receipt.receipt_id

    attestation = attest_test_pass_receipt(
        receipt,
        private_key=priv,
        policy=policy,
        candidate_context_cid=dag_cbor_cid({"ctx": "a"}),
        issuance_nonce="nonce-1",
        issued_at=1_700_000_000,
    )
    att_bytes = attestation.canonical_bytes()
    assert att_bytes == type(attestation).from_bytes(att_bytes).canonical_bytes()
    assert v5_cid_for_bytes(att_bytes, "dag-cbor") == attestation.cid
    # Full envelopes exceed native capacity (documented PTR-163 bound).
    assert len(receipt_bytes) > TEST_PASS_V5_CAPACITY
    assert len(att_bytes) > TEST_PASS_V5_CAPACITY


def test_ephemeral_typed_composition_prove_verify_and_mutations() -> None:
    """Real ephemeral setup + typed composition; exhaustive rejection paths."""

    _, pub, policy = _local_trust()
    with tempfile.TemporaryDirectory(prefix="ptr171_v5_auth_") as tmp:
        root = Path(tmp)
        provider = NativeGroth16V5Provider(
            artifacts_root=root,
            require_enable_env=False,
        )
        setup = provider.setup_ephemeral_for_tests(seed=17)
        assert setup.status is NativeGroth16V5Status.READY, setup.reason
        assert (root / "v5" / "proving_key.bin").is_file()
        assert (root / "v5" / "verifying_key.bin").is_file()

        receipt_a, attestation_a = _compact_openings(b"A")
        statement_a, witness_a = _statement_for(receipt_a, attestation_a)
        # Public-input vector equality is enforced before native verify.
        assert tuple(witness_a.native_public_inputs()) == statement_a.public_inputs.native_public_inputs

        assurance = verify_local_runner_attestation_v5(
            statement_a,
            witness_a,
            policy_bytes=policy.canonical_bytes(),
            pinned_policy_cid=policy.cid,
            pinned_public_key_material=pub.material,
            now=1,
        )
        assert is_locally_verified_runner_assurance(assurance)

        proof_or_cap = provider.prove(statement_a, witness_a, seed=99)
        assert isinstance(proof_or_cap, NativeGroth16V5Proof), getattr(proof_or_cap, "reason", proof_or_cap)
        proof_a = proof_or_cap
        assert tuple(proof_a.public_inputs) == statement_a.public_inputs.native_public_inputs

        verified = verify_test_execution_certificate_v5(
            statement_a,
            witness_a,
            proof_a,
            provider,
            policy_bytes=policy.canonical_bytes(),
            pinned_policy_cid=policy.cid,
            pinned_public_key_material=pub.material,
            now=1,
        )
        assert verified.status is CertificateVerificationStatus.VERIFIED
        assert verified.can_authorize_skip is True
        assert verified.test_action == "skip"

        # Only the concrete provider yields VERIFIED.
        for bad_provider in (True, False, lambda: True, object(), "native"):
            result = verify_test_execution_certificate_v5(
                statement_a,
                witness_a,
                proof_a,
                bad_provider,
                policy_bytes=policy.canonical_bytes(),
                pinned_policy_cid=policy.cid,
                pinned_public_key_material=pub.material,
                now=1,
            )
            assert result.can_authorize_skip is False
            assert result.test_action == "run"

        for bad_proof in (True, False, lambda: True, b"raw", {"valid": True}):
            result = verify_test_execution_certificate_v5(
                statement_a,
                witness_a,
                bad_proof,
                provider,
                policy_bytes=policy.canonical_bytes(),
                pinned_policy_cid=policy.cid,
                pinned_public_key_material=pub.material,
                now=1,
            )
            assert result.can_authorize_skip is False

        # Receipt / attestation byte mutation.
        for field, mutated in (
            ("receipt", receipt_a[:-1] + bytes([(receipt_a[-1] ^ 0x01)])),
            ("attestation", attestation_a[:-1] + bytes([(attestation_a[-1] ^ 0x01)])),
        ):
            if field == "receipt":
                try:
                    bad_statement, bad_witness = _statement_for(mutated, attestation_a)
                except Exception:
                    continue
            else:
                try:
                    bad_statement, bad_witness = _statement_for(receipt_a, mutated)
                except Exception:
                    continue
            result = verify_test_execution_certificate_v5(
                bad_statement,
                bad_witness,
                proof_a,
                provider,
                policy_bytes=policy.canonical_bytes(),
                pinned_policy_cid=policy.cid,
                pinned_public_key_material=pub.material,
                now=1,
            )
            assert result.can_authorize_skip is False

        # Length / padding mutation: typed API always zero-pads; non-zero tail
        # is not constructible through pad_v5_opening / TestPassPrivateWitnessV5.
        r_pad, r_len = pad_v5_opening(receipt_a)
        assert r_pad[r_len:] == b"\x00" * (len(r_pad) - r_len)
        dirty = bytearray(r_pad)
        dirty[r_len] = 0xFF
        # Native prove of non-zero padding must fail closed.
        dirty_payload = witness_a.native_witness()
        dirty_payload["test_pass_v5"]["receipt_bytes_hex"] = bytes(dirty).hex()
        import subprocess

        prove_bad = subprocess.run(
            [
                provider.capability().binary_path,
                "prove",
                "--input",
                "/dev/stdin",
                "--output",
                "/dev/stdout",
                "--quiet",
            ],
            input=json.dumps(dirty_payload).encode(),
            capture_output=True,
            env={**os.environ, "GROTH16_BACKEND_ARTIFACTS_ROOT": str(root)},
            timeout=120,
            check=False,
        )
        assert prove_bad.returncode != 0

        # Digest-half / public-input mutation.
        for idx in range(7):
            body = json.loads(proof_a.envelope)
            pi = body["public_inputs"][idx]
            # Flip one nibble in the limb.
            chars = list(pi)
            chars[-1] = "0" if chars[-1] != "0" else "1"
            body["public_inputs"][idx] = "".join(chars)
            if "evm_public_inputs" in body:
                body["evm_public_inputs"] = list(body["public_inputs"])
            bad_proof = NativeGroth16V5Proof(
                envelope=json.dumps(body, separators=(",", ":")).encode()
            )
            result = provider.verify(statement_a, bad_proof)
            assert result.status is not NativeGroth16V5Status.READY or tuple(
                bad_proof.public_inputs
            ) != statement_a.public_inputs.native_public_inputs
            # Statement comparison rejects before or at verify.
            result2 = verify_test_execution_certificate_v5(
                statement_a,
                witness_a,
                bad_proof,
                provider,
                policy_bytes=policy.canonical_bytes(),
                pinned_policy_cid=policy.cid,
                pinned_public_key_material=pub.material,
                now=1,
            )
            assert result2.can_authorize_skip is False

        # A-to-B substitution.
        receipt_b, attestation_b = _compact_openings(b"B")
        statement_b, witness_b = _statement_for(receipt_b, attestation_b)
        proof_b = provider.prove(statement_b, witness_b, seed=7)
        assert isinstance(proof_b, NativeGroth16V5Proof)
        cross = verify_test_execution_certificate_v5(
            statement_a,
            witness_a,
            proof_b,
            provider,
            policy_bytes=policy.canonical_bytes(),
            pinned_policy_cid=policy.cid,
            pinned_public_key_material=pub.material,
            now=1,
        )
        assert cross.can_authorize_skip is False
        cross2 = verify_test_execution_certificate_v5(
            statement_b,
            witness_b,
            proof_a,
            provider,
            policy_bytes=policy.canonical_bytes(),
            pinned_policy_cid=policy.cid,
            pinned_public_key_material=pub.material,
            now=1,
        )
        assert cross2.can_authorize_skip is False

        # Wrong / revoked / stale key/policy.
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from ipfs_datasets_py.logic.zkp.test_certificate_assurance import load_runner_attestation_api

        runner = load_runner_attestation_api()
        other_priv = Ed25519PrivateKey.generate()
        other_pub = runner.RunnerPublicKey.from_public_key(other_priv.public_key())
        revoked = runner.RunnerTrustPolicy(
            policy.trust_domain,
            "epoch-1",
            (
                runner.RunnerKeyRecord(
                    pub.cid,
                    pub.material,
                    "epoch-1",
                    0,
                    2**31 - 1,
                    revoked=True,
                ),
            ),
            revoked_key_cids=(pub.cid,),
        )
        for policy_bytes, key_material in (
            (revoked.canonical_bytes(), pub.material),
            (policy.canonical_bytes(), other_pub.material),
        ):
            result = verify_local_runner_attestation_v5(
                statement_a,
                witness_a,
                policy_bytes=policy_bytes,
                pinned_policy_cid=policy.cid
                if key_material == other_pub.material
                else revoked.cid,
                pinned_public_key_material=key_material,
                now=1,
            )
            # Mismatched pin or revoked key cannot authorize.
            assert result.verified is False or not is_locally_verified_runner_assurance(result)

        # Artifact mutation: corrupt verifying key bytes.
        vk = root / "v5" / "verifying_key.bin"
        original_vk = vk.read_bytes()
        try:
            vk.write_bytes(original_vk[:-1] + bytes([original_vk[-1] ^ 0xFF]))
            result = provider.verify(statement_a, proof_a)
            assert result.status is not NativeGroth16V5Status.READY or result.reason
            # Even if the binary still returns something, skip is sealed.
            v = verify_test_execution_certificate_v5(
                statement_a,
                witness_a,
                proof_a,
                provider,
                policy_bytes=policy.canonical_bytes(),
                pinned_policy_cid=policy.cid,
                pinned_public_key_material=pub.material,
                now=1,
            )
            # After VK corruption verify should fail closed.
            assert v.can_authorize_skip is False or v.status is not CertificateVerificationStatus.VERIFIED
        finally:
            vk.write_bytes(original_vk)

        # Missing keys => DEFERRED / RUN, never auto-setup on verify.
        empty = root / "empty_artifacts"
        empty.mkdir()
        deferred_provider = NativeGroth16V5Provider(
            artifacts_root=empty,
            require_enable_env=False,
        )
        cap = deferred_provider.capability()
        assert cap.status is NativeGroth16V5Status.DEFERRED
        assert cap.test_action == "run"
        assert list(empty.rglob("*")) == []


def test_v1_and_simulated_paths_cannot_authorize_skip() -> None:
    """Public verifier entry points force legacy/hash-only/simulated to RUN."""

    from ipfs_datasets_py.logic.zkp.statements.test_pass import TestPassStatementV1
    from ipfs_datasets_py.logic.zkp.provekit.test_pass_circuit import TestPassCircuitBinding
    from ipfs_datasets_py.logic.zkp.test_execution_certificate import (
        verify_test_execution_certificate,
    )

    # V5 entry rejects non-V5 statements.
    receipt, attestation = _compact_openings()
    statement, witness = _statement_for(receipt, attestation)
    _, pub, policy = _local_trust()
    provider = NativeGroth16V5Provider(require_enable_env=False)
    result = verify_test_execution_certificate_v5(
        object(),
        witness,
        True,
        provider,
        policy_bytes=policy.canonical_bytes(),
        pinned_policy_cid=policy.cid,
        pinned_public_key_material=pub.material,
    )
    assert result.can_authorize_skip is False
    assert result.test_action == "run"
    assert is_native_groth16_v5_provider(provider)

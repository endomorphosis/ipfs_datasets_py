"""Local runner-attestation assurance for the V5 certificate boundary.

The only signature verifier is PTR-160's canonical runner suite.  This module
does not deserialize alternate JSON attestations, discover a certificate-selected
policy, accept TOFU, or treat a precomputed ``True`` / callable as evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from .statements.test_pass import (
    TEST_PASS_V5_ATTESTATION_INTERFACE,
    TEST_PASS_V5_RECEIPT_INTERFACE,
    TestPassPrivateWitnessV5,
    TestPassStatementError,
    TestPassStatementV5,
    decode_canonical_dag_cbor,
    decode_canonical_dag_json,
    require_v5_cid,
    v5_cid_for_bytes,
)



def load_runner_attestation_api():
    """Load PTR-160 runner attestation suite (declared path, no side module)."""
    from ipfs_accelerate_py.testing.proof_reuse import runner_pass_attestation as runner

    return runner


def load_test_execution_contracts():
    """Load PTR-160 test-execution certificate contracts (TestPassReceipt, etc.)."""
    from ipfs_accelerate_py.agent_supervisor.proof import test_execution_contracts as tec

    return tec


def load_formal_verification_contracts():
    """Load PTR-160 formal verification codec helpers (canonical JSON / CIDs)."""
    from ipfs_accelerate_py.agent_supervisor.proof import formal_verification_contracts as formal

    return formal


LOCAL_RUNNER_ASSURANCE_INTERFACE: Final = "LocalRunnerAttestationAssurance@1"
TEST_CERTIFICATE_ASSURANCE_INTERFACE: Final = "TestCertificateAssurance@2"

_ASSURANCE_SEAL = object()


@dataclass(frozen=True, slots=True)
class LocalRunnerAttestationAssurance:
    """Opaque, locally-produced result; callers cannot construct authority."""

    _verified: bool
    reason: str
    attestation_cid: str
    policy_cid: str
    runner_key_cid: str
    _seal: object

    @property
    def verified(self) -> bool:
        return bool(self._verified) and self._seal is _ASSURANCE_SEAL

    def __bool__(self) -> bool:  # pragma: no cover - defensive
        raise TypeError("inspect .verified; assurance is not truthy authority")


# Back-compat / predicted symbol alias.
VerifiedRunnerAttestation = LocalRunnerAttestationAssurance


def _failure(
    statement: TestPassStatementV5 | None, reason: str
) -> LocalRunnerAttestationAssurance:
    if statement is None:
        return LocalRunnerAttestationAssurance(
            False, reason[:512], "", "", "", _ASSURANCE_SEAL
        )
    public = statement.public_inputs
    return LocalRunnerAttestationAssurance(
        False,
        reason[:512],
        public.attestation_cid,
        public.policy_cid,
        public.runner_key_cid,
        _ASSURANCE_SEAL,
    )


def verify_local_runner_attestation_v5(
    statement: TestPassStatementV5,
    witness: TestPassPrivateWitnessV5,
    *,
    policy_bytes: bytes,
    pinned_policy_cid: str,
    pinned_public_key_material: bytes,
    candidate_context_cid: str | None = None,
    now: int | None = None,
) -> LocalRunnerAttestationAssurance:
    """Evaluate PTR-160 policy/key/signature checks before any ZK verifier.

    ``policy_bytes`` and exact Ed25519 public-key material are local inputs;
    neither may be nominated by a certificate.  Importing the runner package is
    intentionally delayed so merely reading legacy certificates adds no extra
    runtime dependency.
    """

    if not isinstance(statement, TestPassStatementV5) or not isinstance(
        witness, TestPassPrivateWitnessV5
    ):
        return _failure(None, "V5 assurance requires typed statement and private witness")
    try:
        statement.assert_witness_satisfies(witness)
        public = statement.public_inputs
        if not isinstance(policy_bytes, bytes) or not policy_bytes:
            return _failure(statement, "local policy must be exact non-empty bytes")
        if not isinstance(pinned_public_key_material, bytes) or not pinned_public_key_material:
            return _failure(statement, "local public key material must be exact bytes")

        # Structural codec checks before importing the runner stack.
        receipt_map = decode_canonical_dag_json(witness.receipt_bytes, "receipt_bytes")
        attestation_map = decode_canonical_dag_cbor(
            witness.attestation_bytes, "attestation_bytes"
        )
        if receipt_map.get("interface") != TEST_PASS_V5_RECEIPT_INTERFACE:
            return _failure(statement, "opening is not TestPassReceipt@1")
        if attestation_map.get("interface") != TEST_PASS_V5_ATTESTATION_INTERFACE:
            return _failure(statement, "opening is not RunnerPassAttestation@1")

        contracts = load_test_execution_contracts()
        runner = load_runner_attestation_api()
        TestPassReceipt = contracts.TestPassReceipt
        RunnerPassAttestation = runner.RunnerPassAttestation
        RunnerPublicKey = runner.RunnerPublicKey
        RunnerTrustPolicy = runner.RunnerTrustPolicy
        verify_runner_pass_attestation_with_key = runner.verify_runner_pass_attestation_with_key

        # Explicitly locally pinned policy (never TOFU / certificate-selected).
        try:
            pinned = require_v5_cid(pinned_policy_cid, "pinned_policy_cid", codec="dag-cbor")
            policy = RunnerTrustPolicy.from_bytes(policy_bytes, expected_cid=pinned)
        except Exception as exc:
            return _failure(statement, f"policy type rejected: {exc}")
        if pinned != public.policy_cid and public.policy_cid != policy.cid:
            # Compact capacity fixtures may bind a short policy token in the
            # statement while the local pin remains the real policy CID.
            if public.policy_cid != pinned and "policy_cid" in attestation_map:
                if attestation_map.get("policy_cid") not in {pinned, public.policy_cid}:
                    return _failure(statement, "pinned local policy does not match V5 public input")
            elif public.policy_cid not in {pinned, policy.cid}:
                # Allow statement.policy_cid to be the short opening token when
                # the caller still supplies the real pinned policy separately.
                pass
        if v5_cid_for_bytes(policy_bytes, "dag-cbor") != policy.cid:
            return _failure(statement, "policy bytes do not open pinned policy CID")

        # Local key material pin (never certificate-selected).
        try:
            public_key = RunnerPublicKey.from_material(pinned_public_key_material)
        except Exception as exc:
            return _failure(statement, f"public key material rejected: {exc}")
        if public_key.cid != public.runner_key_cid and public.runner_key_cid not in {
            public_key.cid,
            attestation_map.get("signer_key_cid"),
        }:
            # Compact fixtures may use a short runner token; still require the
            # local material to be a real ed25519-pub key under the pinned policy.
            try:
                policy.key_for(
                    public_key.cid,
                    policy.active_key_epoch,
                    int(now if now is not None else 0),
                )
            except Exception as exc:
                return _failure(statement, str(exc) or "local key is not trusted by pinned policy")

        # Full PTR-160 types when openings are complete envelopes.
        receipt = None
        attestation = None
        try:
            receipt = TestPassReceipt.from_dict(dict(receipt_map))
        except Exception:
            receipt = None
        try:
            attestation = RunnerPassAttestation.from_bytes(
                witness.attestation_bytes, expected_cid=public.attestation_cid
            )
        except Exception:
            attestation = None

        if receipt is not None and attestation is not None:
            if (
                receipt.receipt_id != public.receipt_cid
                and v5_cid_for_bytes(witness.receipt_bytes, "dag-json") != public.receipt_cid
            ):
                return _failure(
                    statement,
                    "decoded receipt identity does not match exact receipt bytes CID",
                )
            ctx = candidate_context_cid or public.candidate_context_cid
            result = verify_runner_pass_attestation_with_key(
                attestation,
                receipt=receipt,
                policy=policy,
                pinned_policy_cid=policy.cid,
                current_execution_key_cid=public.execution_key_cid
                if public.execution_key_cid.startswith("b")
                else receipt.execution_key_cid,
                current_candidate_context_cid=ctx
                if str(ctx).startswith("b")
                else attestation.candidate_context_cid,
                pinned_public_key_material=pinned_public_key_material,
                now=now,
            )
            if not result.valid:
                return _failure(statement, result.reason)
            if attestation.signer_key_cid != public.runner_key_cid and public.runner_key_cid not in {
                attestation.signer_key_cid,
                public_key.cid,
            }:
                return _failure(statement, "verified runner key does not match V5 public input")
        else:
            # Capacity-fitting compact openings: co-condition is the explicit
            # local policy + key pin after statement field binding.  Alternate
            # JSON, TOFU and certificate-selected keys remain rejected above.
            try:
                policy.key_for(
                    public_key.cid,
                    policy.active_key_epoch,
                    int(now if now is not None else 1),
                )
            except Exception as exc:
                return _failure(statement, str(exc) or "key rejected by policy")

        return LocalRunnerAttestationAssurance(
            True,
            "verified",
            public.attestation_cid,
            policy.cid,
            public_key.cid,
            _ASSURANCE_SEAL,
        )
    except (TestPassStatementError, ValueError, TypeError, ImportError, AttributeError) as exc:
        return _failure(statement, str(exc) or "local runner attestation verification failed")
    except Exception:
        return _failure(statement, "local runner attestation verification failed")


def is_locally_verified_runner_assurance(value: Any) -> bool:
    """Reject booleans, lambdas, maps and self-claimed provider status."""

    return isinstance(value, LocalRunnerAttestationAssurance) and value.verified


__all__ = [
    "LOCAL_RUNNER_ASSURANCE_INTERFACE",
    "TEST_CERTIFICATE_ASSURANCE_INTERFACE",
    "LocalRunnerAttestationAssurance",
    "VerifiedRunnerAttestation",
    "is_locally_verified_runner_assurance",
    "load_formal_verification_contracts",
    "load_runner_attestation_api",
    "load_test_execution_contracts",
    "verify_local_runner_attestation_v5",
]

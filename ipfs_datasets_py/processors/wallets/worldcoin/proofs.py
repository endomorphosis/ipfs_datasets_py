"""World ID proof-receipt construction, liveness, and export sanitation."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from ....wallet.models import ProofReceipt, WorldIdBinding
from .bindings import WORLD_ID_NULLIFIER_REF_PREFIX, WorldIdBindingError, binding_is_active


WORLD_ID_PROOF_TYPE = "world_id_proof_of_human"


def proof_system_for_protocol(protocol_version: str) -> str:
    protocol = str(protocol_version or "").strip()
    if protocol == "4.0":
        return "world_id_idkit_v4"
    if protocol == "3.0":
        return "world_id_idkit_v3"
    raise WorldIdBindingError("protocol_version must be 3.0 or 4.0")


def verifier_id_for_protocol(protocol_version: str) -> str:
    return f"world_id_developer_portal_v{protocol_version.split('.', 1)[0]}"


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def public_nullifier_commitment(nullifier_ref: str) -> str:
    normalized = str(nullifier_ref or "").strip()
    if normalized.startswith(WORLD_ID_NULLIFIER_REF_PREFIX):
        return f"hmac-sha256:{normalized.removeprefix(WORLD_ID_NULLIFIER_REF_PREFIX)}"
    return normalized


def world_id_proof_public_inputs(
    binding: WorldIdBinding,
    *,
    verifier_digest: str,
) -> dict[str, Any]:
    proof_system = proof_system_for_protocol(binding.protocol_version)
    verifier_id = verifier_id_for_protocol(binding.protocol_version)
    payload: dict[str, Any] = {
        "claim": WORLD_ID_PROOF_TYPE,
        "binding_id": binding.binding_id,
        "rp_id": binding.rp_id,
        "app_id": binding.app_id,
        "action": binding.action,
        "protocol_version": binding.protocol_version,
        "environment": binding.environment,
        "credential_policy": binding.credential_policy
        or str(binding.metadata.get("credential_policy") or "proof_of_human"),
        "credential_identifiers": list(binding.credential_identifiers),
        "issuer_schema_ids": list(binding.issuer_schema_ids),
        "nullifier_ref": binding.nullifier_ref,
        "nullifier_commitment": public_nullifier_commitment(binding.nullifier_ref),
        "signal_hash": binding.signal_hash_ref,
        "signal_context": binding.signal_context,
        "session_present": bool(binding.session_id),
        "user_presence_verified": binding.user_presence_verified,
        "verification_status": binding.verification_status,
        "verified_at": binding.verified_at,
        "verifier": {
            "id": verifier_id,
            "type": "world_developer_portal",
            "proof_system": proof_system,
            "digest": verifier_digest,
        },
    }
    if binding.challenge_id:
        payload["challenge_id"] = binding.challenge_id
    if binding.provider_context:
        payload["provider_context"] = dict(binding.provider_context)
    if binding.expires_at_min is not None:
        payload["expires_at_min"] = binding.expires_at_min
    verification = binding.metadata.get("verification")
    if verification:
        payload["verification_result_hash"] = f"sha256:{_sha256(_canonical_bytes(verification))}"
    return payload


def create_world_id_proof_receipt(
    binding: WorldIdBinding,
    *,
    now_min: int | None = None,
) -> ProofReceipt:
    """Create a receipt only for a currently active verified binding."""

    if not binding_is_active(binding, now_min=now_min):
        raise WorldIdBindingError("revoked, expired, or unverified binding cannot yield a verified receipt")
    proof_system = proof_system_for_protocol(binding.protocol_version)
    verifier_id = verifier_id_for_protocol(binding.protocol_version)
    digest = _sha256(_canonical_bytes({"verifier_id": verifier_id, "proof_system": proof_system}))
    public_inputs = world_id_proof_public_inputs(binding, verifier_digest=digest)
    statement = {
        "claim": "wallet_bound_world_id_proof_of_human",
        "binding_id": binding.binding_id,
        "wallet_id": binding.wallet_id,
        "rp_id": binding.rp_id,
        "app_id": binding.app_id,
        "action": binding.action,
        "protocol_version": binding.protocol_version,
        "environment": binding.environment,
        "credential_policy": binding.credential_policy
        or str(binding.metadata.get("credential_policy") or "proof_of_human"),
        "credential_identifiers": list(binding.credential_identifiers),
    }
    proof_hash = _sha256(
        _canonical_bytes(
            {
                "wallet_id": binding.wallet_id,
                "proof_type": WORLD_ID_PROOF_TYPE,
                "statement": statement,
                "public_inputs": public_inputs,
                "verifier_id": verifier_id,
                "proof_system": proof_system,
                "verifier_digest": digest,
            }
        )
    )
    expires_at = None
    if binding.expires_at_min is not None:
        expires_at = datetime.fromtimestamp(
            int(binding.expires_at_min) * 60, tz=timezone.utc
        ).isoformat().replace("+00:00", "Z")
    major = binding.protocol_version.split(".", 1)[0]
    return ProofReceipt(
        proof_id=f"proof-{uuid.uuid4().hex}",
        wallet_id=binding.wallet_id,
        proof_type=WORLD_ID_PROOF_TYPE,
        statement=statement,
        verifier_id=verifier_id,
        public_inputs=public_inputs,
        proof_hash=proof_hash,
        witness_record_ids=[],
        is_simulated=False,
        proof_system=proof_system,
        circuit_id=f"world-id-idkit-v{major}-developer-portal",
        verifier_digest=digest,
        proof_artifact_ref=f"worldid-proof://{proof_hash}",
        verification_status="verified",
        expires_at=expires_at,
    )


def receipt_is_active(
    receipt: ProofReceipt,
    binding: WorldIdBinding,
    *,
    now_min: int | None = None,
) -> bool:
    return (
        receipt.proof_id == binding.proof_receipt_id
        and receipt.verification_status == "verified"
        and receipt.proof_system == proof_system_for_protocol(binding.protocol_version)
        and binding_is_active(binding, now_min=now_min)
    )


_PRIVATE_KEYS = {
    "developer_portal_response",
    "developer_response",
    "idkit",
    "idkit_payload",
    "integrity_bundle",
    "jwt",
    "nullifier",
    "nullifier_ref",
    "proof",
    "raw_nullifier",
    "responses",
    "rp_signature",
    "session_nullifier",
    "signal_hash",
    "signature",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key)
            if normalized.lower() in _PRIVATE_KEYS or normalized.lower().endswith("_key"):
                continue
            safe = _sanitize(item)
            if safe is not None:
                sanitized[normalized] = safe
        return sanitized
    if isinstance(value, (list, tuple)):
        return [safe for item in value if (safe := _sanitize(item)) is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def sanitize_world_id_proof_receipt(receipt: ProofReceipt | Mapping[str, Any]) -> dict[str, Any]:
    """Return a minimum public receipt without raw proof or nullifier material."""

    source = receipt.to_dict() if isinstance(receipt, ProofReceipt) else dict(receipt)
    public_inputs = dict(source.get("public_inputs") or {})
    nullifier_ref = str(public_inputs.get("nullifier_ref") or "")
    sanitized = _sanitize(source)
    assert isinstance(sanitized, dict)
    safe_inputs = sanitized.setdefault("public_inputs", {})
    if nullifier_ref and isinstance(safe_inputs, dict):
        safe_inputs.setdefault("nullifier_commitment", public_nullifier_commitment(nullifier_ref))
    return sanitized


__all__ = [
    "WORLD_ID_PROOF_TYPE",
    "create_world_id_proof_receipt",
    "proof_system_for_protocol",
    "public_nullifier_commitment",
    "receipt_is_active",
    "sanitize_world_id_proof_receipt",
    "verifier_id_for_protocol",
    "world_id_proof_public_inputs",
]

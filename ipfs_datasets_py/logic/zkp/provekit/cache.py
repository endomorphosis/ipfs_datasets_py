"""Proof cache key and IPFS public payload construction for ProveKit.

Cache keys are deterministic hashes of the components that distinguish one
proof context from another:

- backend ID (``"provekit"``)
- circuit ref (e.g. ``"provekit_knowledge_of_axioms@v1"``)
- hash backend (e.g. ``"sha256"``)
- verifier-key digest (SHA-256 of the ``.pkv`` file)
- ProveKit commit hash
- ruleset ID (e.g. ``"TDFOL_v1"``)

IPFS payloads are restricted to the public proof envelope: raw proof bytes,
public inputs, attestation view, and artifact references. Private witness
material, prover-key paths, and axiom text must never appear.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Mapping, Optional


PROVEKIT_CACHE_KEY_SCHEMA = "provekit-cache-key-v1"
PROVEKIT_IPFS_PAYLOAD_SCHEMA = "provekit-ipfs-payload-v1"

_PRIVATE_ARTIFACT_KEYS = frozenset(
    {
        "prover_key_path",
        "pkp_path",
        "input_path",
        "prover_toml_path",
        "cwd",
        "package_dir",
    }
)


def build_provekit_proof_cache_key(
    *,
    backend_id: str,
    circuit_ref: str,
    hash_backend: str,
    verifier_key_sha256: str,
    provekit_commit: str,
    ruleset_id: str,
) -> str:
    """Return a deterministic SHA-256 cache key for a ProveKit proof context.

    The key covers the six components that distinguish one proof validity
    domain from another. Changing any component invalidates the key.

    Args:
        backend_id: ProveKit backend identifier (e.g. ``"provekit"``).
        circuit_ref: Canonical circuit reference (e.g. ``"provekit_knowledge_of_axioms@v1"``).
        hash_backend: Hash algorithm used during key preparation (e.g. ``"sha256"``).
        verifier_key_sha256: SHA-256 hex digest of the ``.pkv`` verifier key file.
        provekit_commit: ProveKit git commit hash used to prepare the keys.
        ruleset_id: Ruleset identifier bound to the circuit (e.g. ``"TDFOL_v1"``).

    Returns:
        Lowercase 64-character SHA-256 hex string.

    Raises:
        ValueError: if any required component is empty or ``verifier_key_sha256``
            is not a valid 64-character hex string.
    """
    _validate_non_empty("backend_id", backend_id)
    _validate_non_empty("circuit_ref", circuit_ref)
    _validate_non_empty("hash_backend", hash_backend)
    _validate_sha256_hex("verifier_key_sha256", verifier_key_sha256)
    _validate_non_empty("provekit_commit", provekit_commit)
    _validate_non_empty("ruleset_id", ruleset_id)

    key_material: dict[str, str] = {
        "schema": PROVEKIT_CACHE_KEY_SCHEMA,
        "backend_id": backend_id,
        "circuit_ref": circuit_ref,
        "hash_backend": hash_backend,
        "verifier_key_sha256": verifier_key_sha256,
        "provekit_commit": provekit_commit,
        "ruleset_id": ruleset_id,
    }
    canonical = json.dumps(
        key_material,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_provekit_proof_cache_key_from_proof(
    proof_public_inputs: Mapping[str, Any],
    proof_metadata: Mapping[str, Any],
    *,
    verifier_key_sha256: str,
    provekit_commit: Optional[str] = None,
) -> str:
    """Derive a cache key from a ``ZKPProof`` public inputs and metadata dict.

    This is a convenience wrapper around :func:`build_provekit_proof_cache_key`
    that extracts the required components from the proof envelope produced by
    ``ProveKitBackend``.

    Args:
        proof_public_inputs: The ``ZKPProof.public_inputs`` mapping.
        proof_metadata: The ``ZKPProof.metadata`` mapping.
        verifier_key_sha256: SHA-256 of the verifier key used for this proof.
        provekit_commit: Override for ProveKit commit; falls back to
            ``proof_metadata["provekit"]["provekit_commit"]`` or
            ``proof_metadata["provekit_commit"]``.

    Returns:
        Lowercase 64-character SHA-256 hex string.
    """
    pub = dict(proof_public_inputs or {})
    meta = dict(proof_metadata or {})

    backend_id = str(meta.get("backend") or "provekit")
    circuit_ref = str(pub.get("circuit_ref") or "")
    hash_backend = str(
        meta.get("hash_backend")
        or (meta.get("provekit") or {}).get("hash_backend")
        or "sha256"
    )
    ruleset_id = str(pub.get("ruleset_id") or "")

    if provekit_commit is None:
        provekit_nested = meta.get("provekit") or {}
        provekit_commit = str(
            provekit_nested.get("provekit_commit")
            or meta.get("provekit_commit")
            or ""
        )

    return build_provekit_proof_cache_key(
        backend_id=backend_id,
        circuit_ref=circuit_ref,
        hash_backend=hash_backend,
        verifier_key_sha256=verifier_key_sha256,
        provekit_commit=provekit_commit,
        ruleset_id=ruleset_id,
    )


def build_provekit_ipfs_payload(
    proof_public_inputs: Mapping[str, Any],
    proof_metadata: Mapping[str, Any],
    proof_data: bytes,
    *,
    verifier_key_ref: str = "",
    manifest_sha256: str = "",
    proof_system: str = "ProveKit-WHIR",
) -> dict[str, Any]:
    """Build a public-only IPFS payload from a ProveKit proof envelope.

    The payload is safe to publish to IPFS or store in a public cache. It
    contains the proof bytes (base64), all public inputs, the attestation
    view, and artifact references. It never includes prover key paths,
    witness material, or private axiom text.

    Args:
        proof_public_inputs: The ``ZKPProof.public_inputs`` mapping (already
            witness-free per the backend contract).
        proof_metadata: The ``ZKPProof.metadata`` mapping. Prover-key and
            witness paths are stripped automatically.
        proof_data: Raw proof bytes (e.g. ``.np`` file contents).
        verifier_key_ref: IPFS CID or canonical path reference for the
            verifier key artifact. Optional but recommended.
        manifest_sha256: SHA-256 of the ``ProveKitArtifactManifest`` for
            traceability. Optional.
        proof_system: Proof system label (default: ``"ProveKit-WHIR"``).

    Returns:
        A JSON-serialisable dict containing only public information.
    """
    meta = dict(proof_metadata or {})
    attestation_view = meta.get("attestation_view") or {}
    provekit_meta = dict(meta.get("provekit") or {})

    public_artifact_refs: dict[str, str] = {}
    for key in ("verifier_key_path", "pkv_path", "proof_path", "proof_output_path", "program_dir"):
        value = provekit_meta.get("artifacts", {}).get(key) or meta.get(
            "provekit_artifacts", {}
        ).get(key)
        if value:
            public_artifact_refs[key] = str(value)
    if verifier_key_ref:
        public_artifact_refs["verifier_key_ref"] = verifier_key_ref

    payload: dict[str, Any] = {
        "schema": PROVEKIT_IPFS_PAYLOAD_SCHEMA,
        "backend_id": str(meta.get("backend") or "provekit"),
        "proof_system": proof_system,
        "proof_data_b64": base64.b64encode(proof_data).decode("ascii"),
        "proof_size_bytes": len(proof_data),
        "public_inputs": dict(proof_public_inputs or {}),
        "attestation_view": dict(attestation_view),
        "public_artifact_refs": public_artifact_refs,
    }
    if manifest_sha256:
        payload["manifest_sha256"] = manifest_sha256
    if provekit_meta.get("public_input_schema"):
        payload["public_input_schema"] = provekit_meta["public_input_schema"]
    if provekit_meta.get("public_input_hash"):
        payload["public_input_hash"] = provekit_meta["public_input_hash"]

    return payload


def provekit_ipfs_payload_is_public_only(payload: Mapping[str, Any]) -> bool:
    """Return True when ``payload`` contains no private witness material.

    Checks that none of the known private-artifact keys appear at any level
    of the payload. This is a defence-in-depth guard; the primary boundary
    is enforced by :func:`build_provekit_ipfs_payload`.
    """
    payload_str = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    for private_key in _PRIVATE_ARTIFACT_KEYS:
        if f'"{private_key}"' in payload_str:
            return False
    return True


def _validate_non_empty(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")


def _validate_sha256_hex(name: str, value: object) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(
            f"{name} must be a 64-character lowercase hex string, got {value!r}"
        )
    if value.lower() != value:
        raise ValueError(f"{name} must be lowercase hex")
    try:
        int(value, 16)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be valid hex") from exc


__all__ = [
    "PROVEKIT_CACHE_KEY_SCHEMA",
    "PROVEKIT_IPFS_PAYLOAD_SCHEMA",
    "build_provekit_proof_cache_key",
    "build_provekit_proof_cache_key_from_proof",
    "build_provekit_ipfs_payload",
    "provekit_ipfs_payload_is_public_only",
]

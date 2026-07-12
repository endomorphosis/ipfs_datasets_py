"""Verifier-backed Profile F Event-DAG compaction proofs.

This module is the canonical ZK provider for the three Python MCP++ services.
It deliberately does not manufacture a proof when the Groth16 binary or the
audited v3 proving/verifying-key pair is unavailable. Callers can retain the
Profile F hash-commitment certificate in that case, but must keep
``zero_knowledge`` false.

Circuit v3 proves knowledge of one to four private event digests whose
SHA-256 Merkle root and active-leaf count are public. Event digests are derived
as ``SHA256(UTF-8(event_cid))``; archive verification independently recomputes
the public root from the archived event CIDs before accepting the proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import base64
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence


PROFILE_F_RULESET = "MCP++_EventDAG_Compaction_v1"
PROOF_SYSTEM = "groth16-bn254-event-dag-v3"
CIRCUIT_VERSION = 3
MAX_EVENTS = 4


class EventDagZKUnavailable(RuntimeError):
    """Raised when a real Profile F proving or verification path is absent."""


def _sha256_bytes(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def event_digest(event_cid: str) -> bytes:
    if not isinstance(event_cid, str) or not event_cid:
        raise ValueError("event_cid must be a non-empty string")
    return _sha256_bytes(event_cid.encode("utf-8"))


def event_dag_merkle_root(event_cids: Sequence[str]) -> str:
    """Return the circuit-v3 root for one to four canonical event CIDs."""
    if not 1 <= len(event_cids) <= MAX_EVENTS:
        raise ValueError(f"Profile F Groth16 batches require 1..{MAX_EVENTS} event CIDs")
    leaves = [event_digest(event_cid) for event_cid in event_cids]
    leaves.extend([bytes(32)] * (MAX_EVENTS - len(leaves)))
    layer = [_sha256_bytes(leaf) for leaf in leaves]
    while len(layer) > 1:
        layer = [_sha256_bytes(layer[index] + layer[index + 1]) for index in range(0, len(layer), 2)]
    return layer[0].hex()


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _backend_root() -> Path:
    return _package_root() / "processors" / "groth16_backend"


def _binary_path() -> Path | None:
    for value in (os.environ.get("IPFS_DATASETS_GROTH16_BINARY"), os.environ.get("GROTH16_BINARY")):
        if value and Path(value).is_file():
            return Path(value)
    candidates = (
        _backend_root() / "target" / "release" / "groth16",
        _backend_root() / "bin" / "linux-x86_64" / "groth16",
        _backend_root() / "bin" / "darwin-aarch64" / "groth16",
        _backend_root() / "bin" / "darwin-x86_64" / "groth16",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _artifacts_root() -> Path:
    configured = (
        os.environ.get("IPFS_DATASETS_EVENT_DAG_GROTH16_ARTIFACTS")
        or os.environ.get("GROTH16_BACKEND_ARTIFACTS_ROOT")
    )
    return Path(configured) if configured else _backend_root() / "artifacts"


def _artifact_paths() -> tuple[Path, Path]:
    root = _artifacts_root() / f"v{CIRCUIT_VERSION}"
    return root / "proving_key.bin", root / "verifying_key.bin"


def verification_key_cid(verifying_key: bytes) -> str:
    """Return the CIDv1/raw/sha2-256 identifier for a verifying-key blob."""
    multihash = b"\x12\x20" + _sha256_bytes(verifying_key)
    cid_v1_raw = b"\x01\x55" + multihash
    return "b" + base64.b32encode(cid_v1_raw).decode("ascii").lower().rstrip("=")


def availability() -> dict[str, Any]:
    """Report whether this process can issue and verify real Profile F proofs."""
    binary = _binary_path()
    proving_key, verifying_key = _artifact_paths()
    available = bool(binary and proving_key.is_file() and verifying_key.is_file())
    verifying_key_bytes = verifying_key.read_bytes() if verifying_key.is_file() else None
    return {
        "available": available,
        "proof_system": PROOF_SYSTEM,
        "zero_knowledge": available,
        "circuit_version": CIRCUIT_VERSION,
        "ruleset_id": PROFILE_F_RULESET,
        "max_events": MAX_EVENTS,
        "binary": str(binary) if binary else None,
        "proving_key": str(proving_key),
        "verifying_key": str(verifying_key),
        "verification_key_sha256": hashlib.sha256(verifying_key_bytes).hexdigest() if verifying_key_bytes else None,
        "verification_key_cid": verification_key_cid(verifying_key_bytes) if verifying_key_bytes else None,
    }


def _require_available() -> tuple[Path, Path]:
    status = availability()
    if not status["available"]:
        raise EventDagZKUnavailable(
            "Profile F Groth16 backend unavailable; configure IPFS_DATASETS_GROTH16_BINARY "
            "and IPFS_DATASETS_EVENT_DAG_GROTH16_ARTIFACTS with audited v3 artifacts"
        )
    return Path(status["binary"]), _artifacts_root()


def _run(command: str, payload: Mapping[str, Any]) -> Any:
    binary, artifacts_root = _require_available()
    environment = dict(os.environ)
    environment["GROTH16_BACKEND_ARTIFACTS_ROOT"] = str(artifacts_root)
    completed = subprocess.run(
        [str(binary), command, "--input" if command == "prove" else "--proof", "/dev/stdin", "--output" if command == "prove" else "--json", "/dev/stdout" if command == "prove" else "--quiet", "--quiet"] if command == "prove" else [str(binary), "verify", "--proof", "/dev/stdin", "--json", "--quiet"],
        input=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=float(os.environ.get("MCPPP_EVENT_DAG_ZK_TIMEOUT_SECONDS", "300")),
        env=environment,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace").strip()
        raise EventDagZKUnavailable(f"Profile F Groth16 {command} failed: {detail or completed.returncode}")
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise EventDagZKUnavailable(f"Profile F Groth16 {command} emitted invalid JSON") from error


def _witness(event_cids: Sequence[str]) -> dict[str, Any]:
    root = event_dag_merkle_root(event_cids)
    return {
        "private_axioms": [],
        "theorem": "",
        "axioms_commitment_hex": "",
        "theorem_hash_hex": "",
        "circuit_version": CIRCUIT_VERSION,
        "ruleset_id": PROFILE_F_RULESET,
        "event_digests_hex": [event_digest(event_cid).hex() for event_cid in event_cids],
        "event_count": len(event_cids),
        "event_dag_merkle_root_hex": root,
    }


def prove_event_dag_compaction(event_cids: Sequence[str]) -> dict[str, Any]:
    """Create a real Profile F Groth16 certificate for a bounded event batch."""
    witness = _witness(event_cids)
    proof = _run("prove", witness)
    verification = _run("verify", proof)
    if not isinstance(verification, Mapping) or verification.get("valid") is not True:
        raise EventDagZKUnavailable("Profile F Groth16 proof did not verify")
    status = availability()
    return {
        "proof_system": PROOF_SYSTEM,
        "zero_knowledge": True,
        "circuit_version": CIRCUIT_VERSION,
        "ruleset_id": PROFILE_F_RULESET,
        "event_count": witness["event_count"],
        "zk_merkle_root": witness["event_dag_merkle_root_hex"],
        "verification_key_sha256": status["verification_key_sha256"],
        "verification_key_cid": status["verification_key_cid"],
        "proof": proof,
    }


def verify_event_dag_compaction(certificate: Mapping[str, Any], event_cids: Iterable[str] | None = None) -> dict[str, Any]:
    """Verify a Profile F certificate and optionally bind it to archive CIDs."""
    if certificate.get("proof_system") != PROOF_SYSTEM or certificate.get("zero_knowledge") is not True:
        return {"valid": False, "reason": "not_a_profile_f_groth16_certificate"}
    proof = certificate.get("proof")
    if not isinstance(proof, Mapping):
        return {"valid": False, "reason": "proof_missing"}
    if event_cids is not None:
        values = list(event_cids)
        if certificate.get("event_count") != len(values) or certificate.get("zk_merkle_root") != event_dag_merkle_root(values):
            return {"valid": False, "reason": "archive_root_mismatch"}
    try:
        result = _run("verify", proof)
    except EventDagZKUnavailable as error:
        return {"valid": False, "reason": str(error)}
    return {
        "valid": bool(isinstance(result, Mapping) and result.get("valid") is True),
        "proof_system": PROOF_SYSTEM,
        "zero_knowledge": True,
        "verification_key_sha256": certificate.get("verification_key_sha256"),
        "verification_key_cid": certificate.get("verification_key_cid"),
    }


__all__ = [
    "CIRCUIT_VERSION",
    "MAX_EVENTS",
    "PROFILE_F_RULESET",
    "PROOF_SYSTEM",
    "EventDagZKUnavailable",
    "availability",
    "event_dag_merkle_root",
    "prove_event_dag_compaction",
    "verify_event_dag_compaction",
    "verification_key_cid",
]

"""Groth16 backend entrypoint.

This module intentionally remains **fail-closed by default**.

Current state:
- The repository includes a Rust-based Groth16 implementation accessed via
    `backends/groth16_ffi.py`.
- The high-level `ZKPProver`/`ZKPVerifier` API uses the backend protocol defined
    in `backends/__init__.py` (theorem + private axioms → `ZKPProof`).

To avoid accidental production usage, this backend only enables the Rust FFI
path when explicitly opted-in via environment variable.

Opt-in:
- Set `IPFS_DATASETS_ENABLE_GROTH16=1` to enable proof generation/verification
    through the Rust binary (if present).

Determinism:
- Pass `metadata={"seed": <u64>}` to `ZKPProver.generate_proof(...)` (or this backend's
    `generate_proof(...)`) to request deterministic proof generation.
- For test vectors, `GROTH16_BACKEND_DETERMINISTIC=1` may also force stable timestamps
    in the Rust CLI output when supported.

When not enabled (default):
- Backend selection works, but `generate_proof`/`verify_proof` raise `ZKPError`.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Optional

from .. import ZKPError, ZKPProof
from ..canonicalization import (
    canonicalize_axioms,
    hash_axioms_commitment,
    hash_theorem,
    tdfol_v1_axioms_commitment_hex_v2,
)
from ..legal_theorem_semantics import derive_tdfol_v1_trace


@dataclass
class Groth16Backend:
    """Groth16 zkSNARK backend (gated Rust FFI implementation).

    Notes:
    - Default is fail-closed (requires explicit opt-in).
    - When enabled, this backend uses `backends.groth16_ffi.Groth16Backend`.
    """

    backend_id: str = "groth16"
    curve_id: str = "bn254"
    timeout_seconds: int = 30
    binary_path: Optional[str] = None

    def _enabled(self) -> bool:
        return os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "").strip() in {"1", "true", "TRUE", "yes", "YES"}

    def _ffi(self):
        # Import lazily to keep imports quiet and lightweight.
        from .groth16_ffi import Groth16Backend as Groth16FFIBackend

        return Groth16FFIBackend(binary_path=self.binary_path, timeout_seconds=self.timeout_seconds)

    def generate_proof(self, theorem: str, private_axioms: list[str], metadata: dict[str, Any]) -> ZKPProof:
        if not self._enabled():
            raise ZKPError(
                "Groth16 backend is disabled by default. "
                "Set IPFS_DATASETS_ENABLE_GROTH16=1 to enable Rust FFI proving, "
                "or use the default 'simulated' backend."
            )

        if not theorem:
            raise ZKPError("Theorem cannot be empty")
        if not private_axioms:
            raise ZKPError("At least one axiom required")

        canonical_axioms = canonicalize_axioms(private_axioms)

        circuit_version = int((metadata or {}).get("circuit_version", 1))
        ruleset_id = str((metadata or {}).get("ruleset_id", "TDFOL_v1"))

        if circuit_version >= 2 and ruleset_id == "TDFOL_v1":
            axioms_commitment_hex = tdfol_v1_axioms_commitment_hex_v2(canonical_axioms)
            trace = derive_tdfol_v1_trace(canonical_axioms, theorem)
            if trace is None:
                raise ZKPError(
                    "Theorem is not derivable under TDFOL_v1 semantics; "
                    "cannot build a derivation trace for circuit_version=2"
                )
            intermediate_steps = trace
        else:
            axioms_commitment_hex = hash_axioms_commitment(canonical_axioms).hex()
            intermediate_steps = []

        witness = {
            "private_axioms": canonical_axioms,
            # Preserve caller-provided theorem text in public inputs.
            # Hashing is canonicalized by canonicalization.hash_theorem().
            "theorem": theorem,
            "intermediate_steps": intermediate_steps,
            "axioms_commitment_hex": axioms_commitment_hex,
            "theorem_hash_hex": hash_theorem(theorem).hex(),
            "security_level": int((metadata or {}).get("security_level", 0)),
            "circuit_version": circuit_version,
            "ruleset_id": ruleset_id,
        }

        seed = (metadata or {}).get("seed")

        try:
            return self._ffi().generate_proof(json.dumps(witness), seed=seed)
        except Exception as e:
            # Convert backend failures to ZKPError (fail-closed).
            raise ZKPError(f"Groth16 proof generation failed: {e}")

    def verify_proof(self, proof: ZKPProof) -> bool:
        if not self._enabled():
            raise ZKPError(
                "Groth16 backend is disabled by default. "
                "Set IPFS_DATASETS_ENABLE_GROTH16=1 to enable Rust FFI verification, "
                "or use the default 'simulated' backend."
            )

        try:
            proof_json = proof.proof_data.decode("utf-8")
        except Exception as e:
            raise ZKPError(f"Groth16 proof is not in expected JSON-encoded format: {e}")

        try:
            return self._ffi().verify_proof(proof_json)
        except Exception as e:
            raise ZKPError(f"Groth16 proof verification failed: {e}")
    

    def setup(self, version: int = 1, *, seed: Optional[int] = None) -> dict[str, Any]:
        if not self._enabled():
            raise ZKPError(
                "Groth16 backend is disabled by default. "
                "Set IPFS_DATASETS_ENABLE_GROTH16=1 to enable Rust FFI setup, "
                "or use the default 'simulated' backend."
            )

        try:
            return self._ffi().setup(version, seed=seed)
        except Exception as e:
            raise ZKPError(f"Groth16 setup failed: {e}")

    # NOTE: Circuit compilation / setup / key management remains out of scope for
    # this adapter entrypoint. See GROTH16_IMPLEMENTATION_PLAN.md.

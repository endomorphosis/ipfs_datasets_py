"""Simulated ZKP backend.

This backend implements the existing demo-only behavior and is intended to be
used as the default backend.

Security: NOT cryptographically secure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import hashlib
import json
import secrets
import time

from .. import ZKPError, ZKPProof
from ..canonicalization import axioms_commitment_hex, normalize_text, theorem_hash_hex


@dataclass
class SimulatedBackend:
    backend_id: str = "simulated"


    def _simulated_proof_layout_metadata(self) -> dict[str, Any]:
        magic = b"SIMZKP\x00\x01"
        return {
            "format": "SIMZKP/1",
            "byte_length": 160,
            "magic_hex": magic.hex(),
            "segments": [
                {"tag": "magic", "offset": 0, "length": 8},
                {
                    "tag": "proof_hash",
                    "offset": 8,
                    "length": 32,
                    "description": "SHA256(circuit_hash || witness || normalize_text(theorem))",
                },
                {
                    "tag": "circuit_hash",
                    "offset": 40,
                    "length": 32,
                    "description": "SHA256(circuit metadata derived from theorem + axioms)",
                },
                {
                    "tag": "witness",
                    "offset": 72,
                    "length": 32,
                    "description": "SHA256(canonicalized axioms JSON)",
                },
                {"tag": "padding", "offset": 104, "length": 56, "description": "random bytes"},
            ],
        }

    def generate_proof(self, theorem: str, private_axioms: list[str], metadata: dict) -> ZKPProof:
        if not theorem:
            raise ZKPError("Theorem cannot be empty")
        if not private_axioms:
            raise ZKPError("At least one axiom required")

        circuit_hash = self._hash_circuit(theorem, private_axioms)
        witness = self._compute_witness(private_axioms)
        proof_data = self._simulate_groth16_proof(circuit_hash=circuit_hash, witness=witness, theorem=theorem)

        circuit_version = int((metadata or {}).get("circuit_version", 1))
        ruleset_id = str((metadata or {}).get("ruleset_id", "TDFOL_v1"))


        output_metadata = {**(metadata or {})}
        output_metadata.setdefault("simulated_proof_layout", self._simulated_proof_layout_metadata())

        return ZKPProof(
            proof_data=proof_data,
            public_inputs={
                "theorem": theorem,
                "theorem_hash": theorem_hash_hex(theorem),
                "axioms_commitment": axioms_commitment_hex(private_axioms),
                "circuit_version": circuit_version,
                "ruleset_id": ruleset_id,
            },
            metadata={
                **output_metadata,
                "proof_system": "Groth16 (simulated)",
                "num_axioms": len(private_axioms),
            },
            timestamp=time.time(),
            size_bytes=len(proof_data),
        )

    def verify_proof(self, proof: ZKPProof) -> bool:
        theorem = proof.public_inputs.get("theorem", "")
        theorem_hash = proof.public_inputs.get("theorem_hash", "")

        # Check required public input keys
        if "theorem" not in proof.public_inputs or "theorem_hash" not in proof.public_inputs:
            return False

        # Verify theorem hash matches
        expected_hash = theorem_hash_hex(theorem)
        legacy_hash = hashlib.sha256(theorem.encode()).hexdigest()
        if theorem_hash not in (expected_hash, legacy_hash):
            return False

        # Check proof data size bounds (simulated Groth16-like)
        if len(proof.proof_data) < 100 or len(proof.proof_data) > 300:
            return False

        # Check metadata sanity (if present)
        if hasattr(proof, 'metadata') and isinstance(proof.metadata, dict):
            # Verify proof_system field exists (for clarity)
            if 'proof_system' not in proof.metadata:
                return False

        return True

    def _hash_circuit(self, theorem: str, axioms: list[str]) -> bytes:
        normalized_theorem = normalize_text(theorem)
        normalized_axioms = [normalize_text(a) for a in axioms]
        circuit_data = json.dumps(
            {
                "theorem": normalized_theorem,
                "num_axioms": len(normalized_axioms),
                "axiom_hashes": [hashlib.sha256(a.encode("utf-8")).hexdigest() for a in normalized_axioms],
            },
            sort_keys=True,
        )
        return hashlib.sha256(circuit_data.encode()).digest()

    def _compute_witness(self, axioms: list[str]) -> bytes:
        witness_data = json.dumps([normalize_text(a) for a in axioms], sort_keys=True)
        return hashlib.sha256(witness_data.encode()).digest()

    def _simulate_groth16_proof(self, circuit_hash: bytes, witness: bytes, theorem: str) -> bytes:
        proof_inputs = circuit_hash + witness + normalize_text(theorem).encode("utf-8")
        proof_hash = hashlib.sha256(proof_inputs).digest()

        # Byte layout (fixed 160 bytes):
        # - [0:8]     Magic header: b"SIMZKP\x00\x01"
        # - [8:40]    proof_hash: SHA256(circuit_hash || witness || normalize_text(theorem))
        # - [40:72]   circuit_hash: SHA256(normalized theorem + axiom hashes metadata)
        # - [72:104]  witness: SHA256(canonicalized axioms JSON)
        # - [104:160] random padding (demo-only; makes bytes look Groth16-ish)
        #
        # This is demo-only and intentionally non-verifiable as a real zkSNARK.
        magic = b"SIMZKP\x00\x01"
        padding = secrets.token_bytes(56)
        simulated_proof = magic + proof_hash + circuit_hash + witness + padding
        return simulated_proof

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


@dataclass
class SimulatedBackend:
    backend_id: str = "simulated"

    def generate_proof(self, theorem: str, private_axioms: list[str], metadata: dict) -> ZKPProof:
        if not theorem:
            raise ZKPError("Theorem cannot be empty")
        if not private_axioms:
            raise ZKPError("At least one axiom required")

        circuit_hash = self._hash_circuit(theorem, private_axioms)
        witness = self._compute_witness(private_axioms)
        proof_data = self._simulate_groth16_proof(circuit_hash=circuit_hash, witness=witness, theorem=theorem)

        return ZKPProof(
            proof_data=proof_data,
            public_inputs={
                "theorem": theorem,
                "theorem_hash": hashlib.sha256(theorem.encode()).hexdigest(),
            },
            metadata={
                **(metadata or {}),
                "proof_system": "Groth16 (simulated)",
                "num_axioms": len(private_axioms),
            },
            timestamp=time.time(),
            size_bytes=len(proof_data),
        )

    def verify_proof(self, proof: ZKPProof) -> bool:
        theorem = proof.public_inputs.get("theorem", "")
        theorem_hash = proof.public_inputs.get("theorem_hash", "")

        expected_hash = hashlib.sha256(theorem.encode()).hexdigest()
        if theorem_hash != expected_hash:
            return False

        if len(proof.proof_data) < 100 or len(proof.proof_data) > 300:
            return False

        return True

    def _hash_circuit(self, theorem: str, axioms: list[str]) -> bytes:
        circuit_data = json.dumps(
            {
                "theorem": theorem,
                "num_axioms": len(axioms),
                "axiom_hashes": [hashlib.sha256(a.encode()).hexdigest() for a in axioms],
            },
            sort_keys=True,
        )
        return hashlib.sha256(circuit_data.encode()).digest()

    def _compute_witness(self, axioms: list[str]) -> bytes:
        witness_data = json.dumps(axioms, sort_keys=True)
        return hashlib.sha256(witness_data.encode()).digest()

    def _simulate_groth16_proof(self, circuit_hash: bytes, witness: bytes, theorem: str) -> bytes:
        proof_inputs = circuit_hash + witness + theorem.encode()
        proof_hash = hashlib.sha256(proof_inputs).digest()

        simulated_proof = (
            proof_hash +
            secrets.token_bytes(64) +
            secrets.token_bytes(64)
        )

        # Fixed-size simulated proof (matches existing tests expectation ~160 bytes).
        return simulated_proof[:160]

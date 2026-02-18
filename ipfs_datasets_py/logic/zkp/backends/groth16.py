"""Groth16 backend (production placeholder).

This backend is intentionally NOT implemented yet.

Rationale:
- A production Groth16 prover/verifier requires a mature cryptographic stack,
  trusted setup artifacts, circuit compilation, and careful public input encoding.

This backend must **fail closed** until the real implementation is added.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import ZKPError, ZKPProof


@dataclass
class Groth16Backend:
    backend_id: str = "groth16"

    def generate_proof(self, theorem: str, private_axioms: list[str], metadata: dict) -> ZKPProof:
        raise ZKPError(
            "Groth16 backend is not implemented. "
            "Use the default simulated backend, or implement a real Groth16 backend as described in "
            "logic/zkp/GROTH16_IMPLEMENTATION_PLAN.md."
        )

    def verify_proof(self, proof: ZKPProof) -> bool:
        raise ZKPError(
            "Groth16 backend is not implemented. "
            "Use the default simulated backend, or implement a real Groth16 backend as described in "
            "logic/zkp/GROTH16_IMPLEMENTATION_PLAN.md."
        )

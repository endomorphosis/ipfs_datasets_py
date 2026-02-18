"""Groth16 backend (production placeholder).

This backend is intentionally NOT implemented yet.

Rationale:
- A production Groth16 prover/verifier requires a mature cryptographic stack,
  trusted setup artifacts, circuit compilation, and careful public input encoding.

This backend must **fail closed** until the real implementation is added.

Implementation Plan:
See GROTH16_IMPLEMENTATION_PLAN.md for detailed implementation roadmap.

Key Requirements for Real Implementation:
1. Circuit compilation from theorem/axioms to R1CS constraints
2. Trusted setup (circuit-specific proving/verifying keys)
3. Proof generation using py_ecc or similar library
4. On-chain verifier compatibility (BN254 curve for EVM)
5. IPFS-addressable artifacts (PK/VK CIDs)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .. import ZKPError, ZKPProof


@dataclass
class Groth16Backend:
    """Groth16 zkSNARK backend (placeholder).
    
    This is a fail-closed placeholder. All operations raise ZKPError
    directing users to the implementation plan.
    
    Attributes:
        backend_id: Backend identifier ("groth16")
        curve_id: Elliptic curve for proof system (default: "bn254")
        circuit_version: Circuit version identifier
    """
    
    backend_id: str = "groth16"
    curve_id: str = "bn254"  # EVM-compatible curve
    circuit_version: Optional[str] = None
    
    def generate_proof(
        self,
        theorem: str,
        private_axioms: list[str],
        metadata: dict
    ) -> ZKPProof:
        """Generate Groth16 proof (NOT IMPLEMENTED).
        
        Args:
            theorem: Public theorem statement
            private_axioms: Private axioms (witness)
            metadata: Additional proof metadata
            
        Returns:
            ZKPProof object
            
        Raises:
            ZKPError: Always (not implemented)
        """
        raise ZKPError(
            "Groth16 backend is not implemented. "
            "Use the default simulated backend, or implement a real Groth16 backend as described in "
            "logic/zkp/GROTH16_IMPLEMENTATION_PLAN.md."
        )
    
    def verify_proof(self, proof: ZKPProof) -> bool:
        """Verify Groth16 proof (NOT IMPLEMENTED).
        
        Args:
            proof: ZKP proof object
            
        Returns:
            bool: Verification result
            
        Raises:
            ZKPError: Always (not implemented)
        """
        raise ZKPError(
            "Groth16 backend is not implemented. "
            "Use the default simulated backend, or implement a real Groth16 backend as described in "
            "logic/zkp/GROTH16_IMPLEMENTATION_PLAN.md."
        )
    
    # Stubs for future implementation
    
    def compile_circuit(self, theorem: str, axioms: list[str]) -> "R1CSCircuit":
        """Compile theorem/axioms to R1CS constraints (STUB).
        
        This will convert logical statements into arithmetic constraints
        for the Groth16 proof system.
        
        Args:
            theorem: Theorem to prove
            axioms: Axioms available for proof
            
        Returns:
            R1CSCircuit: Compiled circuit (NOT IMPLEMENTED)
            
        Raises:
            ZKPError: Always (not implemented)
        """
        raise ZKPError("Circuit compilation not implemented yet")
    
    def load_proving_key(self, circuit_id: str, version: str) -> "ProvingKey":
        """Load proving key from IPFS (STUB).
        
        In a real implementation, this would:
        1. Compute PK CID from (circuit_id, version)
        2. Fetch PK artifact from IPFS
        3. Deserialize and validate
        
        Args:
            circuit_id: Circuit identifier
            version: Circuit version
            
        Returns:
            ProvingKey: Proving key material (NOT IMPLEMENTED)
            
        Raises:
            ZKPError: Always (not implemented)
        """
        raise ZKPError("Proving key loading not implemented yet")
    
    def load_verifying_key(self, circuit_id: str, version: str) -> "VerifyingKey":
        """Load verifying key from IPFS (STUB).
        
        In a real implementation, this would:
        1. Compute VK CID from (circuit_id, version)
        2. Fetch VK artifact from IPFS
        3. Deserialize and validate
        4. Optionally verify on-chain registration
        
        Args:
            circuit_id: Circuit identifier
            version: Circuit version
            
        Returns:
            VerifyingKey: Verifying key material (NOT IMPLEMENTED)
            
        Raises:
            ZKPError: Always (not implemented)
        """
        raise ZKPError("Verifying key loading not implemented yet")
    
    def canonicalize_inputs(self, theorem: str, axioms: list[str]) -> tuple[str, list[str]]:
        """Canonicalize theorem and axioms (STUB).
        
        In a real implementation, this would:
        1. Normalize whitespace and Unicode
        2. Sort axioms for deterministic ordering
        3. Apply domain-specific canonical forms
        
        Args:
            theorem: Raw theorem string
            axioms: Raw axiom strings
            
        Returns:
            tuple: (canonical_theorem, canonical_axioms) (NOT IMPLEMENTED)
            
        Raises:
            ZKPError: Always (not implemented)
        """
        raise ZKPError("Input canonicalization not implemented yet")
    
    def compute_public_inputs(self, theorem: str, axioms: list[str]) -> dict:
        """Compute public inputs for proof (STUB).
        
        In a real implementation, this would compute:
        - theorem_hash: H(canonical_theorem)
        - axioms_commitment: Merkle root of axioms
        - ruleset_id: Which inference rules used
        - circuit_version: Constraint system version
        
        Args:
            theorem: Canonical theorem
            axioms: Canonical axioms
            
        Returns:
            dict: Public input values (NOT IMPLEMENTED)
            
        Raises:
            ZKPError: Always (not implemented)
        """
        raise ZKPError("Public input computation not implemented yet")


# Type stubs for future implementation
# These classes don't exist yet but are referenced in the stubs above

class R1CSCircuit:
    """R1CS constraint system (STUB).
    
    Will represent the arithmetic circuit as:
    A * witness ⊙ B * witness = C * witness
    """
    pass


class ProvingKey:
    """Groth16 proving key (STUB).
    
    Will contain:
    - Toxic waste-dependent elements for proof generation
    - Circuit-specific parameters
    """
    pass


class VerifyingKey:
    """Groth16 verifying key (STUB).
    
    Will contain:
    - Public parameters for verification
    - Can be published on-chain
    """
    pass


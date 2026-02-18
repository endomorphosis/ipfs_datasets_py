"""
Backend protocol definition for ZKP operations.

This module defines the abstract interface that all ZKP backends must implement.
Backends are loaded lazily to keep module imports lightweight.
"""

from typing import Protocol, runtime_checkable, Any
from dataclasses import dataclass


@runtime_checkable
class ZKBackend(Protocol):
    """
    Abstract protocol for ZKP backend implementations.
    
    All backend implementations must provide these methods and properties.
    This protocol enables pluggable backends (simulated vs. real Groth16).
    """
    
    def generate_proof(
        self,
        theorem: str,
        private_axioms: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> "ZKPProof":
        """
        Generate a zero-knowledge proof.
        
        Args:
            theorem: Public statement to prove
            private_axioms: Secret axioms used to construct the proof
            metadata: Optional metadata (circuit_id, version, etc.)
        
        Returns:
            ZKPProof object with proof data and public inputs
        """
        ...
    
    def verify_proof(self, proof: "ZKPProof") -> bool:
        """
        Verify a zero-knowledge proof.
        
        Args:
            proof: ZKPProof object to verify
        
        Returns:
            True if proof is valid, False otherwise. Must never raise.
        """
        ...
    
    @property
    def backend_id(self) -> str:
        """
        Identifier for this backend implementation.
        
        Examples: 'simulated', 'groth16', 'groth16_ark', etc.
        """
        ...
    
    @property
    def curve_id(self) -> str:
        """
        Elliptic curve identifier for this backend.
        
        Examples: 'bn254', 'bls12_381', 'simulation', etc.
        """
        ...


# Placeholder for ZKPProof (imported from logic/zkp/zkp_proof.py)
class ZKPProof:
    """Placeholder - see zkp_proof.py for full definition."""
    pass

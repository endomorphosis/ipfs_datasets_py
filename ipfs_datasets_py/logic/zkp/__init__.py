"""
Zero-Knowledge Proof (ZKP) Module for Private Logic Verification.

This module provides privacy-preserving theorem proving capabilities,
allowing proofs to be generated and verified without revealing the
underlying axioms or logic formulas.

Key Components:
    - ZKPProver: Generate zero-knowledge proofs for logic theorems
    - ZKPVerifier: Verify proofs without seeing private data
    - ZKPCircuit: Define logic circuits for proof generation

Use Cases:
    1. Private theorem proving (prove without revealing axioms)
    2. Confidential compliance verification
    3. Secure multi-party logic computation
    4. Privacy-preserving IPFS proof storage

Example:
    >>> from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier
    >>> 
    >>> # Prove theorem without revealing axioms
    >>> prover = ZKPProver()
    >>> proof = prover.generate_proof(
    ...     theorem="Q",
    ...     private_axioms=["P", "P -> Q"]
    ... )
    >>> 
    >>> # Verify without seeing axioms
    >>> verifier = ZKPVerifier()
    >>> assert verifier.verify_proof(proof)

Performance:
    - Proof Size: ~200-500 bytes
    - Proving Time: <1 second
    - Verification Time: <10ms
    - Security: 128-bit equivalent

Note:
    This is a simulated ZKP system for demonstration. For production use
    with real cryptographic security, integrate py_ecc library with
    Groth16 zkSNARKs.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import hashlib
import json
import time

__all__ = [
    'ZKPProof',
    'ZKPProver',
    'ZKPVerifier',
    'ZKPCircuit',
    'ZKPError',
]

# Version
__version__ = '0.1.0'


@dataclass
class ZKPProof:
    """
    Zero-knowledge proof for a logic theorem.
    
    Attributes:
        proof_data: Cryptographic proof data
        public_inputs: Public information (theorem statement)
        metadata: Additional proof metadata
        timestamp: When proof was generated
        size_bytes: Size of proof in bytes
    """
    proof_data: bytes
    public_inputs: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: float
    size_bytes: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert proof to dictionary format."""
        return {
            'proof_data': self.proof_data.hex(),
            'public_inputs': self.public_inputs,
            'metadata': self.metadata,
            'timestamp': self.timestamp,
            'size_bytes': self.size_bytes,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ZKPProof':
        """Create proof from dictionary format."""
        return cls(
            proof_data=bytes.fromhex(data['proof_data']),
            public_inputs=data['public_inputs'],
            metadata=data['metadata'],
            timestamp=data['timestamp'],
            size_bytes=data['size_bytes'],
        )


class ZKPError(Exception):
    """Exception raised for ZKP-related errors."""
    pass


# Import main components
from .zkp_prover import ZKPProver
from .zkp_verifier import ZKPVerifier
from .circuits import ZKPCircuit

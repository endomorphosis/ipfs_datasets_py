"""
Zero-Knowledge Proof (ZKP) SIMULATION Module - Educational/Demo Only.

⚠️ WARNING: This is a SIMULATED ZKP system for educational and demonstration
purposes ONLY. It is NOT cryptographically secure and should NOT be used in
production systems requiring real zero-knowledge proofs.

What this module provides:
    - Educational demonstration of ZKP concepts
    - Fast simulation for prototyping (<0.1ms)
    - Simple API showing how ZKP systems work
    - Mock proofs using hash-based commitments

What this module does NOT provide:
    - Real cryptographic security
    - Actual zkSNARKs (Groth16, PLONK, etc.)
    - Production-ready zero-knowledge proofs
    - Integration with py_ecc or other crypto libraries

For production ZKP, you need:
    - Integrate py_ecc library with Groth16 zkSNARKs
    - Implement proper trusted setup
    - Use real circuit compilation
    - Add cryptographic security validations

Key Components (Simulated):
    - SimulatedZKPProver: Generate mock proofs for demonstration
    - SimulatedZKPVerifier: Verify mock proofs
    - SimulatedZKPCircuit: Mock circuit definitions

Use Cases (Educational Only):
    1. Learning ZKP concepts and workflows
    2. Prototyping ZKP-enabled systems
    3. Testing application logic with mock proofs
    4. Educational demonstrations

Example:
    >>> from ipfs_datasets_py.logic.zkp import SimulatedZKPProver, SimulatedZKPVerifier
    >>> 
    >>> # SIMULATION - NOT cryptographically secure!
    >>> prover = SimulatedZKPProver()
    >>> proof = prover.generate_proof(
    ...     theorem="Q",
    ...     private_axioms=["P", "P -> Q"]
    ... )
    >>> 
    >>> # Verify mock proof
    >>> verifier = SimulatedZKPVerifier()
    >>> assert verifier.verify_proof(proof)  # Mock verification
    >>> 
    >>> print("⚠️  This is a SIMULATION - not cryptographically secure!")

Performance (Simulation):
    - Proof Size: ~160 bytes (mock commitment)
    - Proving Time: <0.1ms (no real cryptography)
    - Verification Time: <0.01ms (simple hash check)
    - Security: NONE - simulation only!

For Production Use:
    See KNOWN_LIMITATIONS.md for roadmap to real ZKP integration.
    DO NOT use this module for security-critical applications.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import hashlib
import json
import time

__all__ = [
    'ZKPProof',  # Kept for backward compatibility
    'SimulatedZKPProof',  # New name reflecting simulation
    'ZKPProver',  # Deprecated - use SimulatedZKPProver
    'SimulatedZKPProver',  # Correct name
    'ZKPVerifier',  # Deprecated - use SimulatedZKPVerifier
    'SimulatedZKPVerifier',  # Correct name
    'ZKPCircuit',  # Deprecated - use SimulatedZKPCircuit
    'SimulatedZKPCircuit',  # Correct name
    'ZKPError',
    'create_implication_circuit',
]

# WARNING: Import prints a warning to prevent accidental production use
import warnings
warnings.warn(
    "⚠️  WARNING: ipfs_datasets_py.logic.zkp is a SIMULATION module, NOT cryptographically secure! "
    "Do not use for production systems requiring real zero-knowledge proofs. "
    "See KNOWN_LIMITATIONS.md for details.",
    UserWarning,
    stacklevel=2
)

# Version
__version__ = '0.1.0'


@dataclass
class ZKPProof:
    """
    SIMULATED Zero-Knowledge Proof - Educational/Demo Only.
    
    ⚠️  WARNING: This is NOT a cryptographically secure proof!
    It uses simple hash-based commitments for demonstration purposes.
    
    For production ZKP, integrate py_ecc library with real zkSNARKs.
    
    Attributes:
        proof_data: Mock proof data (hash-based, not cryptographic)
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


# Import main components - must come after ZKPProof and ZKPError definitions
from .zkp_prover import ZKPProver  # noqa: E402
from .zkp_verifier import ZKPVerifier  # noqa: E402
from .circuits import ZKPCircuit, create_implication_circuit  # noqa: E402

# Aliases with correct naming (Simulated prefix)
SimulatedZKPProof = ZKPProof  # Same class, clearer name
SimulatedZKPProver = ZKPProver  # Same class, clearer name
SimulatedZKPVerifier = ZKPVerifier  # Same class, clearer name
SimulatedZKPCircuit = ZKPCircuit  # Same class, clearer name

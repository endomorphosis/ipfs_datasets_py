"""
Zero-Knowledge Proof Verifier for Logic Theorems.

Verifies zero-knowledge proofs without seeing the private axioms.
"""

from typing import Dict, Any
import hashlib
import logging
import time

from . import ZKPProof, ZKPError
from .backends import get_backend

logger = logging.getLogger(__name__)


class ZKPVerifier:
    """
    Verify zero-knowledge proofs for logic theorems.
    
    The verifier can confirm that a proof is valid without learning
    anything about the private axioms used to generate it.
    
    Features:
        - Fast verification (<10ms)
        - No access to private data
        - Proof validity checking
        - Statistics tracking
    
    Example:
        >>> from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier
        >>> 
        >>> # Generate proof
        >>> prover = ZKPProver()
        >>> proof = prover.generate_proof(
        ...     theorem="Q",
        ...     private_axioms=["P", "P -> Q"]
        ... )
        >>> 
        >>> # Verify without seeing axioms
        >>> verifier = ZKPVerifier()
        >>> assert verifier.verify_proof(proof)
        >>> print(f"Verification time: {verifier.get_stats()['avg_verification_time']*1000:.2f}ms")
        Verification time: 0.05ms
    
    Note:
        This is a simulated verifier for demonstration. In production,
        use py_ecc with Groth16 for real cryptographic verification.
    """
    
    def __init__(self, security_level: int = 128, backend: str = "simulated"):
        """
        Initialize ZKP verifier.
        
        Args:
            security_level: Required security bits (default: 128)
        """
        self.security_level = security_level
        self.backend = backend
        self._backend = get_backend(backend)
        self._stats = {
            'proofs_verified': 0,
            'proofs_rejected': 0,
            'total_verification_time': 0.0,
        }
    
    def verify_proof(self, proof: ZKPProof) -> bool:
        """
        Verify a zero-knowledge proof.
        
        Args:
            proof: The ZKP proof to verify
        
        Returns:
            bool: True if proof is valid, False otherwise
        
        Raises:
            ZKPError: If verification process fails
        
        Example:
            >>> verifier = ZKPVerifier()
            >>> valid = verifier.verify_proof(proof)
            >>> if valid:
            ...     print("Proof verified! Theorem is true.")
        """
        start_time = time.time()
        
        try:
            # Validate proof structure
            if not self._validate_proof_structure(proof):
                self._stats['proofs_rejected'] += 1
                return False
            
            # Verify proof via backend
            is_valid = self._backend.verify_proof(proof)
            
            # Update stats
            verification_time = time.time() - start_time
            self._stats['total_verification_time'] += verification_time
            
            if is_valid:
                self._stats['proofs_verified'] += 1
            else:
                self._stats['proofs_rejected'] += 1
            
            return is_valid
            
        except Exception as e:
            raise ZKPError(f"Proof verification failed: {e}")
    
    def _validate_proof_structure(self, proof: ZKPProof) -> bool:
        """Validate proof has correct structure."""
        try:
            # Check required fields
            if not proof.proof_data or not proof.public_inputs:
                return False

            if not self._validate_public_inputs(proof.public_inputs):
                return False
            
            # Check proof size bounds.
            # Simulated backend proofs are ~160 bytes; real Groth16 proofs may be larger.
            proof_backend = ""
            if isinstance(getattr(proof, "metadata", None), dict):
                proof_backend = str(proof.metadata.get("backend") or proof.metadata.get("proof_system") or "")

            max_size = 300
            if proof_backend.lower().startswith("groth16") or "groth16" in proof_backend.lower():
                max_size = 50_000

            if proof.size_bytes < 100 or proof.size_bytes > max_size:
                return False
            
            # Check security level
            proof_security = proof.metadata.get('security_level', 0)
            if proof_security < self.security_level:
                return False
            
            return True
            
        except (AttributeError, TypeError, KeyError) as e:
            # Proof object doesn't have expected attributes or structure
            logger.warning(f"Invalid proof structure during validation: {e}")
            return False

    @staticmethod
    def _is_hex_32_bytes(value: object) -> bool:
        if not isinstance(value, str) or len(value) != 64:
            return False
        try:
            int(value, 16)
            return True
        except Exception:
            return False

    def _validate_public_inputs(self, public_inputs: object) -> bool:
        """Validate standardized public inputs.

        Required:
        - theorem: str
        - theorem_hash: 32-byte hex string (64 hex chars)

        Optional (validated if present):
        - axioms_commitment: 32-byte hex string
        - circuit_version: non-negative int
        - ruleset_id: non-empty str
        """
        if not isinstance(public_inputs, dict):
            return False

        if "theorem" not in public_inputs or "theorem_hash" not in public_inputs:
            return False

        theorem = public_inputs.get("theorem")
        if not isinstance(theorem, str) or theorem == "":
            return False

        theorem_hash = public_inputs.get("theorem_hash")
        if not self._is_hex_32_bytes(theorem_hash):
            return False

        if "axioms_commitment" in public_inputs:
            if not self._is_hex_32_bytes(public_inputs.get("axioms_commitment")):
                return False

        if "circuit_version" in public_inputs:
            cv = public_inputs.get("circuit_version")
            if not isinstance(cv, int) or cv < 0:
                return False

        if "ruleset_id" in public_inputs:
            rid = public_inputs.get("ruleset_id")
            if not isinstance(rid, str) or rid == "":
                return False

        return True
    
    def verify_with_public_inputs(
        self,
        proof: ZKPProof,
        expected_theorem: str,
    ) -> bool:
        """
        Verify proof and check public inputs match expected values.
        
        Args:
            proof: The proof to verify
            expected_theorem: The theorem we expect to be proven
        
        Returns:
            bool: True if proof valid and inputs match
        
        Example:
            >>> verifier = ZKPVerifier()
            >>> valid = verifier.verify_with_public_inputs(
            ...     proof=proof,
            ...     expected_theorem="Q"
            ... )
        """
        # Verify the proof itself
        if not self.verify_proof(proof):
            return False
        
        # Check public inputs match expected
        actual_theorem = proof.public_inputs.get('theorem', '')
        if actual_theorem != expected_theorem:
            return False
        
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get verifier statistics."""
        total_proofs = self._stats['proofs_verified'] + self._stats['proofs_rejected']
        
        return {
            **self._stats,
            'avg_verification_time': (
                self._stats['total_verification_time'] / total_proofs
                if total_proofs > 0 else 0.0
            ),
            'acceptance_rate': (
                self._stats['proofs_verified'] / total_proofs
                if total_proofs > 0 else 0.0
            ),
        }
    
    def reset_stats(self):
        """Reset verification statistics."""
        self._stats = {
            'proofs_verified': 0,
            'proofs_rejected': 0,
            'total_verification_time': 0.0,
        }

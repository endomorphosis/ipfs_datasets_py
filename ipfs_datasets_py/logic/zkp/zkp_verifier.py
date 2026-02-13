"""
Zero-Knowledge Proof Verifier for Logic Theorems.

Verifies zero-knowledge proofs without seeing the private axioms.
"""

from typing import Dict, Any, Optional
import hashlib
import time

from . import ZKPProof, ZKPError


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
    
    def __init__(self, security_level: int = 128):
        """
        Initialize ZKP verifier.
        
        Args:
            security_level: Required security bits (default: 128)
        """
        self.security_level = security_level
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
            
            # Verify proof cryptographically
            is_valid = self._verify_proof_internal(proof)
            
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
            
            # Check proof size (should be 160-256 bytes for simulated Groth16)
            if proof.size_bytes < 100 or proof.size_bytes > 300:
                return False
            
            # Check security level
            proof_security = proof.metadata.get('security_level', 0)
            if proof_security < self.security_level:
                return False
            
            return True
            
        except Exception:  # Any structural issue
            return False
    
    def _verify_proof_internal(self, proof: ZKPProof) -> bool:
        """
        Internal proof verification (simulated).
        
        In production with py_ecc and Groth16, this would:
        1. Parse proof as curve points (A, B, C)
        2. Verify pairing equation:
            e(A, B) = e(α, β) · e(C, δ) · e(public_input, γ)
        3. Return true if equation holds
        
        Real verification takes ~5-10ms with BN254 curve.
        """
        # Simulate pairing check
        # Real verification would check cryptographic pairing equation
        
        # Extract components
        theorem = proof.public_inputs.get('theorem', '')
        theorem_hash = proof.public_inputs.get('theorem_hash', '')
        proof_data = proof.proof_data
        
        # Verify theorem hash matches
        expected_hash = hashlib.sha256(theorem.encode()).hexdigest()
        if theorem_hash != expected_hash:
            return False
        
        # Simulate pairing verification
        # In reality: verify e(A,B) = e(α,β)·e(C,δ)·e(pub,γ)
        # Here we just check proof data is well-formed
        if len(proof_data) < 100 or len(proof_data) > 300:
            return False
        
        # Simulate verification computation (would be pairing check)
        # Real verification is constant time regardless of circuit size
        verification_hash = hashlib.sha256(
            proof_data + theorem.encode()
        ).digest()
        
        # In simulation, we accept all well-formed proofs
        # Real Groth16 would cryptographically verify the proof
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

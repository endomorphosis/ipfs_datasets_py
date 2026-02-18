"""Zero-Knowledge Proof prover.

Default behavior is a **simulation** backend for demonstration purposes.
Production-grade proving requires a real backend (see
`logic/zkp/GROTH16_IMPLEMENTATION_PLAN.md`).
"""

from typing import List, Dict, Any, Optional
import hashlib
import json
import time

from . import ZKPProof, ZKPError
from .backends import get_backend


class ZKPProver:
    """
    Generate zero-knowledge proofs for logic theorems.
    
    This prover generates **simulated** proofs that a theorem can be derived
    from a set of private axioms, without revealing the axioms themselves.
    
    Features:
        - Private axiom hiding
        - Succinct proof generation (<500 bytes)
        - Fast proving (<1 second for simple formulas)
        - Integration with IPFS for proof storage
    
    Example:
        >>> prover = ZKPProver()
        >>> proof = prover.generate_proof(
        ...     theorem="All humans are mortal",
        ...     private_axioms=[
        ...         "Socrates is human",
        ...         "All humans are mortal"
        ...     ]
        ... )
        >>> print(f"Proof size: {proof.size_bytes} bytes")
        Proof size: 256 bytes
    
    Note:
        This is a simulated ZKP prover for demonstration. It is NOT
        cryptographically secure. In production, use a real ZKP backend
        (e.g., Groth16) via a cryptographic library.
    """
    
    def __init__(
        self,
        security_level: int = 128,
        enable_caching: bool = True,
        backend: str = "simulated",
    ):
        """
        Initialize ZKP prover.
        
        Args:
            security_level: Security bits (default: 128)
            enable_caching: Cache generated proofs
        """
        self.security_level = security_level
        self.enable_caching = enable_caching
        self.backend = backend
        self._backend = get_backend(backend)
        self._proof_cache: Dict[str, ZKPProof] = {}
        self._stats = {
            'proofs_generated': 0,
            'cache_hits': 0,
            'total_proving_time': 0.0,
        }
    
    def generate_proof(
        self,
        theorem: str,
        private_axioms: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ZKPProof:
        """
        Generate a zero-knowledge proof for a theorem.
        
        Args:
            theorem: The theorem to prove (public)
            private_axioms: Axioms used in proof (kept private)
            metadata: Additional proof metadata
        
        Returns:
            ZKPProof: The generated zero-knowledge proof
        
        Raises:
            ZKPError: If proof generation fails
        
        Example:
            >>> prover = ZKPProver()
            >>> proof = prover.generate_proof(
            ...     theorem="Q",
            ...     private_axioms=["P", "P -> Q"]
            ... )
            >>> assert proof.size_bytes < 500
        """
        start_time = time.time()
        
        try:
            # Check cache
            cache_key = self._compute_cache_key(theorem, private_axioms)
            if self.enable_caching and cache_key in self._proof_cache:
                self._stats['cache_hits'] += 1
                return self._proof_cache[cache_key]
            
            # Validate inputs
            if not theorem:
                raise ZKPError("Theorem cannot be empty")
            if not private_axioms:
                raise ZKPError("At least one axiom required")
            
            # Generate proof via backend
            proof = self._backend.generate_proof(
                theorem=theorem,
                private_axioms=private_axioms,
                metadata={
                    **(metadata or {}),
                    'security_level': self.security_level,
                },
            )
            
            # Update stats
            proving_time = time.time() - start_time
            self._stats['proofs_generated'] += 1
            self._stats['total_proving_time'] += proving_time
            
            # Cache proof
            if self.enable_caching:
                self._proof_cache[cache_key] = proof
            
            return proof
            
        except Exception as e:
            raise ZKPError(f"Proof generation failed: {e}")
    
    def _compute_cache_key(self, theorem: str, axioms: List[str]) -> str:
        """Compute cache key for proof."""
        key_data = json.dumps({
            'theorem': theorem,
            'axioms': sorted(axioms),
        }, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get prover statistics."""
        return {
            **self._stats,
            'avg_proving_time': (
                self._stats['total_proving_time'] / self._stats['proofs_generated']
                if self._stats['proofs_generated'] > 0 else 0.0
            ),
            'cache_hit_rate': (
                self._stats['cache_hits'] / (
                    self._stats['proofs_generated'] + self._stats['cache_hits']
                ) if (self._stats['proofs_generated'] + self._stats['cache_hits']) > 0 else 0.0
            ),
        }
    
    def clear_cache(self):
        """Clear proof cache."""
        self._proof_cache.clear()

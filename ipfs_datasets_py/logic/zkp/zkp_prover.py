"""Zero-Knowledge Proof prover.

Default behavior is a **simulation** backend for demonstration purposes.
Production-grade proving requires a real backend (see
`logic/zkp/PRODUCTION_UPGRADE_PATH.md`).

⚠️  WARNING: This module generates SIMULATED proofs only.
             NOT cryptographically secure. Educational/demo use only.
"""

from dataclasses import replace
from typing import List, Dict, Any, Optional
import hashlib
import json
import time
import warnings

from . import ZKPProof, ZKPError
from .backends import get_backend
from .canonicalization import canonicalize_axioms, canonicalize_theorem, theorem_hash_hex


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

        ⚠️  WARNING: This produces SIMULATED proofs only — NOT cryptographically
        secure. For production use, integrate a real Groth16/PLONK backend.
        See ``logic/zkp/PRODUCTION_UPGRADE_PATH.md`` for upgrade instructions.

        Args:
            security_level: Security bits (default: 128, simulation only)
            enable_caching: Cache generated proofs
            backend: Proof backend; only "simulated" is currently supported
        """
        warnings.warn(
            "ZKPProver generates SIMULATED proofs only. "
            "NOT cryptographically secure. "
            "Do not use in production systems requiring real zero-knowledge proofs. "
            "See logic/zkp/PRODUCTION_UPGRADE_PATH.md for the upgrade path.",
            UserWarning,
            stacklevel=2,
        )
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
            cache_key = self._compute_cache_key(theorem, private_axioms, metadata)
            if self.enable_caching and cache_key in self._proof_cache:
                self._stats['cache_hits'] += 1
                cached = self._proof_cache[cache_key]
                return self._adapt_cached_proof(cached, theorem)
            
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

    def _adapt_cached_proof(self, proof: ZKPProof, theorem: str) -> ZKPProof:
        """Return a cached proof adapted to the current call.

        Cache keys are canonicalized, so multiple equivalent theorem strings can
        map to one cached proof. If the proof carries the original theorem text
        in public inputs, ensure we return a copy with the current theorem.
        """
        try:
            if not isinstance(proof.public_inputs, dict):
                return proof

            if "theorem" not in proof.public_inputs:
                return proof

            if proof.public_inputs.get("theorem") == theorem:
                return proof

            updated_public_inputs = dict(proof.public_inputs)
            updated_public_inputs["theorem"] = theorem

            if "theorem_hash" in updated_public_inputs:
                updated_public_inputs["theorem_hash"] = theorem_hash_hex(theorem)

            return replace(proof, public_inputs=updated_public_inputs)
        except Exception:
            return proof
    
    def _compute_cache_key(
        self,
        theorem: str,
        axioms: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Compute cache key for proof.

        The cache key must include any caller-controlled inputs that can change
        the produced proof (e.g., Groth16 `seed`, circuit versioning).
        """
        canonical_theorem = canonicalize_theorem(theorem)
        canonical_axioms = canonicalize_axioms(axioms)

        meta_ctx: Dict[str, Any] = {
            # Prover-level security setting is always applied downstream.
            'security_level': self.security_level,
        }
        if metadata:
            for key in ("seed", "circuit_version", "ruleset_id"):
                if key in metadata:
                    meta_ctx[key] = metadata.get(key)

        key_data = json.dumps(
            {
                'theorem': canonical_theorem,
                'axioms': canonical_axioms,
                'meta': meta_ctx,
            },
            sort_keys=True,
        )
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

    def prove(self, statement: str, witness=None, metadata=None) -> 'ZKPProof':
        '''Alias for generate_proof() for backward compatibility.'''
        if isinstance(witness, dict):
            private_axioms = witness.get('axioms', [])
        elif isinstance(witness, str):
            private_axioms = [witness]
        elif isinstance(witness, list):
            private_axioms = witness
        else:
            private_axioms = []
        return self.generate_proof(
            theorem=statement,
            private_axioms=private_axioms,
            metadata=metadata,
        )


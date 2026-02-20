"""
ZKP-CEC Integration Layer

This module provides integration between DCEC (Deontic Cognitive Event Calculus)
theorem proving and zero-knowledge proofs (ZKP), enabling privacy-preserving reasoning.

Features:
- Hybrid proving mode (try ZKP, fall back to standard)
- Privacy-preserving proofs (hide axioms/knowledge base)
- Unified proof result representation
- ZKP-aware proof caching
- Backend selection (simulated, Groth16)

Security Note:
    The "simulated" backend is for educational purposes only. It is NOT
    cryptographically secure and should NOT be used for production systems
    requiring real zero-knowledge proofs. See ../zkp/SECURITY_CONSIDERATIONS.md
    for details.

Example:
    >>> from ipfs_datasets_py.logic.CEC.native import cec_zkp_integration
    >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import parse_dcec
    >>> 
    >>> # Create knowledge base (axioms)
    >>> axioms = [
    ...     parse_dcec("p"),
    ...     parse_dcec("p -> q"),
    ... ]
    >>> 
    >>> # Create hybrid prover (ZKP + standard)
    >>> prover = cec_zkp_integration.ZKPCECProver(
    ...     enable_zkp=True,
    ...     zkp_backend="simulated",
    ...     zkp_fallback="standard",
    ...     enable_caching=True
    ... )
    >>> 
    >>> # Prove with privacy (ZKP hides axioms)
    >>> goal = parse_dcec("q")
    >>> result = prover.prove_theorem(
    ...     goal,
    ...     axioms,
    ...     prefer_zkp=True,
    ...     private_axioms=True
    ... )
    >>> 
    >>> print(f"Proved: {result.is_proved}")
    >>> print(f"Method: {result.method}")  # "cec_zkp" or "cec_standard"
    >>> print(f"Private: {result.is_private}")  # True if ZKP used
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from enum import Enum

# Import CEC components
from .dcec_core import Formula
from .prover_core import (
    ProofAttempt,
    ProofResult as BaseProofResult,
)
from .cec_proof_cache import CachedTheoremProver, HAVE_CACHE

# Import ZKP components (with graceful fallback)
try:
    from ...zkp import ZKPProver, ZKPVerifier, ZKPProof
    HAVE_ZKP = True
except ImportError:
    ZKPProver = None  # type: ignore
    ZKPVerifier = None  # type: ignore
    ZKPProof = None  # type: ignore
    HAVE_ZKP = False

logger = logging.getLogger(__name__)


class ProvingMethod(Enum):
    """Method used to prove a theorem."""
    CEC_STANDARD = "cec_standard"  # Standard CEC theorem proving
    CEC_ZKP = "cec_zkp"  # Zero-knowledge proof
    CEC_HYBRID = "cec_hybrid"  # Hybrid (tried both)
    CEC_CACHED = "cec_cached"  # Retrieved from cache


@dataclass
class UnifiedCECProofResult:
    """
    Unified proof result supporting both standard and ZKP proofs.
    
    This class provides a common interface for proof results from both
    standard DCEC theorem proving and zero-knowledge proofs, enabling
    seamless integration in hybrid proving modes.
    
    Attributes:
        is_proved: Whether the formula was successfully proved
        formula: The formula that was proved
        axioms: Axioms used (may be hidden if private)
        method: Proving method used
        proof_time: Time taken to generate proof (seconds)
        
        # Standard DCEC proof fields
        base_result: Base ProofResult enum
        proof_steps: Number of proof steps (None for ZKP)
        inference_rules: Inference rules used (None for ZKP)
        
        # ZKP proof fields
        zkp_proof: ZKP proof object (None for standard)
        is_private: True if axioms are hidden via ZKP
        zkp_backend: ZKP backend used (if applicable)
        
        # Cache fields
        from_cache: True if result came from cache
        cache_hit_time: Time saved by cache hit
    """
    is_proved: bool
    formula: Formula
    axioms: List[Formula]
    method: ProvingMethod
    proof_time: float
    
    # Standard fields
    base_result: BaseProofResult = BaseProofResult.UNKNOWN
    proof_steps: Optional[int] = None
    inference_rules: Optional[List[str]] = None
    error_message: Optional[str] = None
    
    # ZKP fields
    zkp_proof: Optional[Any] = None  # ZKPProof type
    is_private: bool = False
    zkp_backend: Optional[str] = None
    
    # Cache fields
    from_cache: bool = False
    cache_hit_time: Optional[float] = None
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    
    @classmethod
    def from_standard_proof(
        cls,
        attempt: ProofAttempt,
        from_cache: bool = False,
        cache_hit_time: Optional[float] = None
    ) -> UnifiedCECProofResult:
        """Create unified result from standard ProofAttempt."""
        proof_steps = 0
        inference_rules = []
        
        if attempt.proof_tree:
            proof_tree = attempt.proof_tree

            # Prefer native flat ProofTree structure with .steps list
            if hasattr(proof_tree, "steps") and isinstance(getattr(proof_tree, "steps"), list):
                steps = proof_tree.steps
                proof_steps = len(steps)

                rules_set = set()
                for step in steps:
                    rule_name = getattr(step, "rule", None)
                    if rule_name:
                        rules_set.add(rule_name)
                inference_rules = list(rules_set)
            else:
                # Fallback: treat proof_tree as a recursive node tree
                def count_steps(node):
                    if not node:
                        return 0
                    count = 1
                    if hasattr(node, "children"):
                        for child in node.children:
                            count += count_steps(child)
                    return count

                proof_steps = count_steps(proof_tree)

                def extract_rules(node, rules_set):
                    if not node:
                        return
                    if hasattr(node, "rule") and node.rule:
                        rules_set.add(node.rule)
                    if hasattr(node, "children"):
                        for child in node.children:
                            extract_rules(child, rules_set)

                rules_set = set()
                extract_rules(proof_tree, rules_set)
                inference_rules = list(rules_set)
        
        method = ProvingMethod.CEC_CACHED if from_cache else ProvingMethod.CEC_STANDARD
        
        return cls(
            is_proved=(attempt.result == BaseProofResult.PROVED),
            formula=attempt.goal,
            axioms=attempt.axioms,
            method=method,
            proof_time=attempt.execution_time,
            base_result=attempt.result,
            proof_steps=proof_steps,
            inference_rules=inference_rules,
            error_message=attempt.error_message,
            from_cache=from_cache,
            cache_hit_time=cache_hit_time,
        )
    
    @classmethod
    def from_zkp_proof(
        cls,
        formula: Formula,
        axioms: List[Formula],
        zkp_proof: Any,  # ZKPProof
        is_proved: bool,
        proof_time: float,
        zkp_backend: str,
        is_private: bool = True
    ) -> UnifiedCECProofResult:
        """Create unified result from ZKP proof.
        
        When is_private=True, axioms are replaced with a placeholder to prevent
        direct access to private witness data.
        """
        # For private proofs, replace axioms with a placeholder
        visible_axioms = [] if is_private else axioms
        
        return cls(
            is_proved=is_proved,
            formula=formula,
            axioms=visible_axioms,
            method=ProvingMethod.CEC_ZKP,
            proof_time=proof_time,
            base_result=BaseProofResult.PROVED if is_proved else BaseProofResult.UNKNOWN,
            zkp_proof=zkp_proof,
            is_private=is_private,
            zkp_backend=zkp_backend,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'is_proved': self.is_proved,
            'formula': self.formula.to_string(),
            'axioms': [a.to_string() for a in self.axioms] if not self.is_private else ['<private>'],
            'method': self.method.value,
            'proof_time': self.proof_time,
            'base_result': self.base_result.value,
            'proof_steps': self.proof_steps,
            'is_private': self.is_private,
            'from_cache': self.from_cache,
            'timestamp': self.timestamp,
        }


class ZKPCECProver:
    """
    Hybrid CEC theorem prover with ZKP and caching support.
    
    This prover integrates three proving strategies:
    1. Cache lookup (fastest - O(1), microseconds)
    2. ZKP proving (medium - privacy-preserving)
    3. Standard proving (fallback - full details)
    
    The prover automatically selects the best strategy based on:
    - Cache availability and hit
    - ZKP backend availability
    - Privacy requirements
    - Fallback preferences
    
    Example:
        >>> prover = ZKPCECProver(
        ...     enable_zkp=True,
        ...     enable_caching=True,
        ...     zkp_backend="simulated"
        ... )
        >>> 
        >>> # Prove with all optimizations
        >>> result = prover.prove_theorem(goal, axioms)
        >>> 
        >>> # Force ZKP (privacy-preserving)
        >>> result = prover.prove_theorem(
        ...     goal, axioms,
        ...     prefer_zkp=True,
        ...     private_axioms=True
        ... )
    """
    
    def __init__(
        self,
        enable_zkp: bool = True,
        enable_caching: bool = True,
        zkp_backend: str = "simulated",
        zkp_fallback: str = "standard",
        cache_size: int = 1000,
        cache_ttl: int = 3600,
        use_global_cache: bool = True
    ):
        """
        Initialize hybrid ZKP+cached CEC prover.
        
        Args:
            enable_zkp: Enable ZKP proving
            enable_caching: Enable proof caching
            zkp_backend: ZKP backend ("simulated" or "groth16")
            zkp_fallback: Fallback if ZKP fails ("standard" or "error")
            cache_size: Cache size (if not using global)
            cache_ttl: Cache TTL in seconds
            use_global_cache: Use global cache singleton
        """
        # Initialize cached prover (base)
        self.cached_prover = CachedTheoremProver(
            cache_size=cache_size,
            cache_ttl=cache_ttl,
            use_global_cache=use_global_cache,
            enable_caching=enable_caching
        )
        
        # ZKP configuration
        self.enable_zkp = enable_zkp and HAVE_ZKP
        self.zkp_backend = zkp_backend
        self.zkp_fallback = zkp_fallback
        
        # Initialize ZKP components if enabled
        if self.enable_zkp:
            try:
                self.zkp_prover = ZKPProver(backend=zkp_backend)
                self.zkp_verifier = ZKPVerifier(backend=zkp_backend)
                logger.info(f"ZKP enabled with backend: {zkp_backend}")
            except Exception as e:
                logger.warning(f"Failed to initialize ZKP: {e}")
                self.enable_zkp = False
                self.zkp_prover = None
                self.zkp_verifier = None
        else:
            self.zkp_prover = None
            self.zkp_verifier = None
            if not HAVE_ZKP:
                logger.info("ZKP not available - zkp module not found")
            else:
                logger.info("ZKP disabled by configuration")
        
        # Statistics
        self._zkp_attempts = 0
        self._zkp_successes = 0
        self._standard_proofs = 0
        self._cache_hits = 0

    def initialize(self) -> None:
        """No-op initializer for API compatibility (all init done in __init__)."""
        # Ensure kb is set for backward compat
        if not hasattr(self, 'kb'):
            try:
                from .prover_core import ProofSearchEngine
                self.kb = ProofSearchEngine()
            except Exception:
                from types import SimpleNamespace
                self.kb = SimpleNamespace(axioms=[], rules=[])

    def prove_theorem(
        self,
        goal: Formula,
        axioms: Optional[List[Formula]] = None,
        timeout: Optional[float] = None,
        prefer_zkp: bool = False,
        private_axioms: bool = False,
        use_cache: bool = True,
        force_standard: bool = False,  # compat: same as not prefer_zkp
    ) -> UnifiedCECProofResult:
        """
        Prove a theorem using hybrid strategy.
        
        Strategy:
        1. If use_cache: Check cache first (O(1))
        2. If prefer_zkp and ZKP enabled: Try ZKP proof
        3. If ZKP fails or not preferred: Use standard proving
        
        Args:
            goal: Formula to prove
            axioms: Axioms to use
            timeout: Timeout in seconds
            prefer_zkp: Prefer ZKP over standard
            private_axioms: Hide axioms in proof (requires ZKP)
            use_cache: Use proof cache
            
        Returns:
            UnifiedCECProofResult with proof details
        """
        axioms = axioms or []
        start_time = time.time()

        # force_standard=True means skip ZKP and cache
        if force_standard:
            prefer_zkp = False
            private_axioms = False
            use_cache = False
        
        # Strategy 1: Try cache first (if enabled)
        if use_cache and self.cached_prover.enable_caching:
            # Capture cache statistics before the lookup, if available
            hits_before = getattr(self.cached_prover, "_cache_hits", None)
            cache_start = time.time()
            attempt = self.cached_prover.prove_theorem(goal, axioms, timeout, use_cache=True)
            cache_time = time.time() - cache_start

            # Determine if this was a cache hit using prover statistics or attempt metadata
            cache_hit = False
            if hits_before is not None:
                hits_after = getattr(self.cached_prover, "_cache_hits", hits_before)
                cache_hit = hits_after > hits_before
            if not cache_hit:
                cache_hit = bool(getattr(attempt, "from_cache", False))

            if cache_hit:
                self._cache_hits += 1
                # Report the actual retrieval time as the cache hit timing metric
                return UnifiedCECProofResult.from_standard_proof(
                    attempt,
                    from_cache=True,
                    cache_hit_time=cache_time,
                )
        
        # Strategy 2: Try ZKP (if preferred and enabled)
        if prefer_zkp and self.enable_zkp and self.zkp_prover:
            try:
                self._zkp_attempts += 1
                zkp_result = self._prove_with_zkp(goal, axioms, timeout, private_axioms)
                if zkp_result.is_proved:
                    self._zkp_successes += 1
                    return zkp_result
                else:
                    logger.debug("ZKP proof failed, falling back to standard")
            except Exception as e:
                logger.warning(f"ZKP proof error: {e}")
                if self.zkp_fallback not in ("standard", "simulated"):
                    raise
        
        # Strategy 3: Standard proving (fallback or primary)
        self._standard_proofs += 1
        attempt = self.cached_prover.prove_theorem(goal, axioms, timeout, use_cache=False)
        return UnifiedCECProofResult.from_standard_proof(attempt, from_cache=False)
    
    def _prove_with_zkp(
        self,
        goal: Formula,
        axioms: List[Formula],
        timeout: Optional[float],
        private_axioms: bool
    ) -> UnifiedCECProofResult:
        """
        Prove using ZKP backend.
        
        This creates a privacy-preserving proof that hides the axioms
        while still proving that the goal follows from them.
        
        Note: This is a simplified implementation. Real ZKP for
        first-order logic is complex and may require circuit encoding.
        """
        import hashlib
        start_time = time.time()
        
        # Convert formula and axioms to ZKP-compatible format
        # (In real implementation, this would involve circuit encoding)
        # Use deterministic cryptographic hash (SHA-256) instead of Python's hash()
        axioms_sorted = sorted(a.to_string() for a in axioms)
        axioms_str = "\n".join(axioms_sorted)
        axioms_hash = hashlib.sha256(axioms_str.encode()).hexdigest()
        
        statement = {
            'goal': goal.to_string(),
            'axioms_hash': axioms_hash
        }
        
        # Create witness (private inputs)
        witness = {
            'axioms': [a.to_string() for a in axioms]
        }
        
        try:
            # Generate ZKP proof
            # Convert statement dict to string for ZKPProver.prove() which expects str
            statement_str = (statement if isinstance(statement, str)
                             else f"{statement.get('goal', '')}#{statement.get('axioms_hash', '')}")
            zkp_proof = self.zkp_prover.prove(statement_str, witness)
            
            # Verify proof
            is_valid = self.zkp_verifier.verify(statement, zkp_proof)
            
            proof_time = time.time() - start_time
            
            return UnifiedCECProofResult.from_zkp_proof(
                formula=goal,
                axioms=axioms,
                zkp_proof=zkp_proof,
                is_proved=is_valid,
                proof_time=proof_time,
                zkp_backend=self.zkp_backend,
                is_private=private_axioms
            )
        
        except Exception as e:
            logger.error(f"ZKP proving failed: {e}")
            raise
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        stats = self.cached_prover.get_statistics()
        
        # Add ZKP statistics
        stats.update({
            'zkp_enabled': self.enable_zkp,
            'zkp_attempts': self._zkp_attempts,
            'zkp_successes': self._zkp_successes,
            'zkp_success_rate': (
                self._zkp_successes / self._zkp_attempts
                if self._zkp_attempts > 0 else 0.0
            ),
            'standard_proofs': self._standard_proofs,
            'cache_hits_zkp': self._cache_hits,
        })
        
        return stats
    
    def clear_cache(self) -> None:
        """Clear proof cache."""
        self.cached_prover.clear_cache()
    
    def clear_statistics(self) -> None:
        """Clear all statistics."""
        self._zkp_attempts = 0
        self._zkp_successes = 0
        self._standard_proofs = 0
        self._cache_hits = 0
        self.cached_prover._cache_hits = 0
        self.cached_prover._cache_misses = 0


# Convenience function
def create_hybrid_prover(
    enable_zkp: bool = True,
    enable_caching: bool = True,
    **kwargs
) -> ZKPCECProver:
    """
    Create a hybrid CEC prover with ZKP and caching.
    
    This is a convenience function for quick setup.
    
    Args:
        enable_zkp: Enable ZKP support
        enable_caching: Enable proof caching
        **kwargs: Additional arguments for ZKPCECProver
        
    Returns:
        Configured ZKPCECProver instance
    """
    return ZKPCECProver(
        enable_zkp=enable_zkp,
        enable_caching=enable_caching,
        **kwargs
    )


__all__ = [
    'ProvingMethod',
    'UnifiedCECProofResult',
    'ZKPCECProver',
    'create_hybrid_prover',
    'HAVE_ZKP',
    'HAVE_CACHE',
]

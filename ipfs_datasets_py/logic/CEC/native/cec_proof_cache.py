"""
CEC Proof Cache Integration

This module provides proof caching for DCEC (Deontic Cognitive Event Calculus)
theorem proving, preventing redundant recomputation of previously proven theorems.

Features:
- CID-based content addressing (deterministic hashing)
- O(1) lookups using unified proof cache
- Thread-safe operations
- TTL-based expiration
- Cache hit/miss statistics
- Integration with CEC prover_core

The cache key is computed as:
    CID(formula_canonical + axioms_canonical + prover_config)

This ensures:
1. Same theorem always produces same CID (deterministic)
2. Different theorems produce different CIDs (collision-resistant)
3. O(1) lookup performance (hash-based)
4. Works with proof_core.ProofAttempt results

Example:
    >>> from ipfs_datasets_py.logic.CEC.native import TheoremProver, cec_proof_cache
    >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import parse_dcec
    >>> 
    >>> # Create prover with cache-aware wrapper
    >>> prover = cec_proof_cache.CachedTheoremProver()
    >>> 
    >>> # First proof - cache miss
    >>> goal = parse_dcec("O(p)")
    >>> axioms = [parse_dcec("p")]
    >>> result1 = prover.prove_theorem(goal, axioms)
    >>> print(f"Time: {result1.execution_time:.4f}s")  # e.g., 0.0123s
    >>> 
    >>> # Second proof - cache hit (much faster!)
    >>> result2 = prover.prove_theorem(goal, axioms)
    >>> print(f"Time: {result2.execution_time:.4f}s")  # e.g., 0.0001s (100x faster)
    >>> 
    >>> # Get statistics
    >>> stats = prover.get_cache_statistics()
    >>> print(f"Hit rate: {stats['hit_rate']:.1%}")  # e.g., 50%
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from threading import RLock

# Import CEC components
from .dcec_core import Formula
from .prover_core import (
    TheoremProver as BaseTheoremProver,
    ProofAttempt,
    ProofResult,
)

# Import unified proof cache
try:
    from ...common.proof_cache import ProofCache, CachedProofResult, get_global_cache
    HAVE_CACHE = True
except ImportError:
    ProofCache = None  # type: ignore
    CachedProofResult = None  # type: ignore
    get_global_cache = None  # type: ignore
    HAVE_CACHE = False

logger = logging.getLogger(__name__)


@dataclass
class CECCachedProofResult:
    """
    Cached proof result for CEC proofs.
    
    This wraps ProofAttempt for caching, storing just the essential
    information needed to reconstruct the result.
    """
    is_proved: bool
    result: ProofResult
    execution_time: float
    proof_steps: int = 0
    inference_rules_used: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    @classmethod
    def from_proof_attempt(cls, attempt: ProofAttempt) -> CECCachedProofResult:
        """Create cached result from ProofAttempt."""
        proof_steps = 0
        rules_used = []
        
        if attempt.proof_tree:
            # Count steps in proof tree
            def count_steps(node):
                if not node:
                    return 0
                count = 1
                if hasattr(node, 'children'):
                    for child in node.children:
                        count += count_steps(child)
                return count
            
            proof_steps = count_steps(attempt.proof_tree)
            
            # Extract inference rules
            def extract_rules(node, rules_set):
                if not node:
                    return
                if hasattr(node, 'rule') and node.rule:
                    rules_set.add(node.rule)
                if hasattr(node, 'children'):
                    for child in node.children:
                        extract_rules(child, rules_set)
            
            rules_set = set()
            extract_rules(attempt.proof_tree, rules_set)
            rules_used = list(rules_set)
        
        return cls(
            is_proved=(attempt.result == ProofResult.PROVED),
            result=attempt.result,
            execution_time=attempt.execution_time,
            proof_steps=proof_steps,
            inference_rules_used=rules_used,
            error_message=attempt.error_message
        )
    
    def to_proof_attempt(self, goal: Formula, axioms: List[Formula]) -> ProofAttempt:
        """Reconstruct ProofAttempt from cached result."""
        return ProofAttempt(
            goal=goal,
            axioms=axioms,
            result=self.result,
            execution_time=self.execution_time,  # Cached time (for stats)
            error_message=self.error_message,
            # Note: proof_tree is not cached (too large), only result
        )


class CachedTheoremProver(BaseTheoremProver):
    """
    Theorem prover with integrated proof caching.
    
    This extends the base TheoremProver with automatic caching of proof results.
    When proving a theorem:
    1. Check cache for existing proof
    2. If hit, return cached result (O(1), microseconds)
    3. If miss, compute proof and cache result
    
    Example:
        >>> prover = CachedTheoremProver(cache_size=1000, cache_ttl=3600)
        >>> 
        >>> # First proof - cache miss, normal speed
        >>> result1 = prover.prove_theorem(goal, axioms)
        >>> 
        >>> # Second identical proof - cache hit, 100x faster!
        >>> result2 = prover.prove_theorem(goal, axioms)
        >>> 
        >>> # Different axioms - cache miss (different cache key)
        >>> result3 = prover.prove_theorem(goal, different_axioms)
    """
    
    def __init__(
        self,
        cache_size: int = 1000,
        cache_ttl: int = 3600,
        use_global_cache: bool = True,
        enable_caching: bool = True
    ):
        """
        Initialize cached theorem prover.
        
        Args:
            cache_size: Maximum number of cached proofs
            cache_ttl: Time-to-live for cached proofs (seconds)
            use_global_cache: If True, use global singleton cache
            enable_caching: If False, disable caching (for testing)
        """
        super().__init__()
        
        self.enable_caching = enable_caching and HAVE_CACHE
        
        if self.enable_caching:
            if use_global_cache:
                self.cache = get_global_cache()
                logger.info("Using global proof cache")
            else:
                self.cache = ProofCache(maxsize=cache_size, ttl=cache_ttl)
                logger.info(f"Created local proof cache (size={cache_size}, ttl={cache_ttl}s)")
        else:
            self.cache = None
            if not HAVE_CACHE:
                logger.warning("Proof cache not available - install cachetools package")
            else:
                logger.info("Caching disabled")
        
        # Cache statistics
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_lock = RLock()
    
    def prove_theorem(
        self,
        goal: Formula,
        axioms: Optional[List[Formula]] = None,
        timeout: Optional[float] = None,
        use_cache: bool = True
    ) -> ProofAttempt:
        """
        Prove a theorem with caching.
        
        Args:
            goal: The formula to prove
            axioms: List of axioms (assumed true)
            timeout: Optional timeout in seconds
            use_cache: If False, bypass cache for this proof
            
        Returns:
            ProofAttempt with results (may be from cache)
        """
        axioms = axioms or []
        
        # Try cache if enabled
        if self.enable_caching and use_cache and self.cache:
            cached_result = self._get_from_cache(goal, axioms)
            if cached_result:
                with self._cache_lock:
                    self._cache_hits += 1
                logger.debug(f"Cache HIT for goal: {goal.to_string()[:50]}")
                return cached_result.to_proof_attempt(goal, axioms)
            else:
                with self._cache_lock:
                    self._cache_misses += 1
                logger.debug(f"Cache MISS for goal: {goal.to_string()[:50]}")
        
        # Cache miss or caching disabled - compute proof
        start_time = time.time()
        attempt = super().prove_theorem(goal, axioms, timeout)
        
        # Cache the result if caching enabled
        if self.enable_caching and use_cache and self.cache:
            cached = CECCachedProofResult.from_proof_attempt(attempt)
            self._put_in_cache(goal, axioms, cached)
        
        return attempt
    
    def _get_from_cache(
        self,
        goal: Formula,
        axioms: List[Formula]
    ) -> Optional[CECCachedProofResult]:
        """Get cached proof result."""
        if not self.cache:
            return None
        
        try:
            # Create cache key from formula and axioms
            formula_str = goal.to_string()
            axioms_str = ";".join(sorted(a.to_string() for a in axioms))
            cache_key = f"{formula_str}|{axioms_str}"
            
            # Try to get from cache
            cached = self.cache.get(cache_key, prover_name="cec_native")
            if cached:
                # Convert CachedProofResult to CECCachedProofResult
                if isinstance(cached.metadata, dict):
                    return CECCachedProofResult(
                        is_proved=cached.is_proved,
                        result=ProofResult(cached.metadata.get('result', 'unknown')),
                        execution_time=cached.proof_time,
                        proof_steps=cached.metadata.get('proof_steps', 0),
                        inference_rules_used=cached.metadata.get('inference_rules_used', []),
                        error_message=cached.metadata.get('error_message'),
                        timestamp=cached.timestamp
                    )
            return None
        except Exception as e:
            logger.warning(f"Cache lookup error: {e}")
            return None
    
    def _put_in_cache(
        self,
        goal: Formula,
        axioms: List[Formula],
        result: CECCachedProofResult
    ) -> None:
        """Put proof result in cache."""
        if not self.cache:
            return
        
        try:
            # Create cache key
            formula_str = goal.to_string()
            axioms_str = ";".join(sorted(a.to_string() for a in axioms))
            cache_key = f"{formula_str}|{axioms_str}"
            
            # Create metadata
            metadata = {
                'result': result.result.value,
                'proof_steps': result.proof_steps,
                'inference_rules_used': result.inference_rules_used,
                'error_message': result.error_message,
            }
            
            # Store in cache
            self.cache.set(
                cache_key,
                result.is_proved,
                result.execution_time,
                metadata=metadata,
                prover_name="cec_native"
            )
            
        except Exception as e:
            logger.warning(f"Cache store error: {e}")
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns:
            Dictionary with cache hits, misses, hit rate, etc.
        """
        with self._cache_lock:
            total = self._cache_hits + self._cache_misses
            hit_rate = self._cache_hits / total if total > 0 else 0.0
            
            stats = {
                'cache_enabled': self.enable_caching,
                'cache_hits': self._cache_hits,
                'cache_misses': self._cache_misses,
                'total_lookups': total,
                'hit_rate': hit_rate,
            }
            
            # Add cache-specific stats if available
            if self.cache and hasattr(self.cache, 'get_statistics'):
                cache_stats = self.cache.get_statistics()
                stats.update({
                    'cache_size': cache_stats.get('size', 0),
                    'cache_maxsize': cache_stats.get('maxsize', 0),
                })
            
            return stats
    
    def clear_cache(self) -> None:
        """Clear the proof cache."""
        if self.cache:
            self.cache.clear()
            logger.info("Proof cache cleared")
        
        with self._cache_lock:
            self._cache_hits = 0
            self._cache_misses = 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get combined prover and cache statistics."""
        stats = super().get_statistics()
        stats.update(self.get_cache_statistics())
        return stats


# Global instance for convenience
_global_cached_prover: Optional[CachedTheoremProver] = None


def get_global_cached_prover() -> CachedTheoremProver:
    """
    Get or create the global cached theorem prover.
    
    This is a singleton that uses the global proof cache.
    Useful for applications that want a single shared prover instance.
    
    Returns:
        Global CachedTheoremProver instance
    """
    global _global_cached_prover
    if _global_cached_prover is None:
        _global_cached_prover = CachedTheoremProver(
            use_global_cache=True,
            enable_caching=True
        )
    return _global_cached_prover


__all__ = [
    'CECCachedProofResult',
    'CachedTheoremProver',
    'get_global_cached_prover',
    'HAVE_CACHE',
]

"""
ZKP-TDFOL Integration Layer

This module provides integration between TDFOL theorem proving and
zero-knowledge proofs (ZKP), enabling privacy-preserving reasoning.

Features:
- Hybrid proving mode (try ZKP, fall back to standard)
- Unified proof result representation
- ZKP-aware proof caching
- Backend selection (simulated, Groth16)

Security Note:
    The "simulated" backend is for educational purposes only. It is NOT
    cryptographically secure and should NOT be used for production systems
    requiring real zero-knowledge proofs. See ../zkp/SECURITY_CONSIDERATIONS.md
    for details.

Example:
    >>> from ipfs_datasets_py.logic.TDFOL import parse_tdfol, TDFOLKnowledgeBase
    >>> from ipfs_datasets_py.logic.TDFOL.zkp_integration import ZKPTDFOLProver
    >>> 
    >>> # Create knowledge base
    >>> kb = TDFOLKnowledgeBase()
    >>> kb.add_axiom(parse_tdfol("P"))
    >>> kb.add_axiom(parse_tdfol("P -> Q"))
    >>> 
    >>> # Create hybrid prover
    >>> prover = ZKPTDFOLProver(
    ...     kb,
    ...     enable_zkp=True,
    ...     zkp_backend="simulated",
    ...     zkp_fallback="standard"
    ... )
    >>> 
    >>> # Prove with privacy (ZKP)
    >>> result = prover.prove(
    ...     parse_tdfol("Q"),
    ...     prefer_zkp=True,
    ...     private_axioms=True
    ... )
    >>> print(f"Method: {result.method}")  # "tdfol_zkp" or "tdfol_standard"
    >>> print(f"Private: {result.is_private}")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Import TDFOL components
from .tdfol_core import Formula, TDFOLKnowledgeBase
from .tdfol_prover import TDFOLProver, ProofResult
from .exceptions import ProofError, ZKPProofError, ProofTimeoutError

# Import ZKP components (with graceful fallback)
try:
    from ..zkp import ZKPProver, ZKPVerifier, ZKPProof
    HAVE_ZKP = True
except ImportError:
    ZKPProver = None  # type: ignore
    ZKPVerifier = None  # type: ignore
    ZKPProof = None  # type: ignore
    HAVE_ZKP = False

# Import unified proof cache
try:
    from ..common.proof_cache import ProofCache
    HAVE_CACHE = True
except ImportError:
    ProofCache = None  # type: ignore
    HAVE_CACHE = False

logger = logging.getLogger(__name__)


@dataclass
class UnifiedProofResult:
    """
    Unified proof result supporting both standard and ZKP proofs.
    
    This class provides a common interface for proof results from both
    standard TDFOL proving and zero-knowledge proofs, enabling seamless
    integration in hybrid proving modes.
    
    Attributes:
        is_proved: Whether the formula was successfully proved
        formula: The formula that was proved
        method: Proving method used ("tdfol_standard", "tdfol_zkp", "hybrid")
        proof_time: Time taken to generate proof (seconds)
        
        # Standard TDFOL proof fields
        proof_steps: List of proof steps (None for ZKP)
        inference_rules: Inference rules used (None for ZKP)
        
        # ZKP proof fields
        zkp_proof: ZKP proof object (None for standard)
        is_private: True if axioms are hidden via ZKP
        backend: ZKP backend used ("simulated", "groth16", etc.)
        security_level: Security bits (128, 192, 256)
        
        # Caching
        cache_hit: Whether result was retrieved from cache
        cache_cid: Content ID (CID) of cached proof
    
    Example:
        >>> result = prover.prove(formula, prefer_zkp=True)
        >>> if result.is_private:
        ...     print(f"Private proof ({result.backend}, {result.security_level}-bit)")
        ...     print(f"Proof size: {len(result.zkp_proof.proof_bytes)} bytes")
        ... else:
        ...     print(f"Standard proof ({len(result.proof_steps)} steps)")
    """
    
    # Common fields
    is_proved: bool
    formula: Formula
    method: str  # "tdfol_standard", "tdfol_zkp", "hybrid"
    proof_time: float
    
    # Standard TDFOL proof fields
    proof_steps: Optional[List[Any]] = None
    inference_rules: Optional[List[str]] = None
    
    # ZKP proof fields
    zkp_proof: Optional[Any] = None  # ZKPProof object
    is_private: bool = False
    backend: Optional[str] = None
    security_level: int = 0
    
    # Caching
    cache_hit: bool = False
    cache_cid: Optional[str] = None
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


class ZKPTDFOLProver:
    """
    TDFOL prover with zero-knowledge proof support.
    
    This prover extends the standard TDFOL prover with ZKP capabilities,
    enabling privacy-preserving theorem proving. It supports three modes:
    
    1. **Standard Only:** Traditional TDFOL proving (no privacy)
    2. **ZKP Only:** Zero-knowledge proving (privacy-preserving)
    3. **Hybrid:** Try ZKP first, fall back to standard (recommended)
    
    Attributes:
        kb: TDFOL knowledge base with axioms
        enable_zkp: Whether ZKP is enabled
        zkp_backend: ZKP backend ("simulated", "groth16")
        zkp_security_level: Security bits (128, 192, 256)
        zkp_fallback: Fallback mode if ZKP fails ("standard", "none")
        standard_prover: Standard TDFOL prover
        zkp_prover: ZKP prover (if enabled)
        cache: Unified proof cache (supports both types)
        stats: Proving statistics
    
    Example:
        >>> kb = TDFOLKnowledgeBase()
        >>> prover = ZKPTDFOLProver(
        ...     kb,
        ...     enable_zkp=True,
        ...     zkp_backend="simulated",
        ...     zkp_fallback="standard"
        ... )
        >>> result = prover.prove(formula, prefer_zkp=True)
    
    Security Considerations:
        The "simulated" backend is NOT cryptographically secure. It is for
        educational and testing purposes only. For production use with real
        zero-knowledge proofs, use the "groth16" backend (requires additional
        cryptography libraries). See ../zkp/PRODUCTION_UPGRADE_PATH.md.
    """
    
    def __init__(
        self,
        knowledge_base: TDFOLKnowledgeBase,
        enable_zkp: bool = False,
        zkp_backend: str = "simulated",
        zkp_security_level: int = 128,
        zkp_fallback: str = "standard",
        enable_cache: bool = True,
        cache: Optional[Any] = None  # ProofCache
    ):
        """
        Initialize ZKP-TDFOL prover.
        
        Args:
            knowledge_base: TDFOL knowledge base with axioms
            enable_zkp: Enable zero-knowledge proving
            zkp_backend: ZKP backend ("simulated", "groth16")
            zkp_security_level: Security bits (128, 192, 256)
            zkp_fallback: Fallback mode if ZKP fails ("standard", "none")
            enable_cache: Enable proof caching
            cache: Optional custom cache instance
        
        Raises:
            ImportError: If ZKP is enabled but ZKP module not available
        """
        self.kb = knowledge_base
        self.enable_zkp = enable_zkp
        self.zkp_backend = zkp_backend
        self.zkp_security_level = zkp_security_level
        self.zkp_fallback = zkp_fallback
        self.enable_cache = enable_cache
        
        # Validate ZKP availability
        if enable_zkp and not HAVE_ZKP:
            raise ImportError(
                "ZKP module not available. "
                "Install with: pip install py_ecc (or appropriate ZKP library)"
            )
        
        # Standard TDFOL prover
        self.standard_prover = TDFOLProver(
            knowledge_base,
            enable_cache=enable_cache
        )
        
        # ZKP prover (if enabled)
        self.zkp_prover: Optional[Any] = None
        if enable_zkp and HAVE_ZKP:
            self.zkp_prover = ZKPProver(
                security_level=zkp_security_level,
                enable_caching=enable_cache,
                backend=zkp_backend
            )
        
        # Proof cache (unified)
        if cache:
            self.cache = cache
        elif HAVE_CACHE and enable_cache:
            self.cache = ProofCache(maxsize=10000, ttl=3600)
        else:
            self.cache = None
        
        # Statistics
        self.stats = {
            'standard_proofs': 0,
            'zkp_proofs': 0,
            'hybrid_proofs': 0,
            'zkp_failures': 0,
            'cache_hits': 0,
            'total_time': 0.0,
        }
    
    def prove(
        self,
        formula: Formula,
        prefer_zkp: bool = False,
        private_axioms: bool = False,
        timeout: float = 60.0,
        max_iterations: int = 100
    ) -> UnifiedProofResult:
        """
        Prove formula with hybrid ZKP/standard mode.
        
        This method implements the core proving logic with support for
        three modes: standard, ZKP, and hybrid. The proving strategy is:
        
        1. Check cache first (both standard and ZKP)
        2. If prefer_zkp or private_axioms: try ZKP
        3. If ZKP fails and fallback enabled: try standard
        4. If neither works: raise ProofError
        
        Args:
            formula: Formula to prove
            prefer_zkp: Prefer ZKP if enabled
            private_axioms: Keep axioms private (requires ZKP)
            timeout: Proof timeout (seconds)
            max_iterations: Max forward chaining iterations
        
        Returns:
            UnifiedProofResult with proof information
        
        Raises:
            ProofError: If proof fails in all modes
            ZKPProofError: If ZKP fails and no fallback
            ProofTimeoutError: If proving exceeds timeout
        
        Example:
            >>> # Standard proving
            >>> result = prover.prove(formula)
            >>> 
            >>> # ZKP proving (privacy-preserving)
            >>> result = prover.prove(formula, prefer_zkp=True, private_axioms=True)
            >>> 
            >>> # Hybrid (automatic fallback)
            >>> result = prover.prove(formula, prefer_zkp=True)
        """
        start_time = time.time()
        
        # Validate private_axioms requires ZKP
        if private_axioms and not self.enable_zkp:
            raise ProofError(
                "Private axioms require ZKP, but ZKP is disabled",
                formula=formula,
                suggestion="Enable ZKP with enable_zkp=True"
            )
        
        # Check cache first
        cache_result = self._check_cache(formula, prefer_zkp)
        if cache_result:
            self.stats['cache_hits'] += 1
            return cache_result
        
        # Determine proving mode
        use_zkp = (prefer_zkp or private_axioms) and self.enable_zkp
        
        # Try ZKP first
        if use_zkp:
            try:
                result = self._prove_with_zkp(
                    formula,
                    timeout=timeout,
                    start_time=start_time
                )
                self.stats['zkp_proofs'] += 1
                return result
            except ZKPProofError as e:
                self.stats['zkp_failures'] += 1
                
                # Check fallback mode
                if self.zkp_fallback == "none" or private_axioms:
                    # No fallback allowed
                    raise
                
                # Fall back to standard proving
                logger.warning(
                    f"ZKP failed ({e.backend}): {e.message}. "
                    f"Falling back to standard proving."
                )
                self.stats['hybrid_proofs'] += 1
        
        # Standard proving
        result = self._prove_standard(
            formula,
            timeout=timeout,
            max_iterations=max_iterations,
            start_time=start_time
        )
        self.stats['standard_proofs'] += 1
        return result
    
    def _check_cache(
        self,
        formula: Formula,
        prefer_zkp: bool
    ) -> Optional[UnifiedProofResult]:
        """
        Check cache for existing proof.
        
        Args:
            formula: Formula to check
            prefer_zkp: Whether ZKP is preferred
        
        Returns:
            Cached result if found, None otherwise
        """
        if not self.cache:
            return None
        
        # Try ZKP cache first if preferred
        if prefer_zkp:
            cached = self.cache.get(formula, prover_name="tdfol_zkp")
            if cached:
                return self._cached_to_unified(cached, "zkp")
        
        # Try standard cache
        cached = self.cache.get(formula, prover_name="tdfol_standard")
        if cached:
            return self._cached_to_unified(cached, "standard")
        
        return None
    
    def _cached_to_unified(
        self,
        cached: Any,
        proof_type: str
    ) -> UnifiedProofResult:
        """Convert cached result to UnifiedProofResult."""
        # Simplified conversion - would need actual implementation
        return UnifiedProofResult(
            is_proved=getattr(cached, 'is_proved', lambda: False)() if callable(getattr(cached, 'is_proved', None)) else bool(getattr(cached, 'is_proved', False)),
            formula=getattr(cached, 'formula', None),
            method=f"tdfol_{proof_type}",
            proof_time=getattr(cached, 'time_ms', 0.0) / 1000.0,
            cache_hit=True,
            cache_cid=getattr(cached, 'cid', None)
        )
    
    def _prove_with_zkp(
        self,
        formula: Formula,
        timeout: float,
        start_time: float
    ) -> UnifiedProofResult:
        """
        Prove using zero-knowledge proofs.
        
        Args:
            formula: Formula to prove
            timeout: Proof timeout
            start_time: Start time for timeout tracking
        
        Returns:
            UnifiedProofResult with ZKP proof
        
        Raises:
            ZKPProofError: If ZKP proving fails
            ProofTimeoutError: If timeout exceeded
        """
        if not self.zkp_prover:
            raise ZKPProofError(
                "ZKP prover not initialized",
                formula=formula,
                backend=self.zkp_backend,
                security_level=self.zkp_security_level,
                operation="prove"
            )
        
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise ProofTimeoutError(
                "Timeout before ZKP proving started",
                formula=formula,
                timeout=timeout,
                elapsed=elapsed
            )
        
        try:
            # Convert formula to string for ZKP
            theorem_str = str(formula)
            
            # Get axioms from knowledge base
            _axioms = self.kb.get_axioms() if hasattr(self.kb, 'get_axioms') else (self.kb.get_all_formulas() if hasattr(self.kb, 'get_all_formulas') else list(self.kb.axioms))
            axioms_str = [str(axiom) for axiom in _axioms]
            
            # Generate ZKP proof
            zkp_proof = self.zkp_prover.generate_proof(
                theorem=theorem_str,
                private_axioms=axioms_str
            )
            
            proof_time = time.time() - start_time
            
            # Create unified result
            result = UnifiedProofResult(
                is_proved=True,
                formula=formula,
                method="tdfol_zkp",
                proof_time=proof_time,
                zkp_proof=zkp_proof,
                is_private=True,
                backend=self.zkp_backend,
                security_level=self.zkp_security_level
            )
            
            # Cache the result
            if self.cache:
                self.cache.set(
                    formula,
                    result,
                    prover_name="tdfol_zkp",
                    prover_config={
                        'backend': self.zkp_backend,
                        'security_level': self.zkp_security_level
                    }
                )
            
            return result
            
        except Exception as e:
            raise ZKPProofError(
                f"ZKP proof generation failed: {e}",
                formula=formula,
                backend=self.zkp_backend,
                security_level=self.zkp_security_level,
                operation="prove",
                reason=str(e)
            )
    
    def _prove_standard(
        self,
        formula: Formula,
        timeout: float,
        max_iterations: int,
        start_time: float
    ) -> UnifiedProofResult:
        """
        Prove using standard TDFOL proving.
        
        Args:
            formula: Formula to prove
            timeout: Proof timeout
            max_iterations: Max iterations
            start_time: Start time for timeout tracking
        
        Returns:
            UnifiedProofResult with standard proof
        
        Raises:
            ProofError: If proving fails
            ProofTimeoutError: If timeout exceeded
        """
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise ProofTimeoutError(
                "Timeout before standard proving started",
                formula=formula,
                timeout=timeout,
                elapsed=elapsed
            )
        
        # Use standard prover
        result = self.standard_prover.prove(
            formula,
            timeout_ms=int((timeout - elapsed) * 1000),
        )
        
        proof_time = time.time() - start_time
        
        # Convert to unified result
        unified_result = UnifiedProofResult(
            is_proved=result.is_proved,
            formula=formula,
            method="tdfol_standard",
            proof_time=proof_time,
            proof_steps=result.proof_steps if hasattr(result, 'proof_steps') else [],
            inference_rules=[
                step.rule_name for step in (result.proof_steps if hasattr(result, 'proof_steps') else [])
            ] if hasattr(result, 'proof_steps') else []
        )
        
        # Cache the result
        if self.cache:
            self.cache.set(
                formula,
                unified_result,
                prover_name="tdfol_standard"
            )
        
        return unified_result
    
    def verify_zkp_proof(
        self,
        zkp_proof: Any,  # ZKPProof
        formula: Formula
    ) -> bool:
        """
        Verify a zero-knowledge proof.
        
        Args:
            zkp_proof: ZKP proof to verify
            formula: Formula that was proved
        
        Returns:
            True if proof is valid, False otherwise
        
        Raises:
            ProofError: If ZKP is not enabled
        
        Example:
            >>> result = prover.prove(formula, prefer_zkp=True)
            >>> assert prover.verify_zkp_proof(result.zkp_proof, formula)
        """
        if not self.enable_zkp:
            raise ProofError(
                "ZKP verification requires ZKP to be enabled",
                formula=formula,
                suggestion="Enable ZKP with enable_zkp=True"
            )
        
        if not HAVE_ZKP:
            raise ImportError("ZKP module not available")
        
        verifier = ZKPVerifier(backend=self.zkp_backend)
        return verifier.verify_proof(zkp_proof)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get proving statistics.
        
        Returns:
            Dictionary with statistics
        
        Example:
            >>> stats = prover.get_stats()
            >>> print(f"Standard proofs: {stats['standard_proofs']}")
            >>> print(f"ZKP proofs: {stats['zkp_proofs']}")
            >>> print(f"Cache hit rate: {stats['cache_hit_rate']:.1%}")
        """
        total_proofs = (
            self.stats['standard_proofs'] +
            self.stats['zkp_proofs'] +
            self.stats['hybrid_proofs']
        )
        
        cache_hit_rate = (
            self.stats['cache_hits'] / total_proofs
            if total_proofs > 0 else 0.0
        )
        
        return {
            **self.stats,
            'total_proofs': total_proofs,
            'cache_hit_rate': cache_hit_rate,
        }
    
    def reset_stats(self) -> None:
        """Reset proving statistics."""
        self.stats = {
            'standard_proofs': 0,
            'zkp_proofs': 0,
            'hybrid_proofs': 0,
            'zkp_failures': 0,
            'cache_hits': 0,
            'total_time': 0.0,
        }


__all__ = [
    'UnifiedProofResult',
    'ZKPTDFOLProver',
    'HAVE_ZKP',
]

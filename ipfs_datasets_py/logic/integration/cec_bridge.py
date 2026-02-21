"""
CEC Integration Bridge for ipfs_datasets_py Logic System.

This module provides bridges between CEC implementations and existing
logic infrastructure (IPFS cache, Z3 bridge, prover router, etc.).

Features:
    - CEC Z3 adapter → existing Z3 prover bridge
    - CEC formula cache → IPFS proof cache
    - CEC prover manager → prover router
    - Unified caching for all logic systems

Usage:
    >>> from ipfs_datasets_py.logic.integration.cec_bridge import CECBridge
    >>> bridge = CECBridge()
    >>> result = bridge.prove_with_z3(cec_formula)
    >>> bridge.cache_proof(cec_formula, result)
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import logging

try:
    import z3
    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False

from ..CEC.provers.z3_adapter import Z3Adapter as CECZ3Adapter, Z3ProofResult as CECProofResult
from ..CEC.provers.prover_manager import ProverManager as CECProverManager
from ..CEC.optimization.formula_cache import CacheManager as CECCacheManager
from ..external_provers.smt.z3_prover_bridge import Z3ProverBridge, Z3ProofResult
from ..external_provers.prover_router import ProverRouter, RouterProofResult
from ..integration.caching.ipfs_proof_cache import IPFSProofCache

logger = logging.getLogger(__name__)


@dataclass
class UnifiedProofResult:
    """Unified proof result that works across all logic systems."""
    is_proved: bool
    is_valid: bool
    prover_used: str
    proof_time: float
    status: str
    model: Optional[Any] = None
    error_message: Optional[str] = None
    cec_result: Optional[CECProofResult] = None
    z3_bridge_result: Optional[Z3ProofResult] = None
    router_result: Optional[RouterProofResult] = None


class CECBridge:
    """
    Bridge between CEC implementations and existing logic infrastructure.
    
    This bridge enables:
    1. CEC formulas to use existing Z3 prover bridge
    2. CEC proofs to be cached in IPFS proof cache
    3. CEC prover manager to integrate with prover router
    4. Cross-logic system proof sharing
    
    Args:
        enable_ipfs_cache: Enable IPFS-backed caching
        enable_z3: Enable Z3 prover
        enable_prover_router: Enable prover router
        cache_ttl: Default cache TTL in seconds
        
    Example:
        >>> bridge = CECBridge(enable_ipfs_cache=True)
        >>> result = bridge.prove(cec_formula, strategy='z3')
        >>> # Proof is automatically cached to IPFS
    """
    
    def __init__(
        self,
        enable_ipfs_cache: bool = True,
        enable_z3: bool = True,
        enable_prover_router: bool = True,
        cache_ttl: int = 3600,
        ipfs_host: str = '127.0.0.1',
        ipfs_port: int = 5001,
    ):
        """Initialize CEC bridge."""
        self.enable_ipfs_cache = enable_ipfs_cache
        self.enable_z3 = enable_z3
        self.enable_prover_router = enable_prover_router
        self.cache_ttl = cache_ttl
        
        # Initialize components
        self.cec_z3 = CECZ3Adapter() if enable_z3 and Z3_AVAILABLE else None
        self.z3_bridge = Z3ProverBridge() if enable_z3 and Z3_AVAILABLE else None
        self.cec_prover_manager = CECProverManager()
        self.prover_router = ProverRouter(enable_z3=enable_z3) if enable_prover_router else None
        self.cec_cache = CECCacheManager()
        
        # Initialize IPFS cache
        if enable_ipfs_cache:
            try:
                self.ipfs_cache = IPFSProofCache(
                    ttl=cache_ttl,
                    ipfs_host=ipfs_host,
                    ipfs_port=ipfs_port
                )
            except Exception as e:
                logger.warning(f"Failed to initialize IPFS cache: {e}, using local cache only")
                self.ipfs_cache = None
        else:
            self.ipfs_cache = None
    
    def prove(
        self,
        formula: Any,
        axioms: Optional[List[Any]] = None,
        strategy: str = 'auto',
        timeout: float = 5.0,
        use_cache: bool = True
    ) -> UnifiedProofResult:
        """
        Prove a CEC formula using best available prover.
        
        Args:
            formula: CEC formula to prove
            axioms: List of axioms (optional)
            strategy: Proving strategy ('auto', 'z3', 'router', 'cec')
            timeout: Timeout in seconds
            use_cache: Whether to use cache
            
        Returns:
            UnifiedProofResult with proof information
        """
        # Check cache first
        if use_cache:
            cached = self._get_cached_proof(formula)
            if cached:
                logger.info("Using cached proof")
                return cached
        
        # Select strategy
        if strategy == 'auto':
            strategy = self._select_strategy(formula)
        
        # Prove using selected strategy
        if strategy == 'z3' and self.cec_z3:
            result = self._prove_with_cec_z3(formula, axioms, timeout)
        elif strategy == 'router' and self.prover_router:
            result = self._prove_with_router(formula, timeout)
        elif strategy == 'cec':
            result = self._prove_with_cec_manager(formula, axioms, timeout)
        else:
            # Fallback to CEC native
            result = self._prove_with_cec_manager(formula, axioms, timeout)
        
        # Cache result
        if use_cache and result.is_proved:
            self._cache_proof(formula, result)
        
        return result
    
    def _select_strategy(self, formula: Any) -> str:
        """Select best proving strategy for formula."""
        # Simple heuristic: use Z3 for modal formulas, router for complex ones
        from ..CEC.native.dcec_core import DeonticFormula, CognitiveFormula, TemporalFormula
        
        if isinstance(formula, (DeonticFormula, CognitiveFormula, TemporalFormula)):
            return 'z3' if self.cec_z3 else 'cec'
        elif self.prover_router:
            return 'router'
        else:
            return 'cec'
    
    def _prove_with_cec_z3(
        self,
        formula: Any,
        axioms: Optional[List[Any]],
        timeout: float
    ) -> UnifiedProofResult:
        """Prove using CEC Z3 adapter."""
        try:
            import time
            start = time.time()
            result = self.cec_z3.prove(formula, axioms or [], timeout=timeout)
            proof_time = time.time() - start
            
            return UnifiedProofResult(
                is_proved=result.is_valid,
                is_valid=result.is_valid,
                prover_used='cec_z3',
                proof_time=proof_time,
                status=result.status.value if hasattr(result.status, 'value') else str(result.status),
                model=result.model,
                error_message=result.error_message,
                cec_result=result
            )
        except Exception as e:
            logger.error(f"CEC Z3 proving failed: {e}")
            return UnifiedProofResult(
                is_proved=False,
                is_valid=False,
                prover_used='cec_z3',
                proof_time=0.0,
                status='error',
                error_message=str(e)
            )
    
    def _prove_with_router(self, formula: Any, timeout: float) -> UnifiedProofResult:
        """Prove using prover router (if formula can be converted)."""
        try:
            # For now, use CEC manager as router doesn't directly support CEC
            return self._prove_with_cec_manager(formula, None, timeout)
        except Exception as e:
            logger.error(f"Router proving failed: {e}")
            return UnifiedProofResult(
                is_proved=False,
                is_valid=False,
                prover_used='router',
                proof_time=0.0,
                status='error',
                error_message=str(e)
            )
    
    def _prove_with_cec_manager(
        self,
        formula: Any,
        axioms: Optional[List[Any]],
        timeout: float
    ) -> UnifiedProofResult:
        """Prove using CEC prover manager."""
        try:
            import time
            from ..CEC.provers.prover_manager import ProverStrategy
            
            start = time.time()
            result = self.cec_prover_manager.prove(
                formula,
                axioms or [],
                strategy=ProverStrategy.AUTO,
                timeout=timeout
            )
            proof_time = time.time() - start
            
            return UnifiedProofResult(
                is_proved=result.is_valid,
                is_valid=result.is_valid,
                prover_used=f"cec_{result.best_prover or 'manager'}",
                proof_time=proof_time,
                status='valid' if result.is_valid else 'invalid',
                error_message=None
            )
        except Exception as e:
            logger.error(f"CEC manager proving failed: {e}")
            return UnifiedProofResult(
                is_proved=False,
                is_valid=False,
                prover_used='cec_manager',
                proof_time=0.0,
                status='error',
                error_message=str(e)
            )
    
    def _get_cached_proof(self, formula: Any) -> Optional[UnifiedProofResult]:
        """Get cached proof from IPFS or local cache."""
        formula_hash = self._compute_formula_hash(formula)
        
        # Try IPFS cache first
        if self.ipfs_cache:
            try:
                cached = self.ipfs_cache.get(formula_hash)
                if cached:
                    return UnifiedProofResult(
                        is_proved=True,
                        is_valid=True,
                        prover_used='cached',
                        proof_time=0.0,
                        status='cached'
                    )
            except Exception as e:
                logger.warning(f"IPFS cache lookup failed: {e}")
        
        # Try CEC cache
        try:
            cached = self.cec_cache.proof_cache.get(formula_hash)
            if cached:
                return UnifiedProofResult(
                    is_proved=True,
                    is_valid=True,
                    prover_used='cached',
                    proof_time=0.0,
                    status='cached'
                )
        except Exception:
            pass
        
        return None
    
    def _cache_proof(self, formula: Any, result: UnifiedProofResult):
        """Cache proof result to IPFS and local caches."""
        formula_hash = self._compute_formula_hash(formula)
        
        # Cache to IPFS
        if self.ipfs_cache and result.is_proved:
            try:
                self.ipfs_cache.put(
                    formula_hash,
                    {
                        'is_proved': result.is_proved,
                        'prover_used': result.prover_used,
                        'proof_time': result.proof_time,
                        'status': result.status
                    },
                    ttl=self.cache_ttl,
                    pin=False  # Don't pin by default
                )
            except Exception as e:
                logger.warning(f"IPFS cache storage failed: {e}")
        
        # Cache to CEC cache
        try:
            self.cec_cache.proof_cache.put(formula_hash, result)
        except Exception as e:
            logger.warning(f"CEC cache storage failed: {e}")
    
    def _compute_formula_hash(self, formula: Any) -> str:
        """Compute hash for formula."""
        import hashlib
        formula_str = str(formula)
        return hashlib.sha256(formula_str.encode()).hexdigest()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics from all components."""
        try:
            cec_stats = self.cec_cache.proof_cache.get_stats() if self.cec_cache else {}
        except AttributeError:
            cec_stats = {}
        try:
            ipfs_stats = self.ipfs_cache.get_statistics() if self.ipfs_cache else {}
        except AttributeError:
            ipfs_stats = {}
        try:
            mgr_stats = self.cec_prover_manager.get_statistics() if self.cec_prover_manager else {}
        except AttributeError:
            mgr_stats = {}
        return {
            'cec_cache': cec_stats,
            'ipfs_cache': ipfs_stats,
            'cec_manager': mgr_stats,
        }

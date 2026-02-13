"""Prover Integration Adapter for Logic Theorem Optimizer.

This module provides integration between the Logic Theorem Optimizer's
LogicCritic and the existing theorem prover infrastructure in the repository.

It handles:
- Formula translation from optimizer format to prover-specific formats
- Proof caching for performance
- Timeout handling
- Result aggregation across multiple provers
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time

logger = logging.getLogger(__name__)


class ProverStatus(Enum):
    """Status of prover verification."""
    VALID = "valid"
    INVALID = "invalid"
    TIMEOUT = "timeout"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


@dataclass
class ProverVerificationResult:
    """Result of verification by a single prover.
    
    Attributes:
        prover_name: Name of the prover
        status: Verification status
        is_valid: Whether formula is valid
        confidence: Confidence score (0.0-1.0)
        proof_time: Time taken for verification
        details: Additional details from prover
        error_message: Error message if verification failed
    """
    prover_name: str
    status: ProverStatus
    is_valid: bool
    confidence: float
    proof_time: float
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


@dataclass
class AggregatedProverResult:
    """Aggregated result from multiple provers.
    
    Attributes:
        overall_valid: True if majority of provers agree it's valid
        confidence: Weighted confidence score
        prover_results: Individual results from each prover
        agreement_rate: Percentage of provers that agree
        verified_by: List of provers that verified successfully
    """
    overall_valid: bool
    confidence: float
    prover_results: List[ProverVerificationResult]
    agreement_rate: float
    verified_by: List[str]


class ProverIntegrationAdapter:
    """Adapter for integrating theorem provers with Logic Optimizer.
    
    This adapter:
    - Manages multiple prover instances
    - Translates between optimizer and prover formats
    - Caches proof results
    - Aggregates results from multiple provers
    - Handles timeouts and errors gracefully
    
    Example:
        >>> adapter = ProverIntegrationAdapter(use_provers=['z3', 'cvc5'])
        >>> result = adapter.verify_statement(statement)
        >>> print(f"Valid: {result.overall_valid}, Confidence: {result.confidence}")
    """
    
    def __init__(
        self,
        use_provers: Optional[List[str]] = None,
        enable_cache: bool = True,
        default_timeout: float = 5.0
    ):
        """Initialize the prover integration adapter.
        
        Args:
            use_provers: List of prover names to use
            enable_cache: Whether to enable proof caching
            default_timeout: Default timeout for provers (seconds)
        """
        self.use_provers = use_provers or ['z3']
        self.enable_cache = enable_cache
        self.default_timeout = default_timeout
        
        # Initialize provers
        self.provers = {}
        self._init_provers()
        
        # Initialize cache
        self.cache = None
        if enable_cache:
            self._init_cache()
        
        # Statistics
        self.stats = {
            'verifications': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'timeouts': 0,
            'errors': 0
        }
    
    def _init_provers(self) -> None:
        """Initialize theorem provers."""
        for prover_name in self.use_provers:
            try:
                if prover_name == 'z3':
                    from ipfs_datasets_py.logic.external_provers.smt.z3_prover_bridge import Z3ProverBridge
                    self.provers['z3'] = Z3ProverBridge()
                    logger.info("Initialized Z3 prover bridge")
                    
                elif prover_name == 'cvc5':
                    from ipfs_datasets_py.logic.external_provers.smt.cvc5_prover_bridge import CVC5ProverBridge
                    self.provers['cvc5'] = CVC5ProverBridge()
                    logger.info("Initialized CVC5 prover bridge")
                    
                elif prover_name == 'lean':
                    from ipfs_datasets_py.logic.external_provers.interactive.lean_prover_bridge import LeanProverBridge
                    self.provers['lean'] = LeanProverBridge()
                    logger.info("Initialized Lean prover bridge")
                    
                elif prover_name == 'coq':
                    from ipfs_datasets_py.logic.external_provers.interactive.coq_prover_bridge import CoqProverBridge
                    self.provers['coq'] = CoqProverBridge()
                    logger.info("Initialized Coq prover bridge")
                    
                elif prover_name == 'symbolic':
                    from ipfs_datasets_py.logic.external_provers.neural.symbolicai_prover_bridge import SymbolicAIProverBridge
                    self.provers['symbolic'] = SymbolicAIProverBridge()
                    logger.info("Initialized SymbolicAI prover bridge")
                    
            except ImportError as e:
                logger.warning(f"Could not initialize {prover_name} prover: {e}")
            except Exception as e:
                logger.error(f"Error initializing {prover_name} prover: {e}")
    
    def _init_cache(self) -> None:
        """Initialize proof cache."""
        try:
            from ipfs_datasets_py.logic.external_provers.proof_cache import ProofCache
            self.cache = ProofCache(maxsize=1000, ttl=3600)
            logger.info("Initialized proof cache")
        except ImportError:
            logger.warning("ProofCache not available, caching disabled")
            self.cache = None
    
    def verify_statement(
        self,
        statement: Any,
        timeout: Optional[float] = None
    ) -> AggregatedProverResult:
        """Verify a logical statement using available provers.
        
        Args:
            statement: Logical statement to verify
            timeout: Timeout for verification (uses default if None)
            
        Returns:
            AggregatedProverResult with verification results
        """
        self.stats['verifications'] += 1
        timeout = timeout or self.default_timeout
        
        # Check cache first
        if self.cache:
            cached_result = self._check_cache(statement)
            if cached_result:
                self.stats['cache_hits'] += 1
                return cached_result
            self.stats['cache_misses'] += 1
        
        # Verify with each prover
        prover_results = []
        for prover_name, prover in self.provers.items():
            result = self._verify_with_prover(
                statement, prover_name, prover, timeout
            )
            prover_results.append(result)
        
        # Aggregate results
        aggregated = self._aggregate_results(prover_results)
        
        # Cache the result
        if self.cache:
            self._cache_result(statement, aggregated)
        
        return aggregated
    
    def _verify_with_prover(
        self,
        statement: Any,
        prover_name: str,
        prover: Any,
        timeout: float
    ) -> ProverVerificationResult:
        """Verify statement with a single prover.
        
        Args:
            statement: Statement to verify
            prover_name: Name of the prover
            prover: Prover instance
            timeout: Timeout for verification
            
        Returns:
            ProverVerificationResult
        """
        start_time = time.time()
        
        try:
            # Translate statement to prover format
            formula = self._translate_to_prover_format(statement, prover_name)
            
            # Verify with prover
            if hasattr(prover, 'prove'):
                result = prover.prove(formula, timeout=timeout)
            elif hasattr(prover, 'verify'):
                result = prover.verify(formula, timeout=timeout)
            else:
                raise AttributeError(f"Prover {prover_name} has no prove/verify method")
            
            proof_time = time.time() - start_time
            
            # Extract verification result
            is_valid = self._extract_validity(result, prover_name)
            confidence = self._extract_confidence(result, prover_name)
            
            return ProverVerificationResult(
                prover_name=prover_name,
                status=ProverStatus.VALID if is_valid else ProverStatus.INVALID,
                is_valid=is_valid,
                confidence=confidence,
                proof_time=proof_time,
                details={'raw_result': result}
            )
            
        except TimeoutError:
            self.stats['timeouts'] += 1
            return ProverVerificationResult(
                prover_name=prover_name,
                status=ProverStatus.TIMEOUT,
                is_valid=False,
                confidence=0.0,
                proof_time=timeout,
                error_message="Verification timeout"
            )
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Error verifying with {prover_name}: {e}")
            return ProverVerificationResult(
                prover_name=prover_name,
                status=ProverStatus.ERROR,
                is_valid=False,
                confidence=0.0,
                proof_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def _translate_to_prover_format(
        self,
        statement: Any,
        prover_name: str
    ) -> Any:
        """Translate statement to prover-specific format.
        
        Args:
            statement: Statement from optimizer
            prover_name: Target prover name
            
        Returns:
            Translated formula
        """
        # Extract formula string from statement
        if hasattr(statement, 'formula'):
            formula_str = statement.formula
        else:
            formula_str = str(statement)
        
        # For now, use simple string representation
        # In Phase 2.2, we'll add proper TDFOL/CEC translation
        return formula_str
    
    def _extract_validity(self, result: Any, prover_name: str) -> bool:
        """Extract validity from prover result.
        
        Args:
            result: Prover result
            prover_name: Prover name
            
        Returns:
            True if valid
        """
        # Handle different result types
        if hasattr(result, 'is_valid'):
            return result.is_valid
        elif hasattr(result, 'is_proved'):
            return result.is_proved()
        elif hasattr(result, 'valid'):
            return result.valid
        elif isinstance(result, bool):
            return result
        else:
            # Default: assume valid if no errors
            return True
    
    def _extract_confidence(self, result: Any, prover_name: str) -> float:
        """Extract confidence from prover result.
        
        Args:
            result: Prover result
            prover_name: Prover name
            
        Returns:
            Confidence score (0.0-1.0)
        """
        # Handle different result types
        if hasattr(result, 'confidence'):
            return result.confidence
        elif hasattr(result, 'is_valid'):
            # High confidence for SMT solvers
            return 0.95 if result.is_valid else 0.05
        else:
            # Default medium confidence
            return 0.7
    
    def _aggregate_results(
        self,
        prover_results: List[ProverVerificationResult]
    ) -> AggregatedProverResult:
        """Aggregate results from multiple provers.
        
        Args:
            prover_results: List of individual prover results
            
        Returns:
            AggregatedProverResult
        """
        if not prover_results:
            return AggregatedProverResult(
                overall_valid=False,
                confidence=0.0,
                prover_results=[],
                agreement_rate=0.0,
                verified_by=[]
            )
        
        # Filter successful verifications
        successful = [r for r in prover_results 
                     if r.status not in [ProverStatus.ERROR, ProverStatus.TIMEOUT]]
        
        if not successful:
            return AggregatedProverResult(
                overall_valid=False,
                confidence=0.0,
                prover_results=prover_results,
                agreement_rate=0.0,
                verified_by=[]
            )
        
        # Count valid results
        valid_count = sum(1 for r in successful if r.is_valid)
        
        # Calculate agreement rate
        agreement_rate = valid_count / len(successful)
        
        # Overall validity: majority vote
        overall_valid = agreement_rate > 0.5
        
        # Weighted confidence
        total_confidence = sum(r.confidence for r in successful if r.is_valid)
        confidence = total_confidence / len(successful) if successful else 0.0
        
        # List of provers that verified
        verified_by = [r.prover_name for r in successful if r.is_valid]
        
        return AggregatedProverResult(
            overall_valid=overall_valid,
            confidence=confidence,
            prover_results=prover_results,
            agreement_rate=agreement_rate,
            verified_by=verified_by
        )
    
    def _check_cache(self, statement: Any) -> Optional[AggregatedProverResult]:
        """Check cache for previous verification.
        
        Args:
            statement: Statement to check
            
        Returns:
            Cached result if found, None otherwise
        """
        if not self.cache:
            return None
        
        # Try to get from cache
        # (Cache implementation will handle the lookup)
        try:
            formula_str = statement.formula if hasattr(statement, 'formula') else str(statement)
            cached = self.cache.get(formula_str, prover_name="aggregated")
            if cached:
                return cached.result
        except Exception as e:
            logger.debug(f"Cache lookup error: {e}")
        
        return None
    
    def _cache_result(
        self,
        statement: Any,
        result: AggregatedProverResult
    ) -> None:
        """Cache verification result.
        
        Args:
            statement: Statement that was verified
            result: Verification result
        """
        if not self.cache:
            return
        
        try:
            formula_str = statement.formula if hasattr(statement, 'formula') else str(statement)
            self.cache.set(formula_str, result, prover_name="aggregated")
        except Exception as e:
            logger.debug(f"Cache write error: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get verification statistics.
        
        Returns:
            Dictionary of statistics
        """
        stats = self.stats.copy()
        
        # Calculate cache hit rate
        total_lookups = stats['cache_hits'] + stats['cache_misses']
        if total_lookups > 0:
            stats['cache_hit_rate'] = stats['cache_hits'] / total_lookups
        else:
            stats['cache_hit_rate'] = 0.0
        
        # Add prover info
        stats['available_provers'] = list(self.provers.keys())
        stats['num_provers'] = len(self.provers)
        
        return stats
    
    def close(self) -> None:
        """Clean up resources."""
        # Close prover connections if needed
        for prover_name, prover in self.provers.items():
            if hasattr(prover, 'close'):
                try:
                    prover.close()
                except Exception as e:
                    logger.warning(f"Error closing {prover_name}: {e}")

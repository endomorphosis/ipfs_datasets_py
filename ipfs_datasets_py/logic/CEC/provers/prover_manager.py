"""
Unified Prover Manager for CEC (Phase 6 Week 3).

This module provides a unified interface for managing multiple theorem provers,
with automatic prover selection, parallel proving, and result aggregation.

Classes:
    ProverManager: Main manager for multiple provers
    ProverConfig: Configuration for prover selection
    UnifiedProofResult: Unified result from multiple provers

Features:
    - Auto-selection based on formula complexity and type
    - Parallel execution of multiple provers
    - Result aggregation and confidence scoring
    - Fallback strategies when provers fail
    - Performance tracking and statistics

Usage:
    >>> from ipfs_datasets_py.logic.CEC.provers.prover_manager import ProverManager
    >>> manager = ProverManager()
    >>> result = manager.prove(formula, axioms, strategy="parallel")
    >>> result.is_valid
    True
"""

from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..native.dcec_core import (
    Formula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
)

from .z3_adapter import Z3Adapter, Z3ProofResult, ProofStatus, Z3_AVAILABLE
from .vampire_adapter import VampireAdapter, VampireProofResult, check_vampire_installation
from .e_prover_adapter import EProverAdapter, EProverProofResult, check_eprover_installation

logger = logging.getLogger(__name__)


class ProverType(Enum):
    """Available prover types."""
    Z3 = "z3"
    VAMPIRE = "vampire"
    E_PROVER = "eprover"


class ProverStrategy(Enum):
    """Prover selection strategies."""
    AUTO = "auto"              # Automatic prover selection
    PARALLEL = "parallel"      # Run all provers in parallel
    SEQUENTIAL = "sequential"  # Try provers one by one
    BEST = "best"             # Use single best prover for formula type


@dataclass
class ProverConfig:
    """Configuration for prover manager.
    
    Attributes:
        enabled_provers: Set of enabled prover types
        default_timeout: Default timeout per prover (seconds)
        max_parallel: Maximum parallel provers
        prefer_z3_for_modal: Prefer Z3 for modal logic
        
    Example:
        >>> config = ProverConfig(
        ...     enabled_provers={ProverType.Z3, ProverType.VAMPIRE},
        ...     default_timeout=30
        ... )
    """
    enabled_provers: Set[ProverType] = field(default_factory=lambda: {
        ProverType.Z3, ProverType.VAMPIRE, ProverType.E_PROVER
    })
    default_timeout: int = 30
    max_parallel: int = 3
    prefer_z3_for_modal: bool = True


@dataclass
class UnifiedProofResult:
    """Unified proof result from multiple provers.
    
    Attributes:
        status: Overall proof status
        is_valid: Whether any prover validated the formula
        prover_results: Dict of individual prover results
        best_prover: Prover that produced best result
        total_time: Total time across all provers
        confidence: Confidence score (0.0-1.0)
        
    Example:
        >>> result.is_valid
        True
        >>> result.best_prover
        'z3'
        >>> result.confidence
        0.95
    """
    status: ProofStatus
    is_valid: bool = False
    prover_results: Dict[str, Any] = field(default_factory=dict)
    best_prover: Optional[str] = None
    total_time: float = 0.0
    confidence: float = 0.0
    error_messages: List[str] = field(default_factory=list)


class ProverManager:
    """
    Unified manager for multiple theorem provers.
    
    Coordinates Z3, Vampire, and E provers with intelligent
    selection and parallel execution strategies.
    
    Attributes:
        config: ProverConfig with manager settings
        available_provers: Dict of available prover instances
        
    Example:
        >>> manager = ProverManager()
        >>> result = manager.prove(formula, strategy="auto")
        >>> print(f"Proved by {result.best_prover}")
    """
    
    def __init__(self, config: Optional[ProverConfig] = None):
        """Initialize prover manager.
        
        Args:
            config: Optional ProverConfig (uses defaults if not provided)
        """
        self.config = config or ProverConfig()
        self.available_provers: Dict[ProverType, Any] = {}
        self._init_provers()
        self.stats = {
            'total_proofs': 0,
            'valid_proofs': 0,
            'z3_used': 0,
            'vampire_used': 0,
            'eprover_used': 0
        }
    
    def _init_provers(self) -> None:
        """Initialize available provers."""
        # Try Z3
        if ProverType.Z3 in self.config.enabled_provers and Z3_AVAILABLE:
            try:
                self.available_provers[ProverType.Z3] = Z3Adapter(
                    timeout=self.config.default_timeout * 1000  # Z3 uses milliseconds
                )
                logger.info("Z3 prover initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Z3: {e}")
        
        # Try Vampire
        if ProverType.VAMPIRE in self.config.enabled_provers:
            try:
                vampire = VampireAdapter(timeout=self.config.default_timeout)
                if vampire.is_available():
                    self.available_provers[ProverType.VAMPIRE] = vampire
                    logger.info("Vampire prover initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Vampire: {e}")
        
        # Try E prover
        if ProverType.E_PROVER in self.config.enabled_provers:
            try:
                eprover = EProverAdapter(timeout=self.config.default_timeout)
                if eprover.is_available():
                    self.available_provers[ProverType.E_PROVER] = eprover
                    logger.info("E prover initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize E prover: {e}")
        
        if not self.available_provers:
            logger.warning("No provers available!")
    
    def get_available_provers(self) -> List[ProverType]:
        """Get list of available provers.
        
        Returns:
            List of ProverType values
        """
        return list(self.available_provers.keys())
    
    def select_best_prover(self, formula: Formula) -> Optional[ProverType]:
        """Select best prover for given formula type.
        
        Args:
            formula: Formula to prove
            
        Returns:
            Best ProverType or None if none available
        """
        if not self.available_provers:
            return None
        
        # Z3 is best for modal logic (deontic, cognitive, temporal)
        if self.config.prefer_z3_for_modal:
            if isinstance(formula, (DeonticFormula, CognitiveFormula, TemporalFormula)):
                if ProverType.Z3 in self.available_provers:
                    return ProverType.Z3
        
        # For pure first-order, prefer Vampire or E
        if isinstance(formula, (ConnectiveFormula,)):
            if ProverType.VAMPIRE in self.available_provers:
                return ProverType.VAMPIRE
            elif ProverType.E_PROVER in self.available_provers:
                return ProverType.E_PROVER
        
        # Default: use first available
        return list(self.available_provers.keys())[0]
    
    def prove(
        self,
        formula: Formula,
        axioms: Optional[List[Formula]] = None,
        strategy: str = "auto",
        timeout: Optional[int] = None
    ) -> UnifiedProofResult:
        """Prove formula using configured strategy.
        
        Args:
            formula: Formula to prove
            axioms: Optional list of axioms
            strategy: Strategy ("auto", "parallel", "sequential", "best")
            timeout: Optional timeout override
            
        Returns:
            UnifiedProofResult with aggregated results
        """
        start_time = time.time()
        self.stats['total_proofs'] += 1
        
        if strategy == "parallel":
            return self._prove_parallel(formula, axioms, timeout)
        elif strategy == "sequential":
            return self._prove_sequential(formula, axioms, timeout)
        elif strategy == "best":
            return self._prove_best(formula, axioms, timeout)
        else:  # auto
            return self._prove_auto(formula, axioms, timeout)
    
    def _prove_auto(
        self,
        formula: Formula,
        axioms: Optional[List[Formula]],
        timeout: Optional[int]
    ) -> UnifiedProofResult:
        """Auto strategy: intelligent selection."""
        # Select best prover
        best = self.select_best_prover(formula)
        if not best:
            return UnifiedProofResult(
                status=ProofStatus.ERROR,
                error_messages=["No provers available"]
            )
        
        # Use best prover
        return self._prove_with_prover(best, formula, axioms, timeout)
    
    def _prove_best(
        self,
        formula: Formula,
        axioms: Optional[List[Formula]],
        timeout: Optional[int]
    ) -> UnifiedProofResult:
        """Best strategy: use single best prover."""
        return self._prove_auto(formula, axioms, timeout)
    
    def _prove_sequential(
        self,
        formula: Formula,
        axioms: Optional[List[Formula]],
        timeout: Optional[int]
    ) -> UnifiedProofResult:
        """Sequential strategy: try provers one by one."""
        prover_results = {}
        total_time = 0.0
        
        for prover_type in self.available_provers:
            result = self._prove_with_prover(prover_type, formula, axioms, timeout)
            prover_results[prover_type.value] = result
            total_time += result.total_time
            
            # Stop if valid proof found
            if result.is_valid:
                self.stats['valid_proofs'] += 1
                return UnifiedProofResult(
                    status=ProofStatus.VALID,
                    is_valid=True,
                    prover_results=prover_results,
                    best_prover=prover_type.value,
                    total_time=total_time,
                    confidence=0.95
                )
        
        # No prover succeeded
        return UnifiedProofResult(
            status=ProofStatus.UNKNOWN,
            is_valid=False,
            prover_results=prover_results,
            total_time=total_time,
            confidence=0.0
        )
    
    def _prove_parallel(
        self,
        formula: Formula,
        axioms: Optional[List[Formula]],
        timeout: Optional[int]
    ) -> UnifiedProofResult:
        """Parallel strategy: run all provers simultaneously."""
        prover_results = {}
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.config.max_parallel) as executor:
            # Submit all provers
            futures = {}
            for prover_type in self.available_provers:
                future = executor.submit(
                    self._prove_with_prover,
                    prover_type,
                    formula,
                    axioms,
                    timeout
                )
                futures[future] = prover_type
            
            # Wait for results
            for future in as_completed(futures):
                prover_type = futures[future]
                try:
                    result = future.result()
                    prover_results[prover_type.value] = result
                    
                    # If valid, can return early
                    if result.is_valid:
                        total_time = time.time() - start_time
                        self.stats['valid_proofs'] += 1
                        
                        return UnifiedProofResult(
                            status=ProofStatus.VALID,
                            is_valid=True,
                            prover_results=prover_results,
                            best_prover=prover_type.value,
                            total_time=total_time,
                            confidence=1.0
                        )
                except Exception as e:
                    logger.error(f"Parallel proving error for {prover_type}: {e}")
                    prover_results[prover_type.value] = UnifiedProofResult(
                        status=ProofStatus.ERROR,
                        error_messages=[str(e)]
                    )
        
        # No prover succeeded
        total_time = time.time() - start_time
        return UnifiedProofResult(
            status=ProofStatus.UNKNOWN,
            is_valid=False,
            prover_results=prover_results,
            total_time=total_time,
            confidence=0.0
        )
    
    def _prove_with_prover(
        self,
        prover_type: ProverType,
        formula: Formula,
        axioms: Optional[List[Formula]],
        timeout: Optional[int]
    ) -> UnifiedProofResult:
        """Prove with specific prover."""
        prover = self.available_provers.get(prover_type)
        if not prover:
            return UnifiedProofResult(
                status=ProofStatus.ERROR,
                error_messages=[f"Prover {prover_type.value} not available"]
            )
        
        try:
            # Update stats
            if prover_type == ProverType.Z3:
                self.stats['z3_used'] += 1
            elif prover_type == ProverType.VAMPIRE:
                self.stats['vampire_used'] += 1
            elif prover_type == ProverType.E_PROVER:
                self.stats['eprover_used'] += 1
            
            # Prove
            if prover_type == ProverType.Z3:
                result = prover.prove(formula, axioms, timeout_ms=timeout*1000 if timeout else None)
                return UnifiedProofResult(
                    status=result.status,
                    is_valid=result.is_valid,
                    prover_results={'z3': result},
                    best_prover='z3',
                    total_time=result.proof_time,
                    confidence=0.9 if result.is_valid else 0.0
                )
            
            else:  # Vampire or E prover
                result = prover.prove(formula, axioms, timeout_override=timeout)
                return UnifiedProofResult(
                    status=result.status,
                    is_valid=result.is_valid,
                    prover_results={prover_type.value: result},
                    best_prover=prover_type.value,
                    total_time=result.proof_time,
                    confidence=0.9 if result.is_valid else 0.0
                )
        
        except Exception as e:
            logger.error(f"Prover {prover_type.value} error: {e}")
            return UnifiedProofResult(
                status=ProofStatus.ERROR,
                error_messages=[str(e)]
            )
    
    def get_stats(self) -> Dict[str, int]:
        """Get usage statistics.
        
        Returns:
            Dict with prover usage stats
        """
        return self.stats.copy()
    
    def reset_stats(self) -> None:
        """Reset usage statistics."""
        for key in self.stats:
            self.stats[key] = 0

"""
Prover Router for Automatic Prover Selection and Parallel Proving

This module provides intelligent routing between different provers
based on formula characteristics, and supports parallel proving
with multiple provers simultaneously.

Usage:
    >>> from ipfs_datasets_py.logic.external_provers import ProverRouter
    >>> router = ProverRouter(enable_z3=True, enable_cvc5=True)
    >>> result = router.prove(formula, strategy='auto')
    
    >>> # Parallel proving
    >>> results = router.prove_parallel(formula, timeout=10.0)
    >>> best = router.select_best(results)
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
from enum import Enum
import concurrent.futures
import time


class ProverStrategy(Enum):
    """Strategy for prover selection."""
    AUTO = "auto"  # Automatic selection based on formula
    FASTEST = "fastest"  # Try fastest prover first
    MOST_CAPABLE = "most_capable"  # Try most capable prover
    PARALLEL = "parallel"  # Try all provers in parallel
    SEQUENTIAL = "sequential"  # Try provers sequentially


@dataclass
class RouterProofResult:
    """Result from prover router.
    
    Attributes:
        is_proved: True if formula was proved
        prover_used: Name of prover that succeeded
        proof_time: Time taken to prove
        all_results: Results from all provers (if parallel)
        strategy_used: Strategy that was used
        reason: Reason for result
    """
    is_proved: bool
    prover_used: Optional[str]
    proof_time: float
    all_results: Dict[str, Any]
    strategy_used: str
    reason: str
    
    def get_prover_result(self, prover_name: str) -> Optional[Any]:
        """Get result from a specific prover."""
        return self.all_results.get(prover_name)


class ProverRouter:
    """Router for selecting and coordinating multiple theorem provers.
    
    The router can:
    1. Automatically select the best prover for a formula
    2. Try provers in parallel
    3. Try provers sequentially with fallback
    4. Aggregate and compare results
    
    Attributes:
        enable_z3: Whether to enable Z3
        enable_cvc5: Whether to enable CVC5
        enable_lean: Whether to enable Lean
        enable_coq: Whether to enable Coq
        enable_native: Whether to enable native provers
        default_strategy: Default proving strategy
        default_timeout: Default timeout per prover
    """
    
    def __init__(
        self,
        enable_z3: bool = True,
        enable_cvc5: bool = False,
        enable_lean: bool = False,
        enable_coq: bool = False,
        enable_native: bool = True,
        default_strategy: ProverStrategy = ProverStrategy.AUTO,
        default_timeout: float = 5.0
    ):
        """Initialize prover router.
        
        Args:
            enable_z3: Whether to enable Z3
            enable_cvc5: Whether to enable CVC5
            enable_lean: Whether to enable Lean
            enable_coq: Whether to enable Coq
            enable_native: Whether to enable native provers
            default_strategy: Default proving strategy
            default_timeout: Default timeout per prover
        """
        self.enable_z3 = enable_z3
        self.enable_cvc5 = enable_cvc5
        self.enable_lean = enable_lean
        self.enable_coq = enable_coq
        self.enable_native = enable_native
        self.default_strategy = default_strategy
        self.default_timeout = default_timeout
        
        # Initialize provers
        self.provers = {}
        self._initialize_provers()
    
    def _initialize_provers(self):
        """Initialize available provers."""
        # Z3
        if self.enable_z3:
            try:
                from .smt.z3_prover_bridge import Z3ProverBridge, Z3_AVAILABLE
                if Z3_AVAILABLE:
                    self.provers['z3'] = Z3ProverBridge(timeout=self.default_timeout)
            except ImportError:
                pass
        
        # CVC5
        if self.enable_cvc5:
            try:
                from .smt.cvc5_prover_bridge import CVC5ProverBridge, CVC5_AVAILABLE
                if CVC5_AVAILABLE:
                    self.provers['cvc5'] = CVC5ProverBridge(timeout=self.default_timeout)
            except ImportError:
                pass
        
        # Lean
        if self.enable_lean:
            try:
                from .interactive.lean_prover_bridge import LeanProverBridge, LEAN_AVAILABLE
                if LEAN_AVAILABLE:
                    self.provers['lean'] = LeanProverBridge(timeout=self.default_timeout)
            except ImportError:
                pass
        
        # Coq
        if self.enable_coq:
            try:
                from .interactive.coq_prover_bridge import CoqProverBridge, COQ_AVAILABLE
                if COQ_AVAILABLE:
                    self.provers['coq'] = CoqProverBridge(timeout=self.default_timeout)
            except ImportError:
                pass
        
        # Native prover
        if self.enable_native:
            try:
                from ..TDFOL.tdfol_prover import TDFOLProver
                self.provers['native'] = TDFOLProver()
            except ImportError:
                pass
    
    def get_available_provers(self) -> List[str]:
        """Get list of available provers."""
        return list(self.provers.keys())
    
    def _select_prover_for_formula(self, formula) -> str:
        """Select best prover for a formula based on characteristics.
        
        Args:
            formula: TDFOL formula
            
        Returns:
            Name of selected prover
        """
        # Simple heuristic for now
        # TODO: Add formula analysis
        
        # Prefer Z3 for FOL
        if 'z3' in self.provers:
            return 'z3'
        
        # Fall back to native
        if 'native' in self.provers:
            return 'native'
        
        # Use first available
        if self.provers:
            return list(self.provers.keys())[0]
        
        raise RuntimeError("No provers available")
    
    def prove(
        self,
        formula,
        axioms: Optional[List] = None,
        strategy: Optional[ProverStrategy] = None,
        timeout: Optional[float] = None
    ) -> RouterProofResult:
        """Prove a formula using the specified strategy.
        
        Args:
            formula: TDFOL formula to prove
            axioms: Optional list of axioms
            strategy: Proving strategy (None = use default)
            timeout: Timeout per prover (None = use default)
            
        Returns:
            RouterProofResult with proof status
        """
        strategy = strategy or self.default_strategy
        timeout = timeout or self.default_timeout
        
        if strategy == ProverStrategy.AUTO:
            return self._prove_auto(formula, axioms, timeout)
        elif strategy == ProverStrategy.PARALLEL:
            return self._prove_parallel(formula, axioms, timeout)
        elif strategy == ProverStrategy.SEQUENTIAL:
            return self._prove_sequential(formula, axioms, timeout)
        elif strategy == ProverStrategy.FASTEST:
            return self._prove_fastest(formula, axioms, timeout)
        elif strategy == ProverStrategy.MOST_CAPABLE:
            return self._prove_most_capable(formula, axioms, timeout)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
    
    def _prove_auto(
        self,
        formula,
        axioms: Optional[List],
        timeout: float
    ) -> RouterProofResult:
        """Prove using automatic prover selection."""
        start_time = time.time()
        
        # Select best prover
        prover_name = self._select_prover_for_formula(formula)
        prover = self.provers[prover_name]
        
        # Prove
        try:
            result = prover.prove(formula, axioms=axioms, timeout=timeout)
            proof_time = time.time() - start_time
            
            return RouterProofResult(
                is_proved=result.is_proved() if hasattr(result, 'is_proved') else result.is_valid,
                prover_used=prover_name,
                proof_time=proof_time,
                all_results={prover_name: result},
                strategy_used="auto",
                reason=f"Used {prover_name}"
            )
        except Exception as e:
            proof_time = time.time() - start_time
            return RouterProofResult(
                is_proved=False,
                prover_used=prover_name,
                proof_time=proof_time,
                all_results={},
                strategy_used="auto",
                reason=f"Error: {str(e)}"
            )
    
    def _prove_parallel(
        self,
        formula,
        axioms: Optional[List],
        timeout: float
    ) -> RouterProofResult:
        """Prove using all provers in parallel."""
        start_time = time.time()
        all_results = {}
        
        def prove_with_prover(prover_name: str, prover):
            """Wrapper for parallel execution."""
            try:
                result = prover.prove(formula, axioms=axioms, timeout=timeout)
                return (prover_name, result, None)
            except Exception as e:
                return (prover_name, None, str(e))
        
        # Execute all provers in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.provers)) as executor:
            futures = {
                executor.submit(prove_with_prover, name, prover): name
                for name, prover in self.provers.items()
            }
            
            for future in concurrent.futures.as_completed(futures):
                prover_name, result, error = future.result()
                all_results[prover_name] = result if result else error
        
        proof_time = time.time() - start_time
        
        # Find first successful proof
        for prover_name, result in all_results.items():
            if result and hasattr(result, 'is_proved') and result.is_proved():
                return RouterProofResult(
                    is_proved=True,
                    prover_used=prover_name,
                    proof_time=proof_time,
                    all_results=all_results,
                    strategy_used="parallel",
                    reason=f"Proved by {prover_name}"
                )
        
        return RouterProofResult(
            is_proved=False,
            prover_used=None,
            proof_time=proof_time,
            all_results=all_results,
            strategy_used="parallel",
            reason="No prover succeeded"
        )
    
    def _prove_sequential(
        self,
        formula,
        axioms: Optional[List],
        timeout: float
    ) -> RouterProofResult:
        """Prove trying provers sequentially."""
        start_time = time.time()
        all_results = {}
        
        # Try provers in order
        for prover_name, prover in self.provers.items():
            try:
                result = prover.prove(formula, axioms=axioms, timeout=timeout)
                all_results[prover_name] = result
                
                if result.is_proved() if hasattr(result, 'is_proved') else result.is_valid:
                    proof_time = time.time() - start_time
                    return RouterProofResult(
                        is_proved=True,
                        prover_used=prover_name,
                        proof_time=proof_time,
                        all_results=all_results,
                        strategy_used="sequential",
                        reason=f"Proved by {prover_name}"
                    )
            except Exception as e:
                all_results[prover_name] = f"Error: {str(e)}"
        
        proof_time = time.time() - start_time
        return RouterProofResult(
            is_proved=False,
            prover_used=None,
            proof_time=proof_time,
            all_results=all_results,
            strategy_used="sequential",
            reason="All provers failed"
        )
    
    def _prove_fastest(
        self,
        formula,
        axioms: Optional[List],
        timeout: float
    ) -> RouterProofResult:
        """Prove with fastest prover (Z3 preferred)."""
        # Prefer Z3 as fastest
        if 'z3' in self.provers:
            start_time = time.time()
            try:
                result = self.provers['z3'].prove(formula, axioms=axioms, timeout=timeout)
                proof_time = time.time() - start_time
                return RouterProofResult(
                    is_proved=result.is_proved(),
                    prover_used='z3',
                    proof_time=proof_time,
                    all_results={'z3': result},
                    strategy_used="fastest",
                    reason="Used Z3 (fastest)"
                )
            except Exception as e:
                pass
        
        # Fall back to auto
        return self._prove_auto(formula, axioms, timeout)
    
    def _prove_most_capable(
        self,
        formula,
        axioms: Optional[List],
        timeout: float
    ) -> RouterProofResult:
        """Prove with most capable prover (Lean/Coq preferred)."""
        # Prefer Lean or Coq as most capable
        for prover_name in ['lean', 'coq', 'cvc5', 'z3', 'native']:
            if prover_name in self.provers:
                start_time = time.time()
                try:
                    result = self.provers[prover_name].prove(formula, axioms=axioms, timeout=timeout)
                    proof_time = time.time() - start_time
                    return RouterProofResult(
                        is_proved=result.is_proved() if hasattr(result, 'is_proved') else result.is_valid,
                        prover_used=prover_name,
                        proof_time=proof_time,
                        all_results={prover_name: result},
                        strategy_used="most_capable",
                        reason=f"Used {prover_name}"
                    )
                except Exception as e:
                    continue
        
        # All failed
        return RouterProofResult(
            is_proved=False,
            prover_used=None,
            proof_time=0.0,
            all_results={},
            strategy_used="most_capable",
            reason="No capable prover available"
        )
    
    def prove_parallel(
        self,
        formula,
        axioms: Optional[List] = None,
        timeout: float = None
    ) -> RouterProofResult:
        """Convenience method for parallel proving."""
        return self.prove(formula, axioms, strategy=ProverStrategy.PARALLEL, timeout=timeout)
    
    def select_best(self, result: RouterProofResult) -> Any:
        """Select best result from parallel proving.
        
        Args:
            result: RouterProofResult from parallel proving
            
        Returns:
            Best individual prover result
        """
        if not result.all_results:
            return None
        
        # If any proved, return first proof
        for prover_name, prover_result in result.all_results.items():
            if hasattr(prover_result, 'is_proved') and prover_result.is_proved():
                return prover_result
        
        # Otherwise return first result
        return list(result.all_results.values())[0]


__all__ = [
    "ProverRouter",
    "ProverStrategy",
    "RouterProofResult",
]

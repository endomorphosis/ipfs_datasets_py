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
from typing import Any, Dict, List, Mapping, Optional, Union
from enum import Enum
import concurrent.futures
import inspect
import time
import logging

from .formula_analyzer import FormulaAnalyzer

logger = logging.getLogger(__name__)


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

    def is_compiled(self) -> bool:
        """Return True when at least one prover accepted the formula payload."""

        if self.is_proved:
            return True
        return any(
            _result_is_compiled_result(result)
            for result in self.all_results.values()
        )


def _result_is_compiled_result(result: Any) -> bool:
    """Return True when an individual prover result accepted the payload."""

    if result is None or isinstance(result, str):
        return False
    for attr_name in ("is_compiled", "compiles"):
        compiled = getattr(result, attr_name, None)
        if callable(compiled):
            try:
                return bool(compiled())
            except Exception:
                return False
        if compiled not in (None, ""):
            return bool(compiled)
    return True


@dataclass(frozen=True)
class SyntacticProofResult:
    """Compile-only fallback result for router environments without TDFOL."""

    formula: Any
    is_valid: bool
    message: str
    method: str = "syntactic_native_fallback"

    def is_proved(self) -> bool:
        """The fallback validates routing syntax but never asserts a theorem."""

        return False

    def is_compiled(self) -> bool:
        """Return True when the fallback accepted the formula syntax."""

        return self.is_valid


class SyntacticNativeFallbackProver:
    """Minimal native prover substitute used when the full TDFOL prover is absent."""

    def prove(self, goal: Any, **_: Any) -> SyntacticProofResult:
        formula = ProverRouter._coerce_native_formula(goal)
        is_valid = formula is not None and bool(str(formula).strip())
        return SyntacticProofResult(
            formula=formula,
            is_valid=is_valid,
            message=(
                "formula accepted by syntactic native fallback"
                if is_valid
                else "formula rejected by syntactic native fallback"
            ),
        )


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
        enable_symbolicai: bool = False,
        default_strategy: ProverStrategy = ProverStrategy.AUTO,
        default_timeout: float = 5.0,
        enable_cache: bool = True,
        enable_syntactic_fallback: bool = True,
    ):
        """Initialize prover router.
        
        Args:
            enable_z3: Whether to enable Z3
            enable_cvc5: Whether to enable CVC5
            enable_lean: Whether to enable Lean
            enable_coq: Whether to enable Coq
            enable_native: Whether to enable native provers
            enable_symbolicai: Whether to enable SymbolicAI
            default_strategy: Default proving strategy
            default_timeout: Default timeout per prover
            enable_cache: Whether to enable proof caching
            enable_syntactic_fallback: Whether to keep a compile-only
                fallback available when configured provers are absent
        """
        self.enable_z3 = enable_z3
        self.enable_cvc5 = enable_cvc5
        self.enable_lean = enable_lean
        self.enable_coq = enable_coq
        self.enable_native = enable_native
        self.enable_symbolicai = enable_symbolicai
        self.default_strategy = self._coerce_strategy(default_strategy)
        self.default_timeout = default_timeout
        self.enable_cache = enable_cache
        self.enable_syntactic_fallback = enable_syntactic_fallback
        
        # Initialize formula analyzer for intelligent selection
        self.analyzer = FormulaAnalyzer()
        
        # Initialize cache if enabled
        self._cache = None
        if self.enable_cache:
            try:
                from .proof_cache import get_global_cache
                self._cache = get_global_cache()
            except ImportError:
                self.enable_cache = False
        
        # Initialize provers
        self.provers = {}
        self._initialize_provers()
        if self.enable_syntactic_fallback and not self.provers:
            self.provers['native_syntactic'] = SyntacticNativeFallbackProver()
    
    def _initialize_provers(self):
        """Initialize available provers."""
        # Z3
        if self.enable_z3:
            try:
                from .smt import z3_prover_bridge

                if z3_prover_bridge._ensure_z3_available():
                    self.provers['z3'] = z3_prover_bridge.Z3ProverBridge(
                        timeout=self.default_timeout,
                        enable_cache=self.enable_cache
                    )
            except Exception:
                logger.debug("Z3 prover unavailable during router init", exc_info=True)
        
        # CVC5
        if self.enable_cvc5:
            try:
                from .smt import cvc5_prover_bridge

                if cvc5_prover_bridge._ensure_cvc5_available():
                    self.provers['cvc5'] = cvc5_prover_bridge.CVC5ProverBridge(timeout=self.default_timeout)
            except Exception:
                logger.debug("CVC5 prover unavailable during router init", exc_info=True)
        
        # Lean
        if self.enable_lean:
            try:
                from .interactive import lean_prover_bridge

                if lean_prover_bridge._ensure_lean_available():
                    self.provers['lean'] = lean_prover_bridge.LeanProverBridge(timeout=self.default_timeout)
            except Exception:
                logger.debug("Lean prover unavailable during router init", exc_info=True)
        
        # Coq
        if self.enable_coq:
            try:
                from .interactive import coq_prover_bridge

                if coq_prover_bridge._ensure_coq_available():
                    self.provers['coq'] = coq_prover_bridge.CoqProverBridge(timeout=self.default_timeout)
            except Exception:
                logger.debug("Coq prover unavailable during router init", exc_info=True)
        
        # SymbolicAI
        if self.enable_symbolicai:
            try:
                from .neural import symbolicai_prover_bridge

                if symbolicai_prover_bridge._ensure_symbolicai_available():
                    self.provers['symbolicai'] = symbolicai_prover_bridge.SymbolicAIProverBridge(
                        timeout=self.default_timeout,
                        enable_cache=self.enable_cache
                    )
            except Exception:
                logger.debug("SymbolicAI prover unavailable during router init", exc_info=True)
        
        # Native prover
        if self.enable_native:
            try:
                from ..TDFOL.tdfol_prover import TDFOLProver
                self.provers['native'] = TDFOLProver()
                if self.enable_syntactic_fallback:
                    self.provers['native_syntactic'] = SyntacticNativeFallbackProver()
            except Exception:
                logger.debug(
                    "Native TDFOL prover unavailable; using syntactic fallback",
                    exc_info=True,
                )
                if self.enable_syntactic_fallback:
                    self.provers['native_syntactic'] = SyntacticNativeFallbackProver()
    
    def get_available_provers(self) -> List[str]:
        """Get list of available provers."""
        return list(self.provers.keys())

    @property
    def fallback_prover(self) -> Optional[str]:
        """Return the primary fallback prover currently available."""
        if "native" in self.provers:
            return "native"
        if self.provers:
            return next(iter(self.provers))
        return None

    @property
    def backup_provers(self) -> List[str]:
        """Return available prover names for legacy router callers."""
        return list(self.provers.keys())

    def select_prover(self, formula) -> Optional[str]:
        """Public compatibility wrapper for automatic prover selection."""
        try:
            return self._select_prover_for_formula(formula)
        except Exception:
            logger.debug("Could not select prover for formula", exc_info=True)
            return None

    def route(self, formula, **kwargs) -> RouterProofResult:
        """Public compatibility wrapper for proving through the router."""
        strategy = kwargs.pop("strategy", None)
        if strategy is None:
            for key in ("strategy_name", "strategy_mode", "mode"):
                if key in kwargs:
                    strategy = kwargs.pop(key)
                    break

        timeout = kwargs.pop("timeout", None)
        timeout_ms = kwargs.pop("timeout_ms", None)
        if timeout is None and timeout_ms is not None:
            try:
                timeout = float(timeout_ms) / 1000.0
            except (TypeError, ValueError):
                timeout = None
        elif timeout is not None:
            try:
                timeout = float(timeout)
            except (TypeError, ValueError):
                timeout = None

        axioms = kwargs.pop("axioms", None)
        if kwargs:
            logger.debug(
                "Ignoring unsupported prover router kwargs: %s",
                sorted(str(key) for key in kwargs),
            )

        return self.prove(
            formula,
            axioms=axioms,
            strategy=strategy,
            timeout=timeout,
        )

    @staticmethod
    def _coerce_strategy(strategy: Any) -> ProverStrategy:
        """Normalize string/enum strategy inputs to ProverStrategy values."""

        if isinstance(strategy, ProverStrategy):
            return strategy
        if strategy is None:
            return ProverStrategy.AUTO
        text = (
            str(strategy or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        if not text:
            return ProverStrategy.AUTO
        if text in {"default", "router_default"}:
            return ProverStrategy.AUTO
        for candidate in ProverStrategy:
            if text in {candidate.value, candidate.name.lower()}:
                return candidate
        raise ValueError(f"Unknown strategy: {strategy}")

    def _call_prover(
        self,
        prover_name: str,
        prover: Any,
        formula: Any,
        axioms: Optional[List],
        timeout: float,
    ) -> Any:
        """Call one prover while normalizing signature differences."""

        timeout_seconds = float(
            self.default_timeout if timeout is None else timeout
        )
        timeout_ms = max(1, int(timeout_seconds * 1000.0))
        normalized_formula = formula
        normalized_axioms = axioms

        if prover_name == "native":
            normalized_formula = self._coerce_native_formula(formula)
            if axioms:
                normalized_axioms = [
                    item
                    for item in (
                        self._coerce_native_formula(axiom) for axiom in axioms
                    )
                    if item is not None
                ]

        # Native TDFOL prover uses add_axiom(...) + prove(..., timeout_ms=...).
        if prover_name == "native" and normalized_axioms and hasattr(prover, "add_axiom"):
            for index, axiom in enumerate(normalized_axioms):
                axiom_name = f"router_axiom_{index}"
                try:
                    prover.add_axiom(axiom, name=axiom_name)
                except TypeError:
                    prover.add_axiom(axiom)

        try:
            prove_params = inspect.signature(prover.prove).parameters
        except (TypeError, ValueError):
            prove_params = {}

        accepts_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in prove_params.values()
        )

        kwargs: Dict[str, Any] = {}
        if accepts_kwargs or "axioms" in prove_params:
            kwargs["axioms"] = normalized_axioms
        if accepts_kwargs or "timeout" in prove_params:
            kwargs["timeout"] = timeout_seconds
        elif "timeout_ms" in prove_params:
            kwargs["timeout_ms"] = timeout_ms

        return prover.prove(normalized_formula, **kwargs)

    @staticmethod
    def _coerce_native_formula(formula: Any) -> Any:
        """Best-effort conversion of router payloads into native TDFOL formulas."""

        return ProverRouter._coerce_native_formula_inner(formula, seen=set())

    @staticmethod
    def _coerce_native_formula_inner(formula: Any, *, seen: set[int]) -> Any:
        """Best-effort conversion helper with cycle protection."""

        if formula is None:
            return None
        if isinstance(formula, Mapping):
            object_id = id(formula)
            if object_id in seen:
                return None
            seen.add(object_id)
            consumed_keys: set[str] = set()
            formula_keys = (
                "formula_object",
                "proof_formula_object",
                "formula",
                "candidate_formula",
                "formula_candidate",
                "compiler_formula",
                "program_formula",
                "proof_input",
                "proof_formula",
                "proof_candidate",
                "tdfol_formula",
                "goal",
                "proof_goal",
                "theorem",
                "theorem_formula",
                "claim",
                "claims",
                "assertion",
                "assertions",
                "proposition",
                "propositions",
                "logical_form",
                "logic_formula",
                "normalized_formula",
                "normalized_proof",
                "expression",
                "value",
            )
            container_keys = (
                "proof_obligation",
                "obligation",
                "payload",
                "router_payload",
                "view",
                "data",
                "obligations",
                "proof_obligations",
                "proofs",
                "records",
                "formulas",
                "theorems",
                "goals",
                "clauses",
                "items",
            )
            text_keys = (
                "text",
                "source_text",
                "normalized_text",
            )
            for key in formula_keys + container_keys + text_keys:
                if key not in formula:
                    continue
                consumed_keys.add(key)
                value = formula.get(key)
                if value is formula:
                    continue
                coerced = ProverRouter._coerce_native_formula_inner(value, seen=seen)
                if coerced is not None:
                    return coerced
            for raw_key in sorted(formula.keys(), key=lambda item: str(item)):
                key = str(raw_key)
                if key in consumed_keys:
                    continue
                value = formula.get(raw_key)
                if value is formula:
                    continue
                coerced = ProverRouter._coerce_native_formula_inner(value, seen=seen)
                if coerced is not None:
                    return coerced
            return None
        if isinstance(formula, (list, tuple)):
            object_id = id(formula)
            if object_id in seen:
                return None
            seen.add(object_id)
            for item in formula:
                coerced = ProverRouter._coerce_native_formula_inner(item, seen=seen)
                if coerced is not None:
                    return coerced
            return None
        if hasattr(formula, "to_string") and hasattr(formula, "get_predicates"):
            return formula
        text = str(formula or "").strip()
        if not text:
            return None
        try:
            from ..bridge.fol_tdfol import coerce_tdfol_formula

            coerced = coerce_tdfol_formula(text)
            if coerced is not None:
                return coerced
        except Exception:
            logger.debug("Could not coerce native formula payload", exc_info=True)
        return formula

    @staticmethod
    def _result_is_proved(result: Any) -> bool:
        """Return True when a prover result indicates a valid proof."""

        if result is None:
            return False

        is_proved = getattr(result, "is_proved", None)
        if callable(is_proved):
            try:
                return bool(is_proved())
            except Exception:
                return False

        if hasattr(result, "is_valid"):
            return bool(getattr(result, "is_valid"))

        if isinstance(result, bool):
            return result

        return False
    
    def _select_prover_for_formula(self, formula) -> str:
        """Select best prover for a formula based on characteristics.
        
        Args:
            formula: TDFOL formula
            
        Returns:
            Name of selected prover
        """
        try:
            # Analyze formula to get recommendations
            analysis = self.analyzer.analyze(formula)

            logger.debug(f"Formula analysis: type={analysis.formula_type.value}, "
                        f"complexity={analysis.complexity.value}, score={analysis.complexity_score:.1f}")
            logger.debug(f"Recommended provers: {analysis.recommended_provers}")

            # Try recommended provers in order
            for prover_name in analysis.recommended_provers:
                if prover_name in self.provers:
                    logger.info(f"Selected {prover_name} based on formula analysis")
                    return prover_name
        except Exception:
            logger.debug(
                "Formula analysis failed during prover selection; using fallback order",
                exc_info=True,
            )
        
        # Fallback: prefer Z3 for FOL
        if 'z3' in self.provers:
            logger.info("Fallback to Z3")
            return 'z3'
        
        # Fall back to native
        if 'native' in self.provers:
            logger.info("Fallback to native prover")
            return 'native'

        if 'native_syntactic' in self.provers:
            logger.info("Fallback to syntactic native prover")
            return 'native_syntactic'
        
        # Use first available
        if self.provers:
            prover_name = list(self.provers.keys())[0]
            logger.info(f"Using first available prover: {prover_name}")
            return prover_name
        
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
        strategy = self._coerce_strategy(strategy or self.default_strategy)
        timeout = self.default_timeout if timeout is None else float(timeout)
        
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

        try:
            # Select best prover
            selected_prover = self._select_prover_for_formula(formula)
        except RuntimeError as exc:
            proof_time = time.time() - start_time
            return RouterProofResult(
                is_proved=False,
                prover_used=None,
                proof_time=proof_time,
                all_results={},
                strategy_used="auto",
                reason=str(exc),
            )

        # Keep the analyzer-selected prover first, then deterministically
        # fall back across the remaining available provers.
        ordered_provers = [selected_prover] + [
            prover_name
            for prover_name in self.provers
            if prover_name != selected_prover
        ]
        all_results: Dict[str, Any] = {}
        first_non_error: Optional[str] = None

        for prover_name in ordered_provers:
            prover = self.provers[prover_name]
            try:
                result = self._call_prover(
                    prover_name,
                    prover,
                    formula,
                    axioms,
                    timeout,
                )
            except Exception as exc:
                all_results[prover_name] = f"Error: {str(exc)}"
                continue

            all_results[prover_name] = result
            if first_non_error is None:
                first_non_error = prover_name
            if self._result_is_proved(result):
                proof_time = time.time() - start_time
                return RouterProofResult(
                    is_proved=True,
                    prover_used=prover_name,
                    proof_time=proof_time,
                    all_results=all_results,
                    strategy_used="auto",
                    reason=f"Proved by {prover_name}",
                )

        proof_time = time.time() - start_time
        if first_non_error is None:
            reason = "All provers failed"
        elif first_non_error == selected_prover:
            reason = f"Used {selected_prover} (no proof)"
        else:
            reason = f"Fell back to {first_non_error} (no proof)"
        return RouterProofResult(
            is_proved=False,
            prover_used=first_non_error,
            proof_time=proof_time,
            all_results=all_results,
            strategy_used="auto",
            reason=reason,
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

        if not self.provers:
            return RouterProofResult(
                is_proved=False,
                prover_used=None,
                proof_time=0.0,
                all_results={},
                strategy_used="parallel",
                reason="No provers available",
            )
        
        def prove_with_prover(prover_name: str, prover):
            """Wrapper for parallel execution."""
            try:
                result = self._call_prover(prover_name, prover, formula, axioms, timeout)
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
                all_results[prover_name] = (
                    f"Error: {error}" if error is not None else result
                )
        
        proof_time = time.time() - start_time
        
        # Find first successful proof
        for prover_name, result in all_results.items():
            if self._result_is_proved(result):
                return RouterProofResult(
                    is_proved=True,
                    prover_used=prover_name,
                    proof_time=proof_time,
                    all_results=all_results,
                    strategy_used="parallel",
                    reason=f"Proved by {prover_name}"
                )

        first_non_error = next(
            (
                prover_name
                for prover_name, result in all_results.items()
                if not isinstance(result, str)
            ),
            None,
        )
        
        return RouterProofResult(
            is_proved=False,
            prover_used=first_non_error,
            proof_time=proof_time,
            all_results=all_results,
            strategy_used="parallel",
            reason=(
                f"Used {first_non_error} (no proof)"
                if first_non_error
                else "No prover succeeded"
            )
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
                result = self._call_prover(prover_name, prover, formula, axioms, timeout)
                all_results[prover_name] = result
                
                if self._result_is_proved(result):
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
        first_non_error = next(
            (
                prover_name
                for prover_name, result in all_results.items()
                if not isinstance(result, str)
            ),
            None,
        )
        if first_non_error:
            reason = f"Used {first_non_error} (no proof)"
        elif all_results:
            reason = "All provers failed"
        else:
            reason = "No provers available"
        return RouterProofResult(
            is_proved=False,
            prover_used=first_non_error,
            proof_time=proof_time,
            all_results=all_results,
            strategy_used="sequential",
            reason=reason,
        )
    
    def _prove_fastest(
        self,
        formula,
        axioms: Optional[List],
        timeout: float
    ) -> RouterProofResult:
        """Prove with fastest prover (Z3 preferred)."""
        fastest_order = [
            "z3",
            "native",
            "native_syntactic",
            "cvc5",
            "lean",
            "coq",
            "symbolicai",
        ]
        ordered_provers = [
            name for name in fastest_order if name in self.provers
        ] + [
            name for name in self.provers if name not in fastest_order
        ]
        return self._prove_ordered(
            formula,
            axioms,
            timeout,
            ordered_provers,
            strategy_used="fastest",
            no_available_reason="No fastest prover available",
        )
    
    def _prove_most_capable(
        self,
        formula,
        axioms: Optional[List],
        timeout: float
    ) -> RouterProofResult:
        """Prove with most capable prover (Lean/Coq preferred)."""
        capable_order = ['lean', 'coq', 'cvc5', 'z3', 'native', 'native_syntactic']
        ordered_provers = [
            name for name in capable_order if name in self.provers
        ] + [
            name for name in self.provers if name not in capable_order
        ]
        return self._prove_ordered(
            formula,
            axioms,
            timeout,
            ordered_provers,
            strategy_used="most_capable",
            no_available_reason="No capable prover available",
        )

    def _prove_ordered(
        self,
        formula,
        axioms: Optional[List],
        timeout: float,
        ordered_provers: List[str],
        *,
        strategy_used: str,
        no_available_reason: str,
    ) -> RouterProofResult:
        """Try an explicit prover order and keep compile fallback evidence."""

        start_time = time.time()
        all_results: Dict[str, Any] = {}
        first_non_error: Optional[str] = None

        for prover_name in ordered_provers:
            prover = self.provers.get(prover_name)
            if prover is None:
                continue
            try:
                result = self._call_prover(
                    prover_name,
                    prover,
                    formula,
                    axioms,
                    timeout,
                )
            except Exception as exc:
                all_results[prover_name] = f"Error: {str(exc)}"
                continue

            all_results[prover_name] = result
            if first_non_error is None:
                first_non_error = prover_name
            if self._result_is_proved(result):
                return RouterProofResult(
                    is_proved=True,
                    prover_used=prover_name,
                    proof_time=time.time() - start_time,
                    all_results=all_results,
                    strategy_used=strategy_used,
                    reason=f"Proved by {prover_name}",
                )

        if first_non_error:
            return RouterProofResult(
                is_proved=False,
                prover_used=first_non_error,
                proof_time=time.time() - start_time,
                all_results=all_results,
                strategy_used=strategy_used,
                reason=f"Used {first_non_error} (no proof)",
            )
        if all_results:
            return RouterProofResult(
                is_proved=False,
                prover_used=None,
                proof_time=time.time() - start_time,
                all_results=all_results,
                strategy_used=strategy_used,
                reason="All provers failed",
            )
        return RouterProofResult(
            is_proved=False,
            prover_used=None,
            proof_time=0.0,
            all_results={},
            strategy_used=strategy_used,
            reason=no_available_reason,
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
            if self._result_is_proved(prover_result):
                return prover_result
        
        # Otherwise return first result
        return list(result.all_results.values())[0]


__all__ = [
    "ProverRouter",
    "ProverStrategy",
    "RouterProofResult",
    "SyntacticNativeFallbackProver",
    "SyntacticProofResult",
]

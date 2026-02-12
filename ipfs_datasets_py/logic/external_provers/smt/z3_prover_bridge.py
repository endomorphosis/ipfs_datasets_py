"""
Z3 SMT Solver Integration for TDFOL

This module provides integration with Microsoft's Z3 theorem prover, 
one of the most powerful SMT (Satisfiability Modulo Theories) solvers.

Z3 supports:
- First-order logic with quantifiers
- Integer and real arithmetic
- Arrays, bitvectors, strings
- Uninterpreted functions
- Model generation for satisfiable formulas
- Unsat core extraction

Usage:
    >>> from ipfs_datasets_py.logic.external_provers import Z3ProverBridge
    >>> prover = Z3ProverBridge()
    >>> result = prover.prove(formula, timeout=5.0)
    >>> if result.is_proved():
    ...     print("Formula is valid!")
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
import time

# Check Z3 availability
try:
    import z3
    Z3_AVAILABLE = True
except ImportError:
    z3 = None
    Z3_AVAILABLE = False


@dataclass
class Z3ProofResult:
    """Result from Z3 prover.
    
    Attributes:
        is_valid: True if formula is valid (unsat when negated)
        is_sat: True if formula is satisfiable
        is_unsat: True if formula is unsatisfiable
        model: Model if satisfiable (None otherwise)
        unsat_core: Unsat core if unsatisfiable (None otherwise)
        reason: Reason for the result (sat/unsat/unknown/timeout/error)
        proof_time: Time taken to prove (seconds)
        z3_result: Raw Z3 result object
    """
    is_valid: bool
    is_sat: bool
    is_unsat: bool
    model: Optional[Any]
    unsat_core: Optional[List[str]]
    reason: str
    proof_time: float
    z3_result: Optional[Any]
    
    def is_proved(self) -> bool:
        """Check if the formula was successfully proved."""
        return self.is_valid


class TDFOLToZ3Converter:
    """Convert TDFOL formulas to Z3 expressions.
    
    This converter handles the translation from TDFOL's representation
    to Z3's internal representation, including:
    - Predicates → Z3 functions returning Bool
    - Quantifiers → Z3 ForAll/Exists
    - Logical operators → Z3 And/Or/Not/Implies
    - Terms → Z3 Const/Function application
    """
    
    def __init__(self):
        """Initialize the converter."""
        if not Z3_AVAILABLE:
            raise ImportError("Z3 is not available. Install with: pip install z3-solver")
        
        self.var_cache: Dict[str, Any] = {}
        self.func_cache: Dict[str, Any] = {}
        self.pred_cache: Dict[str, Any] = {}
        self.sort_cache: Dict[str, Any] = {}
    
    def convert(self, formula) -> Any:
        """Convert a TDFOL formula to Z3 expression.
        
        Args:
            formula: TDFOL formula object
            
        Returns:
            Z3 expression
        """
        from ipfs_datasets_py.logic.TDFOL import tdfol_core
        
        if isinstance(formula, tdfol_core.Predicate):
            return self._convert_predicate(formula)
        elif isinstance(formula, tdfol_core.BinaryFormula):
            return self._convert_binary(formula)
        elif isinstance(formula, tdfol_core.UnaryFormula):
            return self._convert_unary(formula)
        elif isinstance(formula, tdfol_core.QuantifiedFormula):
            return self._convert_quantified(formula)
        elif isinstance(formula, tdfol_core.DeonticFormula):
            # Treat deontic operators as predicates for now
            return self._convert_deontic(formula)
        elif isinstance(formula, tdfol_core.TemporalFormula):
            # Treat temporal operators as predicates for now
            return self._convert_temporal(formula)
        else:
            raise ValueError(f"Unsupported formula type: {type(formula)}")
    
    def _get_sort(self, sort_name: str) -> Any:
        """Get or create a Z3 sort."""
        if sort_name not in self.sort_cache:
            # For now, use uninterpreted sorts
            self.sort_cache[sort_name] = z3.DeclareSort(sort_name)
        return self.sort_cache[sort_name]
    
    def _convert_term(self, term) -> Any:
        """Convert a TDFOL term to Z3 expression."""
        from ipfs_datasets_py.logic.TDFOL import tdfol_core
        
        if isinstance(term, tdfol_core.Variable):
            if term.name not in self.var_cache:
                # Create a Z3 constant of appropriate sort
                sort = self._get_sort(term.sort.value if term.sort else "Object")
                self.var_cache[term.name] = z3.Const(term.name, sort)
            return self.var_cache[term.name]
        
        elif isinstance(term, tdfol_core.Constant):
            if term.name not in self.var_cache:
                sort = self._get_sort(term.sort.value if term.sort else "Object")
                self.var_cache[term.name] = z3.Const(term.name, sort)
            return self.var_cache[term.name]
        
        elif isinstance(term, tdfol_core.FunctionApplication):
            # Convert function application
            func_name = term.function_symbol
            if func_name not in self.func_cache:
                # Create uninterpreted function
                arity = len(term.args)
                arg_sorts = [self._get_sort("Object")] * arity
                result_sort = self._get_sort("Object")
                self.func_cache[func_name] = z3.Function(func_name, *arg_sorts, result_sort)
            
            z3_args = [self._convert_term(arg) for arg in term.args]
            return self.func_cache[func_name](*z3_args)
        
        else:
            raise ValueError(f"Unsupported term type: {type(term)}")
    
    def _convert_predicate(self, pred) -> Any:
        """Convert a predicate to Z3 boolean function."""
        pred_name = pred.name
        
        if pred_name not in self.pred_cache:
            # Create boolean function
            arity = len(pred.args)
            arg_sorts = [self._get_sort("Object")] * arity
            self.pred_cache[pred_name] = z3.Function(pred_name, *arg_sorts, z3.BoolSort())
        
        z3_args = [self._convert_term(arg) for arg in pred.args]
        return self.pred_cache[pred_name](*z3_args)
    
    def _convert_binary(self, formula) -> Any:
        """Convert a binary formula."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import LogicOperator
        
        left = self.convert(formula.left)
        right = self.convert(formula.right)
        
        op = formula.operator
        if op == LogicOperator.AND:
            return z3.And(left, right)
        elif op == LogicOperator.OR:
            return z3.Or(left, right)
        elif op == LogicOperator.IMPLIES:
            return z3.Implies(left, right)
        elif op == LogicOperator.IFF:
            return left == right  # Z3 uses == for iff
        else:
            raise ValueError(f"Unsupported binary operator: {op}")
    
    def _convert_unary(self, formula) -> Any:
        """Convert a unary formula."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import LogicOperator
        
        inner = self.convert(formula.formula)
        
        if formula.operator == LogicOperator.NOT:
            return z3.Not(inner)
        else:
            raise ValueError(f"Unsupported unary operator: {formula.operator}")
    
    def _convert_quantified(self, formula) -> Any:
        """Convert a quantified formula."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Quantifier
        
        # Convert bound variable
        var = formula.variable
        z3_var = self._convert_term(var)
        
        # Convert body
        body = self.convert(formula.formula)
        
        if formula.quantifier == Quantifier.FORALL:
            return z3.ForAll([z3_var], body)
        elif formula.quantifier == Quantifier.EXISTS:
            return z3.Exists([z3_var], body)
        else:
            raise ValueError(f"Unsupported quantifier: {formula.quantifier}")
    
    def _convert_deontic(self, formula) -> Any:
        """Convert a deontic formula.
        
        For now, we treat deontic operators as uninterpreted predicates.
        This allows Z3 to reason about their logical properties without
        built-in deontic axioms.
        """
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticOperator
        
        inner = self.convert(formula.formula)
        
        # Create a deontic predicate
        op_name = f"deontic_{formula.operator.value}"
        if op_name not in self.pred_cache:
            self.pred_cache[op_name] = z3.Function(op_name, z3.BoolSort(), z3.BoolSort())
        
        return self.pred_cache[op_name](inner)
    
    def _convert_temporal(self, formula) -> Any:
        """Convert a temporal formula.
        
        For now, we treat temporal operators as uninterpreted predicates.
        Full temporal logic requires a more sophisticated encoding (e.g., LTL).
        """
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import TemporalOperator
        
        inner = self.convert(formula.formula)
        
        # Create a temporal predicate
        op_name = f"temporal_{formula.operator.value}"
        if op_name not in self.pred_cache:
            self.pred_cache[op_name] = z3.Function(op_name, z3.BoolSort(), z3.BoolSort())
        
        return self.pred_cache[op_name](inner)


class Z3ProverBridge:
    """Bridge between TDFOL and Z3 theorem prover.
    
    This class provides a high-level interface to Z3 for proving TDFOL formulas.
    
    Attributes:
        timeout: Default timeout in seconds (None = no timeout)
        use_unsat_core: Whether to extract unsat cores
        use_model: Whether to generate models for satisfiable formulas
    """
    
    def __init__(
        self,
        timeout: Optional[float] = None,
        use_unsat_core: bool = False,
        use_model: bool = True
    ):
        """Initialize Z3 prover bridge.
        
        Args:
            timeout: Default timeout in seconds (None = no timeout)
            use_unsat_core: Whether to extract unsat cores
            use_model: Whether to generate models for satisfiable formulas
        """
        if not Z3_AVAILABLE:
            raise ImportError("Z3 is not available. Install with: pip install z3-solver")
        
        self.timeout = timeout
        self.use_unsat_core = use_unsat_core
        self.use_model = use_model
        self.converter = TDFOLToZ3Converter()
    
    def prove(
        self,
        formula,
        axioms: Optional[List] = None,
        timeout: Optional[float] = None
    ) -> Z3ProofResult:
        """Prove a TDFOL formula using Z3.
        
        Args:
            formula: TDFOL formula to prove
            axioms: Optional list of axiom formulas
            timeout: Timeout in seconds (overrides default)
            
        Returns:
            Z3ProofResult with proof status and details
        """
        start_time = time.time()
        
        try:
            # Create Z3 solver
            solver = z3.Solver()
            
            # Set timeout if specified
            if timeout is not None:
                solver.set("timeout", int(timeout * 1000))  # Z3 uses milliseconds
            elif self.timeout is not None:
                solver.set("timeout", int(self.timeout * 1000))
            
            # Add axioms
            if axioms:
                for axiom in axioms:
                    z3_axiom = self.converter.convert(axiom)
                    solver.add(z3_axiom)
            
            # To prove formula, we check if its negation is unsat
            z3_formula = self.converter.convert(formula)
            solver.add(z3.Not(z3_formula))
            
            # Check satisfiability
            result = solver.check()
            proof_time = time.time() - start_time
            
            if result == z3.unsat:
                # Formula is valid (negation is unsat)
                unsat_core = None
                if self.use_unsat_core:
                    unsat_core = [str(c) for c in solver.unsat_core()]
                
                return Z3ProofResult(
                    is_valid=True,
                    is_sat=False,
                    is_unsat=True,
                    model=None,
                    unsat_core=unsat_core,
                    reason="unsat",
                    proof_time=proof_time,
                    z3_result=result
                )
            
            elif result == z3.sat:
                # Formula is not valid (negation is sat = counterexample exists)
                model = None
                if self.use_model:
                    model = solver.model()
                
                return Z3ProofResult(
                    is_valid=False,
                    is_sat=True,
                    is_unsat=False,
                    model=model,
                    unsat_core=None,
                    reason="sat",
                    proof_time=proof_time,
                    z3_result=result
                )
            
            else:  # z3.unknown
                return Z3ProofResult(
                    is_valid=False,
                    is_sat=False,
                    is_unsat=False,
                    model=None,
                    unsat_core=None,
                    reason="unknown",
                    proof_time=proof_time,
                    z3_result=result
                )
        
        except Exception as e:
            proof_time = time.time() - start_time
            return Z3ProofResult(
                is_valid=False,
                is_sat=False,
                is_unsat=False,
                model=None,
                unsat_core=None,
                reason=f"error: {str(e)}",
                proof_time=proof_time,
                z3_result=None
            )
    
    def check_satisfiability(
        self,
        formula,
        timeout: Optional[float] = None
    ) -> Z3ProofResult:
        """Check satisfiability of a formula (don't negate).
        
        Args:
            formula: TDFOL formula to check
            timeout: Timeout in seconds
            
        Returns:
            Z3ProofResult with satisfiability status
        """
        start_time = time.time()
        
        try:
            solver = z3.Solver()
            
            if timeout is not None:
                solver.set("timeout", int(timeout * 1000))
            elif self.timeout is not None:
                solver.set("timeout", int(self.timeout * 1000))
            
            z3_formula = self.converter.convert(formula)
            solver.add(z3_formula)
            
            result = solver.check()
            proof_time = time.time() - start_time
            
            if result == z3.sat:
                model = solver.model() if self.use_model else None
                return Z3ProofResult(
                    is_valid=False,
                    is_sat=True,
                    is_unsat=False,
                    model=model,
                    unsat_core=None,
                    reason="sat",
                    proof_time=proof_time,
                    z3_result=result
                )
            elif result == z3.unsat:
                unsat_core = None
                if self.use_unsat_core:
                    unsat_core = [str(c) for c in solver.unsat_core()]
                return Z3ProofResult(
                    is_valid=True,
                    is_sat=False,
                    is_unsat=True,
                    model=None,
                    unsat_core=unsat_core,
                    reason="unsat",
                    proof_time=proof_time,
                    z3_result=result
                )
            else:
                return Z3ProofResult(
                    is_valid=False,
                    is_sat=False,
                    is_unsat=False,
                    model=None,
                    unsat_core=None,
                    reason="unknown",
                    proof_time=proof_time,
                    z3_result=result
                )
        
        except Exception as e:
            proof_time = time.time() - start_time
            return Z3ProofResult(
                is_valid=False,
                is_sat=False,
                is_unsat=False,
                model=None,
                unsat_core=None,
                reason=f"error: {str(e)}",
                proof_time=proof_time,
                z3_result=None
            )


# Convenience function
def prove_with_z3(formula, axioms=None, timeout=5.0) -> Z3ProofResult:
    """Prove a formula using Z3 (convenience function).
    
    Args:
        formula: TDFOL formula to prove
        axioms: Optional list of axiom formulas
        timeout: Timeout in seconds
        
    Returns:
        Z3ProofResult
    """
    prover = Z3ProverBridge(timeout=timeout)
    return prover.prove(formula, axioms=axioms)


__all__ = [
    "Z3ProverBridge",
    "Z3ProofResult",
    "TDFOLToZ3Converter",
    "prove_with_z3",
    "Z3_AVAILABLE",
]

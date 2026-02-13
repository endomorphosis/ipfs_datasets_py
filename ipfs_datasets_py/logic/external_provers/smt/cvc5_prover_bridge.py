"""
CVC5 SMT Solver Integration for TDFOL

This module provides integration with Stanford's CVC5 theorem prover.

CVC5 supports:
- First-order logic with excellent quantifier handling
- Integer and real arithmetic (linear and nonlinear)
- Datatypes, strings with regex
- Sets, bags, sequences
- Proof generation

Usage:
    >>> from ipfs_datasets_py.logic.external_provers import CVC5ProverBridge
    >>> prover = CVC5ProverBridge()
    >>> result = prover.prove(formula, timeout=5.0)
    >>> if result.is_proved():
    ...     print("Formula is valid!")
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import time

# Check CVC5 availability
try:
    import cvc5
    from cvc5 import Kind
    CVC5_AVAILABLE = True
except ImportError:
    cvc5 = None
    CVC5_AVAILABLE = False


@dataclass
class CVC5ProofResult:
    """Result from CVC5 prover.
    
    Attributes:
        is_valid: True if formula is valid (unsat when negated)
        is_sat: True if formula is satisfiable
        is_unsat: True if formula is unsatisfiable
        model: Model if satisfiable (None otherwise)
        proof: Proof object if available (None otherwise)
        reason: Reason for the result (sat/unsat/unknown/timeout/error)
        proof_time: Time taken to prove (seconds)
        cvc5_result: Raw CVC5 result object
    """
    is_valid: bool
    is_sat: bool
    is_unsat: bool
    model: Optional[Any]
    proof: Optional[Any]
    reason: str
    proof_time: float
    cvc5_result: Optional[Any]
    
    def is_proved(self) -> bool:
        """Check if the formula was successfully proved."""
        return self.is_valid


class TDFOLToCVC5Converter:
    """Convert TDFOL formulas to CVC5 terms.
    
    This converter handles the translation from TDFOL's representation
    to CVC5's internal representation, including:
    - Predicates → CVC5 functions returning Bool
    - Quantifiers → CVC5 FORALL/EXISTS
    - Logical operators → CVC5 AND/OR/NOT/IMPLIES
    - Terms → CVC5 constants/function application
    """
    
    def __init__(self, solver):
        """Initialize the converter.
        
        Args:
            solver: CVC5 solver instance
        """
        if not CVC5_AVAILABLE:
            raise ImportError("CVC5 is not available. Install with: pip install cvc5")
        
        self.solver = solver
        self.tm = solver.getTermManager()
        self.var_cache: Dict[str, Any] = {}
        self.func_cache: Dict[str, Any] = {}
        self.pred_cache: Dict[str, Any] = {}
        self.sort_cache: Dict[str, Any] = {}
    
    def convert(self, formula) -> Any:
        """Convert a TDFOL formula to CVC5 term.
        
        Args:
            formula: TDFOL formula object
            
        Returns:
            CVC5 term
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
            # Treat deontic operators as predicates
            return self._convert_deontic(formula)
        elif isinstance(formula, tdfol_core.TemporalFormula):
            # Treat temporal operators as predicates
            return self._convert_temporal(formula)
        else:
            raise ValueError(f"Unsupported formula type: {type(formula)}")
    
    def _get_sort(self, sort_name: str) -> Any:
        """Get or create a CVC5 sort."""
        if sort_name not in self.sort_cache:
            # For now, use uninterpreted sorts
            self.sort_cache[sort_name] = self.tm.mkUninterpretedSort(sort_name)
        return self.sort_cache[sort_name]
    
    def _convert_term(self, term) -> Any:
        """Convert a TDFOL term to CVC5 term."""
        from ipfs_datasets_py.logic.TDFOL import tdfol_core
        
        if isinstance(term, tdfol_core.Variable):
            if term.name not in self.var_cache:
                # Create a CVC5 constant of appropriate sort
                sort = self._get_sort(term.sort.value if term.sort else "Object")
                self.var_cache[term.name] = self.tm.mkConst(sort, term.name)
            return self.var_cache[term.name]
        
        elif isinstance(term, tdfol_core.Constant):
            if term.name not in self.var_cache:
                sort = self._get_sort(term.sort.value if term.sort else "Object")
                self.var_cache[term.name] = self.tm.mkConst(sort, term.name)
            return self.var_cache[term.name]
        
        elif isinstance(term, tdfol_core.FunctionApplication):
            # Convert function application
            func_name = term.function_symbol
            if func_name not in self.func_cache:
                # Create uninterpreted function
                arity = len(term.args)
                arg_sorts = [self._get_sort("Object")] * arity
                result_sort = self._get_sort("Object")
                func_sort = self.tm.mkFunctionSort(arg_sorts, result_sort)
                self.func_cache[func_name] = self.tm.mkConst(func_sort, func_name)
            
            cvc5_args = [self._convert_term(arg) for arg in term.args]
            return self.tm.mkTerm(Kind.APPLY_UF, self.func_cache[func_name], *cvc5_args)
        
        else:
            raise ValueError(f"Unsupported term type: {type(term)}")
    
    def _convert_predicate(self, pred) -> Any:
        """Convert a predicate to CVC5 boolean function."""
        pred_name = pred.name
        
        if pred_name not in self.pred_cache:
            # Create boolean function
            arity = len(pred.args)
            arg_sorts = [self._get_sort("Object")] * arity
            bool_sort = self.tm.getBooleanSort()
            func_sort = self.tm.mkFunctionSort(arg_sorts, bool_sort)
            self.pred_cache[pred_name] = self.tm.mkConst(func_sort, pred_name)
        
        cvc5_args = [self._convert_term(arg) for arg in pred.args]
        return self.tm.mkTerm(Kind.APPLY_UF, self.pred_cache[pred_name], *cvc5_args)
    
    def _convert_binary(self, formula) -> Any:
        """Convert a binary formula."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import LogicOperator
        
        left = self.convert(formula.left)
        right = self.convert(formula.right)
        
        op = formula.operator
        if op == LogicOperator.AND:
            return self.tm.mkTerm(Kind.AND, left, right)
        elif op == LogicOperator.OR:
            return self.tm.mkTerm(Kind.OR, left, right)
        elif op == LogicOperator.IMPLIES:
            return self.tm.mkTerm(Kind.IMPLIES, left, right)
        elif op == LogicOperator.IFF:
            return self.tm.mkTerm(Kind.EQUAL, left, right)
        else:
            raise ValueError(f"Unsupported binary operator: {op}")
    
    def _convert_unary(self, formula) -> Any:
        """Convert a unary formula."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import LogicOperator
        
        inner = self.convert(formula.formula)
        
        if formula.operator == LogicOperator.NOT:
            return self.tm.mkTerm(Kind.NOT, inner)
        else:
            raise ValueError(f"Unsupported unary operator: {formula.operator}")
    
    def _convert_quantified(self, formula) -> Any:
        """Convert a quantified formula."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Quantifier
        
        # Convert bound variable
        var = formula.variable
        cvc5_var = self._convert_term(var)
        
        # Convert body
        body = self.convert(formula.formula)
        
        # Create bound variable list
        bound_vars = self.tm.mkTerm(Kind.VARIABLE_LIST, cvc5_var)
        
        if formula.quantifier == Quantifier.FORALL:
            return self.tm.mkTerm(Kind.FORALL, bound_vars, body)
        elif formula.quantifier == Quantifier.EXISTS:
            return self.tm.mkTerm(Kind.EXISTS, bound_vars, body)
        else:
            raise ValueError(f"Unsupported quantifier: {formula.quantifier}")
    
    def _convert_deontic(self, formula) -> Any:
        """Convert a deontic formula.
        
        For now, we treat deontic operators as uninterpreted predicates.
        This allows CVC5 to reason about their logical properties without
        built-in deontic axioms.
        """
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticOperator
        
        inner = self.convert(formula.formula)
        
        # Create a deontic predicate
        op_name = f"deontic_{formula.operator.value}"
        if op_name not in self.pred_cache:
            bool_sort = self.tm.getBooleanSort()
            func_sort = self.tm.mkFunctionSort([bool_sort], bool_sort)
            self.pred_cache[op_name] = self.tm.mkConst(func_sort, op_name)
        
        return self.tm.mkTerm(Kind.APPLY_UF, self.pred_cache[op_name], inner)
    
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
            bool_sort = self.tm.getBooleanSort()
            func_sort = self.tm.mkFunctionSort([bool_sort], bool_sort)
            self.pred_cache[op_name] = self.tm.mkConst(func_sort, op_name)
        
        return self.tm.mkTerm(Kind.APPLY_UF, self.pred_cache[op_name], inner)


class CVC5ProverBridge:
    """Bridge between TDFOL and CVC5 theorem prover.
    
    This class provides a high-level interface to CVC5 for proving TDFOL formulas.
    
    Attributes:
        timeout: Default timeout in seconds (None = no timeout)
        use_proof: Whether to generate proofs
        use_model: Whether to generate models for satisfiable formulas
        enable_cache: Whether to cache proof results
    """
    
    def __init__(
        self,
        timeout: Optional[float] = None,
        use_proof: bool = False,
        use_model: bool = True,
        enable_cache: bool = True
    ):
        """Initialize CVC5 prover bridge.
        
        Args:
            timeout: Default timeout in seconds (None = no timeout)
            use_proof: Whether to generate proofs
            use_model: Whether to generate models for satisfiable formulas
            enable_cache: Whether to enable proof caching
        """
        if not CVC5_AVAILABLE:
            raise ImportError("CVC5 is not available. Install with: pip install cvc5")
        
        self.timeout = timeout
        self.use_proof = use_proof
        self.use_model = use_model
        self.enable_cache = enable_cache
        
        # Initialize cache if enabled
        self._cache = None
        if self.enable_cache:
            try:
                from ..proof_cache import get_global_cache
                self._cache = get_global_cache()
            except ImportError:
                self.enable_cache = False
    
    def prove(
        self,
        formula,
        axioms: Optional[List] = None,
        timeout: Optional[float] = None
    ) -> CVC5ProofResult:
        """Prove a TDFOL formula using CVC5.
        
        Args:
            formula: TDFOL formula to prove
            axioms: Optional list of axiom formulas
            timeout: Timeout in seconds (overrides default)
            
        Returns:
            CVC5ProofResult with proof status and details
        """
        # Check cache first (O(1) lookup via CID)
        if self.enable_cache and self._cache is not None:
            cached_result = self._cache.get(
                formula,
                axioms=axioms,
                prover_name="CVC5",
                prover_config={'timeout': timeout, 'use_proof': self.use_proof, 'use_model': self.use_model}
            )
            if cached_result is not None:
                return cached_result
        
        start_time = time.time()
        
        try:
            # Create CVC5 solver
            solver = cvc5.Solver()
            
            # Set logic (use ALL for general first-order logic)
            solver.setLogic("ALL")
            
            # Set timeout if specified
            if timeout is not None:
                solver.setOption("tlimit-per", str(int(timeout * 1000)))  # CVC5 uses milliseconds
            elif self.timeout is not None:
                solver.setOption("tlimit-per", str(int(self.timeout * 1000)))
            
            # Enable proof production if requested
            if self.use_proof:
                solver.setOption("produce-proofs", "true")
            
            # Enable model production if requested
            if self.use_model:
                solver.setOption("produce-models", "true")
            
            # Create converter
            converter = TDFOLToCVC5Converter(solver)
            
            # Add axioms
            if axioms:
                for axiom in axioms:
                    cvc5_axiom = converter.convert(axiom)
                    solver.assertFormula(cvc5_axiom)
            
            # To prove formula, we check if its negation is unsat
            cvc5_formula = converter.convert(formula)
            tm = solver.getTermManager()
            negated = tm.mkTerm(Kind.NOT, cvc5_formula)
            solver.assertFormula(negated)
            
            # Check satisfiability
            result = solver.checkSat()
            proof_time = time.time() - start_time
            
            if result.isUnsat():
                # Formula is valid (negation is unsat)
                proof_obj = None
                if self.use_proof:
                    try:
                        proof_obj = solver.getProof()
                    except Exception as exc:
                        # Proof generation may not be available in all configurations
                        logger.debug("Could not get proof from CVC5: %s", exc)
                
                proof_result = CVC5ProofResult(
                    is_valid=True,
                    is_sat=False,
                    is_unsat=True,
                    model=None,
                    proof=proof_obj,
                    reason="unsat",
                    proof_time=proof_time,
                    cvc5_result=result
                )
                
                # Cache the result (use same config as cache lookup for consistency)
                if self.enable_cache and self._cache is not None:
                    self._cache.set(formula, proof_result, axioms=axioms, prover_name="CVC5", 
                                    prover_config={'timeout': timeout, 'use_proof': self.use_proof, 'use_model': self.use_model})
                
                return proof_result
            
            elif result.isSat():
                # Formula is not valid (negation is sat = counterexample exists)
                model = None
                if self.use_model:
                    try:
                        # Get model representation
                        model = str(solver.getModel())
                    except Exception as exc:
                        # Model generation may fail in some cases
                        logger.debug("Could not get model from CVC5: %s", exc)
                
                proof_result = CVC5ProofResult(
                    is_valid=False,
                    is_sat=True,
                    is_unsat=False,
                    model=model,
                    proof=None,
                    reason="sat",
                    proof_time=proof_time,
                    cvc5_result=result
                )
                
                # Cache the result (even for sat - useful for repeated queries)
                if self.enable_cache and self._cache is not None:
                    self._cache.set(formula, proof_result, axioms=axioms, prover_name="CVC5", prover_config={'timeout': timeout})
                
                return proof_result
            
            else:  # Unknown
                proof_result = CVC5ProofResult(
                    is_valid=False,
                    is_sat=False,
                    is_unsat=False,
                    model=None,
                    proof=None,
                    reason="unknown",
                    proof_time=proof_time,
                    cvc5_result=result
                )
                
                return proof_result
        
        except Exception as e:
            proof_time = time.time() - start_time
            return CVC5ProofResult(
                is_valid=False,
                is_sat=False,
                is_unsat=False,
                model=None,
                proof=None,
                reason=f"error: {str(e)}",
                proof_time=proof_time,
                cvc5_result=None
            )


__all__ = ["CVC5ProverBridge", "CVC5ProofResult", "CVC5_AVAILABLE", "TDFOLToCVC5Converter"]

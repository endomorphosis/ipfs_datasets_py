"""
Lean 4 Interactive Theorem Prover Integration for TDFOL

This module provides integration with Microsoft's Lean 4 theorem prover.

Lean supports:
- Dependent type theory
- Full higher-order logic
- Interactive proof development
- Extensive mathlib
- Tactic-based proving

Usage:
    >>> from ipfs_datasets_py.logic.external_provers import LeanProverBridge
    >>> prover = LeanProverBridge()
    >>> result = prover.prove(formula, timeout=30.0)
    >>> if result.is_proved():
    ...     print("Formula is valid!")
"""

from dataclasses import dataclass
from typing import List, Optional
import subprocess
import shutil
import time
import tempfile
import os

# Check Lean availability
LEAN_AVAILABLE = shutil.which("lean") is not None or shutil.which("lake") is not None


@dataclass
class LeanProofResult:
    """Result from Lean prover.
    
    Attributes:
        is_valid: True if formula was proved
        proof_script: Lean proof script used
        lean_output: Output from Lean
        reason: Reason for the result (proved/failed/timeout/error)
        proof_time: Time taken (seconds)
    """
    is_valid: bool
    proof_script: Optional[str]
    lean_output: Optional[str]
    reason: str
    proof_time: float
    
    def is_proved(self) -> bool:
        """Check if the formula was successfully proved."""
        return self.is_valid


class TDFOLToLeanConverter:
    """Convert TDFOL formulas to Lean 4 notation.
    
    This converter translates TDFOL formulas into Lean's logical
    syntax, which can then be proved using Lean tactics.
    """
    
    def __init__(self):
        """Initialize the converter."""
        pass
    
    def convert(self, formula) -> str:
        """Convert a TDFOL formula to Lean 4 notation.
        
        Args:
            formula: TDFOL formula object
            
        Returns:
            Lean 4 notation string
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
            return self._convert_deontic(formula)
        elif isinstance(formula, tdfol_core.TemporalFormula):
            return self._convert_temporal(formula)
        else:
            raise ValueError(f"Unsupported formula type: {type(formula)}")
    
    def _convert_term(self, term) -> str:
        """Convert a TDFOL term to Lean notation."""
        from ipfs_datasets_py.logic.TDFOL import tdfol_core
        
        if isinstance(term, tdfol_core.Variable):
            return term.name
        elif isinstance(term, tdfol_core.Constant):
            return term.name
        elif isinstance(term, tdfol_core.FunctionApplication):
            args = " ".join(self._convert_term(arg) for arg in term.args)
            return f"({term.function_symbol} {args})"
        else:
            return str(term)
    
    def _convert_predicate(self, pred) -> str:
        """Convert a predicate to Lean notation."""
        if not pred.args:
            return pred.name
        args = " ".join(self._convert_term(arg) for arg in pred.args)
        return f"({pred.name} {args})"
    
    def _convert_binary(self, formula) -> str:
        """Convert a binary formula to Lean notation."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import LogicOperator
        
        left = self.convert(formula.left)
        right = self.convert(formula.right)
        
        op_map = {
            LogicOperator.AND: "∧",
            LogicOperator.OR: "∨",
            LogicOperator.IMPLIES: "→",
            LogicOperator.IFF: "↔",
        }
        
        op = op_map.get(formula.operator, str(formula.operator))
        return f"({left} {op} {right})"
    
    def _convert_unary(self, formula) -> str:
        """Convert a unary formula to Lean notation."""
        inner = self.convert(formula.formula)
        return f"(¬ {inner})"
    
    def _convert_quantified(self, formula) -> str:
        """Convert a quantified formula to Lean notation."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Quantifier
        
        var = formula.variable.name
        body = self.convert(formula.formula)
        
        if formula.quantifier == Quantifier.FORALL:
            return f"(∀ {var}, {body})"
        else:  # EXISTS
            return f"(∃ {var}, {body})"
    
    def _convert_deontic(self, formula) -> str:
        """Convert a deontic formula to Lean notation.
        
        Deontic operators are represented as predicates in Lean.
        """
        inner = self.convert(formula.formula)
        op_name = f"Deontic_{formula.operator.value}"
        return f"({op_name} {inner})"
    
    def _convert_temporal(self, formula) -> str:
        """Convert a temporal formula to Lean notation.
        
        Temporal operators are represented as predicates in Lean.
        """
        inner = self.convert(formula.formula)
        op_name = f"Temporal_{formula.operator.value}"
        return f"({op_name} {inner})"


class LeanProverBridge:
    """Bridge between TDFOL and Lean 4 theorem prover.
    
    This class provides a high-level interface to Lean for proving TDFOL formulas.
    It generates Lean proof scripts and executes them using lean.
    
    Attributes:
        timeout: Default timeout in seconds
        auto_tactics: List of automatic tactics to try
        enable_cache: Whether to cache proof results
    """
    
    def __init__(
        self,
        timeout: Optional[float] = None,
        auto_tactics: Optional[List[str]] = None,
        enable_cache: bool = True
    ):
        """Initialize Lean prover bridge.
        
        Args:
            timeout: Default timeout in seconds (None = no timeout)
            auto_tactics: List of tactics to try (default: ["trivial", "simp", "tauto"])
            enable_cache: Whether to enable proof caching
        """
        if not LEAN_AVAILABLE:
            raise ImportError("Lean is not available. Install from: https://leanprover.github.io/")
        
        self.timeout = timeout or 30.0
        self.auto_tactics = auto_tactics or ["trivial", "simp", "tauto", "decide"]
        self.enable_cache = enable_cache
        self.converter = TDFOLToLeanConverter()
        
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
    ) -> LeanProofResult:
        """Prove a TDFOL formula using Lean.
        
        Args:
            formula: TDFOL formula to prove
            axioms: Optional list of axiom formulas
            timeout: Timeout in seconds (overrides default)
            
        Returns:
            LeanProofResult with proof status and details
        """
        # Check cache first
        if self.enable_cache and self._cache is not None:
            cached_result = self._cache.get(
                formula,
                axioms=axioms,
                prover_name="Lean",
                prover_config={'timeout': timeout}
            )
            if cached_result is not None:
                return cached_result
        
        start_time = time.time()
        
        try:
            # Convert formula and axioms to Lean notation
            lean_formula = self.converter.convert(formula)
            
            # Generate Lean proof script
            script = self._generate_proof_script(formula, axioms, lean_formula)
            
            # Execute the proof script
            result = self._execute_lean_script(script, timeout or self.timeout)
            
            proof_time = time.time() - start_time
            
            # Parse result
            if result["success"]:
                proof_result = LeanProofResult(
                    is_valid=True,
                    proof_script=script,
                    lean_output=result["output"],
                    reason="proved",
                    proof_time=proof_time
                )
                
                # Cache successful result
                if self.enable_cache and self._cache is not None:
                    self._cache.set(formula, proof_result, axioms=axioms, prover_name="Lean", prover_config={'timeout': timeout})
                
                return proof_result
            else:
                return LeanProofResult(
                    is_valid=False,
                    proof_script=script,
                    lean_output=result["output"],
                    reason="failed",
                    proof_time=proof_time
                )
        
        except subprocess.TimeoutExpired:
            proof_time = time.time() - start_time
            return LeanProofResult(
                is_valid=False,
                proof_script=None,
                lean_output=None,
                reason="timeout",
                proof_time=proof_time
            )
        except Exception as e:
            proof_time = time.time() - start_time
            return LeanProofResult(
                is_valid=False,
                proof_script=None,
                lean_output=str(e),
                reason=f"error: {str(e)}",
                proof_time=proof_time
            )
    
    def _generate_proof_script(self, formula, axioms: Optional[List], lean_formula: str) -> str:
        """Generate a Lean proof script.
        
        Args:
            formula: Original TDFOL formula
            axioms: Optional axioms
            lean_formula: Converted Lean formula string
            
        Returns:
            Lean proof script
        """
        script_lines = []
        
        # Add necessary imports
        script_lines.append("import Std.Logic")
        script_lines.append("")
        
        # Add axioms as variables
        if axioms:
            for i, axiom in enumerate(axioms):
                lean_axiom = self.converter.convert(axiom)
                script_lines.append(f"variable (axiom_{i} : {lean_axiom})")
            script_lines.append("")
        
        # Add theorem to prove
        script_lines.append(f"theorem goal : {lean_formula} := by")
        
        # Try automatic tactics
        for tactic in self.auto_tactics:
            script_lines.append(f"  try {tactic}")
        
        # Note: If automatic tactics don't solve the goal, the theorem will fail
        # to compile. This is the expected behavior for production use.
        # For testing/development, you can add 'sorry' to admit unsolved goals.
        script_lines.append("")
        
        return "\n".join(script_lines)
    
    def _execute_lean_script(self, script: str, timeout: float) -> dict:
        """Execute a Lean proof script.
        
        Args:
            script: Lean proof script
            timeout: Timeout in seconds
            
        Returns:
            Dict with 'success' (bool) and 'output' (str)
        """
        # Write script to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lean', delete=False) as f:
            f.write(script)
            script_file = f.name
        
        try:
            # Execute with lean compiler
            if shutil.which("lean"):
                result = subprocess.run(
                    ["lean", script_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
            elif shutil.which("lake"):
                # If only lake is available, try using it
                result = subprocess.run(
                    ["lake", "env", "lean", script_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
            else:
                raise FileNotFoundError("Neither lean nor lake found in PATH")
            
            # Check if proof succeeded
            output = result.stdout + result.stderr
            success = (result.returncode == 0 and 
                      "error:" not in output.lower() and
                      "sorry" not in output.lower())
            
            return {"success": success, "output": output}
        
        finally:
            # Clean up temporary file
            try:
                os.unlink(script_file)
                # Also clean up .olean file if it exists
                olean_file = script_file.replace('.lean', '.olean')
                if os.path.exists(olean_file):
                    os.unlink(olean_file)
            except OSError:
                # Files may not exist or already deleted - this is fine
                pass


__all__ = ["LeanProverBridge", "LeanProofResult", "LEAN_AVAILABLE", "TDFOLToLeanConverter"]

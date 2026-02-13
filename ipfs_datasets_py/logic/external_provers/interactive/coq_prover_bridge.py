"""
Coq Proof Assistant Integration for TDFOL

This module provides integration with INRIA's Coq proof assistant.

Coq supports:
- Calculus of Inductive Constructions
- Higher-order logic
- Interactive proof development
- Large standard library
- Proof extraction to code

Usage:
    >>> from ipfs_datasets_py.logic.external_provers import CoqProverBridge
    >>> prover = CoqProverBridge()
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

# Check Coq availability
COQ_AVAILABLE = shutil.which("coqc") is not None or shutil.which("coqtop") is not None


@dataclass
class CoqProofResult:
    """Result from Coq prover.
    
    Attributes:
        is_valid: True if formula was proved
        proof_script: Coq proof script used
        coq_output: Output from Coq
        reason: Reason for the result (proved/failed/timeout/error)
        proof_time: Time taken (seconds)
    """
    is_valid: bool
    proof_script: Optional[str]
    coq_output: Optional[str]
    reason: str
    proof_time: float
    
    def is_proved(self) -> bool:
        """Check if the formula was successfully proved."""
        return self.is_valid


class TDFOLToCoqConverter:
    """Convert TDFOL formulas to Coq notation.
    
    This converter translates TDFOL formulas into Coq's logical
    syntax, which can then be proved using Coq tactics.
    """
    
    def __init__(self):
        """Initialize the converter."""
        pass
    
    def convert(self, formula) -> str:
        """Convert a TDFOL formula to Coq notation.
        
        Args:
            formula: TDFOL formula object
            
        Returns:
            Coq notation string
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
        """Convert a TDFOL term to Coq notation."""
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
        """Convert a predicate to Coq notation."""
        if not pred.args:
            return pred.name
        args = " ".join(self._convert_term(arg) for arg in pred.args)
        return f"({pred.name} {args})"
    
    def _convert_binary(self, formula) -> str:
        """Convert a binary formula to Coq notation."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import LogicOperator
        
        left = self.convert(formula.left)
        right = self.convert(formula.right)
        
        op_map = {
            LogicOperator.AND: "/\\",
            LogicOperator.OR: "\\/",
            LogicOperator.IMPLIES: "->",
            LogicOperator.IFF: "<->",
        }
        
        op = op_map.get(formula.operator, str(formula.operator))
        return f"({left} {op} {right})"
    
    def _convert_unary(self, formula) -> str:
        """Convert a unary formula to Coq notation."""
        inner = self.convert(formula.formula)
        return f"(~ {inner})"
    
    def _convert_quantified(self, formula) -> str:
        """Convert a quantified formula to Coq notation."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Quantifier
        
        var = formula.variable.name
        body = self.convert(formula.formula)
        
        if formula.quantifier == Quantifier.FORALL:
            return f"(forall {var}, {body})"
        else:  # EXISTS
            return f"(exists {var}, {body})"
    
    def _convert_deontic(self, formula) -> str:
        """Convert a deontic formula to Coq notation.
        
        Deontic operators are represented as predicates in Coq.
        """
        inner = self.convert(formula.formula)
        op_name = f"Deontic_{formula.operator.value}"
        return f"({op_name} {inner})"
    
    def _convert_temporal(self, formula) -> str:
        """Convert a temporal formula to Coq notation.
        
        Temporal operators are represented as predicates in Coq.
        """
        inner = self.convert(formula.formula)
        op_name = f"Temporal_{formula.operator.value}"
        return f"({op_name} {inner})"


class CoqProverBridge:
    """Bridge between TDFOL and Coq proof assistant.
    
    This class provides a high-level interface to Coq for proving TDFOL formulas.
    It generates Coq proof scripts and executes them using coqtop.
    
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
        """Initialize Coq prover bridge.
        
        Args:
            timeout: Default timeout in seconds (None = no timeout)
            auto_tactics: List of tactics to try (default: ["auto", "intuition", "tauto"])
            enable_cache: Whether to enable proof caching
        """
        if not COQ_AVAILABLE:
            raise ImportError("Coq is not available. Install via opam: opam install coq")
        
        self.timeout = timeout or 30.0
        self.auto_tactics = auto_tactics or ["auto", "intuition", "tauto", "firstorder"]
        self.enable_cache = enable_cache
        self.converter = TDFOLToCoqConverter()
        
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
    ) -> CoqProofResult:
        """Prove a TDFOL formula using Coq.
        
        Args:
            formula: TDFOL formula to prove
            axioms: Optional list of axiom formulas
            timeout: Timeout in seconds (overrides default)
            
        Returns:
            CoqProofResult with proof status and details
        """
        # Check cache first
        if self.enable_cache and self._cache is not None:
            cached_result = self._cache.get(
                formula,
                axioms=axioms,
                prover_name="Coq",
                prover_config={'timeout': timeout}
            )
            if cached_result is not None:
                return cached_result
        
        start_time = time.time()
        
        try:
            # Convert formula and axioms to Coq notation
            coq_formula = self.converter.convert(formula)
            
            # Generate Coq proof script
            script = self._generate_proof_script(formula, axioms, coq_formula)
            
            # Execute the proof script
            result = self._execute_coq_script(script, timeout or self.timeout)
            
            proof_time = time.time() - start_time
            
            # Parse result
            if result["success"]:
                proof_result = CoqProofResult(
                    is_valid=True,
                    proof_script=script,
                    coq_output=result["output"],
                    reason="proved",
                    proof_time=proof_time
                )
                
                # Cache successful result
                if self.enable_cache and self._cache is not None:
                    self._cache.set(formula, proof_result, axioms=axioms, prover_name="Coq", prover_config={'timeout': timeout})
                
                return proof_result
            else:
                return CoqProofResult(
                    is_valid=False,
                    proof_script=script,
                    coq_output=result["output"],
                    reason="failed",
                    proof_time=proof_time
                )
        
        except subprocess.TimeoutExpired:
            proof_time = time.time() - start_time
            return CoqProofResult(
                is_valid=False,
                proof_script=None,
                coq_output=None,
                reason="timeout",
                proof_time=proof_time
            )
        except Exception as e:
            proof_time = time.time() - start_time
            return CoqProofResult(
                is_valid=False,
                proof_script=None,
                coq_output=str(e),
                reason=f"error: {str(e)}",
                proof_time=proof_time
            )
    
    def _generate_proof_script(self, formula, axioms: Optional[List], coq_formula: str) -> str:
        """Generate a Coq proof script.
        
        Args:
            formula: Original TDFOL formula
            axioms: Optional axioms
            coq_formula: Converted Coq formula string
            
        Returns:
            Coq proof script
        """
        script_lines = []
        
        # Add any necessary imports
        script_lines.append("Require Import Coq.Logic.Classical.")
        script_lines.append("Require Import Coq.Logic.Classical_Prop.")
        script_lines.append("")
        
        # Add axioms as hypotheses
        if axioms:
            for i, axiom in enumerate(axioms):
                coq_axiom = self.converter.convert(axiom)
                script_lines.append(f"Hypothesis axiom_{i}: {coq_axiom}.")
            script_lines.append("")
        
        # Add theorem to prove
        script_lines.append(f"Theorem goal: {coq_formula}.")
        script_lines.append("Proof.")
        
        # Try automatic tactics
        for tactic in self.auto_tactics:
            script_lines.append(f"  try {tactic}.")
        
        # Note: if automatic tactics do not solve the goal, 'Qed.' will fail and
        # Coq will report remaining subgoals (no implicit admit/Admitted fallback).
        script_lines.append("Qed.")
        script_lines.append("")
        
        return "\n".join(script_lines)
    
    def _execute_coq_script(self, script: str, timeout: float) -> dict:
        """Execute a Coq proof script.
        
        Args:
            script: Coq proof script
            timeout: Timeout in seconds
            
        Returns:
            Dict with 'success' (bool) and 'output' (str)
        """
        # Write script to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.v', delete=False) as f:
            f.write(script)
            script_file = f.name
        
        try:
            # Try coqc first (batch compiler)
            if shutil.which("coqc"):
                result = subprocess.run(
                    ["coqc", script_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
            # Fall back to coqtop (interactive)
            elif shutil.which("coqtop"):
                result = subprocess.run(
                    ["coqtop", "-batch", "-load-vernac-source", script_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
            else:
                raise FileNotFoundError("Neither coqc nor coqtop found in PATH")
            
            # Check if proof succeeded
            output = result.stdout + result.stderr
            success = (result.returncode == 0 and 
                      "Error" not in output and 
                      "Anomaly" not in output)
            
            return {"success": success, "output": output}
        
        finally:
            # Clean up temporary file
            try:
                os.unlink(script_file)
                # Also clean up .vo and .glob files if they exist
                os.unlink(script_file.replace('.v', '.vo'))
                os.unlink(script_file.replace('.v', '.glob'))
            except OSError:
                # Files may not exist or already deleted - this is fine
                pass


__all__ = ["CoqProverBridge", "CoqProofResult", "COQ_AVAILABLE", "TDFOLToCoqConverter"]

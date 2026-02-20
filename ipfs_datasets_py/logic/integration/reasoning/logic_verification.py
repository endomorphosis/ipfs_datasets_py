"""
Logic Verification Module

This module provides verification and proof support for logical formulas
using SymbolicAI integration and automated reasoning capabilities.

Features:
- Formula consistency checking
- Logical entailment verification
- Basic proof generation and validation
- Axiom management and rule application
- Semantic satisfiability checking

Note: Refactored from 879 LOC to <600 LOC. Types and utilities extracted to
separate modules for better maintainability.
"""

import logging
import re
from typing import Dict, List, Optional, Union, Any, Tuple, Set
try:
    from beartype import beartype  # type: ignore
except Exception:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func
from typing import TYPE_CHECKING

# Import types from refactored modules
from .logic_verification_types import (
    VerificationResult,
    LogicAxiom,
    ProofStep,
    ProofResult,
    ConsistencyCheck,
    EntailmentResult,
)
from .logic_verification_utils import (
    get_basic_axioms,
    get_basic_proof_rules,
    validate_formula_syntax,
    parse_proof_steps,
    are_contradictory,
)
from ._logic_verifier_backends_mixin import LogicVerifierBackendsMixin

if TYPE_CHECKING:
    from symai import Symbol

logger = logging.getLogger(__name__)

# Fallback imports when SymbolicAI is not available
try:
    from symai import Symbol, Expression
    SYMBOLIC_AI_AVAILABLE = True
except (ImportError, SystemExit):
    SYMBOLIC_AI_AVAILABLE = False
    logger.warning("SymbolicAI not available. Logic verification will use fallback methods.")
    
    # Create mock classes for development/testing without SymbolicAI
    class Symbol:
        def __init__(self, value: str, semantic: bool = False):
            self.value = value
            self._semantic = semantic
            
        def query(self, prompt: str) -> str:
            return f"Mock response for: {prompt}"
    
    class Expression:
        pass


class LogicVerifier(LogicVerifierBackendsMixin):
    """Verify and reason about logical formulas using SymbolicAI."""
    
    def __init__(self, use_symbolic_ai: bool = True, fallback_enabled: bool = True):
        """
        Initialize the logic verifier.
        
        Args:
            use_symbolic_ai: Whether to use SymbolicAI for enhanced verification
            fallback_enabled: Whether to allow fallback methods when SymbolicAI fails
        """
        self.use_symbolic_ai = use_symbolic_ai and SYMBOLIC_AI_AVAILABLE
        self.fallback_enabled = bool(fallback_enabled)
        self.known_axioms: List[LogicAxiom] = []
        self.proof_cache: Dict[str, ProofResult] = {}
        
        # Initialize with basic logical axioms
        self._initialize_basic_axioms()
        
        logger.info(f"LogicVerifier initialized with SymbolicAI: {self.use_symbolic_ai}")
    
    def _initialize_basic_axioms(self):
        """Initialize the verifier with basic logical axioms."""
        self.known_axioms.extend(get_basic_axioms())
    
    @beartype
    def add_axiom(self, axiom: LogicAxiom) -> bool:
        """
        Add a new axiom to the knowledge base.
        
        Args:
            axiom: The axiom to add
            
        Returns:
            True if axiom was added successfully
        """
        # Check if axiom already exists
        existing = [a for a in self.known_axioms if a.name == axiom.name]
        if existing:
            logger.warning(f"Axiom {axiom.name} already exists. Skipping.")
            return False
        
        # Validate axiom formula (basic syntax check)
        if not validate_formula_syntax(axiom.formula):
            logger.error(f"Invalid formula syntax in axiom {axiom.name}: {axiom.formula}")
            return False
        
        self.known_axioms.append(axiom)
        logger.info(f"Added axiom: {axiom.name}")
        return True
    
    @beartype
    def check_consistency(self, formulas: List[str]) -> ConsistencyCheck:
        """
        Check if a set of formulas is logically consistent.
        
        Args:
            formulas: List of logical formulas to check
            
        Returns:
            ConsistencyCheck result
        """
        if not formulas:
            return ConsistencyCheck(
                is_consistent=True,
                confidence=1.0,
                explanation="Empty set of formulas is trivially consistent"
            )
        
        if self.use_symbolic_ai:
            return self._check_consistency_symbolic(formulas)
        else:
            return self._check_consistency_fallback(formulas)
    
    @beartype
    def check_entailment(self, premises: List[str], conclusion: str) -> EntailmentResult:
        """
        Check if premises logically entail the conclusion.
        
        Args:
            premises: List of premise formulas
            conclusion: The conclusion formula
            
        Returns:
            EntailmentResult indicating whether entailment holds
        """
        if not premises:
            return EntailmentResult(
                entails=False,
                premises=premises,
                conclusion=conclusion,
                confidence=1.0,
                explanation="No premises provided"
            )
        
        if self.use_symbolic_ai:
            return self._check_entailment_symbolic(premises, conclusion)
        else:
            return self._check_entailment_fallback(premises, conclusion)
    
    @beartype
    def generate_proof(self, premises: List[str], conclusion: str) -> ProofResult:
        """
        Attempt to generate a proof from premises to conclusion.
        
        Args:
            premises: List of premise formulas
            conclusion: The conclusion to prove
            
        Returns:
            ProofResult with proof steps if successful
        """
        import time
        start_time = time.time()
        
        # Check cache first
        cache_key = f"{','.join(premises)} ⊢ {conclusion}"
        if cache_key in self.proof_cache:
            cached_result = self.proof_cache[cache_key]
            logger.info("Using cached proof result")
            return cached_result
        
        if self.use_symbolic_ai:
            result = self._generate_proof_symbolic(premises, conclusion)
        else:
            result = self._generate_proof_fallback(premises, conclusion)
        
        result.time_taken = time.time() - start_time
        
        # Cache the result
        self.proof_cache[cache_key] = result
        
        return result
    
    @beartype
    def verify_formula_syntax(self, formula: str) -> Dict[str, Any]:
        """
        Verify the syntax of a logical formula.

        Args:
            formula: Logical formula to validate

        Returns:
            Dictionary with validation status and details
        """
        result: Dict[str, Any] = {
            "formula": formula,
            "status": "unknown",
            "errors": [],
            "method": "fallback"
        }

        if not formula or not formula.strip():
            result["status"] = "invalid"
            result["errors"].append("Formula is empty")
            return result

        if self.use_symbolic_ai:
            try:
                symbol = Symbol(formula, semantic=True)
                query = symbol.query(
                    "Check whether this is a well-formed logical formula. "
                    "Respond with: valid, invalid, or unknown."
                )
                response = getattr(query, "value", str(query)).lower()
                if "valid" in response and "invalid" not in response:
                    result["status"] = "valid"
                elif "invalid" in response:
                    result["status"] = "invalid"
                else:
                    result["status"] = "unknown"
                # Only treat the LLM answer as authoritative when it commits to
                # valid/invalid. If it returns unknown, fall back to local checks.
                if result["status"] != "unknown":
                    result["method"] = "symbolic_ai"
                    return result
            except Exception as exc:
                logger.warning("SymbolicAI syntax check failed: %s", exc)

        is_valid = validate_formula_syntax(formula)
        result["status"] = "valid" if is_valid else "invalid"
        if not is_valid:
            result["errors"].append("Unbalanced parentheses or empty formula")
        return result

    @beartype
    def check_satisfiability(self, formula: str) -> Dict[str, Any]:
        """
        Check whether a formula is satisfiable.

        Args:
            formula: Logical formula to analyze

        Returns:
            Dictionary with satisfiability result
        """
        result: Dict[str, Any] = {
            "formula": formula,
            "satisfiable": None,
            "status": "unknown",
            "method": "fallback"
        }

        if not formula or not formula.strip():
            result["satisfiable"] = False
            result["status"] = "invalid"
            return result

        if self.use_symbolic_ai:
            try:
                symbol = Symbol(formula, semantic=True)
                query = symbol.query(
                    "Is this logical formula satisfiable? "
                    "Respond with: satisfiable, unsatisfiable, or unknown."
                )
                response = getattr(query, "value", str(query)).lower()
                if "unsatisfiable" in response:
                    result["satisfiable"] = False
                    result["status"] = "unsatisfiable"
                elif "satisfiable" in response:
                    result["satisfiable"] = True
                    result["status"] = "satisfiable"
                else:
                    result["status"] = "unknown"
                # Same as syntax: if the model is non-committal, fall back.
                if result["status"] != "unknown" and result["satisfiable"] is not None:
                    result["method"] = "symbolic_ai"
                    return result
            except Exception as exc:
                logger.warning("SymbolicAI satisfiability check failed: %s", exc)

        normalized = formula.replace(" ", "")
        if "P∧¬P" in normalized or "¬P∧P" in normalized:
            result["satisfiable"] = False
            result["status"] = "unsatisfiable"
            return result

        result["satisfiable"] = True
        result["status"] = "assumed_satisfiable"
        return result

    @beartype
    def check_validity(self, formula: str) -> Dict[str, Any]:
        """
        Check whether a formula is logically valid.

        Args:
            formula: Logical formula to analyze

        Returns:
            Dictionary with validity result
        """
        result: Dict[str, Any] = {
            "formula": formula,
            "valid": None,
            "status": "unknown",
            "method": "fallback"
        }

        if not formula or not formula.strip():
            result["valid"] = False
            result["status"] = "invalid"
            return result

        if self.use_symbolic_ai:
            try:
                symbol = Symbol(formula, semantic=True)
                query = symbol.query(
                    "Is this logical formula valid (true in all models)? "
                    "Respond with: valid, invalid, or unknown."
                )
                response = getattr(query, "value", str(query)).lower()
                if "valid" in response and "invalid" not in response:
                    result["valid"] = True
                    result["status"] = "valid"
                elif "invalid" in response:
                    result["valid"] = False
                    result["status"] = "invalid"
                else:
                    result["status"] = "unknown"
                result["method"] = "symbolic_ai"
                return result
            except Exception as exc:
                logger.warning("SymbolicAI validity check failed: %s", exc)

        normalized = formula.replace(" ", "")
        if "P∨¬P" in normalized or "¬P∨P" in normalized:
            result["valid"] = True
            result["status"] = "tautology"
            return result

        result["valid"] = False
        result["status"] = "unknown"
        return result

    def _initialize_proof_rules(self) -> List[Dict[str, str]]:
        """Initialize core proof rules for fallback reasoning."""
        # Get basic rules and add additional rules
        rules = get_basic_proof_rules()
        rules.extend([
            {"name": "and_introduction", "description": "From P and Q, infer P ∧ Q"},
            {"name": "and_elimination", "description": "From P ∧ Q, infer P (or Q)"},
            {"name": "or_introduction", "description": "From P, infer P ∨ Q"},
            {"name": "double_negation", "description": "From P, infer ¬¬P"}
        ])
        return rules
    
    # Use utility function for contradiction check (removed _are_contradictory)
    
    @beartype
    def get_axioms(self, axiom_type: Optional[str] = None) -> List[LogicAxiom]:
        """
        Get axioms, optionally filtered by type.
        
        Args:
            axiom_type: Optional type filter ('built_in', 'user_defined', 'derived')
            
        Returns:
            List of matching axioms
        """
        if axiom_type is None:
            return self.known_axioms.copy()
        
        return [axiom for axiom in self.known_axioms if axiom.axiom_type == axiom_type]
    
    def clear_cache(self):
        """Clear the proof cache."""
        self.proof_cache.clear()
        logger.info("Proof cache cleared")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get verifier statistics."""
        return {
            "axiom_count": len(self.known_axioms),
            "axiom_types": {
                axiom_type: len([a for a in self.known_axioms if a.axiom_type == axiom_type])
                for axiom_type in ["built_in", "user_defined", "derived"]
            },
            "proof_cache_size": len(self.proof_cache),
            "symbolic_ai_available": self.use_symbolic_ai
        }

    # ------------------------------------------------------------------
    # Backward-compatibility aliases (private method names used by tests)
    # ------------------------------------------------------------------

    def _validate_formula_syntax(self, formula: str) -> bool:
        """Alias for verify_formula_syntax(); returns True if valid."""
        result = self.verify_formula_syntax(formula)
        return result.get("status") == "valid"

    def _are_contradictory(self, formula1: str, formula2: str) -> bool:
        """Delegate to the module-level are_contradictory() utility."""
        from .logic_verification_utils import are_contradictory
        return are_contradictory(formula1, formula2)

    def verify_consistency(self, formulas):
        """Alias for check_consistency()."""
        return self.check_consistency(formulas)

    def validate_proof(self, steps):
        """Validate a sequence of proof steps."""
        results = []
        for step in steps:
            step_num = getattr(step, 'step_number', getattr(step, 'step_num', 0))
            formula = getattr(step, 'formula', '')
            validation = self.verify_formula_syntax(formula)
            results.append({
                'step': step_num,
                'formula': formula,
                'valid': validation.get('status') == 'valid',
                'justification': getattr(step, 'justification', '')
            })
        return results


# Import convenience functions from utils for backward compatibility
from .logic_verification_utils import (
    verify_consistency,
    verify_entailment,
    generate_proof,
)

# Export key classes and functions
__all__ = [
    'LogicVerifier',
    'LogicAxiom', 
    'ProofStep',
    'ProofResult',
    'ConsistencyCheck',
    'EntailmentResult',
    'VerificationResult',
    'verify_consistency',
    'verify_entailment', 
    'generate_proof',
    'SYMBOLIC_AI_AVAILABLE'
]

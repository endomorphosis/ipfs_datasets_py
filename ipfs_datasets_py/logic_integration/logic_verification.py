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
"""

import logging
import re
from typing import Dict, List, Optional, Union, Any, Tuple, Set
from dataclasses import dataclass, field
from beartype import beartype
from beartype.typing import TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from symai import Symbol

# Configure logging
logging.basicConfig(level=logging.INFO)
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


class VerificationResult(Enum):
    """Enumeration for verification results."""
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class LogicAxiom:
    """Represents a logical axiom or rule."""
    name: str
    formula: str
    description: str
    axiom_type: str = "user_defined"  # user_defined, built_in, derived
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProofStep:
    """Represents a single step in a logical proof."""
    step_number: int
    formula: str
    justification: str
    rule_applied: str
    premises: List[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class ProofResult:
    """Result of a proof attempt."""
    is_valid: bool
    conclusion: str
    steps: List[ProofStep]
    confidence: float
    method_used: str
    time_taken: float = 0.0
    errors: List[str] = field(default_factory=list)


@dataclass
class ConsistencyCheck:
    """Result of consistency checking."""
    is_consistent: bool
    conflicting_formulas: List[Tuple[str, str]] = field(default_factory=list)
    confidence: float = 0.0
    explanation: str = ""
    method_used: str = "fallback"


@dataclass
class EntailmentResult:
    """Result of entailment checking."""
    entails: bool
    premises: List[str]
    conclusion: str
    confidence: float
    counterexample: Optional[Dict[str, Any]] = None
    explanation: str = ""


class LogicVerifier:
    """Verify and reason about logical formulas using SymbolicAI."""
    
    def __init__(self, use_symbolic_ai: bool = True):
        """
        Initialize the logic verifier.
        
        Args:
            use_symbolic_ai: Whether to use SymbolicAI for enhanced verification
        """
        self.use_symbolic_ai = use_symbolic_ai and SYMBOLIC_AI_AVAILABLE
        self.known_axioms: List[LogicAxiom] = []
        self.proof_cache: Dict[str, ProofResult] = {}
        
        # Initialize with basic logical axioms
        self._initialize_basic_axioms()
        
        logger.info(f"LogicVerifier initialized with SymbolicAI: {self.use_symbolic_ai}")
    
    def _initialize_basic_axioms(self):
        """Initialize the verifier with basic logical axioms."""
        basic_axioms = [
            LogicAxiom(
                name="modus_ponens",
                formula="((P → Q) ∧ P) → Q",
                description="Modus Ponens: If P implies Q and P is true, then Q is true",
                axiom_type="built_in"
            ),
            LogicAxiom(
                name="modus_tollens", 
                formula="((P → Q) ∧ ¬Q) → ¬P",
                description="Modus Tollens: If P implies Q and Q is false, then P is false",
                axiom_type="built_in"
            ),
            LogicAxiom(
                name="law_of_excluded_middle",
                formula="P ∨ ¬P",
                description="Law of Excluded Middle: Either P or not P",
                axiom_type="built_in"
            ),
            LogicAxiom(
                name="law_of_noncontradiction",
                formula="¬(P ∧ ¬P)",
                description="Law of Non-contradiction: P and not P cannot both be true",
                axiom_type="built_in"
            ),
            LogicAxiom(
                name="universal_instantiation",
                formula="∀x P(x) → P(a)",
                description="Universal Instantiation: If P holds for all x, then P holds for any specific a",
                axiom_type="built_in"
            ),
            LogicAxiom(
                name="existential_generalization",
                formula="P(a) → ∃x P(x)",
                description="Existential Generalization: If P holds for a specific a, then there exists an x such that P(x)",
                axiom_type="built_in"
            )
        ]
        
        self.known_axioms.extend(basic_axioms)
    
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
        if not self._validate_formula_syntax(axiom.formula):
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
    
    def _check_consistency_symbolic(self, formulas: List[str]) -> ConsistencyCheck:
        """Check consistency using SymbolicAI."""
        try:
            # Create a combined symbol representing all formulas
            combined_formulas = " ∧ ".join(f"({formula})" for formula in formulas)
            symbol = Symbol(combined_formulas, semantic=True)
            
            # Query for consistency
            consistency_query = symbol.query(
                "Are these logical formulas consistent with each other? "
                "Can they all be true at the same time? "
                "Respond with: consistent, inconsistent, or unknown"
            )
            
            result_text = getattr(consistency_query, 'value', str(consistency_query)).lower()
            
            if "consistent" in result_text and "inconsistent" not in result_text:
                is_consistent = True
                confidence = 0.8
                explanation = "SymbolicAI analysis indicates the formulas are consistent"
            elif "inconsistent" in result_text:
                is_consistent = False
                confidence = 0.8
                explanation = "SymbolicAI analysis indicates the formulas are inconsistent"
                
                # Try to find conflicting pairs
                conflicting = self._find_conflicting_pairs_symbolic(formulas)
            else:
                is_consistent = False
                confidence = 0.5
                explanation = "SymbolicAI could not determine consistency"
                conflicting = []
            
            return ConsistencyCheck(
                is_consistent=is_consistent,
                conflicting_formulas=conflicting if not is_consistent else [],
                confidence=confidence,
                explanation=explanation,
                method_used="symbolic_ai"
            )
            
        except Exception as e:
            logger.error(f"Error in symbolic consistency check: {e}")
            return self._check_consistency_fallback(formulas)
    
    def _check_consistency_fallback(self, formulas: List[str]) -> ConsistencyCheck:
        """Fallback consistency checking using basic pattern matching."""
        conflicting_pairs = []
        
        # Simple pattern matching for obvious contradictions
        for i, formula1 in enumerate(formulas):
            for j, formula2 in enumerate(formulas[i+1:], i+1):
                if self._are_contradictory(formula1, formula2):
                    conflicting_pairs.append((formula1, formula2))
        
        is_consistent = len(conflicting_pairs) == 0
        confidence = 0.6 if is_consistent else 0.8  # More confident about contradictions
        
        explanation = (
            "Basic pattern matching found no obvious contradictions" if is_consistent else
            f"Found {len(conflicting_pairs)} potential contradictions"
        )
        
        return ConsistencyCheck(
            is_consistent=is_consistent,
            conflicting_formulas=conflicting_pairs,
            confidence=confidence,
            explanation=explanation,
            method_used="pattern_matching"
        )
    
    def _find_conflicting_pairs_symbolic(self, formulas: List[str]) -> List[Tuple[str, str]]:
        """Find conflicting pairs using SymbolicAI."""
        conflicting = []
        
        for i, formula1 in enumerate(formulas):
            for j, formula2 in enumerate(formulas[i+1:], i+1):
                # Check if the pair is contradictory
                combined = Symbol(f"({formula1}) ∧ ({formula2})", semantic=True)
                contradiction_query = combined.query(
                    "Can these two logical statements both be true at the same time? "
                    "Respond with: yes, no, or unknown"
                )
                
                result = getattr(contradiction_query, 'value', str(contradiction_query)).lower()
                if "no" in result:
                    conflicting.append((formula1, formula2))
        
        return conflicting
    
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
    
    def _check_entailment_symbolic(self, premises: List[str], conclusion: str) -> EntailmentResult:
        """Check entailment using SymbolicAI."""
        try:
            # Create combined premises
            combined_premises = " ∧ ".join(f"({p})" for p in premises)
            entailment_formula = f"({combined_premises}) → ({conclusion})"
            
            symbol = Symbol(entailment_formula, semantic=True)
            
            # Query for entailment
            entailment_query = symbol.query(
                "Is this logical implication valid? "
                "Do the premises logically entail the conclusion? "
                "Respond with: yes, no, or unknown"
            )
            
            result_text = getattr(entailment_query, 'value', str(entailment_query)).lower()
            
            if "yes" in result_text:
                entails = True
                confidence = 0.8
                explanation = "SymbolicAI analysis confirms the entailment"
            elif "no" in result_text:
                entails = False
                confidence = 0.8
                explanation = "SymbolicAI analysis rejects the entailment"
            else:
                entails = False
                confidence = 0.5
                explanation = "SymbolicAI could not determine entailment"
            
            return EntailmentResult(
                entails=entails,
                premises=premises,
                conclusion=conclusion,
                confidence=confidence,
                explanation=explanation
            )
            
        except Exception as e:
            logger.error(f"Error in symbolic entailment check: {e}")
            return self._check_entailment_fallback(premises, conclusion)
    
    def _check_entailment_fallback(self, premises: List[str], conclusion: str) -> EntailmentResult:
        """Fallback entailment checking using basic rules."""
        # Very basic entailment checking using known patterns
        entails = False
        confidence = 0.4
        explanation = "Basic pattern matching used"
        
        # Check for simple modus ponens pattern
        for premise in premises:
            if "→" in premise and conclusion in premise:
                # If premise is "P → Q" and conclusion is "Q", check if "P" is also a premise
                parts = premise.split("→")
                if len(parts) == 2:
                    antecedent = parts[0].strip()
                    consequent = parts[1].strip()
                    
                    if consequent == conclusion and antecedent in premises:
                        entails = True
                        confidence = 0.8
                        explanation = "Modus ponens pattern detected"
                        break
        
        return EntailmentResult(
            entails=entails,
            premises=premises,
            conclusion=conclusion,
            confidence=confidence,
            explanation=explanation
        )
    
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
    
    def _generate_proof_symbolic(self, premises: List[str], conclusion: str) -> ProofResult:
        """Generate proof using SymbolicAI."""
        try:
            # Create a symbol representing the proof problem
            premises_text = ", ".join(premises)
            proof_prompt = f"Given premises: {premises_text}. Prove: {conclusion}"
            
            symbol = Symbol(proof_prompt, semantic=True)
            
            # Query for proof steps
            proof_query = symbol.query(
                "Generate a logical proof with step-by-step reasoning. "
                "For each step, provide: step number, formula, and justification. "
                "Format as: Step 1: [formula] (justification)"
            )
            
            proof_text = getattr(proof_query, 'value', str(proof_query))
            
            # Parse the proof steps
            steps = self._parse_proof_steps(proof_text)
            
            # Validate the proof
            is_valid = len(steps) > 0 and steps[-1].formula == conclusion
            confidence = 0.7 if is_valid else 0.3
            
            return ProofResult(
                is_valid=is_valid,
                conclusion=conclusion,
                steps=steps,
                confidence=confidence,
                method_used="symbolic_ai"
            )
            
        except Exception as e:
            logger.error(f"Error in symbolic proof generation: {e}")
            return self._generate_proof_fallback(premises, conclusion)
    
    def _generate_proof_fallback(self, premises: List[str], conclusion: str) -> ProofResult:
        """Generate proof using fallback methods."""
        steps = []
        
        # Add premises as initial steps
        for i, premise in enumerate(premises):
            steps.append(ProofStep(
                step_number=i + 1,
                formula=premise,
                justification="Given premise",
                rule_applied="premise"
            ))
        
        # Try simple modus ponens
        for premise in premises:
            if "→" in premise:
                parts = premise.split("→")
                if len(parts) == 2:
                    antecedent = parts[0].strip()
                    consequent = parts[1].strip()
                    
                    if antecedent in premises and consequent == conclusion:
                        steps.append(ProofStep(
                            step_number=len(steps) + 1,
                            formula=conclusion,
                            justification=f"Modus ponens from '{antecedent}' and '{premise}'",
                            rule_applied="modus_ponens",
                            premises=[antecedent, premise]
                        ))
                        
                        return ProofResult(
                            is_valid=True,
                            conclusion=conclusion,
                            steps=steps,
                            confidence=0.8,
                            method_used="fallback_modus_ponens"
                        )
        
        # If no proof found
        return ProofResult(
            is_valid=False,
            conclusion=conclusion,
            steps=steps,
            confidence=0.1,
            method_used="fallback_failed",
            errors=["Could not generate proof with available fallback methods"]
        )
    
    def _parse_proof_steps(self, proof_text: str) -> List[ProofStep]:
        """Parse proof steps from text."""
        steps = []
        lines = proof_text.split('\n')
        
        step_pattern = r'Step\s+(\d+):\s*(.+?)\s*\((.+?)\)'
        
        for line in lines:
            match = re.search(step_pattern, line, re.IGNORECASE)
            if match:
                step_num = int(match.group(1))
                formula = match.group(2).strip()
                justification = match.group(3).strip()
                
                steps.append(ProofStep(
                    step_number=step_num,
                    formula=formula,
                    justification=justification,
                    rule_applied="symbolic_reasoning"
                ))
        
        return steps
    
    def _validate_formula_syntax(self, formula: str) -> bool:
        """Basic validation of formula syntax."""
        if not formula or not formula.strip():
            return False
        
        # Check for balanced parentheses
        paren_count = 0
        for char in formula:
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
            if paren_count < 0:
                return False
        
        return paren_count == 0

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
                result["method"] = "symbolic_ai"
                return result
            except Exception as exc:
                logger.warning("SymbolicAI syntax check failed: %s", exc)

        is_valid = self._validate_formula_syntax(formula)
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
        return [
            {"name": "modus_ponens", "description": "If P → Q and P, then Q"},
            {"name": "modus_tollens", "description": "If P → Q and ¬Q, then ¬P"},
            {"name": "and_introduction", "description": "From P and Q, infer P ∧ Q"},
            {"name": "and_elimination", "description": "From P ∧ Q, infer P (or Q)"},
            {"name": "or_introduction", "description": "From P, infer P ∨ Q"},
            {"name": "double_negation", "description": "From P, infer ¬¬P"}
        ]
    
    def _are_contradictory(self, formula1: str, formula2: str) -> bool:
        """Check if two formulas are obviously contradictory."""
        # Very basic contradiction detection
        # This is a simplified version - real implementation would be more sophisticated
        
        # Check for direct negation
        if formula1.startswith('¬') and formula1[1:].strip() == formula2.strip():
            return True
        if formula2.startswith('¬') and formula2[1:].strip() == formula1.strip():
            return True
        
        # Check for patterns like "P" and "¬P"
        f1_clean = formula1.strip()
        f2_clean = formula2.strip()
        
        if f1_clean.startswith('¬') and f1_clean[1:].strip() == f2_clean:
            return True
        if f2_clean.startswith('¬') and f2_clean[1:].strip() == f1_clean:
            return True
        
        return False
    
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


# Convenience functions for quick verification
@beartype
def verify_consistency(formulas: List[str]) -> ConsistencyCheck:
    """
    Quick consistency check for a list of formulas.
    
    Args:
        formulas: List of logical formulas
        
    Returns:
        ConsistencyCheck result
    """
    verifier = LogicVerifier()
    return verifier.check_consistency(formulas)


@beartype
def verify_entailment(premises: List[str], conclusion: str) -> EntailmentResult:
    """
    Quick entailment check.
    
    Args:
        premises: List of premise formulas
        conclusion: Conclusion formula
        
    Returns:
        EntailmentResult
    """
    verifier = LogicVerifier()
    return verifier.check_entailment(premises, conclusion)


@beartype
def generate_proof(premises: List[str], conclusion: str) -> ProofResult:
    """
    Quick proof generation.
    
    Args:
        premises: List of premise formulas
        conclusion: Conclusion to prove
        
    Returns:
        ProofResult with proof steps
    """
    verifier = LogicVerifier()
    return verifier.generate_proof(premises, conclusion)


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

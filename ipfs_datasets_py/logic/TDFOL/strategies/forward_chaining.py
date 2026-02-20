"""
Forward chaining strategy for TDFOL theorem proving.

This module implements forward chaining proof strategy, which applies
inference rules to derive new formulas from axioms and theorems until
the goal formula is proved or no further progress can be made.
"""

import logging
import time
from typing import List, Set

from .base import ProverStrategy, StrategyType, ProofStep
from ..tdfol_core import Formula, TDFOLKnowledgeBase
from ..tdfol_prover import ProofResult, ProofStatus

logger = logging.getLogger(__name__)


class ForwardChainingStrategy(ProverStrategy):
    """
    Forward chaining proof strategy.
    
    This strategy applies inference rules iteratively to derive new formulas
    from the knowledge base. It starts with axioms and theorems, then applies
    all available TDFOL inference rules to generate new formulas until either:
    1. The goal formula is derived (proof succeeds)
    2. No new formulas can be generated (proof fails)
    3. Maximum iterations or timeout is reached
    
    Characteristics:
    - Data-driven: Works forward from known facts
    - Completeness: Complete for Horn clauses
    - Performance: Can be slow for large knowledge bases
    - Best for: Goals that follow naturally from axioms
    
    Example:
        >>> from ipfs_datasets_py.logic.TDFOL import TDFOLKnowledgeBase, Predicate
        >>> strategy = ForwardChainingStrategy(max_iterations=100)
        >>> kb = TDFOLKnowledgeBase()
        >>> kb.add_axiom(Predicate("P", ()))
        >>> formula = Predicate("P", ())
        >>> result = strategy.prove(formula, kb, timeout_ms=5000)
        >>> assert result.is_proved()
    """
    
    def __init__(self, max_iterations: int = 100, max_derived: int = 500):
        """
        Initialize forward chaining strategy.
        
        Args:
            max_iterations: Maximum number of rule application iterations
            max_derived: Maximum number of formulas in the derived set before
                stopping (prevents exponential blowup with rule-rich KBs).
        """
        super().__init__("Forward Chaining", StrategyType.FORWARD_CHAINING)
        self.max_iterations = max_iterations
        self.max_derived = max_derived
        self.tdfol_rules = []
        
        # Load TDFOL inference rules
        try:
            from ..inference_rules import get_all_tdfol_rules
            self.tdfol_rules = get_all_tdfol_rules()
            logger.debug(f"Loaded {len(self.tdfol_rules)} TDFOL rules for forward chaining")
        except Exception as e:
            logger.warning(f"Failed to load TDFOL rules: {e}")
    
    def can_handle(self, formula: Formula, kb: TDFOLKnowledgeBase) -> bool:
        """
        Check if forward chaining can handle this formula.
        
        Forward chaining can handle any formula, but is most effective for
        formulas that can be derived from axioms through rule application.
        
        Args:
            formula: Formula to prove
            kb: Knowledge base
        
        Returns:
            Always True (forward chaining is a general-purpose strategy)
        """
        return True  # Forward chaining is general-purpose
    
    def prove(
        self,
        formula: Formula,
        kb: TDFOLKnowledgeBase,
        timeout_ms: int = 5000
    ) -> ProofResult:
        """
        Prove formula using forward chaining.
        
        Applies TDFOL inference rules iteratively to derive new formulas
        from the knowledge base until the goal is proved or no progress
        can be made.
        
        Args:
            formula: Goal formula to prove
            kb: Knowledge base with axioms and theorems
            timeout_ms: Timeout in milliseconds
        
        Returns:
            ProofResult with status and proof steps
        """
        start_time = time.time()
        
        # Initialize derived set with axioms and theorems
        derived: Set[Formula] = set(kb.axioms + kb.theorems)
        proof_steps: List[ProofStep] = []
        
        # Check if goal is already in derived set
        if formula in derived:
            return ProofResult(
                status=ProofStatus.PROVED,
                formula=formula,
                proof_steps=[ProofStep(
                    formula=formula,
                    justification="Already in knowledge base"
                )],
                time_ms=(time.time() - start_time) * 1000,
                method=self.name
            )
        
        # frontier: formulas added in the last step (only these need new rule applications)
        frontier: Set[Formula] = set(derived)
        
        # Iteratively apply rules until goal is derived or no progress
        for iteration in range(self.max_iterations):
            # Check timeout
            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms > timeout_ms:
                return ProofResult(
                    status=ProofStatus.TIMEOUT,
                    formula=formula,
                    proof_steps=proof_steps,
                    time_ms=elapsed_ms,
                    method=self.name,
                    message=f"Timeout after {iteration} iterations"
                )
            
            # Guard against combinatorial explosion
            if len(derived) >= self.max_derived:
                return ProofResult(
                    status=ProofStatus.UNKNOWN,
                    formula=formula,
                    proof_steps=proof_steps,
                    time_ms=elapsed_ms,
                    method=self.name,
                    message=f"Derived set exceeded {self.max_derived} formulas after {iteration} iterations"
                )
            
            # Check if goal is derived
            if formula in derived:
                return ProofResult(
                    status=ProofStatus.PROVED,
                    formula=formula,
                    proof_steps=proof_steps,
                    time_ms=(time.time() - start_time) * 1000,
                    method=self.name,
                    message=f"Proved in {iteration} iterations"
                )
            
            # Apply rules using frontier (new formulas from last step only)
            # to avoid O(n²) blowup across all formula pairs.
            new_formulas = self._apply_rules(frontier, derived, proof_steps)
            
            # No progress made - stop
            if not new_formulas:
                break
            
            # Add new formulas to derived set; next frontier = only the new ones
            derived.update(new_formulas)
            frontier = new_formulas
        
        # Goal not derived
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=formula,
            proof_steps=proof_steps,
            time_ms=(time.time() - start_time) * 1000,
            method=self.name,
            message=f"Forward chaining exhausted after {self.max_iterations} iterations"
        )
    
    def _apply_rules(
        self,
        frontier: Set[Formula],
        derived: Set[Formula],
        proof_steps: List[ProofStep]
    ) -> Set[Formula]:
        """
        Apply all inference rules to the frontier formulas.
        
        Uses a frontier-based approach: only formulas added in the previous
        step are tried as primary inputs. This avoids the O(n²) blowup that
        occurs when iterating over all pairs of an ever-growing derived set.
        
        Single-formula rules are applied to every frontier formula.
        Two-formula rules are applied between each frontier formula and each
        formula in the full derived set (frontier ∪ already-known), ensuring
        completeness while keeping the inner loop bounded by ``len(derived)``
        (not ``len(derived)²``).
        
        Args:
            frontier: Formulas added in the last iteration (new candidates)
            derived: Complete set of currently known formulas
            proof_steps: List to append proof steps to
        
        Returns:
            Set of newly derived formulas (not already in derived)
        """
        new_formulas: Set[Formula] = set()
        
        # Apply rules with each frontier formula as the primary input
        for current_formula in list(frontier):
            for rule in self.tdfol_rules:
                try:
                    # Try single-formula rules
                    if hasattr(rule, 'can_apply'):
                        if rule.can_apply(current_formula):
                            new_formula = rule.apply(current_formula)
                            if new_formula not in derived:
                                new_formulas.add(new_formula)
                                proof_steps.append(ProofStep(
                                    formula=new_formula,
                                    justification=f"Applied {rule.name}",
                                    rule_name=rule.name,
                                    premises=[current_formula]
                                ))
                    
                    # Two-formula rules: pair frontier formula with every known formula.
                    # Using derived (not frontier×frontier) keeps this O(|frontier|×|derived|).
                    for other_formula in list(derived):
                        if current_formula is other_formula:
                            continue
                        try:
                            if hasattr(rule, 'can_apply'):
                                if rule.can_apply(current_formula, other_formula):
                                    new_formula = rule.apply(current_formula, other_formula)
                                    if new_formula not in derived:
                                        new_formulas.add(new_formula)
                                        proof_steps.append(ProofStep(
                                            formula=new_formula,
                                            justification=f"Applied {rule.name}",
                                            rule_name=rule.name,
                                            premises=[current_formula, other_formula]
                                        ))
                        except (AttributeError, TypeError, ValueError):
                            continue
                
                except (AttributeError, TypeError, ValueError) as e:
                    logger.debug(f"Rule {rule.name} failed: {e}")
                    continue
        
        return new_formulas
    
    def get_priority(self) -> int:
        """
        Get strategy priority.
        
        Forward chaining has high priority (70) as it's a reliable
        general-purpose strategy that works well for many formulas.
        
        Returns:
            Priority value of 70 (high priority)
        """
        return 70  # High priority - reliable general-purpose strategy
    
    def estimate_cost(self, formula: Formula, kb: TDFOLKnowledgeBase) -> float:
        """
        Estimate computational cost.
        
        Cost increases with:
        - Number of axioms in KB
        - Number of inference rules
        - Maximum iterations allowed
        
        Args:
            formula: Formula to prove
            kb: Knowledge base
        
        Returns:
            Estimated cost (higher = more expensive)
        """
        kb_size = len(kb.axioms) + len(kb.theorems)
        rule_count = len(self.tdfol_rules)
        
        # Cost is proportional to KB size * rules * iterations
        return kb_size * rule_count * self.max_iterations / 1000.0

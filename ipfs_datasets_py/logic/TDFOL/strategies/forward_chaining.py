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
    
    def __init__(self, max_iterations: int = 100, rules=None):
        """
        Initialize forward chaining strategy.
        
        Args:
            max_iterations: Maximum number of rule application iterations
            rules: Optional list of inference rules (overrides auto-loaded rules)
        """
        super().__init__("Forward Chaining", StrategyType.FORWARD_CHAINING)
        self.max_iterations = max_iterations
        self.tdfol_rules = rules if rules is not None else []
        
        if rules is None:
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
        # Cap timeout to avoid very long runs; use a sensible default upper bound
        timeout_ms = min(timeout_ms, 2000)
        start_time = time.time()
        
        # Initialize derived collection with axioms and theorems
        # Use a list to avoid hash issues with TDFOL formulas that contain list attributes
        all_formulas = list(kb.axioms) + list(kb.theorems)
        derived_list: List[Formula] = list(all_formulas)
        derived_strs: Set[str] = {str(f) for f in derived_list}
        proof_steps: List[ProofStep] = []
        
        def _in_derived(f: Formula) -> bool:
            """Check membership using string representation (handles unhashable formulas)."""
            try:
                return f in derived_list or str(f) in derived_strs
            except Exception:
                return any(str(f) == str(x) for x in derived_list)
        
        def _add_to_derived(f: Formula) -> bool:
            """Add formula to derived if not already present. Returns True if added."""
            f_str = str(f)
            if f_str not in derived_strs:
                derived_list.append(f)
                derived_strs.add(f_str)
                return True
            return False
        
        # Check if goal is already in derived
        if _in_derived(formula):
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
            
            # Check if goal is derived
            if _in_derived(formula):
                return ProofResult(
                    status=ProofStatus.PROVED,
                    formula=formula,
                    proof_steps=proof_steps,
                    time_ms=(time.time() - start_time) * 1000,
                    method=self.name,
                    message=f"Proved in {iteration} iterations"
                )
            
            # Apply all TDFOL rules to derive new formulas (with deadline)
            deadline = start_time + timeout_ms / 1000.0
            new_formulas = self._apply_rules_list(derived_list, proof_steps, deadline=deadline)
            
            # No progress made - stop
            if not new_formulas:
                break
            
            # Add new formulas to derived collection
            for f in new_formulas:
                _add_to_derived(f)
        
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
        derived: Set[Formula],
        proof_steps: List[ProofStep]
    ) -> Set[Formula]:
        """
        Apply all inference rules to derived formulas.
        
        Args:
            derived: Set of currently derived formulas
            proof_steps: List to append proof steps to
        
        Returns:
            Set of newly derived formulas
        """
        return self._apply_rules_list(list(derived), proof_steps)

    def _apply_rules_list(
        self,
        derived: List['Formula'],
        proof_steps: List['ProofStep'],
        deadline: float = None,
    ) -> List['Formula']:
        """
        Apply all inference rules to derived formulas (list-based, hash-safe).
        
        Args:
            derived: List of currently derived formulas
            proof_steps: List to append proof steps to
            deadline: Optional absolute time.time() deadline; stop early if exceeded.
        
        Returns:
            List of newly derived formulas (without duplicates)
        """
        import time as _time
        new_formulas: List[Formula] = []
        derived_strs: Set[str] = {str(f) for f in derived}
        # Hard cap: never generate more than 200 new formulas per iteration
        _MAX_NEW = 200
        
        def _not_in_derived(f: Formula) -> bool:
            try:
                return str(f) not in derived_strs
            except Exception:
                return True
        
        # Try each formula with each rule
        for current_formula in list(derived):
            if deadline is not None and _time.time() > deadline:
                break
            if len(new_formulas) >= _MAX_NEW:
                break
            for rule in self.tdfol_rules:
                if deadline is not None and _time.time() > deadline:
                    break
                if len(new_formulas) >= _MAX_NEW:
                    break
                try:
                    # Try single-formula rules
                    if hasattr(rule, 'can_apply'):
                        if rule.can_apply(current_formula):
                            new_formula = rule.apply(current_formula)
                            if _not_in_derived(new_formula):
                                new_formulas.append(new_formula)
                                derived_strs.add(str(new_formula))
                                proof_steps.append(ProofStep(
                                    formula=new_formula,
                                    justification=f"Applied {rule.name}",
                                    rule_name=rule.name,
                                    premises=[current_formula]
                                ))
                    
                    # Try two-formula rules (only first 20 derived to cap O(n²))
                    for other_formula in list(derived)[:20]:
                        if current_formula == other_formula:
                            continue
                        if deadline is not None and _time.time() > deadline:
                            break
                        if len(new_formulas) >= _MAX_NEW:
                            break
                        try:
                            if hasattr(rule, 'can_apply'):
                                if rule.can_apply(current_formula, other_formula):
                                    new_formula = rule.apply(current_formula, other_formula)
                                    if _not_in_derived(new_formula):
                                        new_formulas.append(new_formula)
                                        derived_strs.add(str(new_formula))
                                        proof_steps.append(ProofStep(
                                            formula=new_formula,
                                            justification=f"Applied {rule.name}",
                                            rule_name=rule.name,
                                            premises=[current_formula, other_formula]
                                        ))
                        except (AttributeError, TypeError, ValueError):
                            # Rule doesn't support two formulas or application failed
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

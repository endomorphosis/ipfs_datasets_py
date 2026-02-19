"""
Proof Strategies for DCEC (Phase 4 Weeks 2-3, Task 2.2)

This module provides different proof search strategies for DCEC theorem proving,
including forward chaining, backward chaining, bidirectional search, and hybrid
adaptive strategies.

Features:
- Forward chaining: Start from axioms, derive forward to goal
- Backward chaining: Start from goal, work backward to axioms
- Bidirectional search: Search from both ends simultaneously
- Hybrid strategies: Adaptively select best strategy based on problem characteristics

These strategies extend the basic prover to handle different proof scenarios
more efficiently.

Examples:
    >>> from ipfs_datasets_py.logic.CEC.native.proof_strategies import ForwardChainingStrategy
    >>> strategy = ForwardChainingStrategy(max_steps=100)
    >>> result = strategy.prove(goal, axioms, rules)
"""

from typing import List, Set, Dict, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod
import logging
import time

from .prover_core import (
    InferenceRule,
    ProofResult,
    ProofState,
    ProofTree,
    ProofStep,
)
from .dcec_core import Formula

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any as AnyType
    F = TypeVar('F', bound=Callable[..., AnyType])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """Types of proof strategies."""
    FORWARD_CHAINING = "forward_chaining"
    BACKWARD_CHAINING = "backward_chaining"
    BIDIRECTIONAL = "bidirectional"
    HYBRID = "hybrid"


class ProofStrategy(ABC):
    """
    Abstract base class for proof strategies.
    
    A proof strategy determines how the search space is explored
    when attempting to prove a goal from axioms.
    """
    
    def __init__(self, max_steps: int = 100):
        """
        Initialize proof strategy.
        
        Args:
            max_steps: Maximum number of inference steps
        """
        self.max_steps = max_steps
        self.steps_taken = 0
    
    @abstractmethod
    def name(self) -> str:
        """Get the name of this strategy."""
        pass
    
    @abstractmethod
    def prove(
        self,
        goal: Formula,
        axioms: List[Formula],
        rules: List[InferenceRule],
        timeout: Optional[float] = None
    ) -> ProofTree:
        """
        Attempt to prove a goal using this strategy.
        
        Args:
            goal: The formula to prove
            axioms: List of axioms (assumed true)
            rules: List of inference rules to use
            timeout: Optional timeout in seconds
            
        Returns:
            ProofTree with the result
        """
        pass
    
    def _is_goal_reached(self, goal: Formula, derived: List[Formula]) -> bool:
        """Check if goal has been derived."""
        goal_str = goal.to_string()
        return any(f.to_string() == goal_str for f in derived)
    
    def _apply_rules(
        self,
        formulas: List[Formula],
        rules: List[InferenceRule]
    ) -> List[Tuple[Formula, str]]:
        """
        Apply all applicable rules to formulas.
        
        Returns:
            List of (new_formula, rule_name) tuples
        """
        new_formulas: List[Tuple[Formula, str]] = []
        
        for rule in rules:
            if rule.can_apply(formulas):
                try:
                    results = rule.apply(formulas)
                    for result in results:
                        # Check if it's new
                        result_str = result.to_string()
                        if not any(f.to_string() == result_str for f in formulas):
                            new_formulas.append((result, rule.name()))
                except Exception as e:
                    logger.warning(f"Error applying {rule.name()}: {e}")
        
        return new_formulas


class ForwardChainingStrategy(ProofStrategy):
    """
    Forward chaining proof strategy.
    
    Starts from axioms and applies inference rules forward,
    deriving new formulas until the goal is reached or resources exhausted.
    
    Best for: Problems with few axioms and many potential conclusions.
    
    Examples:
        >>> strategy = ForwardChainingStrategy(max_steps=100)
        >>> result = strategy.prove(goal, axioms, rules)
    """
    
    def name(self) -> str:
        return "Forward Chaining"
    
    def prove(
        self,
        goal: Formula,
        axioms: List[Formula],
        rules: List[InferenceRule],
        timeout: Optional[float] = None
    ) -> ProofTree:
        """Prove using forward chaining from axioms to goal."""
        logger.info(f"Forward chaining: Proving {goal.to_string()}")
        
        start_time = time.time()
        state = ProofState(goal, axioms)
        
        # Check if goal is already in axioms
        if state.has_goal():
            logger.info("Goal is an axiom!")
            return state.get_proof_tree(ProofResult.PROVED)
        
        # Forward chaining loop
        for step_num in range(self.max_steps):
            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                logger.info(f"Timeout after {step_num} steps")
                return state.get_proof_tree(ProofResult.TIMEOUT)
            
            # Apply rules to derive new formulas
            new_formulas = self._apply_rules(state.derived, rules)
            
            if not new_formulas:
                logger.info(f"No new formulas after {step_num+1} steps")
                break
            
            # Add new formulas to state
            for formula, rule_name in new_formulas:
                state.add_formula(formula, rule_name, [])
                
                # Check if goal reached
                if state.has_goal():
                    logger.info(f"Proof found in {step_num+1} steps!")
                    self.steps_taken = step_num + 1
                    return state.get_proof_tree(ProofResult.PROVED)
        
        logger.info(f"Could not prove goal in {self.max_steps} steps")
        self.steps_taken = self.max_steps
        return state.get_proof_tree(ProofResult.UNKNOWN)


class BackwardChainingStrategy(ProofStrategy):
    """
    Backward chaining proof strategy.
    
    Starts from the goal and works backward, trying to find
    subgoals that can be satisfied by the axioms.
    
    Best for: Problems with a specific goal and many axioms.
    
    Examples:
        >>> strategy = BackwardChainingStrategy(max_steps=100)
        >>> result = strategy.prove(goal, axioms, rules)
    """
    
    def name(self) -> str:
        return "Backward Chaining"
    
    def prove(
        self,
        goal: Formula,
        axioms: List[Formula],
        rules: List[InferenceRule],
        timeout: Optional[float] = None
    ) -> ProofTree:
        """Prove using backward chaining from goal to axioms."""
        logger.info(f"Backward chaining: Proving {goal.to_string()}")
        
        start_time = time.time()
        state = ProofState(goal, axioms)
        
        # Check if goal is already in axioms
        if state.has_goal():
            logger.info("Goal is an axiom!")
            return state.get_proof_tree(ProofResult.PROVED)
        
        # Maintain a stack of subgoals to prove
        subgoals: List[Formula] = [goal]
        proved_subgoals: Set[str] = set(f.to_string() for f in axioms)
        
        for step_num in range(self.max_steps):
            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                logger.info(f"Timeout after {step_num} steps")
                return state.get_proof_tree(ProofResult.TIMEOUT)
            
            if not subgoals:
                break
            
            # Pop a subgoal
            current_goal = subgoals.pop(0)
            current_goal_str = current_goal.to_string()
            
            # Check if already proved
            if current_goal_str in proved_subgoals:
                continue
            
            # Try to find a rule that can produce this goal
            found = False
            for rule in rules:
                # Simplified backward chaining: 
                # Try applying rules to see if they produce the subgoal
                try:
                    # Get current derived formulas
                    candidates = self._apply_rules(state.derived, rules)
                    
                    for formula, rule_name in candidates:
                        if formula.to_string() == current_goal_str:
                            # Found a way to derive the subgoal
                            state.add_formula(formula, rule_name, [])
                            proved_subgoals.add(current_goal_str)
                            found = True
                            break
                    
                    if found:
                        break
                except Exception as e:
                    logger.warning(f"Error in backward chaining: {e}")
            
            # Check if goal is proved
            if goal.to_string() in proved_subgoals:
                logger.info(f"Proof found in {step_num+1} steps!")
                self.steps_taken = step_num + 1
                return state.get_proof_tree(ProofResult.PROVED)
        
        logger.info(f"Could not prove goal in {self.max_steps} steps")
        self.steps_taken = self.max_steps
        return state.get_proof_tree(ProofResult.UNKNOWN)


class BidirectionalStrategy(ProofStrategy):
    """
    Bidirectional search proof strategy.
    
    Searches from both axioms (forward) and goal (backward) simultaneously,
    trying to meet in the middle.
    
    Best for: Problems where both forward and backward search have
    manageable branching factors.
    
    Examples:
        >>> strategy = BidirectionalStrategy(max_steps=100)
        >>> result = strategy.prove(goal, axioms, rules)
    """
    
    def name(self) -> str:
        return "Bidirectional Search"
    
    def prove(
        self,
        goal: Formula,
        axioms: List[Formula],
        rules: List[InferenceRule],
        timeout: Optional[float] = None
    ) -> ProofTree:
        """Prove using bidirectional search."""
        logger.info(f"Bidirectional search: Proving {goal.to_string()}")
        
        start_time = time.time()
        state = ProofState(goal, axioms)
        
        # Check if goal is already in axioms
        if state.has_goal():
            logger.info("Goal is an axiom!")
            return state.get_proof_tree(ProofResult.PROVED)
        
        # Maintain forward and backward frontiers
        forward_derived: Set[str] = set(f.to_string() for f in axioms)
        backward_goals: Set[str] = {goal.to_string()}
        
        # Split steps between forward and backward search
        for step_num in range(self.max_steps):
            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                logger.info(f"Timeout after {step_num} steps")
                return state.get_proof_tree(ProofResult.TIMEOUT)
            
            # Forward step (every other step)
            if step_num % 2 == 0:
                new_formulas = self._apply_rules(state.derived, rules)
                
                for formula, rule_name in new_formulas:
                    formula_str = formula.to_string()
                    state.add_formula(formula, rule_name, [])
                    forward_derived.add(formula_str)
                    
                    # Check if we've met in the middle
                    if formula_str in backward_goals:
                        logger.info(f"Proof found (bidirectional) in {step_num+1} steps!")
                        self.steps_taken = step_num + 1
                        return state.get_proof_tree(ProofResult.PROVED)
            
            # Backward step
            else:
                # Try to expand backward goals
                # (Simplified: just check if forward has reached goal)
                if goal.to_string() in forward_derived:
                    logger.info(f"Proof found (forward reached goal) in {step_num+1} steps!")
                    self.steps_taken = step_num + 1
                    return state.get_proof_tree(ProofResult.PROVED)
        
        logger.info(f"Could not prove goal in {self.max_steps} steps")
        self.steps_taken = self.max_steps
        return state.get_proof_tree(ProofResult.UNKNOWN)


class HybridStrategy(ProofStrategy):
    """
    Hybrid adaptive proof strategy.
    
    Analyzes the problem characteristics and adaptively selects
    the best strategy (forward, backward, or bidirectional) based on:
    - Number of axioms
    - Complexity of goal
    - Problem structure
    
    Best for: Unknown or varying problem types.
    
    Examples:
        >>> strategy = HybridStrategy(max_steps=100)
        >>> result = strategy.prove(goal, axioms, rules)
    """
    
    def name(self) -> str:
        return "Hybrid Adaptive"
    
    def _select_strategy(
        self,
        goal: Formula,
        axioms: List[Formula],
        rules: List[InferenceRule]
    ) -> ProofStrategy:
        """
        Select the best strategy based on problem characteristics.
        
        Heuristics:
        - Few axioms (< 5): Forward chaining
        - Many axioms (>= 10): Backward chaining
        - Medium axioms (5-9): Bidirectional search
        """
        num_axioms = len(axioms)
        
        if num_axioms < 5:
            logger.info("Selecting forward chaining (few axioms)")
            return ForwardChainingStrategy(self.max_steps)
        elif num_axioms >= 10:
            logger.info("Selecting backward chaining (many axioms)")
            return BackwardChainingStrategy(self.max_steps)
        else:
            logger.info("Selecting bidirectional search (medium axioms)")
            return BidirectionalStrategy(self.max_steps)
    
    def prove(
        self,
        goal: Formula,
        axioms: List[Formula],
        rules: List[InferenceRule],
        timeout: Optional[float] = None
    ) -> ProofTree:
        """Prove using adaptively selected strategy."""
        logger.info(f"Hybrid strategy: Analyzing problem for {goal.to_string()}")
        
        # Select best strategy
        selected_strategy = self._select_strategy(goal, axioms, rules)
        logger.info(f"Selected: {selected_strategy.name()}")
        
        # Use the selected strategy
        result = selected_strategy.prove(goal, axioms, rules, timeout)
        self.steps_taken = selected_strategy.steps_taken
        
        return result


# Convenience function for strategy selection

def get_strategy(strategy_type: StrategyType, max_steps: int = 100) -> ProofStrategy:
    """
    Get a proof strategy by type.
    
    Args:
        strategy_type: Type of strategy to create
        max_steps: Maximum number of steps
        
    Returns:
        Instantiated proof strategy
    
    Examples:
        >>> strategy = get_strategy(StrategyType.FORWARD_CHAINING, max_steps=50)
        >>> result = strategy.prove(goal, axioms, rules)
    """
    if strategy_type == StrategyType.FORWARD_CHAINING:
        return ForwardChainingStrategy(max_steps)
    elif strategy_type == StrategyType.BACKWARD_CHAINING:
        return BackwardChainingStrategy(max_steps)
    elif strategy_type == StrategyType.BIDIRECTIONAL:
        return BidirectionalStrategy(max_steps)
    elif strategy_type == StrategyType.HYBRID:
        return HybridStrategy(max_steps)
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")

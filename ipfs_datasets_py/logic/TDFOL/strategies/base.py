"""
Prover strategy abstractions for TDFOL.

This module provides the base classes and interfaces for implementing
pluggable proving strategies in the TDFOL theorem prover.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from ..tdfol_core import Formula, TDFOLKnowledgeBase, ProofStep


class StrategyType(Enum):
    """Types of proving strategies."""
    
    FORWARD_CHAINING = "forward_chaining"
    BACKWARD_CHAINING = "backward_chaining"
    MODAL_TABLEAUX = "modal_tableaux"
    CEC_DELEGATE = "cec_delegate"
    BIDIRECTIONAL = "bidirectional"
    AUTO = "auto"


class ProverStrategy(ABC):
    """
    Abstract base class for proving strategies.
    
    A proving strategy defines a specific approach to theorem proving,
    such as forward chaining, backward chaining, modal tableaux, etc.
    Strategies can be selected automatically based on formula characteristics
    or manually by the user.
    
    Attributes:
        name: Human-readable name of the strategy
        strategy_type: Type of strategy from StrategyType enum
    """
    
    def __init__(self, name: str, strategy_type: StrategyType):
        """
        Initialize the strategy.
        
        Args:
            name: Human-readable name
            strategy_type: Strategy type identifier
        """
        self.name = name
        self.strategy_type = strategy_type
    
    @abstractmethod
    def can_handle(self, formula: Formula, kb: TDFOLKnowledgeBase) -> bool:
        """
        Check if this strategy can handle the given formula.
        
        Args:
            formula: Formula to prove
            kb: Knowledge base with axioms and theorems
        
        Returns:
            True if this strategy is applicable to the formula
        
        Example:
            >>> strategy = ForwardChainingStrategy()
            >>> formula = Predicate("P", ())
            >>> kb = TDFOLKnowledgeBase()
            >>> can_handle = strategy.can_handle(formula, kb)
        """
        pass
    
    @abstractmethod
    def prove(
        self,
        formula: Formula,
        kb: TDFOLKnowledgeBase,
        timeout_ms: Optional[int] = None
    ) -> 'ProofResult':
        """
        Attempt to prove the formula using this strategy.
        
        Args:
            formula: Formula to prove
            kb: Knowledge base with axioms and theorems
            timeout_ms: Optional timeout in milliseconds
        
        Returns:
            ProofResult with status and proof steps
        
        Raises:
            TimeoutError: If proof exceeds timeout
        
        Example:
            >>> strategy = ForwardChainingStrategy()
            >>> formula = Predicate("P", ())
            >>> kb = TDFOLKnowledgeBase()
            >>> result = strategy.prove(formula, kb, timeout_ms=5000)
            >>> print(result.status)
            ProofStatus.PROVED
        """
        pass
    
    @abstractmethod
    def get_priority(self) -> int:
        """
        Get strategy priority for auto-selection.
        
        Higher priority strategies are tried first when using
        automatic strategy selection. Priorities should be:
        - 100+: Very high priority (fast, reliable)
        - 50-99: High priority (good balance)
        - 10-49: Medium priority (slower or specialized)
        - 1-9: Low priority (fallback strategies)
        
        Returns:
            Priority value (higher = try first)
        
        Example:
            >>> strategy = ForwardChainingStrategy()
            >>> priority = strategy.get_priority()
            >>> assert priority >= 50  # High priority for forward chaining
        """
        pass
    
    def estimate_cost(self, formula: Formula, kb: TDFOLKnowledgeBase) -> float:
        """
        Estimate computational cost of using this strategy.
        
        Optional method that can be overridden to provide cost estimates
        for strategy selection. Default implementation returns 1.0.
        
        Args:
            formula: Formula to prove
            kb: Knowledge base
        
        Returns:
            Estimated cost (higher = more expensive)
        """
        return 1.0
    
    def __str__(self) -> str:
        """String representation of the strategy."""
        return f"{self.name} ({self.strategy_type.value})"
    
    def __repr__(self) -> str:
        """Repr of the strategy."""
        return f"ProverStrategy(name='{self.name}', type={self.strategy_type})"

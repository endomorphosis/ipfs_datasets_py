"""
Strategy selector for automatic proving strategy selection.

This module provides automatic selection of the best proving strategy
based on formula characteristics, strategy priorities, and cost estimates.
"""

import logging
from typing import List, Optional

from .base import ProverStrategy, StrategyType
from ..tdfol_core import Formula, TDFOLKnowledgeBase

logger = logging.getLogger(__name__)


class StrategySelector:
    """
    Automatically select best proving strategy.
    
    The strategy selector examines a formula and knowledge base to determine
    which proving strategy is most likely to succeed efficiently. Selection
    is based on:
    
    1. **Applicability**: Strategy can handle the formula
    2. **Priority**: Higher priority strategies tried first
    3. **Cost**: Lower cost strategies preferred when priorities equal
    
    Example:
        >>> from ipfs_datasets_py.logic.TDFOL.strategies import (
        ...     ForwardChainingStrategy, ModalTableauxStrategy, StrategySelector
        ... )
        >>> strategies = [ForwardChainingStrategy(), ModalTableauxStrategy()]
        >>> selector = StrategySelector(strategies)
        >>> 
        >>> # Automatic selection
        >>> formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        >>> kb = TDFOLKnowledgeBase()
        >>> strategy = selector.select_strategy(formula, kb)
        >>> print(strategy.name)
        'Modal Tableaux'  # Selected because formula is modal
    """
    
    def __init__(self, strategies: Optional[List[ProverStrategy]] = None):
        """
        Initialize strategy selector.
        
        Args:
            strategies: List of available strategies. If None, uses default strategies.
        """
        if strategies is None:
            strategies = self._get_default_strategies()
        
        # Sort strategies by priority (highest first)
        self.strategies = sorted(
            strategies,
            key=lambda s: s.get_priority(),
            reverse=True
        )
        
        logger.debug(f"Strategy selector initialized with {len(self.strategies)} strategies")
    
    def _get_default_strategies(self) -> List[ProverStrategy]:
        """Get default set of strategies."""
        strategies = []
        
        # Import strategies dynamically
        try:
            from .forward_chaining import ForwardChainingStrategy
            strategies.append(ForwardChainingStrategy())
        except ImportError:
            logger.warning("ForwardChainingStrategy not available")
        
        try:
            from .modal_tableaux import ModalTableauxStrategy
            strategies.append(ModalTableauxStrategy())
        except ImportError:
            logger.warning("ModalTableauxStrategy not available")
        
        try:
            from .cec_delegate import CECDelegateStrategy
            strategies.append(CECDelegateStrategy())
        except ImportError:
            logger.warning("CECDelegateStrategy not available")
        
        if not strategies:
            logger.error("No strategies available!")
        
        return strategies
    
    def select_strategy(
        self,
        formula: Formula,
        kb: TDFOLKnowledgeBase,
        prefer_low_cost: bool = False
    ) -> ProverStrategy:
        """
        Select best strategy for formula.
        
        Selection algorithm:
        1. Filter to strategies that can handle the formula
        2. If prefer_low_cost, sort by cost estimate
        3. Otherwise, use priority-based selection (default)
        4. Return highest priority / lowest cost strategy
        5. Fallback to first general-purpose strategy if none applicable
        
        Args:
            formula: Formula to prove
            kb: Knowledge base
            prefer_low_cost: If True, prioritize low cost over high priority
        
        Returns:
            Selected proving strategy
        
        Raises:
            ValueError: If no strategies available
        
        Example:
            >>> selector = StrategySelector()
            >>> formula = Predicate("P", ())
            >>> kb = TDFOLKnowledgeBase()
            >>> strategy = selector.select_strategy(formula, kb)
        """
        if not self.strategies:
            raise ValueError("No strategies available for selection")
        
        # Filter to applicable strategies
        applicable = [s for s in self.strategies if s.can_handle(formula, kb)]
        
        if not applicable:
            # No strategy claims to handle it, use fallback
            logger.debug("No applicable strategies found, using fallback")
            return self._get_fallback_strategy()
        
        logger.debug(f"Found {len(applicable)} applicable strategies")
        
        # Select based on cost or priority
        if prefer_low_cost:
            # Sort by cost (lowest first)
            strategy = min(applicable, key=lambda s: s.estimate_cost(formula, kb))
            logger.debug(f"Selected low-cost strategy: {strategy.name}")
        else:
            # Already sorted by priority, take first applicable
            strategy = applicable[0]
            logger.debug(f"Selected high-priority strategy: {strategy.name}")
        
        return strategy
    
    def select_multiple(
        self,
        formula: Formula,
        kb: TDFOLKnowledgeBase,
        max_strategies: int = 3
    ) -> List[ProverStrategy]:
        """
        Select multiple strategies to try in order.
        
        Returns a ranked list of strategies to try, allowing fallback
        if the first strategy fails.
        
        Args:
            formula: Formula to prove
            kb: Knowledge base
            max_strategies: Maximum number of strategies to return
        
        Returns:
            List of strategies in priority order
        
        Example:
            >>> selector = StrategySelector()
            >>> formula = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
            >>> strategies = selector.select_multiple(formula, kb, max_strategies=2)
            >>> # Try strategies in order
            >>> for strategy in strategies:
            ...     result = strategy.prove(formula, kb)
            ...     if result.is_proved():
            ...         break
        """
        if not self.strategies:
            return []
        
        # Filter to applicable strategies
        applicable = [s for s in self.strategies if s.can_handle(formula, kb)]
        
        if not applicable:
            # Use fallback
            return [self._get_fallback_strategy()]
        
        # Return top N strategies
        return applicable[:max_strategies]
    
    def _get_fallback_strategy(self) -> ProverStrategy:
        """
        Get fallback strategy when no strategy is applicable.
        
        Returns the first general-purpose strategy (usually forward chaining).
        
        Returns:
            Fallback strategy
        
        Raises:
            ValueError: If no strategies available at all
        """
        if not self.strategies:
            raise ValueError("No fallback strategy available")
        
        # Look for forward chaining strategy
        for strategy in self.strategies:
            if strategy.strategy_type == StrategyType.FORWARD_CHAINING:
                logger.debug("Using forward chaining as fallback")
                return strategy
        
        # Just return first strategy as last resort
        logger.warning("No forward chaining found, using first available strategy")
        return self.strategies[0]
    
    def get_strategy_info(self) -> List[dict]:
        """
        Get information about available strategies.
        
        Returns:
            List of dictionaries with strategy information
        
        Example:
            >>> selector = StrategySelector()
            >>> info = selector.get_strategy_info()
            >>> for s in info:
            ...     print(f"{s['name']}: priority={s['priority']}, type={s['type']}")
        """
        return [
            {
                "name": s.name,
                "type": s.strategy_type.value,
                "priority": s.get_priority()
            }
            for s in self.strategies
        ]
    
    def add_strategy(self, strategy: ProverStrategy) -> None:
        """
        Add a new strategy to the selector.
        
        The strategy list is re-sorted by priority after addition.
        
        Args:
            strategy: Strategy to add
        
        Example:
            >>> selector = StrategySelector()
            >>> custom_strategy = MyCustomStrategy()
            >>> selector.add_strategy(custom_strategy)
        """
        self.strategies.append(strategy)
        # Re-sort by priority
        self.strategies.sort(key=lambda s: s.get_priority(), reverse=True)
        logger.debug(f"Added strategy: {strategy.name}")

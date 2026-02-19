"""
Prover strategies for TDFOL theorem proving.

This package provides pluggable proving strategies that can be used
with the TDFOL theorem prover. Strategies include:

- ForwardChainingStrategy: Standard forward chaining with inference rules
- ModalTableauxStrategy: Modal tableaux for modal logic
- CECDelegateStrategy: Delegates to CEC prover for compatible formulas
- StrategySelector: Automatically selects the best strategy

Example:
    >>> from ipfs_datasets_py.logic.TDFOL.strategies import (
    ...     ForwardChainingStrategy, StrategySelector
    ... )
    >>> from ipfs_datasets_py.logic.TDFOL import TDFOLKnowledgeBase, Predicate
    >>> 
    >>> # Manual strategy selection
    >>> strategy = ForwardChainingStrategy()
    >>> kb = TDFOLKnowledgeBase()
    >>> formula = Predicate("P", ())
    >>> result = strategy.prove(formula, kb)
    >>> 
    >>> # Automatic strategy selection
    >>> selector = StrategySelector()
    >>> best_strategy = selector.select_strategy(formula, kb)
    >>> result = best_strategy.prove(formula, kb)
"""

from .base import (
    ProverStrategy,
    StrategyType,
)
# Import ProofStep from unified location in tdfol_core
from ..tdfol_core import ProofStep

__all__ = [
    'ProverStrategy',
    'StrategyType',
    'ProofStep',
]

# Strategy implementations will be imported when available
try:
    from .forward_chaining import ForwardChainingStrategy
    __all__.append('ForwardChainingStrategy')
except ImportError:
    pass

try:
    from .modal_tableaux import ModalTableauxStrategy
    __all__.append('ModalTableauxStrategy')
except ImportError:
    pass

try:
    from .cec_delegate import CECDelegateStrategy
    __all__.append('CECDelegateStrategy')
except ImportError:
    pass

try:
    from .strategy_selector import StrategySelector
    __all__.append('StrategySelector')
except ImportError:
    pass

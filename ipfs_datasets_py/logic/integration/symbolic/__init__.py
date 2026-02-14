"""
Symbolic AI integration for logic module.

Provides SymbolicAI and neurosymbolic integration.

Components:
- LogicPrimitives: Symbolic logic primitives
- NeurosymbolicAPI: Neurosymbolic API
- NeurosymbolicGraphRAG: GraphRAG integration
- neurosymbolic/ package
"""

try:
    from .symbolic_logic_primitives import LogicPrimitives
except ImportError:
    LogicPrimitives = None

try:
    from .neurosymbolic_api import NeurosymbolicAPI
except ImportError:
    NeurosymbolicAPI = None

try:
    from .neurosymbolic_graphrag import NeurosymbolicGraphRAG
except ImportError:
    NeurosymbolicGraphRAG = None

__all__ = [
    'LogicPrimitives',
    'NeurosymbolicAPI',
    'NeurosymbolicGraphRAG',
]

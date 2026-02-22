"""Backward-compatibility shim: re-exports SymbolicFOLBridge from integration layer."""
from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import *  # noqa: F401, F403
from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import (  # noqa: F401
    SymbolicFOLBridge,
    FOLConversionResult,
    LogicalComponents,
    SYMBOLIC_AI_AVAILABLE,
)

"""Compatibility wrapper for the canonical F-logic optimizer module."""

from ipfs_datasets_py.logic.flogic_optimizer import (
    FLogicOptimizerConfig,
    FLogicOptimizerResult,
    FLogicSemanticOptimizer,
    OntologyViolation,
)

__all__ = [
    "FLogicSemanticOptimizer",
    "FLogicOptimizerConfig",
    "FLogicOptimizerResult",
    "OntologyViolation",
]

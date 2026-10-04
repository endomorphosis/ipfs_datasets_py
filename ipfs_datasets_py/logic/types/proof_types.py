"""
Proof Type Definitions

This module provides backward-compatible imports for proof-related types.
Types are still defined in TDFOL/tdfol_prover.py but imported here
for centralized access and to prevent circular dependencies.

For internal use within the logic module, import from here:
    from ipfs_datasets_py.logic.types import ProofStatus, ProofResult

For external use, the types are still available from their original location:
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
"""

# Re-export from original location to maintain backward compatibility
from ..TDFOL.tdfol_prover import (
    ProofStatus,
    ProofResult,
    ProofStep,
)

__all__ = [
    "ProofStatus",
    "ProofResult",
    "ProofStep",
]

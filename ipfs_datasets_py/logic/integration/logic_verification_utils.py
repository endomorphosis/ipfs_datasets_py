"""Backward-compatible re-export of logic verification utilities.

New code should import from
``ipfs_datasets_py.logic.integration.reasoning.logic_verification_utils``.
"""

from .reasoning.logic_verification_utils import *  # noqa: F401, F403
from .reasoning.logic_verification_utils import (  # explicit for IDE support
    verify_consistency,
    verify_entailment,
    create_logic_verifier,
    are_contradictory,
)

__all__ = [
    "verify_consistency",
    "verify_entailment",
    "create_logic_verifier",
    "are_contradictory",
]

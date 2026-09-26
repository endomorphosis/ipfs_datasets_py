"""Candidate compiler for legal-surface-ir/v2, separate from canonical v1.

Supervisor implementation target. Returning None is an explicit abstention;
do not infer an obligation from a definition or a declaration of policy.
"""
from __future__ import annotations

from .extended_contracts import ExtendedLegalIR


def compile_extended(text: str) -> ExtendedLegalIR | None:
    """Compile a complete supported span; abstain on unsupported/mixed residue."""
    if type(text) is not str or not text.strip():
        raise ValueError("source must be nonempty text")
    return None

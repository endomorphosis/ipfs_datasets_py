"""Backward-compat shim: re-exports from reasoning.logic_verification_utils."""
from .reasoning.logic_verification_utils import (
    verify_consistency,
    verify_entailment,
    create_logic_verifier,
    generate_proof,
    are_contradictory,
    validate_formula_syntax,
    parse_proof_steps,
    get_basic_axioms,
)

__all__ = [
    "verify_consistency",
    "verify_entailment",
    "create_logic_verifier",
    "generate_proof",
    "are_contradictory",
    "validate_formula_syntax",
    "parse_proof_steps",
    "get_basic_axioms",
]

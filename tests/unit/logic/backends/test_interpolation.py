from __future__ import annotations

from ipfs_datasets_py.logic.backends.smt.compiler import (
    SmtTerm,
    SmtTermKind,
    term_and,
    term_int,
    term_symbol,
)
from ipfs_datasets_py.logic.backends.smt.interpolation import (
    InterpolationStatus,
    compute_and_validate_interpolant,
)


def _range(symbol: str, lower: int, upper: int) -> SmtTerm:
    value = term_symbol(symbol)
    return term_and(
        SmtTerm(SmtTermKind.GE, arguments=(value, term_int(lower))),
        SmtTerm(SmtTermKind.LE, arguments=(value, term_int(upper))),
    )


def test_live_qf_lia_interpolant_is_independently_validated() -> None:
    receipt = compute_and_validate_interpolant(_range("x", 0, 10), _range("x", 20, 30))
    assert receipt.status is InterpolationStatus.VALIDATED
    assert receipt.interpolant is not None
    assert set(receipt.interpolant_vocabulary) <= {"x"}
    assert receipt.a_implies_i_receipt.startswith("b")
    assert receipt.i_and_b_unsat_receipt.startswith("b")


def test_non_shared_provider_symbol_cannot_be_admitted() -> None:
    # No shared symbol means the provider must produce a constant interpolant.
    receipt = compute_and_validate_interpolant(_range("x", 0, 1), _range("y", 2, 3))
    assert set(receipt.interpolant_vocabulary) <= set(receipt.shared_vocabulary)
    assert receipt.status in {InterpolationStatus.VALIDATED, InterpolationStatus.UNKNOWN}


def test_unqualified_theory_is_typed_unsupported() -> None:
    receipt = compute_and_validate_interpolant(
        _range("x", 0, 1), _range("x", 2, 3), theory="AUFLIA"
    )
    assert receipt.status is InterpolationStatus.UNSUPPORTED
    assert receipt.interpolant is None

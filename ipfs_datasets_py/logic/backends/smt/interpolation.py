"""Capability-negotiated Craig interpolation with independent validation.

The initial qualified fragment is quantifier-free linear integer arithmetic.
No interpolant is admitted merely because a provider returned a term: two
fresh Z3 sessions re-check ``A => I`` and ``I & B`` unsatisfiable, and the
shared-vocabulary condition is checked structurally.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from ipfs_datasets_py.logic.backends.smt.compiler import (
    INT_SORT,
    SmtTerm,
    SmtTermKind,
    term_not,
)
from ipfs_datasets_py.logic.backends.smt.incremental import (
    SmtCheckStatus,
    open_incremental_smt_session,
)
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity

INTERPOLATION_INTERFACE: Final = "ValidatedCraigInterpolation@1"
INTERPOLATION_RECEIPT_SCHEMA: Final = "validated-craig-interpolant/v1"


class InterpolationError(ValueError):
    """Raised for malformed interpolation requests."""


class InterpolationStatus(StrEnum):
    VALIDATED = "validated"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ValidatedInterpolantReceipt:
    status: InterpolationStatus | str
    partition_a_cid: str
    partition_b_cid: str
    shared_vocabulary: tuple[str, ...]
    interpolant: SmtTerm | None
    interpolant_vocabulary: tuple[str, ...]
    provider: str
    provider_version: str
    theory: str
    a_implies_i_receipt: str = ""
    i_and_b_unsat_receipt: str = ""
    reason: str = ""
    limitations: tuple[str, ...] = ()
    schema: str = INTERPOLATION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        try:
            status = (
                self.status
                if isinstance(self.status, InterpolationStatus)
                else InterpolationStatus(self.status)
            )
        except ValueError as error:
            raise InterpolationError(str(error)) from error
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "shared_vocabulary", tuple(sorted(set(self.shared_vocabulary))))
        object.__setattr__(
            self, "interpolant_vocabulary", tuple(sorted(set(self.interpolant_vocabulary)))
        )
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        if status is InterpolationStatus.VALIDATED and self.interpolant is None:
            raise InterpolationError("validated receipt requires an interpolant")
        if self.schema != INTERPOLATION_RECEIPT_SCHEMA:
            raise InterpolationError("unsupported interpolation receipt schema")

    @property
    def receipt_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="logic.backends.smt.validated-interpolant",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "a_implies_i_receipt": self.a_implies_i_receipt,
            "i_and_b_unsat_receipt": self.i_and_b_unsat_receipt,
            "interpolant": None if self.interpolant is None else self.interpolant.to_dict(),
            "interpolant_vocabulary": list(self.interpolant_vocabulary),
            "limitations": list(self.limitations),
            "partition_a_cid": self.partition_a_cid,
            "partition_b_cid": self.partition_b_cid,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "reason": self.reason,
            "schema": self.schema,
            "shared_vocabulary": list(self.shared_vocabulary),
            "status": (
                self.status.value
                if isinstance(self.status, InterpolationStatus)
                else self.status
            ),
            "theory": self.theory,
        }


def _term_cid(term: SmtTerm, label: str) -> str:
    return canonical_identity(
        term.to_dict(),
        domain=f"logic.backends.smt.interpolation.{label}",
        schema_version="smt-term/v1",
    ).cid


def _symbols(term: SmtTerm) -> set[str]:
    result = {term.value} if term.kind is SmtTermKind.SYMBOL else set()
    for item in term.arguments:
        result.update(_symbols(item))
    return result


def _to_cvc5(term: SmtTerm, solver: Any, symbols: dict[str, Any], kind: Any) -> Any:
    children = [_to_cvc5(item, solver, symbols, kind) for item in term.arguments]
    if term.kind is SmtTermKind.TRUE:
        return solver.mkBoolean(True)
    if term.kind is SmtTermKind.FALSE:
        return solver.mkBoolean(False)
    if term.kind is SmtTermKind.INT:
        return solver.mkInteger(term.value)
    if term.kind is SmtTermKind.SYMBOL:
        return symbols.setdefault(term.value, solver.mkConst(solver.getIntegerSort(), term.value))
    operations = {
        SmtTermKind.NOT: kind.NOT,
        SmtTermKind.AND: kind.AND,
        SmtTermKind.OR: kind.OR,
        SmtTermKind.IMPLIES: kind.IMPLIES,
        SmtTermKind.EQ: kind.EQUAL,
        SmtTermKind.IFF: kind.EQUAL,
        SmtTermKind.LT: kind.LT,
        SmtTermKind.LE: kind.LEQ,
        SmtTermKind.GT: kind.GT,
        SmtTermKind.GE: kind.GEQ,
        SmtTermKind.ADD: kind.ADD,
        SmtTermKind.SUB: kind.SUB,
        SmtTermKind.MUL: kind.MULT,
    }
    if term.kind not in operations:
        raise InterpolationError(f"unsupported QF_LIA term {term.kind.value}")
    return solver.mkTerm(operations[term.kind], *children)


def _from_cvc5(term: Any, kind: Any) -> SmtTerm:
    if term.isIntegerValue():
        return SmtTerm(SmtTermKind.INT, value=str(term.getIntegerValue()))
    if term.isBooleanValue():
        return SmtTerm(SmtTermKind.TRUE if term.getBooleanValue() else SmtTermKind.FALSE)
    if term.hasSymbol():
        return SmtTerm(SmtTermKind.SYMBOL, value=str(term.getSymbol()))
    reverse = {
        kind.NOT: SmtTermKind.NOT,
        kind.AND: SmtTermKind.AND,
        kind.OR: SmtTermKind.OR,
        kind.IMPLIES: SmtTermKind.IMPLIES,
        kind.EQUAL: SmtTermKind.EQ,
        kind.LT: SmtTermKind.LT,
        kind.LEQ: SmtTermKind.LE,
        kind.GT: SmtTermKind.GT,
        kind.GEQ: SmtTermKind.GE,
        kind.ADD: SmtTermKind.ADD,
        kind.SUB: SmtTermKind.SUB,
        kind.MULT: SmtTermKind.MUL,
    }
    term_kind = term.getKind()
    if term_kind not in reverse:
        raise InterpolationError(f"provider returned unsupported interpolant kind {term_kind}")
    return SmtTerm(reverse[term_kind], arguments=tuple(_from_cvc5(item, kind) for item in term))


def _validate_with_z3(
    *,
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    interpolant: SmtTerm,
    symbols: tuple[str, ...],
    request_root: str,
) -> tuple[bool, str, str]:
    first = open_incremental_smt_session(
        session_id="interpolant-a-implies-i",
        translator_identity="cvc5-interpolant-to-structured-smt-term@1",
        theory_fingerprint="QF_LIA@1",
        policy_root=request_root,
        configuration_root=request_root,
        environment_root="local-independent-z3-validator@1",
    )
    second = open_incremental_smt_session(
        session_id="interpolant-i-and-b",
        translator_identity="cvc5-interpolant-to-structured-smt-term@1",
        theory_fingerprint="QF_LIA@1",
        policy_root=request_root,
        configuration_root=request_root,
        environment_root="local-independent-z3-validator@1",
    )
    for symbol in symbols:
        first.declare_symbol(symbol, INT_SORT)
        second.declare_symbol(symbol, INT_SORT)
    first.add_named_assertion(
        "partition-a",
        partition_a,
        source_ref=_term_cid(partition_a, "a"),
        obligation_id="a-implies-i",
    )
    first.add_named_assertion(
        "not-interpolant",
        term_not(interpolant),
        source_ref=_term_cid(interpolant, "i"),
        obligation_id="a-implies-i",
    )
    first_result = first.check()
    second.add_named_assertion(
        "interpolant", interpolant, source_ref=_term_cid(interpolant, "i"), obligation_id="i-and-b"
    )
    second.add_named_assertion(
        "partition-b", partition_b, source_ref=_term_cid(partition_b, "b"), obligation_id="i-and-b"
    )
    second_result = second.check()
    return (
        first_result.status is SmtCheckStatus.UNSAT
        and first_result.core_validated
        and second_result.status is SmtCheckStatus.UNSAT
        and second_result.core_validated,
        first_result.receipt_id,
        second_result.receipt_id,
    )


def compute_and_validate_interpolant(
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    *,
    theory: str = "QF_LIA",
) -> ValidatedInterpolantReceipt:
    """Compute ``I`` for unsatisfiable ``A & B`` and independently admit it."""

    a_cid = _term_cid(partition_a, "a")
    b_cid = _term_cid(partition_b, "b")
    shared = tuple(sorted(_symbols(partition_a) & _symbols(partition_b)))
    if theory != "QF_LIA":
        return ValidatedInterpolantReceipt(
            InterpolationStatus.UNSUPPORTED,
            a_cid,
            b_cid,
            shared,
            None,
            (),
            "cvc5",
            "unprobed",
            theory,
            reason="initial adapter is qualified only for QF_LIA",
        )
    try:
        cvc5 = importlib.import_module("cvc5")
    except ImportError:
        return ValidatedInterpolantReceipt(
            InterpolationStatus.UNAVAILABLE,
            a_cid,
            b_cid,
            shared,
            None,
            (),
            "cvc5",
            "unavailable",
            theory,
            reason="cvc5 Python API is not installed",
        )
    if not hasattr(cvc5.Solver, "getInterpolant"):
        return ValidatedInterpolantReceipt(
            InterpolationStatus.UNAVAILABLE,
            a_cid,
            b_cid,
            shared,
            None,
            (),
            "cvc5",
            str(cvc5.__version__),
            theory,
            reason="installed provider has no interpolation API",
        )
    try:
        solver = cvc5.Solver()
        solver.setLogic(theory)
        solver.setOption("produce-interpolants", "true")
        symbols: dict[str, Any] = {}
        a_term = _to_cvc5(partition_a, solver, symbols, cvc5.Kind)
        b_term = _to_cvc5(partition_b, solver, symbols, cvc5.Kind)
        solver.assertFormula(a_term)
        # cvc5 expects A => conjecture; conjecture is not(B).
        candidate = solver.getInterpolant(solver.mkTerm(cvc5.Kind.NOT, b_term))
        interpolant = _from_cvc5(candidate, cvc5.Kind)
    except (RuntimeError, InterpolationError) as error:
        return ValidatedInterpolantReceipt(
            InterpolationStatus.UNKNOWN,
            a_cid,
            b_cid,
            shared,
            None,
            (),
            "cvc5",
            str(cvc5.__version__),
            theory,
            reason=str(error),
        )
    vocabulary = tuple(sorted(_symbols(interpolant)))
    if not set(vocabulary) <= set(shared):
        return ValidatedInterpolantReceipt(
            InterpolationStatus.INVALID,
            a_cid,
            b_cid,
            shared,
            interpolant,
            vocabulary,
            "cvc5",
            str(cvc5.__version__),
            theory,
            reason="interpolant uses symbols outside shared vocabulary",
        )
    request_root = canonical_identity(
        {"a": a_cid, "b": b_cid, "provider": str(cvc5.__version__), "theory": theory},
        domain="logic.backends.smt.interpolation-request",
        schema_version="interpolation-request/v1",
    ).digest
    valid, first_receipt, second_receipt = _validate_with_z3(
        partition_a=partition_a,
        partition_b=partition_b,
        interpolant=interpolant,
        symbols=tuple(sorted(_symbols(partition_a) | _symbols(partition_b))),
        request_root=request_root,
    )
    return ValidatedInterpolantReceipt(
        InterpolationStatus.VALIDATED if valid else InterpolationStatus.INVALID,
        a_cid,
        b_cid,
        shared,
        interpolant,
        vocabulary,
        "cvc5",
        str(cvc5.__version__),
        theory,
        first_receipt,
        second_receipt,
        "" if valid else "independent implication or inconsistency check failed",
        ("experimental_cvc5_interpolation_api", "qualified_qf_lia_fragment_only"),
    )


__all__ = [
    "INTERPOLATION_INTERFACE",
    "INTERPOLATION_RECEIPT_SCHEMA",
    "InterpolationError",
    "InterpolationStatus",
    "ValidatedInterpolantReceipt",
    "compute_and_validate_interpolant",
]

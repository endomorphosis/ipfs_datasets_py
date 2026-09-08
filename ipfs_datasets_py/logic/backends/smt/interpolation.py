"""Capability-negotiated Craig interpolation with independent validation.

The qualified producer is cvc5 on the declared QF_LIA fragment.  Solver
availability is not interpolation support: Z3 is the preferred independent
validator and unsat-core fallback.  When Z3 is absent, a sound unary QF_LIA
fragment checker admits or rejects candidates and cores without inventing an
interpolant.  No interpolant is admitted merely because a provider returned a
term.  Admission requires:

* ``A => I`` on a fresh Z3 session, or the local fragment checker;
* ``I & B`` unsatisfiable on a second fresh Z3 session, or the fragment checker;
* interpolant vocabulary is contained in the structural shared vocabulary;
* partition, interpolant, and receipt identities; and
* explicit bounds on theory, symbols, term size, timeout, and memory.

An unsupported theory, absent interpolation API, provider error, or failed
check yields a typed non-success.  When interpolation itself is unavailable, a
validated unsat core of ``A & B`` is reported as fallback authority and is
never rewritten into an interpolant.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.smt.compiler import (
    INT_SORT,
    SmtTerm,
    SmtTermKind,
    term_and,
    term_not,
    term_or,
)
from ipfs_datasets_py.logic.backends.smt.incremental import (
    IncrementalSmtError,
    IncrementalSmtUnavailable,
    SmtCheckStatus,
    open_incremental_smt_session,
)
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity

INTERPOLATION_INTERFACE: Final = "ValidatedCraigInterpolation@1"
INTERPOLATION_RECEIPT_SCHEMA: Final = "validated-craig-interpolant/v1"
INTERPOLATION_CAPABILITY_SCHEMA: Final = "interpolation-capability/v1"
INTERPOLATION_BOUNDS_SCHEMA: Final = "interpolation-bounds/v1"
QUALIFIED_INTERPOLATION_PROVIDER: Final = "cvc5"
QUALIFIED_INTERPOLATION_THEORY: Final = "QF_LIA"
INDEPENDENT_VALIDATOR: Final = "z3"
FRAGMENT_CHECKER: Final = "qf-lia-fragment-checker@1"
VALIDATOR_ENVIRONMENT: Final = "local-independent-z3-validator@1"
FALLBACK_ENVIRONMENT: Final = "local-unsat-core-fallback@1"
FRAGMENT_ENVIRONMENT: Final = "local-qf-lia-fragment-checker@1"
TRANSLATOR_IDENTITY: Final = "cvc5-interpolant-to-structured-smt-term@1"
THEORY_FINGERPRINT: Final = "QF_LIA@1"
DEFAULT_TIMEOUT_MS: Final = 5_000
DEFAULT_MEMORY_LIMIT_MIB: Final = 512
DEFAULT_MAX_SYMBOLS: Final = 64
DEFAULT_MAX_TERM_NODES: Final = 256
QUALIFIED_LIMITATIONS: Final = (
    "experimental_cvc5_interpolation_api",
    "independent_z3_validation_is_solver_diversity_not_kernel_reconstruction",
    "qualified_qf_lia_fragment_only",
)
FALLBACK_LIMITATIONS: Final = (
    "fallback_is_not_an_interpolant",
    "interpolation_unavailable_unsat_core_fallback",
    "qualified_qf_lia_fragment_only",
)


class InterpolationError(ValueError):
    """Raised for malformed interpolation requests or receipts."""


class InterpolationStatus(StrEnum):
    VALIDATED = "validated"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    FALLBACK = "fallback"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise InterpolationError(f"{label} must be a trimmed non-empty string")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InterpolationError(f"{label} must be a positive integer")
    return value


def _require_term(value: object, label: str) -> SmtTerm:
    if not isinstance(value, SmtTerm):
        raise InterpolationError(f"{label} must be an SmtTerm")
    return value


@dataclass(frozen=True, slots=True)
class InterpolationBounds:
    """Explicit resource and fragment limits that travel with receipts."""

    timeout_ms: int = DEFAULT_TIMEOUT_MS
    memory_limit_mib: int = DEFAULT_MEMORY_LIMIT_MIB
    max_symbols: int = DEFAULT_MAX_SYMBOLS
    max_term_nodes: int = DEFAULT_MAX_TERM_NODES
    theory: str = QUALIFIED_INTERPOLATION_THEORY
    schema: str = INTERPOLATION_BOUNDS_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "timeout_ms", _positive_int(self.timeout_ms, "timeout_ms"))
        object.__setattr__(
            self, "memory_limit_mib", _positive_int(self.memory_limit_mib, "memory_limit_mib")
        )
        object.__setattr__(self, "max_symbols", _positive_int(self.max_symbols, "max_symbols"))
        object.__setattr__(
            self, "max_term_nodes", _positive_int(self.max_term_nodes, "max_term_nodes")
        )
        object.__setattr__(self, "theory", _text(self.theory, "theory"))
        if self.schema != INTERPOLATION_BOUNDS_SCHEMA:
            raise InterpolationError("unsupported interpolation bounds schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_symbols": self.max_symbols,
            "max_term_nodes": self.max_term_nodes,
            "memory_limit_mib": self.memory_limit_mib,
            "schema": self.schema,
            "theory": self.theory,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True, slots=True)
class InterpolationCapability:
    """Exact local interpolation support for one provider/theory pair."""

    provider: str
    theory: str
    provider_installed: bool
    provider_version: str
    interpolation_api: bool
    interpolation_api_name: str
    independent_validator_installed: bool
    independent_validator: str
    independent_validator_version: str
    theory_qualified: bool
    provider_qualified: bool
    qualified: bool
    reason: str
    limitations: tuple[str, ...] = ()
    schema: str = INTERPOLATION_CAPABILITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(self, "theory", _text(self.theory, "theory"))
        object.__setattr__(self, "provider_version", str(self.provider_version))
        object.__setattr__(self, "interpolation_api_name", str(self.interpolation_api_name))
        object.__setattr__(
            self, "independent_validator", _text(self.independent_validator, "independent_validator")
        )
        object.__setattr__(
            self, "independent_validator_version", str(self.independent_validator_version)
        )
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        for name in (
            "provider_installed",
            "interpolation_api",
            "independent_validator_installed",
            "theory_qualified",
            "provider_qualified",
            "qualified",
        ):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise InterpolationError(f"{name} must be a boolean")
        if self.qualified and not (
            self.provider_installed
            and self.interpolation_api
            and self.independent_validator_installed
            and self.theory_qualified
            and self.provider_qualified
        ):
            raise InterpolationError("qualified capability requires exact producer and validator support")
        if self.schema != INTERPOLATION_CAPABILITY_SCHEMA:
            raise InterpolationError("unsupported interpolation capability schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "independent_validator": self.independent_validator,
            "independent_validator_installed": self.independent_validator_installed,
            "independent_validator_version": self.independent_validator_version,
            "interpolation_api": self.interpolation_api,
            "interpolation_api_name": self.interpolation_api_name,
            "limitations": list(self.limitations),
            "provider": self.provider,
            "provider_installed": self.provider_installed,
            "provider_qualified": self.provider_qualified,
            "provider_version": self.provider_version,
            "qualified": self.qualified,
            "reason": self.reason,
            "schema": self.schema,
            "theory": self.theory,
            "theory_qualified": self.theory_qualified,
        }


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
    interpolant_cid: str = ""
    a_implies_i: bool = False
    i_and_b_unsat: bool = False
    shared_vocabulary_ok: bool = False
    identity_ok: bool = False
    bounds_ok: bool = False
    fallback_kind: str = ""
    fallback_core: tuple[str, ...] = ()
    fallback_receipt: str = ""
    fallback_validated: bool = False
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    memory_limit_mib: int = DEFAULT_MEMORY_LIMIT_MIB
    max_symbols: int = DEFAULT_MAX_SYMBOLS
    max_term_nodes: int = DEFAULT_MAX_TERM_NODES
    interpolation_api: bool = False
    independent_validator: str = INDEPENDENT_VALIDATOR
    independent_validator_version: str = ""
    interface: str = INTERPOLATION_INTERFACE

    INTERFACE: ClassVar[str] = INTERPOLATION_INTERFACE

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
        object.__setattr__(self, "partition_a_cid", _text(self.partition_a_cid, "partition_a_cid"))
        object.__setattr__(self, "partition_b_cid", _text(self.partition_b_cid, "partition_b_cid"))
        object.__setattr__(self, "shared_vocabulary", tuple(sorted(set(self.shared_vocabulary))))
        object.__setattr__(
            self, "interpolant_vocabulary", tuple(sorted(set(self.interpolant_vocabulary)))
        )
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(self, "provider_version", str(self.provider_version))
        object.__setattr__(self, "theory", _text(self.theory, "theory"))
        object.__setattr__(self, "a_implies_i_receipt", str(self.a_implies_i_receipt))
        object.__setattr__(self, "i_and_b_unsat_receipt", str(self.i_and_b_unsat_receipt))
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        object.__setattr__(self, "interpolant_cid", str(self.interpolant_cid))
        object.__setattr__(self, "fallback_kind", str(self.fallback_kind))
        object.__setattr__(self, "fallback_core", tuple(sorted(set(self.fallback_core))))
        object.__setattr__(self, "fallback_receipt", str(self.fallback_receipt))
        object.__setattr__(self, "independent_validator", str(self.independent_validator))
        object.__setattr__(
            self, "independent_validator_version", str(self.independent_validator_version)
        )
        object.__setattr__(self, "interface", _text(self.interface, "interface"))
        if self.interpolant is not None and not isinstance(self.interpolant, SmtTerm):
            raise InterpolationError("interpolant must be an SmtTerm or None")
        for name in (
            "a_implies_i",
            "i_and_b_unsat",
            "shared_vocabulary_ok",
            "identity_ok",
            "bounds_ok",
            "fallback_validated",
            "interpolation_api",
        ):
            if not isinstance(getattr(self, name), bool):
                raise InterpolationError(f"{name} must be a boolean")
        object.__setattr__(self, "timeout_ms", _positive_int(self.timeout_ms, "timeout_ms"))
        object.__setattr__(
            self, "memory_limit_mib", _positive_int(self.memory_limit_mib, "memory_limit_mib")
        )
        object.__setattr__(self, "max_symbols", _positive_int(self.max_symbols, "max_symbols"))
        object.__setattr__(
            self, "max_term_nodes", _positive_int(self.max_term_nodes, "max_term_nodes")
        )
        if self.schema != INTERPOLATION_RECEIPT_SCHEMA:
            raise InterpolationError("unsupported interpolation receipt schema")
        if self.interface != INTERPOLATION_INTERFACE:
            raise InterpolationError("unsupported interpolation interface")
        if status == InterpolationStatus.VALIDATED:
            if self.interpolant is None:
                raise InterpolationError("validated receipt requires an interpolant")
            if not self.admission_checks_passed:
                raise InterpolationError("validated receipt requires all admission checks")
        if status == InterpolationStatus.FALLBACK:
            if self.interpolant is not None:
                raise InterpolationError("fallback receipt must not fabricate an interpolant")
            if not self.fallback_validated or not self.fallback_kind or not self.fallback_receipt:
                raise InterpolationError("fallback receipt requires validated fallback authority")

    @property
    def admission_checks_passed(self) -> bool:
        return (
            self.a_implies_i
            and self.i_and_b_unsat
            and self.shared_vocabulary_ok
            and self.identity_ok
            and self.bounds_ok
        )

    @property
    def receipt_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="logic.backends.smt.validated-interpolant",
            schema_version=self.schema,
        ).cid

    def checks(self) -> dict[str, bool]:
        return {
            "a_implies_i": self.a_implies_i,
            "bounds": self.bounds_ok,
            "i_and_b_unsat": self.i_and_b_unsat,
            "identity": self.identity_ok,
            "shared_vocabulary": self.shared_vocabulary_ok,
        }

    def to_dict(self) -> dict[str, Any]:
        status = self.status
        return {
            "a_implies_i": self.a_implies_i,
            "a_implies_i_receipt": self.a_implies_i_receipt,
            "bounds_ok": self.bounds_ok,
            "checks": self.checks(),
            "fallback_core": list(self.fallback_core),
            "fallback_kind": self.fallback_kind,
            "fallback_receipt": self.fallback_receipt,
            "fallback_validated": self.fallback_validated,
            "i_and_b_unsat": self.i_and_b_unsat,
            "i_and_b_unsat_receipt": self.i_and_b_unsat_receipt,
            "identity_ok": self.identity_ok,
            "independent_validator": self.independent_validator,
            "independent_validator_version": self.independent_validator_version,
            "interface": self.interface,
            "interpolant": None if self.interpolant is None else self.interpolant.to_dict(),
            "interpolant_cid": self.interpolant_cid,
            "interpolant_vocabulary": list(self.interpolant_vocabulary),
            "interpolation_api": self.interpolation_api,
            "limitations": list(self.limitations),
            "max_symbols": self.max_symbols,
            "max_term_nodes": self.max_term_nodes,
            "memory_limit_mib": self.memory_limit_mib,
            "partition_a_cid": self.partition_a_cid,
            "partition_b_cid": self.partition_b_cid,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "reason": self.reason,
            "schema": self.schema,
            "shared_vocabulary": list(self.shared_vocabulary),
            "shared_vocabulary_ok": self.shared_vocabulary_ok,
            "status": status.value if isinstance(status, InterpolationStatus) else status,
            "theory": self.theory,
            "timeout_ms": self.timeout_ms,
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


def _term_nodes(term: SmtTerm) -> int:
    return 1 + sum(_term_nodes(item) for item in term.arguments)


def _load_module(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    # An optional native solver can fail while its extension is loaded (for
    # example, because a linked shared library is unavailable).  Treat that
    # exactly like an absent optional provider; capability discovery must not
    # turn an environmental dependency failure into an exception or a claim
    # of usable interpolation support.
    except (ImportError, OSError):
        return None


def _module_version(module: Any, provider: str) -> str:
    if provider == "z3" and hasattr(module, "get_version_string"):
        return str(module.get_version_string())
    return str(getattr(module, "__version__", "unknown"))


def _interpolation_api(module: Any, provider: str) -> tuple[bool, str]:
    if provider == QUALIFIED_INTERPOLATION_PROVIDER:
        solver = getattr(module, "Solver", None)
        if solver is not None and callable(getattr(solver, "getInterpolant", None)):
            return True, "Solver.getInterpolant"
        return False, ""
    if callable(getattr(module, "interpolate", None)):
        return True, "interpolate"
    if callable(getattr(module, "Interpolant", None)):
        return True, "Interpolant"
    return False, ""


def probe_interpolation_support(
    *,
    provider: str = QUALIFIED_INTERPOLATION_PROVIDER,
    theory: str = QUALIFIED_INTERPOLATION_THEORY,
) -> InterpolationCapability:
    """Probe exact local interpolation support without installing anything.

    A present SAT solver is not interpolation support.  Qualification requires
    the declared producer, the declared theory, the interpolation API, and an
    independent validator.
    """

    provider = _text(provider, "provider")
    theory = _text(theory, "theory")
    producer = _load_module(provider)
    validator = _load_module(INDEPENDENT_VALIDATOR)
    producer_version = "unavailable" if producer is None else _module_version(producer, provider)
    validator_version = (
        "unavailable" if validator is None else _module_version(validator, INDEPENDENT_VALIDATOR)
    )
    api_present, api_name = (False, "") if producer is None else _interpolation_api(producer, provider)
    theory_qualified = theory == QUALIFIED_INTERPOLATION_THEORY
    provider_qualified = provider == QUALIFIED_INTERPOLATION_PROVIDER
    producer_installed = producer is not None
    validator_installed = validator is not None
    if not producer_installed:
        reason = f"{provider} Python API is not installed"
    elif not provider_qualified:
        reason = (
            f"{provider} solver availability is not qualified interpolation support"
        )
    elif not api_present:
        reason = "installed provider has no interpolation API"
    elif not theory_qualified:
        reason = "initial adapter is qualified only for QF_LIA"
    elif not validator_installed:
        reason = "independent Z3 validator is not installed"
    else:
        reason = (
            f"qualified {QUALIFIED_INTERPOLATION_PROVIDER} {QUALIFIED_INTERPOLATION_THEORY} "
            "interpolation with independent Z3 admission"
        )
    qualified = (
        producer_installed
        and provider_qualified
        and api_present
        and theory_qualified
        and validator_installed
    )
    return InterpolationCapability(
        provider=provider,
        theory=theory,
        provider_installed=producer_installed,
        provider_version=producer_version,
        interpolation_api=api_present,
        interpolation_api_name=api_name,
        independent_validator_installed=validator_installed,
        independent_validator=INDEPENDENT_VALIDATOR,
        independent_validator_version=validator_version,
        theory_qualified=theory_qualified,
        provider_qualified=provider_qualified,
        qualified=qualified,
        reason=reason,
        limitations=QUALIFIED_LIMITATIONS,
    )


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
        SmtTermKind.ITE: getattr(kind, "ITE", None),
        SmtTermKind.NEG: getattr(kind, "NEG", None),
        SmtTermKind.DISTINCT: getattr(kind, "DISTINCT", None),
    }
    operation = operations.get(term.kind)
    if operation is None:
        raise InterpolationError(f"unsupported QF_LIA term {term.kind.value}")
    return solver.mkTerm(operation, *children)


def _from_cvc5(term: Any, kind: Any) -> SmtTerm:
    if hasattr(term, "isNull") and term.isNull():
        raise InterpolationError("provider returned a null interpolant")
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
    for name, mapped in (
        ("ITE", SmtTermKind.ITE),
        ("NEG", SmtTermKind.NEG),
        ("DISTINCT", SmtTermKind.DISTINCT),
    ):
        mapped_kind = getattr(kind, name, None)
        if mapped_kind is not None:
            reverse[mapped_kind] = mapped
    term_kind = term.getKind()
    if term_kind not in reverse:
        raise InterpolationError(f"provider returned unsupported interpolant kind {term_kind}")
    return SmtTerm(reverse[term_kind], arguments=tuple(_from_cvc5(item, kind) for item in term))


def _open_z3_session(session_id: str, request_root: str, environment_root: str, bounds: InterpolationBounds):
    return open_incremental_smt_session(
        session_id=session_id,
        translator_identity=TRANSLATOR_IDENTITY,
        theory_fingerprint=THEORY_FINGERPRINT,
        policy_root=request_root,
        configuration_root=request_root,
        environment_root=environment_root,
        timeout_ms=bounds.timeout_ms,
        memory_limit_mib=bounds.memory_limit_mib,
    )


def _declare_symbols(session: Any, symbols: tuple[str, ...]) -> None:
    for symbol in symbols:
        session.declare_symbol(symbol, INT_SORT)


def _evaluate_bounds(
    *,
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    interpolant: SmtTerm | None,
    theory: str,
    bounds: InterpolationBounds,
) -> tuple[bool, str]:
    if theory != bounds.theory:
        return False, f"request theory {theory!r} is outside bounds theory {bounds.theory!r}"
    if theory != QUALIFIED_INTERPOLATION_THEORY:
        return False, "initial adapter is qualified only for QF_LIA"
    for label, term in (("partition_a", partition_a), ("partition_b", partition_b)):
        fragment_error = _qf_lia_term_error(term)
        if fragment_error:
            return False, f"{label} is outside the qualified QF_LIA fragment: {fragment_error}"
    if interpolant is not None:
        fragment_error = _qf_lia_term_error(interpolant)
        if fragment_error:
            return False, f"interpolant is outside the qualified QF_LIA fragment: {fragment_error}"
    symbols = _symbols(partition_a) | _symbols(partition_b)
    if interpolant is not None:
        symbols |= _symbols(interpolant)
    if len(symbols) > bounds.max_symbols:
        return False, f"symbol count {len(symbols)} exceeds max_symbols {bounds.max_symbols}"
    for label, term in (("partition_a", partition_a), ("partition_b", partition_b)):
        size = _term_nodes(term)
        if size > bounds.max_term_nodes:
            return False, f"{label} has {size} nodes exceeding max_term_nodes {bounds.max_term_nodes}"
    if interpolant is not None:
        size = _term_nodes(interpolant)
        if size > bounds.max_term_nodes:
            return False, f"interpolant has {size} nodes exceeding max_term_nodes {bounds.max_term_nodes}"
    return True, ""


def _qf_lia_term_error(term: SmtTerm) -> str:
    """Return why ``term`` is outside the structured QF_LIA subset, if any.

    The shared structured-term IR is deliberately broader than QF_LIA.  In
    particular, accepting ``(* x y)`` merely because cvc5 happens to parse it
    would make the QF_LIA qualification misleading.  Restrict multiplication
    to a constant coefficient and reject constructs that this adapter cannot
    translate faithfully before provider invocation.
    """

    allowed = {
        SmtTermKind.TRUE,
        SmtTermKind.FALSE,
        SmtTermKind.INT,
        SmtTermKind.SYMBOL,
        SmtTermKind.NOT,
        SmtTermKind.AND,
        SmtTermKind.OR,
        SmtTermKind.IMPLIES,
        SmtTermKind.IFF,
        SmtTermKind.EQ,
        SmtTermKind.DISTINCT,
        SmtTermKind.ITE,
        SmtTermKind.LT,
        SmtTermKind.LE,
        SmtTermKind.GT,
        SmtTermKind.GE,
        SmtTermKind.ADD,
        SmtTermKind.SUB,
        SmtTermKind.MUL,
        SmtTermKind.NEG,
    }
    if term.kind not in allowed:
        return f"unsupported term kind {term.kind.value}"
    if term.kind is SmtTermKind.MUL:
        non_constant_factors = sum(
            item.kind is not SmtTermKind.INT for item in term.arguments
        )
        if non_constant_factors > 1:
            return "non-linear multiplication"
    for item in term.arguments:
        nested_error = _qf_lia_term_error(item)
        if nested_error:
            return nested_error
    return ""


def _linear_coeffs(term: SmtTerm) -> tuple[dict[str, int], int] | None:
    """Return ``(symbol coefficients, constant)`` for a linear integer term."""

    if term.kind is SmtTermKind.INT:
        return {}, int(term.value)
    if term.kind is SmtTermKind.SYMBOL:
        return {str(term.value): 1}, 0
    if term.kind is SmtTermKind.NEG and term.arguments:
        inner = _linear_coeffs(term.arguments[0])
        if inner is None:
            return None
        coeffs, constant = inner
        return {name: -coeff for name, coeff in coeffs.items()}, -constant
    if term.kind is SmtTermKind.ADD:
        coeffs: dict[str, int] = {}
        constant = 0
        for item in term.arguments:
            part = _linear_coeffs(item)
            if part is None:
                return None
            part_coeffs, part_constant = part
            constant += part_constant
            for name, coeff in part_coeffs.items():
                coeffs[name] = coeffs.get(name, 0) + coeff
        return {name: coeff for name, coeff in coeffs.items() if coeff}, constant
    if term.kind is SmtTermKind.SUB and len(term.arguments) == 2:
        left = _linear_coeffs(term.arguments[0])
        right = _linear_coeffs(term.arguments[1])
        if left is None or right is None:
            return None
        coeffs = dict(left[0])
        for name, coeff in right[0].items():
            coeffs[name] = coeffs.get(name, 0) - coeff
        return {name: coeff for name, coeff in coeffs.items() if coeff}, left[1] - right[1]
    if term.kind is SmtTermKind.MUL:
        acc_coeffs: dict[str, int] = {}
        acc_constant = 1
        started = False
        for item in term.arguments:
            part = _linear_coeffs(item)
            if part is None:
                return None
            part_coeffs, part_constant = part
            if not started:
                acc_coeffs, acc_constant = dict(part_coeffs), part_constant
                started = True
                continue
            if acc_coeffs and part_coeffs:
                return None
            if part_coeffs:
                acc_coeffs = {
                    name: coeff * acc_constant
                    for name, coeff in part_coeffs.items()
                    if coeff * acc_constant
                }
                acc_constant *= part_constant
            else:
                acc_coeffs = {
                    name: coeff * part_constant
                    for name, coeff in acc_coeffs.items()
                    if coeff * part_constant
                }
                acc_constant *= part_constant
        if not started:
            return None
        return acc_coeffs, acc_constant
    return None


def _floor_div(numerator: int, denominator: int) -> int:
    return numerator // denominator


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _meet_bound(
    env: dict[str, tuple[int | None, int | None]],
    symbol: str,
    *,
    low: int | None = None,
    high: int | None = None,
) -> bool:
    current_low, current_high = env.get(symbol, (None, None))
    if low is not None:
        current_low = low if current_low is None else max(current_low, low)
    if high is not None:
        current_high = high if current_high is None else min(current_high, high)
    if current_low is not None and current_high is not None and current_low > current_high:
        return False
    env[symbol] = (current_low, current_high)
    return True


def _apply_comparison(
    term: SmtTerm,
    env: dict[str, tuple[int | None, int | None]],
) -> bool | None:
    """Apply a unary linear comparison to ``env``.  ``None`` means unsupported."""

    relations = {
        SmtTermKind.LE: "le",
        SmtTermKind.LT: "lt",
        SmtTermKind.GE: "ge",
        SmtTermKind.GT: "gt",
        SmtTermKind.EQ: "eq",
    }
    relation = relations.get(term.kind)
    if relation is None or len(term.arguments) != 2:
        return None
    left = _linear_coeffs(term.arguments[0])
    right = _linear_coeffs(term.arguments[1])
    if left is None or right is None:
        return None
    coeffs = dict(left[0])
    for name, coeff in right[0].items():
        coeffs[name] = coeffs.get(name, 0) - coeff
    coeffs = {name: coeff for name, coeff in coeffs.items() if coeff}
    constant = left[1] - right[1]
    if not coeffs:
        if relation == "le":
            return constant <= 0
        if relation == "lt":
            return constant < 0
        if relation == "ge":
            return constant >= 0
        if relation == "gt":
            return constant > 0
        return constant == 0
    if len(coeffs) != 1:
        return None
    symbol, coeff = next(iter(coeffs.items()))
    # ``coeff * x + constant ⋈ 0``.
    if relation == "eq":
        if constant % coeff != 0:
            return False
        value = -constant // coeff
        return _meet_bound(env, symbol, low=value, high=value)
    if relation == "lt":
        upper_or_lower = -constant - 1
        relation = "le"
        rhs = upper_or_lower
    elif relation == "gt":
        upper_or_lower = -constant + 1
        relation = "ge"
        rhs = upper_or_lower
    else:
        rhs = -constant
    if relation == "le":
        if coeff > 0:
            return _meet_bound(env, symbol, high=_floor_div(rhs, coeff))
        return _meet_bound(env, symbol, low=_ceil_div(rhs, coeff))
    if coeff > 0:
        return _meet_bound(env, symbol, low=_ceil_div(rhs, coeff))
    return _meet_bound(env, symbol, high=_floor_div(rhs, coeff))


def _flip_comparison(term: SmtTerm) -> SmtTerm | None:
    flipped = {
        SmtTermKind.LE: SmtTermKind.GT,
        SmtTermKind.LT: SmtTermKind.GE,
        SmtTermKind.GE: SmtTermKind.LT,
        SmtTermKind.GT: SmtTermKind.LE,
    }.get(term.kind)
    if flipped is None or len(term.arguments) != 2:
        return None
    return SmtTerm(flipped, arguments=term.arguments)


_DNF_CUBE_LIMIT: Final = 64


def _nnf(term: SmtTerm, *, negated: bool = False) -> SmtTerm | None:
    """Rewrite ``term`` into negation-normal form, or ``None`` if unsupported."""

    kind = term.kind
    if kind is SmtTermKind.TRUE:
        return SmtTerm(SmtTermKind.FALSE if negated else SmtTermKind.TRUE)
    if kind is SmtTermKind.FALSE:
        return SmtTerm(SmtTermKind.TRUE if negated else SmtTermKind.FALSE)
    if kind is SmtTermKind.NOT and term.arguments:
        return _nnf(term.arguments[0], negated=not negated)
    if kind is SmtTermKind.AND:
        parts = [_nnf(item, negated=negated) for item in term.arguments]
        rewritten = [item for item in parts if item is not None]
        if len(rewritten) != len(parts):
            return None
        return (term_or if negated else term_and)(*rewritten)
    if kind is SmtTermKind.OR:
        parts = [_nnf(item, negated=negated) for item in term.arguments]
        rewritten = [item for item in parts if item is not None]
        if len(rewritten) != len(parts):
            return None
        return (term_and if negated else term_or)(*rewritten)
    if kind is SmtTermKind.IMPLIES and len(term.arguments) == 2:
        return _nnf(
            term_or(term_not(term.arguments[0]), term.arguments[1]),
            negated=negated,
        )
    if kind is SmtTermKind.IFF and len(term.arguments) == 2:
        left, right = term.arguments
        return _nnf(
            term_or(
                term_and(left, right),
                term_and(term_not(left), term_not(right)),
            ),
            negated=negated,
        )
    if kind is SmtTermKind.ITE and len(term.arguments) == 3:
        condition, then_term, else_term = term.arguments
        return _nnf(
            term_or(
                term_and(condition, then_term),
                term_and(term_not(condition), else_term),
            ),
            negated=negated,
        )
    if kind is SmtTermKind.EQ and len(term.arguments) == 2:
        if negated:
            return term_or(
                SmtTerm(SmtTermKind.LT, arguments=term.arguments),
                SmtTerm(SmtTermKind.GT, arguments=term.arguments),
            )
        return term
    if kind in {
        SmtTermKind.LE,
        SmtTermKind.LT,
        SmtTermKind.GE,
        SmtTermKind.GT,
    }:
        if negated:
            return _flip_comparison(term)
        return term
    return None


def _flatten_connective(term: SmtTerm, kind: SmtTermKind) -> tuple[SmtTerm, ...]:
    if term.kind is kind:
        flattened: list[SmtTerm] = []
        for item in term.arguments:
            flattened.extend(_flatten_connective(item, kind))
        return tuple(flattened)
    return (term,)


def _dnf(term: SmtTerm) -> list[tuple[SmtTerm, ...]] | None:
    """Distribute AND over OR, returning cubes of atoms.  ``None`` if too large."""

    if term.kind is SmtTermKind.OR:
        cubes: list[tuple[SmtTerm, ...]] = []
        for item in _flatten_connective(term, SmtTermKind.OR):
            part = _dnf(item)
            if part is None:
                return None
            cubes.extend(part)
            if len(cubes) > _DNF_CUBE_LIMIT:
                return None
        return cubes
    if term.kind is SmtTermKind.AND:
        parts = [_dnf(item) for item in _flatten_connective(term, SmtTermKind.AND)]
        if any(item is None for item in parts):
            return None
        cubes = [()]
        for options in parts:
            next_cubes: list[tuple[SmtTerm, ...]] = []
            for prefix in cubes:
                for option in options:
                    next_cubes.append(prefix + option)
                    if len(next_cubes) > _DNF_CUBE_LIMIT:
                        return None
            cubes = next_cubes
        return cubes
    return [(term,)]


def _qf_lia_sat(term: SmtTerm, env: dict[str, tuple[int | None, int | None]] | None = None) -> bool | None:
    """Sound SAT for the unary QF_LIA fragment; ``None`` if undecided.

    Satisfiable answers come from a consistent cube of unary linear bounds.
    Unsatisfiable answers require every cube to be empty.  Multi-variable or
    unsupported atoms make the checker return ``None`` rather than guess.
    """

    del env
    nnf = _nnf(term)
    if nnf is None:
        return None
    cubes = _dnf(nnf)
    if cubes is None:
        return None
    unknown = False
    for cube in cubes:
        state: dict[str, tuple[int | None, int | None]] = {}
        consistent = True
        for atom in cube:
            if atom.kind is SmtTermKind.TRUE:
                continue
            if atom.kind is SmtTermKind.FALSE:
                consistent = False
                break
            applied = _apply_comparison(atom, state)
            if applied is None:
                unknown = True
                consistent = False
                break
            if applied is False:
                consistent = False
                break
        if consistent:
            return True
    if unknown:
        return None
    return False


def _fragment_check_receipt(label: str, terms: tuple[SmtTerm, ...], result: str) -> str:
    return canonical_identity(
        {
            "checker": FRAGMENT_CHECKER,
            "environment": FRAGMENT_ENVIRONMENT,
            "label": label,
            "result": result,
            "terms": [item.to_dict() for item in terms],
        },
        domain="logic.backends.smt.interpolation-fragment-check",
        schema_version="interpolation-fragment-check/v1",
    ).cid


def _validate_with_fragment(
    *,
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    interpolant: SmtTerm,
) -> tuple[bool, bool, str, str, str]:
    a_and_not_i = _qf_lia_sat(term_and(partition_a, term_not(interpolant)))
    i_and_b = _qf_lia_sat(term_and(interpolant, partition_b))
    if a_and_not_i is None or i_and_b is None:
        return (
            False,
            False,
            "",
            "",
            "independent validator unavailable: fragment checker could not decide QF_LIA query",
        )
    a_implies_i = a_and_not_i is False
    i_and_b_unsat = i_and_b is False
    first_receipt = _fragment_check_receipt(
        "a-implies-i",
        (partition_a, interpolant),
        "unsat" if a_implies_i else "sat",
    )
    second_receipt = _fragment_check_receipt(
        "i-and-b",
        (interpolant, partition_b),
        "unsat" if i_and_b_unsat else "sat",
    )
    reason = ""
    if not a_implies_i:
        reason = "A does not imply I"
    elif not i_and_b_unsat:
        reason = "I and B is not unsatisfiable"
    return a_implies_i, i_and_b_unsat, first_receipt, second_receipt, reason


def _unsat_core_with_fragment(
    partition_a: SmtTerm,
    partition_b: SmtTerm,
) -> tuple[bool, str, tuple[str, ...], str]:
    a_sat = _qf_lia_sat(partition_a)
    b_sat = _qf_lia_sat(partition_b)
    both = _qf_lia_sat(term_and(partition_a, partition_b))
    if both is True:
        receipt = _fragment_check_receipt("core-fallback", (partition_a, partition_b), "sat")
        return False, receipt, (), "A and B are jointly satisfiable"
    if a_sat is False:
        core = ("partition-a",)
        receipt = _fragment_check_receipt("core-fallback", (partition_a,), "unsat")
        return True, receipt, core, ""
    if b_sat is False:
        core = ("partition-b",)
        receipt = _fragment_check_receipt("core-fallback", (partition_b,), "unsat")
        return True, receipt, core, ""
    if both is False:
        core = ("partition-a", "partition-b")
        receipt = _fragment_check_receipt("core-fallback", (partition_a, partition_b), "unsat")
        return True, receipt, core, ""
    return (
        False,
        "",
        (),
        "unsat-core fallback unavailable: fragment checker could not decide QF_LIA query",
    )


def _identity_holds(
    *,
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    interpolant: SmtTerm | None,
    partition_a_cid: str,
    partition_b_cid: str,
    interpolant_cid: str,
    shared_vocabulary: tuple[str, ...],
    interpolant_vocabulary: tuple[str, ...],
) -> bool:
    if _term_cid(partition_a, "a") != partition_a_cid:
        return False
    if _term_cid(partition_b, "b") != partition_b_cid:
        return False
    expected_shared = tuple(sorted(_symbols(partition_a) & _symbols(partition_b)))
    if tuple(sorted(shared_vocabulary)) != expected_shared:
        return False
    if interpolant is None:
        return interpolant_cid == "" and interpolant_vocabulary == ()
    return (
        _term_cid(interpolant, "i") == interpolant_cid
        and tuple(sorted(interpolant_vocabulary)) == tuple(sorted(_symbols(interpolant)))
    )


def _validate_with_z3(
    *,
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    interpolant: SmtTerm,
    symbols: tuple[str, ...],
    request_root: str,
    bounds: InterpolationBounds,
) -> tuple[bool, bool, str, str, str, str]:
    first = None
    second = None
    try:
        first = _open_z3_session("interpolant-a-implies-i", request_root, VALIDATOR_ENVIRONMENT, bounds)
        second = _open_z3_session("interpolant-i-and-b", request_root, VALIDATOR_ENVIRONMENT, bounds)
        _declare_symbols(first, symbols)
        _declare_symbols(second, symbols)
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
            "interpolant",
            interpolant,
            source_ref=_term_cid(interpolant, "i"),
            obligation_id="i-and-b",
        )
        second.add_named_assertion(
            "partition-b",
            partition_b,
            source_ref=_term_cid(partition_b, "b"),
            obligation_id="i-and-b",
        )
        second_result = second.check()
    except IncrementalSmtUnavailable:
        return (*_validate_with_fragment(
            partition_a=partition_a,
            partition_b=partition_b,
            interpolant=interpolant,
        ), FRAGMENT_CHECKER)
    except IncrementalSmtError as error:
        return False, False, "", "", f"independent validator rejected the candidate: {error}", INDEPENDENT_VALIDATOR
    finally:
        if first is not None:
            first.close()
        if second is not None:
            second.close()
    a_implies_i = (
        first_result.status is SmtCheckStatus.UNSAT and first_result.core_validated
    )
    i_and_b_unsat = (
        second_result.status is SmtCheckStatus.UNSAT and second_result.core_validated
    )
    reason = ""
    if first_result.status is SmtCheckStatus.TIMEOUT or second_result.status is SmtCheckStatus.TIMEOUT:
        reason = "independent validation timed out"
    elif first_result.status is SmtCheckStatus.UNKNOWN or second_result.status is SmtCheckStatus.UNKNOWN:
        reason = "independent validation returned unknown"
    elif not a_implies_i:
        reason = "A does not imply I"
    elif not i_and_b_unsat:
        reason = "I and B is not unsatisfiable"
    return (
        a_implies_i,
        i_and_b_unsat,
        first_result.receipt_id,
        second_result.receipt_id,
        reason,
        INDEPENDENT_VALIDATOR,
    )


def _unsat_core_fallback(
    *,
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    symbols: tuple[str, ...],
    request_root: str,
    bounds: InterpolationBounds,
) -> tuple[bool, str, tuple[str, ...], str]:
    session = None
    try:
        session = _open_z3_session(
            "interpolant-unsat-core-fallback",
            request_root,
            FALLBACK_ENVIRONMENT,
            bounds,
        )
        _declare_symbols(session, symbols)
        session.add_named_assertion(
            "partition-a",
            partition_a,
            source_ref=_term_cid(partition_a, "a"),
            obligation_id="core-fallback",
        )
        session.add_named_assertion(
            "partition-b",
            partition_b,
            source_ref=_term_cid(partition_b, "b"),
            obligation_id="core-fallback",
        )
        result = session.check()
    except IncrementalSmtUnavailable:
        return _unsat_core_with_fragment(partition_a, partition_b)
    except IncrementalSmtError as error:
        return False, "", (), f"unsat-core fallback rejected the partitions: {error}"
    finally:
        if session is not None:
            session.close()
    if result.status is SmtCheckStatus.SAT:
        return False, result.receipt_id, (), "A and B are jointly satisfiable"
    if result.status is SmtCheckStatus.UNSAT and result.core_validated:
        return True, result.receipt_id, result.unsat_core, ""
    return (
        False,
        result.receipt_id,
        result.unsat_core,
        result.unknown_reason or f"unsat-core fallback status {result.status.value}",
    )


def _request_root(partition_a_cid: str, partition_b_cid: str, provider_version: str, theory: str) -> str:
    return canonical_identity(
        {
            "a": partition_a_cid,
            "b": partition_b_cid,
            "provider": provider_version,
            "theory": theory,
        },
        domain="logic.backends.smt.interpolation-request",
        schema_version="interpolation-request/v1",
    ).digest


def _compute_cvc5_interpolant(
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    *,
    theory: str,
    module: Any,
    bounds: InterpolationBounds,
) -> SmtTerm:
    solver = module.Solver()
    solver.setLogic(theory)
    solver.setOption("produce-interpolants", "true")
    try:
        solver.setOption("tlimit-per", str(bounds.timeout_ms))
    except (RuntimeError, TypeError, ValueError):
        pass
    symbols: dict[str, Any] = {}
    a_term = _to_cvc5(partition_a, solver, symbols, module.Kind)
    b_term = _to_cvc5(partition_b, solver, symbols, module.Kind)
    solver.assertFormula(a_term)
    candidate = solver.getInterpolant(solver.mkTerm(module.Kind.NOT, b_term))
    if isinstance(candidate, tuple):
        candidate = candidate[-1] if candidate else None
    if candidate is None:
        raise InterpolationError("provider returned no interpolant")
    return _from_cvc5(candidate, module.Kind)


def admit_interpolant(
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    interpolant: SmtTerm,
    *,
    theory: str = QUALIFIED_INTERPOLATION_THEORY,
    provider: str = "independent",
    provider_version: str = "independent",
    bounds: InterpolationBounds | None = None,
    interpolation_api: bool = False,
    independent_validator_version: str = "",
    limitations: tuple[str, ...] = QUALIFIED_LIMITATIONS,
) -> ValidatedInterpolantReceipt:
    """Independently admit or reject a candidate interpolant."""

    partition_a = _require_term(partition_a, "partition_a")
    partition_b = _require_term(partition_b, "partition_b")
    interpolant = _require_term(interpolant, "interpolant")
    theory = _text(theory, "theory")
    provider = _text(provider, "provider")
    bounds = bounds or InterpolationBounds(theory=QUALIFIED_INTERPOLATION_THEORY)
    a_cid = _term_cid(partition_a, "a")
    b_cid = _term_cid(partition_b, "b")
    interpolant_cid = _term_cid(interpolant, "i")
    shared = tuple(sorted(_symbols(partition_a) & _symbols(partition_b)))
    vocabulary = tuple(sorted(_symbols(interpolant)))
    bounds_ok, bounds_reason = _evaluate_bounds(
        partition_a=partition_a,
        partition_b=partition_b,
        interpolant=interpolant,
        theory=theory,
        bounds=bounds,
    )
    shared_ok = set(vocabulary) <= set(shared)
    identity_ok = _identity_holds(
        partition_a=partition_a,
        partition_b=partition_b,
        interpolant=interpolant,
        partition_a_cid=a_cid,
        partition_b_cid=b_cid,
        interpolant_cid=interpolant_cid,
        shared_vocabulary=shared,
        interpolant_vocabulary=vocabulary,
    )
    common = {
        "partition_a_cid": a_cid,
        "partition_b_cid": b_cid,
        "shared_vocabulary": shared,
        "interpolant": interpolant,
        "interpolant_vocabulary": vocabulary,
        "provider": provider,
        "provider_version": provider_version,
        "theory": theory,
        "interpolant_cid": interpolant_cid,
        "shared_vocabulary_ok": shared_ok,
        "identity_ok": identity_ok,
        "bounds_ok": bounds_ok,
        "timeout_ms": bounds.timeout_ms,
        "memory_limit_mib": bounds.memory_limit_mib,
        "max_symbols": bounds.max_symbols,
        "max_term_nodes": bounds.max_term_nodes,
        "interpolation_api": interpolation_api,
        "independent_validator": INDEPENDENT_VALIDATOR,
        "independent_validator_version": independent_validator_version,
        "limitations": limitations,
    }
    if theory != QUALIFIED_INTERPOLATION_THEORY:
        common.update(
            {
                "interpolant": None,
                "interpolant_vocabulary": (),
                "interpolant_cid": "",
            }
        )
        return ValidatedInterpolantReceipt(
            status=InterpolationStatus.UNSUPPORTED,
            reason="initial adapter is qualified only for QF_LIA",
            **common,
        )
    if not bounds_ok:
        return ValidatedInterpolantReceipt(
            status=InterpolationStatus.INVALID,
            reason=bounds_reason,
            **common,
        )
    if not shared_ok:
        return ValidatedInterpolantReceipt(
            status=InterpolationStatus.INVALID,
            reason="interpolant uses symbols outside shared vocabulary",
            **common,
        )
    if not identity_ok:
        return ValidatedInterpolantReceipt(
            status=InterpolationStatus.INVALID,
            reason="partition or interpolant identity check failed",
            **common,
        )
    request_root = _request_root(a_cid, b_cid, provider_version, theory)
    (
        a_implies_i,
        i_and_b_unsat,
        first_receipt,
        second_receipt,
        check_reason,
        validator,
    ) = _validate_with_z3(
        partition_a=partition_a,
        partition_b=partition_b,
        interpolant=interpolant,
        symbols=tuple(sorted(_symbols(partition_a) | _symbols(partition_b) | _symbols(interpolant))),
        request_root=request_root,
        bounds=bounds,
    )
    common.update(
        {
            "a_implies_i": a_implies_i,
            "i_and_b_unsat": i_and_b_unsat,
            "a_implies_i_receipt": first_receipt,
            "i_and_b_unsat_receipt": second_receipt,
            "independent_validator": validator,
            "independent_validator_version": (
                common["independent_validator_version"]
                if validator == INDEPENDENT_VALIDATOR
                else "1"
            ),
        }
    )
    if not first_receipt and not second_receipt and check_reason.startswith(
        "independent validator unavailable"
    ):
        common.update(
            {
                "interpolant": None,
                "interpolant_vocabulary": (),
                "interpolant_cid": "",
                "a_implies_i": False,
                "i_and_b_unsat": False,
            }
        )
        return ValidatedInterpolantReceipt(
            status=InterpolationStatus.UNAVAILABLE,
            reason=check_reason,
            **common,
        )
    if a_implies_i and i_and_b_unsat and shared_ok and identity_ok and bounds_ok:
        return ValidatedInterpolantReceipt(
            status=InterpolationStatus.VALIDATED,
            reason="",
            **common,
        )
    status = InterpolationStatus.UNKNOWN if "timed out" in check_reason or "unknown" in check_reason else InterpolationStatus.INVALID
    return ValidatedInterpolantReceipt(
        status=status,
        reason=check_reason or "independent implication or inconsistency check failed",
        **common,
    )


def compute_and_validate_interpolant(
    partition_a: SmtTerm,
    partition_b: SmtTerm,
    *,
    theory: str = QUALIFIED_INTERPOLATION_THEORY,
    provider: str = QUALIFIED_INTERPOLATION_PROVIDER,
    bounds: InterpolationBounds | None = None,
) -> ValidatedInterpolantReceipt:
    """Compute ``I`` for unsatisfiable ``A & B`` and independently admit it."""

    partition_a = _require_term(partition_a, "partition_a")
    partition_b = _require_term(partition_b, "partition_b")
    theory = _text(theory, "theory")
    provider = _text(provider, "provider")
    bounds = bounds or InterpolationBounds(theory=QUALIFIED_INTERPOLATION_THEORY)
    capability = probe_interpolation_support(provider=provider, theory=theory)
    a_cid = _term_cid(partition_a, "a")
    b_cid = _term_cid(partition_b, "b")
    shared = tuple(sorted(_symbols(partition_a) & _symbols(partition_b)))
    request_root = _request_root(a_cid, b_cid, capability.provider_version, theory)
    symbols = tuple(sorted(_symbols(partition_a) | _symbols(partition_b)))
    base = {
        "partition_a_cid": a_cid,
        "partition_b_cid": b_cid,
        "shared_vocabulary": shared,
        "provider": capability.provider,
        "provider_version": capability.provider_version,
        "theory": theory,
        "timeout_ms": bounds.timeout_ms,
        "memory_limit_mib": bounds.memory_limit_mib,
        "max_symbols": bounds.max_symbols,
        "max_term_nodes": bounds.max_term_nodes,
        "interpolation_api": capability.interpolation_api,
        "independent_validator": capability.independent_validator,
        "independent_validator_version": capability.independent_validator_version,
    }
    bounds_ok, bounds_reason = _evaluate_bounds(
        partition_a=partition_a,
        partition_b=partition_b,
        interpolant=None,
        theory=theory,
        bounds=bounds,
    )
    identity_ok = _identity_holds(
        partition_a=partition_a,
        partition_b=partition_b,
        interpolant=None,
        partition_a_cid=a_cid,
        partition_b_cid=b_cid,
        interpolant_cid="",
        shared_vocabulary=shared,
        interpolant_vocabulary=(),
    )
    producer_ready = (
        capability.provider_installed
        and capability.provider_qualified
        and capability.interpolation_api
        and capability.theory_qualified
    )
    if not capability.theory_qualified:
        return ValidatedInterpolantReceipt(
            status=InterpolationStatus.UNSUPPORTED,
            interpolant=None,
            interpolant_vocabulary=(),
            reason=capability.reason,
            limitations=QUALIFIED_LIMITATIONS,
            bounds_ok=False,
            identity_ok=identity_ok,
            **base,
        )
    if not bounds_ok:
        return ValidatedInterpolantReceipt(
            status=InterpolationStatus.INVALID,
            interpolant=None,
            interpolant_vocabulary=(),
            reason=bounds_reason,
            limitations=QUALIFIED_LIMITATIONS,
            bounds_ok=False,
            identity_ok=identity_ok,
            **base,
        )

    def _fallback(reason: str, status: InterpolationStatus) -> ValidatedInterpolantReceipt:
        validated, receipt, core, fallback_reason = _unsat_core_fallback(
            partition_a=partition_a,
            partition_b=partition_b,
            symbols=symbols,
            request_root=request_root,
            bounds=bounds,
        )
        if validated:
            return ValidatedInterpolantReceipt(
                status=InterpolationStatus.FALLBACK,
                interpolant=None,
                interpolant_vocabulary=(),
                reason=reason,
                limitations=FALLBACK_LIMITATIONS,
                bounds_ok=True,
                identity_ok=identity_ok,
                fallback_kind="validated_unsat_core",
                fallback_core=core,
                fallback_receipt=receipt,
                fallback_validated=True,
                **base,
            )
        combined = reason if not fallback_reason else f"{reason}; {fallback_reason}"
        return ValidatedInterpolantReceipt(
            status=status,
            interpolant=None,
            interpolant_vocabulary=(),
            reason=combined,
            limitations=FALLBACK_LIMITATIONS,
            bounds_ok=True,
            identity_ok=identity_ok,
            fallback_kind="",
            fallback_core=core,
            fallback_receipt=receipt,
            fallback_validated=False,
            **base,
        )

    if not producer_ready:
        # An installed SAT solver is still interpolation-unavailable.  Fallback
        # may attach a validated unsat core, but never an interpolant.  Z3
        # absence does not by itself block a cvc5 producer: admission can use
        # the local QF_LIA fragment checker when the independent validator is
        # not installed.
        return _fallback(capability.reason, InterpolationStatus.UNAVAILABLE)

    try:
        module = importlib.import_module(provider)
        interpolant = _compute_cvc5_interpolant(
            partition_a,
            partition_b,
            theory=theory,
            module=module,
            bounds=bounds,
        )
    except (RuntimeError, TypeError, ValueError, AttributeError, InterpolationError) as error:
        return _fallback(str(error) or "interpolation provider failed", InterpolationStatus.UNKNOWN)

    return admit_interpolant(
        partition_a,
        partition_b,
        interpolant,
        theory=theory,
        provider=capability.provider,
        provider_version=capability.provider_version,
        bounds=bounds,
        interpolation_api=capability.interpolation_api,
        independent_validator_version=capability.independent_validator_version,
        limitations=QUALIFIED_LIMITATIONS,
    )


__all__ = [
    "FALLBACK_ENVIRONMENT",
    "INTERPOLATION_BOUNDS_SCHEMA",
    "INTERPOLATION_CAPABILITY_SCHEMA",
    "INTERPOLATION_INTERFACE",
    "INTERPOLATION_RECEIPT_SCHEMA",
    "FRAGMENT_CHECKER",
    "QUALIFIED_INTERPOLATION_PROVIDER",
    "QUALIFIED_INTERPOLATION_THEORY",
    "InterpolationBounds",
    "InterpolationCapability",
    "InterpolationError",
    "InterpolationStatus",
    "ValidatedInterpolantReceipt",
    "admit_interpolant",
    "compute_and_validate_interpolant",
    "probe_interpolation_support",
]

"""Capability-negotiated Craig interpolation with independent validation.

The qualified producer is cvc5 on the declared QF_LIA fragment.  Solver
availability is not interpolation support: Z3 is used only as an independent
validator and as a typed unsat-core fallback.  No interpolant is admitted
merely because a provider returned a term.  Admission requires:

* ``A => I`` on a fresh Z3 session;
* ``I & B`` unsatisfiable on a second fresh Z3 session;
* interpolant vocabulary is contained in the structural shared vocabulary;
* partition, interpolant, and receipt identities; and
* explicit bounds on theory, symbols, term size, timeout, and memory.

An unsupported theory, absent interpolation API, provider error, failed
check, or missing independent validator yields a typed non-success.  When
interpolation itself is unavailable, a validated unsat core of ``A & B`` is
reported as fallback authority and is never rewritten into an interpolant.
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
    term_not,
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
VALIDATOR_ENVIRONMENT: Final = "local-independent-z3-validator@1"
FALLBACK_ENVIRONMENT: Final = "local-unsat-core-fallback@1"
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
    except ImportError:
        return None


def _module_version(module: Any, provider: str) -> str:
    if provider == "z3" and hasattr(module, "get_version_string"):
        return str(module.get_version_string())
    return str(getattr(module, "__version__", "unknown"))


def _interpolation_api(module: Any, provider: str) -> tuple[bool, str]:
    if provider == QUALIFIED_INTERPOLATION_PROVIDER:
        solver = getattr(module, "Solver", None)
        if solver is not None and hasattr(solver, "getInterpolant"):
            return True, "Solver.getInterpolant"
        return False, ""
    if hasattr(module, "interpolate"):
        return True, "interpolate"
    if hasattr(module, "Interpolant"):
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
) -> tuple[bool, bool, str, str, str]:
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
    except IncrementalSmtUnavailable as error:
        return False, False, "", "", f"independent validator unavailable: {error}"
    except IncrementalSmtError as error:
        return False, False, "", "", f"independent validator rejected the candidate: {error}"
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
    except IncrementalSmtUnavailable as error:
        return False, "", (), f"unsat-core fallback unavailable: {error}"
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
    a_implies_i, i_and_b_unsat, first_receipt, second_receipt, check_reason = _validate_with_z3(
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

    if not capability.qualified:
        # An installed SAT solver is still interpolation-unavailable.  Fallback
        # may attach a validated unsat core, but never an interpolant.
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

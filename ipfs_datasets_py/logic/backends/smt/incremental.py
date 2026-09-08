"""Provider-neutral reusable incremental SMT sessions.

The session is a cache/replay optimization, never a new proof authority.
Assertions retain stable source identities and every result binds the exact
provider, toolchain, translator, policy, declarations, and active assertion
set.  Optional solver imports remain cold until ``open_incremental_smt_session``.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from ipfs_datasets_py.logic.backends.smt.compiler import (
    SmtFunDecl,
    SmtSort,
    SmtTerm,
    SmtTermKind,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity

INCREMENTAL_SMT_INTERFACE: Final = "IncrementalSmtSession@1"
INCREMENTAL_SMT_SCHEMA: Final = "incremental-smt-session/v1"
INCREMENTAL_SMT_REPLAY_SCHEMA: Final = "incremental-smt-replay-manifest/v1"
INCREMENTAL_SMT_RESULT_SCHEMA: Final = "incremental-smt-result/v1"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,511}$")


class IncrementalSmtError(ValueError):
    """Raised for malformed or stale incremental session operations."""


class IncrementalSmtUnavailable(IncrementalSmtError):
    """Raised when a requested provider is not installed/usable."""


class IncrementalSmtStale(IncrementalSmtError):
    """Raised when a caller attempts reuse under a different fingerprint."""


class SmtCheckStatus(StrEnum):
    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CLOSED = "closed"


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise IncrementalSmtError(f"{label} must be a trimmed non-empty string")
    return value


def _id(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise IncrementalSmtError(f"{label} must be a stable identifier")
    return result


@dataclass(frozen=True, slots=True)
class IncrementalSmtFingerprint:
    """All semantic/tool facts that authorize mutable-context reuse."""

    provider: str
    provider_version: str
    logic: str
    translator_identity: str
    theory_fingerprint: str
    policy_root: str
    configuration_root: str
    environment_root: str
    deterministic_seed: int = 0
    timeout_ms: int = 5_000
    memory_limit_mib: int = 512
    schema: str = INCREMENTAL_SMT_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "provider_version",
            "logic",
            "translator_identity",
            "theory_fingerprint",
            "policy_root",
            "configuration_root",
            "environment_root",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("deterministic_seed", "timeout_ms", "memory_limit_mib"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise IncrementalSmtError(f"{name} must be a non-negative integer")
        if self.timeout_ms == 0:
            raise IncrementalSmtError("timeout_ms must be positive")
        if self.memory_limit_mib == 0:
            raise IncrementalSmtError("memory_limit_mib must be positive")
        if self.schema != INCREMENTAL_SMT_SCHEMA:
            raise IncrementalSmtError("unsupported incremental SMT schema")

    @property
    def digest(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="logic.backends.smt.incremental-session",
            schema_version=self.schema,
        ).digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_root": self.configuration_root,
            "deterministic_seed": self.deterministic_seed,
            "environment_root": self.environment_root,
            "logic": self.logic,
            "memory_limit_mib": self.memory_limit_mib,
            "policy_root": self.policy_root,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "schema": self.schema,
            "theory_fingerprint": self.theory_fingerprint,
            "timeout_ms": self.timeout_ms,
            "translator_identity": self.translator_identity,
        }


@dataclass(frozen=True, slots=True)
class NamedSessionAssertion:
    assertion_id: str
    formula: SmtTerm
    source_ref: str
    obligation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "assertion_id", _id(self.assertion_id, "assertion_id"))
        if not isinstance(self.formula, SmtTerm):
            raise IncrementalSmtError("formula must be SmtTerm")
        object.__setattr__(self, "source_ref", _text(self.source_ref, "source_ref"))
        object.__setattr__(self, "obligation_id", _id(self.obligation_id, "obligation_id"))

    @property
    def digest(self) -> str:
        return "sha256:" + stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "formula": self.formula.to_dict(),
            "obligation_id": self.obligation_id,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True, slots=True)
class IncrementalSmtResult:
    session_id: str
    session_fingerprint: str
    status: SmtCheckStatus | str
    active_assertion_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...] = ()
    model: FrozenMap = field(default_factory=FrozenMap)
    unsat_core: tuple[str, ...] = ()
    unknown_reason: str = ""
    model_validated: bool = False
    core_validated: bool = False
    statistics: FrozenMap = field(default_factory=FrozenMap)
    limitations: tuple[str, ...] = ()
    schema: str = INCREMENTAL_SMT_RESULT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _id(self.session_id, "session_id"))
        object.__setattr__(
            self, "session_fingerprint", _text(self.session_fingerprint, "session_fingerprint")
        )
        try:
            status = (
                self.status
                if isinstance(self.status, SmtCheckStatus)
                else SmtCheckStatus(self.status)
            )
        except ValueError as error:
            raise IncrementalSmtError(str(error)) from error
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "active_assertion_ids", tuple(sorted(self.active_assertion_ids)))
        object.__setattr__(self, "assumption_ids", tuple(sorted(self.assumption_ids)))
        object.__setattr__(self, "unsat_core", tuple(sorted(self.unsat_core)))
        object.__setattr__(
            self,
            "model",
            self.model if isinstance(self.model, FrozenMap) else FrozenMap(self.model),
        )
        object.__setattr__(
            self,
            "statistics",
            self.statistics
            if isinstance(self.statistics, FrozenMap)
            else FrozenMap(self.statistics),
        )
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        if self.schema != INCREMENTAL_SMT_RESULT_SCHEMA:
            raise IncrementalSmtError("unsupported result schema")

    @property
    def receipt_id(self) -> str:
        # Solver statistics contain process-local counters (for example Z3's
        # allocation count) and are useful telemetry, not semantic evidence.
        # Excluding them makes independently replayed results content-stable
        # while the full observation remains available through ``to_dict``.
        identity_payload = self.to_dict()
        identity_payload.pop("statistics", None)
        return canonical_identity(
            identity_payload,
            domain="logic.backends.smt.incremental-result",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_assertion_ids": list(self.active_assertion_ids),
            "assumption_ids": list(self.assumption_ids),
            "core_validated": self.core_validated,
            "limitations": list(self.limitations),
            "model": self.model.to_dict(),
            "model_validated": self.model_validated,
            "schema": self.schema,
            "session_fingerprint": self.session_fingerprint,
            "session_id": self.session_id,
            "statistics": self.statistics.to_dict(),
            "status": (
                self.status.value
                if isinstance(self.status, SmtCheckStatus)
                else self.status
            ),
            "unknown_reason": self.unknown_reason,
            "unsat_core": list(self.unsat_core),
        }


class IncrementalSmtSession:
    """Z3-backed implementation of the provider-neutral session contract."""

    interface = INCREMENTAL_SMT_INTERFACE

    def __init__(
        self,
        *,
        session_id: str,
        fingerprint: IncrementalSmtFingerprint,
        z3_module: Any,
    ) -> None:
        self.session_id = _id(session_id, "session_id")
        self.fingerprint = fingerprint
        self._z3 = z3_module
        self._solver = z3_module.Solver()
        self._solver.set(timeout=fingerprint.timeout_ms)
        self._sorts: dict[str, Any] = {
            "Bool": z3_module.BoolSort(),
            "Int": z3_module.IntSort(),
            "Real": z3_module.RealSort(),
        }
        self._symbols: dict[str, Any] = {}
        self._assertions: list[NamedSessionAssertion] = []
        self._frame_sizes: list[int] = []
        self._last_result: IncrementalSmtResult | None = None
        self._closed = False
        self._cancelled = False
        self._transcript: list[dict[str, Any]] = []

    def _require_open(self) -> None:
        if self._closed:
            raise IncrementalSmtError("incremental SMT session is closed")

    def assert_fresh(self, expected: IncrementalSmtFingerprint | str) -> None:
        expected_digest = (
            expected.digest if isinstance(expected, IncrementalSmtFingerprint) else expected
        )
        if expected_digest != self.fingerprint.digest:
            raise IncrementalSmtStale(
                f"session fingerprint mismatch expected={expected_digest} actual={self.fingerprint.digest}"
            )

    def declare_sort(self, name: str, arity: int = 0) -> SmtSort:
        self._require_open()
        name = _id(name, "sort name")
        if name in self._sorts:
            raise IncrementalSmtError(f"sort {name!r} already declared")
        if isinstance(arity, bool) or not isinstance(arity, int) or arity < 0:
            raise IncrementalSmtError("sort arity must be non-negative")
        if arity:
            sort = self._z3.DeclareSort(name) if arity == 0 else self._z3.DeclareSort(name)
        else:
            sort = self._z3.DeclareSort(name)
        self._sorts[name] = sort
        self._transcript.append({"operation": "declare_sort", "name": name, "arity": arity})
        return SmtSort(name=name, arity=arity)

    def _sort(self, sort: SmtSort | str) -> Any:
        name = sort.name if isinstance(sort, SmtSort) else _text(sort, "sort")
        if name == "Array" and isinstance(sort, SmtSort) and len(sort.parameters) == 2:
            return self._z3.ArraySort(
                self._sort(sort.parameters[0]), self._sort(sort.parameters[1])
            )
        try:
            return self._sorts[name]
        except KeyError as error:
            raise IncrementalSmtError(f"undeclared sort {name!r}") from error

    def declare_symbol(
        self,
        name: str,
        range_sort: SmtSort | str,
        domain: Sequence[SmtSort | str] = (),
    ) -> Any:
        self._require_open()
        name = _id(name, "symbol name")
        if name in self._symbols:
            raise IncrementalSmtError(f"symbol {name!r} already declared")
        range_z3 = self._sort(range_sort)
        domain_z3 = tuple(self._sort(item) for item in domain)
        symbol = (
            self._z3.Const(name, range_z3)
            if not domain_z3
            else self._z3.Function(name, *domain_z3, range_z3)
        )
        self._symbols[name] = symbol
        decl = SmtFunDecl(
            name=name,
            domain=tuple(item if isinstance(item, SmtSort) else SmtSort(item) for item in domain),
            range=range_sort if isinstance(range_sort, SmtSort) else SmtSort(range_sort),
            is_const=not domain_z3,
        )
        self._transcript.append({"operation": "declare_symbol", "declaration": decl.to_dict()})
        return symbol

    def add_named_assertion(
        self,
        assertion_id: str,
        formula: SmtTerm,
        *,
        source_ref: str,
        obligation_id: str,
    ) -> NamedSessionAssertion:
        self._require_open()
        if any(item.assertion_id == assertion_id for item in self._assertions):
            raise IncrementalSmtError(f"assertion {assertion_id!r} already exists")
        record = NamedSessionAssertion(assertion_id, formula, source_ref, obligation_id)
        # Translate now so unsupported syntax fails before state mutation.
        self._term(formula)
        self._assertions.append(record)
        self._transcript.append({"operation": "add_named_assertion", "assertion": record.to_dict()})
        return record

    def push(self) -> None:
        self._require_open()
        self._frame_sizes.append(len(self._assertions))
        self._transcript.append({"operation": "push"})

    def pop(self, levels: int = 1) -> None:
        self._require_open()
        if isinstance(levels, bool) or not isinstance(levels, int) or levels <= 0:
            raise IncrementalSmtError("pop levels must be a positive integer")
        if levels > len(self._frame_sizes):
            raise IncrementalSmtError("pop exceeds pushed frame depth")
        target = self._frame_sizes[-levels]
        del self._assertions[target:]
        del self._frame_sizes[-levels:]
        self._transcript.append({"operation": "pop", "levels": levels})

    def _term(self, term: SmtTerm, bound: Mapping[str, Any] | None = None) -> Any:
        z3 = self._z3
        env = dict(bound or {})
        kind = term.kind
        args = [self._term(item, env) for item in term.arguments]
        if kind is SmtTermKind.TRUE:
            return z3.BoolVal(True)
        if kind is SmtTermKind.FALSE:
            return z3.BoolVal(False)
        if kind is SmtTermKind.INT:
            return z3.IntVal(int(term.value))
        if kind is SmtTermKind.REAL:
            return z3.RealVal(term.value)
        if kind is SmtTermKind.BOOL:
            return z3.BoolVal(term.value == "true")
        if kind is SmtTermKind.SYMBOL:
            if term.value in env:
                return env[term.value]
            if term.value not in self._symbols:
                raise IncrementalSmtError(f"undeclared symbol {term.value!r}")
            return self._symbols[term.value]
        if kind is SmtTermKind.RAW:
            raise IncrementalSmtError("raw SMT terms are unsupported in reusable sessions")
        if kind is SmtTermKind.NOT:
            return z3.Not(args[0])
        if kind is SmtTermKind.AND:
            return z3.And(*args)
        if kind is SmtTermKind.OR:
            return z3.Or(*args)
        if kind is SmtTermKind.IMPLIES:
            return z3.Implies(args[0], args[1])
        if kind is SmtTermKind.IFF or kind is SmtTermKind.EQ:
            return args[0] == args[1]
        if kind is SmtTermKind.DISTINCT:
            return z3.Distinct(*args)
        if kind is SmtTermKind.ITE:
            return z3.If(*args)
        if kind is SmtTermKind.LT:
            return args[0] < args[1]
        if kind is SmtTermKind.LE:
            return args[0] <= args[1]
        if kind is SmtTermKind.GT:
            return args[0] > args[1]
        if kind is SmtTermKind.GE:
            return args[0] >= args[1]
        if kind is SmtTermKind.ADD:
            return sum(args[1:], args[0])
        if kind is SmtTermKind.SUB:
            return args[0] - args[1]
        if kind is SmtTermKind.MUL:
            result = args[0]
            for item in args[1:]:
                result = result * item
            return result
        if kind is SmtTermKind.DIV:
            return args[0] / args[1]
        if kind is SmtTermKind.MOD:
            return args[0] % args[1]
        if kind is SmtTermKind.NEG:
            return -args[0]
        if kind is SmtTermKind.SELECT:
            return z3.Select(args[0], args[1])
        if kind is SmtTermKind.STORE:
            return z3.Store(args[0], args[1], args[2])
        if kind is SmtTermKind.APPLY:
            if term.value not in self._symbols:
                raise IncrementalSmtError(f"undeclared function {term.value!r}")
            symbol = self._symbols[term.value]
            return symbol(*args) if args else symbol
        if kind in {SmtTermKind.FORALL, SmtTermKind.EXISTS}:
            binders: list[Any] = []
            nested = dict(env)
            for binder in term.binders:
                value = z3.Const(binder.name, self._sort(binder.sort))
                binders.append(value)
                nested[binder.name] = value
            body = self._term(term.arguments[0], nested)
            return (
                z3.ForAll(binders, body) if kind is SmtTermKind.FORALL else z3.Exists(binders, body)
            )
        raise IncrementalSmtError(f"unsupported reusable-session term kind {kind.value}")

    def _active(self) -> tuple[NamedSessionAssertion, ...]:
        return tuple(self._assertions)

    def _new_solver(self) -> tuple[Any, dict[str, Any]]:
        solver = self._z3.Solver()
        solver.set(timeout=self.fingerprint.timeout_ms)
        trackers: dict[str, Any] = {}
        for item in self._active():
            tracker = self._z3.Bool(f"track__{stable_digest({'id': item.assertion_id})[:24]}")
            trackers[item.assertion_id] = tracker
            solver.add(self._z3.Implies(tracker, self._term(item.formula)))
        return solver, trackers

    def check(self) -> IncrementalSmtResult:
        return self._check_with_extra(())

    def check_with_assumptions(
        self,
        assumptions: Mapping[str, SmtTerm] | Sequence[tuple[str, SmtTerm]],
    ) -> IncrementalSmtResult:
        items = (
            tuple(assumptions.items()) if isinstance(assumptions, Mapping) else tuple(assumptions)
        )
        normalized: list[NamedSessionAssertion] = []
        for assumption_id, term in items:
            normalized.append(
                NamedSessionAssertion(
                    assertion_id=_id(assumption_id, "assumption id"),
                    formula=term,
                    source_ref=f"assumption:{assumption_id}",
                    obligation_id=f"assumption:{assumption_id}",
                )
            )
        return self._check_with_extra(tuple(normalized))

    def _check_with_extra(self, extra: tuple[NamedSessionAssertion, ...]) -> IncrementalSmtResult:
        self._require_open()
        if self._cancelled:
            return self._record_result(SmtCheckStatus.CANCELLED, extra=extra)
        solver, trackers = self._new_solver()
        for item in extra:
            tracker = self._z3.Bool(f"assume__{stable_digest({'id': item.assertion_id})[:24]}")
            trackers[item.assertion_id] = tracker
            solver.add(self._z3.Implies(tracker, self._term(item.formula)))
        ordered = tuple(trackers[name] for name in sorted(trackers))
        outcome = solver.check(*ordered)
        if outcome == self._z3.sat:
            model = solver.model()
            model_data = {
                name: str(model.eval(symbol, model_completion=True))
                for name, symbol in sorted(self._symbols.items())
                if not callable(symbol)
            }
            validated = all(
                self._z3.is_true(model.eval(self._term(item.formula), model_completion=True))
                for item in (*self._active(), *extra)
            )
            return self._record_result(
                SmtCheckStatus.SAT,
                solver=solver,
                model=model_data,
                model_validated=validated,
                extra=extra,
            )
        if outcome == self._z3.unsat:
            tracker_to_id = {str(value): key for key, value in trackers.items()}
            core = tuple(sorted(tracker_to_id[str(item)] for item in solver.unsat_core()))
            validated = self._validate_core(core, extra)
            return self._record_result(
                SmtCheckStatus.UNSAT,
                solver=solver,
                core=core,
                core_validated=validated,
                extra=extra,
            )
        reason = str(solver.reason_unknown())
        status = SmtCheckStatus.TIMEOUT if "timeout" in reason.lower() else SmtCheckStatus.UNKNOWN
        return self._record_result(status, solver=solver, reason=reason, extra=extra)

    def _validate_core(
        self, core: tuple[str, ...], extra: tuple[NamedSessionAssertion, ...]
    ) -> bool:
        by_id = {item.assertion_id: item for item in (*self._active(), *extra)}
        if not core or any(item not in by_id for item in core):
            return False
        solver = self._z3.Solver()
        solver.set(timeout=self.fingerprint.timeout_ms)
        solver.add(*(self._term(by_id[item].formula) for item in core))
        return solver.check() == self._z3.unsat

    def _statistics(self, solver: Any | None) -> FrozenMap:
        if solver is None:
            return FrozenMap()
        data: dict[str, str | int] = {}
        stats = solver.statistics()
        for index in range(len(stats)):
            key = str(stats.keys()[index])
            value = stats.get_key_value(key)
            data[key] = (
                value if isinstance(value, int) and not isinstance(value, bool) else str(value)
            )
        return FrozenMap(data)

    def _record_result(
        self,
        status: SmtCheckStatus,
        *,
        solver: Any | None = None,
        model: Mapping[str, Any] | None = None,
        core: tuple[str, ...] = (),
        reason: str = "",
        model_validated: bool = False,
        core_validated: bool = False,
        extra: tuple[NamedSessionAssertion, ...] = (),
    ) -> IncrementalSmtResult:
        result = IncrementalSmtResult(
            session_id=self.session_id,
            session_fingerprint=self.fingerprint.digest,
            status=status,
            active_assertion_ids=tuple(item.assertion_id for item in self._active()),
            assumption_ids=tuple(item.assertion_id for item in extra),
            model=FrozenMap(model or {}),
            unsat_core=core,
            unknown_reason=reason,
            model_validated=model_validated,
            core_validated=core_validated,
            statistics=self._statistics(solver),
            limitations=(
                "z3py_in_process_session_has_no_subprocess_crash_isolation",
                "incremental_reuse_does_not_raise_evidence_authority",
            ),
        )
        self._last_result = result
        self._transcript.append(
            {
                "operation": "check",
                "result_receipt_id": result.receipt_id,
                "status": (
                    result.status.value
                    if isinstance(result.status, SmtCheckStatus)
                    else result.status
                ),
            }
        )
        return result

    def get_model(self) -> FrozenMap:
        if self._last_result is None or self._last_result.status is not SmtCheckStatus.SAT:
            raise IncrementalSmtError("no SAT model is available")
        return self._last_result.model

    def get_unsat_core(self) -> tuple[str, ...]:
        if self._last_result is None or self._last_result.status is not SmtCheckStatus.UNSAT:
            raise IncrementalSmtError("no UNSAT core is available")
        return self._last_result.unsat_core

    def get_proof(self) -> str:
        raise IncrementalSmtError(
            "proof objects are unavailable in this session profile; use a proof-enabled provider and reconstruction checker"
        )

    def get_statistics(self) -> FrozenMap:
        return FrozenMap() if self._last_result is None else self._last_result.statistics

    def cancel(self) -> None:
        self._cancelled = True
        self._transcript.append({"operation": "cancel"})

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._transcript.append({"operation": "close"})

    def snapshot_or_replay_manifest(self) -> dict[str, Any]:
        payload = {
            "assertions": [item.to_dict() for item in self._active()],
            "fingerprint": self.fingerprint.to_dict(),
            "frame_sizes": list(self._frame_sizes),
            "schema": INCREMENTAL_SMT_REPLAY_SCHEMA,
            "session_id": self.session_id,
            "symbols": [
                item["declaration"]
                for item in self._transcript
                if item.get("operation") == "declare_symbol"
            ],
            "transcript": list(self._transcript),
        }
        identity = canonical_identity(
            payload,
            domain="logic.backends.smt.incremental-replay",
            schema_version=INCREMENTAL_SMT_REPLAY_SCHEMA,
        )
        return {**payload, "manifest_cid": identity.cid, "manifest_digest": identity.digest}


def probe_incremental_smt_capabilities() -> dict[str, Any]:
    """Probe exact local APIs without installing or contacting a network."""

    providers: dict[str, Any] = {}
    for provider, module_name in (("z3", "z3"), ("cvc5", "cvc5")):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            providers[provider] = {"available": False, "reason": "module_not_installed"}
            continue
        version = (
            module.get_version_string()
            if provider == "z3" and hasattr(module, "get_version_string")
            else getattr(module, "__version__", "unknown")
        )
        providers[provider] = {
            "available": True,
            "version": str(version),
            "incremental_adapter": provider == "z3",
            "interpolation_api": bool(
                hasattr(module, "interpolate") or hasattr(module, "Interpolant")
            ),
        }
    return {
        "interface": INCREMENTAL_SMT_INTERFACE,
        "network_used": False,
        "providers": providers,
    }


def open_incremental_smt_session(
    *,
    session_id: str,
    provider: str = "z3",
    logic: str = "QF_LIA",
    translator_identity: str,
    theory_fingerprint: str,
    policy_root: str,
    configuration_root: str,
    environment_root: str,
    deterministic_seed: int = 0,
    timeout_ms: int = 5_000,
    memory_limit_mib: int = 512,
) -> IncrementalSmtSession:
    """Open a qualified local session; never installs a missing provider."""

    provider = _text(provider, "provider")
    if provider != "z3":
        raise IncrementalSmtUnavailable(
            f"provider {provider!r} has no qualified reusable-session adapter"
        )
    try:
        z3 = importlib.import_module("z3")
    except ImportError as error:
        raise IncrementalSmtUnavailable("z3 Python API is not installed") from error
    fingerprint = IncrementalSmtFingerprint(
        provider=provider,
        provider_version=str(z3.get_version_string()),
        logic=logic,
        translator_identity=translator_identity,
        theory_fingerprint=theory_fingerprint,
        policy_root=policy_root,
        configuration_root=configuration_root,
        environment_root=environment_root,
        deterministic_seed=deterministic_seed,
        timeout_ms=timeout_ms,
        memory_limit_mib=memory_limit_mib,
    )
    return IncrementalSmtSession(session_id=session_id, fingerprint=fingerprint, z3_module=z3)


__all__ = [
    "INCREMENTAL_SMT_INTERFACE",
    "INCREMENTAL_SMT_REPLAY_SCHEMA",
    "INCREMENTAL_SMT_RESULT_SCHEMA",
    "INCREMENTAL_SMT_SCHEMA",
    "IncrementalSmtError",
    "IncrementalSmtFingerprint",
    "IncrementalSmtResult",
    "IncrementalSmtSession",
    "IncrementalSmtStale",
    "IncrementalSmtUnavailable",
    "NamedSessionAssertion",
    "SmtCheckStatus",
    "open_incremental_smt_session",
    "probe_incremental_smt_capabilities",
]

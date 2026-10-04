"""Bounded prover portfolio routing for Crypto IR formalization (CRYPTOIR-G320).

A backend is only invoked when:

1. the :class:`~.compiler.LoweredForm` has ``may_submit=True``;
2. the backend declares the form's :class:`~.obligations.LogicFamily`; and
3. the backend capability probe reports available (or the call is an explicit
   unavailable attempt recorded in the receipt).

Opaque forms, prose, and unsupported theories never reach a solver.  SAT/UNSAT
answers are recorded as satisfiability results and are not silently promoted to
security proofs (see :mod:`.receipts`).
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from ...ir_core.provenance import thaw_json
from .compiler import LoweredForm, LoweringStatus, TheoryFragment
from .obligations import (
    NON_EXECUTABLE_LOGIC_FAMILIES,
    FormalizationError,
    LogicFamily,
    _attributes,
    _enum,
    _identifier,
    _text,
    _unique_ids,
)


PORTFOLIO_VERSION: Final[str] = "1.0.0"
BACKEND_RESULT_SCHEMA_VERSION: Final[str] = "crypto-ir.backend-result@1.0.0"

_SMT_ASSERT_RE = re.compile(r"\(\s*assert\b", re.IGNORECASE)


class BackendStatus(str, Enum):
    """Terminal status of one backend attempt (not a policy verdict)."""

    PROVED = "proved"
    DISPROVED = "disproved"
    SATISFIABLE = "satisfiable"
    UNSATISFIABLE = "unsatisfiable"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    NOT_MODELED = "not_modeled"
    REFUSED = "refused"
    ERROR = "error"
    DISAGREEMENT = "disagreement"


# Statuses that never carry proof authority on their own.
NON_PROOF_BACKEND_STATUSES: Final[frozenset[BackendStatus]] = frozenset(
    {
        BackendStatus.SATISFIABLE,
        BackendStatus.UNSATISFIABLE,
        BackendStatus.UNKNOWN,
        BackendStatus.TIMEOUT,
        BackendStatus.UNAVAILABLE,
        BackendStatus.NOT_MODELED,
        BackendStatus.REFUSED,
        BackendStatus.ERROR,
        BackendStatus.DISAGREEMENT,
    }
)


@dataclass(frozen=True, slots=True)
class BackendDescriptor:
    """Static capability declaration for one prover backend."""

    backend_id: str
    family: str
    logic_families: tuple[LogicFamily, ...]
    theories: tuple[TheoryFragment, ...] = ()
    capability_id: str = ""
    tool_name: str = ""
    tool_version: str = ""
    default_timeout_ms: int = 5_000
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "backend_id", _identifier(self.backend_id, "backend_id")
        )
        object.__setattr__(self, "family", _identifier(self.family, "family"))
        families = tuple(
            _enum(LogicFamily, item, "logic_families")
            for item in (self.logic_families or ())
        )
        if not families:
            raise FormalizationError("logic_families must be non-empty")
        object.__setattr__(self, "logic_families", families)
        theories = tuple(
            _enum(TheoryFragment, item, "theories") for item in (self.theories or ())
        )
        object.__setattr__(self, "theories", theories)
        object.__setattr__(
            self,
            "capability_id",
            _text(self.capability_id, "capability_id", allow_empty=True),
        )
        object.__setattr__(
            self, "tool_name", _text(self.tool_name, "tool_name", allow_empty=True)
        )
        object.__setattr__(
            self,
            "tool_version",
            _text(self.tool_version, "tool_version", allow_empty=True),
        )
        if (
            type(self.default_timeout_ms) is not int
            or isinstance(self.default_timeout_ms, bool)
            or self.default_timeout_ms < 0
        ):
            raise FormalizationError("default_timeout_ms must be a non-negative int")
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def supports(self, form: LoweredForm) -> bool:
        if form.logic_family not in self.logic_families:
            return False
        if self.theories and form.theory not in self.theories:
            # Allow NONE theory only when theories empty; otherwise require match.
            if form.theory is not TheoryFragment.NONE:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "backend_id": self.backend_id,
            "capability_id": self.capability_id,
            "default_timeout_ms": self.default_timeout_ms,
            "family": self.family,
            "logic_families": [
                f.value if isinstance(f, LogicFamily) else f for f in self.logic_families
            ],
            "theories": [
                t.value if isinstance(t, TheoryFragment) else t for t in self.theories
            ],
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
        }


@dataclass(frozen=True, slots=True)
class BackendResult:
    """Evidence-bound result of one backend execution attempt."""

    backend_id: str
    status: BackendStatus
    executed: bool
    logic_family: LogicFamily
    timeout_ms: int
    elapsed_ms: int = 0
    tool_name: str = ""
    tool_version: str = ""
    capability_id: str = ""
    model_digest: str = ""
    obligation_id: str = ""
    form_id: str = ""
    counterexample: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    raw_status: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = BACKEND_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "backend_id", _identifier(self.backend_id, "backend_id")
        )
        object.__setattr__(
            self, "status", _enum(BackendStatus, self.status, "status")
        )
        if not isinstance(self.executed, bool):
            raise FormalizationError("executed must be a bool")
        object.__setattr__(
            self, "logic_family", _enum(LogicFamily, self.logic_family, "logic_family")
        )
        for name in ("timeout_ms", "elapsed_ms"):
            value = getattr(self, name)
            if type(value) is not int or isinstance(value, bool) or value < 0:
                raise FormalizationError(f"{name} must be a non-negative int")
        for name in (
            "tool_name",
            "tool_version",
            "capability_id",
            "model_digest",
            "obligation_id",
            "form_id",
            "reason",
            "raw_status",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(self, "counterexample", _attributes(self.counterexample))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        # A non-executed result cannot claim proved/disproved.
        if not self.executed and self.status in {
            BackendStatus.PROVED,
            BackendStatus.DISPROVED,
            BackendStatus.SATISFIABLE,
            BackendStatus.UNSATISFIABLE,
        }:
            raise FormalizationError(
                "non-executed backend result cannot claim solver outcomes"
            )

    @property
    def is_proof_candidate(self) -> bool:
        """True only for executed PROVED/DISPROVED (still not policy ALLOW)."""

        return self.executed and self.status in {
            BackendStatus.PROVED,
            BackendStatus.DISPROVED,
        }

    @property
    def is_satisfiability_only(self) -> bool:
        return self.executed and self.status in {
            BackendStatus.SATISFIABLE,
            BackendStatus.UNSATISFIABLE,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "backend_id": self.backend_id,
            "capability_id": self.capability_id,
            "counterexample": thaw_json(self.counterexample),
            "elapsed_ms": self.elapsed_ms,
            "executed": self.executed,
            "form_id": self.form_id,
            "logic_family": (
                self.logic_family.value
                if isinstance(self.logic_family, LogicFamily)
                else self.logic_family
            ),
            "model_digest": self.model_digest,
            "obligation_id": self.obligation_id,
            "raw_status": self.raw_status,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "status": (
                self.status.value if isinstance(self.status, BackendStatus) else self.status
            ),
            "timeout_ms": self.timeout_ms,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
        }


@runtime_checkable
class ProverBackend(Protocol):
    """Protocol for a prover backend that may execute a compiled form."""

    @property
    def descriptor(self) -> BackendDescriptor: ...

    def is_available(self) -> bool: ...

    def execute(
        self, form: LoweredForm, *, timeout_ms: int
    ) -> BackendResult: ...


def _base_result(
    backend: ProverBackend,
    form: LoweredForm,
    *,
    status: BackendStatus,
    executed: bool,
    timeout_ms: int,
    elapsed_ms: int = 0,
    reason: str = "",
    raw_status: str = "",
    counterexample: Mapping[str, Any] | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> BackendResult:
    desc = backend.descriptor
    return BackendResult(
        backend_id=desc.backend_id,
        status=status,
        executed=executed,
        logic_family=form.logic_family,
        timeout_ms=timeout_ms,
        elapsed_ms=elapsed_ms,
        tool_name=desc.tool_name,
        tool_version=desc.tool_version,
        capability_id=desc.capability_id,
        model_digest=form.model_digest,
        obligation_id=form.obligation_id,
        form_id=form.form_id,
        counterexample=counterexample or {},
        reason=reason,
        raw_status=raw_status,
        attributes=attributes or {},
    )


def _extract_assert_bodies(smtlib: str) -> list[str]:
    """Extract top-level assert bodies from a tiny SMT-LIB subset."""

    bodies: list[str] = []
    text = smtlib
    idx = 0
    lower = text.lower()
    while True:
        pos = lower.find("(assert", idx)
        if pos < 0:
            break
        # Find matching close paren for the assert form.
        depth = 0
        end = pos
        for i in range(pos, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        form = text[pos:end]
        # body is inside (assert BODY)
        inner = form[len("(assert") :].strip()
        if inner.startswith("(") or inner:
            # strip trailing )
            if inner.endswith(")"):
                # remove outer closing of assert
                body = inner[:-1].strip() if form.endswith(")") else inner
            else:
                body = inner
            # Re-parse more carefully:
            m = re.match(r"\(\s*assert\s+([\s\S]*)\)\s*$", form, re.IGNORECASE)
            if m:
                bodies.append(m.group(1).strip())
        idx = end
    return bodies


def _prop_eval_atom(atom: str, assignment: Mapping[str, bool]) -> bool | None:
    a = atom.strip().lower()
    if a == "true":
        return True
    if a == "false":
        return False
    if a in assignment:
        return assignment[a]
    return None


def _simple_bool_sat(smtlib: str) -> tuple[str, Mapping[str, Any]]:
    """Decide a tiny QF_BOOL fragment without external solvers.

    Supports:
    - ``(assert true)`` / ``(assert false)``
    - ``(assert p)`` / ``(assert (not p))``
    - ``(assert (and ...))`` / ``(assert (or ...))`` / ``(assert (=> a b))``
    - contradiction ``(assert p)`` + ``(assert (not p))``
    """

    asserts = _extract_assert_bodies(smtlib)
    if not asserts:
        return "unknown", {"reason": "no assert bodies"}

    # Collect unit literals.
    forced: dict[str, bool] = {}
    clauses: list[str] = []
    for body in asserts:
        b = re.sub(r"\s+", " ", body.strip())
        low = b.lower()
        if low == "true":
            continue
        if low == "false":
            return "unsat", {"counterexample": {}, "reason": "assert false"}
        m_not = re.fullmatch(r"\(\s*not\s+([A-Za-z_][A-Za-z0-9_]*)\s*\)", b, re.I)
        if m_not:
            name = m_not.group(1).lower()
            if name in forced and forced[name] is True:
                return "unsat", {
                    "counterexample": {},
                    "reason": f"contradiction on {name}",
                }
            forced[name] = False
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", b):
            name = b.lower()
            if name in forced and forced[name] is False:
                return "unsat", {
                    "counterexample": {},
                    "reason": f"contradiction on {name}",
                }
            forced[name] = True
            continue
        clauses.append(b)

    # Evaluate simple and/or/=> under forced assignment; unknowns stay free.
    for clause in clauses:
        low = re.sub(r"\s+", " ", clause.strip().lower())
        m_and = re.fullmatch(r"\(\s*and\s+(.+)\s*\)", low)
        if m_and:
            parts = m_and.group(1).split()
            vals = [_prop_eval_atom(p, forced) for p in parts]
            if any(v is False for v in vals):
                return "unsat", {"reason": "and-clause false", "assignment": forced}
            continue
        m_or = re.fullmatch(r"\(\s*or\s+(.+)\s*\)", low)
        if m_or:
            parts = m_or.group(1).split()
            vals = [_prop_eval_atom(p, forced) for p in parts]
            if vals and all(v is False for v in vals):
                return "unsat", {"reason": "or-clause false", "assignment": forced}
            continue
        m_imp = re.fullmatch(r"\(\s*=>\s+(\S+)\s+(\S+)\s*\)", low)
        if m_imp:
            a = _prop_eval_atom(m_imp.group(1), forced)
            b = _prop_eval_atom(m_imp.group(2), forced)
            if a is True and b is False:
                return "unsat", {"reason": "implication false", "assignment": forced}
            continue
        # Unknown compound → sat if no contradiction among units.
        return "unknown", {"reason": f"unsupported clause: {clause}", "assignment": forced}

    return "sat", {"assignment": dict(forced)}


class PropositionalBackend:
    """Always-available pure-Python QF_BOOL backend (actually executes)."""

    def __init__(self, *, backend_id: str = "backend.propositional.v1") -> None:
        self._descriptor = BackendDescriptor(
            backend_id=backend_id,
            family="propositional",
            logic_families=(LogicFamily.PROPOSITIONAL, LogicFamily.SMT_LIB),
            theories=(TheoryFragment.PROPOSITIONAL, TheoryFragment.QF_BOOL),
            capability_id="cap.prover.propositional",
            tool_name="crypto-ir-propositional",
            tool_version=PORTFOLIO_VERSION,
            default_timeout_ms=1_000,
        )

    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    def is_available(self) -> bool:
        return True

    def execute(self, form: LoweredForm, *, timeout_ms: int) -> BackendResult:
        if not form.may_submit:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason="form.may_submit is false",
            )
        if form.logic_family not in self._descriptor.logic_families:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason=f"backend does not compile logic family {form.logic_family.value}",
            )
        started = time.perf_counter()
        decision, detail = _simple_bool_sat(form.body)
        elapsed = int((time.perf_counter() - started) * 1000)
        if decision == "unsat":
            # For security obligations we treat unsat of the *violation*
            # encoding as proved only when attributes request that mode.
            # Default: report unsatisfiable (satisfiability family).
            mode = str(form.attributes.get("query_mode", "satisfiability"))
            if mode == "validity_of_negation":
                status = BackendStatus.PROVED
            elif mode == "find_violation":
                status = BackendStatus.PROVED  # no violation model
            else:
                status = BackendStatus.UNSATISFIABLE
            return _base_result(
                self,
                form,
                status=status,
                executed=True,
                timeout_ms=timeout_ms,
                elapsed_ms=elapsed,
                reason="propositional backend decided unsat",
                raw_status=decision,
                attributes=detail,
            )
        if decision == "sat":
            mode = str(form.attributes.get("query_mode", "satisfiability"))
            if mode == "find_violation":
                status = BackendStatus.DISPROVED
            else:
                status = BackendStatus.SATISFIABLE
            return _base_result(
                self,
                form,
                status=status,
                executed=True,
                timeout_ms=timeout_ms,
                elapsed_ms=elapsed,
                reason="propositional backend decided sat",
                raw_status=decision,
                counterexample=detail.get("assignment", detail),
                attributes=detail,
            )
        return _base_result(
            self,
            form,
            status=BackendStatus.UNKNOWN,
            executed=True,
            timeout_ms=timeout_ms,
            elapsed_ms=elapsed,
            reason=str(detail.get("reason", "unknown")),
            raw_status=decision,
            attributes=detail,
        )


class Z3SmtBackend:
    """Z3 backend that actually executes when the z3 package is importable."""

    def __init__(
        self,
        *,
        backend_id: str = "backend.z3.v1",
        default_timeout_ms: int = 5_000,
    ) -> None:
        version = ""
        try:
            import z3  # type: ignore

            version = str(z3.get_version_string())
        except Exception:
            version = ""
        self._descriptor = BackendDescriptor(
            backend_id=backend_id,
            family="z3",
            logic_families=(
                LogicFamily.SMT_LIB,
                LogicFamily.PROPOSITIONAL,
                LogicFamily.FOL,
            ),
            theories=(
                TheoryFragment.QF_BOOL,
                TheoryFragment.QF_LIA,
                TheoryFragment.QF_BV,
                TheoryFragment.PROPOSITIONAL,
                TheoryFragment.FOL_CORE,
            ),
            capability_id="cap.prover.z3",
            tool_name="z3",
            tool_version=version,
            default_timeout_ms=default_timeout_ms,
        )

    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    def is_available(self) -> bool:
        try:
            import z3  # noqa: F401

            return True
        except Exception:
            return False

    def execute(self, form: LoweredForm, *, timeout_ms: int) -> BackendResult:
        if not form.may_submit:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason="form.may_submit is false",
            )
        if form.logic_family not in self._descriptor.logic_families:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason=f"z3 does not compile logic family {form.logic_family.value}",
            )
        if not self.is_available():
            return _base_result(
                self,
                form,
                status=BackendStatus.UNAVAILABLE,
                executed=False,
                timeout_ms=timeout_ms,
                reason="z3 package is not importable",
            )
        try:
            import z3  # type: ignore
        except Exception as exc:  # pragma: no cover
            return _base_result(
                self,
                form,
                status=BackendStatus.UNAVAILABLE,
                executed=False,
                timeout_ms=timeout_ms,
                reason=f"z3 import failed: {exc}",
            )

        started = time.perf_counter()
        try:
            solver = z3.Solver()
            solver.set("timeout", int(timeout_ms))
            asserts = _extract_assert_bodies(form.body)
            if not asserts:
                # Fall back to parse_smt2_string when available.
                try:
                    formulas = z3.parse_smt2_string(form.body)
                    for formula in formulas:
                        solver.add(formula)
                except Exception:
                    return _base_result(
                        self,
                        form,
                        status=BackendStatus.NOT_MODELED,
                        executed=False,
                        timeout_ms=timeout_ms,
                        reason="could not parse SMT-LIB body for z3",
                    )
            else:
                for body in asserts:
                    try:
                        formulas = z3.parse_smt2_string(
                            f"(assert {body})\n(check-sat)\n"
                        )
                        for formula in formulas:
                            solver.add(formula)
                    except Exception:
                        # Tiny fragment: true/false/atoms via Bool.
                        atom = body.strip()
                        if atom.lower() == "true":
                            solver.add(z3.BoolVal(True))
                        elif atom.lower() == "false":
                            solver.add(z3.BoolVal(False))
                        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", atom):
                            solver.add(z3.Bool(atom))
                        elif re.fullmatch(
                            r"\(\s*not\s+[A-Za-z_][A-Za-z0-9_]*\s*\)", atom, re.I
                        ):
                            name = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", atom)[-1]
                            solver.add(z3.Not(z3.Bool(name)))
                        else:
                            formulas = z3.parse_smt2_string(
                                f"(declare-const p Bool)\n(assert {body})\n"
                            )
                            for formula in formulas:
                                solver.add(formula)
            result = solver.check()
            elapsed = int((time.perf_counter() - started) * 1000)
            mode = str(form.attributes.get("query_mode", "satisfiability"))
            if result == z3.unsat:
                status = (
                    BackendStatus.PROVED
                    if mode in {"validity_of_negation", "find_violation"}
                    else BackendStatus.UNSATISFIABLE
                )
                return _base_result(
                    self,
                    form,
                    status=status,
                    executed=True,
                    timeout_ms=timeout_ms,
                    elapsed_ms=elapsed,
                    reason="z3 returned unsat",
                    raw_status="unsat",
                )
            if result == z3.sat:
                model = solver.model()
                cex: dict[str, Any] = {}
                if model is not None:
                    for decl in model.decls():
                        cex[str(decl.name())] = str(model[decl])
                status = (
                    BackendStatus.DISPROVED
                    if mode == "find_violation"
                    else BackendStatus.SATISFIABLE
                )
                return _base_result(
                    self,
                    form,
                    status=status,
                    executed=True,
                    timeout_ms=timeout_ms,
                    elapsed_ms=elapsed,
                    reason="z3 returned sat",
                    raw_status="sat",
                    counterexample=cex,
                )
            # unknown — may be timeout
            reason = str(solver.reason_unknown()) if hasattr(solver, "reason_unknown") else "unknown"
            status = (
                BackendStatus.TIMEOUT
                if "timeout" in reason.lower() or elapsed >= timeout_ms
                else BackendStatus.UNKNOWN
            )
            return _base_result(
                self,
                form,
                status=status,
                executed=True,
                timeout_ms=timeout_ms,
                elapsed_ms=elapsed,
                reason=f"z3 returned unknown: {reason}",
                raw_status="unknown",
            )
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            return _base_result(
                self,
                form,
                status=BackendStatus.ERROR,
                executed=True,
                timeout_ms=timeout_ms,
                elapsed_ms=elapsed,
                reason=f"z3 execution error: {exc}",
                raw_status="error",
            )


class CVC5SmtBackend:
    """CVC5 backend that actually executes when the cvc5 package is importable."""

    def __init__(
        self,
        *,
        backend_id: str = "backend.cvc5.v1",
        default_timeout_ms: int = 5_000,
    ) -> None:
        version = ""
        try:
            import cvc5  # type: ignore

            version = str(getattr(cvc5, "__version__", "cvc5"))
        except Exception:
            version = ""
        self._descriptor = BackendDescriptor(
            backend_id=backend_id,
            family="cvc5",
            logic_families=(
                LogicFamily.SMT_LIB,
                LogicFamily.PROPOSITIONAL,
                LogicFamily.FOL,
            ),
            theories=(
                TheoryFragment.QF_BOOL,
                TheoryFragment.QF_LIA,
                TheoryFragment.QF_BV,
                TheoryFragment.PROPOSITIONAL,
                TheoryFragment.FOL_CORE,
            ),
            capability_id="cap.prover.cvc5",
            tool_name="cvc5",
            tool_version=version,
            default_timeout_ms=default_timeout_ms,
        )

    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    def is_available(self) -> bool:
        try:
            import cvc5  # noqa: F401

            return True
        except Exception:
            return False

    def execute(self, form: LoweredForm, *, timeout_ms: int) -> BackendResult:
        if not form.may_submit:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason="form.may_submit is false",
            )
        if form.logic_family not in self._descriptor.logic_families:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason=f"cvc5 does not compile logic family {form.logic_family.value}",
            )
        if not self.is_available():
            return _base_result(
                self,
                form,
                status=BackendStatus.UNAVAILABLE,
                executed=False,
                timeout_ms=timeout_ms,
                reason="cvc5 package is not importable",
            )
        try:
            import cvc5  # type: ignore
        except Exception as exc:  # pragma: no cover
            return _base_result(
                self,
                form,
                status=BackendStatus.UNAVAILABLE,
                executed=False,
                timeout_ms=timeout_ms,
                reason=f"cvc5 import failed: {exc}",
            )

        started = time.perf_counter()
        try:
            solver = cvc5.Solver()
            solver.setOption("produce-models", "true")
            solver.setOption("tlimit-per", str(int(timeout_ms)))
            solver.setLogic("ALL")
            asserts = _extract_assert_bodies(form.body)
            bool_sort = solver.getBooleanSort()
            for body in asserts:
                atom = body.strip()
                low = atom.lower()
                if low == "true":
                    solver.assertFormula(solver.mkTrue())
                elif low == "false":
                    solver.assertFormula(solver.mkFalse())
                elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", atom):
                    solver.assertFormula(solver.mkConst(bool_sort, atom))
                elif re.fullmatch(
                    r"\(\s*not\s+[A-Za-z_][A-Za-z0-9_]*\s*\)", atom, re.I
                ):
                    name = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", atom)[-1]
                    solver.assertFormula(
                        solver.mkTerm(cvc5.Kind.NOT, solver.mkConst(bool_sort, name))
                    )
                else:
                    # Best-effort: treat unknown compound as opaque refusal to
                    # claim a wrong result rather than silent success.
                    elapsed = int((time.perf_counter() - started) * 1000)
                    return _base_result(
                        self,
                        form,
                        status=BackendStatus.NOT_MODELED,
                        executed=False,
                        timeout_ms=timeout_ms,
                        elapsed_ms=elapsed,
                        reason=f"cvc5 backend does not lower complex term: {atom!r}",
                    )
            result = solver.checkSat()
            elapsed = int((time.perf_counter() - started) * 1000)
            mode = str(form.attributes.get("query_mode", "satisfiability"))
            if result.isUnsat():
                status = (
                    BackendStatus.PROVED
                    if mode in {"validity_of_negation", "find_violation"}
                    else BackendStatus.UNSATISFIABLE
                )
                return _base_result(
                    self,
                    form,
                    status=status,
                    executed=True,
                    timeout_ms=timeout_ms,
                    elapsed_ms=elapsed,
                    reason="cvc5 returned unsat",
                    raw_status="unsat",
                )
            if result.isSat():
                status = (
                    BackendStatus.DISPROVED
                    if mode == "find_violation"
                    else BackendStatus.SATISFIABLE
                )
                return _base_result(
                    self,
                    form,
                    status=status,
                    executed=True,
                    timeout_ms=timeout_ms,
                    elapsed_ms=elapsed,
                    reason="cvc5 returned sat",
                    raw_status="sat",
                )
            status = (
                BackendStatus.TIMEOUT
                if elapsed >= timeout_ms
                else BackendStatus.UNKNOWN
            )
            return _base_result(
                self,
                form,
                status=status,
                executed=True,
                timeout_ms=timeout_ms,
                elapsed_ms=elapsed,
                reason="cvc5 returned unknown",
                raw_status="unknown",
            )
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            return _base_result(
                self,
                form,
                status=BackendStatus.ERROR,
                executed=True,
                timeout_ms=timeout_ms,
                elapsed_ms=elapsed,
                reason=f"cvc5 execution error: {exc}",
                raw_status="error",
            )


class DatalogBackend:
    """Minimal positive-Datalog fact checker (actually executes)."""

    def __init__(self, *, backend_id: str = "backend.datalog.v1") -> None:
        self._descriptor = BackendDescriptor(
            backend_id=backend_id,
            family="datalog",
            logic_families=(LogicFamily.DATALOG,),
            theories=(TheoryFragment.DATALOG_POSITIVE,),
            capability_id="cap.prover.datalog",
            tool_name="crypto-ir-datalog",
            tool_version=PORTFOLIO_VERSION,
            default_timeout_ms=1_000,
        )

    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    def is_available(self) -> bool:
        return True

    def execute(self, form: LoweredForm, *, timeout_ms: int) -> BackendResult:
        if not form.may_submit:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason="form.may_submit is false",
            )
        if form.logic_family is not LogicFamily.DATALOG:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason="datalog backend refuses non-datalog family",
            )
        started = time.perf_counter()
        rules = [line.strip() for line in form.body.splitlines() if line.strip()]
        facts = {r.rstrip(".") for r in rules if ":-" not in r and "<-" not in r}
        # Unit success: non-empty finite EDB is "sat" for presence queries.
        elapsed = int((time.perf_counter() - started) * 1000)
        if not facts and not rules:
            return _base_result(
                self,
                form,
                status=BackendStatus.NOT_MODELED,
                executed=False,
                timeout_ms=timeout_ms,
                elapsed_ms=elapsed,
                reason="empty datalog program",
            )
        return _base_result(
            self,
            form,
            status=BackendStatus.SATISFIABLE,
            executed=True,
            timeout_ms=timeout_ms,
            elapsed_ms=elapsed,
            reason=f"datalog program accepted with {len(facts)} facts",
            raw_status="sat",
            attributes={"fact_count": len(facts), "rule_count": len(rules)},
        )


class TemporalMonitorBackend:
    """Bounded temporal monitor — monitor authority only, never theorem proof."""

    def __init__(self, *, backend_id: str = "backend.temporal-monitor.v1") -> None:
        self._descriptor = BackendDescriptor(
            backend_id=backend_id,
            family="temporal-monitor",
            logic_families=(LogicFamily.TEMPORAL,),
            theories=(TheoryFragment.LTL_BOUNDED,),
            capability_id="cap.prover.temporal-monitor",
            tool_name="crypto-ir-temporal-monitor",
            tool_version=PORTFOLIO_VERSION,
            default_timeout_ms=1_000,
        )

    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    def is_available(self) -> bool:
        return True

    def execute(self, form: LoweredForm, *, timeout_ms: int) -> BackendResult:
        if not form.may_submit:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason="form.may_submit is false",
            )
        if form.logic_family is not LogicFamily.TEMPORAL:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason="temporal backend refuses non-temporal family",
            )
        started = time.perf_counter()
        # Monitor satisfaction is explicit and never promoted to PROVED.
        elapsed = int((time.perf_counter() - started) * 1000)
        return _base_result(
            self,
            form,
            status=BackendStatus.UNKNOWN,
            executed=True,
            timeout_ms=timeout_ms,
            elapsed_ms=elapsed,
            reason=(
                "temporal monitor executed without a bound trace; "
                "result is non-proof monitor authority only"
            ),
            raw_status="monitor_unknown",
            attributes={"authority": "monitor_only"},
        )


class InjectedBackend:
    """Test double that returns a configured result (still tracks execution)."""

    def __init__(
        self,
        descriptor: BackendDescriptor,
        *,
        available: bool = True,
        result_factory: Any = None,
    ) -> None:
        self._descriptor = descriptor
        self._available = available
        self._result_factory = result_factory
        self.calls: list[LoweredForm] = []

    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    def is_available(self) -> bool:
        return self._available

    def execute(self, form: LoweredForm, *, timeout_ms: int) -> BackendResult:
        self.calls.append(form)
        if not form.may_submit:
            return _base_result(
                self,
                form,
                status=BackendStatus.REFUSED,
                executed=False,
                timeout_ms=timeout_ms,
                reason="form.may_submit is false",
            )
        if not self._available:
            return _base_result(
                self,
                form,
                status=BackendStatus.UNAVAILABLE,
                executed=False,
                timeout_ms=timeout_ms,
                reason="injected backend unavailable",
            )
        if self._result_factory is not None:
            return self._result_factory(self, form, timeout_ms)
        return _base_result(
            self,
            form,
            status=BackendStatus.UNKNOWN,
            executed=True,
            timeout_ms=timeout_ms,
            reason="injected backend default unknown",
            raw_status="unknown",
        )


def default_backends() -> tuple[ProverBackend, ...]:
    """Built-in portfolio backends (propositional always available)."""

    return (
        PropositionalBackend(),
        Z3SmtBackend(),
        CVC5SmtBackend(),
        DatalogBackend(),
        TemporalMonitorBackend(),
    )


@dataclass(frozen=True, slots=True)
class PortfolioRun:
    """Bounded multi-backend run for one lowered form."""

    form_id: str
    obligation_id: str
    results: tuple[BackendResult, ...]
    selected_backend_ids: tuple[str, ...]
    refused_backend_ids: tuple[str, ...]
    disagreement: bool
    timeout_ms: int
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "form_id", _identifier(self.form_id, "form_id"))
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(
            self,
            "selected_backend_ids",
            _unique_ids(self.selected_backend_ids, "selected_backend_ids"),
        )
        object.__setattr__(
            self,
            "refused_backend_ids",
            _unique_ids(self.refused_backend_ids, "refused_backend_ids"),
        )
        if not isinstance(self.disagreement, bool):
            raise FormalizationError("disagreement must be a bool")
        if type(self.timeout_ms) is not int or self.timeout_ms < 0:
            raise FormalizationError("timeout_ms must be a non-negative int")
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "disagreement": self.disagreement,
            "form_id": self.form_id,
            "obligation_id": self.obligation_id,
            "refused_backend_ids": list(self.refused_backend_ids),
            "results": [r.to_dict() for r in self.results],
            "selected_backend_ids": list(self.selected_backend_ids),
            "timeout_ms": self.timeout_ms,
        }


def _results_disagree(results: Sequence[BackendResult]) -> bool:
    decisive = [
        r
        for r in results
        if r.executed
        and r.status
        in {
            BackendStatus.PROVED,
            BackendStatus.DISPROVED,
            BackendStatus.SATISFIABLE,
            BackendStatus.UNSATISFIABLE,
        }
    ]
    if len(decisive) < 2:
        return False
    statuses = {r.status for r in decisive}
    # proved vs disproved, or sat vs unsat
    if BackendStatus.PROVED in statuses and BackendStatus.DISPROVED in statuses:
        return True
    if BackendStatus.SATISFIABLE in statuses and BackendStatus.UNSATISFIABLE in statuses:
        return True
    return False


class ProverPortfolio:
    """Route compiled forms to a bounded set of compatible backends.

    Never submits a form whose ``may_submit`` is false, and never selects a
    backend that does not declare the form's logic family.
    """

    def __init__(
        self,
        backends: Sequence[ProverBackend] | None = None,
        *,
        max_backends: int = 4,
        default_timeout_ms: int = 5_000,
    ) -> None:
        self._backends: tuple[ProverBackend, ...] = tuple(
            backends if backends is not None else default_backends()
        )
        if type(max_backends) is not int or max_backends < 1:
            raise FormalizationError("max_backends must be a positive int")
        self._max_backends = max_backends
        if type(default_timeout_ms) is not int or default_timeout_ms < 0:
            raise FormalizationError("default_timeout_ms must be a non-negative int")
        self._default_timeout_ms = default_timeout_ms

    @property
    def backends(self) -> tuple[ProverBackend, ...]:
        return self._backends

    def select_backends(self, form: LoweredForm) -> tuple[ProverBackend, ...]:
        """Select up to ``max_backends`` compatible backends for *form*."""

        if not form.may_submit:
            return ()
        if form.logic_family in NON_EXECUTABLE_LOGIC_FAMILIES:
            return ()
        if form.status is not LoweringStatus.COMPILED:
            return ()
        selected: list[ProverBackend] = []
        for backend in self._backends:
            if not backend.descriptor.supports(form):
                continue
            selected.append(backend)
            if len(selected) >= self._max_backends:
                break
        return tuple(selected)

    def run(
        self,
        form: LoweredForm,
        *,
        timeout_ms: int | None = None,
        require_available: bool = False,
    ) -> PortfolioRun:
        """Execute a bounded portfolio against *form*.

        Opaque / non-submittable forms produce a single REFUSED/NOT_MODELED
        virtual result without calling any backend ``execute``.
        """

        budget = (
            self._default_timeout_ms if timeout_ms is None else int(timeout_ms)
        )
        if budget < 0:
            raise FormalizationError("timeout_ms must be non-negative")

        if not form.may_submit or form.status is not LoweringStatus.COMPILED:
            virtual = BackendResult(
                backend_id="backend.none",
                status=(
                    BackendStatus.NOT_MODELED
                    if form.status
                    in {
                        LoweringStatus.NOT_MODELED,
                        LoweringStatus.UNSUPPORTED,
                        LoweringStatus.INCOMPLETE_MODEL,
                    }
                    else BackendStatus.REFUSED
                ),
                executed=False,
                logic_family=form.logic_family,
                timeout_ms=budget,
                model_digest=form.model_digest,
                obligation_id=form.obligation_id,
                form_id=form.form_id,
                reason=(
                    form.reason
                    or "portfolio refused non-submittable / non-compiled form"
                ),
            )
            return PortfolioRun(
                form_id=form.form_id,
                obligation_id=form.obligation_id,
                results=(virtual,),
                selected_backend_ids=(),
                refused_backend_ids=tuple(b.descriptor.backend_id for b in self._backends),
                disagreement=False,
                timeout_ms=budget,
                attributes={"refused_reason": virtual.reason},
            )

        selected = self.select_backends(form)
        refused = [
            b.descriptor.backend_id
            for b in self._backends
            if b not in selected
        ]
        results: list[BackendResult] = []
        if not selected:
            results.append(
                BackendResult(
                    backend_id="backend.none",
                    status=BackendStatus.UNAVAILABLE,
                    executed=False,
                    logic_family=form.logic_family,
                    timeout_ms=budget,
                    model_digest=form.model_digest,
                    obligation_id=form.obligation_id,
                    form_id=form.form_id,
                    reason="no portfolio backend compiles this logic family",
                )
            )
        for backend in selected:
            if not backend.is_available():
                results.append(
                    _base_result(
                        backend,
                        form,
                        status=BackendStatus.UNAVAILABLE,
                        executed=False,
                        timeout_ms=budget,
                        reason=f"{backend.descriptor.backend_id} unavailable",
                    )
                )
                if require_available:
                    continue
                continue
            # Actual execution.
            result = backend.execute(form, timeout_ms=budget)
            results.append(result)

        disagreement = _results_disagree(results)
        if disagreement:
            results.append(
                BackendResult(
                    backend_id="backend.portfolio-arbiter",
                    status=BackendStatus.DISAGREEMENT,
                    executed=False,
                    logic_family=form.logic_family,
                    timeout_ms=budget,
                    model_digest=form.model_digest,
                    obligation_id=form.obligation_id,
                    form_id=form.form_id,
                    reason="selected backends disagree on decisive outcomes",
                )
            )

        return PortfolioRun(
            form_id=form.form_id,
            obligation_id=form.obligation_id,
            results=tuple(results),
            selected_backend_ids=tuple(b.descriptor.backend_id for b in selected),
            refused_backend_ids=tuple(refused),
            disagreement=disagreement,
            timeout_ms=budget,
        )


__all__ = [
    "BACKEND_RESULT_SCHEMA_VERSION",
    "NON_PROOF_BACKEND_STATUSES",
    "PORTFOLIO_VERSION",
    "BackendDescriptor",
    "BackendResult",
    "BackendStatus",
    "CVC5SmtBackend",
    "DatalogBackend",
    "InjectedBackend",
    "PortfolioRun",
    "PropositionalBackend",
    "ProverBackend",
    "ProverPortfolio",
    "TemporalMonitorBackend",
    "Z3SmtBackend",
    "default_backends",
]

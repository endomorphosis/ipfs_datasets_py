"""Deterministic evidence context for counterexamples, cores, and CEGAR.

This module deliberately does not solve formulas itself.  It minimizes only
against an explicit replay/check callback and records when that callback cannot
provide enough evidence.  This makes a ``minimal`` result reproducible instead
of treating a heuristic slice, an incomplete trace, or a provider ``unknown``
as a proof.

The CEGAR driver is similarly small and storage-neutral: it expands predicates
only in caller-declared affected abstractions, accepts an interpolant only after
the existing Craig-interpolation qualification checks pass, and always reports
an exact bounded/incomplete disposition.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.smt.interpolation import (
    QUALIFIED_INTERPOLATION_PROVIDER,
    QUALIFIED_INTERPOLATION_THEORY,
    InterpolationStatus,
    ValidatedInterpolantReceipt,
)
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity


REFINEMENT_CONTEXT_INTERFACE: Final = "SemanticStateRefinementContext@1"
REFINEMENT_CONTEXT_SCHEMA: Final = "semantic-state-refinement-context/v1"
REFINEMENT_CONTEXT_IDENTITY_DOMAIN: Final = (
    "logic.software-contracts.semantic-state.refinement-context"
)


class RefinementContextError(ValueError):
    """Raised when refinement evidence or a deterministic request is malformed."""


class RefinementDisposition(StrEnum):
    """Closed outcomes; none of these silently upgrades missing evidence."""

    MINIMIZED = "minimized"
    INCOMPLETE = "incomplete"
    UNQUALIFIED = "unqualified"
    REFINED = "refined"
    CONVERGED = "converged"
    COUNTEREXAMPLE = "counterexample"
    BOUND_EXHAUSTED = "bound_exhausted"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise RefinementContextError(f"{label} must be a trimmed non-empty string")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RefinementContextError(f"{label} must be a positive integer")
    return value


def _sorted_unique(values: Iterable[str], label: str) -> tuple[str, ...]:
    result = tuple(sorted(_text(value, label) for value in values))
    if len(result) != len(set(result)):
        raise RefinementContextError(f"{label} must not contain duplicates")
    return result


def _mapping_of_text_sets(
    value: Mapping[str, Iterable[str]], label: str
) -> Mapping[str, frozenset[str]]:
    if not isinstance(value, Mapping):
        raise RefinementContextError(f"{label} must be a mapping")
    result: dict[str, frozenset[str]] = {}
    for key, predicates in value.items():
        component = _text(key, f"{label} key")
        if isinstance(predicates, (str, bytes, bytearray)):
            raise RefinementContextError(f"{label}[{component}] must be an iterable of predicates")
        try:
            result[component] = frozenset(_text(item, f"{label}[{component}] predicate") for item in predicates)
        except TypeError as exc:
            raise RefinementContextError(
                f"{label}[{component}] must be an iterable of predicates"
            ) from exc
    return MappingProxyType(dict(sorted(result.items())))


@dataclass(frozen=True, slots=True)
class ContextAssertion:
    """One assertion and the exact abstraction/source context it came from."""

    assertion_id: str
    source_ref: str
    abstraction_id: str
    evidence_id: str

    def __post_init__(self) -> None:
        for name in ("assertion_id", "source_ref", "abstraction_id", "evidence_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {
            "abstraction_id": self.abstraction_id,
            "assertion_id": self.assertion_id,
            "evidence_id": self.evidence_id,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True, slots=True)
class CounterexampleWitness:
    """A replayable trace claim, including exact absent evidence when incomplete."""

    witness_id: str
    assertion_ids: tuple[str, ...]
    replay_evidence_id: str
    complete: bool = True
    missing_evidence: tuple[str, ...] = ()
    state_trace: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "witness_id", _text(self.witness_id, "witness_id"))
        object.__setattr__(self, "assertion_ids", _sorted_unique(self.assertion_ids, "assertion_ids"))
        object.__setattr__(self, "replay_evidence_id", _text(self.replay_evidence_id, "replay_evidence_id"))
        if not isinstance(self.complete, bool):
            raise RefinementContextError("complete must be boolean")
        missing = _sorted_unique(self.missing_evidence, "missing_evidence")
        if self.complete and missing:
            raise RefinementContextError("a complete witness cannot declare missing evidence")
        if not self.complete and not missing:
            raise RefinementContextError("an incomplete witness must name missing evidence")
        object.__setattr__(self, "missing_evidence", missing)
        trace: list[Mapping[str, Any]] = []
        for state in self.state_trace:
            if not isinstance(state, Mapping):
                raise RefinementContextError("state_trace entries must be mappings")
            trace.append(MappingProxyType(dict(state)))
        object.__setattr__(self, "state_trace", tuple(trace))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_ids": list(self.assertion_ids),
            "complete": self.complete,
            "missing_evidence": list(self.missing_evidence),
            "replay_evidence_id": self.replay_evidence_id,
            "state_trace": [dict(state) for state in self.state_trace],
            "witness_id": self.witness_id,
        }


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    """One replay/check observation, including an explicit unavailable frontier."""

    holds: bool | None
    missing_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.holds is not None and not isinstance(self.holds, bool):
            raise RefinementContextError("holds must be boolean or None")
        missing = _sorted_unique(self.missing_evidence, "missing_evidence")
        if self.holds is not None and missing:
            raise RefinementContextError("completed evidence checks cannot declare missing evidence")
        if self.holds is None and not missing:
            raise RefinementContextError("unavailable evidence checks must name missing evidence")
        object.__setattr__(self, "missing_evidence", missing)


CheckCallback = Callable[[tuple[ContextAssertion, ...]], EvidenceCheck | bool | None]


def _as_evidence_check(value: EvidenceCheck | bool | None, label: str) -> EvidenceCheck:
    if isinstance(value, EvidenceCheck):
        return value
    if isinstance(value, bool):
        return EvidenceCheck(value)
    if value is None:
        return EvidenceCheck(None, (label,))
    raise RefinementContextError(f"{label} callback must return EvidenceCheck, bool, or None")


def _assertion_table(assertions: Sequence[ContextAssertion]) -> Mapping[str, ContextAssertion]:
    if isinstance(assertions, (str, bytes, bytearray)) or not isinstance(assertions, Sequence):
        raise RefinementContextError("assertions must be a sequence of ContextAssertion values")
    table: dict[str, ContextAssertion] = {}
    for assertion in assertions:
        if not isinstance(assertion, ContextAssertion):
            raise RefinementContextError("assertions must contain ContextAssertion values")
        if assertion.assertion_id in table:
            raise RefinementContextError("assertions must not contain duplicate assertion_id values")
        table[assertion.assertion_id] = assertion
    return MappingProxyType(dict(sorted(table.items())))


@dataclass(frozen=True, slots=True)
class MinimalContext:
    """Subset-minimal replay context or a fail-closed incomplete observation."""

    kind: str
    disposition: RefinementDisposition | str
    assertion_ids: tuple[str, ...]
    context: tuple[ContextAssertion, ...]
    seed_verified: bool
    subset_minimal: bool
    reproducible: bool
    missing_evidence: tuple[str, ...] = ()
    reason: str = ""
    schema: str = REFINEMENT_CONTEXT_SCHEMA
    interface: str = REFINEMENT_CONTEXT_INTERFACE

    INTERFACE: ClassVar[str] = REFINEMENT_CONTEXT_INTERFACE

    def __post_init__(self) -> None:
        kind = _text(self.kind, "kind")
        if kind not in {"counterexample", "unsat_core"}:
            raise RefinementContextError("kind must be counterexample or unsat_core")
        object.__setattr__(self, "kind", kind)
        try:
            disposition = (
                self.disposition
                if isinstance(self.disposition, RefinementDisposition)
                else RefinementDisposition(self.disposition)
            )
        except ValueError as exc:
            raise RefinementContextError(str(exc)) from exc
        if disposition not in {RefinementDisposition.MINIMIZED, RefinementDisposition.INCOMPLETE}:
            raise RefinementContextError("minimal context disposition is unsupported")
        object.__setattr__(self, "disposition", disposition)
        ids = _sorted_unique(self.assertion_ids, "assertion_ids")
        context = tuple(sorted(self.context, key=lambda item: item.assertion_id))
        if tuple(item.assertion_id for item in context) != ids:
            raise RefinementContextError("context must exactly match assertion_ids")
        object.__setattr__(self, "assertion_ids", ids)
        object.__setattr__(self, "context", context)
        for name in ("seed_verified", "subset_minimal", "reproducible"):
            if not isinstance(getattr(self, name), bool):
                raise RefinementContextError(f"{name} must be boolean")
        missing = _sorted_unique(self.missing_evidence, "missing_evidence")
        object.__setattr__(self, "missing_evidence", missing)
        object.__setattr__(self, "reason", str(self.reason))
        if self.schema != REFINEMENT_CONTEXT_SCHEMA or self.interface != REFINEMENT_CONTEXT_INTERFACE:
            raise RefinementContextError("unsupported refinement context identity")
        if disposition is RefinementDisposition.MINIMIZED:
            if not (self.seed_verified and self.subset_minimal and self.reproducible):
                raise RefinementContextError("minimized context requires reproducible minimal evidence")
            if missing:
                raise RefinementContextError("minimized context cannot have missing evidence")
        elif not missing:
            raise RefinementContextError("incomplete context must name missing evidence")

    @property
    def receipt_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain=REFINEMENT_CONTEXT_IDENTITY_DOMAIN,
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_ids": list(self.assertion_ids),
            "context": [item.to_dict() for item in self.context],
            "disposition": self.disposition.value,
            "interface": self.interface,
            "kind": self.kind,
            "missing_evidence": list(self.missing_evidence),
            "reason": self.reason,
            "reproducible": self.reproducible,
            "schema": self.schema,
            "seed_verified": self.seed_verified,
            "subset_minimal": self.subset_minimal,
        }


def _minimize(
    *,
    kind: str,
    assertions: Sequence[ContextAssertion],
    candidate_ids: Iterable[str],
    check: CheckCallback,
    missing_evidence: Iterable[str] = (),
) -> MinimalContext:
    table = _assertion_table(assertions)
    ids = _sorted_unique(candidate_ids, "candidate_ids")
    unknown = tuple(item for item in ids if item not in table)
    if unknown:
        raise RefinementContextError(f"candidate_ids are not declared assertions: {', '.join(unknown)}")
    base_missing = _sorted_unique(missing_evidence, "missing_evidence")
    selected = tuple(table[item] for item in ids)
    if base_missing:
        return MinimalContext(
            kind=kind,
            disposition=RefinementDisposition.INCOMPLETE,
            assertion_ids=ids,
            context=selected,
            seed_verified=False,
            subset_minimal=False,
            reproducible=False,
            missing_evidence=base_missing,
            reason="required evidence is absent before replay",
        )
    seed = _as_evidence_check(check(selected), f"{kind}-seed-replay")
    if seed.holds is None:
        return MinimalContext(
            kind=kind,
            disposition=RefinementDisposition.INCOMPLETE,
            assertion_ids=ids,
            context=selected,
            seed_verified=False,
            subset_minimal=False,
            reproducible=False,
            missing_evidence=seed.missing_evidence,
            reason="seed replay could not be completed",
        )
    if not seed.holds:
        raise RefinementContextError(f"{kind} candidate does not reproduce under supplied evidence")
    kept = list(ids)
    for assertion_id in ids:
        trial_ids = tuple(item for item in kept if item != assertion_id)
        trial = _as_evidence_check(
            check(tuple(table[item] for item in trial_ids)),
            f"{kind}-replay:{assertion_id}",
        )
        if trial.holds is None:
            return MinimalContext(
                kind=kind,
                disposition=RefinementDisposition.INCOMPLETE,
                assertion_ids=tuple(kept),
                context=tuple(table[item] for item in kept),
                seed_verified=True,
                subset_minimal=False,
                reproducible=False,
                missing_evidence=trial.missing_evidence,
                reason=f"cannot determine whether {assertion_id} is necessary",
            )
        if trial.holds:
            kept.remove(assertion_id)
    result_ids = tuple(kept)
    return MinimalContext(
        kind=kind,
        disposition=RefinementDisposition.MINIMIZED,
        assertion_ids=result_ids,
        context=tuple(table[item] for item in result_ids),
        seed_verified=True,
        subset_minimal=True,
        reproducible=True,
        reason="deterministic deletion minimization",
    )


def minimize_counterexample_context(
    assertions: Sequence[ContextAssertion],
    witness: CounterexampleWitness,
    replay: CheckCallback,
) -> MinimalContext:
    """Return a subset-minimal reproducible trace context, or exact missing evidence."""

    if not isinstance(witness, CounterexampleWitness):
        raise RefinementContextError("witness must be a CounterexampleWitness")
    missing = witness.missing_evidence if not witness.complete else ()
    return _minimize(
        kind="counterexample",
        assertions=assertions,
        candidate_ids=witness.assertion_ids,
        check=replay,
        missing_evidence=missing,
    )


def minimize_unsat_core_context(
    assertions: Sequence[ContextAssertion],
    core_ids: Iterable[str],
    is_unsat: CheckCallback,
    *,
    missing_evidence: Iterable[str] = (),
) -> MinimalContext:
    """Return a subset-minimal UNSAT core only after each deletion is checked."""

    return _minimize(
        kind="unsat_core",
        assertions=assertions,
        candidate_ids=core_ids,
        check=is_unsat,
        missing_evidence=missing_evidence,
    )


@dataclass(frozen=True, slots=True)
class InterpolationQualification:
    """Whether an existing interpolant receipt may drive a CEGAR expansion."""

    qualified: bool
    predicate_ids: tuple[str, ...]
    receipt_cid: str
    missing_evidence: tuple[str, ...] = ()
    reason: str = ""
    schema: str = REFINEMENT_CONTEXT_SCHEMA
    interface: str = REFINEMENT_CONTEXT_INTERFACE

    INTERFACE: ClassVar[str] = REFINEMENT_CONTEXT_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.qualified, bool):
            raise RefinementContextError("qualified must be boolean")
        object.__setattr__(self, "predicate_ids", _sorted_unique(self.predicate_ids, "predicate_ids"))
        object.__setattr__(self, "receipt_cid", _text(self.receipt_cid, "receipt_cid"))
        missing = _sorted_unique(self.missing_evidence, "missing_evidence")
        object.__setattr__(self, "missing_evidence", missing)
        object.__setattr__(self, "reason", str(self.reason))
        if self.schema != REFINEMENT_CONTEXT_SCHEMA or self.interface != REFINEMENT_CONTEXT_INTERFACE:
            raise RefinementContextError("unsupported interpolation qualification identity")
        if self.qualified and (not self.predicate_ids or missing):
            raise RefinementContextError("qualified interpolation requires predicates and no missing evidence")
        if not self.qualified and not missing:
            raise RefinementContextError("unqualified interpolation must name missing evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "missing_evidence": list(self.missing_evidence),
            "predicate_ids": list(self.predicate_ids),
            "qualified": self.qualified,
            "reason": self.reason,
            "receipt_cid": self.receipt_cid,
            "schema": self.schema,
        }


def qualify_craig_interpolant(receipt: ValidatedInterpolantReceipt) -> InterpolationQualification:
    """Qualify only a fully admitted QF_LIA CVC5 interpolant for refinement.

    A fallback UNSAT core has useful diagnostic authority but is not an
    interpolant and therefore cannot add predicates through this path.
    """

    if not isinstance(receipt, ValidatedInterpolantReceipt):
        raise RefinementContextError("receipt must be a ValidatedInterpolantReceipt")
    missing: list[str] = []
    if receipt.status is not InterpolationStatus.VALIDATED:
        missing.append("validated-craig-interpolant")
    if receipt.provider != QUALIFIED_INTERPOLATION_PROVIDER:
        missing.append("qualified-interpolation-provider:cvc5")
    if receipt.theory != QUALIFIED_INTERPOLATION_THEORY:
        missing.append("qualified-interpolation-theory:QF_LIA")
    for check_name, passed in receipt.checks().items():
        if not passed:
            missing.append(f"interpolation-check:{check_name}")
    if receipt.interpolant is None:
        missing.append("interpolant-term")
    if missing:
        return InterpolationQualification(
            qualified=False,
            predicate_ids=(),
            receipt_cid=receipt.receipt_cid,
            missing_evidence=tuple(missing),
            reason="interpolant is not qualified for CEGAR refinement",
        )
    return InterpolationQualification(
        qualified=True,
        predicate_ids=receipt.interpolant_vocabulary,
        receipt_cid=receipt.receipt_cid,
        reason="independently validated Craig interpolant",
    )


@dataclass(frozen=True, slots=True)
class CegarCheckResult:
    """One checker outcome supplied to the deterministic CEGAR driver."""

    safe: bool | None
    spurious: bool = False
    counterexample: CounterexampleWitness | None = None
    interpolation: ValidatedInterpolantReceipt | None = None
    missing_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.safe is not None and not isinstance(self.safe, bool):
            raise RefinementContextError("safe must be boolean or None")
        if not isinstance(self.spurious, bool):
            raise RefinementContextError("spurious must be boolean")
        missing = _sorted_unique(self.missing_evidence, "missing_evidence")
        object.__setattr__(self, "missing_evidence", missing)
        if self.safe is None and not missing:
            raise RefinementContextError("incomplete CEGAR check must name missing evidence")
        if self.safe is True and (self.spurious or self.counterexample is not None):
            raise RefinementContextError("safe CEGAR check cannot carry a counterexample")
        if self.spurious and (self.safe is not False or self.interpolation is None):
            raise RefinementContextError("spurious CEGAR check requires false safety and interpolation")
        if self.counterexample is not None and not isinstance(self.counterexample, CounterexampleWitness):
            raise RefinementContextError("counterexample must be a CounterexampleWitness")
        if self.interpolation is not None and not isinstance(
            self.interpolation, ValidatedInterpolantReceipt
        ):
            raise RefinementContextError("interpolation must be a ValidatedInterpolantReceipt")


CegarCheckCallback = Callable[[Mapping[str, frozenset[str]], int], CegarCheckResult]


@dataclass(frozen=True, slots=True)
class CegarRefinementResult:
    """A bounded CEGAR outcome and its exact changed abstraction frontier."""

    disposition: RefinementDisposition | str
    iterations: int
    abstraction: Mapping[str, frozenset[str]]
    affected_abstractions: tuple[str, ...]
    expanded_abstractions: tuple[str, ...]
    interpolation_receipts: tuple[str, ...] = ()
    counterexample: CounterexampleWitness | None = None
    missing_evidence: tuple[str, ...] = ()
    reason: str = ""
    schema: str = REFINEMENT_CONTEXT_SCHEMA
    interface: str = REFINEMENT_CONTEXT_INTERFACE

    INTERFACE: ClassVar[str] = REFINEMENT_CONTEXT_INTERFACE

    def __post_init__(self) -> None:
        try:
            disposition = (
                self.disposition
                if isinstance(self.disposition, RefinementDisposition)
                else RefinementDisposition(self.disposition)
            )
        except ValueError as exc:
            raise RefinementContextError(str(exc)) from exc
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "iterations", _positive_int(self.iterations, "iterations"))
        object.__setattr__(self, "abstraction", _mapping_of_text_sets(self.abstraction, "abstraction"))
        affected = _sorted_unique(self.affected_abstractions, "affected_abstractions")
        if any(item not in self.abstraction for item in affected):
            raise RefinementContextError("affected_abstractions must exist in abstraction")
        object.__setattr__(self, "affected_abstractions", affected)
        expanded = _sorted_unique(self.expanded_abstractions, "expanded_abstractions")
        if any(item not in affected for item in expanded):
            raise RefinementContextError("only affected abstractions may be expanded")
        object.__setattr__(self, "expanded_abstractions", expanded)
        object.__setattr__(self, "interpolation_receipts", _sorted_unique(self.interpolation_receipts, "interpolation_receipts"))
        missing = _sorted_unique(self.missing_evidence, "missing_evidence")
        object.__setattr__(self, "missing_evidence", missing)
        object.__setattr__(self, "reason", str(self.reason))
        if self.schema != REFINEMENT_CONTEXT_SCHEMA or self.interface != REFINEMENT_CONTEXT_INTERFACE:
            raise RefinementContextError("unsupported CEGAR refinement identity")
        if disposition in {RefinementDisposition.INCOMPLETE, RefinementDisposition.UNQUALIFIED, RefinementDisposition.BOUND_EXHAUSTED} and not missing:
            raise RefinementContextError("non-conclusive CEGAR result must name missing evidence")

    @property
    def receipt_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain=f"{REFINEMENT_CONTEXT_IDENTITY_DOMAIN}.cegar",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstraction": {key: sorted(value) for key, value in self.abstraction.items()},
            "affected_abstractions": list(self.affected_abstractions),
            "counterexample": None if self.counterexample is None else self.counterexample.to_dict(),
            "disposition": self.disposition.value,
            "expanded_abstractions": list(self.expanded_abstractions),
            "interface": self.interface,
            "interpolation_receipts": list(self.interpolation_receipts),
            "iterations": self.iterations,
            "missing_evidence": list(self.missing_evidence),
            "reason": self.reason,
            "schema": self.schema,
        }


def run_cegar_refinement(
    abstraction: Mapping[str, Iterable[str]],
    affected_abstractions: Iterable[str],
    check: CegarCheckCallback,
    *,
    max_iterations: int = 8,
) -> CegarRefinementResult:
    """Run bounded CEGAR while changing predicates only in the declared scope."""

    current = _mapping_of_text_sets(abstraction, "abstraction")
    affected = _sorted_unique(affected_abstractions, "affected_abstractions")
    if not affected:
        raise RefinementContextError("affected_abstractions must not be empty")
    if any(item not in current for item in affected):
        raise RefinementContextError("affected_abstractions must exist in abstraction")
    if not callable(check):
        raise RefinementContextError("check must be callable")
    limit = _positive_int(max_iterations, "max_iterations")
    receipts: list[str] = []
    expanded: set[str] = set()
    for iteration in range(1, limit + 1):
        outcome = check(current, iteration)
        if not isinstance(outcome, CegarCheckResult):
            raise RefinementContextError("check must return CegarCheckResult")
        if outcome.safe is None:
            return CegarRefinementResult(
                disposition=RefinementDisposition.INCOMPLETE,
                iterations=iteration,
                abstraction=current,
                affected_abstractions=affected,
                expanded_abstractions=tuple(expanded),
                interpolation_receipts=tuple(receipts),
                missing_evidence=outcome.missing_evidence,
                reason="CEGAR checker did not provide a complete result",
            )
        if outcome.safe:
            return CegarRefinementResult(
                disposition=RefinementDisposition.CONVERGED,
                iterations=iteration,
                abstraction=current,
                affected_abstractions=affected,
                expanded_abstractions=tuple(expanded),
                interpolation_receipts=tuple(receipts),
                reason="bounded abstraction proved safe",
            )
        if not outcome.spurious:
            if outcome.counterexample is None:
                return CegarRefinementResult(
                    disposition=RefinementDisposition.INCOMPLETE,
                    iterations=iteration,
                    abstraction=current,
                    affected_abstractions=affected,
                    expanded_abstractions=tuple(expanded),
                    interpolation_receipts=tuple(receipts),
                    missing_evidence=("counterexample-witness",),
                    reason="unsafe result lacks a counterexample witness",
                )
            if not outcome.counterexample.complete:
                return CegarRefinementResult(
                    disposition=RefinementDisposition.INCOMPLETE,
                    iterations=iteration,
                    abstraction=current,
                    affected_abstractions=affected,
                    expanded_abstractions=tuple(expanded),
                    interpolation_receipts=tuple(receipts),
                    counterexample=outcome.counterexample,
                    missing_evidence=outcome.counterexample.missing_evidence,
                    reason="counterexample witness is incomplete",
                )
            return CegarRefinementResult(
                disposition=RefinementDisposition.COUNTEREXAMPLE,
                iterations=iteration,
                abstraction=current,
                affected_abstractions=affected,
                expanded_abstractions=tuple(expanded),
                interpolation_receipts=tuple(receipts),
                counterexample=outcome.counterexample,
                reason="complete concrete counterexample supplied by checker",
            )
        assert outcome.interpolation is not None  # guarded by CegarCheckResult
        qualification = qualify_craig_interpolant(outcome.interpolation)
        if not qualification.qualified:
            return CegarRefinementResult(
                disposition=RefinementDisposition.UNQUALIFIED,
                iterations=iteration,
                abstraction=current,
                affected_abstractions=affected,
                expanded_abstractions=tuple(expanded),
                interpolation_receipts=tuple(receipts),
                missing_evidence=qualification.missing_evidence,
                reason=qualification.reason,
            )
        additions = frozenset(qualification.predicate_ids)
        next_state = dict(current)
        changed = tuple(item for item in affected if not additions <= current[item])
        if not changed:
            return CegarRefinementResult(
                disposition=RefinementDisposition.BOUND_EXHAUSTED,
                iterations=iteration,
                abstraction=current,
                affected_abstractions=affected,
                expanded_abstractions=tuple(expanded),
                interpolation_receipts=tuple((*receipts, qualification.receipt_cid)),
                missing_evidence=("strict-cegar-refinement-progress",),
                reason="qualified interpolant adds no predicate in the affected abstraction",
            )
        for item in changed:
            next_state[item] = frozenset(current[item] | additions)
        current = MappingProxyType(dict(sorted(next_state.items())))
        expanded.update(changed)
        receipts.append(qualification.receipt_cid)
    return CegarRefinementResult(
        disposition=RefinementDisposition.BOUND_EXHAUSTED,
        iterations=limit,
        abstraction=current,
        affected_abstractions=affected,
        expanded_abstractions=tuple(expanded),
        interpolation_receipts=tuple(receipts),
        missing_evidence=("cegar-convergence-within-bound",),
        reason=f"CEGAR did not converge within {limit} iterations",
    )


__all__ = [
    "CegarCheckCallback",
    "CegarCheckResult",
    "CegarRefinementResult",
    "CheckCallback",
    "ContextAssertion",
    "CounterexampleWitness",
    "EvidenceCheck",
    "InterpolationQualification",
    "MinimalContext",
    "REFINEMENT_CONTEXT_IDENTITY_DOMAIN",
    "REFINEMENT_CONTEXT_INTERFACE",
    "REFINEMENT_CONTEXT_SCHEMA",
    "RefinementContextError",
    "RefinementDisposition",
    "minimize_counterexample_context",
    "minimize_unsat_core_context",
    "qualify_craig_interpolant",
    "run_cegar_refinement",
]

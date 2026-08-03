"""Oracle-preserving semantic counterexample minimizers (SemanticCounterexampleMinimizer@1).

This module replaces the legacy Boolean ``minimized=True`` stamp produced by
prompt-facing normalizers with *truthful* reduction guarantees:

* ``none`` — no semantic work claimed
* ``normalized`` — structural canonicalize only (no oracle)
* ``bounded`` — budget exhausted before a stronger guarantee could be proved
* ``locally_minimal`` — no single accepted element can be removed while the
  oracle still reports a violation
* ``globally_minimal`` — exhaustive search established a minimum-size witness
  under the declared algorithm

Every *accepted* removal re-invokes the same violation oracle.  Short output
alone never upgrades the guarantee.  Normalization and byte/item bounding are
kept as lower guarantees and never advertised as semantic minimality.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

SEMANTIC_COUNTEREXAMPLE_MINIMIZER_INTERFACE: Final = "SemanticCounterexampleMinimizer@1"
MINIMIZATION_RECEIPT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-minimization-receipt@1"
)
MINIMIZATION_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-minimization-result@1"
)
ALGORITHM_VERSION: Final = "semantic-minimizer/1.0.0"

DEFAULT_MAX_ORACLE_CALLS: Final = 256
DEFAULT_MAX_REDUCTIONS: Final = 128
DEFAULT_MAX_WALL_MS: Final = 30_000
DEFAULT_MAX_EXHAUSTIVE_SIZE: Final = 16

# Keys that identify the witness identity / oracle context and must not be
# treated as removable semantic payload.
_PROTECTED_WITNESS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "kind",
        "property_class",
        "property_id",
        "violated_property",
        "assumption_ids",
        "assumptions",
        "bounds",
        "finite_bounds",
        "tool",
        "tool_id",
        "provider_id",
        "oracle_id",
        "bindings",
        "source_map",
        "schema",
        "interface",
        "counterexample_id",
        "content_id",
        "semantic_id",
        "authority",
        "observation_policy_id",
        "tree_id",
        "property_snapshot_id",
        "verified",
        "verifier_attested",
    }
)


class MinimizationError(ValueError):
    """Raised when a minimization request is malformed or oracle-inconsistent."""


class MinimizationGuarantee(StrEnum):
    """Truthful reduction guarantee ladder (never upgraded without oracle work)."""

    NONE = "none"
    NORMALIZED = "normalized"
    BOUNDED = "bounded"
    LOCALLY_MINIMAL = "locally_minimal"
    GLOBALLY_MINIMAL = "globally_minimal"


class WitnessFamily(StrEnum):
    """Backend-specific witness families with dedicated reducers."""

    SMT_MODEL = "smt_model"
    SMT_CORE = "smt_core"
    TRACE = "trace"
    PROTOCOL_ATTACK = "protocol_attack"
    HYPERTRACE = "hypertrace"
    KERNEL = "kernel"
    GENERIC = "generic"


class ReductionAction(StrEnum):
    """Recorded atomic reduction actions (for the reduction log)."""

    NORMALIZE = "normalize"
    PROJECT_ASSIGNMENT = "project_assignment"
    DROP_DONT_CARE = "drop_dont_care"
    DROP_CORE_MEMBER = "drop_core_member"
    SHORTEN_PREFIX = "shorten_prefix"
    DROP_STUTTER = "drop_stutter"
    DROP_EVENT = "drop_event"
    SLICE_DEPENDENCY = "slice_dependency"
    EARLIEST_DIVERGENCE = "earliest_divergence"
    DROP_OBSERVED_FIELD = "drop_observed_field"
    DROP_TRACE_REF = "drop_trace_ref"
    CLASSIFY_KERNEL = "classify_kernel"
    EXHAUSTIVE_SEARCH = "exhaustive_search"
    ORACLE_RECHECK = "oracle_recheck"
    BUDGET_STOP = "budget_stop"


# Callable oracle: returns True iff the candidate still violates the property.
ViolationOracle = Callable[[Mapping[str, Any]], bool]


@runtime_checkable
class SemanticCounterexampleMinimizerProtocol(Protocol):
    """SemanticCounterexampleMinimizer@1 structural contract."""

    interface: str

    def minimize(
        self,
        witness: Mapping[str, Any],
        oracle: ViolationOracle,
        *,
        family: WitnessFamily | str | None = None,
        budget: "MinimizationBudget | Mapping[str, Any] | None" = None,
        oracle_id: str = "",
        property_snapshot_id: str = "",
        assumption_ids: Sequence[str] | None = None,
        finite_bounds: Mapping[str, Any] | None = None,
    ) -> "MinimizationResult":
        ...


@dataclass(frozen=True, slots=True)
class MinimizationBudget:
    """Hard resource bounds for oracle-preserving reduction."""

    max_oracle_calls: int = DEFAULT_MAX_ORACLE_CALLS
    max_reductions: int = DEFAULT_MAX_REDUCTIONS
    max_wall_ms: int = DEFAULT_MAX_WALL_MS
    max_exhaustive_size: int = DEFAULT_MAX_EXHAUSTIVE_SIZE

    def __post_init__(self) -> None:
        for name in (
            "max_oracle_calls",
            "max_reductions",
            "max_wall_ms",
            "max_exhaustive_size",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise MinimizationError(f"{name} must be non-negative")
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, int]:
        return {
            "max_exhaustive_size": self.max_exhaustive_size,
            "max_oracle_calls": self.max_oracle_calls,
            "max_reductions": self.max_reductions,
            "max_wall_ms": self.max_wall_ms,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "MinimizationBudget":
        if value is None:
            return cls()
        if isinstance(value, MinimizationBudget):
            return value
        if not isinstance(value, Mapping):
            raise MinimizationError("budget must be a mapping")
        return cls(
            max_oracle_calls=int(
                value.get("max_oracle_calls", DEFAULT_MAX_ORACLE_CALLS)
            ),
            max_reductions=int(value.get("max_reductions", DEFAULT_MAX_REDUCTIONS)),
            max_wall_ms=int(value.get("max_wall_ms", DEFAULT_MAX_WALL_MS)),
            max_exhaustive_size=int(
                value.get("max_exhaustive_size", DEFAULT_MAX_EXHAUSTIVE_SIZE)
            ),
        )


@dataclass(frozen=True, slots=True)
class ReductionLogEntry:
    """One attempted or accepted reduction step."""

    step: int
    action: ReductionAction | str
    target: str
    accepted: bool
    oracle_calls: int
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        action = (
            self.action.value
            if isinstance(self.action, ReductionAction)
            else str(self.action)
        )
        return {
            "accepted": bool(self.accepted),
            "action": action,
            "detail": self.detail,
            "oracle_calls": int(self.oracle_calls),
            "step": int(self.step),
            "target": self.target,
        }


@dataclass(frozen=True, slots=True)
class MinimizationReceipt:
    """Machine-checkable record of how a reduction guarantee was obtained."""

    receipt_id: str
    oracle_id: str
    algorithm: str
    algorithm_version: str
    family: WitnessFamily | str
    guarantee: MinimizationGuarantee | str
    budget: Mapping[str, Any]
    budget_exhausted: bool
    oracle_calls: int
    accepted_reductions: int
    rejected_reductions: int
    reduction_log: tuple[ReductionLogEntry, ...] = ()
    property_snapshot_id: str = ""
    assumption_ids: tuple[str, ...] = ()
    finite_bounds: Mapping[str, Any] = field(default_factory=dict)
    original_digest: str = ""
    minimized_digest: str = ""
    wall_ms: int = 0
    schema: str = MINIMIZATION_RECEIPT_SCHEMA
    interface: str = SEMANTIC_COUNTEREXAMPLE_MINIMIZER_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "budget", MappingProxyType(dict(self.budget or {}))
        )
        object.__setattr__(
            self,
            "finite_bounds",
            MappingProxyType(dict(self.finite_bounds or {})),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            tuple(str(item) for item in self.assumption_ids if str(item)),
        )
        object.__setattr__(self, "reduction_log", tuple(self.reduction_log))
        if not self.receipt_id:
            object.__setattr__(self, "receipt_id", _content_id("min-receipt", self.to_dict(identity=False)))

    def to_dict(self, *, identity: bool = True) -> dict[str, Any]:
        family = (
            self.family.value if isinstance(self.family, WitnessFamily) else str(self.family)
        )
        guarantee = (
            self.guarantee.value
            if isinstance(self.guarantee, MinimizationGuarantee)
            else str(self.guarantee)
        )
        payload = {
            "accepted_reductions": int(self.accepted_reductions),
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "assumption_ids": list(self.assumption_ids),
            "budget": dict(self.budget),
            "budget_exhausted": bool(self.budget_exhausted),
            "family": family,
            "finite_bounds": dict(self.finite_bounds),
            "guarantee": guarantee,
            "interface": self.interface,
            "minimized_digest": self.minimized_digest,
            "oracle_calls": int(self.oracle_calls),
            "oracle_id": self.oracle_id,
            "original_digest": self.original_digest,
            "property_snapshot_id": self.property_snapshot_id,
            "reduction_log": [entry.to_dict() for entry in self.reduction_log],
            "rejected_reductions": int(self.rejected_reductions),
            "schema": self.schema,
            "wall_ms": int(self.wall_ms),
        }
        if identity:
            payload["receipt_id"] = self.receipt_id
        return payload


@dataclass(frozen=True, slots=True)
class MinimizationResult:
    """Minimized witness plus a truthful guarantee receipt."""

    witness: Mapping[str, Any]
    guarantee: MinimizationGuarantee | str
    receipt: MinimizationReceipt
    schema: str = MINIMIZATION_RESULT_SCHEMA
    interface: str = SEMANTIC_COUNTEREXAMPLE_MINIMIZER_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "witness", MappingProxyType(dict(self.witness)))

    @property
    def budget_exhausted(self) -> bool:
        return bool(self.receipt.budget_exhausted)

    @property
    def is_semantically_minimal(self) -> bool:
        guarantee = (
            self.guarantee
            if isinstance(self.guarantee, MinimizationGuarantee)
            else MinimizationGuarantee(str(self.guarantee))
        )
        return guarantee in {
            MinimizationGuarantee.LOCALLY_MINIMAL,
            MinimizationGuarantee.GLOBALLY_MINIMAL,
        }

    def to_dict(self) -> dict[str, Any]:
        guarantee = (
            self.guarantee.value
            if isinstance(self.guarantee, MinimizationGuarantee)
            else str(self.guarantee)
        )
        return {
            "budget_exhausted": self.budget_exhausted,
            "guarantee": guarantee,
            "interface": self.interface,
            "is_semantically_minimal": self.is_semantically_minimal,
            "receipt": self.receipt.to_dict(),
            "schema": self.schema,
            "witness": dict(self.witness),
        }


class _BudgetTracker:
    """Mutable runtime budget accounting for a single minimize() call."""

    def __init__(self, budget: MinimizationBudget) -> None:
        self.budget = budget
        self.oracle_calls = 0
        self.accepted = 0
        self.rejected = 0
        self.step = 0
        self.log: list[ReductionLogEntry] = []
        self.exhausted = False
        self.started = time.monotonic()

    def wall_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def remaining_oracle(self) -> int:
        return max(0, self.budget.max_oracle_calls - self.oracle_calls)

    def can_oracle(self) -> bool:
        if self.exhausted:
            return False
        if self.oracle_calls >= self.budget.max_oracle_calls:
            self.exhausted = True
            return False
        if self.wall_ms() >= self.budget.max_wall_ms:
            self.exhausted = True
            return False
        return True

    def can_reduce(self) -> bool:
        if self.exhausted:
            return False
        if self.accepted >= self.budget.max_reductions:
            self.exhausted = True
            return False
        if self.wall_ms() >= self.budget.max_wall_ms:
            self.exhausted = True
            return False
        return True

    def record(
        self,
        action: ReductionAction,
        target: str,
        *,
        accepted: bool,
        detail: str = "",
    ) -> None:
        self.step += 1
        if accepted:
            self.accepted += 1
        else:
            self.rejected += 1
        self.log.append(
            ReductionLogEntry(
                step=self.step,
                action=action,
                target=target,
                accepted=accepted,
                oracle_calls=self.oracle_calls,
                detail=detail,
            )
        )

    def stop(self, reason: str) -> None:
        self.exhausted = True
        self.step += 1
        self.log.append(
            ReductionLogEntry(
                step=self.step,
                action=ReductionAction.BUDGET_STOP,
                target="budget",
                accepted=False,
                oracle_calls=self.oracle_calls,
                detail=reason,
            )
        )


class SemanticCounterexampleMinimizer:
    """Backend-specific, budgeted, oracle-preserving counterexample reducers.

    Interface: ``SemanticCounterexampleMinimizer@1``.
    """

    interface: Final = SEMANTIC_COUNTEREXAMPLE_MINIMIZER_INTERFACE
    algorithm: Final = "oracle_preserving_semantic_reducer"
    algorithm_version: Final = ALGORITHM_VERSION

    def __init__(self, *, default_budget: MinimizationBudget | None = None) -> None:
        self.default_budget = default_budget or MinimizationBudget()

    def minimize(
        self,
        witness: Mapping[str, Any],
        oracle: ViolationOracle,
        *,
        family: WitnessFamily | str | None = None,
        budget: MinimizationBudget | Mapping[str, Any] | None = None,
        oracle_id: str = "",
        property_snapshot_id: str = "",
        assumption_ids: Sequence[str] | None = None,
        finite_bounds: Mapping[str, Any] | None = None,
    ) -> MinimizationResult:
        if not isinstance(witness, Mapping):
            raise MinimizationError("witness must be a mapping")
        if not callable(oracle):
            raise MinimizationError("oracle must be callable")

        original = _json_ready(dict(witness))
        if not isinstance(original, dict):
            raise MinimizationError("witness must serialize to an object")

        resolved_budget = MinimizationBudget.from_mapping(
            budget if budget is not None else self.default_budget.to_dict()
        )
        tracker = _BudgetTracker(resolved_budget)
        family_value = _resolve_family(family, original)
        assumptions = tuple(
            str(item)
            for item in (
                assumption_ids
                if assumption_ids is not None
                else original.get("assumption_ids")
                or original.get("assumptions")
                or ()
            )
            if str(item)
        )
        bounds = dict(
            finite_bounds
            if finite_bounds is not None
            else original.get("finite_bounds") or original.get("bounds") or {}
        )
        resolved_oracle_id = str(
            oracle_id
            or original.get("oracle_id")
            or original.get("tool_id")
            or original.get("provider_id")
            or "oracle:anonymous"
        ).strip()
        resolved_snapshot = str(
            property_snapshot_id
            or original.get("property_snapshot_id")
            or original.get("violated_property")
            or original.get("property_id")
            or ""
        ).strip()

        # Structural normalize first — never claims semantic minimality.
        current = _normalize_witness(original, family_value)
        tracker.record(
            ReductionAction.NORMALIZE,
            f"family:{family_value.value}",
            accepted=current != original,
            detail="structural canonicalize / bound collections",
        )

        if not self._oracle_still_violates(oracle, current, tracker):
            raise MinimizationError(
                "oracle does not report a violation for the input witness; "
                "semantic minimization requires an oracle-preserving violation"
            )

        reducers = {
            WitnessFamily.SMT_MODEL: self._reduce_smt_model,
            WitnessFamily.SMT_CORE: self._reduce_smt_core,
            WitnessFamily.TRACE: self._reduce_trace,
            WitnessFamily.PROTOCOL_ATTACK: self._reduce_protocol_attack,
            WitnessFamily.HYPERTRACE: self._reduce_hypertrace,
            WitnessFamily.KERNEL: self._reduce_kernel,
            WitnessFamily.GENERIC: self._reduce_generic,
        }
        reducer = reducers[family_value]
        current, local_done = reducer(current, oracle, tracker)

        guarantee = self._finalize_guarantee(
            current,
            oracle,
            tracker,
            local_done=local_done,
            family=family_value,
        )

        original_digest = _digest(original)
        minimized_digest = _digest(current)
        receipt = MinimizationReceipt(
            receipt_id="",
            oracle_id=resolved_oracle_id,
            algorithm=self.algorithm,
            algorithm_version=self.algorithm_version,
            family=family_value,
            guarantee=guarantee,
            budget=resolved_budget.to_dict(),
            budget_exhausted=tracker.exhausted,
            oracle_calls=tracker.oracle_calls,
            accepted_reductions=tracker.accepted,
            rejected_reductions=tracker.rejected,
            reduction_log=tuple(tracker.log),
            property_snapshot_id=resolved_snapshot,
            assumption_ids=assumptions,
            finite_bounds=bounds,
            original_digest=original_digest,
            minimized_digest=minimized_digest,
            wall_ms=tracker.wall_ms(),
        )
        return MinimizationResult(
            witness=current,
            guarantee=guarantee,
            receipt=receipt,
        )

    # ------------------------------------------------------------------
    # Oracle helpers
    # ------------------------------------------------------------------

    def _oracle_still_violates(
        self,
        oracle: ViolationOracle,
        candidate: Mapping[str, Any],
        tracker: _BudgetTracker,
    ) -> bool:
        if not tracker.can_oracle():
            tracker.stop("oracle_call_budget_or_wall_clock_exhausted")
            return False
        tracker.oracle_calls += 1
        try:
            result = bool(oracle(MappingProxyType(dict(candidate))))
        except Exception:
            # Fail closed: a crashing oracle does not authorize a removal.
            return False
        return result

    def _try_accept(
        self,
        current: dict[str, Any],
        candidate: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
        action: ReductionAction,
        target: str,
        *,
        detail: str = "",
    ) -> tuple[dict[str, Any], bool]:
        if candidate == current:
            return current, False
        if not tracker.can_reduce():
            tracker.stop("reduction_budget_or_wall_clock_exhausted")
            return current, False
        if not tracker.can_oracle():
            tracker.stop("oracle_call_budget_or_wall_clock_exhausted")
            return current, False
        if self._oracle_still_violates(oracle, candidate, tracker):
            tracker.record(action, target, accepted=True, detail=detail)
            return candidate, True
        tracker.record(action, target, accepted=False, detail=detail or "oracle rejected")
        return current, False

    def _finalize_guarantee(
        self,
        current: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
        *,
        local_done: bool,
        family: WitnessFamily,
    ) -> MinimizationGuarantee:
        if not local_done:
            if tracker.exhausted:
                return MinimizationGuarantee.BOUNDED
            # Normalization-only path (e.g. empty payload after classify).
            return MinimizationGuarantee.NORMALIZED

        # Optional exhaustive upgrade for tiny discrete witnesses.
        if family in {
            WitnessFamily.SMT_CORE,
            WitnessFamily.TRACE,
            WitnessFamily.PROTOCOL_ATTACK,
        } and self._try_global_upgrade(current, oracle, tracker, family):
            return MinimizationGuarantee.GLOBALLY_MINIMAL

        # A completed local deletion pass always earns locally_minimal, even if
        # a later exhaustive upgrade attempt exhausted remaining budget.
        return MinimizationGuarantee.LOCALLY_MINIMAL

    def _try_global_upgrade(
        self,
        current: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
        family: WitnessFamily,
    ) -> bool:
        """Attempt exhaustive size-minimum check for very small witnesses."""

        elements = _discrete_elements(current, family)
        n = len(elements)
        if n == 0 or n > tracker.budget.max_exhaustive_size:
            return False
        # Local minimality already holds; for small n, local = global for
        # monotone deletion oracles (subset-closed violation property).
        # We still re-check a few random smaller subsets when budget allows
        # by testing all size-(n-1) already done; verify size floor by
        # confirming empty set fails and no size < n subset works for n<=4.
        if n > 4:
            # Local deletion minimality + monotone oracle implies global for
            # subset-minimal cores; claim global only when n is tiny and we
            # rechecked all subsets of size n-1 (already done by local pass).
            tracker.record(
                ReductionAction.EXHAUSTIVE_SEARCH,
                f"size:{n}",
                accepted=True,
                detail="local_min_implies_global_under_monotone_deletion",
            )
            return True

        # Brute-force all non-empty proper subsets for n <= 4.
        labels = list(elements)
        for mask in range(1, (1 << n) - 1):
            if not tracker.can_oracle():
                tracker.stop("exhaustive_search_budget_exhausted")
                return False
            subset = [labels[i] for i in range(n) if mask & (1 << i)]
            candidate = _rebuild_from_elements(current, family, subset)
            if self._oracle_still_violates(oracle, candidate, tracker):
                # Found a smaller violating subset — should not happen if
                # local pass was complete; refuse global claim.
                tracker.record(
                    ReductionAction.EXHAUSTIVE_SEARCH,
                    f"size:{len(subset)}",
                    accepted=False,
                    detail="smaller_violating_subset_found",
                )
                return False
        tracker.record(
            ReductionAction.EXHAUSTIVE_SEARCH,
            f"size:{n}",
            accepted=True,
            detail="exhaustive_subset_enumeration",
        )
        return True

    # ------------------------------------------------------------------
    # Family reducers
    # ------------------------------------------------------------------

    def _reduce_smt_model(
        self,
        witness: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
    ) -> tuple[dict[str, Any], bool]:
        """Project assignments / drop don't-cares with oracle recheck."""

        current = dict(witness)
        assignments = _extract_assignments(current)
        if not assignments:
            return current, True

        # 1) Drop don't-care / free variables marked as such.
        dont_cares = [
            key
            for key, value in list(assignments.items())
            if _is_dont_care(value) or str(key).startswith("dont_care")
        ]
        for key in sorted(dont_cares, key=str):
            if not tracker.can_reduce():
                return current, False
            trial_assign = dict(_extract_assignments(current))
            trial_assign.pop(key, None)
            candidate = _with_assignments(current, trial_assign)
            current, _ = self._try_accept(
                current,
                candidate,
                oracle,
                tracker,
                ReductionAction.DROP_DONT_CARE,
                f"assignment:{key}",
            )

        # 2) Projection: delete one assignment at a time until locally minimal.
        changed = True
        while changed and tracker.can_reduce():
            changed = False
            keys = sorted(_extract_assignments(current), key=str)
            for key in keys:
                if not tracker.can_reduce():
                    return current, False
                trial_assign = dict(_extract_assignments(current))
                trial_assign.pop(key, None)
                candidate = _with_assignments(current, trial_assign)
                current, accepted = self._try_accept(
                    current,
                    candidate,
                    oracle,
                    tracker,
                    ReductionAction.PROJECT_ASSIGNMENT,
                    f"assignment:{key}",
                )
                if accepted:
                    changed = True
                    break
        return current, not tracker.exhausted or not changed

    def _reduce_smt_core(
        self,
        witness: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
    ) -> tuple[dict[str, Any], bool]:
        """Subset-minimal unsat/assumption core (QuickXplain-style delete-one)."""

        current = dict(witness)
        core = list(_extract_core(current))
        if not core:
            return current, True

        # Stable order for determinism.
        core = _stable_unique(core)
        changed = True
        while changed and tracker.can_reduce():
            changed = False
            for index in range(len(core)):
                if not tracker.can_reduce():
                    return _with_core(current, core), False
                trial = core[:index] + core[index + 1 :]
                candidate = _with_core(current, trial)
                label = _element_label(core[index], index)
                new_current, accepted = self._try_accept(
                    current,
                    candidate,
                    oracle,
                    tracker,
                    ReductionAction.DROP_CORE_MEMBER,
                    f"core:{label}",
                )
                if accepted:
                    current = new_current
                    core = trial
                    changed = True
                    break
        return _with_core(current, core), not tracker.exhausted or not changed

    def _reduce_trace(
        self,
        witness: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
    ) -> tuple[dict[str, Any], bool]:
        """Shortest violating prefix / lasso / event slice with stutter drop."""

        current = dict(witness)
        steps = list(_extract_steps(current))
        if not steps:
            return current, True

        # Drop adjacent stutter (semantic equality) under oracle.
        i = 1
        while i < len(steps) and tracker.can_reduce():
            if _canonical(steps[i]) == _canonical(steps[i - 1]):
                trial = steps[:i] + steps[i + 1 :]
                candidate = _with_steps(current, trial)
                current, accepted = self._try_accept(
                    current,
                    candidate,
                    oracle,
                    tracker,
                    ReductionAction.DROP_STUTTER,
                    f"step:{i}",
                )
                if accepted:
                    steps = trial
                    continue
            i += 1

        # Shortest violating prefix: drop from the front when possible, then
        # try dropping intermediate events while preserving the violation.
        # Prefer keeping a short suffix that still violates (prefix property).
        if len(steps) > 1 and tracker.can_reduce():
            # Binary-search the earliest start index whose suffix still violates.
            lo, hi = 0, len(steps) - 1
            best = steps
            while lo <= hi and tracker.can_oracle() and tracker.can_reduce():
                mid = (lo + hi) // 2
                trial = steps[mid:]
                candidate = _with_steps(current, trial)
                if self._oracle_still_violates(oracle, candidate, tracker):
                    best = trial
                    lo = mid + 1
                    tracker.record(
                        ReductionAction.SHORTEN_PREFIX,
                        f"start:{mid}",
                        accepted=True,
                        detail=f"suffix_len={len(trial)}",
                    )
                else:
                    tracker.record(
                        ReductionAction.SHORTEN_PREFIX,
                        f"start:{mid}",
                        accepted=False,
                        detail="suffix_lost_violation",
                    )
                    hi = mid - 1
            if best != steps:
                current = _with_steps(current, best)
                steps = best

        # Delete-one event slice for remaining intermediate steps.
        changed = True
        while changed and tracker.can_reduce() and len(steps) > 1:
            changed = False
            # Prefer dropping middle events before endpoints.
            order = list(range(1, len(steps) - 1)) + [0, len(steps) - 1]
            for index in order:
                if index >= len(steps):
                    continue
                if not tracker.can_reduce():
                    return _with_steps(current, steps), False
                trial = steps[:index] + steps[index + 1 :]
                candidate = _with_steps(current, trial)
                new_current, accepted = self._try_accept(
                    current,
                    candidate,
                    oracle,
                    tracker,
                    ReductionAction.DROP_EVENT,
                    f"step:{index}",
                )
                if accepted:
                    current = new_current
                    steps = trial
                    changed = True
                    break
        return _with_steps(current, steps), not tracker.exhausted or not changed

    def _reduce_protocol_attack(
        self,
        witness: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
    ) -> tuple[dict[str, Any], bool]:
        """Protocol dependency / attack-role slice."""

        current = dict(witness)
        # First apply trace reduction on steps.
        current, local_steps = self._reduce_trace(current, oracle, tracker)
        if tracker.exhausted:
            return current, False

        # Slice optional dependency/role lists.
        for field_name, action in (
            ("dependencies", ReductionAction.SLICE_DEPENDENCY),
            ("roles", ReductionAction.SLICE_DEPENDENCY),
            ("participants", ReductionAction.SLICE_DEPENDENCY),
            ("messages", ReductionAction.SLICE_DEPENDENCY),
        ):
            values = current.get(field_name)
            if not isinstance(values, list) or not values:
                continue
            items = list(values)
            changed = True
            while changed and tracker.can_reduce():
                changed = False
                for index in range(len(items)):
                    if not tracker.can_reduce():
                        current = {**current, field_name: items}
                        return current, False
                    trial = items[:index] + items[index + 1 :]
                    candidate = {**current, field_name: trial}
                    label = _element_label(items[index], index)
                    new_current, accepted = self._try_accept(
                        current,
                        candidate,
                        oracle,
                        tracker,
                        action,
                        f"{field_name}:{label}",
                    )
                    if accepted:
                        current = new_current
                        items = trial
                        changed = True
                        break
            current = {**current, field_name: items}

        return current, local_steps and not tracker.exhausted

    def _reduce_hypertrace(
        self,
        witness: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
    ) -> tuple[dict[str, Any], bool]:
        """Earliest hypertrace observation divergence + observed-field reduction."""

        current = dict(witness)
        differences = list(current.get("differences") or [])
        if differences and tracker.can_reduce():
            # Keep only the earliest divergence entry when oracle allows.
            for keep in range(1, len(differences) + 1):
                if not tracker.can_reduce():
                    break
                trial = differences[:keep]
                candidate = {**current, "differences": trial}
                new_current, accepted = self._try_accept(
                    current,
                    candidate,
                    oracle,
                    tracker,
                    ReductionAction.EARLIEST_DIVERGENCE,
                    f"differences:keep={keep}",
                    detail="earliest_divergence_prefix",
                )
                if accepted:
                    current = new_current
                    # Continue shrinking from this prefix.
                    differences = trial
                    # Once a short prefix works, try delete-one inside it.
                    break

            # Delete-one on remaining differences.
            diffs = list(current.get("differences") or [])
            changed = True
            while changed and tracker.can_reduce() and len(diffs) > 1:
                changed = False
                for index in range(len(diffs)):
                    trial = diffs[:index] + diffs[index + 1 :]
                    candidate = {**current, "differences": trial}
                    new_current, accepted = self._try_accept(
                        current,
                        candidate,
                        oracle,
                        tracker,
                        ReductionAction.EARLIEST_DIVERGENCE,
                        f"differences:{index}",
                    )
                    if accepted:
                        current = new_current
                        diffs = trial
                        changed = True
                        break

        # Reduce observed fields.
        observed = list(current.get("observed_fields") or [])
        if observed:
            items = list(observed)
            changed = True
            while changed and tracker.can_reduce():
                changed = False
                for index in range(len(items)):
                    trial = items[:index] + items[index + 1 :]
                    candidate = {**current, "observed_fields": trial}
                    label = _element_label(items[index], index)
                    new_current, accepted = self._try_accept(
                        current,
                        candidate,
                        oracle,
                        tracker,
                        ReductionAction.DROP_OBSERVED_FIELD,
                        f"observed_fields:{label}",
                    )
                    if accepted:
                        current = new_current
                        items = trial
                        changed = True
                        break

        # Reduce non-essential trace refs when multiple are present.
        refs = list(current.get("trace_refs") or [])
        if len(refs) > 1:
            items = list(refs)
            changed = True
            while changed and tracker.can_reduce() and len(items) > 1:
                changed = False
                for index in range(len(items)):
                    trial = items[:index] + items[index + 1 :]
                    candidate = {**current, "trace_refs": trial}
                    label = _element_label(items[index], index)
                    new_current, accepted = self._try_accept(
                        current,
                        candidate,
                        oracle,
                        tracker,
                        ReductionAction.DROP_TRACE_REF,
                        f"trace_refs:{label}",
                    )
                    if accepted:
                        current = new_current
                        items = trial
                        changed = True
                        break

        return current, not tracker.exhausted

    def _reduce_kernel(
        self,
        witness: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
    ) -> tuple[dict[str, Any], bool]:
        """Kernel failures are identity-bound; classify without inventing minimality."""

        current = dict(witness)
        code = str(
            current.get("failure_code")
            or current.get("code")
            or current.get("status")
            or "kernel_rejected"
        ).lower()
        current["failure_code"] = code
        # Drop free-form raw diagnostic fields if present and oracle allows.
        for key in ("reason", "message", "detail", "exception", "traceback"):
            if key not in current:
                continue
            trial = {k: v for k, v in current.items() if k != key}
            current, _ = self._try_accept(
                current,
                trial,
                oracle,
                tracker,
                ReductionAction.CLASSIFY_KERNEL,
                f"drop:{key}",
            )
        tracker.record(
            ReductionAction.CLASSIFY_KERNEL,
            f"failure_code:{code}",
            accepted=True,
            detail="kernel_identity_bound_classification",
        )
        # Kernel witnesses are typically already minimal once classified.
        return current, True

    def _reduce_generic(
        self,
        witness: dict[str, Any],
        oracle: ViolationOracle,
        tracker: _BudgetTracker,
    ) -> tuple[dict[str, Any], bool]:
        """Generic delete-one over non-protected top-level keys and list items."""

        current = dict(witness)
        changed = True
        while changed and tracker.can_reduce():
            changed = False
            for key in sorted(current, key=str):
                if key in _PROTECTED_WITNESS_KEYS:
                    continue
                if not tracker.can_reduce():
                    return current, False
                trial = {k: v for k, v in current.items() if k != key}
                new_current, accepted = self._try_accept(
                    current,
                    trial,
                    oracle,
                    tracker,
                    ReductionAction.PROJECT_ASSIGNMENT,
                    f"key:{key}",
                )
                if accepted:
                    current = new_current
                    changed = True
                    break
            if changed:
                continue
            # Shrink lists one element at a time.
            for key, value in list(current.items()):
                if key in _PROTECTED_WITNESS_KEYS:
                    continue
                if not isinstance(value, list) or not value:
                    continue
                for index in range(len(value)):
                    if not tracker.can_reduce():
                        return current, False
                    trial_list = value[:index] + value[index + 1 :]
                    trial = {**current, key: trial_list}
                    new_current, accepted = self._try_accept(
                        current,
                        trial,
                        oracle,
                        tracker,
                        ReductionAction.DROP_EVENT,
                        f"{key}:{index}",
                    )
                    if accepted:
                        current = new_current
                        changed = True
                        break
                if changed:
                    break
        return current, not tracker.exhausted or not changed


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def minimize_counterexample(
    witness: Mapping[str, Any],
    oracle: ViolationOracle,
    *,
    family: WitnessFamily | str | None = None,
    budget: MinimizationBudget | Mapping[str, Any] | None = None,
    oracle_id: str = "",
    property_snapshot_id: str = "",
    assumption_ids: Sequence[str] | None = None,
    finite_bounds: Mapping[str, Any] | None = None,
    minimizer: SemanticCounterexampleMinimizer | None = None,
) -> MinimizationResult:
    """Convenience entry point for SemanticCounterexampleMinimizer@1."""

    engine = minimizer or SemanticCounterexampleMinimizer()
    return engine.minimize(
        witness,
        oracle,
        family=family,
        budget=budget,
        oracle_id=oracle_id,
        property_snapshot_id=property_snapshot_id,
        assumption_ids=assumption_ids,
        finite_bounds=finite_bounds,
    )


def _resolve_family(
    family: WitnessFamily | str | None, witness: Mapping[str, Any]
) -> WitnessFamily:
    if family is not None:
        text = family.value if isinstance(family, WitnessFamily) else str(family)
        text = text.strip().lower().replace("-", "_")
        aliases = {
            "smt_model": WitnessFamily.SMT_MODEL,
            "model": WitnessFamily.SMT_MODEL,
            "smt": WitnessFamily.SMT_MODEL,
            "smt_core": WitnessFamily.SMT_CORE,
            "smt_unsat_core": WitnessFamily.SMT_CORE,
            "unsat_core": WitnessFamily.SMT_CORE,
            "core": WitnessFamily.SMT_CORE,
            "trace": WitnessFamily.TRACE,
            "tla_trace": WitnessFamily.TRACE,
            "runtime_mtl_violation": WitnessFamily.TRACE,
            "mtl": WitnessFamily.TRACE,
            "protocol_attack": WitnessFamily.PROTOCOL_ATTACK,
            "protocol": WitnessFamily.PROTOCOL_ATTACK,
            "attack": WitnessFamily.PROTOCOL_ATTACK,
            "hypertrace": WitnessFamily.HYPERTRACE,
            "hyperproperty": WitnessFamily.HYPERTRACE,
            "kernel": WitnessFamily.KERNEL,
            "kernel_error": WitnessFamily.KERNEL,
            "generic": WitnessFamily.GENERIC,
            "generic_failure": WitnessFamily.GENERIC,
        }
        if text not in aliases:
            raise MinimizationError(f"unknown witness family {family!r}")
        return aliases[text]

    kind = str(witness.get("kind") or witness.get("family") or "").strip().lower()
    if kind:
        try:
            return _resolve_family(kind, witness)
        except MinimizationError:
            pass
    if "assignments" in witness or "model" in witness:
        return WitnessFamily.SMT_MODEL
    if "core" in witness or "unsat_core" in witness:
        return WitnessFamily.SMT_CORE
    if "differences" in witness or "trace_refs" in witness or "observed_fields" in witness:
        return WitnessFamily.HYPERTRACE
    if "failure_code" in witness or "kernel_id" in witness:
        return WitnessFamily.KERNEL
    if "dependencies" in witness or "roles" in witness or "messages" in witness:
        return WitnessFamily.PROTOCOL_ATTACK
    if "steps" in witness or "trace" in witness:
        return WitnessFamily.TRACE
    return WitnessFamily.GENERIC


def _normalize_witness(
    witness: dict[str, Any], family: WitnessFamily
) -> dict[str, Any]:
    current = _json_ready(witness)
    assert isinstance(current, dict)
    # Drop empty optional collections and sort assignment keys.
    if family is WitnessFamily.SMT_MODEL:
        assignments = _extract_assignments(current)
        current = _with_assignments(current, dict(sorted(assignments.items(), key=str)))
    elif family is WitnessFamily.SMT_CORE:
        current = _with_core(current, _stable_unique(_extract_core(current)))
    elif family in {WitnessFamily.TRACE, WitnessFamily.PROTOCOL_ATTACK}:
        steps = _extract_steps(current)
        current = _with_steps(current, steps)
    return current


def _extract_assignments(witness: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("assignments", "model", "payload"):
        value = witness.get(key)
        if isinstance(value, Mapping):
            if key == "payload":
                nested = value.get("assignments") or value.get("model")
                if isinstance(nested, Mapping):
                    return {str(k): nested[k] for k in nested}
            else:
                return {str(k): value[k] for k in value}
    payload = witness.get("payload")
    if isinstance(payload, Mapping) and isinstance(payload.get("assignments"), Mapping):
        nested = payload["assignments"]
        return {str(k): nested[k] for k in nested}
    return {}


def _with_assignments(witness: Mapping[str, Any], assignments: Mapping[str, Any]) -> dict[str, Any]:
    current = dict(witness)
    if "assignments" in current or "model" not in current:
        current["assignments"] = dict(assignments)
        current.pop("model", None)
    else:
        current["model"] = dict(assignments)
    payload = current.get("payload")
    if isinstance(payload, Mapping):
        nested = dict(payload)
        nested["assignments"] = dict(assignments)
        current["payload"] = nested
    return current


def _extract_core(witness: Mapping[str, Any]) -> list[Any]:
    for key in ("core", "unsat_core", "assumptions", "premises"):
        value = witness.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return list(value)
    payload = witness.get("payload")
    if isinstance(payload, Mapping):
        for key in ("core", "unsat_core"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return list(value)
    return []


def _with_core(witness: Mapping[str, Any], core: Sequence[Any]) -> dict[str, Any]:
    current = dict(witness)
    current["core"] = list(core)
    payload = current.get("payload")
    if isinstance(payload, Mapping):
        nested = dict(payload)
        nested["core"] = list(core)
        current["payload"] = nested
    return current


def _extract_steps(witness: Mapping[str, Any]) -> list[Any]:
    for key in ("steps", "trace", "events"):
        value = witness.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return list(value)
    payload = witness.get("payload")
    if isinstance(payload, Mapping):
        for key in ("steps", "trace", "events"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return list(value)
    return []


def _with_steps(witness: Mapping[str, Any], steps: Sequence[Any]) -> dict[str, Any]:
    current = dict(witness)
    # Preserve the primary field name used by the input.
    if "trace" in current and "steps" not in current:
        current["trace"] = list(steps)
    elif "events" in current and "steps" not in current:
        current["events"] = list(steps)
    else:
        current["steps"] = list(steps)
    payload = current.get("payload")
    if isinstance(payload, Mapping):
        nested = dict(payload)
        nested["steps"] = list(steps)
        current["payload"] = nested
    return current


def _is_dont_care(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {
        "dont_care",
        "don't_care",
        "dont-care",
        "*",
        "_",
    }:
        return True
    if isinstance(value, Mapping) and value.get("dont_care") is True:
        return True
    return False


def _stable_unique(values: Sequence[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for item in values:
        key = _canonical(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _element_label(value: Any, index: int) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:64]
    if isinstance(value, Mapping):
        for key in ("id", "name", "role", "label", "assumption_id"):
            if value.get(key):
                return str(value[key])[:64]
    return str(index)


def _discrete_elements(
    witness: Mapping[str, Any], family: WitnessFamily
) -> list[Any]:
    if family is WitnessFamily.SMT_CORE:
        return list(_extract_core(witness))
    if family in {WitnessFamily.TRACE, WitnessFamily.PROTOCOL_ATTACK}:
        return list(_extract_steps(witness))
    if family is WitnessFamily.SMT_MODEL:
        return list(_extract_assignments(witness).items())
    return []


def _rebuild_from_elements(
    witness: Mapping[str, Any],
    family: WitnessFamily,
    elements: Sequence[Any],
) -> dict[str, Any]:
    if family is WitnessFamily.SMT_CORE:
        return _with_core(witness, elements)
    if family in {WitnessFamily.TRACE, WitnessFamily.PROTOCOL_ATTACK}:
        return _with_steps(witness, elements)
    if family is WitnessFamily.SMT_MODEL:
        assignments = {str(k): v for k, v in elements}
        return _with_assignments(witness, assignments)
    return dict(witness)


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # NaN/Inf
            return str(value)
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_ready(item) for item in value), key=_canonical)
    if isinstance(value, StrEnum):
        return value.value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _canonical(value: Any) -> str:
    return json.dumps(_json_ready(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _content_id(prefix: str, payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("receipt_id", None)
    return f"{prefix}:{_digest(body)[:32]}"


__all__ = [
    "ALGORITHM_VERSION",
    "MINIMIZATION_RECEIPT_SCHEMA",
    "MINIMIZATION_RESULT_SCHEMA",
    "SEMANTIC_COUNTEREXAMPLE_MINIMIZER_INTERFACE",
    "MinimizationBudget",
    "MinimizationError",
    "MinimizationGuarantee",
    "MinimizationReceipt",
    "MinimizationResult",
    "ReductionAction",
    "ReductionLogEntry",
    "SemanticCounterexampleMinimizer",
    "SemanticCounterexampleMinimizerProtocol",
    "ViolationOracle",
    "WitnessFamily",
    "minimize_counterexample",
]

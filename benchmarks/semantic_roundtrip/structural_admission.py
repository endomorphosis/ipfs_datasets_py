"""Hammer/cvc5/Lean structural admission gates for hybrid repair.

Interface: ``StructuralAdmission@1``

Optional repairs on the hybrid path may be admitted or rejected by bounded
Hammer/cvc5 and/or Lean structural checks **before** the candidate L1 is
allowed to affect T1/L2 scoring.  These tools are admit/reject gates only:

* a **reject** leaves the prior L1 unchanged and records ``validator_reject``;
* a **timeout** or validator error is fail-closed (same L1 retention);
* a **proof pass** never becomes end-to-end semantic loss by itself.

Metrics expose ``reject_rate`` and ``accepted_repair_delta`` separately from
protocol end-to-end loss.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from benchmarks.semantic_roundtrip.constructors.autoencoder_guided import (
    CanonicalFieldChange,
    canonical_field_changes,
)
from benchmarks.semantic_roundtrip.contracts import (
    RULE_FIELDS,
    CanonicalRuleIR,
    ContractError,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    DECLARED_STRUCTURAL_CONSTRAINTS,
    STRUCTURAL_VALIDATION_INTERFACE,
    StructuralTool,
    StructuralValidationReceipt,
    StructuralValidationRequest,
    StructuralValidatorBinding,
    StructuralValidatorCallable,
)


STRUCTURAL_ADMISSION_INTERFACE: Final = "StructuralAdmission@1"
STRUCTURAL_ADMISSION_RECEIPT_INTERFACE: Final = "StructuralAdmissionReceipt@1"
STRUCTURAL_ADMISSION_METRICS_INTERFACE: Final = "StructuralAdmissionMetrics@1"
STRUCTURAL_ADMISSION_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-structural-admission.v1"
)

VALIDATOR_REJECT: Final = "validator_reject"
DEFAULT_ADMISSION_TIMEOUT_SECONDS: Final = 5.0
DEFAULT_HAMMER_VALIDATOR_ID: Final = "hammer_cvc5"
DEFAULT_LEAN_VALIDATOR_ID: Final = "lean"

# Closed set of gate dispositions for one admission attempt.
_ADMISSION_DISPOSITIONS: Final = frozenset(
    {
        "accepted",
        "validator_reject",
        "timeout",
        "error",
        "not_applicable",
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _detail(value: object, fallback: str) -> str:
    text = " ".join(str(value or fallback).split())
    return (text or fallback)[:1000]


def _finite_positive(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise StructuralAdmissionError(
            f"{field} must be a positive finite number"
        )
    return float(value)


class AdmissionDisposition(str, Enum):
    """Terminal disposition of one structural admission attempt."""

    ACCEPTED = "accepted"
    VALIDATOR_REJECT = "validator_reject"
    TIMEOUT = "timeout"
    ERROR = "error"
    NOT_APPLICABLE = "not_applicable"


class StructuralAdmissionError(ContractError):
    """Contract or configuration failure in the structural admission path."""


@dataclass(frozen=True, slots=True)
class StructuralAdmissionPolicy:
    """Preregistered timeout, tool set, and fail-closed behaviour."""

    timeout_seconds: float = DEFAULT_ADMISSION_TIMEOUT_SECONDS
    tools: tuple[StructuralTool, ...] = (
        StructuralTool.HAMMER_CVC5,
        StructuralTool.LEAN,
    )
    require_all_pass: bool = True
    fail_closed_on_timeout: bool = True
    fail_closed_on_error: bool = True
    structural_constraints: tuple[str, ...] = DECLARED_STRUCTURAL_CONSTRAINTS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timeout_seconds",
            _finite_positive(self.timeout_seconds, "timeout_seconds"),
        )
        if self.timeout_seconds > 60.0:
            raise StructuralAdmissionError(
                "timeout_seconds exceeds the admission bound of 60s"
            )
        try:
            tools = tuple(StructuralTool(item) for item in self.tools)
        except (TypeError, ValueError) as exc:
            raise StructuralAdmissionError(
                "tools must be StructuralTool values"
            ) from exc
        if not tools or len(set(tools)) != len(tools):
            raise StructuralAdmissionError(
                "tools must be a nonempty unique sequence of StructuralTool"
            )
        object.__setattr__(self, "tools", tools)
        for name in (
            "require_all_pass",
            "fail_closed_on_timeout",
            "fail_closed_on_error",
        ):
            if not isinstance(getattr(self, name), bool):
                raise StructuralAdmissionError(f"{name} must be boolean")
        constraints = tuple(self.structural_constraints)
        if (
            not constraints
            or len(set(constraints)) != len(constraints)
            or any(
                item not in DECLARED_STRUCTURAL_CONSTRAINTS
                for item in constraints
            )
        ):
            raise StructuralAdmissionError(
                "structural_constraints must be a unique nonempty subset "
                "of the declared structural constraints"
            )
        object.__setattr__(self, "structural_constraints", constraints)

    @property
    def digest(self) -> str:
        return _sha(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "fail_closed_on_error": self.fail_closed_on_error,
            "fail_closed_on_timeout": self.fail_closed_on_timeout,
            "interface": STRUCTURAL_ADMISSION_INTERFACE,
            "require_all_pass": self.require_all_pass,
            "structural_constraints": list(self.structural_constraints),
            "timeout_seconds": self.timeout_seconds,
            "tools": [item.value for item in self.tools],
        }


@dataclass(frozen=True, slots=True)
class AdmissionCheckReceipt:
    """One bounded tool invocation inside an admission attempt.

    ``semantic_authority`` is always false: a proof/solver pass cannot
    adjudicate source meaning or lower end-to-end loss by itself.
    """

    validator_id: str
    tool: StructuralTool
    passed: bool
    timed_out: bool
    elapsed_seconds: float
    detail: str | None = None
    constraints: tuple[str, ...] = ()
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.validator_id, str) or not self.validator_id.strip():
            raise StructuralAdmissionError("validator_id must be nonblank")
        if not isinstance(self.tool, StructuralTool):
            try:
                object.__setattr__(self, "tool", StructuralTool(self.tool))
            except (TypeError, ValueError) as exc:
                raise StructuralAdmissionError(
                    "admission check tool is invalid"
                ) from exc
        if not isinstance(self.passed, bool) or not isinstance(
            self.timed_out, bool
        ):
            raise StructuralAdmissionError(
                "passed and timed_out must be booleans"
            )
        if self.timed_out and self.passed:
            raise StructuralAdmissionError(
                "a timed-out check cannot pass"
            )
        elapsed = self.elapsed_seconds
        if (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed))
            or float(elapsed) < 0.0
        ):
            raise StructuralAdmissionError(
                "elapsed_seconds must be a nonnegative finite number"
            )
        object.__setattr__(self, "elapsed_seconds", float(elapsed))
        if self.semantic_authority is not False:
            raise StructuralAdmissionError(
                "Hammer/cvc5/Lean admission cannot claim semantic authority"
            )
        object.__setattr__(self, "constraints", tuple(self.constraints))
        if self.detail is not None and not str(self.detail).strip():
            raise StructuralAdmissionError(
                "admission check detail must be nonblank when present"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "constraints": list(self.constraints),
            "detail": self.detail,
            "elapsed_seconds": self.elapsed_seconds,
            "interface": STRUCTURAL_VALIDATION_INTERFACE,
            "passed": self.passed,
            "semantic_authority": False,
            "timed_out": self.timed_out,
            "tool": self.tool.value,
            "validator_id": self.validator_id,
        }


@dataclass(frozen=True, slots=True)
class StructuralAdmissionResult:
    """Admit/reject result for one prior-L1 vs candidate-L1 repair pair.

    On reject or fail-closed timeout/error, ``admitted_l1`` is identical to
    ``prior_l1`` and ``prior_l1_unchanged`` is true.  Proof success never
    appears as end-to-end loss.
    """

    disposition: AdmissionDisposition
    prior_l1: CanonicalRuleIR
    candidate_l1: CanonicalRuleIR | None
    admitted_l1: CanonicalRuleIR
    prior_l1_unchanged: bool
    rejection_reason: str | None
    check_receipts: tuple[AdmissionCheckReceipt, ...]
    field_changes: tuple[CanonicalFieldChange, ...]
    policy_digest: str
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, AdmissionDisposition):
            try:
                object.__setattr__(
                    self,
                    "disposition",
                    AdmissionDisposition(self.disposition),
                )
            except (TypeError, ValueError) as exc:
                raise StructuralAdmissionError(
                    "admission disposition is invalid"
                ) from exc
        if self.disposition.value not in _ADMISSION_DISPOSITIONS:
            raise StructuralAdmissionError(
                f"unknown admission disposition: {self.disposition!r}"
            )
        if not isinstance(self.prior_l1, CanonicalRuleIR):
            raise StructuralAdmissionError("prior_l1 must be CanonicalRuleIR")
        if self.candidate_l1 is not None and not isinstance(
            self.candidate_l1, CanonicalRuleIR
        ):
            raise StructuralAdmissionError(
                "candidate_l1 must be CanonicalRuleIR or None"
            )
        if not isinstance(self.admitted_l1, CanonicalRuleIR):
            raise StructuralAdmissionError(
                "admitted_l1 must be CanonicalRuleIR"
            )
        if not isinstance(self.prior_l1_unchanged, bool):
            raise StructuralAdmissionError(
                "prior_l1_unchanged must be boolean"
            )
        object.__setattr__(self, "check_receipts", tuple(self.check_receipts))
        object.__setattr__(self, "field_changes", tuple(self.field_changes))
        if not all(
            isinstance(item, AdmissionCheckReceipt)
            for item in self.check_receipts
        ):
            raise StructuralAdmissionError("check_receipts are invalid")
        if not all(
            isinstance(item, CanonicalFieldChange)
            for item in self.field_changes
        ):
            raise StructuralAdmissionError("field_changes are invalid")
        if not isinstance(self.policy_digest, str) or not self.policy_digest:
            raise StructuralAdmissionError("policy_digest must be nonblank")

        if self.disposition is AdmissionDisposition.ACCEPTED:
            if self.candidate_l1 is None:
                raise StructuralAdmissionError(
                    "accepted admission requires a candidate L1"
                )
            if self.admitted_l1 != self.candidate_l1:
                raise StructuralAdmissionError(
                    "accepted admission must admit the candidate L1"
                )
            if self.prior_l1_unchanged and self.candidate_l1 != self.prior_l1:
                raise StructuralAdmissionError(
                    "accepted non-identity repair cannot claim prior unchanged"
                )
            if self.rejection_reason is not None:
                raise StructuralAdmissionError(
                    "accepted admission cannot carry a rejection_reason"
                )
        elif self.disposition is AdmissionDisposition.NOT_APPLICABLE:
            if self.admitted_l1 != self.prior_l1:
                raise StructuralAdmissionError(
                    "not_applicable must retain prior L1"
                )
            if not self.prior_l1_unchanged:
                raise StructuralAdmissionError(
                    "not_applicable must leave prior L1 unchanged"
                )
        else:
            # Reject / timeout / error: fail-closed retention of prior L1.
            if self.admitted_l1 != self.prior_l1:
                raise StructuralAdmissionError(
                    "rejected or fail-closed admission must leave prior L1 "
                    "unchanged as admitted_l1"
                )
            if not self.prior_l1_unchanged:
                raise StructuralAdmissionError(
                    "rejected or fail-closed admission must set "
                    "prior_l1_unchanged"
                )
            if self.disposition is AdmissionDisposition.VALIDATOR_REJECT:
                if self.rejection_reason != VALIDATOR_REJECT:
                    raise StructuralAdmissionError(
                        "validator reject must record "
                        f"{VALIDATOR_REJECT!r}"
                    )
            elif self.disposition is AdmissionDisposition.TIMEOUT:
                if self.rejection_reason not in {
                    VALIDATOR_REJECT,
                    "timeout",
                }:
                    raise StructuralAdmissionError(
                        "timeout fail-closed must record a reject reason"
                    )
            elif self.disposition is AdmissionDisposition.ERROR:
                if self.rejection_reason not in {
                    VALIDATOR_REJECT,
                    "error",
                }:
                    raise StructuralAdmissionError(
                        "error fail-closed must record a reject reason"
                    )

    @property
    def accepted(self) -> bool:
        return self.disposition is AdmissionDisposition.ACCEPTED

    @property
    def rejected(self) -> bool:
        return self.disposition in {
            AdmissionDisposition.VALIDATOR_REJECT,
            AdmissionDisposition.TIMEOUT,
            AdmissionDisposition.ERROR,
        }

    @property
    def field_change_count(self) -> int:
        return len(self.field_changes)

    @property
    def accepted_repair_delta(self) -> int:
        """Field-change count credited only when the repair is admitted.

        Zero when rejected/timeout/not-applicable so proof/structure
        outcomes never masquerade as end-to-end semantic improvement.
        """

        if self.disposition is not AdmissionDisposition.ACCEPTED:
            return 0
        return self.field_change_count

    @property
    def end_to_end_loss(self) -> None:
        """Structural admission never produces end-to-end loss."""

        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "accepted_repair_delta": self.accepted_repair_delta,
            "admitted_l1": self.admitted_l1.to_dict(),
            "candidate_l1": (
                self.candidate_l1.to_dict()
                if self.candidate_l1 is not None
                else None
            ),
            "check_receipts": [
                item.to_dict() for item in self.check_receipts
            ],
            "detail": self.detail,
            "disposition": self.disposition.value,
            "end_to_end_loss": None,
            "field_change_count": self.field_change_count,
            "field_changes": [item.to_dict() for item in self.field_changes],
            "interface": STRUCTURAL_ADMISSION_RECEIPT_INTERFACE,
            "policy_digest": self.policy_digest,
            "prior_l1": self.prior_l1.to_dict(),
            "prior_l1_unchanged": self.prior_l1_unchanged,
            "proof_pass_is_not_end_to_end_loss": True,
            "rejected": self.rejected,
            "rejection_reason": self.rejection_reason,
            "schema": STRUCTURAL_ADMISSION_SCHEMA,
            "semantic_authority": False,
            "separate_from_end_to_end_loss": True,
        }


@dataclass(frozen=True, slots=True)
class StructuralAdmissionMetrics:
    """Aggregate admission statistics, separate from end-to-end loss.

    ``reject_rate`` is the fraction of applicable attempts that failed closed
    (validator reject, timeout, or error).  ``accepted_repair_delta`` is the
    mean field-change count over accepted repairs only (0 when none accepted).
    Neither value is protocol end-to-end loss.
    """

    attempts: int
    accepted: int
    rejected: int
    timeouts: int
    errors: int
    not_applicable: int
    total_accepted_field_changes: int

    def __post_init__(self) -> None:
        for name in (
            "attempts",
            "accepted",
            "rejected",
            "timeouts",
            "errors",
            "not_applicable",
            "total_accepted_field_changes",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise StructuralAdmissionError(
                    f"{name} must be a non-negative integer"
                )
        applicable = self.accepted + self.rejected
        if self.attempts != applicable + self.not_applicable:
            raise StructuralAdmissionError(
                "attempts must equal accepted + rejected + not_applicable"
            )
        if self.timeouts + self.errors > self.rejected:
            raise StructuralAdmissionError(
                "timeouts and errors cannot exceed rejected"
            )
        if self.accepted == 0 and self.total_accepted_field_changes != 0:
            raise StructuralAdmissionError(
                "accepted field changes require accepted attempts"
            )

    @property
    def reject_rate(self) -> float:
        applicable = self.accepted + self.rejected
        if applicable == 0:
            return 0.0
        return self.rejected / applicable

    @property
    def accept_rate(self) -> float:
        applicable = self.accepted + self.rejected
        if applicable == 0:
            return 0.0
        return self.accepted / applicable

    @property
    def accepted_repair_delta(self) -> float:
        """Mean field-change delta over accepted repairs only."""

        if self.accepted == 0:
            return 0.0
        return self.total_accepted_field_changes / self.accepted

    @property
    def end_to_end_loss(self) -> None:
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "accept_rate": self.accept_rate,
            "accepted": self.accepted,
            "accepted_repair_delta": self.accepted_repair_delta,
            "attempts": self.attempts,
            "end_to_end_loss": None,
            "errors": self.errors,
            "interface": STRUCTURAL_ADMISSION_METRICS_INTERFACE,
            "not_applicable": self.not_applicable,
            "proof_pass_is_not_end_to_end_loss": True,
            "reject_rate": self.reject_rate,
            "rejected": self.rejected,
            "schema": STRUCTURAL_ADMISSION_SCHEMA,
            "separate_from_end_to_end_loss": True,
            "timeouts": self.timeouts,
            "total_accepted_field_changes": self.total_accepted_field_changes,
        }


def aggregate_structural_admission_metrics(
    results: Sequence[StructuralAdmissionResult],
) -> StructuralAdmissionMetrics:
    """Aggregate admission results into reject-rate and repair-delta metrics."""

    if isinstance(results, (str, bytes, bytearray)) or not isinstance(
        results, Sequence
    ):
        raise StructuralAdmissionError(
            "results must be a sequence of StructuralAdmissionResult"
        )
    accepted = 0
    rejected = 0
    timeouts = 0
    errors = 0
    not_applicable = 0
    total_delta = 0
    for item in results:
        if not isinstance(item, StructuralAdmissionResult):
            raise StructuralAdmissionError(
                "results must contain StructuralAdmissionResult records"
            )
        if item.disposition is AdmissionDisposition.ACCEPTED:
            accepted += 1
            total_delta += item.accepted_repair_delta
        elif item.disposition is AdmissionDisposition.NOT_APPLICABLE:
            not_applicable += 1
        else:
            rejected += 1
            if item.disposition is AdmissionDisposition.TIMEOUT:
                timeouts += 1
            elif item.disposition is AdmissionDisposition.ERROR:
                errors += 1
    return StructuralAdmissionMetrics(
        attempts=len(results),
        accepted=accepted,
        rejected=rejected,
        timeouts=timeouts,
        errors=errors,
        not_applicable=not_applicable,
        total_accepted_field_changes=total_delta,
    )


def _local_structural_reasons(
    prior: CanonicalRuleIR,
    candidate: CanonicalRuleIR,
    *,
    allowed_field_paths: Sequence[str] | None,
    constraints: Sequence[str],
) -> tuple[str, ...]:
    """Evaluate declared structural constraints without proof tools."""

    reasons: list[str] = []
    constraint_set = set(constraints)
    if "non_vacuous_candidate" in constraint_set and candidate.is_empty:
        reasons.append("vacuous_candidate")
    if (
        "rule_cardinality_preserved" in constraint_set
        and len(candidate.rules) != len(prior.rules)
    ):
        reasons.append("rule_cardinality_changed")
    changes = canonical_field_changes(prior, candidate)
    if "untriggered_projection_preserved" in constraint_set:
        if allowed_field_paths is not None:
            allowed = set(allowed_field_paths)
            # Wildcard means every changed path was already authorized upstream.
            if "*" not in allowed:
                for change in changes:
                    path = (
                        f"rules[{change.baseline_rule_index}]."
                        f"{change.canonical_field}"
                        if change.baseline_rule_index is not None
                        else change.path
                    )
                    if change.canonical_field not in RULE_FIELDS:
                        continue
                    bare = change.canonical_field
                    alt = (
                        f"rules[{change.guided_rule_index}]."
                        f"{change.canonical_field}"
                        if change.guided_rule_index is not None
                        else path
                    )
                    if (
                        path not in allowed
                        and bare not in allowed
                        and alt not in allowed
                    ):
                        reasons.append(f"untriggered_field_changed:{path}")
                        break
    return tuple(reasons)


def _run_validator_bounded(
    binding: StructuralValidatorBinding,
    request: StructuralValidationRequest,
    *,
    timeout_seconds: float,
) -> AdmissionCheckReceipt:
    """Invoke one structural validator under a hard wall-clock budget."""

    started = time.perf_counter()

    def _invoke() -> StructuralValidationReceipt:
        receipt = binding.validate(request)
        if not isinstance(receipt, StructuralValidationReceipt):
            raise StructuralAdmissionError(
                "validator returned a non-StructuralValidationReceipt"
            )
        if (
            receipt.validator_id != binding.validator_id
            or receipt.tool is not binding.tool
        ):
            raise StructuralAdmissionError(
                "validator receipt drifted from its binding"
            )
        if receipt.semantic_authority is not False:
            raise StructuralAdmissionError(
                "validator cannot claim semantic authority"
            )
        return receipt

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_invoke)
            try:
                receipt = future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                future.cancel()
                elapsed = time.perf_counter() - started
                return AdmissionCheckReceipt(
                    validator_id=binding.validator_id,
                    tool=binding.tool,
                    passed=False,
                    timed_out=True,
                    elapsed_seconds=elapsed,
                    detail=_detail(
                        f"validator timed out after {timeout_seconds}s",
                        "validator timeout",
                    ),
                    constraints=binding.constraints,
                )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        elapsed = time.perf_counter() - started
        # Treat explicit timeout-class exceptions as fail-closed timeouts.
        timed_out = isinstance(exc, (TimeoutError, concurrent.futures.TimeoutError))
        return AdmissionCheckReceipt(
            validator_id=binding.validator_id,
            tool=binding.tool,
            passed=False,
            timed_out=timed_out,
            elapsed_seconds=elapsed,
            detail=_detail(
                f"validator failed: {type(exc).__name__}: {exc}",
                "validator failed",
            ),
            constraints=binding.constraints,
        )

    elapsed = time.perf_counter() - started
    return AdmissionCheckReceipt(
        validator_id=binding.validator_id,
        tool=binding.tool,
        passed=bool(receipt.passed),
        timed_out=False,
        elapsed_seconds=elapsed,
        detail=receipt.detail,
        constraints=receipt.constraints,
    )


class StructuralAdmissionGate:
    """Bounded Hammer/cvc5 and/or Lean admission gate for hybrid repairs.

    Callers supply prior L1 (pre-repair) and a candidate repaired L1.  The
    gate returns an admitted L1 that is either the candidate (accept) or the
    prior (reject / fail-closed), never a silent substitution.
    """

    interface: Final = STRUCTURAL_ADMISSION_INTERFACE

    def __init__(
        self,
        policy: StructuralAdmissionPolicy | None = None,
        *,
        validators: Sequence[StructuralValidatorBinding] = (),
    ) -> None:
        self._policy = policy or StructuralAdmissionPolicy()
        if not isinstance(self._policy, StructuralAdmissionPolicy):
            raise StructuralAdmissionError(
                "policy must be StructuralAdmissionPolicy"
            )
        self._validators = tuple(validators)
        if not all(
            isinstance(item, StructuralValidatorBinding)
            for item in self._validators
        ):
            raise StructuralAdmissionError(
                "validators must be StructuralValidatorBinding records"
            )
        identities = [item.validator_id for item in self._validators]
        if len(set(identities)) != len(identities):
            raise StructuralAdmissionError(
                "structural validator identities must be unique"
            )
        tool_set = {item.tool for item in self._validators}
        for required in self._policy.tools:
            if required not in tool_set and self._validators:
                # When validators are supplied they must cover every policy tool.
                # Empty validators means pure local-constraint admission.
                raise StructuralAdmissionError(
                    f"missing validator binding for policy tool {required.value}"
                )
        for binding in self._validators:
            if binding.tool not in self._policy.tools:
                raise StructuralAdmissionError(
                    f"validator tool {binding.tool.value} is not in policy tools"
                )

    @property
    def policy(self) -> StructuralAdmissionPolicy:
        return self._policy

    @property
    def validators(self) -> tuple[StructuralValidatorBinding, ...]:
        return self._validators

    @property
    def identity(self) -> str:
        validators = ",".join(
            f"{item.tool.value}:{item.validator_id}"
            for item in self._validators
        ) or "local_constraints_only"
        return f"{self.interface}:{self._policy.digest}:{validators}"

    def admit(
        self,
        prior_l1: CanonicalRuleIR,
        candidate_l1: CanonicalRuleIR | None,
        *,
        allowed_field_paths: Sequence[str] | None = None,
    ) -> StructuralAdmissionResult:
        """Admit or reject a candidate repair under the frozen policy.

        * No candidate, or candidate identical to prior → ``not_applicable``,
          prior retained.
        * All configured checks pass → ``accepted``, candidate admitted.
        * Any check fails → ``validator_reject``, prior retained.
        * Timeout / error → fail-closed reject, prior retained.
        """

        if not isinstance(prior_l1, CanonicalRuleIR):
            raise StructuralAdmissionError("prior_l1 must be CanonicalRuleIR")
        if candidate_l1 is not None and not isinstance(
            candidate_l1, CanonicalRuleIR
        ):
            raise StructuralAdmissionError(
                "candidate_l1 must be CanonicalRuleIR or None"
            )

        if candidate_l1 is None or candidate_l1 == prior_l1:
            return StructuralAdmissionResult(
                disposition=AdmissionDisposition.NOT_APPLICABLE,
                prior_l1=prior_l1,
                candidate_l1=candidate_l1,
                admitted_l1=prior_l1,
                prior_l1_unchanged=True,
                rejection_reason=None,
                check_receipts=(),
                field_changes=(),
                policy_digest=self._policy.digest,
                detail="no repair candidate to admit",
            )

        changes = canonical_field_changes(prior_l1, candidate_l1)
        local_reasons = _local_structural_reasons(
            prior_l1,
            candidate_l1,
            allowed_field_paths=allowed_field_paths,
            constraints=self._policy.structural_constraints,
        )
        if local_reasons:
            return StructuralAdmissionResult(
                disposition=AdmissionDisposition.VALIDATOR_REJECT,
                prior_l1=prior_l1,
                candidate_l1=candidate_l1,
                admitted_l1=prior_l1,
                prior_l1_unchanged=True,
                rejection_reason=VALIDATOR_REJECT,
                check_receipts=(),
                field_changes=changes,
                policy_digest=self._policy.digest,
                detail="local structural constraints failed: "
                + ",".join(local_reasons),
            )

        if not self._validators:
            # Local constraints alone: admit when they pass.
            return StructuralAdmissionResult(
                disposition=AdmissionDisposition.ACCEPTED,
                prior_l1=prior_l1,
                candidate_l1=candidate_l1,
                admitted_l1=candidate_l1,
                prior_l1_unchanged=False,
                rejection_reason=None,
                check_receipts=(),
                field_changes=changes,
                policy_digest=self._policy.digest,
                detail="admitted under local structural constraints only",
            )

        changed_paths = tuple(
            (
                f"rules[{item.baseline_rule_index}].{item.canonical_field}"
                if item.baseline_rule_index is not None
                else item.path
            )
            for item in changes
        )
        allowed = (
            tuple(allowed_field_paths)
            if allowed_field_paths is not None
            else changed_paths or ("*",)
        )
        # StructuralValidationRequest requires nonempty allowed paths.
        if not allowed:
            allowed = ("*",)

        receipts: list[AdmissionCheckReceipt] = []
        any_timeout = False
        any_error = False
        any_fail = False
        for binding in self._validators:
            request = StructuralValidationRequest(
                baseline_ir=prior_l1,
                candidate_ir=candidate_l1,
                allowed_field_paths=allowed,
                changed_field_paths=changed_paths,
                constraints=binding.constraints,
            )
            receipt = _run_validator_bounded(
                binding,
                request,
                timeout_seconds=self._policy.timeout_seconds,
            )
            receipts.append(receipt)
            if receipt.timed_out:
                any_timeout = True
                any_fail = True
            elif not receipt.passed:
                # Distinguish hard errors (detail starts with validator failed)
                # from ordinary structural rejection.
                detail = (receipt.detail or "").lower()
                if detail.startswith("validator failed:"):
                    any_error = True
                any_fail = True
            if any_fail and not self._policy.require_all_pass:
                # Still record remaining tools only when all must pass.
                # With require_all_pass=False, first failure already decides.
                break
            if any_fail and self._policy.require_all_pass:
                # Continue to collect receipts for auditability.
                continue

        if any_timeout and self._policy.fail_closed_on_timeout:
            return StructuralAdmissionResult(
                disposition=AdmissionDisposition.TIMEOUT,
                prior_l1=prior_l1,
                candidate_l1=candidate_l1,
                admitted_l1=prior_l1,
                prior_l1_unchanged=True,
                rejection_reason=VALIDATOR_REJECT,
                check_receipts=tuple(receipts),
                field_changes=changes,
                policy_digest=self._policy.digest,
                detail="admission timed out; fail-closed retain prior L1",
            )
        if any_error and self._policy.fail_closed_on_error:
            return StructuralAdmissionResult(
                disposition=AdmissionDisposition.ERROR,
                prior_l1=prior_l1,
                candidate_l1=candidate_l1,
                admitted_l1=prior_l1,
                prior_l1_unchanged=True,
                rejection_reason=VALIDATOR_REJECT,
                check_receipts=tuple(receipts),
                field_changes=changes,
                policy_digest=self._policy.digest,
                detail="admission validator error; fail-closed retain prior L1",
            )
        if any_fail:
            return StructuralAdmissionResult(
                disposition=AdmissionDisposition.VALIDATOR_REJECT,
                prior_l1=prior_l1,
                candidate_l1=candidate_l1,
                admitted_l1=prior_l1,
                prior_l1_unchanged=True,
                rejection_reason=VALIDATOR_REJECT,
                check_receipts=tuple(receipts),
                field_changes=changes,
                policy_digest=self._policy.digest,
                detail="structural validator rejected the candidate repair",
            )

        return StructuralAdmissionResult(
            disposition=AdmissionDisposition.ACCEPTED,
            prior_l1=prior_l1,
            candidate_l1=candidate_l1,
            admitted_l1=candidate_l1,
            prior_l1_unchanged=False,
            rejection_reason=None,
            check_receipts=tuple(receipts),
            field_changes=changes,
            policy_digest=self._policy.digest,
            detail="candidate repair admitted by structural gates",
        )


def admit_hybrid_repair(
    prior_l1: CanonicalRuleIR,
    candidate_l1: CanonicalRuleIR | None,
    *,
    gate: StructuralAdmissionGate | None = None,
    allowed_field_paths: Sequence[str] | None = None,
) -> StructuralAdmissionResult:
    """Hybrid-path entry: gate a candidate repair against prior L1.

    Intended for ``typed_deontic → optional repair → deterministic realizer``
    pipelines so that rejected candidates never replace prior L1.
    """

    active = gate or StructuralAdmissionGate()
    return active.admit(
        prior_l1,
        candidate_l1,
        allowed_field_paths=allowed_field_paths,
    )


def make_admission_binding(
    *,
    validator_id: str,
    tool: StructuralTool | str,
    validate: StructuralValidatorCallable,
    constraints: Sequence[str] | None = None,
) -> StructuralValidatorBinding:
    """Build a preregistered structural validator binding for admission."""

    return StructuralValidatorBinding(
        validator_id=validator_id,
        tool=tool if isinstance(tool, StructuralTool) else StructuralTool(tool),
        constraints=tuple(constraints or DECLARED_STRUCTURAL_CONSTRAINTS),
        validate=validate,
    )


def make_passing_binding(
    *,
    validator_id: str,
    tool: StructuralTool | str,
    constraints: Sequence[str] | None = None,
    delay_seconds: float = 0.0,
) -> StructuralValidatorBinding:
    """Test/helper binding that always passes (optionally after a delay)."""

    resolved_tool = (
        tool if isinstance(tool, StructuralTool) else StructuralTool(tool)
    )
    resolved_constraints = tuple(
        constraints or DECLARED_STRUCTURAL_CONSTRAINTS
    )

    def validate(
        request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        del request
        if delay_seconds > 0.0:
            time.sleep(delay_seconds)
        return StructuralValidationReceipt(
            validator_id=validator_id,
            tool=resolved_tool,
            constraints=resolved_constraints,
            passed=True,
            detail="structural admission pass",
        )

    return make_admission_binding(
        validator_id=validator_id,
        tool=resolved_tool,
        validate=validate,
        constraints=resolved_constraints,
    )


def make_rejecting_binding(
    *,
    validator_id: str,
    tool: StructuralTool | str,
    constraints: Sequence[str] | None = None,
    detail: str = "structural admission reject",
) -> StructuralValidatorBinding:
    """Test/helper binding that always rejects."""

    resolved_tool = (
        tool if isinstance(tool, StructuralTool) else StructuralTool(tool)
    )
    resolved_constraints = tuple(
        constraints or DECLARED_STRUCTURAL_CONSTRAINTS
    )

    def validate(
        request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        del request
        return StructuralValidationReceipt(
            validator_id=validator_id,
            tool=resolved_tool,
            constraints=resolved_constraints,
            passed=False,
            detail=detail,
        )

    return make_admission_binding(
        validator_id=validator_id,
        tool=resolved_tool,
        validate=validate,
        constraints=resolved_constraints,
    )


def make_timeout_binding(
    *,
    validator_id: str,
    tool: StructuralTool | str,
    constraints: Sequence[str] | None = None,
    sleep_seconds: float = 30.0,
) -> StructuralValidatorBinding:
    """Test/helper binding that sleeps past any reasonable admission budget."""

    resolved_tool = (
        tool if isinstance(tool, StructuralTool) else StructuralTool(tool)
    )
    resolved_constraints = tuple(
        constraints or DECLARED_STRUCTURAL_CONSTRAINTS
    )

    def validate(
        request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        del request
        time.sleep(sleep_seconds)
        return StructuralValidationReceipt(
            validator_id=validator_id,
            tool=resolved_tool,
            constraints=resolved_constraints,
            passed=True,
            detail="should not be observed under timeout",
        )

    return make_admission_binding(
        validator_id=validator_id,
        tool=resolved_tool,
        validate=validate,
        constraints=resolved_constraints,
    )


def make_error_binding(
    *,
    validator_id: str,
    tool: StructuralTool | str,
    constraints: Sequence[str] | None = None,
    message: str = "injected validator crash",
) -> StructuralValidatorBinding:
    """Test/helper binding that raises, for fail-closed error coverage."""

    resolved_tool = (
        tool if isinstance(tool, StructuralTool) else StructuralTool(tool)
    )
    resolved_constraints = tuple(
        constraints or DECLARED_STRUCTURAL_CONSTRAINTS
    )

    def validate(
        request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        del request
        raise RuntimeError(message)

    return make_admission_binding(
        validator_id=validator_id,
        tool=resolved_tool,
        validate=validate,
        constraints=resolved_constraints,
    )


def _constraint_reasons_from_request(
    request: StructuralValidationRequest,
    constraints: Sequence[str],
) -> tuple[str, ...]:
    """Map a validation request onto the declared structural constraints."""

    return _local_structural_reasons(
        request.baseline_ir,
        request.candidate_ir,
        allowed_field_paths=request.allowed_field_paths,
        constraints=constraints,
    )


def default_hammer_cvc5_binding(
    *,
    validator_id: str = DEFAULT_HAMMER_VALIDATOR_ID,
    constraints: Sequence[str] | None = None,
) -> StructuralValidatorBinding:
    """Bind Hammer/cvc5 as a structural admit/reject gate (lazy import).

    Declared structural constraints are evaluated against prior vs candidate.
    cvc5 is invoked as a non-authoritative self-consistency smoke on the
    candidate only so field-changing repairs are not rejected solely for
    differing from the prior.  The solver verdict never becomes end-to-end
    semantic loss.
    """

    resolved_constraints = tuple(
        constraints or DECLARED_STRUCTURAL_CONSTRAINTS
    )

    def validate(
        request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        local_reasons = _constraint_reasons_from_request(
            request, resolved_constraints
        )
        if local_reasons:
            return StructuralValidationReceipt(
                validator_id=validator_id,
                tool=StructuralTool.HAMMER_CVC5,
                constraints=resolved_constraints,
                passed=False,
                detail="structural constraints failed: "
                + ",".join(local_reasons),
            )
        from benchmarks.bench_semantic_logic_roundtrip import (
            hammer_cvc5_equivalence,
        )

        # Self-consistency smoke: candidate ≡ candidate under cvc5.
        # This exercises the solver without treating proof pass as fidelity.
        candidate = request.candidate_ir.to_dict()
        payload = hammer_cvc5_equivalence(
            candidate,
            candidate,
            request_id=(
                f"admission-{validator_id}-"
                f"{_sha(request.to_dict())[:16]}"
            ),
        )
        status = str(payload.get("status", "unavailable"))
        if status != "success":
            return StructuralValidationReceipt(
                validator_id=validator_id,
                tool=StructuralTool.HAMMER_CVC5,
                constraints=resolved_constraints,
                passed=False,
                detail=_detail(
                    payload.get("reason") or status,
                    "hammer_cvc5 unavailable",
                ),
            )
        nonvacuous = bool(payload.get("nonvacuous", True))
        solver_ok = bool(payload.get("equivalent")) and nonvacuous
        return StructuralValidationReceipt(
            validator_id=validator_id,
            tool=StructuralTool.HAMMER_CVC5,
            constraints=resolved_constraints,
            passed=solver_ok,
            detail=_detail(
                f"hammer_cvc5 self_consistent={solver_ok} "
                f"nonvacuous={nonvacuous}",
                "hammer_cvc5 result",
            ),
        )

    return make_admission_binding(
        validator_id=validator_id,
        tool=StructuralTool.HAMMER_CVC5,
        validate=validate,
        constraints=resolved_constraints,
    )


def default_lean_binding(
    *,
    validator_id: str = DEFAULT_LEAN_VALIDATOR_ID,
    lean_path: str | None = None,
    constraints: Sequence[str] | None = None,
) -> StructuralValidatorBinding:
    """Bind Lean as a structural admit/reject gate (lazy import).

    Declared constraints are checked first.  Lean is then invoked as a
    candidate self-identity smoke so repairs that change slots are not
    rejected solely for differing from prior L1.  Kernel success is never
    end-to-end loss.
    """

    import shutil

    resolved_constraints = tuple(
        constraints or DECLARED_STRUCTURAL_CONSTRAINTS
    )
    resolved_lean = lean_path if lean_path is not None else shutil.which("lean")

    def validate(
        request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        local_reasons = _constraint_reasons_from_request(
            request, resolved_constraints
        )
        if local_reasons:
            return StructuralValidationReceipt(
                validator_id=validator_id,
                tool=StructuralTool.LEAN,
                constraints=resolved_constraints,
                passed=False,
                detail="structural constraints failed: "
                + ",".join(local_reasons),
            )
        if resolved_lean is None:
            return StructuralValidationReceipt(
                validator_id=validator_id,
                tool=StructuralTool.LEAN,
                constraints=resolved_constraints,
                passed=False,
                detail="Lean executable is unavailable",
            )
        from benchmarks.bench_semantic_logic_roundtrip import (
            lean_exact_identity,
        )

        candidate = request.candidate_ir.to_dict()
        payload = lean_exact_identity(
            candidate,
            candidate,
            lean_path=resolved_lean,
        )
        status = str(payload.get("status", "unavailable"))
        if status != "success":
            return StructuralValidationReceipt(
                validator_id=validator_id,
                tool=StructuralTool.LEAN,
                constraints=resolved_constraints,
                passed=False,
                detail=_detail(
                    payload.get("reason") or status,
                    "lean unavailable",
                ),
            )
        # lean_exact_identity uses kernel_accepted / benchmark_accepted.
        identical = bool(
            payload.get("benchmark_accepted")
            or payload.get("kernel_accepted")
            or payload.get("identical")
            or payload.get("accepted")
        )
        return StructuralValidationReceipt(
            validator_id=validator_id,
            tool=StructuralTool.LEAN,
            constraints=resolved_constraints,
            passed=identical,
            detail=_detail(
                f"lean self_identity={identical}",
                "lean result",
            ),
        )

    return make_admission_binding(
        validator_id=validator_id,
        tool=StructuralTool.LEAN,
        validate=validate,
        constraints=resolved_constraints,
    )


def build_default_admission_gate(
    *,
    policy: StructuralAdmissionPolicy | None = None,
    include_hammer_cvc5: bool = True,
    include_lean: bool = True,
    lean_path: str | None = None,
) -> StructuralAdmissionGate:
    """Assemble a gate with the requested tool family bindings."""

    active = policy
    if active is None:
        tools: list[StructuralTool] = []
        if include_hammer_cvc5:
            tools.append(StructuralTool.HAMMER_CVC5)
        if include_lean:
            tools.append(StructuralTool.LEAN)
        if not tools:
            tools = [StructuralTool.HAMMER_CVC5]
        active = StructuralAdmissionPolicy(tools=tuple(tools))
    bindings: list[StructuralValidatorBinding] = []
    if include_hammer_cvc5 and StructuralTool.HAMMER_CVC5 in active.tools:
        bindings.append(default_hammer_cvc5_binding())
    if include_lean and StructuralTool.LEAN in active.tools:
        bindings.append(default_lean_binding(lean_path=lean_path))
    return StructuralAdmissionGate(active, validators=bindings)


__all__ = [
    "AdmissionCheckReceipt",
    "AdmissionDisposition",
    "DEFAULT_ADMISSION_TIMEOUT_SECONDS",
    "DEFAULT_HAMMER_VALIDATOR_ID",
    "DEFAULT_LEAN_VALIDATOR_ID",
    "STRUCTURAL_ADMISSION_INTERFACE",
    "STRUCTURAL_ADMISSION_METRICS_INTERFACE",
    "STRUCTURAL_ADMISSION_RECEIPT_INTERFACE",
    "STRUCTURAL_ADMISSION_SCHEMA",
    "StructuralAdmissionError",
    "StructuralAdmissionGate",
    "StructuralAdmissionMetrics",
    "StructuralAdmissionPolicy",
    "StructuralAdmissionResult",
    "VALIDATOR_REJECT",
    "admit_hybrid_repair",
    "aggregate_structural_admission_metrics",
    "build_default_admission_gate",
    "default_hammer_cvc5_binding",
    "default_lean_binding",
    "make_admission_binding",
    "make_error_binding",
    "make_passing_binding",
    "make_rejecting_binding",
    "make_timeout_binding",
]

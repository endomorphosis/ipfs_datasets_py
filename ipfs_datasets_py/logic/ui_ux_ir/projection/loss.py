"""Projection loss receipts for explicit degradation and unsatisfiable results.

Silent omission of mandatory actions, consent, consequences, errors,
confirmations, feedback, or accessibility alternatives is forbidden. Every
adapted, fallback, omitted, or unsatisfiable semantic produces a structured
loss receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Iterable, Mapping, Sequence

from ..schema import AdaptationPolicy, UIIRValidationError

UI_PROJECTION_LOSS_INTERFACE: Final = "UIProjectionLoss@1"
UI_PROJECTION_LOSS_SCHEMA_VERSION: Final = "ui-projection-loss/v1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class LossCategory(str, Enum):
    """How a semantic was treated under projection."""

    PRESERVED = "preserved"
    ADAPTED = "adapted"
    SUMMARIZED = "summarized"
    FALLBACK = "fallback"
    OMITTED = "omitted"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"
    UNSATISFIABLE = "unsatisfiable"
    BUDGET_EXCEEDED = "budget_exceeded"


class MandatorySemanticKind(str, Enum):
    """Semantics that must never be silently dropped."""

    ACTION = "action"
    CONSENT = "consent"
    CONSEQUENCE = "consequence"
    ERROR = "error"
    CONFIRMATION = "confirmation"
    FEEDBACK = "feedback"
    ACCESSIBILITY = "accessibility"
    PRIVACY = "privacy"


# Mandatory kinds that always require preserve, fallback, or explicit unsatisfiable.
MANDATORY_SEMANTIC_KINDS: Final[frozenset[str]] = frozenset(
    kind.value for kind in MandatorySemanticKind
)

# Loss categories that do not constitute silent omission for mandatory semantics.
_MANDATORY_SAFE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        LossCategory.PRESERVED.value,
        LossCategory.ADAPTED.value,
        LossCategory.SUMMARIZED.value,
        LossCategory.FALLBACK.value,
        LossCategory.UNSATISFIABLE.value,
        LossCategory.UNSUPPORTED.value,
        LossCategory.BUDGET_EXCEEDED.value,
        LossCategory.DEGRADED.value,
    }
)

# Categories that still count as "handled" rather than silent omit.
_EXPLICIT_OUTCOME_CATEGORIES: Final[frozenset[str]] = (
    _MANDATORY_SAFE_CATEGORIES | frozenset({LossCategory.OMITTED.value})
)


class LossSeverity(str, Enum):
    """Relative severity for ranking projection variants."""

    NONE = "none"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise UIIRValidationError(f"{name} is not a stable identifier")


def _validate_non_empty_string(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise UIIRValidationError(f"{name} must be a non-empty string")


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise UIIRValidationError(f"{name} must be an immutable tuple")


def severity_for_category(
    category: LossCategory,
    *,
    mandatory: bool,
) -> LossSeverity:
    """Map a loss category to severity (deterministic, closed table)."""

    if category is LossCategory.PRESERVED:
        return LossSeverity.NONE
    if category is LossCategory.ADAPTED:
        return LossSeverity.INFO if not mandatory else LossSeverity.WARNING
    if category is LossCategory.SUMMARIZED:
        return LossSeverity.WARNING
    if category is LossCategory.FALLBACK:
        return LossSeverity.WARNING
    if category is LossCategory.DEGRADED:
        return LossSeverity.WARNING
    if category is LossCategory.OMITTED:
        return LossSeverity.ERROR if mandatory else LossSeverity.WARNING
    if category is LossCategory.BUDGET_EXCEEDED:
        return LossSeverity.ERROR if mandatory else LossSeverity.WARNING
    if category is LossCategory.UNSUPPORTED:
        return LossSeverity.ERROR if mandatory else LossSeverity.WARNING
    if category is LossCategory.UNSATISFIABLE:
        return LossSeverity.CRITICAL if mandatory else LossSeverity.ERROR
    return LossSeverity.ERROR


def loss_score(category: LossCategory, *, mandatory: bool) -> int:
    """Integer penalty used to rank projection variants (lower is better)."""

    base = {
        LossCategory.PRESERVED: 0,
        LossCategory.ADAPTED: 1,
        LossCategory.SUMMARIZED: 2,
        LossCategory.FALLBACK: 3,
        LossCategory.DEGRADED: 4,
        LossCategory.OMITTED: 8,
        LossCategory.BUDGET_EXCEEDED: 9,
        LossCategory.UNSUPPORTED: 10,
        LossCategory.UNSATISFIABLE: 100,
    }[category]
    return base + (50 if mandatory and category is not LossCategory.PRESERVED else 0)


@dataclass(frozen=True, slots=True)
class ProjectionLoss:
    """One explicit projection loss or disposition receipt entry."""

    loss_id: str
    semantic_id: str
    semantic_kind: str
    category: LossCategory
    reason: str
    mandatory: bool = False
    adaptation_policy: AdaptationPolicy = AdaptationPolicy.PRESERVE
    fallback_ref: str = ""
    budget_kind: str = ""
    severity: LossSeverity = LossSeverity.INFO
    source_ref: str = ""
    details: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("ProjectionLoss.loss_id", self.loss_id)
        _validate_identifier("ProjectionLoss.semantic_id", self.semantic_id)
        _validate_non_empty_string("ProjectionLoss.semantic_kind", self.semantic_kind)
        if not isinstance(self.category, LossCategory):
            raise UIIRValidationError(
                "ProjectionLoss.category must be a LossCategory"
            )
        _validate_non_empty_string("ProjectionLoss.reason", self.reason)
        if not isinstance(self.mandatory, bool):
            raise UIIRValidationError("ProjectionLoss.mandatory must be a boolean")
        if not isinstance(self.adaptation_policy, AdaptationPolicy):
            raise UIIRValidationError(
                "ProjectionLoss.adaptation_policy must be an AdaptationPolicy"
            )
        if not isinstance(self.fallback_ref, str):
            raise UIIRValidationError("ProjectionLoss.fallback_ref must be a string")
        if not isinstance(self.budget_kind, str):
            raise UIIRValidationError("ProjectionLoss.budget_kind must be a string")
        if not isinstance(self.severity, LossSeverity):
            raise UIIRValidationError(
                "ProjectionLoss.severity must be a LossSeverity"
            )
        if not isinstance(self.source_ref, str):
            raise UIIRValidationError("ProjectionLoss.source_ref must be a string")
        _require_tuple("ProjectionLoss.details", self.details)
        for index, detail in enumerate(self.details):
            if not isinstance(detail, str):
                raise UIIRValidationError(
                    f"ProjectionLoss.details[{index}] must be a string"
                )
        if self.mandatory and self.semantic_kind not in MANDATORY_SEMANTIC_KINDS:
            # Allow extension kinds only when not claimed mandatory via closed set;
            # callers may mark non-catalogue kinds mandatory for domain policy.
            pass
        if (
            self.mandatory
            and self.category is LossCategory.OMITTED
            and self.adaptation_policy is not AdaptationPolicy.OMIT
        ):
            # Explicit omit of a mandatory semantic is only valid when the
            # declared policy is OMIT *and* the receipt is present — still
            # escalated as unsatisfiable by the solver for core mandatory kinds.
            pass
        if (
            self.category is LossCategory.FALLBACK
            and not self.fallback_ref
            and self.mandatory
        ):
            raise UIIRValidationError(
                f"ProjectionLoss {self.loss_id!r} fallback category for mandatory "
                "semantic requires fallback_ref"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptation_policy": self.adaptation_policy.value,
            "budget_kind": self.budget_kind,
            "category": self.category.value,
            "details": list(self.details),
            "fallback_ref": self.fallback_ref,
            "loss_id": self.loss_id,
            "mandatory": self.mandatory,
            "reason": self.reason,
            "semantic_id": self.semantic_id,
            "semantic_kind": self.semantic_kind,
            "severity": self.severity.value,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True, slots=True)
class ProjectionLossReport:
    """Bound collection of projection loss receipts with deterministic digest."""

    report_id: str
    losses: tuple[ProjectionLoss, ...] = ()
    schema_version: str = UI_PROJECTION_LOSS_SCHEMA_VERSION
    interface: str = UI_PROJECTION_LOSS_INTERFACE

    def validate(self) -> "ProjectionLossReport":
        _validate_identifier("ProjectionLossReport.report_id", self.report_id)
        if self.schema_version != UI_PROJECTION_LOSS_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported projection loss schema_version: {self.schema_version!r}"
            )
        _require_tuple("ProjectionLossReport.losses", self.losses)
        seen: set[str] = set()
        for loss in self.losses:
            if not isinstance(loss, ProjectionLoss):
                raise UIIRValidationError(
                    "ProjectionLossReport.losses members must be ProjectionLoss"
                )
            loss.validate()
            if loss.loss_id in seen:
                raise UIIRValidationError(f"Duplicate loss id: {loss.loss_id}")
            seen.add(loss.loss_id)
        return self

    @property
    def has_unsatisfiable(self) -> bool:
        return any(
            loss.category is LossCategory.UNSATISFIABLE for loss in self.losses
        )

    @property
    def mandatory_losses(self) -> tuple[ProjectionLoss, ...]:
        return tuple(loss for loss in self.losses if loss.mandatory)

    @property
    def total_score(self) -> int:
        return sum(
            loss_score(loss.category, mandatory=loss.mandatory) for loss in self.losses
        )

    def losses_for_kind(self, kind: str) -> tuple[ProjectionLoss, ...]:
        return tuple(loss for loss in self.losses if loss.semantic_kind == kind)

    def digest(self) -> str:
        """Stable content digest of the loss report."""

        payload = self.to_dict()
        text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "losses": [
                item.to_dict()
                for item in sorted(self.losses, key=lambda loss: loss.loss_id)
            ],
            "report_id": self.report_id,
            "schema_version": self.schema_version,
            "total_score": self.total_score,
        }


def make_loss(
    *,
    loss_id: str,
    semantic_id: str,
    semantic_kind: str | MandatorySemanticKind,
    category: LossCategory,
    reason: str,
    mandatory: bool = False,
    adaptation_policy: AdaptationPolicy = AdaptationPolicy.PRESERVE,
    fallback_ref: str = "",
    budget_kind: str = "",
    source_ref: str = "",
    details: Sequence[str] = (),
) -> ProjectionLoss:
    """Construct a validated projection loss receipt."""

    kind = (
        semantic_kind.value
        if isinstance(semantic_kind, MandatorySemanticKind)
        else str(semantic_kind)
    )
    if kind in MANDATORY_SEMANTIC_KINDS:
        mandatory = True
    severity = severity_for_category(category, mandatory=mandatory)
    loss = ProjectionLoss(
        loss_id=loss_id,
        semantic_id=semantic_id,
        semantic_kind=kind,
        category=category,
        reason=reason,
        mandatory=mandatory,
        adaptation_policy=adaptation_policy,
        fallback_ref=fallback_ref,
        budget_kind=budget_kind,
        severity=severity,
        source_ref=source_ref,
        details=tuple(details),
    )
    loss.validate()
    return loss


def build_loss_report(
    report_id: str,
    losses: Sequence[ProjectionLoss],
) -> ProjectionLossReport:
    """Build and validate a deterministic projection loss report."""

    ordered = tuple(sorted(losses, key=lambda loss: loss.loss_id))
    return ProjectionLossReport(report_id=report_id, losses=ordered).validate()


def assert_no_silent_mandatory_omission(
    required_semantic_ids: Mapping[str, str],
    losses: Sequence[ProjectionLoss],
    preserved_ids: Iterable[str],
) -> None:
    """Fail closed if a mandatory semantic has neither preserve nor explicit loss.

    ``required_semantic_ids`` maps semantic_id -> semantic_kind for mandatory items.
    Every mandatory id must appear in ``preserved_ids`` or in ``losses``.
    An ``omitted`` loss for a mandatory core kind without a declared OMIT policy
    is itself treated as a contract violation (must be unsatisfiable instead).
    """

    if not isinstance(required_semantic_ids, Mapping):
        raise UIIRValidationError("required_semantic_ids must be a mapping")
    preserved = set(preserved_ids)
    loss_by_semantic: dict[str, list[ProjectionLoss]] = {}
    for loss in losses:
        if not isinstance(loss, ProjectionLoss):
            raise UIIRValidationError("losses members must be ProjectionLoss")
        loss.validate()
        loss_by_semantic.setdefault(loss.semantic_id, []).append(loss)

    missing: list[str] = []
    illegal_omits: list[str] = []
    for semantic_id, kind in sorted(required_semantic_ids.items()):
        if semantic_id in preserved:
            continue
        related = loss_by_semantic.get(semantic_id, [])
        if not related:
            missing.append(f"{kind}:{semantic_id}")
            continue
        # Must have at least one explicit outcome category.
        if not any(loss.category.value in _EXPLICIT_OUTCOME_CATEGORIES for loss in related):
            missing.append(f"{kind}:{semantic_id}")
            continue
        if kind in MANDATORY_SEMANTIC_KINDS:
            for loss in related:
                if (
                    loss.category is LossCategory.OMITTED
                    and loss.adaptation_policy is not AdaptationPolicy.OMIT
                ):
                    illegal_omits.append(f"{kind}:{semantic_id}")

    if missing:
        raise UIIRValidationError(
            "Silent omission of mandatory semantics is forbidden; missing "
            f"explicit preserve/loss for: {', '.join(missing)}"
        )
    if illegal_omits:
        raise UIIRValidationError(
            "Mandatory semantics cannot be silently omitted; use fallback or "
            f"unsatisfiable instead of omit for: {', '.join(illegal_omits)}"
        )


def categorize_adaptation(policy: AdaptationPolicy) -> LossCategory:
    """Map an adaptation policy to the corresponding loss category."""

    if policy is AdaptationPolicy.PRESERVE:
        return LossCategory.PRESERVED
    if policy is AdaptationPolicy.ADAPT:
        return LossCategory.ADAPTED
    if policy is AdaptationPolicy.SUMMARIZE:
        return LossCategory.SUMMARIZED
    if policy is AdaptationPolicy.FALLBACK:
        return LossCategory.FALLBACK
    if policy is AdaptationPolicy.OMIT:
        return LossCategory.OMITTED
    raise UIIRValidationError(f"Unknown adaptation policy: {policy!r}")


def merge_loss_reports(
    report_id: str,
    reports: Sequence[ProjectionLossReport],
) -> ProjectionLossReport:
    """Merge multiple reports, re-keying by sorted loss_id (deterministic)."""

    combined: list[ProjectionLoss] = []
    seen: set[str] = set()
    for report in reports:
        if not isinstance(report, ProjectionLossReport):
            raise UIIRValidationError(
                "merge_loss_reports expects ProjectionLossReport members"
            )
        report.validate()
        for loss in report.losses:
            if loss.loss_id in seen:
                # Deterministic de-dupe: keep first in report order (already sorted).
                continue
            seen.add(loss.loss_id)
            combined.append(loss)
    return build_loss_report(report_id, combined)


__all__ = [
    "LossCategory",
    "LossSeverity",
    "MANDATORY_SEMANTIC_KINDS",
    "MandatorySemanticKind",
    "ProjectionLoss",
    "ProjectionLossReport",
    "UI_PROJECTION_LOSS_INTERFACE",
    "UI_PROJECTION_LOSS_SCHEMA_VERSION",
    "assert_no_silent_mandatory_omission",
    "build_loss_report",
    "categorize_adaptation",
    "loss_score",
    "make_loss",
    "merge_loss_reports",
    "severity_for_category",
]

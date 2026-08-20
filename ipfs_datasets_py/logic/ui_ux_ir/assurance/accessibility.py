"""Accessibility equivalence validator (``UIAccessibilityValidator@1``).

Checks names, roles, focus order, timing, alternatives, feedback, and
localization coverage. Essential actions/outputs without a viable alternative
produce explicit findings (never silent pass).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping, Sequence

UI_ACCESSIBILITY_VALIDATOR_INTERFACE: Final = "UIAccessibilityValidator@1"
ACCESSIBILITY_SCHEMA_VERSION: Final = "ui-assurance-accessibility/v1"


class FindingSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class AccessibilityFinding:
    finding_id: str
    severity: FindingSeverity
    reason_code: str
    source_id: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "message": self.message,
            "reason_code": self.reason_code,
            "severity": self.severity.value,
            "source_id": self.source_id,
        }


@dataclass(frozen=True, slots=True)
class AccessibilityReport:
    passed: bool
    findings: tuple[AccessibilityFinding, ...]
    interface: str = UI_ACCESSIBILITY_VALIDATOR_INTERFACE
    schema_version: str = ACCESSIBILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "interface": self.interface,
            "passed": self.passed,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class AccessibleAction:
    """Essential action requiring name, role, and alternative path."""

    action_id: str
    accessible_name: str = ""
    role: str = ""
    focusable: bool = True
    alternative_action_ids: tuple[str, ...] = ()
    feedback_message_key: str = ""
    localization_keys: tuple[str, ...] = ()
    essential: bool = True


@dataclass(frozen=True, slots=True)
class AccessibilitySurface:
    """Closed surface description for deterministic checks."""

    surface_id: str
    actions: tuple[AccessibleAction, ...]
    focus_order: tuple[str, ...] = ()
    timing_ms: int | None = None
    max_timing_ms: int = 60_000
    available_locale_keys: frozenset[str] = frozenset()


def validate_accessibility(surface: AccessibilitySurface) -> AccessibilityReport:
    findings: list[AccessibilityFinding] = []
    action_ids = {a.action_id for a in surface.actions}

    for action in surface.actions:
        if not action.essential:
            continue
        if not action.accessible_name.strip():
            findings.append(
                AccessibilityFinding(
                    finding_id=f"a11y-name-{action.action_id}",
                    severity=FindingSeverity.ERROR,
                    reason_code="missing_accessible_name",
                    source_id=action.action_id,
                    message=f"Essential action {action.action_id!r} lacks accessible name",
                )
            )
        if not action.role.strip():
            findings.append(
                AccessibilityFinding(
                    finding_id=f"a11y-role-{action.action_id}",
                    severity=FindingSeverity.ERROR,
                    reason_code="missing_role",
                    source_id=action.action_id,
                    message=f"Essential action {action.action_id!r} lacks role",
                )
            )
        if not action.focusable and not action.alternative_action_ids:
            findings.append(
                AccessibilityFinding(
                    finding_id=f"a11y-alt-{action.action_id}",
                    severity=FindingSeverity.CRITICAL,
                    reason_code="no_viable_alternative",
                    source_id=action.action_id,
                    message=(
                        f"Essential non-focusable action {action.action_id!r} "
                        "has no alternative path"
                    ),
                )
            )
        for alt in action.alternative_action_ids:
            if alt not in action_ids:
                findings.append(
                    AccessibilityFinding(
                        finding_id=f"a11y-alt-missing-{action.action_id}-{alt}",
                        severity=FindingSeverity.ERROR,
                        reason_code="alternative_unresolved",
                        source_id=action.action_id,
                        message=f"Alternative {alt!r} for {action.action_id!r} is unresolved",
                    )
                )
        if not action.feedback_message_key.strip():
            findings.append(
                AccessibilityFinding(
                    finding_id=f"a11y-feedback-{action.action_id}",
                    severity=FindingSeverity.WARNING,
                    reason_code="missing_feedback_key",
                    source_id=action.action_id,
                    message=f"Action {action.action_id!r} missing feedback message key",
                )
            )
        for key in action.localization_keys:
            if key not in surface.available_locale_keys:
                findings.append(
                    AccessibilityFinding(
                        finding_id=f"a11y-i18n-{action.action_id}-{key}",
                        severity=FindingSeverity.ERROR,
                        reason_code="missing_localization",
                        source_id=action.action_id,
                        message=f"Localization key {key!r} unavailable for {action.action_id!r}",
                    )
                )

    # Focus order must include every focusable essential action exactly once order-wise.
    focusable = [a.action_id for a in surface.actions if a.focusable and a.essential]
    if focusable:
        if not surface.focus_order:
            findings.append(
                AccessibilityFinding(
                    finding_id=f"a11y-focus-{surface.surface_id}",
                    severity=FindingSeverity.ERROR,
                    reason_code="missing_focus_order",
                    source_id=surface.surface_id,
                    message="Focusable essential actions require an explicit focus order",
                )
            )
        else:
            missing = [aid for aid in focusable if aid not in surface.focus_order]
            for aid in missing:
                findings.append(
                    AccessibilityFinding(
                        finding_id=f"a11y-focus-miss-{aid}",
                        severity=FindingSeverity.ERROR,
                        reason_code="focus_order_incomplete",
                        source_id=aid,
                        message=f"Focusable action {aid!r} missing from focus_order",
                    )
                )

    if surface.timing_ms is not None and surface.timing_ms > surface.max_timing_ms:
        findings.append(
            AccessibilityFinding(
                finding_id=f"a11y-timing-{surface.surface_id}",
                severity=FindingSeverity.WARNING,
                reason_code="timing_exceeds_bound",
                source_id=surface.surface_id,
                message=(
                    f"Surface timing {surface.timing_ms}ms exceeds bound "
                    f"{surface.max_timing_ms}ms"
                ),
            )
        )

    blocking = {
        FindingSeverity.ERROR,
        FindingSeverity.CRITICAL,
    }
    passed = not any(f.severity in blocking for f in findings)
    return AccessibilityReport(passed=passed, findings=tuple(findings))


class UIAccessibilityValidator:
    """``UIAccessibilityValidator@1``."""

    interface: Final = UI_ACCESSIBILITY_VALIDATOR_INTERFACE

    def validate(self, surface: AccessibilitySurface) -> AccessibilityReport:
        return validate_accessibility(surface)

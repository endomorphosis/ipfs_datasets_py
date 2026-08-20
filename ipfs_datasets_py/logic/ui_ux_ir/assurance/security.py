"""Security / authorization / injection validator (``UISecurityValidator@1``).

Covers expression/import injection, confused deputy, delegation mismatch,
stale/replay, and presentation (hidden/enabled) authorization bypass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping

UI_SECURITY_VALIDATOR_INTERFACE: Final = "UISecurityValidator@1"
SECURITY_SCHEMA_VERSION: Final = "ui-assurance-security/v1"

_INJECTION_PATTERNS: Final = (
    re.compile(r"javascript\s*:", re.I),
    re.compile(r"<\s*script\b", re.I),
    re.compile(r"\beval\s*\(", re.I),
    re.compile(r"\bexec\s*\(", re.I),
    re.compile(r"\$\{"),
    re.compile(r"\{\{"),
    re.compile(r"on\w+\s*=", re.I),
    re.compile(r"__import__"),
    re.compile(r"\bimport\s*\("),
)


class SecuritySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    finding_id: str
    severity: SecuritySeverity
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
class SecurityReport:
    passed: bool
    findings: tuple[SecurityFinding, ...]
    interface: str = UI_SECURITY_VALIDATOR_INTERFACE
    schema_version: str = SECURITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "interface": self.interface,
            "passed": self.passed,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class SecurityContext:
    """Adversarial admission context for one UI interaction candidate."""

    context_id: str
    imported_text: str = ""
    imported_markup: str = ""
    expression: str = ""
    # Presentation is observational — never authority.
    ui_visible: bool = True
    ui_enabled: bool = True
    # Authority fields
    policy_allows: bool = False
    actor_kind: str = "human"  # human | agent | system
    delegation_scope: frozenset[str] = frozenset()
    binding_id: str = ""
    action_id: str = ""
    # Stale / replay
    state_version: int = 0
    expected_state_version: int | None = None
    event_timestamp_ms: int = 0
    latest_timestamp_ms: int = 0
    # Confused deputy: caller claims authority over another actor
    claimed_actor_id: str = ""
    authentic_actor_id: str = ""


def _scan_injection(label: str, text: str, source_id: str) -> list[SecurityFinding]:
    if not text:
        return []
    findings: list[SecurityFinding] = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            findings.append(
                SecurityFinding(
                    finding_id=f"sec-inj-{label}-{source_id}-{pattern.pattern[:12]}",
                    severity=SecuritySeverity.CRITICAL,
                    reason_code="injection_detected",
                    source_id=source_id,
                    message=f"Forbidden executable pattern in {label}: {pattern.pattern!r}",
                )
            )
            break  # one finding per field is enough
    return findings


def validate_security(context: SecurityContext) -> SecurityReport:
    findings: list[SecurityFinding] = []
    sid = context.context_id

    findings.extend(_scan_injection("imported_text", context.imported_text, sid))
    findings.extend(_scan_injection("imported_markup", context.imported_markup, sid))
    findings.extend(_scan_injection("expression", context.expression, sid))

    # Presentation cannot authorize.
    if (context.ui_visible or context.ui_enabled) and not context.policy_allows:
        # Not a finding by itself — only if caller treats UI as grant.
        # We always record that presentation is non-authoritative when deny path.
        pass
    if context.policy_allows is False:
        # Explicit check: UI enabled must not flip allow.
        if context.ui_enabled and context.ui_visible:
            findings.append(
                SecurityFinding(
                    finding_id=f"sec-pres-{sid}",
                    severity=SecuritySeverity.INFO,
                    reason_code="presentation_non_authoritative",
                    source_id=sid,
                    message=(
                        "UI visible/enabled state observed but policy does not allow; "
                        "presentation must not authorize"
                    ),
                )
            )

    # Delegation / agent confused deputy.
    if context.actor_kind == "agent":
        scope = context.delegation_scope
        if not scope:
            findings.append(
                SecurityFinding(
                    finding_id=f"sec-del-empty-{sid}",
                    severity=SecuritySeverity.CRITICAL,
                    reason_code="empty_agent_delegation",
                    source_id=sid,
                    message="Agent actor has empty delegation scope",
                )
            )
        elif context.binding_id and context.binding_id not in scope and (
            not context.action_id or context.action_id not in scope
        ):
            findings.append(
                SecurityFinding(
                    finding_id=f"sec-del-miss-{sid}",
                    severity=SecuritySeverity.CRITICAL,
                    reason_code="delegation_mismatch",
                    source_id=context.binding_id or context.action_id,
                    message="Agent delegation does not include binding/action",
                )
            )

    if (
        context.claimed_actor_id
        and context.authentic_actor_id
        and context.claimed_actor_id != context.authentic_actor_id
    ):
        findings.append(
            SecurityFinding(
                finding_id=f"sec-deputy-{sid}",
                severity=SecuritySeverity.CRITICAL,
                reason_code="confused_deputy",
                source_id=context.claimed_actor_id,
                message=(
                    f"Claimed actor {context.claimed_actor_id!r} does not match "
                    f"authentic {context.authentic_actor_id!r}"
                ),
            )
        )

    # Stale / replay fences.
    if (
        context.expected_state_version is not None
        and context.expected_state_version != context.state_version
    ):
        findings.append(
            SecurityFinding(
                finding_id=f"sec-stale-ver-{sid}",
                severity=SecuritySeverity.ERROR,
                reason_code="stale_state_version",
                source_id=sid,
                message=(
                    f"expected_state_version {context.expected_state_version} != "
                    f"state_version {context.state_version}"
                ),
            )
        )
    if (
        context.latest_timestamp_ms > 0
        and context.event_timestamp_ms < context.latest_timestamp_ms
    ):
        findings.append(
            SecurityFinding(
                finding_id=f"sec-stale-ts-{sid}",
                severity=SecuritySeverity.ERROR,
                reason_code="stale_timestamp",
                source_id=sid,
                message="Event timestamp is older than latest observed timestamp",
            )
        )

    # Hidden/enabled cannot grant when policy denies (adversarial assertion).
    if not context.policy_allows:
        expr_l = context.expression.lower()
        text_l = context.imported_text.lower()
        if "grant" in expr_l or ("allow" in text_l and "policy" in text_l):
            findings.append(
                SecurityFinding(
                    finding_id=f"sec-bypass-{sid}",
                    severity=SecuritySeverity.CRITICAL,
                    reason_code="presentation_authorization_bypass_attempt",
                    source_id=sid,
                    message="Import/expression attempts to assert policy grant without authority",
                )
            )

    blocking = {SecuritySeverity.ERROR, SecuritySeverity.CRITICAL}
    passed = not any(f.severity in blocking for f in findings)
    return SecurityReport(passed=passed, findings=tuple(findings))


class UISecurityValidator:
    """``UISecurityValidator@1``."""

    interface: Final = UI_SECURITY_VALIDATOR_INTERFACE

    def validate(self, context: SecurityContext) -> SecurityReport:
        return validate_security(context)

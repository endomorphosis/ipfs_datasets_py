"""Privacy / consent / minimization validator (``UIPrivacyValidator@1``)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping

UI_PRIVACY_VALIDATOR_INTERFACE: Final = "UIPrivacyValidator@1"
PRIVACY_SCHEMA_VERSION: Final = "ui-assurance-privacy/v1"

# Material that must never appear in UI/UX IR payloads or observational streams.
_FORBIDDEN_SENSOR_KEYS: Final = frozenset(
    {
        "raw_emg",
        "continuous_neural",
        "raw_biometric",
        "raw_eeg",
        "fingerprint_template",
        "iris_template",
        "face_embedding_raw",
        "password",
        "private_key",
        "secret",
        "authorization",
        "token",
    }
)


class PrivacySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class PrivacyFinding:
    finding_id: str
    severity: PrivacySeverity
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
class PrivacyReport:
    passed: bool
    findings: tuple[PrivacyFinding, ...]
    interface: str = UI_PRIVACY_VALIDATOR_INTERFACE
    schema_version: str = PRIVACY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "interface": self.interface,
            "passed": self.passed,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class PrivacyContext:
    """Purpose-bound privacy admission envelope."""

    context_id: str
    purpose: str
    consent_granted: bool
    retention_days: int
    max_retention_days: int = 365
    payload_keys: frozenset[str] = frozenset()
    sensitive_outputs: frozenset[str] = frozenset()
    allowed_sensitive_outputs: frozenset[str] = frozenset()
    minimization_ok: bool = True


def validate_privacy(context: PrivacyContext) -> PrivacyReport:
    findings: list[PrivacyFinding] = []

    if not context.purpose.strip():
        findings.append(
            PrivacyFinding(
                finding_id=f"priv-purpose-{context.context_id}",
                severity=PrivacySeverity.CRITICAL,
                reason_code="missing_purpose",
                source_id=context.context_id,
                message="Purpose binding is required",
            )
        )
    if not context.consent_granted:
        findings.append(
            PrivacyFinding(
                finding_id=f"priv-consent-{context.context_id}",
                severity=PrivacySeverity.CRITICAL,
                reason_code="consent_missing",
                source_id=context.context_id,
                message="Consent is not granted for this purpose-bound context",
            )
        )
    if context.retention_days < 0:
        findings.append(
            PrivacyFinding(
                finding_id=f"priv-ret-neg-{context.context_id}",
                severity=PrivacySeverity.ERROR,
                reason_code="invalid_retention",
                source_id=context.context_id,
                message="retention_days must be non-negative",
            )
        )
    elif context.retention_days > context.max_retention_days:
        findings.append(
            PrivacyFinding(
                finding_id=f"priv-ret-{context.context_id}",
                severity=PrivacySeverity.ERROR,
                reason_code="retention_exceeds_bound",
                source_id=context.context_id,
                message=(
                    f"retention_days {context.retention_days} exceeds "
                    f"max {context.max_retention_days}"
                ),
            )
        )
    if not context.minimization_ok:
        findings.append(
            PrivacyFinding(
                finding_id=f"priv-min-{context.context_id}",
                severity=PrivacySeverity.ERROR,
                reason_code="minimization_failed",
                source_id=context.context_id,
                message="Data minimization check failed",
            )
        )

    lowered = {k.lower() for k in context.payload_keys}
    bad = lowered & _FORBIDDEN_SENSOR_KEYS
    for key in sorted(bad):
        findings.append(
            PrivacyFinding(
                finding_id=f"priv-sensor-{key}",
                severity=PrivacySeverity.CRITICAL,
                reason_code="forbidden_sensor_material",
                source_id=context.context_id,
                message=f"Forbidden sensor/biometric/secret key present: {key}",
            )
        )

    for out in sorted(context.sensitive_outputs - context.allowed_sensitive_outputs):
        findings.append(
            PrivacyFinding(
                finding_id=f"priv-out-{out}",
                severity=PrivacySeverity.ERROR,
                reason_code="unauthorized_sensitive_output",
                source_id=out,
                message=f"Sensitive output {out!r} is not purpose-allowed",
            )
        )

    blocking = {PrivacySeverity.ERROR, PrivacySeverity.CRITICAL}
    passed = not any(f.severity in blocking for f in findings)
    return PrivacyReport(passed=passed, findings=tuple(findings))


class UIPrivacyValidator:
    """``UIPrivacyValidator@1``."""

    interface: Final = UI_PRIVACY_VALIDATOR_INTERFACE

    def validate(self, context: PrivacyContext) -> PrivacyReport:
        return validate_privacy(context)

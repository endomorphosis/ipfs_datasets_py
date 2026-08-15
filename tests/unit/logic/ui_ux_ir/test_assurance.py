"""UIR-060: accessibility, privacy, and security assurance validators."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir.assurance.accessibility import (
    AccessibleAction,
    AccessibilitySurface,
    FindingSeverity,
    UIAccessibilityValidator,
    UI_ACCESSIBILITY_VALIDATOR_INTERFACE,
    validate_accessibility,
)
from ipfs_datasets_py.logic.ui_ux_ir.assurance.privacy import (
    PrivacyContext,
    PrivacySeverity,
    UIPrivacyValidator,
    UI_PRIVACY_VALIDATOR_INTERFACE,
    validate_privacy,
)
from ipfs_datasets_py.logic.ui_ux_ir.assurance.security import (
    SecurityContext,
    SecuritySeverity,
    UISecurityValidator,
    UI_SECURITY_VALIDATOR_INTERFACE,
    validate_security,
)


def test_interface_identities() -> None:
    assert UI_ACCESSIBILITY_VALIDATOR_INTERFACE == "UIAccessibilityValidator@1"
    assert UI_PRIVACY_VALIDATOR_INTERFACE == "UIPrivacyValidator@1"
    assert UI_SECURITY_VALIDATOR_INTERFACE == "UISecurityValidator@1"
    assert UIAccessibilityValidator().interface == UI_ACCESSIBILITY_VALIDATOR_INTERFACE
    assert UIPrivacyValidator().interface == UI_PRIVACY_VALIDATOR_INTERFACE
    assert UISecurityValidator().interface == UI_SECURITY_VALIDATOR_INTERFACE


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------


def test_accessibility_equivalence_pass() -> None:
    surface = AccessibilitySurface(
        surface_id="surf:main",
        actions=(
            AccessibleAction(
                action_id="action:submit",
                accessible_name="Submit form",
                role="button",
                focusable=True,
                feedback_message_key="ui.feedback.submit",
                localization_keys=("ui.feedback.submit",),
            ),
            AccessibleAction(
                action_id="action:voice-submit",
                accessible_name="Submit by voice",
                role="button",
                focusable=False,
                alternative_action_ids=("action:submit",),
                feedback_message_key="ui.feedback.submit",
                localization_keys=("ui.feedback.submit",),
            ),
        ),
        focus_order=("action:submit",),
        available_locale_keys=frozenset({"ui.feedback.submit"}),
        timing_ms=100,
    )
    report = validate_accessibility(surface)
    assert report.passed is True
    assert report.interface == UI_ACCESSIBILITY_VALIDATOR_INTERFACE


def test_accessibility_missing_name_and_alternative() -> None:
    surface = AccessibilitySurface(
        surface_id="surf:bad",
        actions=(
            AccessibleAction(
                action_id="action:hidden",
                accessible_name="",
                role="",
                focusable=False,
                alternative_action_ids=(),
            ),
        ),
        focus_order=(),
    )
    report = validate_accessibility(surface)
    assert report.passed is False
    codes = {f.reason_code for f in report.findings}
    assert "missing_accessible_name" in codes
    assert "missing_role" in codes
    assert "no_viable_alternative" in codes
    assert any(f.severity is FindingSeverity.CRITICAL for f in report.findings)


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def test_privacy_purpose_consent_retention() -> None:
    ok = validate_privacy(
        PrivacyContext(
            context_id="ctx:ok",
            purpose="ui.interaction.mediation",
            consent_granted=True,
            retention_days=30,
            max_retention_days=90,
            payload_keys=frozenset({"event_id", "capability_id"}),
            minimization_ok=True,
        )
    )
    assert ok.passed is True

    bad = validate_privacy(
        PrivacyContext(
            context_id="ctx:bad",
            purpose="",
            consent_granted=False,
            retention_days=999,
            max_retention_days=30,
            payload_keys=frozenset({"raw_emg", "event_id"}),
            sensitive_outputs=frozenset({"ssn"}),
            allowed_sensitive_outputs=frozenset(),
            minimization_ok=False,
        )
    )
    assert bad.passed is False
    codes = {f.reason_code for f in bad.findings}
    assert "missing_purpose" in codes
    assert "consent_missing" in codes
    assert "retention_exceeds_bound" in codes
    assert "forbidden_sensor_material" in codes
    assert "unauthorized_sensitive_output" in codes
    assert "minimization_failed" in codes
    assert any(f.severity is PrivacySeverity.CRITICAL for f in bad.findings)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


def test_security_injection_and_presentation_non_authority() -> None:
    report = validate_security(
        SecurityContext(
            context_id="sec:inj",
            imported_markup="<script>alert(1)</script>",
            expression="eval(user)",
            ui_visible=True,
            ui_enabled=True,
            policy_allows=False,
        )
    )
    assert report.passed is False
    codes = {f.reason_code for f in report.findings}
    assert "injection_detected" in codes
    assert "presentation_non_authoritative" in codes


def test_security_delegation_confused_deputy_stale() -> None:
    report = validate_security(
        SecurityContext(
            context_id="sec:agent",
            actor_kind="agent",
            delegation_scope=frozenset({"binding:other"}),
            binding_id="binding:submit",
            action_id="action:submit",
            claimed_actor_id="actor:victim",
            authentic_actor_id="actor:attacker",
            state_version=5,
            expected_state_version=3,
            event_timestamp_ms=10,
            latest_timestamp_ms=100,
            policy_allows=False,
        )
    )
    assert report.passed is False
    codes = {f.reason_code for f in report.findings}
    assert "delegation_mismatch" in codes
    assert "confused_deputy" in codes
    assert "stale_state_version" in codes
    assert "stale_timestamp" in codes
    assert any(f.severity is SecuritySeverity.CRITICAL for f in report.findings)


def test_security_clean_allow_path() -> None:
    report = validate_security(
        SecurityContext(
            context_id="sec:ok",
            imported_text="Submit the form",
            expression="fact:ready",
            ui_visible=True,
            ui_enabled=True,
            policy_allows=True,
            actor_kind="human",
            state_version=1,
            expected_state_version=1,
            event_timestamp_ms=200,
            latest_timestamp_ms=100,
        )
    )
    assert report.passed is True
    assert report.interface == UI_SECURITY_VALIDATOR_INTERFACE


def test_stable_finding_ids_and_serialization() -> None:
    report = UISecurityValidator().validate(
        SecurityContext(
            context_id="sec:ser",
            imported_text="javascript:alert(1)",
            policy_allows=False,
        )
    )
    payload = report.to_dict()
    assert payload["interface"] == "UISecurityValidator@1"
    assert all(f["finding_id"] and f["reason_code"] and f["source_id"] for f in payload["findings"])

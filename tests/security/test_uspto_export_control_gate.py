"""Export-control and secrecy-order gate tests for USPTO public sinks.

PATLAW-071 — unknown publication/export state quarantines; secrecy-order and
restricted export-review material is denied until human clearance and
reclassification; tests inspect quarantine records, audit events, and sink
captures rather than return codes alone.
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PrivacyBoundaryError,
    UsptoPrivacyPolicy,
)
from ipfs_datasets_py.processors.domains.uspto.privacy_sinks import (
    EnforcementDecisionCode,
    ExportControlGate,
    ExportControlState,
    PublicationState,
    PublicSinkEnforcer,
    SinkChannel,
    SinkDispatchRequest,
    TenantPolicy,
    all_sink_channels,
    payload_contains_canary,
)

PRIVATE_TEXT_CANARY = "export-control canary unpublished-spec-text-e4b1"
PRIVATE_CID_CANARY = "bafyexportcontrolprivatecid0000000000000000000000000002"
PRIVATE_BYTES_CANARY = b"%PDF-EXPORT-CONTROL-PRIVATE-SYNTHETIC%"
PRIVATE_EMBEDDING_CANARY = [0.111, 0.222, 0.888421]
EMBEDDING_MARKER = "0.888421"

CANARIES = (
    PRIVATE_TEXT_CANARY,
    PRIVATE_CID_CANARY,
    PRIVATE_BYTES_CANARY,
    EMBEDDING_MARKER,
)


@pytest.fixture
def gate() -> ExportControlGate:
    return ExportControlGate()


@pytest.fixture
def enforcer() -> PublicSinkEnforcer:
    return PublicSinkEnforcer(
        tenant_policy=TenantPolicy(tenant_id="tenant-export-a")
    )


def _assert_no_canaries(surface: str) -> None:
    found = payload_contains_canary(surface, CANARIES)
    assert found == [], f"export-control canaries leaked: {found!r}"


# ---------------------------------------------------------------------------
# Unknown publication / export state → quarantine
# ---------------------------------------------------------------------------


def test_unknown_publication_state_quarantines(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        publication_state=PublicationState.UNKNOWN,
        export_control_state=ExportControlState.CLEARED,
    )
    assert decision.allowed is False
    assert decision.quarantined is True
    assert decision.code is EnforcementDecisionCode.DENIED_UNKNOWN_PUBLICATION
    assert decision.requires_human_clearance is True
    assert gate.must_quarantine(
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        publication_state=PublicationState.UNKNOWN,
        export_control_state=ExportControlState.CLEARED,
    )


def test_unknown_export_control_state_quarantines(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        publication_state=PublicationState.PUBLIC,
        export_control_state=ExportControlState.UNKNOWN,
    )
    assert decision.allowed is False
    assert decision.quarantined is True
    assert decision.code is EnforcementDecisionCode.DENIED_UNKNOWN_EXPORT_STATE


def test_both_unknown_states_quarantine(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        publication_state=None,
        export_control_state=None,
    )
    assert decision.allowed is False
    assert decision.quarantined is True
    assert decision.publication_state is PublicationState.UNKNOWN
    assert decision.export_control_state is ExportControlState.UNKNOWN


def test_unrecognized_state_labels_coerce_to_unknown_and_quarantine(
    gate: ExportControlGate,
) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        publication_state="not-a-real-publication-state",
        export_control_state="not-a-real-export-state",
    )
    assert decision.allowed is False
    assert decision.quarantined is True
    assert decision.publication_state is PublicationState.UNKNOWN
    assert decision.export_control_state is ExportControlState.UNKNOWN


def test_quarantine_record_has_reason_codes_not_private_content(
    gate: ExportControlGate,
) -> None:
    record = gate.quarantine(
        quarantine_id="q:export:1",
        classification=DisclosureClassification.UNKNOWN,
        publication_state=PublicationState.UNKNOWN,
        export_control_state=ExportControlState.UNKNOWN,
        related_artifact_ids=("artifact:export:1",),
        content_kinds=(ContentKind.EXTRACTED_TEXT, ContentKind.DOCUMENT_BYTES),
    )
    assert record.quarantine_id == "q:export:1"
    assert record.classification is DisclosureClassification.UNKNOWN
    assert record.reason_codes
    blob = json.dumps(record.to_dict(), sort_keys=True)
    _assert_no_canaries(blob)
    assert "artifact:export:1" in record.related_artifact_ids


# ---------------------------------------------------------------------------
# Secrecy order (35 USC 181–188)
# ---------------------------------------------------------------------------


def test_secrecy_order_publication_denied(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        publication_state=PublicationState.SECRECY_ORDER,
        export_control_state=ExportControlState.CLEARED,
    )
    assert decision.allowed is False
    assert decision.code is EnforcementDecisionCode.DENIED_SECRECY_ORDER
    assert decision.requires_human_clearance is True
    assert decision.quarantined is False


def test_secrecy_order_export_state_denied(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        publication_state=PublicationState.PUBLIC,
        export_control_state=ExportControlState.SECRECY_ORDER,
    )
    assert decision.allowed is False
    assert decision.code is EnforcementDecisionCode.DENIED_SECRECY_ORDER


def test_secrecy_order_indicator_forces_denial(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        publication_state=PublicationState.PUBLIC,
        export_control_state=ExportControlState.CLEARED,
        secrecy_order_indicator=True,
    )
    assert decision.allowed is False
    assert decision.code is EnforcementDecisionCode.DENIED_SECRECY_ORDER
    assert decision.publication_state is PublicationState.SECRECY_ORDER
    assert decision.export_control_state is ExportControlState.SECRECY_ORDER


def test_secrecy_order_blocks_all_public_channels(
    enforcer: PublicSinkEnforcer,
) -> None:
    for channel in all_sink_channels():
        result = enforcer.dispatch(
            SinkDispatchRequest(
                tenant_id="tenant-export-a",
                classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
                channel=channel,
                content_kind=ContentKind.EXTRACTED_TEXT,
                publication_state=PublicationState.PUBLIC,
                export_control_state=ExportControlState.CLEARED,
                secrecy_order_indicator=True,
                payload=PRIVATE_TEXT_CANARY,
                digest="d" * 64,
                artifact_id="artifact:secrecy:1",
            )
        )
        assert result.allowed is False
        assert result.code is EnforcementDecisionCode.DENIED_SECRECY_ORDER
        assert enforcer.channel_payloads(channel) == ()

    surface = enforcer.all_captured_surface_text()
    _assert_no_canaries(surface)
    # Telemetry/errors must show denial codes without private text.
    assert enforcer.telemetry
    assert all(ev.get("allowed") is False for ev in enforcer.telemetry)
    tel = json.dumps([dict(e) for e in enforcer.telemetry], default=str)
    assert PRIVATE_TEXT_CANARY not in tel
    assert any(
        e.get("code") == EnforcementDecisionCode.DENIED_SECRECY_ORDER.value
        for e in enforcer.error_surfaces
    )


# ---------------------------------------------------------------------------
# Restricted export review
# ---------------------------------------------------------------------------


def test_restricted_export_review_classification_denied(
    gate: ExportControlGate,
) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
        publication_state=PublicationState.EXPORT_REVIEW_PENDING,
        export_control_state=ExportControlState.PENDING_REVIEW,
    )
    assert decision.allowed is False
    assert decision.code is EnforcementDecisionCode.DENIED_EXPORT_CONTROL
    assert decision.requires_human_clearance is True


def test_restricted_export_review_not_cleared_by_public_flags_alone(
    gate: ExportControlGate,
) -> None:
    """Even CLEARED + PUBLIC cannot admit restricted_export_review class."""
    decision = gate.evaluate(
        classification=DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
        publication_state=PublicationState.PUBLIC,
        export_control_state=ExportControlState.CLEARED,
    )
    assert decision.allowed is False
    assert decision.code is EnforcementDecisionCode.DENIED_EXPORT_CONTROL
    assert decision.requires_human_clearance is True


def test_export_review_pending_publication_denied(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        publication_state=PublicationState.EXPORT_REVIEW_PENDING,
        export_control_state=ExportControlState.CLEARED,
    )
    assert decision.allowed is False
    assert decision.code is EnforcementDecisionCode.DENIED_EXPORT_CONTROL


def test_restricted_and_pending_export_states_denied(
    gate: ExportControlGate,
) -> None:
    for state in (
        ExportControlState.RESTRICTED,
        ExportControlState.PENDING_REVIEW,
    ):
        decision = gate.evaluate(
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            publication_state=PublicationState.PUBLIC,
            export_control_state=state,
        )
        assert decision.allowed is False
        assert decision.code is EnforcementDecisionCode.DENIED_EXPORT_CONTROL
        assert decision.requires_human_clearance is True


def test_export_review_material_denied_from_all_sinks_with_surface_inspection(
    enforcer: PublicSinkEnforcer,
) -> None:
    payloads = {
        ContentKind.DOCUMENT_BYTES: PRIVATE_BYTES_CANARY,
        ContentKind.EXTRACTED_TEXT: PRIVATE_TEXT_CANARY,
        ContentKind.EMBEDDING: PRIVATE_EMBEDDING_CANARY,
        ContentKind.CONTENT_IDENTIFIER: PRIVATE_CID_CANARY,
    }
    for channel in all_sink_channels():
        for kind, payload in payloads.items():
            result = enforcer.dispatch(
                SinkDispatchRequest(
                    tenant_id="tenant-export-a",
                    classification=DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
                    channel=channel,
                    content_kind=kind,
                    publication_state=PublicationState.EXPORT_REVIEW_PENDING,
                    export_control_state=ExportControlState.RESTRICTED,
                    payload=payload,
                    digest="e" * 64,
                    artifact_id="artifact:export-review:1",
                )
            )
            assert result.allowed is False
            assert result.code in {
                EnforcementDecisionCode.DENIED_EXPORT_CONTROL,
                EnforcementDecisionCode.DENIED_UNKNOWN_EXPORT_STATE,
            }

    assert enforcer.admitted == ()
    surface = enforcer.all_captured_surface_text()
    _assert_no_canaries(surface)
    for channel in all_sink_channels():
        assert enforcer.channel_payloads(channel) == ()

    # Audit events carry codes, not substance.
    for event in enforcer.audit_log:
        rendered = json.dumps(dict(event), default=str)
        _assert_no_canaries(rendered)
        assert event.get("code")


# ---------------------------------------------------------------------------
# Private unpublished and private classification
# ---------------------------------------------------------------------------


def test_private_unpublished_fails_export_gate(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        publication_state=PublicationState.PRIVATE_UNPUBLISHED,
        export_control_state=ExportControlState.CLEARED,
    )
    assert decision.allowed is False
    assert decision.code is EnforcementDecisionCode.DENIED_PRIVATE


def test_cleared_public_official_passes_export_gate(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        publication_state=PublicationState.PUBLIC,
        export_control_state=ExportControlState.CLEARED,
    )
    assert decision.allowed is True
    assert decision.code is EnforcementDecisionCode.ALLOWED
    assert decision.quarantined is False
    assert decision.requires_human_clearance is False


def test_cleared_public_user_passes_export_gate(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PUBLIC_USER,
        publication_state=PublicationState.PUBLIC,
        export_control_state=ExportControlState.CLEARED,
    )
    assert decision.allowed is True


def test_privileged_work_product_never_passes_export_gate(
    gate: ExportControlGate,
) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        publication_state=PublicationState.PUBLIC,
        export_control_state=ExportControlState.CLEARED,
    )
    assert decision.allowed is False
    assert decision.code is EnforcementDecisionCode.DENIED_PRIVATE


# ---------------------------------------------------------------------------
# Integration: export gate + sink enforcer
# ---------------------------------------------------------------------------


def test_unknown_export_state_blocks_dispatch_and_quarantines_observability(
    enforcer: PublicSinkEnforcer,
) -> None:
    result = enforcer.dispatch(
        SinkDispatchRequest(
            tenant_id="tenant-export-a",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            channel=SinkChannel.PUBLIC_IPFS_GATEWAY,
            content_kind=ContentKind.CONTENT_IDENTIFIER,
            publication_state=PublicationState.PUBLIC,
            export_control_state=ExportControlState.UNKNOWN,
            payload=PRIVATE_CID_CANARY,
            digest="f" * 64,
        )
    )
    assert result.allowed is False
    assert result.quarantined is True
    assert result.code is EnforcementDecisionCode.DENIED_UNKNOWN_EXPORT_STATE
    assert enforcer.channel_payloads(SinkChannel.PUBLIC_IPFS_GATEWAY) == ()
    surface = enforcer.all_captured_surface_text()
    assert PRIVATE_CID_CANARY not in surface
    assert any(ev.get("quarantined") is True for ev in enforcer.audit_log)


def test_mixed_sources_with_export_review_inherit_restriction(
    enforcer: PublicSinkEnforcer,
) -> None:
    result = enforcer.dispatch(
        SinkDispatchRequest(
            tenant_id="tenant-export-a",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            channel=SinkChannel.JUSTICE_DAO,
            content_kind=ContentKind.DOCUMENT_BYTES,
            publication_state=PublicationState.PUBLIC,
            export_control_state=ExportControlState.CLEARED,
            source_classifications=(
                DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
            ),
            payload=PRIVATE_BYTES_CANARY,
            digest="1" * 64,
        )
    )
    assert result.allowed is False
    assert (
        result.classification is DisclosureClassification.RESTRICTED_EXPORT_REVIEW
    )
    assert enforcer.channel_payloads(SinkChannel.JUSTICE_DAO) == ()
    _assert_no_canaries(enforcer.all_captured_surface_text())


def test_assert_dispatch_export_denial_audit_safe(
    enforcer: PublicSinkEnforcer,
) -> None:
    with pytest.raises(PrivacyBoundaryError) as caught:
        enforcer.assert_dispatch_allowed(
            SinkDispatchRequest(
                tenant_id="tenant-export-a",
                classification=DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
                channel=SinkChannel.REMOTE_MODEL,
                content_kind=ContentKind.EXTRACTED_TEXT,
                publication_state=PublicationState.EXPORT_REVIEW_PENDING,
                export_control_state=ExportControlState.PENDING_REVIEW,
                payload=PRIVATE_TEXT_CANARY,
            )
        )
    err = caught.value
    rendered = f"{err!s}\n{err!r}\n{json.dumps(err.audit_dict())}"
    assert PRIVATE_TEXT_CANARY not in rendered
    assert err.code == EnforcementDecisionCode.DENIED_EXPORT_CONTROL.value


def test_export_gate_decision_to_dict_is_json_safe(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
        publication_state=PublicationState.EXPORT_REVIEW_PENDING,
        export_control_state=ExportControlState.RESTRICTED,
    )
    blob = json.dumps(decision.to_dict(), sort_keys=True)
    parsed = json.loads(blob)
    assert parsed["allowed"] is False
    assert parsed["requires_human_clearance"] is True
    assert "classification" in parsed


def test_public_cleared_metadata_admits_to_dataset_not_credentials(
    enforcer: PublicSinkEnforcer,
) -> None:
    ok = enforcer.dispatch(
        SinkDispatchRequest(
            tenant_id="tenant-export-a",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            channel=SinkChannel.PUBLIC_DATASET,
            content_kind=ContentKind.METADATA_DIGEST,
            publication_state=PublicationState.PUBLIC,
            export_control_state=ExportControlState.CLEARED,
            payload={"sha256": "2" * 64, "doc_type": "grant"},
            digest="2" * 64,
        )
    )
    assert ok.allowed is True

    denied = enforcer.dispatch(
        SinkDispatchRequest(
            tenant_id="tenant-export-a",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            channel=SinkChannel.PUBLIC_DATASET,
            content_kind=ContentKind.CREDENTIAL_SECRET,
            publication_state=PublicationState.PUBLIC,
            export_control_state=ExportControlState.CLEARED,
            payload="not-a-real-secret",
            digest="3" * 64,
        )
    )
    assert denied.allowed is False
    # Admitted public metadata must not include export canaries.
    _assert_no_canaries(enforcer.all_captured_surface_text())


def test_gate_uses_policy_classify_before_dispatch(gate: ExportControlGate) -> None:
    decision = gate.evaluate(
        classification=DisclosureClassification.PUBLIC_USER,
        publication_state=PublicationState.PUBLIC,
        export_control_state=ExportControlState.CLEARED,
        source_classifications=(
            DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        ),
    )
    assert decision.allowed is False
    assert decision.classification is DisclosureClassification.PRIVILEGED_WORK_PRODUCT


def test_default_privacy_policy_denies_external_models() -> None:
    policy = UsptoPrivacyPolicy()
    assert policy.allow_external_models_for_private is False
    eng = PublicSinkEnforcer(policy=policy)
    assert eng._allow_external_models is False  # noqa: SLF001 — default contract

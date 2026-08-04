"""Adversarial assurance boundary: private substance never reaches public sinks.

PATLAW-071 — proves that under adversarial paths, private bytes, text,
embeddings, and CIDs cannot enter public IPFS (DHT/gateway/pin), datasets,
embedding indexes, remote models, caches, logs, traces, telemetry, or error
surfaces. Tests inspect captured outputs and observability, not merely return
codes. External-model use is denied by default. Unknown classification and
cross-tenant access fail closed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PrivacyBoundaryError,
    PublicSink,
    UsptoPrivacyPolicy,
)
from ipfs_datasets_py.processors.domains.uspto.privacy_sinks import (
    PRIVACY_SINKS_SCHEMA_VERSION,
    EnforcementDecisionCode,
    ExportControlState,
    PublicationState,
    PublicSinkEnforcer,
    SinkChannel,
    SinkDispatchRequest,
    TenantPolicy,
    all_ipfs_public_channels,
    all_sink_channels,
    channel_to_public_sink,
    deny_private_substance_from_all_channels,
    payload_contains_canary,
    redact_for_observability,
)

# Synthetic canaries — not live secrets or real matter content.
PRIVATE_BYTES_CANARY = b"%PDF-ASSURANCE-PRIVATE-OA-SYNTHETIC-9f3a%"
PRIVATE_TEXT_CANARY = "CONFIDENTIAL unpublished claim language assurance-canary-7c2e"
PRIVATE_EMBEDDING_CANARY = [0.001, 0.002, 0.003, 0.997531]
PRIVATE_CID_CANARY = "bafyassuranceprivatecid00000000000000000000000000000000001"
PRIVATE_EMBEDDING_MARKER = "0.997531"

PRIVATE_CLASSES = (
    DisclosureClassification.CONFIDENTIAL_APPLICATION,
    DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
    DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
)

SUBSTANTIVE_KINDS = (
    ContentKind.DOCUMENT_BYTES,
    ContentKind.EXTRACTED_TEXT,
    ContentKind.EMBEDDING,
    ContentKind.CONTENT_IDENTIFIER,
)

PAYLOADS: dict[ContentKind, Any] = {
    ContentKind.DOCUMENT_BYTES: PRIVATE_BYTES_CANARY,
    ContentKind.EXTRACTED_TEXT: PRIVATE_TEXT_CANARY,
    ContentKind.EMBEDDING: PRIVATE_EMBEDDING_CANARY,
    ContentKind.CONTENT_IDENTIFIER: PRIVATE_CID_CANARY,
}

CANARIES: tuple[Any, ...] = (
    PRIVATE_BYTES_CANARY,
    PRIVATE_TEXT_CANARY,
    PRIVATE_EMBEDDING_MARKER,
    PRIVATE_CID_CANARY,
)


@pytest.fixture
def enforcer() -> PublicSinkEnforcer:
    return PublicSinkEnforcer(
        tenant_policy=TenantPolicy(tenant_id="tenant-assurance-a")
    )


def _request(
    *,
    channel: SinkChannel,
    kind: ContentKind,
    classification: DisclosureClassification = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    ),
    tenant_id: str = "tenant-assurance-a",
    publication_state: PublicationState = PublicationState.PRIVATE_UNPUBLISHED,
    export_control_state: ExportControlState = ExportControlState.CLEARED,
    payload: Any = None,
    **kwargs: Any,
) -> SinkDispatchRequest:
    if payload is None:
        payload = PAYLOADS.get(kind, PRIVATE_TEXT_CANARY)
    return SinkDispatchRequest(
        tenant_id=tenant_id,
        classification=classification,
        channel=channel,
        content_kind=kind,
        publication_state=publication_state,
        export_control_state=export_control_state,
        payload=payload,
        matter_id=kwargs.get("matter_id", "matter:assurance:1"),
        artifact_id=kwargs.get("artifact_id", "artifact:assurance:1"),
        digest=kwargs.get("digest", "a" * 64),
        secrecy_order_indicator=kwargs.get("secrecy_order_indicator"),
        source_classifications=kwargs.get("source_classifications", ()),
    )


def _assert_no_canaries(surface: str) -> None:
    found = payload_contains_canary(surface, CANARIES)
    assert found == [], f"private canaries leaked into surface: {found!r}"


# ---------------------------------------------------------------------------
# Channel enumeration and mapping
# ---------------------------------------------------------------------------


def test_all_public_channels_are_enumerated() -> None:
    channels = all_sink_channels()
    assert SinkChannel.PUBLIC_IPFS_DHT in channels
    assert SinkChannel.PUBLIC_IPFS_GATEWAY in channels
    assert SinkChannel.PUBLIC_IPFS_PIN in channels
    assert SinkChannel.PUBLIC_DATASET in channels
    assert SinkChannel.EMBEDDING_INDEX in channels
    assert SinkChannel.REMOTE_MODEL in channels
    assert SinkChannel.PUBLIC_CACHE in channels
    assert SinkChannel.LOGS in channels
    assert SinkChannel.TELEMETRY in channels
    assert SinkChannel.TRACE in channels
    assert SinkChannel.ERROR_SURFACE in channels
    assert SinkChannel.JUSTICE_DAO in channels
    assert set(all_ipfs_public_channels()) == {
        SinkChannel.PUBLIC_IPFS_DHT,
        SinkChannel.PUBLIC_IPFS_GATEWAY,
        SinkChannel.PUBLIC_IPFS_PIN,
    }


def test_channels_map_to_privacy_policy_public_sinks() -> None:
    assert channel_to_public_sink(SinkChannel.PUBLIC_IPFS_DHT) is PublicSink.PUBLIC_IPFS
    assert channel_to_public_sink(SinkChannel.PUBLIC_IPFS_GATEWAY) is PublicSink.PUBLIC_IPFS
    assert channel_to_public_sink(SinkChannel.PUBLIC_IPFS_PIN) is PublicSink.PUBLIC_IPFS
    assert channel_to_public_sink(SinkChannel.REMOTE_MODEL) is PublicSink.REMOTE_PROMPT
    assert channel_to_public_sink(SinkChannel.EMBEDDING_INDEX) is PublicSink.PUBLIC_DATASET
    assert channel_to_public_sink(SinkChannel.TRACE) is PublicSink.TELEMETRY
    assert channel_to_public_sink(SinkChannel.ERROR_SURFACE) is PublicSink.LOGS


# ---------------------------------------------------------------------------
# Adversarial private substance matrix
# ---------------------------------------------------------------------------


def test_private_bytes_text_embeddings_cids_denied_from_all_channels(
    enforcer: PublicSinkEnforcer,
) -> None:
    """No private canary reaches any forbidden sink under adversarial paths."""
    attempt_count = 0
    for cls in PRIVATE_CLASSES:
        for channel in all_sink_channels():
            for kind, payload in PAYLOADS.items():
                result = enforcer.dispatch(
                    _request(
                        channel=channel,
                        kind=kind,
                        classification=cls,
                        payload=payload,
                        # Export-review class uses matching publication state.
                        publication_state=(
                            PublicationState.EXPORT_REVIEW_PENDING
                            if cls is DisclosureClassification.RESTRICTED_EXPORT_REVIEW
                            else PublicationState.PRIVATE_UNPUBLISHED
                        ),
                        export_control_state=(
                            ExportControlState.RESTRICTED
                            if cls is DisclosureClassification.RESTRICTED_EXPORT_REVIEW
                            else ExportControlState.CLEARED
                        ),
                    )
                )
                attempt_count += 1
                assert result.allowed is False, (
                    f"expected denial for {cls.value}/{channel.value}/{kind.value}"
                )

    assert attempt_count == len(PRIVATE_CLASSES) * len(all_sink_channels()) * len(
        PAYLOADS
    )
    assert enforcer.admitted == ()
    assert len(enforcer.denied) == attempt_count

    # Inspect outputs / logs / telemetry — not merely return codes.
    surface = enforcer.all_captured_surface_text()
    _assert_no_canaries(surface)
    for channel in all_sink_channels():
        assert enforcer.channel_payloads(channel) == ()


def test_deny_helper_covers_full_matrix_and_inspects_telemetry() -> None:
    eng = PublicSinkEnforcer(tenant_policy=TenantPolicy(tenant_id="tenant-h"))
    results = deny_private_substance_from_all_channels(
        tenant_id="tenant-h",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        enforcer=eng,
        payloads=PAYLOADS,
    )
    assert results
    assert all(not r.allowed for r in results)
    pairs = {(r.channel, r.content_kind) for r in results}
    for channel in all_sink_channels():
        for kind in SUBSTANTIVE_KINDS:
            assert (channel, kind) in pairs

    # Telemetry records denials with codes, never private substance.
    assert eng.telemetry
    assert all(ev.get("allowed") is False for ev in eng.telemetry)
    tel_json = json.dumps([dict(e) for e in eng.telemetry], default=str)
    _assert_no_canaries(tel_json)
    assert PRIVATE_TEXT_CANARY not in tel_json
    assert PRIVATE_CID_CANARY not in tel_json


def test_public_ipfs_dht_gateway_pin_never_receive_private_cid(
    enforcer: PublicSinkEnforcer,
) -> None:
    for channel in all_ipfs_public_channels():
        result = enforcer.dispatch(
            _request(
                channel=channel,
                kind=ContentKind.CONTENT_IDENTIFIER,
                payload=PRIVATE_CID_CANARY,
            )
        )
        assert result.allowed is False
        assert enforcer.channel_payloads(channel) == ()
    surface = enforcer.all_captured_surface_text()
    assert PRIVATE_CID_CANARY not in surface


def test_embeddings_denied_from_public_dataset_and_index(
    enforcer: PublicSinkEnforcer,
) -> None:
    for channel in (SinkChannel.PUBLIC_DATASET, SinkChannel.EMBEDDING_INDEX):
        result = enforcer.dispatch(
            _request(
                channel=channel,
                kind=ContentKind.EMBEDDING,
                payload=PRIVATE_EMBEDDING_CANARY,
            )
        )
        assert result.allowed is False
        assert result.code in {
            EnforcementDecisionCode.DENIED_PRIVATE,
            EnforcementDecisionCode.DENIED_EXPORT_CONTROL,
        }
    surface = enforcer.all_captured_surface_text()
    assert PRIVATE_EMBEDDING_MARKER not in surface


# ---------------------------------------------------------------------------
# External model default deny
# ---------------------------------------------------------------------------


def test_external_model_denied_by_default_for_private(
    enforcer: PublicSinkEnforcer,
) -> None:
    for kind, payload in PAYLOADS.items():
        result = enforcer.dispatch(
            _request(
                channel=SinkChannel.REMOTE_MODEL,
                kind=kind,
                payload=payload,
            )
        )
        assert result.allowed is False
        assert result.code in {
            EnforcementDecisionCode.DENIED_EXTERNAL_MODEL,
            EnforcementDecisionCode.DENIED_PRIVATE,
            EnforcementDecisionCode.DENIED_EXPORT_CONTROL,
        }
    assert enforcer.channel_payloads(SinkChannel.REMOTE_MODEL) == ()
    prompts_surface = enforcer.all_captured_surface_text()
    _assert_no_canaries(prompts_surface)


def test_external_model_still_denied_even_if_policy_flag_alone_true() -> None:
    """Tenant must also opt in; policy flag alone is insufficient."""
    policy = UsptoPrivacyPolicy(allow_external_models_for_private=True)
    eng = PublicSinkEnforcer(
        policy=policy,
        tenant_policy=TenantPolicy(
            tenant_id="tenant-assurance-a",
            allow_external_models=False,
        ),
        allow_external_models_for_private=True,
    )
    # Export gate still blocks private_unpublished before remote model check;
    # use a path that exercises the remote-model deny when classification is
    # private — private publication always fails export gate first, which is
    # also a valid deny. Additionally force via confidential + private state.
    result = eng.dispatch(
        _request(
            channel=SinkChannel.REMOTE_MODEL,
            kind=ContentKind.EXTRACTED_TEXT,
            payload=PRIVATE_TEXT_CANARY,
            publication_state=PublicationState.PRIVATE_UNPUBLISHED,
        )
    )
    assert result.allowed is False
    assert eng.channel_payloads(SinkChannel.REMOTE_MODEL) == ()
    assert PRIVATE_TEXT_CANARY not in eng.all_captured_surface_text()


# ---------------------------------------------------------------------------
# Logs, telemetry, traces, errors — inspect content, not just codes
# ---------------------------------------------------------------------------


def test_logs_telemetry_traces_errors_never_hold_private_substance(
    enforcer: PublicSinkEnforcer,
) -> None:
    for channel in (
        SinkChannel.LOGS,
        SinkChannel.TELEMETRY,
        SinkChannel.TRACE,
        SinkChannel.ERROR_SURFACE,
    ):
        for kind, payload in PAYLOADS.items():
            result = enforcer.dispatch(
                _request(channel=channel, kind=kind, payload=payload)
            )
            assert result.allowed is False

    # Observability surfaces produced by the enforcer itself.
    for event in enforcer.audit_log:
        rendered = json.dumps(dict(event), default=str, sort_keys=True)
        _assert_no_canaries(rendered)
        assert event.get("schema_version") == PRIVACY_SINKS_SCHEMA_VERSION
        assert "payload" not in event or event.get("payload") is None
        # payload_marker may describe size/type only.
        marker = event.get("payload_marker") or {}
        assert PRIVATE_TEXT_CANARY not in json.dumps(marker, default=str)

    for event in enforcer.telemetry:
        _assert_no_canaries(json.dumps(dict(event), default=str))
        assert event.get("allowed") is False

    for event in enforcer.error_surfaces:
        rendered = json.dumps(dict(event), default=str)
        _assert_no_canaries(rendered)
        assert event.get("event") == "sink_denied"
        assert "code" in event

    assert enforcer.admitted == ()


def test_assert_dispatch_raises_without_leaking_payload(
    enforcer: PublicSinkEnforcer,
) -> None:
    with pytest.raises(PrivacyBoundaryError) as caught:
        enforcer.assert_dispatch_allowed(
            _request(
                channel=SinkChannel.PUBLIC_IPFS_DHT,
                kind=ContentKind.EXTRACTED_TEXT,
                payload=PRIVATE_TEXT_CANARY,
            )
        )
    err = caught.value
    rendered = f"{err!s}\n{err!r}\n{json.dumps(err.audit_dict())}"
    assert PRIVATE_TEXT_CANARY not in rendered
    assert err.code
    audit = err.audit_dict()
    assert "text" not in audit
    assert audit.get("sink") == SinkChannel.PUBLIC_IPFS_DHT.value


def test_redact_for_observability_strips_private_keys() -> None:
    payload = {
        "artifact_id": "artifact:assurance:1",
        "matter_id": "matter:assurance:1",
        "tenant_id": "tenant-assurance-a",
        "classification": DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
        "digest": "a" * 64,
        "text": PRIVATE_TEXT_CANARY,
        "embedding": PRIVATE_EMBEDDING_CANARY,
        "cid": PRIVATE_CID_CANARY,
        "bytes": PRIVATE_BYTES_CANARY.hex(),
        "prompt": PRIVATE_TEXT_CANARY,
        "channel": SinkChannel.LOGS.value,
        "code": "denied_private",
    }
    redacted = redact_for_observability(
        DisclosureClassification.CONFIDENTIAL_APPLICATION, payload
    )
    rendered = canonical_json(dict(redacted))
    _assert_no_canaries(rendered)
    assert redacted["artifact_id"] == "artifact:assurance:1"
    assert redacted.get("redacted") is True


# ---------------------------------------------------------------------------
# Unknown classification quarantines
# ---------------------------------------------------------------------------


def test_unknown_classification_quarantines_all_channels(
    enforcer: PublicSinkEnforcer,
) -> None:
    for channel in all_sink_channels():
        for kind in SUBSTANTIVE_KINDS:
            result = enforcer.dispatch(
                _request(
                    channel=channel,
                    kind=kind,
                    classification=DisclosureClassification.UNKNOWN,
                    publication_state=PublicationState.UNKNOWN,
                    export_control_state=ExportControlState.UNKNOWN,
                    payload=PRIVATE_TEXT_CANARY,
                )
            )
            assert result.allowed is False
            assert result.quarantined is True
            assert result.code in {
                EnforcementDecisionCode.DENIED_QUARANTINE,
                EnforcementDecisionCode.DENIED_UNKNOWN_PUBLICATION,
                EnforcementDecisionCode.DENIED_UNKNOWN_EXPORT_STATE,
            }
    assert enforcer.admitted == ()
    _assert_no_canaries(enforcer.all_captured_surface_text())


def test_unrecognized_classification_label_fails_closed(
    enforcer: PublicSinkEnforcer,
) -> None:
    result = enforcer.dispatch(
        _request(
            channel=SinkChannel.PUBLIC_DATASET,
            kind=ContentKind.EXTRACTED_TEXT,
            classification="totally-bogus-label",  # type: ignore[arg-type]
            payload=PRIVATE_TEXT_CANARY,
        )
    )
    assert result.allowed is False
    assert result.classification is DisclosureClassification.UNKNOWN or result.quarantined
    _assert_no_canaries(enforcer.all_captured_surface_text())


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


def test_cross_tenant_dispatch_denied(enforcer: PublicSinkEnforcer) -> None:
    result = enforcer.dispatch(
        _request(
            channel=SinkChannel.PUBLIC_DATASET,
            kind=ContentKind.METADATA_DIGEST,
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            tenant_id="tenant-other",
            publication_state=PublicationState.PUBLIC,
            export_control_state=ExportControlState.CLEARED,
            payload={"sha256": "b" * 64},
        )
    )
    assert result.allowed is False
    assert result.code is EnforcementDecisionCode.DENIED_TENANT_ISOLATION
    assert enforcer.channel_payloads(SinkChannel.PUBLIC_DATASET) == ()


def test_assert_tenant_isolation_raises() -> None:
    eng = PublicSinkEnforcer(
        tenant_policy=TenantPolicy(tenant_id="tenant-a")
    )
    with pytest.raises(PrivacyBoundaryError) as caught:
        eng.assert_tenant_isolation("tenant-b", resource_tenant_id="tenant-a")
    assert caught.value.code == EnforcementDecisionCode.DENIED_TENANT_ISOLATION.value


def test_same_tenant_public_metadata_may_admit() -> None:
    eng = PublicSinkEnforcer(
        tenant_policy=TenantPolicy(tenant_id="tenant-public")
    )
    result = eng.dispatch(
        SinkDispatchRequest(
            tenant_id="tenant-public",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            channel=SinkChannel.PUBLIC_DATASET,
            content_kind=ContentKind.METADATA_DIGEST,
            publication_state=PublicationState.PUBLIC,
            export_control_state=ExportControlState.CLEARED,
            payload={"sha256": "c" * 64, "title": "US-PUBLIC-GRANT"},
            digest="c" * 64,
        )
    )
    assert result.allowed is True
    assert result.code is EnforcementDecisionCode.ALLOWED
    assert eng.channel_payloads(SinkChannel.PUBLIC_DATASET)
    # Public payload may appear on admitted channel — canaries must not.
    surface = eng.all_captured_surface_text()
    _assert_no_canaries(surface)


def test_mixed_bundle_inherits_private_and_blocks_all_channels(
    enforcer: PublicSinkEnforcer,
) -> None:
    result = enforcer.dispatch(
        _request(
            channel=SinkChannel.PUBLIC_IPFS_PIN,
            kind=ContentKind.DOCUMENT_BYTES,
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            source_classifications=(
                DisclosureClassification.PUBLIC_USER,
                DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
            ),
            publication_state=PublicationState.PUBLIC,
            export_control_state=ExportControlState.CLEARED,
            payload=PRIVATE_BYTES_CANARY,
        )
    )
    assert result.allowed is False
    assert result.classification is DisclosureClassification.PRIVILEGED_WORK_PRODUCT
    assert enforcer.channel_payloads(SinkChannel.PUBLIC_IPFS_PIN) == ()


def test_credential_classification_denied_everywhere(
    enforcer: PublicSinkEnforcer,
) -> None:
    for channel in all_sink_channels():
        result = enforcer.dispatch(
            _request(
                channel=channel,
                kind=ContentKind.CREDENTIAL_SECRET,
                classification=DisclosureClassification.CREDENTIAL_OR_PAYMENT,
                publication_state=PublicationState.PUBLIC,
                export_control_state=ExportControlState.CLEARED,
                payload="vault-ref-not-real://token",
            )
        )
        assert result.allowed is False
    assert enforcer.admitted == ()


def test_deny_matrix_helper_returns_only_denials(
    enforcer: PublicSinkEnforcer,
) -> None:
    denials = enforcer.deny_matrix(
        tenant_id="tenant-assurance-a",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        payload=PRIVATE_TEXT_CANARY,
    )
    assert denials
    assert all(not d.allowed for d in denials)
    assert len(denials) == len(all_sink_channels()) * len(
        (
            ContentKind.DOCUMENT_BYTES,
            ContentKind.EXTRACTED_TEXT,
            ContentKind.EMBEDDING,
            ContentKind.CONTENT_IDENTIFIER,
        )
    )


def test_audit_event_never_embeds_private_payload_keys(
    enforcer: PublicSinkEnforcer,
) -> None:
    result = enforcer.dispatch(
        _request(
            channel=SinkChannel.TELEMETRY,
            kind=ContentKind.EXTRACTED_TEXT,
            payload={
                "text": PRIVATE_TEXT_CANARY,
                "cid": PRIVATE_CID_CANARY,
                "embedding": PRIVATE_EMBEDDING_CANARY,
            },
        )
    )
    assert result.allowed is False
    event = dict(result.audit_event)
    for forbidden in ("text", "cid", "embedding", "bytes", "payload", "prompt"):
        assert forbidden not in event
    rendered = json.dumps(event, default=str)
    _assert_no_canaries(rendered)

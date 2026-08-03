"""Unit tests for USPTO matter events and application status (PATLAW-020)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    MatterEvent,
    MatterEventKind,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.matter_events import (
    MATTER_EVENTS_SCHEMA_VERSION,
    META_RETRIEVAL_UTC,
    META_SOURCE_EVENT_UTC,
    ApplicationLifecyclePhase,
    ApplicationStatusSnapshot,
    EventTemporalRole,
    MatterEventError,
    NormalizedMatterEvent,
    RejectionDisposition,
    build_matter_event,
    event_temporal_pair,
    normalize_application_status,
    order_matter_events,
)

DIGEST_A = "a" * 64


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert (
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == canonical_json(first)
    )
    assert restored == record


# ---------------------------------------------------------------------------
# Application status — multi-dimensional, not a single rejected flag
# ---------------------------------------------------------------------------


def test_status_snapshot_has_no_rejected_boolean_field() -> None:
    snap = normalize_application_status(
        status_code="DOCKED",
        status_text="Docketed New Case - Ready for Examination",
        as_of_source_utc="2026-01-15T12:00:00Z",
        retrieval_utc="2026-08-01T09:00:00Z",
    )
    assert not hasattr(snap, "rejected")
    payload = snap.to_dict()
    assert "rejected" not in payload
    assert snap.rejection_disposition in RejectionDisposition
    assert snap.lifecycle_phase is ApplicationLifecyclePhase.PRE_EXAMINATION
    assert snap.is_pending is True
    _assert_round_trip(snap)


def test_status_preserves_final_rejection_without_terminal_rejected_flag() -> None:
    snap = normalize_application_status(
        status_code="CTFR",
        status_text="Final Rejection Mailed",
        raw_fields={
            "transactionCode": "CTFR",
            "mailDate": "2025-06-01",
            "upstreamStatus": "Final Rejection Mailed",
        },
        as_of_source_utc="2025-06-01T00:00:00Z",
        retrieval_utc="2026-08-01T10:00:00Z",
    )
    assert snap.rejection_disposition is RejectionDisposition.FINAL
    assert snap.lifecycle_phase is ApplicationLifecyclePhase.EXAMINATION
    # Still pending prosecution after a final rejection until abandon/allow/appeal.
    assert snap.is_abandoned is not True
    assert snap.is_allowed is not True
    assert snap.raw_fields["transactionCode"] == "CTFR"
    assert "rejected" not in snap.to_dict()


def test_status_nonfinal_allowance_abandonment_grant_axes() -> None:
    nonfinal = normalize_application_status(status_text="Non-Final Rejection")
    assert nonfinal.rejection_disposition is RejectionDisposition.NONFINAL

    allowed = normalize_application_status(status_text="Notice of Allowance Mailed")
    assert allowed.lifecycle_phase is ApplicationLifecyclePhase.ALLOWANCE
    assert allowed.is_allowed is True
    assert allowed.rejection_disposition is RejectionDisposition.NOT_APPLICABLE

    abandoned = normalize_application_status(status_text="Abandoned -- Failure to Respond")
    assert abandoned.lifecycle_phase is ApplicationLifecyclePhase.ABANDONMENT
    assert abandoned.is_abandoned is True
    assert abandoned.is_pending is False

    granted = normalize_application_status(status_text="Patented Case")
    assert granted.lifecycle_phase is ApplicationLifecyclePhase.GRANT
    assert granted.is_patented is True


def test_lossy_single_rejected_flag_refused() -> None:
    with pytest.raises(MatterEventError) as excinfo:
        ApplicationStatusSnapshot(
            schema_version=MATTER_EVENTS_SCHEMA_VERSION,
            status_code=None,
            status_text=None,
            lifecycle_phase=ApplicationLifecyclePhase.UNKNOWN,
            rejection_disposition=RejectionDisposition.UNKNOWN,
            is_pending=None,
            is_abandoned=None,
            is_allowed=None,
            is_patented=None,
            is_appealed=None,
            entity_status=None,
            as_of_source_utc=None,
            retrieval_utc=None,
            raw_fields={"rejected": "true"},
            notes=(),
        )
    assert excinfo.value.code == "lossy_rejected_flag"


def test_status_explicit_axes_without_inference() -> None:
    snap = normalize_application_status(
        status_text="Final Rejection Mailed",
        lifecycle_phase=ApplicationLifecyclePhase.APPEAL,
        rejection_disposition=RejectionDisposition.FINAL,
        is_appealed=True,
        is_pending=True,
        infer=False,
    )
    assert snap.lifecycle_phase is ApplicationLifecyclePhase.APPEAL
    assert snap.rejection_disposition is RejectionDisposition.FINAL
    assert snap.is_appealed is True


# ---------------------------------------------------------------------------
# Matter events — kinds, temporal axes, contract projection
# ---------------------------------------------------------------------------


def test_all_lifecycle_kinds_supported() -> None:
    kinds = (
        MatterEventKind.FILING,
        MatterEventKind.STATUS,
        MatterEventKind.TRANSACTION,
        MatterEventKind.DOCUMENT,
        MatterEventKind.RESPONSE,
        MatterEventKind.APPEAL,
        MatterEventKind.ABANDONMENT,
        MatterEventKind.ALLOWANCE,
        MatterEventKind.GRANT,
    )
    for kind in kinds:
        event = build_matter_event(
            event_id=f"event:{kind.value}",
            matter_id="matter:16-123456",
            kind=kind,
            source_event_utc="2026-01-01T00:00:00Z",
            retrieval_utc="2026-08-01T12:00:00Z",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        )
        assert event.kind is kind
        contract = event.to_matter_event()
        assert contract.kind is kind
        assert contract.event_utc == "2026-01-01T00:00:00Z"
        assert contract.metadata[META_SOURCE_EVENT_UTC] == "2026-01-01T00:00:00Z"
        assert contract.metadata[META_RETRIEVAL_UTC] == "2026-08-01T12:00:00Z"


def test_source_and_retrieval_times_not_conflated() -> None:
    event = build_matter_event(
        event_id="event:tx:1",
        matter_id="matter:1",
        kind=MatterEventKind.TRANSACTION,
        source_event_utc="2025-03-15T16:30:00Z",
        retrieval_utc="2026-08-03T08:00:00Z",
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        metadata={"doc_code": "A...", "upstream_id": "tx-9"},
    )
    source, retrieval = event_temporal_pair(event)
    assert source == "2025-03-15T16:30:00Z"
    assert retrieval == "2026-08-03T08:00:00Z"
    assert source != retrieval

    contract = event.to_matter_event()
    assert contract.event_utc == source
    assert contract.metadata[META_RETRIEVAL_UTC] == retrieval
    # Free metadata preserved alongside temporal keys.
    assert contract.metadata["doc_code"] == "A..."

    lifted = NormalizedMatterEvent.from_matter_event(contract)
    assert lifted.source_event_utc == source
    assert lifted.retrieval_utc == retrieval
    assert lifted.metadata.get("doc_code") == "A..."


def test_normalized_event_and_status_round_trip() -> None:
    status = normalize_application_status(
        status_code="CTNF",
        status_text="Non-Final Rejection",
        as_of_source_utc="2025-04-01T00:00:00Z",
        retrieval_utc="2026-08-01T11:00:00Z",
    )
    event = build_matter_event(
        event_id="event:status:1",
        matter_id="matter:16-123456",
        kind=MatterEventKind.STATUS,
        source_event_utc="2025-04-01T00:00:00Z",
        retrieval_utc="2026-08-01T11:00:00Z",
        source_receipt_id="receipt:odp:1",
        description_digest=DIGEST_A,
        related_artifact_ids=("artifact:oa:1",),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        status_snapshot=status,
        metadata={"pair_status_code": "CTNF"},
        notes=("from_odp",),
    )
    _assert_round_trip(event)

    contract = event.to_matter_event()
    assert contract.schema_version == CONTRACTS_SCHEMA_VERSION
    restored_contract = MatterEvent.from_dict(contract.to_dict())
    assert restored_contract == contract

    lifted = NormalizedMatterEvent.from_matter_event(restored_contract)
    assert lifted.source_event_utc == event.source_event_utc
    assert lifted.retrieval_utc == event.retrieval_utc
    assert lifted.status_snapshot is not None
    assert lifted.status_snapshot.rejection_disposition is RejectionDisposition.NONFINAL


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_event_ordering_preserves_source_then_retrieval() -> None:
    # Same source day, different retrieval times; plus earlier/later source times.
    events = [
        build_matter_event(
            event_id="event:c",
            matter_id="matter:1",
            kind=MatterEventKind.DOCUMENT,
            source_event_utc="2025-06-01T12:00:00Z",
            retrieval_utc="2026-08-02T00:00:00Z",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        ),
        build_matter_event(
            event_id="event:a",
            matter_id="matter:1",
            kind=MatterEventKind.FILING,
            source_event_utc="2024-01-01T00:00:00Z",
            retrieval_utc="2026-08-03T00:00:00Z",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        ),
        build_matter_event(
            event_id="event:b2",
            matter_id="matter:1",
            kind=MatterEventKind.TRANSACTION,
            source_event_utc="2025-06-01T12:00:00Z",
            retrieval_utc="2026-08-01T00:00:00Z",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        ),
        build_matter_event(
            event_id="event:b1",
            matter_id="matter:1",
            kind=MatterEventKind.STATUS,
            source_event_utc="2025-06-01T12:00:00Z",
            retrieval_utc=None,
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        ),
        build_matter_event(
            event_id="event:d",
            matter_id="matter:1",
            kind=MatterEventKind.GRANT,
            source_event_utc="2026-01-01T00:00:00Z",
            retrieval_utc="2026-08-01T00:00:00Z",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        ),
    ]

    ordered = order_matter_events(events)
    ids = [e.event_id for e in ordered]
    # Source ascending: a (2024), then b2 before c (same source, retrieval earlier),
    # missing retrieval last among same source, then d.
    assert ids[0] == "event:a"
    assert ids[-1] == "event:d"
    same_source = [e for e in ordered if e.source_event_utc == "2025-06-01T12:00:00Z"]
    assert [e.event_id for e in same_source] == ["event:b2", "event:c", "event:b1"]

    # Both axes still present after ordering.
    for event in ordered:
        source, retrieval = event_temporal_pair(event)
        assert source == event.source_event_utc
        assert retrieval == event.retrieval_utc


def test_order_by_retrieval_primary_still_keeps_source() -> None:
    events = [
        build_matter_event(
            event_id="event:old-source-new-retrieval",
            matter_id="matter:1",
            kind=MatterEventKind.DOCUMENT,
            source_event_utc="2020-01-01T00:00:00Z",
            retrieval_utc="2026-08-03T00:00:00Z",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        ),
        build_matter_event(
            event_id="event:new-source-old-retrieval",
            matter_id="matter:1",
            kind=MatterEventKind.DOCUMENT,
            source_event_utc="2025-01-01T00:00:00Z",
            retrieval_utc="2026-08-01T00:00:00Z",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        ),
    ]
    ordered = order_matter_events(
        events,
        primary=EventTemporalRole.RETRIEVAL,
        secondary=EventTemporalRole.SOURCE,
    )
    assert ordered[0].event_id == "event:new-source-old-retrieval"
    assert ordered[0].source_event_utc == "2025-01-01T00:00:00Z"
    assert ordered[1].retrieval_utc == "2026-08-03T00:00:00Z"


def test_order_accepts_contract_events() -> None:
    n = build_matter_event(
        event_id="event:1",
        matter_id="matter:1",
        kind=MatterEventKind.RESPONSE,
        source_event_utc="2025-01-02T00:00:00Z",
        retrieval_utc="2026-08-01T00:00:00Z",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    contract = n.to_matter_event()
    ordered = order_matter_events([contract])
    assert len(ordered) == 1
    assert ordered[0].source_event_utc == "2025-01-02T00:00:00Z"
    assert ordered[0].retrieval_utc == "2026-08-01T00:00:00Z"


def test_temporal_role_collision_rejected() -> None:
    with pytest.raises(MatterEventError):
        order_matter_events(
            [],
            primary=EventTemporalRole.SOURCE,
            secondary=EventTemporalRole.SOURCE,
        )


def test_schema_version_pinned() -> None:
    assert MATTER_EVENTS_SCHEMA_VERSION == "uspto.matter-events.v1"

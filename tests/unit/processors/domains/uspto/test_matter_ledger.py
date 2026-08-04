"""Unit tests for USPTO matter ledger reconciliation (PATLAW-025)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    MatterEvent,
    MatterEventKind,
    SourceReceipt,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.matter_ledger import (
    MATTER_LEDGER_SCHEMA_VERSION,
    ClaimSetVersion,
    ConflictCode,
    GapCode,
    GapInterpretation,
    InMemoryLedgerStore,
    IngestDisposition,
    LedgerChannel,
    LedgerConflict,
    LedgerEntry,
    LedgerGap,
    LedgerItemKind,
    LedgerPresence,
    MatterLedger,
    MatterLedgerError,
    MatterLedgerSnapshot,
    QuarantineRecord,
    build_manifest_for_ledger,
    content_addressed_id,
    infer_item_kind,
    matter_ids_compatible,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
MATTER = "matter:syn:16-000001"
MATTER_OTHER = "matter:syn:16-999999"


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


def _fixed_clock(when: str = "2026-08-03T12:00:00Z"):
    return lambda: when


def _ledger() -> MatterLedger:
    return MatterLedger(InMemoryLedgerStore(), wall_clock=_fixed_clock())


def _manifest(
    *,
    artifact_id: str = "art-original-1",
    sha256: str = DIGEST_A,
    matter_id: str = MATTER,
    media_type: str = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    authority: AuthorityRelation = AuthorityRelation.AUTHORITATIVE_ORIGINAL,
    parents: tuple[str, ...] = (),
    labels: dict[str, str] | None = None,
    size_bytes: int = 128,
) -> Any:
    return build_manifest_for_ledger(
        artifact_id=artifact_id,
        sha256=sha256,
        size_bytes=size_bytes,
        matter_id=matter_id,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        media_type=media_type,
        authority_relation=authority,
        parent_artifact_ids=parents,
        labels=labels
        or {
            "role": "original_submission"
            if authority is AuthorityRelation.AUTHORITATIVE_ORIGINAL
            else "uspto_converted_pdf"
        },
    )


# ---------------------------------------------------------------------------
# Helpers / inference
# ---------------------------------------------------------------------------


def test_infer_item_kind_from_labels_and_relation() -> None:
    assert (
        infer_item_kind(labels={"role": "original_submission"})
        is LedgerItemKind.ORIGINAL_SUBMISSION
    )
    assert (
        infer_item_kind(labels={"role": "uspto_converted_pdf"})
        is LedgerItemKind.CONVERTED_RENDERING
    )
    assert (
        infer_item_kind(labels={"role": "acknowledgement"})
        is LedgerItemKind.ACKNOWLEDGEMENT
    )
    assert (
        infer_item_kind(labels={"role": "payment_receipt"})
        is LedgerItemKind.PAYMENT_RECEIPT
    )
    assert (
        infer_item_kind(
            authority_relation=AuthorityRelation.DERIVATIVE,
            media_type="application/pdf",
        )
        is LedgerItemKind.CONVERTED_RENDERING
    )
    assert (
        infer_item_kind(explicit=LedgerItemKind.CLAIM_SET)
        is LedgerItemKind.CLAIM_SET
    )


def test_matter_ids_compatible() -> None:
    assert matter_ids_compatible(MATTER, MATTER)
    assert matter_ids_compatible(MATTER, None)
    assert not matter_ids_compatible(MATTER, MATTER_OTHER)


def test_content_addressed_id_is_stable() -> None:
    a = content_addressed_id("le", {"x": 1, "y": "z"})
    b = content_addressed_id("le", {"y": "z", "x": 1})
    assert a == b
    assert a.startswith("le:")


# ---------------------------------------------------------------------------
# Record round-trips
# ---------------------------------------------------------------------------


def test_ledger_entry_round_trip() -> None:
    entry = LedgerEntry(
        schema_version=MATTER_LEDGER_SCHEMA_VERSION,
        entry_id="le:deadbeef",
        matter_id=MATTER,
        logical_id="art-original-1",
        item_kind=LedgerItemKind.ORIGINAL_SUBMISSION,
        authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
        presence=LedgerPresence.PRESENT,
        version=1,
        content_sha256=DIGEST_A,
        size_bytes=128,
        artifact_id="art-original-1",
        parent_entry_ids=(),
        parent_artifact_ids=(),
        related_entry_ids=(),
        source_receipt_id=None,
        channel=LedgerChannel.PRIVATE_IMPORT,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        media_type="application/pdf",
        event_kind=None,
        event_utc=None,
        admitted_utc="2026-08-03T12:00:00Z",
        labels={"role": "original_submission"},
        notes=(),
    )
    _assert_round_trip(entry)


def test_gap_never_allows_proof_of_nonreceipt() -> None:
    with pytest.raises(MatterLedgerError) as exc:
        LedgerGap(
            schema_version=MATTER_LEDGER_SCHEMA_VERSION,
            gap_id="gap:x",
            matter_id=MATTER,
            code=GapCode.INVENTORY_WITHOUT_BYTES,
            interpretation=GapInterpretation.FRESHNESS_GAP,
            logical_id="doc-1",
            message="missing bytes",
            recorded_utc="2026-08-03T12:00:00Z",
            related_entry_ids=(),
            is_proof_of_nonreceipt=True,
            details={},
        )
    assert exc.value.code == "gap_nonreceipt_forbidden"


def test_conflict_and_quarantine_round_trip() -> None:
    conflict = LedgerConflict(
        schema_version=MATTER_LEDGER_SCHEMA_VERSION,
        conflict_id="cf:abc",
        matter_id=MATTER,
        code=ConflictCode.MATTER_ID_MISMATCH,
        entry_ids=(),
        message="wrong matter",
        recorded_utc="2026-08-03T12:00:00Z",
        details={"observed_matter_id": MATTER_OTHER},
    )
    _assert_round_trip(conflict)
    q = QuarantineRecord(
        schema_version=MATTER_LEDGER_SCHEMA_VERSION,
        quarantine_id="q:abc",
        expected_matter_id=MATTER,
        observed_matter_id=MATTER_OTHER,
        reason_codes=("wrong_matter_id",),
        message="quarantined",
        recorded_utc="2026-08-03T12:00:00Z",
        artifact_id="art-x",
        content_sha256=DIGEST_A,
        source_payload_digest=DIGEST_B,
        labels={},
    )
    _assert_round_trip(q)


# ---------------------------------------------------------------------------
# Ingest: originals, derivatives, receipts
# ---------------------------------------------------------------------------


def test_ingest_original_and_derivative_preserves_authority() -> None:
    ledger = _ledger()
    original = _manifest(
        artifact_id="art-docx",
        sha256=DIGEST_A,
        labels={"role": "original_submission"},
    )
    converted = _manifest(
        artifact_id="art-pdf",
        sha256=DIGEST_B,
        media_type="application/pdf",
        authority=AuthorityRelation.DERIVATIVE,
        parents=("art-docx",),
        labels={"role": "uspto_converted_pdf"},
    )
    r1 = ledger.ingest_artifact(matter_id=MATTER, manifest=original)
    r2 = ledger.ingest_artifact(matter_id=MATTER, manifest=converted)
    assert r1.disposition is IngestDisposition.ADMITTED
    assert r2.disposition is IngestDisposition.ADMITTED
    assert r1.entry is not None and r2.entry is not None
    assert r1.entry.is_authoritative_original
    assert r2.entry.is_derivative
    assert "art-docx" in r2.entry.parent_artifact_ids
    assert r1.entry.item_kind is LedgerItemKind.ORIGINAL_SUBMISSION
    assert r2.entry.item_kind is LedgerItemKind.CONVERTED_RENDERING

    snap = ledger.reconcile(MATTER)
    assert len(snap.originals()) >= 1
    assert len(snap.derivatives()) >= 1
    assert snap.derivatives()[0].parent_artifact_ids == ("art-docx",)
    # Derivative must not replace original in history.
    assert len(snap.entries) >= 2
    assert all(e.entry_id in snap.history_entry_ids for e in snap.entries)


def test_ingest_acknowledgement_and_payment_receipts() -> None:
    ledger = _ledger()
    # Original required so structural gap is not raised for receipts alone.
    ledger.ingest_artifact(matter_id=MATTER, manifest=_manifest())
    ack = _manifest(
        artifact_id="art-ack",
        sha256=DIGEST_B,
        media_type="text/plain",
        labels={"role": "acknowledgement"},
    )
    pay = _manifest(
        artifact_id="art-pay",
        sha256=DIGEST_C,
        media_type="text/plain",
        labels={"role": "payment_receipt"},
    )
    ra = ledger.ingest_artifact(matter_id=MATTER, manifest=ack)
    rp = ledger.ingest_artifact(matter_id=MATTER, manifest=pay)
    assert ra.entry is not None and rp.entry is not None
    assert ra.entry.item_kind is LedgerItemKind.ACKNOWLEDGEMENT
    assert rp.entry.item_kind is LedgerItemKind.PAYMENT_RECEIPT
    assert ra.entry.is_authoritative_original
    assert rp.entry.is_authoritative_original


def test_gui_metadata_ingested_explicitly() -> None:
    ledger = _ledger()
    result = ledger.ingest_gui_metadata(
        matter_id=MATTER,
        logical_id="gui:doc-desc-1",
        metadata={
            "document_description": "Specification",
            "document_code": "SPEC",
        },
    )
    assert result.ok
    assert result.entry is not None
    assert result.entry.item_kind is LedgerItemKind.GUI_METADATA
    assert result.entry.labels["document_description"] == "Specification"


# ---------------------------------------------------------------------------
# Wrong matter id → quarantine
# ---------------------------------------------------------------------------


def test_wrong_matter_id_is_quarantined() -> None:
    ledger = _ledger()
    bad = _manifest(matter_id=MATTER_OTHER, artifact_id="art-wrong", sha256=DIGEST_A)
    result = ledger.ingest_artifact(matter_id=MATTER, manifest=bad)
    assert result.disposition is IngestDisposition.QUARANTINED
    assert result.entry is None
    assert result.quarantine is not None
    assert "wrong_matter_id" in result.quarantine.reason_codes
    assert result.quarantine.observed_matter_id == MATTER_OTHER
    assert result.quarantine.expected_matter_id == MATTER
    assert any(c.code is ConflictCode.MATTER_ID_MISMATCH for c in result.conflicts)

    snap = ledger.reconcile(MATTER)
    assert snap.has_quarantines
    assert len(snap.entries) == 0
    assert len(snap.quarantines) == 1
    # Quarantined item is not in the active matter entry set.
    assert all(e.artifact_id != "art-wrong" for e in snap.entries)


def test_wrong_matter_event_is_quarantined() -> None:
    ledger = _ledger()
    event = MatterEvent(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        event_id="evt-1",
        matter_id=MATTER_OTHER,
        kind=MatterEventKind.STATUS,
        event_utc="2026-01-01T00:00:00Z",
        source_receipt_id=None,
        description_digest=DIGEST_A,
        related_artifact_ids=(),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        metadata={"status_code": "150"},
    )
    result = ledger.ingest_event(matter_id=MATTER, event=event)
    assert result.disposition is IngestDisposition.QUARANTINED
    assert result.quarantine is not None
    snap = ledger.reconcile(MATTER)
    assert snap.has_quarantines
    assert len(snap.entries) == 0


# ---------------------------------------------------------------------------
# Missing / delayed inventory remains explicit (not nonreceipt)
# ---------------------------------------------------------------------------


def test_missing_inventory_is_freshness_gap_not_nonreceipt() -> None:
    ledger = _ledger()
    result = ledger.ingest_inventory_item(
        matter_id=MATTER,
        source_document_id="odp-doc-delayed-1",
        available=False,
        delayed=True,
    )
    assert result.disposition is IngestDisposition.GAP_RECORDED
    assert result.entry is not None
    assert result.entry.presence is LedgerPresence.DELAYED
    assert result.entry.item_kind is LedgerItemKind.INVENTORY_PLACEHOLDER
    assert len(result.gaps) == 1
    gap = result.gaps[0]
    assert gap.is_proof_of_nonreceipt is False
    assert gap.interpretation is GapInterpretation.FRESHNESS_GAP
    assert gap.code is GapCode.DELAYED_PUBLICATION
    assert "nonreceipt" in gap.message.lower() or "not proof" in gap.message.lower()

    snap = ledger.reconcile(MATTER)
    assert snap.has_gaps
    assert all(g.is_proof_of_nonreceipt is False for g in snap.gaps)
    assert "not proof of nonreceipt" in " ".join(snap.notes).lower() or snap.has_gaps


def test_available_inventory_requires_digest() -> None:
    ledger = _ledger()
    with pytest.raises(MatterLedgerError) as exc:
        ledger.ingest_inventory_item(
            matter_id=MATTER,
            source_document_id="odp-doc-1",
            available=True,
        )
    assert exc.value.code == "missing_content_sha256"


def test_available_inventory_admitted() -> None:
    ledger = _ledger()
    result = ledger.ingest_inventory_item(
        matter_id=MATTER,
        source_document_id="odp-doc-1",
        available=True,
        content_sha256=DIGEST_A,
        size_bytes=99,
        media_type="application/pdf",
        artifact_id="art-odp-1",
    )
    assert result.disposition is IngestDisposition.ADMITTED
    assert result.entry is not None
    assert result.entry.item_kind is LedgerItemKind.FILE_WRAPPER_DOCUMENT
    assert result.entry.presence is LedgerPresence.PRESENT


# ---------------------------------------------------------------------------
# Versioning: never overwrite history
# ---------------------------------------------------------------------------


def test_same_content_is_deduplicated_not_overwritten() -> None:
    ledger = _ledger()
    man = _manifest(artifact_id="art-v", sha256=DIGEST_A, labels={"role": "original_submission", "logical_id": "spec-body"})
    r1 = ledger.ingest_artifact(matter_id=MATTER, manifest=man, logical_id="spec-body")
    r2 = ledger.ingest_artifact(matter_id=MATTER, manifest=man, logical_id="spec-body")
    assert r1.disposition is IngestDisposition.ADMITTED
    assert r2.disposition is IngestDisposition.DEDUPLICATED
    assert r1.entry is not None and r2.entry is not None
    assert r1.entry.entry_id == r2.entry.entry_id
    assert r1.entry.version == 1
    history = ledger.history(MATTER)
    assert len(history) == 1


def test_changed_content_versions_without_overwriting() -> None:
    ledger = _ledger()
    m1 = _manifest(
        artifact_id="art-v1",
        sha256=DIGEST_A,
        labels={"role": "original_submission", "logical_id": "spec-body"},
    )
    m2 = _manifest(
        artifact_id="art-v2",
        sha256=DIGEST_B,
        labels={"role": "original_submission", "logical_id": "spec-body"},
    )
    r1 = ledger.ingest_artifact(matter_id=MATTER, manifest=m1, logical_id="spec-body")
    r2 = ledger.ingest_artifact(matter_id=MATTER, manifest=m2, logical_id="spec-body")
    assert r1.disposition is IngestDisposition.ADMITTED
    assert r2.disposition is IngestDisposition.VERSIONED
    assert r1.entry is not None and r2.entry is not None
    assert r1.entry.version == 1
    assert r2.entry.version == 2
    assert r1.entry.entry_id != r2.entry.entry_id
    # Both versions retained.
    history = ledger.history(MATTER)
    assert len(history) == 2
    assert {h.version for h in history} == {1, 2}
    # Store refuses overwrite of entry_id.
    store = ledger.store
    assert isinstance(store, InMemoryLedgerStore)
    assert store.append_entry(r1.entry) is False
    still = store.get_entry(MATTER, r1.entry.entry_id)
    assert still is not None
    assert still.content_sha256 == DIGEST_A

    snap = ledger.reconcile(MATTER)
    assert snap.current_by_logical_id["spec-body"] == r2.entry.entry_id
    assert r1.entry.entry_id in snap.history_entry_ids
    assert r2.entry.entry_id in snap.history_entry_ids


def test_append_entry_collision_with_different_body_raises() -> None:
    store = InMemoryLedgerStore()
    entry = LedgerEntry(
        schema_version=MATTER_LEDGER_SCHEMA_VERSION,
        entry_id="le:same",
        matter_id=MATTER,
        logical_id="x",
        item_kind=LedgerItemKind.OTHER,
        authority_relation=AuthorityRelation.UNKNOWN,
        presence=LedgerPresence.PRESENT,
        version=1,
        content_sha256=DIGEST_A,
        size_bytes=1,
        artifact_id=None,
        parent_entry_ids=(),
        parent_artifact_ids=(),
        related_entry_ids=(),
        source_receipt_id=None,
        channel=LedgerChannel.MANUAL,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        media_type=None,
        event_kind=None,
        event_utc=None,
        admitted_utc="2026-08-03T12:00:00Z",
        labels={},
        notes=(),
    )
    assert store.append_entry(entry) is True
    twin = LedgerEntry(
        schema_version=MATTER_LEDGER_SCHEMA_VERSION,
        entry_id="le:same",
        matter_id=MATTER,
        logical_id="x",
        item_kind=LedgerItemKind.OTHER,
        authority_relation=AuthorityRelation.UNKNOWN,
        presence=LedgerPresence.PRESENT,
        version=1,
        content_sha256=DIGEST_B,  # different body, same id
        size_bytes=1,
        artifact_id=None,
        parent_entry_ids=(),
        parent_artifact_ids=(),
        related_entry_ids=(),
        source_receipt_id=None,
        channel=LedgerChannel.MANUAL,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        media_type=None,
        event_kind=None,
        event_utc=None,
        admitted_utc="2026-08-03T12:00:00Z",
        labels={},
        notes=(),
    )
    with pytest.raises(MatterLedgerError) as exc:
        store.append_entry(twin)
    assert exc.value.code == "entry_id_collision"


# ---------------------------------------------------------------------------
# Claim sets and amendments
# ---------------------------------------------------------------------------


def test_claim_set_versions_and_current() -> None:
    ledger = _ledger()
    r1 = ledger.record_claim_set(matter_id=MATTER, content_sha256=DIGEST_A)
    r2 = ledger.record_claim_set(matter_id=MATTER, content_sha256=DIGEST_B)
    assert r1.disposition is IngestDisposition.ADMITTED
    assert r2.disposition is IngestDisposition.VERSIONED
    snap = ledger.reconcile(MATTER)
    assert len(snap.claim_sets) == 2
    current = snap.current_claim_set()
    assert current is not None
    assert current.content_sha256 == DIGEST_B
    assert current.version == 2
    _assert_round_trip(current)


def test_amendment_recorded_as_authoritative() -> None:
    ledger = _ledger()
    result = ledger.record_amendment(
        matter_id=MATTER,
        content_sha256=DIGEST_A,
        logical_id="amendment:2025-06-01",
        event_utc="2025-06-01T00:00:00Z",
    )
    assert result.ok
    assert result.entry is not None
    assert result.entry.item_kind is LedgerItemKind.AMENDMENT
    assert result.entry.is_authoritative_original
    assert result.entry.event_kind is MatterEventKind.RESPONSE


# ---------------------------------------------------------------------------
# Status / transaction events
# ---------------------------------------------------------------------------


def test_ingest_status_and_transaction_events() -> None:
    ledger = _ledger()
    status = MatterEvent(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        event_id="status-1",
        matter_id=MATTER,
        kind=MatterEventKind.STATUS,
        event_utc="2026-01-15T12:00:00Z",
        source_receipt_id="rcpt-1",
        description_digest=DIGEST_A,
        related_artifact_ids=(),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        metadata={"status_code": "150"},
    )
    txn = MatterEvent(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        event_id="txn-ctnf",
        matter_id=MATTER,
        kind=MatterEventKind.TRANSACTION,
        event_utc="2025-06-01T00:00:00Z",
        source_receipt_id="rcpt-2",
        description_digest=DIGEST_B,
        related_artifact_ids=(),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        metadata={"event_code": "CTNF"},
    )
    rs = ledger.ingest_event(matter_id=MATTER, event=status)
    rt = ledger.ingest_event(matter_id=MATTER, event=txn)
    assert rs.entry is not None and rt.entry is not None
    assert rs.entry.item_kind is LedgerItemKind.STATUS_EVENT
    assert rt.entry.item_kind is LedgerItemKind.TRANSACTION_EVENT
    # Idempotent re-ingest.
    rs2 = ledger.ingest_event(matter_id=MATTER, event=status)
    assert rs2.disposition is IngestDisposition.DEDUPLICATED


def test_source_receipt_ingest() -> None:
    ledger = _ledger()
    receipt = SourceReceipt(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        receipt_id="rcpt-auth-1",
        endpoint="local://authorized-patent-center-export",
        retrieval_utc="2026-08-01T10:00:00Z",
        response_status=200,
        upstream_id="export-1",
        last_modified=None,
        request_digest=DIGEST_A,
        response_digest=DIGEST_B,
        cache_hit=False,
        retry_count=0,
        metadata={"authorization_id": "auth-1"},
    )
    result = ledger.ingest_source_receipt(matter_id=MATTER, receipt=receipt)
    assert result.ok
    assert result.entry is not None
    assert result.entry.source_receipt_id == "rcpt-auth-1"


# ---------------------------------------------------------------------------
# Link derivative / structural reconcile
# ---------------------------------------------------------------------------


def test_link_derivative_preserves_both_entries() -> None:
    ledger = _ledger()
    orig = ledger.ingest_artifact(
        matter_id=MATTER,
        manifest=_manifest(artifact_id="art-docx", sha256=DIGEST_A),
        logical_id="spec",
    )
    # Derivative admitted without parent first.
    der = ledger.ingest_artifact(
        matter_id=MATTER,
        manifest=_manifest(
            artifact_id="art-pdf",
            sha256=DIGEST_B,
            media_type="application/pdf",
            authority=AuthorityRelation.DERIVATIVE,
            parents=(),
            labels={"role": "uspto_converted_pdf"},
        ),
        logical_id="spec-pdf",
    )
    assert orig.entry is not None and der.entry is not None
    # Gap for missing parent at ingest.
    assert any(g.code is GapCode.CONVERSION_WITHOUT_ORIGINAL for g in der.gaps)

    linked = ledger.link_derivative(
        matter_id=MATTER,
        original_entry_id=orig.entry.entry_id,
        derivative_entry_id=der.entry.entry_id,
    )
    assert linked.entry is not None
    assert linked.entry.is_derivative
    assert orig.entry.entry_id in linked.entry.parent_entry_ids
    assert "art-docx" in linked.entry.parent_artifact_ids
    # Prior derivative retained in history.
    history = ledger.history(MATTER)
    assert len(history) >= 3  # original + unlinked der + linked der version


def test_receipt_without_original_records_gap() -> None:
    ledger = _ledger()
    ledger.ingest_artifact(
        matter_id=MATTER,
        manifest=_manifest(
            artifact_id="art-ack-only",
            sha256=DIGEST_A,
            media_type="text/plain",
            labels={"role": "acknowledgement"},
        ),
    )
    snap = ledger.reconcile(MATTER)
    assert any(g.code is GapCode.RECEIPT_WITHOUT_ORIGINAL for g in snap.gaps)


# ---------------------------------------------------------------------------
# Replay determinism
# ---------------------------------------------------------------------------


def test_replay_yields_same_ledger_and_never_overwrites() -> None:
    ops: list[dict[str, Any]] = [
        {
            "op": "artifact",
            "manifest": _manifest(
                artifact_id="art-docx",
                sha256=DIGEST_A,
                labels={"role": "original_submission", "logical_id": "spec"},
            ).to_dict(),
            "logical_id": "spec",
        },
        {
            "op": "artifact",
            "manifest": _manifest(
                artifact_id="art-pdf",
                sha256=DIGEST_B,
                media_type="application/pdf",
                authority=AuthorityRelation.DERIVATIVE,
                parents=("art-docx",),
                labels={"role": "uspto_converted_pdf", "logical_id": "spec-pdf"},
            ).to_dict(),
            "logical_id": "spec-pdf",
        },
        {
            "op": "inventory",
            "source_document_id": "odp-missing-1",
            "available": False,
            "delayed": True,
        },
        {
            "op": "claim_set",
            "content_sha256": DIGEST_C,
        },
        {
            "op": "artifact",
            "manifest": _manifest(
                artifact_id="art-wrong",
                sha256=DIGEST_A,
                matter_id=MATTER_OTHER,
            ).to_dict(),
        },
    ]

    ledger_a = MatterLedger(InMemoryLedgerStore(), wall_clock=_fixed_clock("2026-08-03T12:00:00Z"))
    snap_a = ledger_a.replay(MATTER, ops)

    ledger_b = MatterLedger(InMemoryLedgerStore(), wall_clock=_fixed_clock("2026-08-03T18:00:00Z"))
    snap_b = ledger_b.replay(MATTER, ops)

    # Content digest is clock-independent.
    assert snap_a.content_digest == snap_b.content_digest
    assert snap_a.snapshot_id == snap_b.snapshot_id
    assert [e.entry_id for e in snap_a.entries] == [e.entry_id for e in snap_b.entries]
    assert [c.conflict_id for c in snap_a.conflicts] == [
        c.conflict_id for c in snap_b.conflicts
    ]
    assert [g.gap_id for g in snap_a.gaps] == [g.gap_id for g in snap_b.gaps]
    assert [q.quarantine_id for q in snap_a.quarantines] == [
        q.quarantine_id for q in snap_b.quarantines
    ]

    # Replaying ops again on the same ledger is idempotent (no new history rows
    # for identical content).
    before = len(ledger_a.history(MATTER))
    ledger_a.replay(MATTER, ops, reset_store=False)
    after = len(ledger_a.history(MATTER))
    assert after == before

    # Snapshot round-trip.
    _assert_round_trip(snap_a)
    assert snap_a.has_gaps
    assert snap_a.has_quarantines
    assert any(e.is_authoritative_original for e in snap_a.entries)
    assert any(e.is_derivative for e in snap_a.entries)


def test_reconcile_snapshot_round_trip() -> None:
    ledger = _ledger()
    ledger.ingest_artifact(matter_id=MATTER, manifest=_manifest())
    snap = ledger.reconcile(MATTER)
    assert snap.schema_version == MATTER_LEDGER_SCHEMA_VERSION
    _assert_round_trip(snap)
    restored = MatterLedgerSnapshot.from_dict(snap.to_dict())
    assert restored.content_digest == snap.content_digest


def test_ingest_result_to_dict_shape() -> None:
    ledger = _ledger()
    result = ledger.ingest_artifact(matter_id=MATTER, manifest=_manifest())
    payload = result.to_dict()
    assert payload["ok"] is True
    assert payload["disposition"] == IngestDisposition.ADMITTED.value
    assert payload["entry"]["matter_id"] == MATTER

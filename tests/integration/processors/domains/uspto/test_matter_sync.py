"""Integration tests for matter ledger reconciliation (PATLAW-025).

Exercises the full reconciliation path using:

* authorized private Patent Center export fixtures (original DOCX, converted
  PDF, acknowledgement, payment receipt);
* synthetic public file-wrapper inventory (including delayed/missing bytes);
* status / transaction events; and
* claim-set / amendment versions.

Validates acceptance criteria:

* conflicts and missing/delayed items remain explicit;
* authoritative original versus derivative is preserved;
* wrong matter identifiers are quarantined;
* replay yields the same ledger and never overwrites history.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    MatterEvent,
    MatterEventKind,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.matter_ledger import (
    MATTER_LEDGER_SCHEMA_VERSION,
    ConflictCode,
    GapCode,
    GapInterpretation,
    InMemoryLedgerStore,
    IngestDisposition,
    LedgerChannel,
    LedgerItemKind,
    LedgerPresence,
    MatterLedger,
    build_manifest_for_ledger,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    PrivateArtifactStore,
    generate_tenant_key,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_center_export import (
    PatentCenterExportProvider,
    load_fixture_authorization,
    load_fixture_manifest,
)

# tests/integration/processors/domains/uspto → parents[4] == tests/
FIXTURE_DIR = (
    Path(__file__).resolve().parents[4] / "fixtures" / "uspto" / "private_import"
)
MATTER = "matter:syn:16-000001"
WRONG_MATTER = "matter:syn:99-999999"
FIXED_UTC = "2026-08-03T12:00:00Z"


def _fixed_clock(when: str = FIXED_UTC):
    return lambda: when


@pytest.fixture
def private_import_batch(tmp_path: Path):
    """Import the authorized private export fixture into a tenant store."""
    assert (FIXTURE_DIR / "export_manifest.json").is_file()
    key = generate_tenant_key("tenant-ledger-it")
    store = PrivateArtifactStore(tmp_path / "private_store", key)
    provider = PatentCenterExportProvider(store)
    import_root = FIXTURE_DIR
    auth = load_fixture_authorization(
        FIXTURE_DIR, import_root=import_root, tenant_id="tenant-ledger-it"
    )
    manifest = load_fixture_manifest(FIXTURE_DIR)
    batch = provider.import_export(
        import_root=import_root, manifest=manifest, authorization=auth
    )
    assert batch.rejected_count == 0
    assert batch.imported_count == len(manifest.entries)
    return batch, manifest, store


def _ledger() -> MatterLedger:
    return MatterLedger(InMemoryLedgerStore(), wall_clock=_fixed_clock())


def _ingest_private_batch(ledger: MatterLedger, batch, export_manifest) -> list:
    """Project imported private artifacts into the matter ledger.

    ``ImportedArtifactResult.manifest`` is a privacy-redacted dict (not a full
    ``ArtifactManifest``). Rebuild ledger manifests from the export entry plus
    import result digests / artifact ids.
    """
    results = []
    # Map relative_path → artifact_id from import results for parent linking.
    by_path: dict[str, str] = {}
    for result, entry in zip(batch.results, export_manifest.entries):
        if result.status in ("imported", "skipped_idempotent") and result.artifact_id:
            by_path[entry.relative_path] = result.artifact_id

    for result, entry in zip(batch.results, export_manifest.entries):
        if result.status not in ("imported", "skipped_idempotent"):
            continue
        if not result.artifact_id or not result.sha256:
            continue
        parent_ids = tuple(
            by_path[p] for p in entry.parent_relative_paths if p in by_path
        )
        # Import result manifest is a redacted dict; size may be present.
        man_dict = dict(result.manifest or {})
        size_bytes = int(man_dict.get("size_bytes") or 0)
        labels = dict(entry.labels)
        labels.setdefault("export_id", export_manifest.export_id)
        labels.setdefault("relative_path", entry.relative_path)
        rebuilt = build_manifest_for_ledger(
            artifact_id=result.artifact_id,
            sha256=result.sha256,
            size_bytes=size_bytes,
            matter_id=export_manifest.matter_id,
            classification=entry.classification,
            media_type=entry.media_type,
            authority_relation=entry.authority_relation,
            parent_artifact_ids=parent_ids,
            source_receipt_id=batch.source_receipt.receipt_id,
            labels=labels,
        )
        ir = ledger.ingest_artifact(
            matter_id=export_manifest.matter_id,
            manifest=rebuilt,
            channel=LedgerChannel.PRIVATE_IMPORT,
        )
        results.append(ir)
    # Authorization / import receipt as acknowledgement surface.
    ledger.ingest_source_receipt(
        matter_id=export_manifest.matter_id,
        receipt=batch.source_receipt,
        item_kind=LedgerItemKind.ACKNOWLEDGEMENT,
        channel=LedgerChannel.PRIVATE_IMPORT,
    )
    return results


# ---------------------------------------------------------------------------
# End-to-end: private import + public inventory + status → ledger
# ---------------------------------------------------------------------------


def test_matter_sync_reconciles_private_and_public_surfaces(
    private_import_batch,
) -> None:
    batch, export_manifest, _store = private_import_batch
    assert export_manifest.matter_id == MATTER

    ledger = _ledger()
    private_results = _ingest_private_batch(ledger, batch, export_manifest)
    assert all(r.ok for r in private_results)
    assert any(
        r.entry is not None and r.entry.item_kind is LedgerItemKind.ORIGINAL_SUBMISSION
        for r in private_results
    )
    assert any(
        r.entry is not None and r.entry.item_kind is LedgerItemKind.CONVERTED_RENDERING
        for r in private_results
    )
    assert any(
        r.entry is not None and r.entry.item_kind is LedgerItemKind.ACKNOWLEDGEMENT
        for r in private_results
    )
    assert any(
        r.entry is not None and r.entry.item_kind is LedgerItemKind.PAYMENT_RECEIPT
        for r in private_results
    )

    # Public file-wrapper inventory: one present document + one delayed.
    present_bytes = b"%PDF-1.4 public office action fixture\n%%EOF\n"
    present_sha = sha256_hex(present_bytes)
    ledger.ingest_inventory_item(
        matter_id=MATTER,
        source_document_id="odp-oa-001",
        available=True,
        content_sha256=present_sha,
        size_bytes=len(present_bytes),
        media_type="application/pdf",
        artifact_id="art-odp-oa-001",
        labels={"document_code": "CTNF", "document_description": "Non-Final Rejection"},
        channel=LedgerChannel.PUBLIC_FILE_WRAPPER,
    )
    delayed = ledger.ingest_inventory_item(
        matter_id=MATTER,
        source_document_id="odp-doc-pending-bytes",
        available=False,
        delayed=True,
        labels={"document_code": "NPL", "document_description": "Cited NPL"},
        channel=LedgerChannel.PUBLIC_FILE_WRAPPER,
    )
    assert delayed.disposition is IngestDisposition.GAP_RECORDED
    assert delayed.gaps[0].is_proof_of_nonreceipt is False
    assert delayed.gaps[0].interpretation is GapInterpretation.FRESHNESS_GAP

    # Status + transaction events from public ODP surface.
    ledger.ingest_event(
        matter_id=MATTER,
        event=MatterEvent(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            event_id="status:docketed",
            matter_id=MATTER,
            kind=MatterEventKind.STATUS,
            event_utc="2026-01-15T12:00:00Z",
            source_receipt_id="odp-rcpt-status",
            description_digest=hashlib.sha256(b"status-150").hexdigest(),
            related_artifact_ids=(),
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            metadata={
                "status_code": "150",
                "status_text": "Docketed New Case - Ready for Examination",
            },
        ),
        channel=LedgerChannel.STATUS_API,
    )
    ledger.ingest_event(
        matter_id=MATTER,
        event=MatterEvent(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            event_id="txn:ctnf",
            matter_id=MATTER,
            kind=MatterEventKind.TRANSACTION,
            event_utc="2025-06-01T00:00:00Z",
            source_receipt_id="odp-rcpt-txn",
            description_digest=hashlib.sha256(b"CTNF").hexdigest(),
            related_artifact_ids=("art-odp-oa-001",),
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            metadata={"event_code": "CTNF"},
        ),
        channel=LedgerChannel.STATUS_API,
    )

    # GUI/export metadata + claim set + amendment.
    ledger.ingest_gui_metadata(
        matter_id=MATTER,
        logical_id="gui:spec-desc",
        metadata={
            "document_description": "Specification",
            "document_code": "SPEC",
            "source": "patent_center_export",
        },
    )
    claim_v1 = hashlib.sha256(b"claims v1").hexdigest()
    claim_v2 = hashlib.sha256(b"claims v2 after amendment").hexdigest()
    ledger.record_claim_set(matter_id=MATTER, content_sha256=claim_v1)
    ledger.record_amendment(
        matter_id=MATTER,
        content_sha256=hashlib.sha256(b"amendment body").hexdigest(),
        logical_id="amendment:2025-09-01",
        event_utc="2025-09-01T00:00:00Z",
    )
    ledger.record_claim_set(matter_id=MATTER, content_sha256=claim_v2)

    # Wrong-matter artifact is quarantined, not admitted.
    wrong = build_manifest_for_ledger(
        artifact_id="art-wrong-matter",
        sha256=hashlib.sha256(b"foreign matter bytes").hexdigest(),
        size_bytes=32,
        matter_id=WRONG_MATTER,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        media_type="application/pdf",
        authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
        labels={"role": "original_submission"},
    )
    q = ledger.ingest_artifact(matter_id=MATTER, manifest=wrong)
    assert q.disposition is IngestDisposition.QUARANTINED
    assert q.quarantine is not None

    snap = ledger.reconcile(MATTER)
    assert snap.schema_version == MATTER_LEDGER_SCHEMA_VERSION
    assert snap.matter_id == MATTER

    # --- Acceptance: authoritative original vs derivative preserved ---
    originals = snap.originals()
    derivatives = snap.derivatives()
    assert originals, "expected at least one authoritative original"
    assert derivatives, "expected at least one derivative (converted PDF)"
    for der in derivatives:
        # Converted PDF from private import must reference original parent.
        if der.item_kind is LedgerItemKind.CONVERTED_RENDERING:
            assert der.parent_artifact_ids or der.parent_entry_ids
            assert der.authority_relation is AuthorityRelation.DERIVATIVE
    # Originals are never demoted to derivative by reconciliation.
    for orig in originals:
        if orig.item_kind is LedgerItemKind.ORIGINAL_SUBMISSION:
            assert orig.authority_relation is AuthorityRelation.AUTHORITATIVE_ORIGINAL

    # --- Acceptance: conflicts and missing/delayed remain explicit ---
    assert snap.has_gaps
    delayed_gaps = [
        g
        for g in snap.gaps
        if g.code in (GapCode.DELAYED_PUBLICATION, GapCode.INVENTORY_WITHOUT_BYTES)
    ]
    assert delayed_gaps
    assert all(g.is_proof_of_nonreceipt is False for g in snap.gaps)
    assert any(
        g.interpretation is GapInterpretation.FRESHNESS_GAP for g in delayed_gaps
    )
    # Delayed inventory placeholder is present with DELAYED presence.
    delayed_entries = [
        e
        for e in snap.entries
        if e.logical_id == "odp-doc-pending-bytes"
    ]
    assert delayed_entries
    assert delayed_entries[0].presence is LedgerPresence.DELAYED

    # Matter-id mismatch conflict is explicit.
    assert any(c.code is ConflictCode.MATTER_ID_MISMATCH for c in snap.conflicts)

    # --- Acceptance: wrong matter identifiers quarantined ---
    assert snap.has_quarantines
    assert any(
        q.observed_matter_id == WRONG_MATTER for q in snap.quarantines
    )
    assert all(e.artifact_id != "art-wrong-matter" for e in snap.entries)

    # --- Claim-set versions ---
    assert len(snap.claim_sets) == 2
    current = snap.current_claim_set()
    assert current is not None
    assert current.content_sha256 == claim_v2
    assert current.version == 2

    # Status / transaction entries present.
    kinds = {e.item_kind for e in snap.entries}
    assert LedgerItemKind.STATUS_EVENT in kinds
    assert LedgerItemKind.TRANSACTION_EVENT in kinds
    assert LedgerItemKind.GUI_METADATA in kinds
    assert LedgerItemKind.AMENDMENT in kinds
    assert LedgerItemKind.FILE_WRAPPER_DOCUMENT in kinds

    # Snapshot is serializable and round-trips.
    restored = type(snap).from_dict(snap.to_dict())
    assert restored.content_digest == snap.content_digest
    assert canonical_json(restored.to_dict()) == canonical_json(snap.to_dict())


# ---------------------------------------------------------------------------
# Replay equality + history immutability
# ---------------------------------------------------------------------------


def test_matter_sync_replay_is_deterministic_and_append_only(
    private_import_batch,
) -> None:
    batch, export_manifest, _store = private_import_batch

    def build_ops() -> list[dict]:
        ops: list[dict] = []
        by_path: dict[str, str] = {}
        for result, entry in zip(batch.results, export_manifest.entries):
            if result.status in ("imported", "skipped_idempotent") and result.artifact_id:
                by_path[entry.relative_path] = result.artifact_id
        for result, entry in zip(batch.results, export_manifest.entries):
            if result.status not in ("imported", "skipped_idempotent"):
                continue
            if not result.artifact_id or not result.sha256:
                continue
            parent_ids = tuple(
                by_path[p] for p in entry.parent_relative_paths if p in by_path
            )
            man_dict = dict(result.manifest or {})
            size_bytes = int(man_dict.get("size_bytes") or 0)
            labels = dict(entry.labels)
            labels.setdefault("export_id", export_manifest.export_id)
            labels.setdefault("relative_path", entry.relative_path)
            rebuilt = build_manifest_for_ledger(
                artifact_id=result.artifact_id,
                sha256=result.sha256,
                size_bytes=size_bytes,
                matter_id=export_manifest.matter_id,
                classification=entry.classification,
                media_type=entry.media_type,
                authority_relation=entry.authority_relation,
                parent_artifact_ids=parent_ids,
                source_receipt_id=batch.source_receipt.receipt_id,
                labels=labels,
            )
            ops.append(
                {
                    "op": "artifact",
                    "manifest": rebuilt.to_dict(),
                    "channel": LedgerChannel.PRIVATE_IMPORT.value,
                }
            )
        ops.append(
            {
                "op": "inventory",
                "source_document_id": "odp-delayed-x",
                "available": False,
                "delayed": True,
            }
        )
        ops.append(
            {
                "op": "inventory",
                "source_document_id": "odp-present-x",
                "available": True,
                "content_sha256": "1" * 64,
                "size_bytes": 10,
                "media_type": "application/pdf",
                "artifact_id": "art-odp-present-x",
            }
        )
        ops.append(
            {
                "op": "event",
                "event": {
                    "schema_version": CONTRACTS_SCHEMA_VERSION,
                    "event_id": "status:replay",
                    "matter_id": MATTER,
                    "kind": MatterEventKind.STATUS.value,
                    "event_utc": "2026-01-15T12:00:00Z",
                    "source_receipt_id": None,
                    "description_digest": "2" * 64,
                    "related_artifact_ids": [],
                    "classification": DisclosureClassification.PUBLIC_OFFICIAL.value,
                    "metadata": {"status_code": "150"},
                },
            }
        )
        ops.append({"op": "claim_set", "content_sha256": "3" * 64})
        ops.append(
            {
                "op": "artifact",
                "manifest": build_manifest_for_ledger(
                    artifact_id="art-foreign",
                    sha256="4" * 64,
                    size_bytes=4,
                    matter_id=WRONG_MATTER,
                    classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
                    media_type="application/pdf",
                    labels={"role": "original_submission"},
                ).to_dict(),
            }
        )
        # Version bump of claim set.
        ops.append({"op": "claim_set", "content_sha256": "5" * 64})
        return ops

    ops = build_ops()

    ledger_a = MatterLedger(
        InMemoryLedgerStore(), wall_clock=_fixed_clock("2026-08-03T12:00:00Z")
    )
    snap_a = ledger_a.replay(MATTER, ops)

    ledger_b = MatterLedger(
        InMemoryLedgerStore(), wall_clock=_fixed_clock("2099-01-01T00:00:00Z")
    )
    snap_b = ledger_b.replay(MATTER, ops)

    assert snap_a.content_digest == snap_b.content_digest
    assert snap_a.snapshot_id == snap_b.snapshot_id
    # Identity fields (entry_id / content) match; observational admitted_utc may differ.
    assert [e.entry_id for e in snap_a.entries] == [e.entry_id for e in snap_b.entries]
    assert [e.identity_payload() for e in snap_a.entries] == [
        e.identity_payload() for e in snap_b.entries
    ]
    assert [g.gap_id for g in snap_a.gaps] == [g.gap_id for g in snap_b.gaps]
    assert [q.quarantine_id for q in snap_a.quarantines] == [
        q.quarantine_id for q in snap_b.quarantines
    ]

    # Re-replay on same store: no history growth for identical content.
    hist_before = list(ledger_a.history(MATTER))
    ledger_a.replay(MATTER, ops, reset_store=False)
    hist_after = list(ledger_a.history(MATTER))
    assert [e.entry_id for e in hist_before] == [e.entry_id for e in hist_after]
    assert len(hist_after) == len(hist_before)

    # Explicit version history for claim sets: both digests retained.
    claim_entries = [
        e for e in hist_after if e.item_kind is LedgerItemKind.CLAIM_SET
    ]
    assert len(claim_entries) == 2
    assert {e.version for e in claim_entries} == {1, 2}
    assert {e.content_sha256 for e in claim_entries} == {"3" * 64, "5" * 64}

    # Store refuses overwrite.
    first = hist_after[0]
    assert ledger_a.store.append_entry(first) is False
    assert ledger_a.store.get_entry(MATTER, first.entry_id) == first


def test_matter_sync_idempotent_private_reimport(
    private_import_batch,
) -> None:
    """Re-importing the same private batch does not duplicate ledger entries."""
    batch, export_manifest, _store = private_import_batch
    ledger = _ledger()
    _ingest_private_batch(ledger, batch, export_manifest)
    first_hist = ledger.history(MATTER)
    _ingest_private_batch(ledger, batch, export_manifest)
    second_hist = ledger.history(MATTER)
    assert [e.entry_id for e in first_hist] == [e.entry_id for e in second_hist]

    snap1 = ledger.reconcile(MATTER)
    snap2 = ledger.reconcile(MATTER)
    assert snap1.content_digest == snap2.content_digest


def test_converted_pdf_never_overwrites_original(
    private_import_batch,
) -> None:
    batch, export_manifest, _store = private_import_batch
    ledger = _ledger()
    _ingest_private_batch(ledger, batch, export_manifest)
    snap = ledger.reconcile(MATTER)

    originals = [
        e
        for e in snap.entries
        if e.item_kind is LedgerItemKind.ORIGINAL_SUBMISSION
    ]
    conversions = [
        e
        for e in snap.entries
        if e.item_kind is LedgerItemKind.CONVERTED_RENDERING
    ]
    assert originals and conversions
    original_ids = {e.entry_id for e in originals}
    conversion_ids = {e.entry_id for e in conversions}
    assert original_ids.isdisjoint(conversion_ids)
    for conv in conversions:
        assert conv.authority_relation is AuthorityRelation.DERIVATIVE
        # Parent original artifact id is preserved on the derivative.
        assert conv.parent_artifact_ids
        parent_arts = set(conv.parent_artifact_ids)
        assert any(
            o.artifact_id in parent_arts for o in originals if o.artifact_id
        )


def test_gaps_json_export_never_claims_nonreceipt(
    private_import_batch,
) -> None:
    batch, export_manifest, _store = private_import_batch
    ledger = _ledger()
    _ingest_private_batch(ledger, batch, export_manifest)
    ledger.ingest_inventory_item(
        matter_id=MATTER,
        source_document_id="odp-gap-only",
        available=False,
        delayed=True,
    )
    snap = ledger.reconcile(MATTER)
    payload = json.loads(snap.to_canonical_json())
    for gap in payload["gaps"]:
        assert gap["is_proof_of_nonreceipt"] is False
        assert "nonreceipt" in gap["message"].lower() or gap[
            "interpretation"
        ] in {
            GapInterpretation.FRESHNESS_GAP.value,
            GapInterpretation.RETRIEVAL_GAP.value,
        }

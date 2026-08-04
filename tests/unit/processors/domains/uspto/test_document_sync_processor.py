"""Unit tests for DocumentSyncProcessor (PATLAW-023)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.document_sync_processor import (
    DOCUMENT_SYNC_SCHEMA_VERSION,
    FIXTURE_SCHEMA_VERSION,
    AdmittedDocumentStore,
    BoundedQuarantineSession,
    CheckpointStore,
    DocumentSyncKey,
    DocumentSyncOutcomeKind,
    DocumentSyncProcessor,
    DownloadBytesResult,
    GapInterpretation,
    InventoryDocument,
    MappingDocumentBytesDownloader,
    QuarantineError,
    build_update_marker,
    classify_unavailable,
    default_fixture_dir,
    load_document_sync_recipe,
    processor_from_recipe_case,
    recipe_case,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    ProviderOutcomeKind,
    sha256_hex,
)

# test file: tests/unit/processors/domains/uspto/ → parents[4] == tests/
FIXTURE_DIR = (
    Path(__file__).resolve().parents[4] / "fixtures" / "uspto" / "odp" / "documents"
)
RECIPE_PATH = FIXTURE_DIR / "odp_document_sync_recipe.json"

PDF_V1 = b"""%PDF-1.1
1 0 obj<<>>endobj
trailer<<>>
%%EOF
"""
PDF_V2 = b"""%PDF-1.1
1 0 obj<</Title(v2)>>endobj
trailer<<>>
%%EOF
"""
PDF_V1_SHA = sha256_hex(PDF_V1)
PDF_V2_SHA = sha256_hex(PDF_V2)


def _recipe() -> dict:
    return load_document_sync_recipe(RECIPE_PATH)


def _case(case_id: str) -> dict:
    return recipe_case(_recipe(), case_id)


def _processor_for(
    case_id: str,
    *,
    store: AdmittedDocumentStore | None = None,
    checkpoints: CheckpointStore | None = None,
    tmp_path: Path | None = None,
) -> tuple[DocumentSyncProcessor, str, list]:
    case = _case(case_id)
    # version cases may use downloads_v1 key instead of downloads
    if "downloads" not in case and "downloads_v1" in case:
        case = dict(case)
        case["downloads"] = case["downloads_v1"]
    qroot = None if tmp_path is None else tmp_path / "quarantine"
    return processor_from_recipe_case(
        case,
        store=store,
        checkpoints=checkpoints,
        quarantine_root=qroot,
        wall_clock_utc=lambda: "2026-08-03T12:00:00Z",
    )


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


def test_fixture_recipe_schema_and_default_dir() -> None:
    recipe = _recipe()
    assert recipe["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert default_fixture_dir().is_dir()
    assert (default_fixture_dir() / "odp_document_sync_recipe.json").is_file()
    case = _case("admit_public_pdf")
    assert case["application_number"] == "16123456"


# ---------------------------------------------------------------------------
# Happy path: admit public PDF
# ---------------------------------------------------------------------------


def test_admits_public_document_bytes(tmp_path: Path) -> None:
    proc, app, inventory = _processor_for("admit_public_pdf", tmp_path=tmp_path)
    with proc:
        result = proc.sync_inventory(app, inventory)

    assert result.ok
    assert result.inventory_count == 1
    assert result.admitted_count == 1
    item = result.items[0]
    assert item.kind is DocumentSyncOutcomeKind.ADMITTED
    assert item.source_document_id == "DOCID001"
    assert item.version == 1
    assert item.content_sha256 == PDF_V1_SHA
    assert item.media_type == "application/pdf"
    assert item.sync_key is not None
    assert item.sync_key == DocumentSyncKey("DOCID001", PDF_V1_SHA)

    stored = proc.store.latest("DOCID001")
    assert stored is not None
    assert stored.version == 1
    assert proc.store.get_bytes(stored.artifact_id) == PDF_V1
    manifest = proc.store.get_manifest(stored.artifact_id)
    assert manifest is not None
    assert manifest.sha256 == PDF_V1_SHA
    assert manifest.classification is DisclosureClassification.PUBLIC_OFFICIAL


# ---------------------------------------------------------------------------
# Same source ID + hash deduplicates
# ---------------------------------------------------------------------------


def test_same_source_id_and_hash_deduplicates(tmp_path: Path) -> None:
    store = AdmittedDocumentStore()
    checkpoints = CheckpointStore(root=tmp_path / "ckpts")
    proc, app, inventory = _processor_for(
        "admit_public_pdf", store=store, checkpoints=checkpoints, tmp_path=tmp_path
    )
    with proc:
        first = proc.sync_inventory(app, inventory)
        second = proc.sync_inventory(app, inventory)

    assert first.admitted_count == 1
    # Second run: markers unchanged → UNCHANGED (or DEDUPLICATED if forced).
    assert second.items[0].kind is DocumentSyncOutcomeKind.UNCHANGED
    assert len(store.versions_for("DOCID001")) == 1
    assert store.version_count == 1

    # Force re-download of identical bytes → DEDUPLICATED, still one version.
    with DocumentSyncProcessor(
        downloader=proc._downloader,  # noqa: SLF001
        store=store,
        checkpoints=checkpoints,
        quarantine_root=tmp_path / "q2",
        wall_clock_utc=lambda: "2026-08-03T12:05:00Z",
    ) as forced:
        third = forced.sync_inventory(app, inventory, force_download=True)

    assert third.items[0].kind is DocumentSyncOutcomeKind.DEDUPLICATED
    assert third.deduplicated_count == 1
    assert len(store.versions_for("DOCID001")) == 1
    assert third.items[0].content_sha256 == PDF_V1_SHA
    assert third.items[0].artifact_id == first.items[0].artifact_id


# ---------------------------------------------------------------------------
# Changed bytes create a new version
# ---------------------------------------------------------------------------


def test_changed_bytes_create_new_version(tmp_path: Path) -> None:
    store = AdmittedDocumentStore()
    checkpoints = CheckpointStore(root=tmp_path / "ckpts")
    case = _case("version_on_changed_bytes")
    app = case["application_number"]
    inventory_v1 = [
        InventoryDocument.from_mapping(case["documents"][0], application_number=app)
    ]
    downloader = MappingDocumentBytesDownloader(case["downloads_v1"])
    proc = DocumentSyncProcessor(
        downloader=downloader,
        store=store,
        checkpoints=checkpoints,
        quarantine_root=tmp_path / "q",
        wall_clock_utc=lambda: "2026-08-03T12:00:00Z",
    )
    with proc:
        r1 = proc.sync_inventory(app, inventory_v1)
    assert r1.items[0].kind is DocumentSyncOutcomeKind.ADMITTED
    assert r1.items[0].version == 1
    assert r1.items[0].content_sha256 == PDF_V1_SHA

    # New marker + new bytes → version 2.
    inventory_v2 = [
        InventoryDocument.from_mapping(case["documents_v2_marker"], application_number=app)
    ]
    downloader_v2 = MappingDocumentBytesDownloader(case["downloads_v2"])
    proc2 = DocumentSyncProcessor(
        downloader=downloader_v2,
        store=store,
        checkpoints=checkpoints,
        quarantine_root=tmp_path / "q2",
        wall_clock_utc=lambda: "2026-08-03T13:00:00Z",
    )
    with proc2:
        r2 = proc2.sync_inventory(app, inventory_v2)

    assert r2.items[0].kind is DocumentSyncOutcomeKind.VERSIONED
    assert r2.versioned_count == 1
    assert r2.items[0].version == 2
    assert r2.items[0].content_sha256 == PDF_V2_SHA
    versions = store.versions_for("DOCID001")
    assert len(versions) == 2
    assert versions[0].content_sha256 == PDF_V1_SHA
    assert versions[1].content_sha256 == PDF_V2_SHA
    # History is immutable — both digests remain available.
    assert store.get_bytes(versions[0].artifact_id) == PDF_V1
    assert store.get_bytes(versions[1].artifact_id) == PDF_V2
    # Distinct sync keys.
    assert versions[0].sync_key != versions[1].sync_key


# ---------------------------------------------------------------------------
# Partial downloads never become admitted artifacts
# ---------------------------------------------------------------------------


def test_partial_download_never_admitted(tmp_path: Path) -> None:
    store = AdmittedDocumentStore()
    proc, app, inventory = _processor_for(
        "partial_download_rejected", store=store, tmp_path=tmp_path
    )
    with proc:
        result = proc.sync_inventory(app, inventory)

    assert result.partial_rejected_count == 1
    item = result.items[0]
    assert item.kind is DocumentSyncOutcomeKind.PARTIAL_REJECTED
    assert item.error_code == "partial_download"
    assert store.version_count == 0
    assert store.latest("DOCID-PARTIAL") is None
    assert item.artifact_id is None


def test_size_mismatch_never_admitted(tmp_path: Path) -> None:
    store = AdmittedDocumentStore()
    proc, app, inventory = _processor_for(
        "size_mismatch_rejected", store=store, tmp_path=tmp_path
    )
    with proc:
        result = proc.sync_inventory(app, inventory)

    item = result.items[0]
    # Declared Content-Length/contentLength longer than body is treated as
    # partial (truncated) or explicit size_mismatch — never admitted either way.
    assert item.kind is DocumentSyncOutcomeKind.PARTIAL_REJECTED
    assert item.error_code in {"size_mismatch", "partial_download"}
    assert store.version_count == 0
    assert item.artifact_id is None


def test_quarantine_session_discards_on_truncation(tmp_path: Path) -> None:
    session = BoundedQuarantineSession(
        root=tmp_path / "q",
        source_document_id="DOCX",
        max_bytes=1024,
    )
    session.write(PDF_V1[:10])
    with pytest.raises(QuarantineError) as excinfo:
        session.admit(
            expected_size=len(PDF_V1),
            media_type="application/pdf",
            mime_type_identifier="PDF",
            truncated=True,
        )
    assert excinfo.value.code == "partial_download"
    # No admitted leftovers.
    parts = list((tmp_path / "q").glob("*"))
    assert parts == [] or all(p.suffix != ".admitted" for p in parts)


def test_quarantine_rejects_media_mismatch(tmp_path: Path) -> None:
    session = BoundedQuarantineSession(
        root=tmp_path / "q",
        source_document_id="NOTPDF",
        max_bytes=1024,
    )
    session.write_all(b"not-a-pdf-payload")
    with pytest.raises(QuarantineError) as excinfo:
        session.admit(
            media_type="application/pdf",
            mime_type_identifier="PDF",
        )
    assert excinfo.value.code == "media_mismatch"


# ---------------------------------------------------------------------------
# Unavailable NPL / private documents are explicit
# ---------------------------------------------------------------------------


def test_unavailable_npl_is_explicit(tmp_path: Path) -> None:
    proc, app, inventory = _processor_for("unavailable_npl_explicit", tmp_path=tmp_path)
    with proc:
        result = proc.sync_inventory(app, inventory)

    assert result.unavailable_count == 1
    item = result.items[0]
    assert item.kind is DocumentSyncOutcomeKind.UNAVAILABLE
    assert item.gap_interpretation is GapInterpretation.UNAVAILABLE_NPL
    assert item.is_nonreceipt is False
    assert "NPL" in (item.message or "").upper() or "npl" in (item.message or "")


def test_unavailable_private_is_explicit(tmp_path: Path) -> None:
    proc, app, inventory = _processor_for(
        "unavailable_private_explicit", tmp_path=tmp_path
    )
    with proc:
        result = proc.sync_inventory(app, inventory)

    item = result.items[0]
    assert item.kind is DocumentSyncOutcomeKind.UNAVAILABLE
    assert item.gap_interpretation is GapInterpretation.UNAVAILABLE_PRIVATE
    assert item.is_nonreceipt is False


def test_forbidden_download_marked_unavailable_private(tmp_path: Path) -> None:
    proc, app, inventory = _processor_for(
        "forbidden_download_private", tmp_path=tmp_path
    )
    with proc:
        result = proc.sync_inventory(app, inventory)

    item = result.items[0]
    assert item.kind is DocumentSyncOutcomeKind.UNAVAILABLE
    assert item.gap_interpretation is GapInterpretation.UNAVAILABLE_PRIVATE
    assert item.is_nonreceipt is False


def test_classify_unavailable_helpers() -> None:
    npl = InventoryDocument.from_mapping(
        {
            "documentIdentifier": "N1",
            "availability": "npl",
            "downloadOptionBag": [],
        },
        application_number="1",
    )
    is_u, interp, _ = classify_unavailable(npl)
    assert is_u and interp is GapInterpretation.UNAVAILABLE_NPL

    priv = InventoryDocument.from_mapping(
        {
            "documentIdentifier": "P1",
            "accessLimitation": "confidential",
            "downloadOptionBag": [],
        },
        application_number="1",
    )
    is_u, interp, _ = classify_unavailable(priv)
    assert is_u and interp is GapInterpretation.UNAVAILABLE_PRIVATE


# ---------------------------------------------------------------------------
# Delayed inventory is a freshness gap, not nonreceipt
# ---------------------------------------------------------------------------


def test_delayed_bytes_404_is_freshness_gap_not_nonreceipt(tmp_path: Path) -> None:
    proc, app, inventory = _processor_for(
        "delayed_inventory_freshness_gap", tmp_path=tmp_path
    )
    with proc:
        result = proc.sync_inventory(app, inventory)

    assert result.freshness_gap_count == 1
    item = result.items[0]
    assert item.kind is DocumentSyncOutcomeKind.FRESHNESS_GAP
    assert item.gap_interpretation is GapInterpretation.FRESHNESS_GAP
    assert item.is_nonreceipt is False
    assert "nonreceipt" not in (item.message or "").lower() or "not nonreceipt" in (
        item.message or ""
    ).lower()
    # No admitted artifact for the delayed doc.
    assert proc.store.latest("doc-9001") is None


def test_missing_download_options_is_freshness_gap(tmp_path: Path) -> None:
    proc, app, inventory = _processor_for(
        "no_download_options_freshness_gap", tmp_path=tmp_path
    )
    with proc:
        result = proc.sync_inventory(app, inventory)

    item = result.items[0]
    assert item.kind is DocumentSyncOutcomeKind.FRESHNESS_GAP
    assert item.is_nonreceipt is False
    # Constructing a freshness-gap item with is_nonreceipt=True must fail.
    with pytest.raises(ValueError, match="nonreceipt"):
        from ipfs_datasets_py.processors.domains.uspto.document_sync_processor import (
            DocumentSyncItemResult,
        )

        DocumentSyncItemResult(
            schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
            source_document_id="x",
            kind=DocumentSyncOutcomeKind.FRESHNESS_GAP,
            application_number="1",
            is_nonreceipt=True,
        )


# ---------------------------------------------------------------------------
# Mixed inventory + checkpoint durability
# ---------------------------------------------------------------------------


def test_mixed_inventory_outcomes(tmp_path: Path) -> None:
    proc, app, inventory = _processor_for("mixed_inventory", tmp_path=tmp_path)
    with proc:
        result = proc.sync_inventory(app, inventory)

    kinds = {item.source_document_id: item.kind for item in result.items}
    assert kinds["DOC-OK"] is DocumentSyncOutcomeKind.ADMITTED
    assert kinds["DOC-DELAYED"] is DocumentSyncOutcomeKind.FRESHNESS_GAP
    assert kinds["DOC-NPL"] is DocumentSyncOutcomeKind.UNAVAILABLE
    assert result.admitted_count == 1
    assert result.freshness_gap_count == 1
    assert result.unavailable_count == 1
    # Delayed item is never nonreceipt.
    delayed = next(i for i in result.items if i.source_document_id == "DOC-DELAYED")
    assert delayed.is_nonreceipt is False


def test_checkpoint_survives_restart(tmp_path: Path) -> None:
    ckpt_root = tmp_path / "ckpts"
    store = AdmittedDocumentStore(root=tmp_path / "store")
    proc, app, inventory = _processor_for(
        "admit_public_pdf",
        store=store,
        checkpoints=CheckpointStore(root=ckpt_root),
        tmp_path=tmp_path,
    )
    with proc:
        proc.sync_inventory(app, inventory)

    # New processor instance, same durable checkpoint + store index in memory
    # rebuilt empty — but checkpoint markers should still skip re-download when
    # store already holds the version (here we keep the same store object).
    proc2 = DocumentSyncProcessor(
        downloader=proc._downloader,  # noqa: SLF001
        store=store,
        checkpoints=CheckpointStore(root=ckpt_root),
        quarantine_root=tmp_path / "q-restart",
        wall_clock_utc=lambda: "2026-08-03T14:00:00Z",
    )
    with proc2:
        result = proc2.sync_inventory(app, inventory)
    assert result.items[0].kind is DocumentSyncOutcomeKind.UNCHANGED

    # Checkpoint file exists and is valid JSON.
    files = list(ckpt_root.glob("doc-sync-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["schema_version"] == DOCUMENT_SYNC_SCHEMA_VERSION
    assert "DOCID001" in payload["entries"]


def test_result_and_version_round_trip(tmp_path: Path) -> None:
    proc, app, inventory = _processor_for("admit_public_pdf", tmp_path=tmp_path)
    with proc:
        result = proc.sync_inventory(app, inventory)
    payload = result.to_dict()
    assert payload["schema_version"] == DOCUMENT_SYNC_SCHEMA_VERSION
    assert canonical_json(payload)  # deterministic encode
    record = proc.store.latest("DOCID001")
    assert record is not None
    restored = type(record).from_dict(record.to_dict())
    assert restored.to_dict() == record.to_dict()


def test_build_update_marker_stable() -> None:
    doc = InventoryDocument.from_mapping(
        {
            "documentIdentifier": "D1",
            "officialDate": "2020-01-01",
            "downloadOptionBag": [
                {
                    "mimeTypeIdentifier": "PDF",
                    "downloadUrl": "https://api.uspto.gov/api/v1/download/D1.pdf",
                    "pageTotalQuantity": 2,
                }
            ],
        },
        application_number="16123456",
    )
    m1 = build_update_marker(doc)
    m2 = build_update_marker(doc)
    assert m1.matches(m2)
    assert m1.raw_marker_digest == m2.raw_marker_digest


def test_mapping_downloader_fixture_miss() -> None:
    dl = MappingDocumentBytesDownloader()
    result = dl.download(
        "https://api.uspto.gov/api/v1/download/missing.pdf",
        document_identifier="missing",
    )
    assert result.kind is ProviderOutcomeKind.NOT_FOUND
    assert result.status_code == 404


def test_sync_key_rejects_bad_digest() -> None:
    with pytest.raises(ValueError):
        DocumentSyncKey(source_document_id="D1", content_sha256="not-a-hash")


def test_download_bytes_result_ok_flag() -> None:
    ok = DownloadBytesResult(
        kind=ProviderOutcomeKind.SUCCESS,
        status_code=200,
        body=PDF_V1,
    )
    assert ok.ok
    bad = DownloadBytesResult(
        kind=ProviderOutcomeKind.SUCCESS,
        status_code=200,
        body=PDF_V1[:5],
        truncated=True,
    )
    assert not bad.ok

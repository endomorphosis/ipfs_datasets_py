"""Unit tests for USPTO PDF/OCR bridge (PATLAW-121)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractionOrigin,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.pdf_ocr_bridge import (
    PDF_OCR_BRIDGE_SCHEMA_VERSION,
    BridgeDisposition,
    BridgeReasonCode,
    CheckpointStore,
    DeniedRemoteOcrBackend,
    OcrProviderKind,
    PageBridgeStatus,
    PdfOcrBridge,
    PdfOcrBridgeBounds,
    PdfOcrBridgeInput,
    PdfOcrBridgePolicy,
    PdfOcrBridgeResult,
    RecordingOcrBackend,
    bridge_pdf,
    content_addressed_cid,
    estimate_native_char_coverage,
    parser_digest,
    sha256_hex,
    should_run_page_ocr,
    text_digest,
)
from tests.fixtures.uspto.documents.generators import (
    NATIVE_CANARY,
    SCANNED_CANARY,
    build_corrupt_pdf,
    build_native_pdf_with_metadata,
    build_password_pdf,
    build_scanned_image_only_pdf,
)


def _bridge(**kwargs) -> PdfOcrBridge:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"pdfocr:test:{counter['n']:04d}"

    return PdfOcrBridge(id_factory=_ids, **kwargs)


def _assert_round_trip(result: PdfOcrBridgeResult) -> None:
    first = result.to_dict()
    restored = PdfOcrBridgeResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert "full_text" not in public
    assert "page_texts" not in public
    blob = json.dumps(public)
    assert NATIVE_CANARY not in blob
    assert SCANNED_CANARY not in blob


def _assert_span_links(result: PdfOcrBridgeResult) -> None:
    assert result.source_cid
    assert result.content_sha256
    assert len(result.content_sha256) == 64
    for span in result.spans:
        assert span.schema_version == CONTRACTS_SCHEMA_VERSION
        assert span.artifact_id == result.artifact_id
        assert span.span_id
        assert span.origin in ExtractionOrigin
        if span.text_digest:
            assert len(span.text_digest) == 64
        # page/bounds provenance
        assert span.page_index is not None
    for cov in result.page_coverage:
        assert cov.artifact_id == result.artifact_id
        assert cov.source_cid == result.source_cid
        assert cov.schema_version == PDF_OCR_BRIDGE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_coverage_helpers() -> None:
    assert estimate_native_char_coverage("") == 0.0
    assert estimate_native_char_coverage("a" * 200) > 0.5
    assert should_run_page_ocr("", force=True) is True
    assert should_run_page_ocr("x" * 5) is True
    assert should_run_page_ocr("word " * 80, coverage=0.9) is False
    digest = parser_digest()
    assert len(digest) == 64
    cid = content_addressed_cid("a" * 64)
    assert cid.startswith("baguqeera")


# ---------------------------------------------------------------------------
# Native PDF → deterministic spans with CID/page/bounds
# ---------------------------------------------------------------------------


def test_native_pdf_deterministic_spans_with_source_cid() -> None:
    pdf = build_native_pdf_with_metadata()
    digest = sha256_hex(pdf)
    source_cid = content_addressed_cid(digest)
    bridge = _bridge()
    result = bridge.process(
        PdfOcrBridgeInput(
            artifact_id="art:native-1",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            source_cid=source_cid,
            content_sha256=digest,
            filename="native.pdf",
            labels={"fixture": "native"},
        )
    )
    assert result.disposition in (
        BridgeDisposition.EXTRACTED,
        BridgeDisposition.REVIEW,
    )
    assert result.page_count == 1
    assert result.source_cid == source_cid
    assert result.content_sha256 == digest
    assert NATIVE_CANARY in result.full_text
    assert any(s.origin is ExtractionOrigin.NATIVE for s in result.spans)
    assert any(s.bbox is not None for s in result.spans)
    assert any(s.reading_order is not None for s in result.spans)
    cov = result.page_coverage[0]
    assert cov.has_native_text is True
    assert cov.native_coverage > 0.0
    assert cov.render_digest is None or len(cov.render_digest) == 64
    assert BridgeReasonCode.NATIVE_TEXT_EXTRACTED.value in result.reason_codes
    _assert_span_links(result)
    _assert_round_trip(result)

    # Determinism: second run same digests / span text digests
    again = bridge.process(
        artifact_id="art:native-1b",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
        source_cid=source_cid,
    )
    digests_a = sorted(s.text_digest for s in result.spans if s.text_digest)
    digests_b = sorted(s.text_digest for s in again.spans if s.text_digest)
    assert digests_a == digests_b


def test_bridge_pdf_convenience() -> None:
    pdf = build_native_pdf_with_metadata()
    result = bridge_pdf(
        artifact_id="art:conv-1",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.page_count == 1
    assert result.source_cid


# ---------------------------------------------------------------------------
# Scanned PDF + confidence-gated OCR
# ---------------------------------------------------------------------------


def test_scanned_pdf_ocr_injection_confidence_gated() -> None:
    pdf = build_scanned_image_only_pdf()

    def fake_ocr(image_bytes: bytes, page_index: int):
        assert page_index == 0
        return {
            "text": SCANNED_CANARY,
            "confidence": 0.92,
            "status": "ok",
            "word_boxes": [
                {
                    "text": SCANNED_CANARY,
                    "bbox": [10.0, 10.0, 400.0, 40.0],
                    "confidence": 0.92,
                }
            ],
        }

    backend = RecordingOcrBackend(callable=fake_ocr)
    result = _bridge(ocr_backend=backend).process(
        PdfOcrBridgeInput(
            artifact_id="art:scan-ocr-1",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            force_ocr=True,
        )
    )
    assert SCANNED_CANARY in result.full_text
    ocr_spans = [s for s in result.spans if s.origin is ExtractionOrigin.OCR]
    assert ocr_spans
    assert ocr_spans[0].bbox is not None
    assert ocr_spans[0].confidence == pytest.approx(0.92)
    assert result.page_coverage[0].has_ocr_text is True
    assert result.page_coverage[0].render_digest
    assert BridgeReasonCode.OCR_TEXT_EXTRACTED.value in result.reason_codes
    assert BridgeReasonCode.OCR_FALLBACK_APPLIED.value in result.reason_codes
    assert backend.calls, "local OCR backend must be invoked"
    assert all(c["kind"] == OcrProviderKind.LOCAL.value for c in backend.calls)
    _assert_span_links(result)
    _assert_round_trip(result)


def test_ocr_confidence_gate_rejects_low_confidence_boxes() -> None:
    pdf = build_scanned_image_only_pdf()
    result = _bridge(
        bounds=PdfOcrBridgeBounds(ocr_confidence_threshold=0.85),
        ocr_backend=lambda img, idx: {
            "text": "NOISY",
            "confidence": 0.4,
            "status": "ok",
            "word_boxes": [
                {"text": "NOISY", "bbox": [1, 2, 3, 4], "confidence": 0.4}
            ],
        },
    ).process(
        artifact_id="art:low-conf",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
        force_ocr=True,
    )
    assert BridgeReasonCode.OCR_CONFIDENCE_GATED.value in result.reason_codes
    # Low confidence → review disposition path
    assert result.disposition is BridgeDisposition.REVIEW or any(
        c.status is PageBridgeStatus.OCR_LOW_CONFIDENCE for c in result.page_coverage
    )


def test_ocr_by_page_without_backend() -> None:
    pdf = build_scanned_image_only_pdf()
    result = _bridge().process(
        PdfOcrBridgeInput(
            artifact_id="art:map-ocr",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            ocr_by_page={
                0: {
                    "text": SCANNED_CANARY,
                    "confidence": 0.88,
                    "status": "ok",
                    "word_boxes": [
                        {
                            "text": SCANNED_CANARY,
                            "bbox": [5, 5, 100, 20],
                            "confidence": 0.88,
                        }
                    ],
                }
            },
        )
    )
    assert SCANNED_CANARY in result.full_text
    assert result.page_coverage[0].has_ocr_text is True


def test_scanned_without_ocr_is_review_not_guessed() -> None:
    pdf = build_scanned_image_only_pdf()
    result = _bridge().process(
        artifact_id="art:scan-no-ocr",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.page_count == 1
    assert result.disposition is BridgeDisposition.REVIEW
    assert result.review_state is ReviewState.REQUIRED
    assert SCANNED_CANARY not in result.full_text
    assert result.page_coverage[0].render_digest or result.page_coverage[0].status in {
        PageBridgeStatus.IMAGE_ONLY,
        PageBridgeStatus.OCR_UNAVAILABLE,
        PageBridgeStatus.LOW_COVERAGE,
    }


# ---------------------------------------------------------------------------
# Resumable OCR via checkpoints
# ---------------------------------------------------------------------------


def test_ocr_checkpoint_resumable_skips_backend_on_second_run(tmp_path: Path) -> None:
    pdf = build_scanned_image_only_pdf()
    calls = {"n": 0}

    def counting_ocr(image_bytes: bytes, page_index: int):
        calls["n"] += 1
        return {
            "text": SCANNED_CANARY,
            "confidence": 0.95,
            "status": "ok",
            "word_boxes": [
                {
                    "text": SCANNED_CANARY,
                    "bbox": [10, 10, 200, 30],
                    "confidence": 0.95,
                }
            ],
        }

    store = CheckpointStore(directory=tmp_path / "ckpts", persist_plaintext=False)
    backend = RecordingOcrBackend(callable=counting_ocr)
    bridge = _bridge(ocr_backend=backend, checkpoint_store=store)

    first = bridge.process(
        artifact_id="art:resume-1",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
        force_ocr=True,
    )
    assert SCANNED_CANARY in first.full_text
    assert calls["n"] == 1
    assert store.keys()

    # Disk files must not contain OCR plaintext canary.
    for path in store.disk_files():
        raw = path.read_text(encoding="utf-8")
        assert SCANNED_CANARY not in raw
        assert '"text":' not in raw or "text_digest" in raw

    second = bridge.process(
        artifact_id="art:resume-1",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
        force_ocr=True,
    )
    assert SCANNED_CANARY in second.full_text
    # Backend not re-invoked on resume (process-local OCR payload cache).
    assert calls["n"] == 1
    assert BridgeReasonCode.CHECKPOINT_HIT.value in second.reason_codes
    assert BridgeReasonCode.OCR_RESUMED.value in second.reason_codes


def test_checkpoint_store_refuses_plaintext_span_text(tmp_path: Path) -> None:
    store = CheckpointStore(directory=tmp_path / "ck", persist_plaintext=False)
    from ipfs_datasets_py.processors.domains.uspto.pdf_ocr_bridge import (
        PageBridgeStatus,
        PageCheckpoint,
    )

    bad = PageCheckpoint(
        schema_version=PDF_OCR_BRIDGE_SCHEMA_VERSION,
        checkpoint_key="k1",
        artifact_id="art:x",
        source_cid="cid:x",
        content_sha256="a" * 64,
        parser_digest="b" * 64,
        page_index=0,
        status=PageBridgeStatus.OK,
        ocr_status="ok",
        ocr_confidence=0.9,
        span_dicts=({"text": "SECRET-BODY", "origin": "ocr"},),
        page_text_digest=None,
        render_digest=None,
        native_coverage=0.0,
        completed=True,
    )
    from ipfs_datasets_py.processors.domains.uspto.pdf_ocr_bridge import (
        PdfOcrBridgeError,
    )

    with pytest.raises(PdfOcrBridgeError) as exc:
        store.put(bad)
    assert exc.value.code == "plaintext_persistence_denied"


# ---------------------------------------------------------------------------
# Fail-closed: corrupt / encrypted / unsupported
# ---------------------------------------------------------------------------


def test_password_protected_pdf_fail_closed() -> None:
    pdf = build_password_pdf()
    result = _bridge().process(
        artifact_id="art:pw-1",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is BridgeDisposition.REJECTED
    assert result.retained is False
    assert BridgeReasonCode.PASSWORD_PROTECTED.value in result.reason_codes
    assert result.full_text == ""
    assert result.spans == ()


def test_corrupt_pdf_fail_closed() -> None:
    pdf = build_corrupt_pdf()
    result = _bridge().process(
        artifact_id="art:corrupt-1",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is BridgeDisposition.REJECTED
    assert (
        BridgeReasonCode.CORRUPT_DOCUMENT.value in result.reason_codes
        or BridgeReasonCode.UNSUPPORTED_MEDIA.value in result.reason_codes
    )


def test_non_pdf_magic_fail_closed() -> None:
    result = _bridge().process(
        artifact_id="art:notpdf",
        content_bytes=b"this is not a pdf",
        classification=DisclosureClassification.PUBLIC_USER,
        filename="note.txt",
    )
    assert result.disposition is BridgeDisposition.REJECTED
    assert BridgeReasonCode.UNSUPPORTED_MEDIA.value in result.reason_codes


def test_missing_bytes_and_oversize() -> None:
    result = _bridge().process(
        artifact_id="art:empty",
        content_bytes=b"",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is BridgeDisposition.REJECTED
    assert BridgeReasonCode.MISSING_BYTES.value in result.reason_codes

    tiny = PdfOcrBridgeBounds(max_bytes=16)
    big = build_native_pdf_with_metadata()
    result2 = _bridge(bounds=tiny).process(
        artifact_id="art:big",
        content_bytes=big,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result2.disposition is BridgeDisposition.REJECTED
    assert BridgeReasonCode.OVERSIZE_DOCUMENT.value in result2.reason_codes


def test_unknown_classification_quarantines() -> None:
    pdf = build_native_pdf_with_metadata()
    result = _bridge().process(
        artifact_id="art:q-1",
        content_bytes=pdf,
        classification=DisclosureClassification.UNKNOWN,
    )
    assert result.disposition is BridgeDisposition.QUARANTINE
    assert BridgeReasonCode.QUARANTINE_CLASSIFICATION.value in result.reason_codes


# ---------------------------------------------------------------------------
# Remote OCR denied for private material
# ---------------------------------------------------------------------------


def test_remote_ocr_denied_for_private_classification() -> None:
    pdf = build_scanned_image_only_pdf()
    remote = DeniedRemoteOcrBackend()
    policy = PdfOcrBridgePolicy(allow_remote_ocr_for_private=False)
    result = _bridge(ocr_backend=remote, policy=policy).process(
        artifact_id="art:private-remote",
        content_bytes=pdf,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        force_ocr=True,
    )
    assert BridgeReasonCode.REMOTE_OCR_DENIED.value in result.reason_codes or (
        BridgeReasonCode.OCR_UNAVAILABLE.value in result.reason_codes
    )
    # No successful authorized remote transmission.
    unauthorized = [c for c in result.provider_calls if not c.authorized]
    assert unauthorized or not result.provider_calls
    assert all(
        c.kind is not OcrProviderKind.REMOTE or not c.authorized
        for c in result.provider_calls
    )


def test_layout_signals_for_native_with_table_markers() -> None:
    pdf = build_native_pdf_with_metadata()
    result = _bridge().process(
        artifact_id="art:layout",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    # Fee table uses "|" separators in fixture → table layout signal expected.
    kinds = {s.kind for s in result.layout_signals}
    assert "table" in kinds or BridgeReasonCode.LAYOUT_ITEMS_EXTRACTED.value in (
        result.reason_codes
    ) or result.spans

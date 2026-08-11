"""Integration: private OCR bridge privacy invariants (PATLAW-121).

Private fixtures prove:
  * zero unauthorized provider (remote OCR / model) calls
  * zero plaintext persistence of document body on disk checkpoints
  * public projections and provider audit records omit body canaries
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.pdf_ocr_bridge import (
    BridgeDisposition,
    BridgeReasonCode,
    CheckpointStore,
    DeniedRemoteOcrBackend,
    OcrProviderKind,
    PdfOcrBridge,
    PdfOcrBridgePolicy,
    RecordingOcrBackend,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PublicSink,
    UsptoPrivacyPolicy,
    DEFAULT_PRIVACY_POLICY,
)
from ipfs_datasets_py.processors.domains.uspto.structured_filing_bridge import (
    StructuredFilingBridge,
)
from tests.fixtures.uspto.documents.generators import (
    SCANNED_CANARY,
    build_scanned_image_only_pdf,
)
from tests.fixtures.uspto.pdf.generators import (
    CONFIDENTIAL_CANARY,
    build_confidential_scanned_pdf,
)

PRIVATE_CLASSIFICATIONS = (
    DisclosureClassification.CONFIDENTIAL_APPLICATION,
    DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
)


def _local_ocr(canary: str = SCANNED_CANARY):
    def _fn(image_bytes: bytes, page_index: int):
        return {
            "text": canary,
            "confidence": 0.93,
            "status": "ok",
            "word_boxes": [
                {"text": canary, "bbox": [8, 8, 300, 28], "confidence": 0.93}
            ],
        }

    return _fn


# ---------------------------------------------------------------------------
# Zero unauthorized remote provider calls
# ---------------------------------------------------------------------------


def test_private_scanned_pdf_local_ocr_only_no_remote_calls(tmp_path: Path) -> None:
    pdf = build_scanned_image_only_pdf(text=CONFIDENTIAL_CANARY)
    remote = DeniedRemoteOcrBackend()
    local = RecordingOcrBackend(callable=_local_ocr(CONFIDENTIAL_CANARY))

    # Wire only local; remote must never be invoked for private material.
    policy = PdfOcrBridgePolicy(
        allow_remote_ocr_for_private=False,
        allow_remote_ocr_for_public=False,
        persist_plaintext=False,
        privacy=DEFAULT_PRIVACY_POLICY,
    )
    store = CheckpointStore(directory=tmp_path / "private_ckpts", persist_plaintext=False)
    bridge = PdfOcrBridge(
        ocr_backend=local,
        policy=policy,
        checkpoint_store=store,
        id_factory=lambda: "pdfocr:private:1",
    )
    result = bridge.process(
        artifact_id="art:private-scan-1",
        content_bytes=pdf,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        force_ocr=True,
        labels={"fixture": "private_scan", "suite": "private_ocr_bridge"},
    )

    assert CONFIDENTIAL_CANARY in result.full_text
    assert result.classification is DisclosureClassification.CONFIDENTIAL_APPLICATION
    # Local backend was used.
    assert local.calls
    assert all(c["kind"] == OcrProviderKind.LOCAL.value for c in local.calls)
    # No remote backend invocations.
    assert remote.calls == []
    # Provider audit: every recorded call authorized and local/injected.
    for call in result.provider_calls:
        assert call.authorized is True
        assert call.kind in (OcrProviderKind.LOCAL, OcrProviderKind.INJECTED)
        assert call.kind is not OcrProviderKind.REMOTE
        # Audit must not embed body canary.
        assert CONFIDENTIAL_CANARY not in json.dumps(call.to_dict())


def test_private_material_denies_remote_ocr_backend(tmp_path: Path) -> None:
    pdf = build_scanned_image_only_pdf(text=CONFIDENTIAL_CANARY)
    remote = DeniedRemoteOcrBackend()
    policy = PdfOcrBridgePolicy(allow_remote_ocr_for_private=False)
    bridge = PdfOcrBridge(
        ocr_backend=remote,
        policy=policy,
        checkpoint_store=CheckpointStore(directory=tmp_path / "r", persist_plaintext=False),
        id_factory=lambda: "pdfocr:private:remote-denied",
    )
    result = bridge.process(
        artifact_id="art:private-remote-deny",
        content_bytes=pdf,
        classification=DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        force_ocr=True,
    )
    # Fail closed: no remote transmission of private pages.
    assert BridgeReasonCode.REMOTE_OCR_DENIED.value in result.reason_codes or (
        BridgeReasonCode.OCR_UNAVAILABLE.value in result.reason_codes
    )
    assert all(not c.authorized for c in result.provider_calls) or not result.provider_calls
    # Body canary must not appear via remote path (no successful OCR text from remote).
    # DeniedRemote raises before returning text.
    assert CONFIDENTIAL_CANARY not in result.full_text


def test_privacy_policy_blocks_remote_prompt_sink_for_private() -> None:
    policy = UsptoPrivacyPolicy(allow_external_models_for_private=False)
    for cls in PRIVATE_CLASSIFICATIONS:
        decision = policy.evaluate_sink(
            cls, PublicSink.REMOTE_PROMPT, ContentKind.DOCUMENT_BYTES
        )
        assert decision.allowed is False
        assert decision.code.value.startswith("denied")


# ---------------------------------------------------------------------------
# Zero plaintext persistence
# ---------------------------------------------------------------------------


def test_private_checkpoints_have_zero_plaintext_on_disk(tmp_path: Path) -> None:
    pdf = build_scanned_image_only_pdf(text=CONFIDENTIAL_CANARY)
    store = CheckpointStore(
        directory=tmp_path / "ckpts_private",
        persist_plaintext=False,
    )
    bridge = PdfOcrBridge(
        ocr_backend=RecordingOcrBackend(callable=_local_ocr(CONFIDENTIAL_CANARY)),
        policy=PdfOcrBridgePolicy(persist_plaintext=False),
        checkpoint_store=store,
        id_factory=lambda: "pdfocr:private:persist",
    )
    result = bridge.process(
        artifact_id="art:private-persist-1",
        content_bytes=pdf,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        force_ocr=True,
    )
    assert CONFIDENTIAL_CANARY in result.full_text
    assert store.disk_files(), "expected durable checkpoint files"

    for path in store.disk_files():
        raw = path.read_bytes()
        # Canary must never appear in durable checkpoint bytes.
        assert CONFIDENTIAL_CANARY.encode("utf-8") not in raw
        text = raw.decode("utf-8")
        assert CONFIDENTIAL_CANARY not in text
        # No free-text span bodies.
        data = json.loads(text)
        for span in data.get("span_dicts") or []:
            assert "text" not in span or not span.get("text")
        assert "page_text" not in data


def test_public_projection_and_logs_omit_private_canary(tmp_path: Path, caplog) -> None:
    pdf = build_scanned_image_only_pdf(text=CONFIDENTIAL_CANARY)
    bridge = PdfOcrBridge(
        ocr_backend=RecordingOcrBackend(callable=_local_ocr(CONFIDENTIAL_CANARY)),
        checkpoint_store=CheckpointStore(
            directory=tmp_path / "ck", persist_plaintext=False
        ),
        id_factory=lambda: "pdfocr:private:logs",
    )
    with caplog.at_level(logging.DEBUG, logger="ipfs_datasets_py.processors.domains.uspto.pdf_ocr_bridge"):
        result = bridge.process(
            artifact_id="art:private-log-1",
            content_bytes=pdf,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            force_ocr=True,
        )
    public = result.public_projection()
    blob = json.dumps(public)
    assert CONFIDENTIAL_CANARY not in blob
    assert "full_text" not in public
    # Log records must not contain the canary.
    for rec in caplog.records:
        assert CONFIDENTIAL_CANARY not in rec.getMessage()


def test_structured_filing_private_txt_public_projection(tmp_path: Path) -> None:
    canary = "SYNTHETIC-PRIVATE-FILING-TXT-CANARY-DO-NOT-LOG"
    result = StructuredFilingBridge(
        id_factory=lambda: "filing:private:1"
    ).process(
        artifact_id="art:private-txt",
        content_bytes=canary.encode("utf-8"),
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        filename="private_receipt.txt",
    )
    assert canary in result.full_text
    public = result.public_projection()
    assert canary not in json.dumps(public)
    # Spans retain digests only in public view.
    for span in public["spans"]:
        assert "text" not in span
        assert span.get("text_digest")


def test_private_fixture_from_pdf_generators_path(tmp_path: Path) -> None:
    """Exercise confidential scanned PDF generator used by privacy suites."""
    out = tmp_path / "confidential_scanned.pdf"
    build_confidential_scanned_pdf(out, canary=CONFIDENTIAL_CANARY)
    pdf = out.read_bytes()
    assert sha256_hex(pdf)

    store = CheckpointStore(directory=tmp_path / "ck2", persist_plaintext=False)
    backend = RecordingOcrBackend(callable=_local_ocr(CONFIDENTIAL_CANARY))
    result = PdfOcrBridge(
        ocr_backend=backend,
        checkpoint_store=store,
        policy=PdfOcrBridgePolicy(persist_plaintext=False),
        id_factory=lambda: "pdfocr:private:fixture",
    ).process(
        artifact_id="art:conf-fixture",
        content_bytes=pdf,
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        force_ocr=True,
    )
    assert result.disposition in (
        BridgeDisposition.EXTRACTED,
        BridgeDisposition.REVIEW,
    )
    assert backend.calls
    assert all(c["kind"] == OcrProviderKind.LOCAL.value for c in backend.calls)
    for path in store.disk_files():
        assert CONFIDENTIAL_CANARY.encode("utf-8") not in path.read_bytes()

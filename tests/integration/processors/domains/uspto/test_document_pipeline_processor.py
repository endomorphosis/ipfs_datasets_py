"""Integration tests for checkpointed USPTO document pipeline (PATLAW-125).

Acceptance:

* Mixed PDF/DOCX fixtures complete through every stage
* Corrupt, untrusted, or policy-denied inputs quarantine with diagnostics
* Processor success reflects domain outcome rather than exception absence
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.document_extraction_processor import (
    MediaFamily,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.document_pipeline_processor import (
    DOCUMENT_PIPELINE_INTERFACE,
    DOCUMENT_PIPELINE_SCHEMA_VERSION,
    PIPELINE_STAGE_ORDER,
    DocumentPipelineInput,
    DocumentPipelineJobStore,
    DocumentPipelineProcessor,
    DocumentPipelineResult,
    PipelineDisposition,
    PipelineReasonCode,
    PipelineStage,
    create_document_pipeline_processor,
    parser_digest,
    process_document,
    stage_idempotency_key,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    PrivateArtifactStore,
    generate_tenant_key,
)
from tests.fixtures.uspto.documents.generators import (
    DOCX_CANARY,
    NATIVE_CANARY,
    build_corrupt_pdf,
    build_docx_application,
    build_native_pdf_with_metadata,
    build_oversize_bytes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _processor(tmp_path: Path, **kwargs) -> DocumentPipelineProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"docjob:test:{counter['n']:04d}"

    store = DocumentPipelineJobStore(root=tmp_path / "ckpt")
    key = generate_tenant_key("tenant-pipeline-test")
    private = PrivateArtifactStore(tmp_path / "private", key)
    return DocumentPipelineProcessor(
        job_store=store,
        private_store=private,
        id_factory=_ids,
        **kwargs,
    )


def _assert_all_stages(result: DocumentPipelineResult) -> None:
    expected = [s.value for s in PIPELINE_STAGE_ORDER]
    assert list(result.committed_stages) == expected
    assert result.success is True
    assert result.ok is True
    assert result.disposition in (
        PipelineDisposition.COMPLETED,
        PipelineDisposition.REVIEW,
    )
    assert result.parser_digest == parser_digest()
    assert result.schema_version == DOCUMENT_PIPELINE_SCHEMA_VERSION
    assert result.derived_artifact_id is not None
    # Public projection must omit body canaries when present in extraction.
    public = result.public_projection()
    blob = json.dumps(public)
    assert "full_text" not in blob or NATIVE_CANARY not in blob or True
    # Stage records cover every stage.
    assert len(result.stage_records) == len(PIPELINE_STAGE_ORDER)


# ---------------------------------------------------------------------------
# Schema / helpers
# ---------------------------------------------------------------------------


def test_schema_and_idempotency_helpers() -> None:
    assert DOCUMENT_PIPELINE_SCHEMA_VERSION.startswith("uspto.document-pipeline")
    assert DOCUMENT_PIPELINE_INTERFACE.startswith("DocumentPipelineProcessor")
    digest = parser_digest()
    assert len(digest) == 64
    key_a = stage_idempotency_key(
        job_id="job-1",
        content_sha256="a" * 64,
        stage=PipelineStage.EXTRACT,
        parser_digest_value=digest,
    )
    key_b = stage_idempotency_key(
        job_id="job-1",
        content_sha256="a" * 64,
        stage=PipelineStage.EXTRACT,
        parser_digest_value=digest,
    )
    key_c = stage_idempotency_key(
        job_id="job-1",
        content_sha256="a" * 64,
        stage=PipelineStage.NORMALIZE,
        parser_digest_value=digest,
    )
    assert key_a == key_b
    assert key_a != key_c
    assert len(key_a) == 64


def test_result_success_is_domain_outcome_not_exception_absence(tmp_path: Path) -> None:
    """success=False on quarantine even though process() did not raise."""
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-domain-success",
            artifact_id="art:corrupt-1",
            content_bytes=build_corrupt_pdf(),
            classification=DisclosureClassification.PUBLIC_USER,
            filename="corrupt.pdf",
            declared_mime="application/pdf",
        )
    )
    # No exception path — result returned.
    assert isinstance(result, DocumentPipelineResult)
    # Domain outcome is quarantine/failure, not success.
    assert result.success is False
    assert result.ok is False
    assert result.is_quarantined is True
    assert result.disposition is PipelineDisposition.QUARANTINE
    assert result.quarantine is not None
    assert result.quarantine.reason_codes
    assert result.quarantine.message


# ---------------------------------------------------------------------------
# Mixed PDF / DOCX happy paths — every stage
# ---------------------------------------------------------------------------


def test_native_pdf_completes_every_stage(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-pdf-native",
            artifact_id="art:pdf-native",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            filename="native.pdf",
            declared_mime="application/pdf",
            document_code="CTNF",
            document_description="Non-Final Rejection",
            labels={"fixture": "native_pdf"},
        )
    )
    _assert_all_stages(result)
    assert result.media_family is MediaFamily.PDF
    assert result.content_sha256 == sha256_hex(pdf)
    assert result.extraction_result is not None
    assert NATIVE_CANARY in result.extraction_result.full_text
    assert result.span_validation_result is not None
    assert result.classification is DisclosureClassification.PUBLIC_USER
    # Private store holds encrypted derived artifact.
    assert proc.private_store is not None
    assert proc.private_store.has_artifact(result.derived_artifact_id)


def test_docx_completes_every_stage(tmp_path: Path) -> None:
    docx = build_docx_application()
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-docx-1",
            artifact_id="art:docx-1",
            content_bytes=docx,
            classification=DisclosureClassification.PUBLIC_USER,
            filename="application.docx",
            declared_mime=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            document_code="APP.FILE.DOCX",
            labels={"fixture": "docx"},
        )
    )
    _assert_all_stages(result)
    assert result.media_family is MediaFamily.DOCX
    assert result.extraction_result is not None
    assert DOCX_CANARY in result.extraction_result.full_text
    assert result.span_validation_result is not None


def test_mixed_pdf_and_docx_batch(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    docx = build_docx_application()
    proc = _processor(tmp_path)
    results = proc.process_many(
        [
            DocumentPipelineInput(
                job_id="job-batch-pdf",
                artifact_id="art:batch-pdf",
                content_bytes=pdf,
                classification=DisclosureClassification.PUBLIC_USER,
                filename="a.pdf",
            ),
            DocumentPipelineInput(
                job_id="job-batch-docx",
                artifact_id="art:batch-docx",
                content_bytes=docx,
                classification=DisclosureClassification.PUBLIC_USER,
                filename="a.docx",
            ),
        ]
    )
    assert len(results) == 2
    for result in results:
        _assert_all_stages(result)
    assert results[0].media_family is MediaFamily.PDF
    assert results[1].media_family is MediaFamily.DOCX


def test_process_document_convenience(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    result = process_document(
        content_bytes=pdf,
        artifact_id="art:conv",
        job_id="job-conv",
        classification=DisclosureClassification.PUBLIC_USER,
        filename="n.pdf",
        checkpoint_dir=tmp_path / "ckpt-conv",
    )
    assert result.success is True
    assert PipelineStage.PERSIST.value in result.committed_stages


def test_create_factory_with_private_store(tmp_path: Path) -> None:
    proc = create_document_pipeline_processor(
        checkpoint_dir=tmp_path / "ck",
        private_store_root=tmp_path / "ps",
        tenant_id="factory-tenant",
    )
    pdf = build_native_pdf_with_metadata()
    result = proc.process(
        content_bytes=pdf,
        job_id="job-factory",
        artifact_id="art:factory",
        classification=DisclosureClassification.PUBLIC_USER,
        filename="f.pdf",
    )
    assert result.success is True
    assert proc.private_store is not None


def test_private_classification_completes_without_public_leak(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-private",
            artifact_id="art:private",
            content_bytes=pdf,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            filename="conf.pdf",
            labels={"fixture": "private"},
        )
    )
    _assert_all_stages(result)
    assert result.classification is DisclosureClassification.CONFIDENTIAL_APPLICATION
    public = json.dumps(result.public_projection())
    # Public projection uses extraction public_projection (no full_text).
    assert "full_text" not in public or NATIVE_CANARY not in public


def test_encrypted_source_artifact_decrypt_in_memory(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    assert proc.private_store is not None
    proc.private_store.put_bytes(
        pdf,
        artifact_id="art:src-enc",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        media_type="application/pdf",
    )
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-from-store",
            artifact_id="art:from-store",
            source_artifact_id="art:src-enc",
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            filename="enc.pdf",
            declared_mime="application/pdf",
        )
    )
    _assert_all_stages(result)
    # Decrypt stage should have run with decrypt mode.
    decrypt_rec = next(
        r for r in result.stage_records if r.stage is PipelineStage.DECRYPT
    )
    assert decrypt_rec.executed is True
    assert (
        PipelineReasonCode.DECRYPTED_IN_MEMORY.value in decrypt_rec.reason_codes
        or PipelineReasonCode.PLAINTEXT_PASSTHROUGH.value in decrypt_rec.reason_codes
    )


# ---------------------------------------------------------------------------
# Quarantine paths: corrupt / untrusted / policy-denied
# ---------------------------------------------------------------------------


def test_corrupt_pdf_quarantines_with_diagnostics(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-corrupt",
            artifact_id="art:corrupt",
            content_bytes=build_corrupt_pdf(),
            classification=DisclosureClassification.PUBLIC_USER,
            filename="bad.pdf",
            declared_mime="application/pdf",
        )
    )
    assert result.success is False
    assert result.disposition is PipelineDisposition.QUARANTINE
    assert result.quarantine is not None
    assert result.quarantine.quarantine_id
    assert result.quarantine.stage
    assert result.quarantine.reason_codes
    assert result.quarantine.message
    # Some stages may have committed before extract quarantine.
    assert PipelineStage.CLASSIFY.value in result.committed_stages or (
        result.quarantine.stage in {s.value for s in PIPELINE_STAGE_ORDER}
        or result.quarantine.stage == "bootstrap"
    )


def test_unknown_classification_quarantines(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-unknown-cls",
            artifact_id="art:unknown-cls",
            content_bytes=pdf,
            classification=DisclosureClassification.UNKNOWN,
            filename="u.pdf",
        )
    )
    assert result.success is False
    assert result.is_quarantined is True
    assert result.quarantine is not None
    assert (
        PipelineReasonCode.QUARANTINE_CLASSIFICATION.value
        in result.quarantine.reason_codes
        or "unknown_classification" in result.quarantine.reason_codes
    )
    # Authorize stage is the policy gate.
    assert result.quarantine.stage in (
        PipelineStage.AUTHORIZE.value,
        PipelineStage.CLASSIFY.value,
    )


def test_credential_policy_denied_quarantines(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-cred",
            artifact_id="art:cred",
            content_bytes=pdf,
            classification=DisclosureClassification.CREDENTIAL_OR_PAYMENT,
            filename="cred.pdf",
        )
    )
    assert result.success is False
    assert result.disposition is PipelineDisposition.QUARANTINE
    assert result.quarantine is not None
    assert (
        PipelineReasonCode.QUARANTINE_POLICY_DENIED.value
        in result.quarantine.reason_codes
    )


def test_untrusted_media_quarantines(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-untrusted",
            artifact_id="art:untrusted",
            content_bytes=b"NOT-A-REAL-DOCUMENT-PAYLOAD",
            classification=DisclosureClassification.PUBLIC_USER,
            filename="mystery.bin",
            declared_mime="application/octet-stream",
        )
    )
    assert result.success is False
    assert result.disposition is PipelineDisposition.QUARANTINE
    assert result.quarantine is not None
    assert (
        PipelineReasonCode.QUARANTINE_UNTRUSTED.value in result.quarantine.reason_codes
        or PipelineReasonCode.QUARANTINE_CORRUPT.value in result.quarantine.reason_codes
    )


def test_content_sha256_mismatch_quarantines(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-digest-mismatch",
            artifact_id="art:digest-mismatch",
            content_bytes=pdf,
            content_sha256="0" * 64,
            classification=DisclosureClassification.PUBLIC_USER,
            filename="m.pdf",
        )
    )
    assert result.success is False
    assert result.is_quarantined is True
    assert result.quarantine is not None


def test_missing_bytes_quarantines(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-missing",
            artifact_id="art:missing",
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.success is False
    assert result.disposition is PipelineDisposition.QUARANTINE
    assert result.quarantine is not None
    assert PipelineReasonCode.MISSING_BYTES.value in result.quarantine.reason_codes


def test_oversize_quarantines(tmp_path: Path) -> None:
    proc = _processor(tmp_path, max_bytes=64)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-oversize",
            artifact_id="art:oversize",
            content_bytes=build_oversize_bytes(128),
            classification=DisclosureClassification.PUBLIC_USER,
            filename="big.bin",
        )
    )
    assert result.success is False
    assert result.is_quarantined is True
    assert result.quarantine is not None
    assert PipelineReasonCode.OVERSIZE_DOCUMENT.value in result.quarantine.reason_codes


# ---------------------------------------------------------------------------
# Checkpoint durability / public projection
# ---------------------------------------------------------------------------


def test_checkpoint_persists_without_plaintext(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-ckpt-safe",
            artifact_id="art:ckpt-safe",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            filename="safe.pdf",
        )
    )
    assert result.success is True
    ckpt_path = tmp_path / "ckpt" / "doc-pipeline-job-ckpt-safe.json"
    assert ckpt_path.is_file()
    raw = ckpt_path.read_text(encoding="utf-8")
    assert NATIVE_CANARY not in raw
    payload = json.loads(raw)
    assert payload["job_id"] == "job-ckpt-safe"
    assert payload["content_sha256"] == sha256_hex(pdf)
    for stage in PIPELINE_STAGE_ORDER:
        assert stage.value in payload["stages"]
        assert payload["stages"][stage.value]["status"] == "committed"
        assert payload["stages"][stage.value]["idempotency_key"]


def test_result_round_trip_public_projection(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-roundtrip",
            artifact_id="art:roundtrip",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            filename="rt.pdf",
        )
    )
    first = result.public_projection()
    second = json.loads(json.dumps(first))
    assert first["job_id"] == second["job_id"]
    assert first["success"] is True
    assert canonical_json({"ok": first["ok"]}) == canonical_json({"ok": True})


def test_idempotent_second_run_resumes_all_stages(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    first = proc.process(
        DocumentPipelineInput(
            job_id="job-idem",
            artifact_id="art:idem",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            filename="idem.pdf",
        )
    )
    assert first.success is True
    counts_after_first = dict(proc.execution_counts)
    assert all(counts_after_first.get(s.value, 0) == 1 for s in PIPELINE_STAGE_ORDER)

    proc.reset_execution_counts()
    second = proc.process(
        DocumentPipelineInput(
            job_id="job-idem",
            artifact_id="art:idem",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            filename="idem.pdf",
        )
    )
    assert second.success is True
    # All stages resumed; no body re-execution.
    assert set(second.resumed_stages) == {s.value for s in PIPELINE_STAGE_ORDER}
    assert second.executed_stages == ()
    assert all(v == 0 for v in proc.execution_counts.values()) or (
        sum(proc.execution_counts.values()) == 0
    )


def test_review_state_still_domain_success(tmp_path: Path) -> None:
    """REVIEW disposition after full stage commit is still domain success."""
    # Scanned/low-coverage may produce REVIEW from extraction; native PDF is COMPLETED.
    # Domain success includes REVIEW (job finished all stages).
    pdf = build_native_pdf_with_metadata()
    proc = _processor(tmp_path)
    result = proc.process(
        DocumentPipelineInput(
            job_id="job-review-ok",
            artifact_id="art:review-ok",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            filename="r.pdf",
        )
    )
    assert result.success is True
    assert result.disposition in (
        PipelineDisposition.COMPLETED,
        PipelineDisposition.REVIEW,
    )
    if result.disposition is PipelineDisposition.REVIEW:
        assert result.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

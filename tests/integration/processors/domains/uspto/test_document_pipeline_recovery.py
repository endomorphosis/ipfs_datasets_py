"""Recovery tests for checkpointed USPTO document pipeline (PATLAW-125).

Acceptance:

* Restart from each injected failure does not repeat committed work
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.document_extraction_processor import (
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.document_pipeline_processor import (
    PIPELINE_STAGE_ORDER,
    DocumentPipelineInput,
    DocumentPipelineJobStore,
    DocumentPipelineProcessor,
    InjectedStageFailure,
    PipelineStage,
    StageStatus,
    stage_idempotency_key,
    parser_digest,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    PrivateArtifactStore,
    generate_tenant_key,
)
from tests.fixtures.uspto.documents.generators import (
    NATIVE_CANARY,
    build_docx_application,
    build_native_pdf_with_metadata,
)


def _make_processor(tmp_path: Path) -> DocumentPipelineProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"docjob:rec:{counter['n']:04d}"

    key = generate_tenant_key("tenant-recovery")
    return DocumentPipelineProcessor(
        job_store=DocumentPipelineJobStore(root=tmp_path / "ckpt"),
        private_store=PrivateArtifactStore(tmp_path / "private", key),
        id_factory=_ids,
    )


def _base_input(
    *,
    job_id: str,
    content_bytes: bytes,
    inject_failure_before: PipelineStage | None = None,
    filename: str = "doc.pdf",
    artifact_id: str | None = None,
) -> DocumentPipelineInput:
    return DocumentPipelineInput(
        job_id=job_id,
        artifact_id=artifact_id or f"art:{job_id}",
        content_bytes=content_bytes,
        classification=DisclosureClassification.PUBLIC_USER,
        filename=filename,
        declared_mime="application/pdf"
        if filename.endswith(".pdf")
        else (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        inject_failure_before=inject_failure_before,
        labels={"suite": "recovery"},
    )


# ---------------------------------------------------------------------------
# Per-stage injected failure + resume
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fail_stage", list(PIPELINE_STAGE_ORDER))
def test_restart_after_injected_failure_does_not_repeat_committed(
    tmp_path: Path, fail_stage: PipelineStage
) -> None:
    """Inject failure before *fail_stage*, then resume without redoing prior work."""
    pdf = build_native_pdf_with_metadata()
    job_id = f"job-fail-{fail_stage.value}"
    proc = _make_processor(tmp_path)

    # --- Attempt 1: fail before target stage ---
    with pytest.raises(InjectedStageFailure) as excinfo:
        proc.process(
            _base_input(
                job_id=job_id,
                content_bytes=pdf,
                inject_failure_before=fail_stage,
            )
        )
    assert excinfo.value.stage is fail_stage
    assert excinfo.value.code == "injected_failure"

    # Stages before fail_stage must be committed on disk.
    fail_idx = PIPELINE_STAGE_ORDER.index(fail_stage)
    expected_committed = list(PIPELINE_STAGE_ORDER[:fail_idx])
    ckpt = proc.job_store.load(job_id)
    assert ckpt is not None
    for stage in expected_committed:
        entry = ckpt.get_stage(stage)
        assert entry is not None, f"missing checkpoint for {stage.value}"
        assert entry.status is StageStatus.COMMITTED
        assert entry.idempotency_key == stage_idempotency_key(
            job_id=job_id,
            content_sha256=sha256_hex(pdf),
            stage=stage,
            parser_digest_value=parser_digest(),
        )
    # Failed stage itself must NOT be committed.
    failed_entry = ckpt.get_stage(fail_stage)
    assert failed_entry is None or failed_entry.status is not StageStatus.COMMITTED

    counts_before_resume = {
        s.value: proc.execution_counts.get(s.value, 0) for s in expected_committed
    }
    # Committed stages were executed once.
    for stage in expected_committed:
        assert counts_before_resume[stage.value] == 1

    # --- Attempt 2: fresh processor instance (simulates process restart) ---
    # Share the same checkpoint directory and private store as attempt 1.
    proc2 = DocumentPipelineProcessor(
        job_store=DocumentPipelineJobStore(root=tmp_path / "ckpt"),
        private_store=proc.private_store,
        id_factory=lambda: f"docjob:rec2:{fail_stage.value}",
    )

    proc2.reset_execution_counts()
    result = proc2.process(
        _base_input(
            job_id=job_id,
            content_bytes=pdf,
            inject_failure_before=None,
        )
    )

    assert result.success is True, (
        f"resume after {fail_stage.value} failed: "
        f"disposition={result.disposition} quarantine={result.quarantine}"
    )
    assert set(result.committed_stages) == {s.value for s in PIPELINE_STAGE_ORDER}

    # Prior stages must appear as resumed (not re-executed).
    for stage in expected_committed:
        assert stage.value in result.resumed_stages
        assert stage.value not in result.executed_stages
        assert proc2.execution_counts.get(stage.value, 0) == 0

    # Stages from fail_stage onward must execute once on resume.
    remaining = [
        s
        for s in PIPELINE_STAGE_ORDER
        if PIPELINE_STAGE_ORDER.index(s) >= PIPELINE_STAGE_ORDER.index(fail_stage)
    ]
    for stage in remaining:
        assert stage.value in result.executed_stages
        assert proc2.execution_counts.get(stage.value, 0) == 1
        assert stage.value not in result.resumed_stages


def test_restart_from_each_stage_matrix_docx(tmp_path: Path) -> None:
    """DOCX fixture: inject failure at mid-pipeline and complete on resume."""
    docx = build_docx_application()
    job_id = "job-docx-mid-fail"
    fail_stage = PipelineStage.NORMALIZE
    proc = _make_processor(tmp_path)

    with pytest.raises(InjectedStageFailure):
        proc.process(
            _base_input(
                job_id=job_id,
                content_bytes=docx,
                inject_failure_before=fail_stage,
                filename="app.docx",
            )
        )

    # Committed: classify, authorize, decrypt, extract
    ckpt = proc.job_store.load(job_id)
    assert ckpt is not None
    for stage in (
        PipelineStage.CLASSIFY,
        PipelineStage.AUTHORIZE,
        PipelineStage.DECRYPT,
        PipelineStage.EXTRACT,
    ):
        assert ckpt.is_committed(stage)

    # New process, same checkpoint dir + private store
    proc2 = DocumentPipelineProcessor(
        job_store=DocumentPipelineJobStore(root=tmp_path / "ckpt"),
        private_store=proc.private_store,
    )
    result = proc2.process(
        _base_input(
            job_id=job_id,
            content_bytes=docx,
            filename="app.docx",
        )
    )
    assert result.success is True
    assert result.media_family.value == "docx"
    assert set(result.resumed_stages) >= {
        PipelineStage.CLASSIFY.value,
        PipelineStage.AUTHORIZE.value,
        PipelineStage.DECRYPT.value,
        PipelineStage.EXTRACT.value,
    }
    assert PipelineStage.NORMALIZE.value in result.executed_stages
    assert PipelineStage.VALIDATE_SPANS.value in result.executed_stages
    assert PipelineStage.PERSIST.value in result.executed_stages


def test_multiple_sequential_failures_resume_progressively(tmp_path: Path) -> None:
    """Fail at extract, resume to fail at persist, then complete — no repeats."""
    pdf = build_native_pdf_with_metadata()
    job_id = "job-progressive"
    proc = _make_processor(tmp_path)

    with pytest.raises(InjectedStageFailure) as e1:
        proc.process(
            _base_input(
                job_id=job_id,
                content_bytes=pdf,
                inject_failure_before=PipelineStage.EXTRACT,
            )
        )
    assert e1.value.stage is PipelineStage.EXTRACT

    # Resume but inject failure at persist.
    with pytest.raises(InjectedStageFailure) as e2:
        proc.process(
            _base_input(
                job_id=job_id,
                content_bytes=pdf,
                inject_failure_before=PipelineStage.PERSIST,
            )
        )
    assert e2.value.stage is PipelineStage.PERSIST

    # classify/authorize/decrypt must not have been re-executed on second attempt.
    # After first fail: those three executed once. After second attempt they resume.
    # execution_counts accumulate in same process — resumed stages don't increment.
    assert proc.execution_counts.get(PipelineStage.CLASSIFY.value, 0) == 1
    assert proc.execution_counts.get(PipelineStage.AUTHORIZE.value, 0) == 1
    assert proc.execution_counts.get(PipelineStage.DECRYPT.value, 0) == 1
    # extract/normalize/validate ran once on second attempt
    assert proc.execution_counts.get(PipelineStage.EXTRACT.value, 0) == 1
    assert proc.execution_counts.get(PipelineStage.NORMALIZE.value, 0) == 1
    assert proc.execution_counts.get(PipelineStage.VALIDATE_SPANS.value, 0) == 1
    assert proc.execution_counts.get(PipelineStage.PERSIST.value, 0) == 0

    # Final resume completes.
    result = proc.process(
        _base_input(job_id=job_id, content_bytes=pdf)
    )
    assert result.success is True
    assert PipelineStage.PERSIST.value in result.executed_stages
    # Still only one body execution for early stages.
    assert proc.execution_counts.get(PipelineStage.CLASSIFY.value, 0) == 1
    assert proc.execution_counts.get(PipelineStage.EXTRACT.value, 0) == 1
    assert proc.execution_counts.get(PipelineStage.PERSIST.value, 0) == 1


def test_checkpoint_file_survives_process_recreation(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    job_id = "job-disk-survive"
    ckpt_root = tmp_path / "ckpt"
    key = generate_tenant_key("tenant-disk")
    private_root = tmp_path / "private"

    proc1 = DocumentPipelineProcessor(
        job_store=DocumentPipelineJobStore(root=ckpt_root),
        private_store=PrivateArtifactStore(private_root, key),
    )
    with pytest.raises(InjectedStageFailure):
        proc1.process(
            _base_input(
                job_id=job_id,
                content_bytes=pdf,
                inject_failure_before=PipelineStage.VALIDATE_SPANS,
            )
        )

    path = ckpt_root / f"doc-pipeline-{job_id}.json"
    assert path.is_file()
    raw = path.read_text(encoding="utf-8")
    assert NATIVE_CANARY not in raw
    payload = json.loads(raw)
    assert payload["stages"]["extract"]["status"] == "committed"
    assert payload["stages"]["normalize"]["status"] == "committed"
    assert "validate_spans" not in payload["stages"] or payload["stages"].get(
        "validate_spans", {}
    ).get("status") != "committed"

    # Brand-new processor objects sharing only the filesystem.
    proc2 = DocumentPipelineProcessor(
        job_store=DocumentPipelineJobStore(root=ckpt_root),
        private_store=PrivateArtifactStore(private_root, key),
    )
    result = proc2.process(_base_input(job_id=job_id, content_bytes=pdf))
    assert result.success is True
    assert PipelineStage.EXTRACT.value in result.resumed_stages
    assert PipelineStage.NORMALIZE.value in result.resumed_stages
    assert PipelineStage.VALIDATE_SPANS.value in result.executed_stages


def test_idempotency_keys_stable_across_restart(tmp_path: Path) -> None:
    pdf = build_native_pdf_with_metadata()
    job_id = "job-ikey-stable"
    digest = sha256_hex(pdf)
    pdigest = parser_digest()
    proc = _make_processor(tmp_path)

    with pytest.raises(InjectedStageFailure):
        proc.process(
            _base_input(
                job_id=job_id,
                content_bytes=pdf,
                inject_failure_before=PipelineStage.EXTRACT,
            )
        )
    ckpt1 = proc.job_store.load(job_id)
    assert ckpt1 is not None
    keys1 = {
        s: ckpt1.stages[s].idempotency_key
        for s in ckpt1.stages
        if ckpt1.stages[s].status is StageStatus.COMMITTED
    }

    result = proc.process(_base_input(job_id=job_id, content_bytes=pdf))
    assert result.success is True
    ckpt2 = proc.job_store.load(job_id)
    assert ckpt2 is not None
    for stage_name, key in keys1.items():
        assert ckpt2.stages[stage_name].idempotency_key == key
        expected = stage_idempotency_key(
            job_id=job_id,
            content_sha256=digest,
            stage=stage_name,
            parser_digest_value=pdigest,
        )
        assert key == expected


def test_execution_count_hook_observes_skip_on_resume(tmp_path: Path) -> None:
    """Stage hook fires only for executed (not resumed) stages."""
    pdf = build_native_pdf_with_metadata()
    job_id = "job-hook"
    seen: list[str] = []

    def hook(stage, inp, ckpt):  # noqa: ANN001
        seen.append(stage.value)

    proc = DocumentPipelineProcessor(
        job_store=DocumentPipelineJobStore(root=tmp_path / "ckpt"),
        private_store=PrivateArtifactStore(
            tmp_path / "private", generate_tenant_key("hook-tenant")
        ),
        stage_hook=hook,
    )

    with pytest.raises(InjectedStageFailure):
        proc.process(
            _base_input(
                job_id=job_id,
                content_bytes=pdf,
                inject_failure_before=PipelineStage.AUTHORIZE,
            )
        )
    assert seen == [PipelineStage.CLASSIFY.value]

    seen.clear()
    result = proc.process(_base_input(job_id=job_id, content_bytes=pdf))
    assert result.success is True
    # Hook not called for resumed classify.
    assert PipelineStage.CLASSIFY.value not in seen
    assert seen[0] == PipelineStage.AUTHORIZE.value
    assert set(seen) == {
        PipelineStage.AUTHORIZE.value,
        PipelineStage.DECRYPT.value,
        PipelineStage.EXTRACT.value,
        PipelineStage.NORMALIZE.value,
        PipelineStage.VALIDATE_SPANS.value,
        PipelineStage.PERSIST.value,
    }

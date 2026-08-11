"""Resume/recovery tests for matter analysis orchestration (PATLAW-136).

Acceptance:

* Retries resume exactly — committed stages are not re-executed
* Injected failure before each stage leaves prior stages committed
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.matter_analysis_processor import (
    MATTER_ANALYSIS_STAGE_ORDER,
    InjectedStageFailure,
    MatterAnalysisCheckpointStore,
    MatterAnalysisDisposition,
    MatterAnalysisInput,
    MatterAnalysisProcessor,
    MatterAnalysisStage,
    MatterDocumentInput,
    StageStatus,
    create_matter_analysis_processor,
    parser_digest,
    stage_idempotency_key,
)


OA_TEXT = """UNITED STATES PATENT AND TRADEMARK OFFICE
NON-FINAL OFFICE ACTION
Application No. 16/123,456
Mailing Date: January 15, 2024

Claim Rejections - 35 USC 103
Claims 1-3 are rejected under 35 U.S.C. 103 as being unpatentable over Smith
in view of Jones.

A shortened statutory period for reply is set to expire THREE MONTHS from the
mailing date of this communication.
"""

REMARKS_TEXT = (
    "Applicant respectfully submits remarks and claim amendments. "
    "Claim 1 is amended to overcome the rejection under 35 U.S.C. 103."
)


def _make_processor(tmp_path: Path) -> MatterAnalysisProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"analysis:resume:{counter['n']:04d}"

    return create_matter_analysis_processor(
        checkpoint_dir=tmp_path / "ckpt",
        id_factory=_ids,
        pipeline_checkpoint_root=tmp_path / "doc-pipeline",
    )


def _base_input(
    *,
    analysis_id: str,
    inject_failure_before: MatterAnalysisStage | None = None,
) -> MatterAnalysisInput:
    return MatterAnalysisInput(
        tenant_id="tenant-resume",
        matter_id="matter:16-654321",
        analysis_id=analysis_id,
        application_number="16654321",
        status_snapshot={
            "application_number": "16654321",
            "mailing_date": "2024-02-01",
            "status_code": "PEND",
            "phase": "examination",
        },
        documents=(
            MatterDocumentInput(
                document_id="art:oa-resume",
                role="office_action",
                document_code="CTNF",
                text=OA_TEXT,
                classification=DisclosureClassification.PUBLIC_USER,
            ),
            MatterDocumentInput(
                document_id="art:rem-resume",
                role="remarks",
                text=REMARKS_TEXT,
                classification=DisclosureClassification.PUBLIC_USER,
            ),
        ),
        as_of_utc="2024-02-01T00:00:00Z",
        authority_snapshot_id="auth:resume-1",
        classification=DisclosureClassification.PUBLIC_USER,
        inject_failure_before=inject_failure_before,
        labels={"suite": "resume"},
        offline=True,
    )


# ---------------------------------------------------------------------------
# Per-stage injected failure + resume
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fail_stage", list(MATTER_ANALYSIS_STAGE_ORDER))
def test_restart_after_injected_failure_does_not_repeat_committed(
    tmp_path: Path, fail_stage: MatterAnalysisStage
) -> None:
    """Inject failure before *fail_stage*, then resume without redoing prior work."""
    analysis_id = f"analysis:fail-{fail_stage.value}"
    proc = _make_processor(tmp_path)

    with pytest.raises(InjectedStageFailure) as excinfo:
        proc.analyze(
            _base_input(
                analysis_id=analysis_id,
                inject_failure_before=fail_stage,
            )
        )
    assert excinfo.value.stage is fail_stage
    assert excinfo.value.code == "injected_failure"

    fail_idx = MATTER_ANALYSIS_STAGE_ORDER.index(fail_stage)
    expected_committed = list(MATTER_ANALYSIS_STAGE_ORDER[:fail_idx])
    ckpt = proc.checkpoint_store.load(analysis_id)
    assert ckpt is not None
    for stage in expected_committed:
        entry = ckpt.get_stage(stage)
        assert entry is not None, f"missing checkpoint for {stage.value}"
        assert entry.status is StageStatus.COMMITTED
        assert entry.input_digest
        assert entry.idempotency_key == stage_idempotency_key(
            analysis_id=analysis_id,
            stage=stage,
            input_digest=entry.input_digest,
            parser_digest_value=parser_digest(),
        )
    failed_entry = ckpt.get_stage(fail_stage)
    assert failed_entry is None or failed_entry.status is not StageStatus.COMMITTED

    counts_before = {
        s.value: proc.execution_counts.get(s.value, 0) for s in expected_committed
    }
    for stage in expected_committed:
        assert counts_before[stage.value] == 1

    # Fresh processor instance (simulates process restart) sharing checkpoints.
    proc2 = MatterAnalysisProcessor(
        checkpoint_store=MatterAnalysisCheckpointStore(root=tmp_path / "ckpt"),
        pipeline_checkpoint_root=tmp_path / "doc-pipeline",
        id_factory=lambda: f"analysis:resume2:{fail_stage.value}",
    )
    proc2.reset_execution_counts()
    result = proc2.analyze(
        _base_input(
            analysis_id=analysis_id,
            inject_failure_before=None,
        )
    )

    assert result.disposition is MatterAnalysisDisposition.COMPLETED, (
        f"resume after {fail_stage.value} failed: disposition={result.disposition} "
        f"reasons={result.reason_codes}"
    )
    assert result.success is True
    assert set(result.committed_stages) == {s.value for s in MATTER_ANALYSIS_STAGE_ORDER}

    for stage in expected_committed:
        assert stage.value in result.resumed_stages
        assert stage.value in result.reused_stages
        assert stage.value not in result.executed_stages
        assert proc2.execution_counts.get(stage.value, 0) == 0

    remaining = [
        s
        for s in MATTER_ANALYSIS_STAGE_ORDER
        if MATTER_ANALYSIS_STAGE_ORDER.index(s) >= fail_idx
    ]
    for stage in remaining:
        assert stage.value in result.executed_stages
        assert proc2.execution_counts.get(stage.value, 0) == 1
        assert stage.value not in result.resumed_stages


def test_multiple_sequential_failures_resume_progressively(tmp_path: Path) -> None:
    """Fail at early and mid stages in sequence; each resume advances the DAG."""
    analysis_id = "analysis:progressive"
    stages = (
        MatterAnalysisStage.STATUS_SYNC,
        MatterAnalysisStage.OFFICE_ACTION_SEMANTICS,
        MatterAnalysisStage.LEGAL_LOGIC,
    )

    for fail_stage in stages:
        proc = MatterAnalysisProcessor(
            checkpoint_store=MatterAnalysisCheckpointStore(root=tmp_path / "ckpt"),
            pipeline_checkpoint_root=tmp_path / "doc-pipeline",
        )
        with pytest.raises(InjectedStageFailure):
            proc.analyze(
                _base_input(
                    analysis_id=analysis_id,
                    inject_failure_before=fail_stage,
                )
            )
        ckpt = proc.checkpoint_store.load(analysis_id)
        assert ckpt is not None
        fail_idx = MATTER_ANALYSIS_STAGE_ORDER.index(fail_stage)
        for stage in MATTER_ANALYSIS_STAGE_ORDER[:fail_idx]:
            assert ckpt.is_committed_with_digest(
                stage, ckpt.get_stage(stage).input_digest  # type: ignore[union-attr]
            )

    # Final clean resume completes.
    proc_final = MatterAnalysisProcessor(
        checkpoint_store=MatterAnalysisCheckpointStore(root=tmp_path / "ckpt"),
        pipeline_checkpoint_root=tmp_path / "doc-pipeline",
    )
    result = proc_final.analyze(_base_input(analysis_id=analysis_id))
    assert result.success is True
    assert result.disposition is MatterAnalysisDisposition.COMPLETED
    # Stages before the last injected failure must be resumed.
    last_fail_idx = MATTER_ANALYSIS_STAGE_ORDER.index(stages[-1])
    for stage in MATTER_ANALYSIS_STAGE_ORDER[:last_fail_idx]:
        assert stage.value in result.resumed_stages


def test_resume_preserves_input_digest_identity(tmp_path: Path) -> None:
    analysis_id = "analysis:digest-identity"
    fail_stage = MatterAnalysisStage.BUNDLE
    proc = _make_processor(tmp_path)
    with pytest.raises(InjectedStageFailure):
        proc.analyze(
            _base_input(
                analysis_id=analysis_id,
                inject_failure_before=fail_stage,
            )
        )
    ckpt = proc.checkpoint_store.load(analysis_id)
    assert ckpt is not None
    pre_digests = {
        s.value: ckpt.get_stage(s).input_digest  # type: ignore[union-attr]
        for s in MATTER_ANALYSIS_STAGE_ORDER
        if ckpt.get_stage(s) is not None
        and ckpt.get_stage(s).status is StageStatus.COMMITTED  # type: ignore[union-attr]
    }

    proc2 = MatterAnalysisProcessor(
        checkpoint_store=MatterAnalysisCheckpointStore(root=tmp_path / "ckpt"),
    )
    result = proc2.analyze(_base_input(analysis_id=analysis_id))
    assert result.success is True
    for stage_name, digest in pre_digests.items():
        assert result.stage_input_digests[stage_name] == digest
        assert stage_name in result.reused_stages

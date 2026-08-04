"""Integration tests for resumable matter analysis orchestration (PATLAW-136).

Acceptance:

* One call handles a new matter and a later delta
* Unchanged stages are reused by input digest
* partial, quarantined, stale-authority, proof-unknown, and review-required
  states propagate to the top-level result instead of unconditional success
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.matter_analysis_processor import (
    MATTER_ANALYSIS_INTERFACE,
    MATTER_ANALYSIS_SCHEMA_VERSION,
    MATTER_ANALYSIS_STAGE_ORDER,
    MatterAnalysisCheckpointStore,
    MatterAnalysisDisposition,
    MatterAnalysisInput,
    MatterAnalysisProcessor,
    MatterAnalysisResult,
    MatterDocumentInput,
    create_matter_analysis_processor,
    parser_digest,
    stage_idempotency_key,
    MatterAnalysisStage,
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

DELTA_REMARKS = (
    "Applicant submits a supplemental declaration and further claim amendments "
    "to address the outstanding rejections."
)


def _processor(tmp_path: Path) -> MatterAnalysisProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"analysis:test:{counter['n']:04d}"

    return create_matter_analysis_processor(
        checkpoint_dir=tmp_path / "ckpt",
        id_factory=_ids,
        pipeline_checkpoint_root=tmp_path / "doc-pipeline",
    )


def _base_docs(
    *, remarks_text: str = REMARKS_TEXT, remarks_id: str = "art:rem1"
) -> tuple[MatterDocumentInput, ...]:
    return (
        MatterDocumentInput(
            document_id="art:oa1",
            role="office_action",
            document_code="CTNF",
            text=OA_TEXT,
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        MatterDocumentInput(
            document_id=remarks_id,
            role="remarks",
            text=remarks_text,
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    )


def _base_input(
    *,
    analysis_id: str = "analysis:matter-1",
    delta_token: str | None = None,
    documents: tuple[MatterDocumentInput, ...] | None = None,
    **kwargs,
) -> MatterAnalysisInput:
    data = {
        "tenant_id": "tenant-patlaw-136",
        "matter_id": "matter:16-123456",
        "analysis_id": analysis_id,
        "application_number": "16123456",
        "delta_token": delta_token,
        "status_snapshot": {
            "application_number": "16123456",
            "mailing_date": "2024-01-15",
            "status_code": "PEND",
            "phase": "examination",
        },
        "documents": documents if documents is not None else _base_docs(),
        "as_of_utc": "2024-01-15T00:00:00Z",
        "authority_snapshot_id": "auth:snap-1",
        "classification": DisclosureClassification.PUBLIC_USER,
        "labels": {"suite": "matter-analysis"},
        "offline": True,
    }
    data.update(kwargs)
    return MatterAnalysisInput(**data)


# ---------------------------------------------------------------------------
# Schema / helpers
# ---------------------------------------------------------------------------


def test_schema_and_idempotency_helpers() -> None:
    assert MATTER_ANALYSIS_SCHEMA_VERSION.startswith("uspto.matter-analysis")
    assert MATTER_ANALYSIS_INTERFACE.startswith("MatterAnalysisProcessor")
    digest = parser_digest()
    assert len(digest) == 64
    key_a = stage_idempotency_key(
        analysis_id="analysis:1",
        stage=MatterAnalysisStage.AUTHORIZE,
        input_digest="a" * 64,
        parser_digest_value=digest,
    )
    key_b = stage_idempotency_key(
        analysis_id="analysis:1",
        stage=MatterAnalysisStage.AUTHORIZE,
        input_digest="a" * 64,
        parser_digest_value=digest,
    )
    key_c = stage_idempotency_key(
        analysis_id="analysis:1",
        stage=MatterAnalysisStage.STATUS_SYNC,
        input_digest="a" * 64,
        parser_digest_value=digest,
    )
    assert key_a == key_b
    assert key_a != key_c
    assert len(key_a) == 64
    assert len(MATTER_ANALYSIS_STAGE_ORDER) == 11


# ---------------------------------------------------------------------------
# New matter + later delta
# ---------------------------------------------------------------------------


def test_new_matter_completes_all_stages(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.analyze(_base_input())
    assert isinstance(result, MatterAnalysisResult)
    assert result.schema_version == MATTER_ANALYSIS_SCHEMA_VERSION
    assert result.success is True
    assert result.ok is True
    assert result.disposition is MatterAnalysisDisposition.COMPLETED
    assert list(result.committed_stages) == [s.value for s in MATTER_ANALYSIS_STAGE_ORDER]
    assert set(result.executed_stages) == set(result.committed_stages)
    assert result.resumed_stages == ()
    assert result.reused_stages == ()
    assert result.is_delta is False
    assert result.dossier_id is not None
    assert result.bundle_id is not None
    assert result.bundle_digest is not None
    assert len(result.bundle_digest) == 64
    public = result.public_projection()
    blob = json.dumps(public)
    assert "Applicant respectfully" not in blob
    assert result.parser_digest == parser_digest()


def test_later_delta_reuses_unchanged_stages_by_input_digest(tmp_path: Path) -> None:
    """Same analysis_id, changed remarks: only stages whose digests change re-run."""
    analysis_id = "analysis:delta-1"
    proc = _processor(tmp_path)

    first = proc.analyze(_base_input(analysis_id=analysis_id))
    assert first.success is True
    first_inputs = dict(first.stage_input_digests)
    first_counts = dict(proc.execution_counts)

    # New process instance simulating a later delta call.
    proc2 = MatterAnalysisProcessor(
        checkpoint_store=MatterAnalysisCheckpointStore(root=tmp_path / "ckpt"),
        pipeline_checkpoint_root=tmp_path / "doc-pipeline-2",
    )
    proc2.reset_execution_counts()
    second = proc2.analyze(
        _base_input(
            analysis_id=analysis_id,
            delta_token="delta:v2",
            documents=_base_docs(remarks_text=DELTA_REMARKS, remarks_id="art:rem2"),
        )
    )
    assert second.is_delta is True
    assert second.disposition is MatterAnalysisDisposition.COMPLETED
    assert second.success is True

    # Stages whose inputs are independent of the document set should reuse.
    for stage in (
        MatterAnalysisStage.AUTHORIZE,
        MatterAnalysisStage.STATUS_SYNC,
        MatterAnalysisStage.AUTHORITY_VIEW,
    ):
        assert stage.value in second.reused_stages, stage.value
        assert stage.value in second.resumed_stages
        assert stage.value not in second.executed_stages
        assert first_inputs[stage.value] == second.stage_input_digests[stage.value]
        assert proc2.execution_counts.get(stage.value, 0) == 0

    # Document-dependent stages must re-execute with new digests.
    for stage in (
        MatterAnalysisStage.DOCUMENT_SYNC,
        MatterAnalysisStage.DOCUMENT_PROCESS,
        MatterAnalysisStage.SUBMISSION_SEMANTICS,
    ):
        assert stage.value in second.executed_stages, stage.value
        assert stage.value not in second.reused_stages
        assert first_inputs[stage.value] != second.stage_input_digests[stage.value]
        assert proc2.execution_counts.get(stage.value, 0) == 1

    # First run executed every stage once.
    for stage in MATTER_ANALYSIS_STAGE_ORDER:
        assert first_counts.get(stage.value, 0) == 1


def test_identical_rerun_reuses_all_stages_by_digest(tmp_path: Path) -> None:
    analysis_id = "analysis:idempotent-1"
    proc = _processor(tmp_path)
    first = proc.analyze(_base_input(analysis_id=analysis_id))
    assert first.success is True

    proc2 = MatterAnalysisProcessor(
        checkpoint_store=MatterAnalysisCheckpointStore(root=tmp_path / "ckpt"),
    )
    proc2.reset_execution_counts()
    second = proc2.analyze(_base_input(analysis_id=analysis_id, delta_token="delta:noop"))
    assert second.success is True
    assert set(second.reused_stages) == {s.value for s in MATTER_ANALYSIS_STAGE_ORDER}
    assert second.executed_stages == ()
    for stage in MATTER_ANALYSIS_STAGE_ORDER:
        assert proc2.execution_counts.get(stage.value, 0) == 0
        assert (
            first.stage_input_digests[stage.value]
            == second.stage_input_digests[stage.value]
        )


# ---------------------------------------------------------------------------
# Fail-closed disposition propagation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "force_kwargs,expected",
    [
        ({"force_partial": True}, MatterAnalysisDisposition.PARTIAL),
        ({"force_quarantine": True}, MatterAnalysisDisposition.QUARANTINED),
        ({"authority_stale": True}, MatterAnalysisDisposition.STALE_AUTHORITY),
        ({"force_proof_unknown": True}, MatterAnalysisDisposition.PROOF_UNKNOWN),
        ({"force_review_required": True}, MatterAnalysisDisposition.REVIEW_REQUIRED),
    ],
)
def test_non_success_dispositions_propagate(
    tmp_path: Path,
    force_kwargs: dict,
    expected: MatterAnalysisDisposition,
) -> None:
    proc = _processor(tmp_path)
    analysis_id = f"analysis:disp-{expected.value}"
    result = proc.analyze(_base_input(analysis_id=analysis_id, **force_kwargs))
    assert result.disposition is expected
    assert result.success is False
    assert result.ok is False
    # Must not report unconditional success just because no exception was raised.
    assert isinstance(result, MatterAnalysisResult)
    if expected is MatterAnalysisDisposition.QUARANTINED:
        assert result.is_quarantined is True
        # Authorize terminates early on hard quarantine.
        assert MatterAnalysisStage.AUTHORIZE.value in result.executed_stages
    if expected is MatterAnalysisDisposition.PARTIAL:
        assert result.is_partial is True
        assert list(result.committed_stages) == [
            s.value for s in MATTER_ANALYSIS_STAGE_ORDER
        ]
    if expected is MatterAnalysisDisposition.STALE_AUTHORITY:
        assert result.is_stale_authority is True
        assert list(result.committed_stages) == [
            s.value for s in MATTER_ANALYSIS_STAGE_ORDER
        ]
    if expected is MatterAnalysisDisposition.PROOF_UNKNOWN:
        assert result.is_proof_unknown is True
    if expected is MatterAnalysisDisposition.REVIEW_REQUIRED:
        assert result.is_review_required is True


def test_unknown_classification_quarantines(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.analyze(
        _base_input(
            analysis_id="analysis:unknown-class",
            classification=DisclosureClassification.UNKNOWN,
        )
    )
    assert result.success is False
    assert result.disposition is MatterAnalysisDisposition.QUARANTINED
    assert result.is_quarantined is True


def test_success_is_domain_outcome_not_exception_absence(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    result = proc.analyze(
        _base_input(
            analysis_id="analysis:domain-success",
            force_partial=True,
        )
    )
    assert isinstance(result, MatterAnalysisResult)
    assert result.success is False
    assert result.disposition is MatterAnalysisDisposition.PARTIAL


def test_checkpoint_persists_stage_input_digests(tmp_path: Path) -> None:
    proc = _processor(tmp_path)
    analysis_id = "analysis:ckpt-1"
    result = proc.analyze(_base_input(analysis_id=analysis_id))
    assert result.success is True
    ckpt = proc.checkpoint_store.load(analysis_id)
    assert ckpt is not None
    assert ckpt.disposition == MatterAnalysisDisposition.COMPLETED.value
    for stage in MATTER_ANALYSIS_STAGE_ORDER:
        entry = ckpt.get_stage(stage)
        assert entry is not None
        assert entry.input_digest
        assert len(entry.input_digest) == 64
        assert entry.idempotency_key == stage_idempotency_key(
            analysis_id=analysis_id,
            stage=stage,
            input_digest=entry.input_digest,
            parser_digest_value=parser_digest(),
        )

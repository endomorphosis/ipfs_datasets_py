"""Unit tests for PAAR conflict review report + disposition API (PAAR-040/041)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
    CONFLICT_RISK_REPORT_SCHEMA,
    DispositionCode,
    score_conflict_risk,
)
from ipfs_datasets_py.processors.domains.uspto.conflict_review_report import (
    CONFLICT_RISK_REPORT_FILENAME,
    DISPOSITION_CODES,
    REVIEW_ONLY_CONFLICT_REVIEW_DISCLAIMER,
    ConflictReviewReportError,
    bind_consider_ids_to_ids_queue,
    build_and_persist_conflict_review_report,
    build_conflict_review_report,
    load_conflict_review_report,
    persist_conflict_review_report,
    recompute_report_digest,
    record_disposition_and_bind_ids,
    record_human_disposition,
)
from ipfs_datasets_py.processors.domains.uspto.ids_review_operator import (
    bind_conflict_consider_ids,
    load_ids_queue,
)


LIMITATIONS = [
    {
        "limitation_id": "lim:c1-1",
        "claim_number": 1,
        "text": "receiving a temperature signal from a probe",
    },
    {
        "limitation_id": "lim:c1-2",
        "claim_number": 1,
        "text": "activating a cooling valve when the temperature signal exceeds a threshold",
    },
]

HITS = [
    {
        "hit_id": "US9999901B2",
        "text": (
            "The controller receives a temperature signal from a probe and "
            "activates a cooling valve when the temperature signal exceeds a "
            "safety threshold."
        ),
    },
    {
        "hit_id": "US1111111B1",
        "text": "A bicycle chain lubrication system with a drip reservoir.",
    },
]

ACK = "Casey Responsible-Human"


def _scored_report(**kwargs):
    return score_conflict_risk(
        application_number="16000001",
        limitations=LIMITATIONS,
        hits=HITS,
        coverage_gaps=[
            {"kind": "foreign_patent", "status": "unsearched", "corpus": "foreign_patents"},
            {"kind": "npl", "status": "unsearched", "corpus": "npl"},
        ],
        generated_at_utc="2026-08-06T00:00:00Z",
        **kwargs,
    )


def test_disposition_codes_closed_set() -> None:
    assert DISPOSITION_CODES == {
        "not_material",
        "consider_ids",
        "distinguish_in_remarks",
        "needs_counsel",
        "deferred",
    }


def test_build_and_persist_under_prior_art_run(tmp_path: Path) -> None:
    prior = tmp_path / "prior_art" / "16000001" / "run-001"
    prior.mkdir(parents=True)

    result = build_and_persist_conflict_review_report(
        application_number="16000001",
        limitations=LIMITATIONS,
        hits=HITS,
        coverage_gaps=[],
        generated_at_utc="2026-08-06T00:00:00Z",
        prior_art_run_dir=prior,
    )
    assert result["ok"] is True
    assert result["auto_file_blocked"] is True
    assert result["content_digest"]
    assert len(result["content_digest"]) == 64
    path = Path(result["primary_path"])
    assert path.name == CONFLICT_RISK_REPORT_FILENAME
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == CONFLICT_RISK_REPORT_SCHEMA
    assert payload["auto_file_blocked"] is True
    assert payload["cells"]
    assert "coverage_gaps" in payload
    assert payload["dispositions"] == []
    assert "patentability" in (payload.get("disclaimer") or "").lower() or "not" in (
        payload.get("disclaimer") or ""
    ).lower()


def test_persist_under_both_run_dirs(tmp_path: Path) -> None:
    prior = tmp_path / "prior"
    review = tmp_path / "review"
    prior.mkdir()
    review.mkdir()
    report = _scored_report()
    result = persist_conflict_review_report(
        report,
        prior_art_run_dir=prior,
        review_run_dir=review,
    )
    assert len(result["paths"]) == 2
    p1 = json.loads((prior / CONFLICT_RISK_REPORT_FILENAME).read_text(encoding="utf-8"))
    p2 = json.loads((review / CONFLICT_RISK_REPORT_FILENAME).read_text(encoding="utf-8"))
    assert p1["content_digest"] == p2["content_digest"] == result["content_digest"]


def test_load_from_prior_art_run(tmp_path: Path) -> None:
    prior = tmp_path / "run"
    prior.mkdir()
    report = build_conflict_review_report(engine_report=_scored_report())
    persist_conflict_review_report(report, prior_art_run_dir=prior)
    loaded = load_conflict_review_report(prior_art_run_dir=prior)
    assert loaded.report_id == report.report_id
    assert loaded.content_digest == report.content_digest
    assert loaded.auto_file_blocked is True


def test_disposition_requires_acknowledger_name() -> None:
    report = _scored_report()
    with pytest.raises(ConflictReviewReportError) as exc:
        record_human_disposition(
            report,
            disposition_code="deferred",
            acknowledger_name="",
            cell_ids=[report.cells[0].cell_id] if report.cells else [],
        )
    assert exc.value.code == "acknowledger_name_required"

    with pytest.raises(ConflictReviewReportError):
        record_human_disposition(
            report,
            disposition_code="not_material",
            acknowledger_name="   ",
        )


def test_record_disposition_updates_digest(tmp_path: Path) -> None:
    prior = tmp_path / "run"
    prior.mkdir()
    report = _scored_report()
    before = report.content_digest
    cell_id = report.cells[0].cell_id
    out = record_human_disposition(
        report,
        disposition_code=DispositionCode.NEEDS_COUNSEL,
        acknowledger_name=ACK,
        cell_ids=[cell_id],
        notes="counsel review requested",
        persist=True,
        prior_art_run_dir=prior,
    )
    assert out["ok"] is True
    assert out["auto_file_blocked"] is True
    assert out["content_digest"] != before
    assert out["disposition"]["acknowledger_name"] == ACK
    assert out["disposition"]["acknowledger_id"] == ACK
    assert out["disposition"]["disposition_code"] == "needs_counsel"
    loaded = load_conflict_review_report(prior_art_run_dir=prior)
    assert len(loaded.dispositions) == 1
    assert loaded.content_digest == out["content_digest"]
    # Digest is content-bound
    rebound = recompute_report_digest(loaded)
    assert rebound.content_digest == loaded.content_digest


def test_invalid_disposition_code() -> None:
    report = _scored_report()
    with pytest.raises(ConflictReviewReportError) as exc:
        record_human_disposition(
            report,
            disposition_code="auto_file_ids",  # forbidden / invalid
            acknowledger_name=ACK,
        )
    assert exc.value.code == "invalid_disposition_code"


def test_unknown_cell_ids_fail_closed() -> None:
    report = _scored_report()
    assert report.cells
    with pytest.raises(ConflictReviewReportError) as exc:
        record_human_disposition(
            report,
            disposition_code="deferred",
            acknowledger_name=ACK,
            cell_ids=["cell:does-not-exist"],
        )
    assert exc.value.code == "unknown_cell_ids"


def test_consider_ids_binds_to_ids_queue_without_auto_file(tmp_path: Path) -> None:
    prior = tmp_path / "prior_art" / "16000001" / "run-1"
    prior.mkdir(parents=True)
    report = _scored_report()
    # Pick high/medium risk cell if present, else first cell
    target = next(
        (c for c in report.cells if c.risk.value in {"high", "medium"}),
        report.cells[0],
    )
    recorded = record_human_disposition(
        report,
        disposition_code="consider_ids",
        acknowledger_name=ACK,
        cell_ids=[target.cell_id],
        notes="human flagged for IDS consideration",
        persist=True,
        prior_art_run_dir=prior,
    )
    updated = recorded["report"]
    bind = bind_consider_ids_to_ids_queue(
        updated,
        prior_art_run_dir=prior,
        application_number="16000001",
        state_root=tmp_path,
    )
    assert bind["ok"] is True
    assert bind["auto_file_blocked"] is True
    assert bind["patent_center_filing"] is False
    assert bind["promoted"] is False
    assert bind["added_count"] >= 1
    assert bind["ids_ready_count"] == 0

    qpath = Path(bind["queue_path"])
    assert qpath.is_file()
    queue = load_ids_queue(qpath)
    assert queue.auto_file_blocked is True
    assert len(queue.candidates) >= 1
    for c in queue.candidates:
        assert c.is_ids_ready is False
        assert c.auto_file_blocked is True
        assert c.state.value == "candidate"

    # Operator wrapper path
    again = bind_conflict_consider_ids(
        report_path=prior / CONFLICT_RISK_REPORT_FILENAME,
        prior_art_run_dir=prior,
        application_number="16000001",
    )
    assert again["auto_file_blocked"] is True
    # Second bind is idempotent on document_id (no duplicate adds required)
    assert again["added_count"] == 0 or again["candidate_count"] >= bind["candidate_count"]


def test_record_disposition_and_bind_ids_convenience(tmp_path: Path) -> None:
    prior = tmp_path / "run"
    prior.mkdir()
    report = _scored_report()
    cell_id = report.cells[0].cell_id
    out = record_disposition_and_bind_ids(
        report,
        disposition_code="consider_ids",
        acknowledger_name=ACK,
        cell_ids=[cell_id],
        prior_art_run_dir=prior,
        application_number="16000001",
    )
    assert out["ok"] is True
    assert out["auto_file_blocked"] is True
    assert out["ids_bind"] is not None
    assert out["ids_bind"]["auto_file_blocked"] is True
    assert out["ids_bind"]["added_count"] >= 1
    assert (prior / "ids_review_queue.json").is_file()
    assert (prior / CONFLICT_RISK_REPORT_FILENAME).is_file()


def test_non_consider_ids_skips_queue_bind(tmp_path: Path) -> None:
    prior = tmp_path / "run"
    prior.mkdir()
    report = _scored_report()
    out = record_disposition_and_bind_ids(
        report,
        disposition_code="not_material",
        acknowledger_name=ACK,
        cell_ids=[report.cells[0].cell_id],
        prior_art_run_dir=prior,
    )
    assert out["ids_bind"] is None
    assert not (prior / "ids_review_queue.json").is_file()


def test_no_forbidden_patentability_language(tmp_path: Path) -> None:
    prior = tmp_path / "run"
    prior.mkdir()
    result = build_and_persist_conflict_review_report(
        application_number="16000001",
        limitations=LIMITATIONS,
        hits=HITS,
        coverage_gaps=[],
        generated_at_utc="2026-08-06T12:00:00Z",
        prior_art_run_dir=prior,
    )
    blob = json.dumps(result).lower()
    for phrase in (
        "is patentable",
        "is novel",
        "is obvious",
        "no prior art exists",
        "will be allowed",
    ):
        assert phrase not in blob
    assert result["auto_file_blocked"] is True
    assert "not legal advice" in REVIEW_ONLY_CONFLICT_REVIEW_DISCLAIMER.lower()


def test_persist_requires_target() -> None:
    report = _scored_report()
    with pytest.raises(ConflictReviewReportError) as exc:
        persist_conflict_review_report(report)
    assert exc.value.code == "missing_persist_target"

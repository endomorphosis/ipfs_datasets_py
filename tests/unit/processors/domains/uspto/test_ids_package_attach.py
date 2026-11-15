"""Unit tests: attach IDS-ready export into revision package as role ids."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.ids_review_queue import (
    IDS_REVIEW_QUEUE_DISCLAIMER,
    IDS_REVIEW_QUEUE_SCHEMA_VERSION,
    IdsCandidateState,
    IdsReferenceCandidate,
    IdsReviewQueue,
    MaterialityDisposition,
    RelevanceDisposition,
    build_ids_review_queue,
    promote_to_ids_ready,
    record_materiality_review,
    record_relevance_review,
)
from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
    score_conflict_risk,
)
from ipfs_datasets_py.processors.domains.uspto.conflict_review_report import (
    persist_conflict_review_report,
    record_human_disposition,
)
from ipfs_datasets_py.processors.domains.uspto.ids_review_operator import (
    attach_ids_export_to_revision,
    bind_conflict_consider_ids,
    export_ids_ready_checklist,
    list_ids_candidates,
    load_ids_queue,
    save_ids_queue,
)
from ipfs_datasets_py.processors.domains.uspto.revision_response import (
    IDS_ATTACHMENT_ROLE,
    attach_ids_role_files,
    attach_to_revision,
    open_revision_case,
)


SUBJECT = "app-18654466"
REVIEWER = "operator:test"
REVIEW_T0 = "2024-06-01T12:00:00Z"
REVIEW_T1 = "2024-06-01T12:05:00Z"
REVIEW_T2 = "2024-06-01T12:10:00Z"


def _write_promoted_queue(path: Path) -> Path:
    """Persist a queue with one IDS-ready candidate (human reviews done)."""
    queue = build_ids_review_queue(subject_id=SUBJECT, queue_id="ids-queue:test-attach")
    cand = IdsReferenceCandidate(
        candidate_id="ids-cand:doc-prior-1",
        document_id="doc:prior-1",
        subject_id=SUBJECT,
        state=IdsCandidateState.CANDIDATE,
        citation_text="US 10,000,000 — monitoring device with tamper evidence",
        identifiers={"publication_number": "US10000000"},
        auto_file_blocked=True,
        is_ids_ready=False,
    )
    queue = IdsReviewQueue(
        schema_version=IDS_REVIEW_QUEUE_SCHEMA_VERSION,
        queue_id=queue.queue_id,
        subject_id=SUBJECT,
        candidates=(cand,),
        auto_file_blocked=True,
        claims_exhaustive_search=False,
        disclaimer=IDS_REVIEW_QUEUE_DISCLAIMER,
    )
    queue = record_relevance_review(
        queue,
        candidate_id=cand.candidate_id,
        reviewer_id=REVIEWER,
        disposition=RelevanceDisposition.RELEVANT,
        acted_at_utc=REVIEW_T0,
        is_natural_person=True,
    )
    queue = record_materiality_review(
        queue,
        candidate_id=cand.candidate_id,
        reviewer_id=REVIEWER,
        disposition=MaterialityDisposition.MATERIAL,
        acted_at_utc=REVIEW_T1,
        is_natural_person=True,
    )
    queue = promote_to_ids_ready(
        queue,
        candidate_id=cand.candidate_id,
        reviewer_id=REVIEWER,
        acted_at_utc=REVIEW_T2,
        is_natural_person=True,
        require_coverage_acknowledgement=False,
    )
    assert queue.candidates[0].is_ids_ready is True
    assert queue.auto_file_blocked is True
    save_ids_queue(queue, path)
    return path


def test_export_attaches_markdown_json_as_ids_role(tmp_path: Path) -> None:
    qpath = _write_promoted_queue(tmp_path / "ids_review_queue.json")
    case = open_revision_case(
        "18654466",
        state_root=tmp_path,
        document_description="Non-Final Rejection",
        document_code="CTNF",
        official_date="2024-05-03",
    )
    assert case.package_dir

    exported = export_ids_ready_checklist(
        qpath,
        revision_id=case.revision_id,
        state_root=tmp_path,
    )

    assert exported["ok"] is True
    assert exported["auto_file_blocked"] is True
    assert exported["patent_center_filing"] is False
    assert exported["role"] == IDS_ATTACHMENT_ROLE == "ids"
    assert exported["revision_id"] == case.revision_id
    assert exported["ids_ready_count"] >= 1

    package = Path(exported["package_dir"])
    assert package.is_dir()
    assert package == Path(case.package_dir)

    # Both markdown and JSON land under package_dir with ids role prefix
    package_files = [Path(p) for p in exported["package_files"]]
    assert len(package_files) >= 2
    assert all(p.is_file() for p in package_files)
    assert all(p.parent == package for p in package_files)
    names = {p.name for p in package_files}
    assert any(n.startswith("ids__") and n.endswith(".json") for n in names)
    assert any(n.startswith("ids__") and n.endswith(".md") for n in names)

    roles = {a["role"] for a in exported["attachments"]}
    assert roles == {"ids"}

    # Source export files exist and package copies preserve content
    json_src = Path(exported["json_path"])
    md_src = Path(exported["markdown_path"])
    assert json_src.is_file()
    assert md_src.is_file()
    payload = json.loads(json_src.read_text(encoding="utf-8"))
    assert payload["auto_file_blocked"] is True
    assert payload["ids_ready_count"] >= 1
    md_text = md_src.read_text(encoding="utf-8")
    assert "Auto-file blocked" in md_text
    assert "human-only" in md_text.lower() or "never auto-files" in md_text.lower()

    pkg_json = next(p for p in package_files if p.suffix == ".json")
    pkg_payload = json.loads(pkg_json.read_text(encoding="utf-8"))
    assert pkg_payload["auto_file_blocked"] is True


def test_attach_ids_export_to_revision_standalone(tmp_path: Path) -> None:
    qpath = _write_promoted_queue(tmp_path / "ids_review_queue.json")
    case = open_revision_case(
        "18654466",
        state_root=tmp_path,
        document_description="Notice to File Missing Parts",
        official_date="2025-01-15",
    )

    result = attach_ids_export_to_revision(
        case.revision_id,
        queue_path=qpath,
        state_root=tmp_path,
    )
    assert result["ok"] is True
    assert result["auto_file_blocked"] is True
    assert result["patent_center_filing"] is False
    assert result["role"] == "ids"
    package = Path(result["package_dir"])
    assert any(package.glob("ids__*.json"))
    assert any(package.glob("ids__*.md"))

    pointer = Path(case.case_dir) / "ids_export_attachment.json"
    assert pointer.is_file()
    ptr = json.loads(pointer.read_text(encoding="utf-8"))
    assert ptr["auto_file_blocked"] is True
    assert ptr["patent_center_filing"] is False
    assert ptr["role"] == "ids"


def test_attach_ids_role_files_direct(tmp_path: Path) -> None:
    case = open_revision_case(
        "16000001",
        state_root=tmp_path,
        document_description="Non-Final Rejection",
        official_date="2024-05-03",
    )
    json_f = tmp_path / "ids_ready_export.json"
    md_f = tmp_path / "ids_ready_export.md"
    json_f.write_text(
        json.dumps({"auto_file_blocked": True, "ids_ready_count": 0}) + "\n",
        encoding="utf-8",
    )
    md_f.write_text("# IDS checklist\n\nAuto-file blocked: **yes**\n", encoding="utf-8")

    updated = attach_ids_role_files(
        case.revision_id,
        [json_f, md_f],
        state_root=tmp_path,
    )
    assert len(updated.attachments) == 2
    assert all(a.role == "ids" for a in updated.attachments)
    package = Path(updated.package_dir)
    assert (package / "ids__ids_ready_export.json").is_file()
    assert (package / "ids__ids_ready_export.md").is_file()


def test_attach_to_revision_accepts_ids_role(tmp_path: Path) -> None:
    case = open_revision_case(
        "16000002",
        state_root=tmp_path,
        document_description="Non-Final Rejection",
        official_date="2024-05-03",
    )
    f = tmp_path / "sb08_notes.md"
    f.write_text("human IDS form prep notes\n", encoding="utf-8")
    updated = attach_to_revision(
        case.revision_id,
        f,
        role="ids",
        state_root=tmp_path,
    )
    assert updated.attachments[0].role == "ids"
    assert Path(updated.attachments[0].path).is_file()


def test_attach_ids_role_files_empty_raises(tmp_path: Path) -> None:
    case = open_revision_case(
        "16000003",
        state_root=tmp_path,
        document_description="Non-Final Rejection",
        official_date="2024-05-03",
    )
    with pytest.raises(Exception) as excinfo:
        attach_ids_role_files(case.revision_id, [], state_root=tmp_path)
    assert "empty" in str(excinfo.value).lower() or getattr(
        excinfo.value, "code", ""
    ) == "empty_ids_attach"


def test_export_without_revision_still_blocks_auto_file(tmp_path: Path) -> None:
    qpath = _write_promoted_queue(tmp_path / "ids_review_queue.json")
    exported = export_ids_ready_checklist(qpath)
    assert exported["ok"] is True
    assert exported["auto_file_blocked"] is True
    assert exported["patent_center_filing"] is False
    assert "revision_id" not in exported or not exported.get("revision_id")
    assert Path(exported["json_path"]).is_file()
    assert Path(exported["markdown_path"]).is_file()


def test_consider_ids_disposition_binds_ids_queue_not_ready(tmp_path: Path) -> None:
    """PAAR-041: consider_ids → human IDS queue; never auto-file / never IDS-ready."""
    run_dir = tmp_path / "prior_art" / "18654466" / "run-crr"
    run_dir.mkdir(parents=True)

    report = score_conflict_risk(
        application_number="18654466",
        limitations=[
            {
                "limitation_id": "lim:c1-1",
                "claim_number": 1,
                "text": "monitoring device with tamper evidence",
            }
        ],
        hits=[
            {
                "hit_id": "doc-prior-1",
                "text": "monitoring device with tamper evidence and secure seal",
            }
        ],
        coverage_gaps=[],
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    persist_conflict_review_report(report, prior_art_run_dir=run_dir)
    cell_id = report.cells[0].cell_id
    recorded = record_human_disposition(
        report,
        disposition_code="consider_ids",
        acknowledger_name=REVIEWER,
        cell_ids=[cell_id],
        notes="flag for IDS review queue",
        persist=True,
        prior_art_run_dir=run_dir,
    )
    assert recorded["auto_file_blocked"] is True

    bind = bind_conflict_consider_ids(
        recorded["report"],
        prior_art_run_dir=run_dir,
        application_number="18654466",
        state_root=tmp_path,
    )
    assert bind["ok"] is True
    assert bind["auto_file_blocked"] is True
    assert bind["patent_center_filing"] is False
    assert bind["added_count"] >= 1
    assert bind["ids_ready_count"] == 0

    qpath = Path(bind["queue_path"])
    queue = load_ids_queue(qpath)
    listed = list_ids_candidates(queue)
    assert listed["auto_file_blocked"] is True
    assert listed["ids_ready_count"] == 0
    assert listed["candidate_count"] >= 1
    assert all(not c["is_ids_ready"] for c in listed["candidates"])

    # Export path still blocks auto-file (no ready refs yet)
    exported = export_ids_ready_checklist(qpath)
    assert exported["auto_file_blocked"] is True
    assert exported["ids_ready_count"] == 0
    assert exported["patent_center_filing"] is False

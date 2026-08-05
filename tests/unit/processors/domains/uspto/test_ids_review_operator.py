"""Unit tests for human IDS review operator + audit show/report."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.domains.uspto.ids_review_operator import (
    export_ids_ready_checklist,
    list_ids_candidates,
    resolve_ids_queue_path,
    review_ids_candidate,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    search_prior_art,
)
from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
    audit_submission,
    build_ids_queue_from_prior_art_run,
    list_compliance_audits,
    show_compliance_audit,
)


def _snap(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "document_id": "doc:ids-1",
                    "title": "Monitoring device with tamper evidence",
                    "abstract": "tamper evident monitoring",
                    "claims": "1. A method comprising monitoring.",
                    "source_cid": (
                        "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
                    ),
                    "publicationDate": "2020-01-15",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_ids_review_promote_and_export(tmp_path: Path) -> None:
    pa = search_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text="1. A method comprising tamper evident monitoring.",
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        local_snapshot_path=_snap(tmp_path / "snap.json"),
        max_queries=2,
    )
    built = build_ids_queue_from_prior_art_run(
        pa["run_dir"],
        application_number="18654466",
        persist=True,
        state_root=tmp_path,
    )
    assert built["candidate_count"] >= 1
    qpath = Path(built["paths"]["ids_queue"])
    assert qpath.is_file()

    listed = list_ids_candidates(
        __import__(
            "ipfs_datasets_py.processors.domains.uspto.ids_review_operator",
            fromlist=["load_ids_queue"],
        ).load_ids_queue(qpath)
    )
    cand_id = listed["candidates"][0]["candidate_id"]

    # Partial review cannot promote
    mid = review_ids_candidate(
        qpath,
        candidate_id=cand_id,
        reviewer_id="operator:test",
        relevance="relevant",
    )
    assert mid["candidate"]["is_ids_ready"] is False

    full = review_ids_candidate(
        qpath,
        candidate_id=cand_id,
        reviewer_id="operator:test",
        materiality="material",
        promote=True,
    )
    assert full["ok"] is True
    assert full["candidate"]["is_ids_ready"] is True
    assert full["ids_ready_count"] >= 1

    exported = export_ids_ready_checklist(qpath)
    assert exported["ok"] is True
    assert exported["ids_ready_count"] >= 1
    assert Path(exported["json_path"]).is_file()
    assert Path(exported["markdown_path"]).is_file()
    md = Path(exported["markdown_path"]).read_text(encoding="utf-8")
    assert "IDS-ready" in md
    assert "never auto-files" in md.lower() or "Auto-file blocked" in md


def test_audit_list_show_markdown(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "02_amended_claims.pdf").write_bytes(b"x")
    (pkg / "03_remarks.pdf").write_bytes(b"x")
    pa = search_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text="1. A method comprising tamper evident monitoring.",
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        local_snapshot_path=_snap(tmp_path / "snap.json"),
        max_queries=2,
    )
    audit = audit_submission(
        application_number="18654466",
        state_root=tmp_path,
        package_dir=pkg,
        prior_art_run_dir=pa["run_dir"],
        persist=True,
    )
    assert Path(audit["paths"]["markdown"]).is_file()
    md = Path(audit["paths"]["markdown"]).read_text(encoding="utf-8")
    assert "Action plan" in md
    assert "Filing rules" in md

    listed = list_compliance_audits(
        application_number="18654466", state_root=tmp_path
    )
    assert listed["count"] >= 1

    shown = show_compliance_audit(
        application_number="18654466", state_root=tmp_path
    )
    assert shown["ok"] is True
    assert shown["overall_status"]
    assert Path(shown["markdown_path"]).is_file()

    # resolve queue via application number
    qpath = resolve_ids_queue_path(
        application_number="18654466", state_root=tmp_path
    )
    assert qpath.is_file()

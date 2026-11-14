"""End-to-end prior-art compliance loop (offline).

Covers PATLAW-205 acceptance path:

    search → audit → IDS → re-audit → filing-assist

Offline path uses a local patent snapshot. Does not require ODP/HF network,
Patent Center session, or API keys.
"""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.domains.uspto.filing_assist import (
    HARD_BARRIER_CLICK_LABELS,
    build_filing_checklist,
)
from ipfs_datasets_py.processors.domains.uspto.ids_review_operator import (
    export_ids_ready_checklist,
    list_ids_candidates,
    load_ids_queue,
    resolve_ids_queue_path,
    review_ids_candidate,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    search_prior_art,
)
from ipfs_datasets_py.processors.domains.uspto.revision_response import (
    IDS_ATTACHMENT_ROLE,
    attach_to_revision,
    open_revision_case,
)
from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
    AUDIT_DISCLAIMER,
    DELTA_SCHEMA,
    audit_submission,
)


CLAIM = (
    "1. A method comprising tamper evident securing of a monitoring device "
    "to an individual."
)

APP = "18654466"
REVIEWER = "operator:e2e"


def _snap(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "document_id": "doc:tamper-monitor",
                    "title": "Tamper evident monitoring device",
                    "abstract": "tamper evident securing monitoring individual",
                    "claims": CLAIM,
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


def _open_oa_case(tmp_path: Path, *, app: str = APP):
    case = open_revision_case(
        app,
        state_root=tmp_path,
        document_identifier="OA-E2E",
        document_code="CTNF",
        document_description="Non-Final Rejection",
        official_date="2025-01-15",
        kind="office_action_nonfinal",
        analyze=False,
        notes=["e2e compliance audit"],
    )
    pkg = Path(case.package_dir)
    claims = pkg / "02_amended_claims.pdf"
    remarks = pkg / "03_remarks.pdf"
    claims.write_bytes(b"%PDF-claims")
    remarks.write_bytes(b"%PDF-remarks")
    case = attach_to_revision(
        case.revision_id, claims, role="amended_claims", state_root=tmp_path
    )
    case = attach_to_revision(
        case.revision_id, remarks, role="remarks", state_root=tmp_path
    )
    return case


def _run_offline_search(tmp_path: Path, *, app: str = APP) -> dict:
    return search_prior_art(
        application_number=app,
        state_root=tmp_path,
        claims_text=CLAIM,
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        local_snapshot_path=_snap(tmp_path / "snap.json"),
        max_queries=4,
    )


def test_e2e_revision_prior_art_and_audit(tmp_path: Path) -> None:
    # 1) Open revision case (OA nonfinal → office_action_response scenario)
    case = _open_oa_case(tmp_path)
    assert case.revision_id
    assert case.package_dir
    assert len(case.attachments) >= 2

    # 2) Prior-art search (local snapshot — offline)
    pa = _run_offline_search(tmp_path)
    assert pa["ok"] is True
    assert Path(pa["paths"]["journal"]).is_file()
    assert Path(pa["paths"]["claim_chart"]).is_file()

    # 3) Combined audit (revision + package + prior-art run)
    audit = audit_submission(
        revision_id=case.revision_id,
        state_root=tmp_path,
        prior_art_run_dir=pa["run_dir"],
        application_type="utility",
        persist=True,
    )
    assert audit["ok"] is True
    assert audit["overall_status"] in {"ready", "review_required", "not_ready"}

    summary = audit["summary"]
    assert summary["revision_id"] == case.revision_id
    assert summary["application_number"] == "18654466"

    filing = summary["filing_rules"]
    assert filing["matched_count"] >= 1
    assert filing["missing_mandatory_count"] == 0
    assert "amended_claims" in filing["roles_present"]
    assert "remarks" in filing["roles_present"]
    assert any("1.121" in c or "1.111" in c for c in (filing.get("cfr_citations") or []))

    prior = summary["prior_art"]
    assert prior["status"] in {"ready", "review_required", "not_ready"}
    # US-only local search → foreign/NPL gaps visible as warnings (not hard block)
    assert "prior_art_run_missing" not in (prior.get("blocking_codes") or [])

    inv = summary["package_inventory"]
    assert inv["file_count"] >= 2

    # Persisted artifacts
    assert Path(audit["paths"]["audit"]).is_file()
    assert Path(audit["paths"]["filing_rules"]).is_file()
    assert Path(audit["paths"]["prior_art"]).is_file()
    assert Path(audit["paths"]["revision_pointer"]).is_file()

    saved = json.loads(Path(audit["paths"]["audit"]).read_text(encoding="utf-8"))
    assert "not legal advice" in saved["disclaimer"].lower()
    assert "review_tips" in saved
    assert AUDIT_DISCLAIMER

    # 4) Auto-discover latest prior-art run without explicit path
    auto = audit_submission(
        revision_id=case.revision_id,
        state_root=tmp_path,
        persist=False,
    )
    assert auto["ok"] is True
    assert auto["summary"]["prior_art_bundle"]["present"] is True


def test_e2e_missing_remarks_is_flagged(tmp_path: Path) -> None:
    """Remarks are unconditional mandatory for OA response; claims are conditional."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    # Claims present without remarks
    (pkg / "02_amended_claims.pdf").write_bytes(b"x")
    audit = audit_submission(
        application_number="18654466",
        state_root=tmp_path,
        package_dir=pkg,
        scenario="office_action_response",
        persist=False,
    )
    filing = audit["summary"]["filing_rules"]
    assert filing["missing_mandatory_count"] >= 1
    assert audit["overall_status"] in {"review_required", "not_ready"}
    kinds = {
        g.get("evidence_kind")
        for g in filing["evidence_gaps"]
        if g.get("status") == "missing"
    }
    assert "remarks" in kinds


def test_e2e_remarks_only_skips_conditional_claim_amendment(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "03_remarks.pdf").write_bytes(b"x")
    audit = audit_submission(
        application_number="18654466",
        state_root=tmp_path,
        package_dir=pkg,
        scenario="office_action_response",
        persist=False,
    )
    filing = audit["summary"]["filing_rules"]
    missing_kinds = {
        g.get("evidence_kind")
        for g in filing["evidence_gaps"]
        if g.get("status") == "missing"
    }
    # Conditional claim_amendment should not block a remarks-only reply package
    assert "claim_amendment" not in missing_kinds
    assert filing["missing_mandatory_count"] == 0


def test_e2e_full_compliance_loop_search_audit_ids_reaudit_filing_assist(
    tmp_path: Path,
) -> None:
    """Full offline loop: search → audit → IDS → re-audit → filing-assist."""
    case = _open_oa_case(tmp_path)
    pa = _run_offline_search(tmp_path)
    assert pa["ok"] is True
    run_dir = Path(pa["run_dir"])

    # --- audit ---
    audit1 = audit_submission(
        revision_id=case.revision_id,
        state_root=tmp_path,
        prior_art_run_dir=run_dir,
        application_type="utility",
        persist=True,
        build_ids_queue=True,
    )
    assert audit1["ok"] is True
    audit_id_1 = audit1["summary"]["audit_id"]
    assert audit1["summary"]["ids_queue"]["auto_file_blocked"] is True
    assert Path(audit1["paths"]["audit"]).is_file()
    # Action plan should point operators at next loop steps
    plan = audit1["summary"].get("action_plan") or []
    assert isinstance(plan, list)

    # --- IDS: resolve queue, optional promote, export + attach as role ids ---
    qpath = resolve_ids_queue_path(
        application_number=APP,
        run_dir=run_dir,
        state_root=tmp_path,
    )
    assert qpath.is_file()
    listed = list_ids_candidates(load_ids_queue(qpath))
    assert listed["ok"] is True
    assert listed["auto_file_blocked"] is True
    candidates = listed.get("candidates") or []

    if candidates:
        cid = candidates[0]["candidate_id"]
        reviewed = review_ids_candidate(
            qpath,
            candidate_id=cid,
            reviewer_id=REVIEWER,
            relevance="relevant",
            materiality="material",
            promote=True,
        )
        assert reviewed["ok"] is True
        assert reviewed["candidate"]["is_ids_ready"] is True
        assert reviewed["ids_ready_count"] >= 1

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
    package_files = [Path(p) for p in (exported.get("package_files") or [])]
    assert package_files, "IDS export must attach files into package_dir"
    assert all(p.is_file() for p in package_files)
    assert any(p.name.startswith("ids__") for p in package_files)
    # Source export preserves human-only disclaimer
    md_src = Path(exported["markdown_path"])
    md_text = md_src.read_text(encoding="utf-8")
    assert "auto-file" in md_text.lower() or "auto file" in md_text.lower()

    pointer = Path(case.case_dir) / "ids_export_attachment.json"
    assert pointer.is_file()
    ptr = json.loads(pointer.read_text(encoding="utf-8"))
    assert ptr["auto_file_blocked"] is True
    assert ptr["patent_center_filing"] is False
    assert ptr["role"] == "ids"

    # --- re-audit with delta (history immutable) ---
    prior_audit_path = Path(audit1["paths"]["audit"])
    prior_payload = json.loads(prior_audit_path.read_text(encoding="utf-8"))
    prior_fingerprint = json.dumps(prior_payload, sort_keys=True)

    audit2 = audit_submission(
        revision_id=case.revision_id,
        state_root=tmp_path,
        prior_art_run_dir=run_dir,
        application_type="utility",
        persist=True,
        delta_from=audit_id_1,
    )
    assert audit2["ok"] is True
    assert audit2["summary"]["audit_id"] != audit_id_1
    delta = audit2.get("delta") or audit2["summary"].get("delta")
    assert isinstance(delta, dict)
    assert delta.get("schema") == DELTA_SCHEMA or "closed_gaps" in delta
    assert delta.get("history_rewritten") is False
    assert "closed_gaps" in delta and "opened_gaps" in delta
    assert "status_transition" in delta
    assert "closed_gap_count" in delta and "opened_gap_count" in delta
    # Prior audit file must be unchanged (no history rewrite)
    after = prior_audit_path.read_text(encoding="utf-8")
    assert json.dumps(json.loads(after), sort_keys=True) == prior_fingerprint
    # New audit + delta artifact persisted separately
    assert Path(audit2["paths"]["audit"]).is_file()
    assert Path(audit2["paths"]["audit"]) != prior_audit_path
    if "delta" in audit2["paths"]:
        assert Path(audit2["paths"]["delta"]).is_file()

    # --- filing-assist: checklist only (no browser / no Sign-Pay-Submit) ---
    checklist = build_filing_checklist(
        application_number=APP,
        package_dir=Path(case.package_dir),
        state_root=tmp_path,
    )
    payload = checklist.to_dict()
    assert payload["application_number"] == APP
    assert payload["package_path"]
    hard_steps = [s for s in payload["steps"] if s.get("hard_barrier")]
    assert len(hard_steps) >= 3
    hard_ids = {s["step_id"] for s in hard_steps}
    assert "human-sign-certify" in hard_ids or any(
        "sign" in s["step_id"] for s in hard_steps
    )
    assert any("pay" in s["step_id"] for s in hard_steps)
    assert any("submit" in s["step_id"] for s in hard_steps)
    for s in hard_steps:
        assert s["automation_allowed"] is False
        assert s["actor"] == "human"
    assert HARD_BARRIER_CLICK_LABELS
    assert any("sign" in label for label in HARD_BARRIER_CLICK_LABELS)
    assert "not" in payload["disclaimer"].lower() or "human" in payload["disclaimer"].lower()
    # Receipt drop folder is prepared for post-submit human downloads
    assert payload.get("post_submit_receipt_dir")
    assert Path(payload["post_submit_receipt_dir"]).is_dir()

"""End-to-end: prior-art search → package → submission compliance audit.

Offline path (local snapshot). Does not require ODP/HF network.
"""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    search_prior_art,
)
from ipfs_datasets_py.processors.domains.uspto.revision_response import (
    attach_to_revision,
    open_revision_case,
)
from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
    AUDIT_DISCLAIMER,
    audit_submission,
)


CLAIM = (
    "1. A method comprising tamper evident securing of a monitoring device "
    "to an individual."
)


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


def test_e2e_revision_prior_art_and_audit(tmp_path: Path) -> None:
    # 1) Open revision case (OA nonfinal → office_action_response scenario)
    case = open_revision_case(
        "18654466",
        state_root=tmp_path,
        document_identifier="OA-E2E",
        document_code="CTNF",
        document_description="Non-Final Rejection",
        official_date="2025-01-15",
        kind="office_action_nonfinal",
        analyze=False,
        notes=["e2e compliance audit"],
    )
    assert case.revision_id
    assert case.package_dir

    # 2) Human-authored package files + attach roles
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
    assert len(case.attachments) >= 2

    # 3) Prior-art search (local snapshot — offline)
    pa = search_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text=CLAIM,
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        local_snapshot_path=_snap(tmp_path / "snap.json"),
        max_queries=4,
    )
    assert pa["ok"] is True
    assert Path(pa["paths"]["journal"]).is_file()
    assert Path(pa["paths"]["claim_chart"]).is_file()

    # 4) Combined audit (revision + package + prior-art run)
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

    # 5) Auto-discover latest prior-art run without explicit path
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
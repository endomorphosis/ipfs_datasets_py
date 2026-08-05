"""Unit tests for submission compliance audit (MPEP/CFR + prior art)."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    search_prior_art,
)
from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
    AUDIT_DISCLAIMER,
    audit_filing_rules,
    audit_prior_art_compliance,
    audit_submission,
    inventory_package_dir,
    load_prior_art_audit_bundle,
)


def _snap(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "document_id": "doc:encode",
                    "title": "Tamper evident monitoring",
                    "abstract": "A method comprising tamper evident securing",
                    "claims": "1. A method comprising tamper evident securing.",
                    "source_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
                    "publicationDate": "2020-01-15",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_inventory_package_dir_roles(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "02_amended_claims.pdf").write_bytes(b"x")
    (pkg / "remarks_final.pdf").write_bytes(b"x")
    inv = inventory_package_dir(pkg)
    assert inv["file_count"] == 2
    assert "amended_claims" in inv["roles_present"]
    assert "remarks" in inv["roles_present"]
    assert "claim_amendment" in inv["evidence_kinds_present"] or "claims" in inv[
        "evidence_kinds_present"
    ]


def test_audit_filing_rules_matches_oa_response() -> None:
    result = audit_filing_rules(
        application_number="18654466",
        application_type="utility",
        scenario="office_action_response",
        prosecution_stage="examination",
        attached_roles=("amended_claims", "remarks"),
        package_inventory={
            "roles_present": ["amended_claims", "remarks"],
            "evidence_kinds_present": ["claim_amendment", "remarks", "claims"],
        },
    )
    assert result["matched_count"] >= 1
    assert "37 C.F.R" in " ".join(result["cfr_citations"]) or result["cfr_citations"]
    assert result["missing_mandatory_count"] == 0
    assert result["status"] in {"ready", "review_required"}


def test_audit_prior_art_missing_run() -> None:
    result = audit_prior_art_compliance({"present": False})
    assert result["status"] == "not_ready"
    assert "prior_art_run_missing" in result["blocking_codes"]


def test_full_audit_with_prior_art_run(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "02_amended_claims.pdf").write_bytes(b"x")
    (pkg / "03_remarks.pdf").write_bytes(b"x")

    pa = search_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text=(
            "1. A method comprising tamper evident securing of a monitoring device."
        ),
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        local_snapshot_path=_snap(tmp_path / "snap.json"),
        max_queries=3,
    )
    bundle = load_prior_art_audit_bundle(pa["run_dir"])
    assert bundle["present"] is True

    audit = audit_submission(
        application_number="18654466",
        state_root=tmp_path,
        package_dir=pkg,
        prior_art_run_dir=pa["run_dir"],
        persist=True,
    )
    assert audit["ok"] is True
    assert audit["overall_status"] in {"ready", "review_required", "not_ready"}
    summary = audit["summary"]
    assert summary["filing_rules"]["matched_count"] >= 1
    assert summary["prior_art"]["status"] in {
        "ready",
        "review_required",
        "not_ready",
    }
    # Foreign/NPL gaps should surface as warnings when US-only search ran
    assert "disclaimer" in summary
    assert "not legal advice" in AUDIT_DISCLAIMER.lower()
    assert Path(audit["paths"]["audit"]).is_file()
    saved = json.loads(Path(audit["paths"]["audit"]).read_text(encoding="utf-8"))
    assert saved["application_number"] == "18654466"
    assert "review_tips" in saved

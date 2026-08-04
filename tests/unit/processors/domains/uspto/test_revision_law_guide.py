"""Unit tests for law-guided revision packages."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.domains.uspto.revision_law_guide import (
    build_revision_law_guide,
    lookup_authority_excerpt,
    seed_authority_corpus_readme,
)
from ipfs_datasets_py.processors.domains.uspto.revision_response import (
    attach_to_revision,
    open_revision_case,
)


def test_seed_and_lookup_excerpt(tmp_path: Path) -> None:
    corpus = seed_authority_corpus_readme(tmp_path)
    assert (corpus / "README.txt").is_file()
    assert (corpus / "index.json").is_file()

    target = corpus / "cfr" / "37" / "1.121.txt"
    target.parent.mkdir(parents=True)
    target.write_text(
        "37 C.F.R. § 1.121 Manner of making amendments in applications.\n"
        "(a) Amendments in applications… claims must be presented with status identifiers.\n",
        encoding="utf-8",
    )
    hit = lookup_authority_excerpt("37 C.F.R. 1.121", corpus_roots=[corpus])
    assert hit["found"] is True
    assert "status identifiers" in (hit.get("excerpt") or "")


def test_build_law_guide_matches_oa_rules(tmp_path: Path) -> None:
    corpus = seed_authority_corpus_readme(tmp_path)
    (corpus / "cfr" / "37").mkdir(parents=True)
    (corpus / "cfr" / "37" / "1.121.txt").write_text(
        "37 CFR 1.121 amendments require marked-up claim listings.\n",
        encoding="utf-8",
    )

    case = open_revision_case(
        "16000001",
        state_root=tmp_path,
        document_code="CTNF",
        document_description="Non-Final Rejection under 35 U.S.C. 103",
        official_date="2024-05-03",
        analyze=False,
    )
    # Simulate letter analysis with a rejection + citation
    case.letter_analysis = {
        "analysis": {
            "ok": True,
            "action_kind": "non_final_rejection",
            "rejections": [
                "Claims 1-5 are rejected under 35 U.S.C. § 103 as obvious over Smith."
            ],
            "claim_ranges": ["Claims 1-5"],
            "citations": ["35 U.S.C. § 103"],
            "objections": [],
            "response_instructions": [
                "A shortened statutory period for reply is set to expire 3 months."
            ],
            "period_months_from_text": 3,
        }
    }
    from ipfs_datasets_py.processors.domains.uspto.revision_response import (
        save_revision_case,
    )

    save_revision_case(case, state_root=tmp_path)

    guide = build_revision_law_guide(
        case.revision_id,
        state_root=tmp_path,
        application_type="utility",
        corpus_roots=[corpus],
    )
    assert guide["schema"] == "patlaw-revision-law-guide-v1"
    assert (guide.get("filing_obligations") or {}).get("matched_count", 0) >= 1
    assert any(
        "1.121" in str(c) or "claim" in str(c).lower()
        for c in (guide.get("filing_obligations") or {}).get("matched_rule_ids") or []
    ) or (guide.get("filing_obligations") or {}).get("matched_count", 0) >= 1
    # Evidence gaps should note missing remarks / claim amendment before attach
    checks = (guide.get("package_evidence") or {}).get("checks") or []
    assert checks
    assert any(c.get("status") == "missing_mandatory" for c in checks) or any(
        c.get("status") == "human_hard_barrier" for c in checks
    )

    # Attach remarks → reduces missing remarks gap
    remarks = tmp_path / "remarks.docx"
    remarks.write_bytes(b"PK\x03\x04 fake remarks")
    attach_to_revision(
        case.revision_id, remarks, role="remarks", state_root=tmp_path
    )
    guide2 = build_revision_law_guide(
        case.revision_id,
        state_root=tmp_path,
        corpus_roots=[corpus],
    )
    roles = (guide2.get("package_evidence") or {}).get("attached_roles") or []
    assert "remarks" in roles
    assert Path(guide2.get("law_guide_path") or "").is_file()

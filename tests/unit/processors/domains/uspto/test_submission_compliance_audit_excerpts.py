"""Unit tests for PATLAW-200: authority excerpts in compliance audit packages.

Acceptance
----------
* Audits persist ``mpep_authority_surface`` with found excerpts when corpus seeded.
* Markdown report includes sample citations.
"""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
    audit_mpep_authority_surface,
    audit_submission,
    render_audit_markdown,
)


# Core citations always included by audit_submission (must resolve after seed).
_CORE_CITATIONS = (
    "37 C.F.R. § 1.121",
    "37 C.F.R. § 1.111",
    "37 C.F.R. § 1.56",
    "MPEP § 714",
    "MPEP § 707",
    "MPEP § 2106",
)


def _seed_minimal_authority_corpus(state_root: Path) -> Path:
    """Materialize a bounded offline corpus under ``{state}/authority_corpus``."""
    corpus = state_root / "authority_corpus"
    index: dict[str, str] = {
        "37-cfr-1.121": "cfr/37/1.121.txt",
        "37-cfr-1.111": "cfr/37/1.111.txt",
        "37-cfr-1.56": "cfr/37/1.56.txt",
        "mpep-714": "mpep/714.txt",
        "mpep-707": "mpep/707.txt",
        "mpep-2106": "mpep/2106.txt",
    }
    bodies: dict[str, str] = {
        "cfr/37/1.121.txt": (
            "37 C.F.R. § 1.121 — Manner of making amendments in application.\n"
            "Fixture excerpt for offline audits (PATLAW-200). Status identifiers "
            "and claim amendment form requirements for examination response packages.\n"
        ),
        "cfr/37/1.111.txt": (
            "37 C.F.R. § 1.111 — Reply by applicant or patent owner to a non-final "
            "Office action. Fixture excerpt: reply must point out errors and "
            "reply to every ground of rejection. Offline decision support only.\n"
        ),
        "cfr/37/1.56.txt": (
            "37 C.F.R. § 1.56 — Duty to disclose information material to patentability. "
            "Fixture excerpt for IDS and materiality reminders. Not legal advice.\n"
        ),
        "mpep/714.txt": (
            "MPEP § 714 — Amendments, Applicant's Action (guidance only; non-binding). "
            "Fixture excerpt for claim/spec amendment practice. MPEP never elevates "
            "to binding law over statute or regulation.\n"
        ),
        "mpep/707.txt": (
            "MPEP § 707 — Office Action (guidance only; non-binding). Fixture excerpt "
            "covering examination action content. Guidance never outranks statute.\n"
        ),
        "mpep/2106.txt": (
            "MPEP § 2106 — Patent Subject Matter Eligibility (guidance only; "
            "non-binding). Fixture excerpt for eligibility analysis structure. "
            "Not a patentability determination.\n"
        ),
    }
    for rel, text in bodies.items():
        path = corpus / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (corpus / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return corpus


def test_audit_mpep_authority_surface_finds_seeded_excerpts(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    _seed_minimal_authority_corpus(state)

    surface = audit_mpep_authority_surface(
        citations=list(_CORE_CITATIONS),
        state_root=state,
        with_law_index=False,
    )
    assert surface["local_excerpts_found"] > 0
    assert surface["local_excerpts_found"] == surface["citation_count"]
    assert any(e.get("found") for e in surface["local_excerpts"])
    for excerpt in surface["local_excerpts"]:
        assert excerpt.get("found") is True, excerpt
        assert excerpt.get("excerpt")
        assert "fixture" in (excerpt.get("excerpt") or "").lower() or len(
            excerpt.get("excerpt") or ""
        ) > 40
    # state_root authority_corpus is among search roots
    roots = " ".join(surface.get("authority_corpus_roots") or [])
    assert "authority_corpus" in roots


def test_audit_submission_persists_mpep_authority_surface_with_excerpts(
    tmp_path: Path,
) -> None:
    """Acceptance: persist mpep_authority_surface with found excerpts when seeded."""
    state = tmp_path / "state"
    state.mkdir()
    _seed_minimal_authority_corpus(state)

    pkg = state / "pkg"
    pkg.mkdir()
    (pkg / "02_amended_claims.pdf").write_bytes(b"%PDF-claims")
    (pkg / "03_remarks.pdf").write_bytes(b"%PDF-remarks")

    audit = audit_submission(
        application_number="18654466",
        state_root=state,
        package_dir=pkg,
        persist=True,
        with_law_index=False,
        build_ids_queue=False,
    )
    assert audit["ok"] is True
    paths = audit["paths"]
    assert paths.get("authority"), "mpep_authority_surface.json must be persisted"
    authority_path = Path(paths["authority"])
    assert authority_path.name == "mpep_authority_surface.json"
    assert authority_path.is_file()

    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    assert authority["local_excerpts_found"] > 0
    found = [e for e in authority.get("local_excerpts") or [] if e.get("found")]
    assert found, "seeded corpus must yield found excerpts"
    assert any("1.121" in str(e.get("citation") or "") for e in found)
    assert all(e.get("excerpt") for e in found)

    # Summary rollup also reports found counts + sample citations
    summary = audit["summary"]
    mpep = summary.get("mpep_authority") or {}
    assert mpep.get("local_excerpts_found", 0) > 0
    assert mpep.get("sample_excerpts")
    assert any(s.get("found") for s in mpep["sample_excerpts"])
    assert mpep.get("sample_citations")
    assert any("C.F.R" in c or "MPEP" in c for c in mpep["sample_citations"])

    # Full audit JSON on disk matches
    saved = json.loads(Path(paths["audit"]).read_text(encoding="utf-8"))
    assert saved["mpep_authority"]["local_excerpts_found"] > 0


def test_markdown_report_includes_sample_citations(tmp_path: Path) -> None:
    """Acceptance: markdown report includes sample citations."""
    state = tmp_path / "state"
    state.mkdir()
    _seed_minimal_authority_corpus(state)

    pkg = state / "pkg"
    pkg.mkdir()
    (pkg / "remarks.pdf").write_bytes(b"x")

    audit = audit_submission(
        application_number="18654466",
        state_root=state,
        package_dir=pkg,
        persist=True,
        with_law_index=False,
        build_ids_queue=False,
    )
    md_path = Path(audit["paths"]["markdown"])
    assert md_path.is_file()
    md = md_path.read_text(encoding="utf-8")

    assert "authority excerpt" in md.lower() or "MPEP / CFR authority" in md
    assert "Sample citations" in md
    # At least one core citation string appears in the report
    assert "1.121" in md or "1.111" in md or "MPEP" in md
    # Found excerpt body should be quoted in the markdown
    assert "fixture" in md.lower() or "amendment" in md.lower() or "guidance" in md.lower()

    # render_audit_markdown is the shared renderer (also used by show)
    rendered = render_audit_markdown(audit["summary"])
    assert "Sample citations" in rendered
    assert "Local excerpts found" in rendered
    assert int(audit["summary"]["mpep_authority"]["local_excerpts_found"]) > 0


def test_render_audit_markdown_lists_citations_without_corpus() -> None:
    """Markdown still surfaces citation section when no local excerpts found."""
    summary = {
        "application_number": "18654466",
        "revision_id": None,
        "overall_status": "review_required",
        "generated_at_utc": "2026-01-01T00:00:00Z",
        "disclaimer": "decision support only",
        "filing_rules": {
            "status": "ready",
            "scenario": "office_action_response",
            "prosecution_stage": "examination",
            "matched_count": 1,
            "missing_mandatory_count": 0,
            "cfr_citations": ["37 C.F.R. § 1.121"],
            "mpep_citations": ["MPEP § 714"],
            "roles_present": ["remarks"],
            "evidence_gaps": [],
        },
        "prior_art": {
            "status": "not_ready",
            "blocking_codes": ["prior_art_run_missing"],
            "warning_codes": [],
            "searched_corpora": [],
            "unsearched_corpora": [],
        },
        "ids_queue": {"ok": False, "candidate_count": 0},
        "action_plan": [],
        "mpep_authority": {
            "citation_count": 2,
            "local_excerpts_found": 0,
            "hybrid_index_hit_count": 0,
            "sample_excerpts": [],
            "sample_citations": [],
        },
    }
    md = render_audit_markdown(summary)
    assert "Sample citations" in md
    assert "1.121" in md or "714" in md
    assert "Local excerpts found" in md

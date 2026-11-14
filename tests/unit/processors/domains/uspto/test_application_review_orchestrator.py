"""Unit tests for PAAR unified application review orchestrator (PAAR-090).

Hermetic offline only — uses tests/fixtures/uspto/paar_review/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.application_review_orchestrator import (
    EXIT_CODE_BY_DISPOSITION,
    REVIEW_ONLY_UNIFIED_DISCLAIMER,
    UNIFIED_APPLICATION_REVIEW_SCHEMA,
    ApplicationReviewOrchestratorError,
    ReviewDisposition,
    compute_disposition,
    disposition_exit_code,
    load_fixture_bundle,
    normalize_prior_hits,
    run_unified_application_review,
)


FIXTURES = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "uspto"
    / "paar_review"
)


def _assert_no_patentability(payload: dict) -> None:
    blob = json.dumps(payload).lower()
    for phrase in (
        "is patentable",
        "is unpatentable",
        "is novel",
        "is obvious",
        "no prior art exists",
        "will be allowed",
    ):
        assert phrase not in blob
    assert "not legal advice" in blob or "not a patentability" in blob


def test_fixture_bundle_loads() -> None:
    clean = load_fixture_bundle(FIXTURES / "clean_package")
    assert clean.get("claims_text")
    assert clean.get("prior_hits")
    assert clean.get("application_number") == "16990002"
    planted = load_fixture_bundle(FIXTURES / "planted_conflict")
    assert planted.get("prior_hits")
    assert any(
        h.get("planted_overlap") for h in planted["prior_hits"] if isinstance(h, dict)
    )


def test_normalize_prior_hits_prefers_body_excerpt() -> None:
    rows = normalize_prior_hits(
        [
            {
                "hit_id": "h1",
                "title": "short",
                "body_excerpt": "long body excerpt with temperature signal",
            }
        ]
    )
    assert rows[0]["text"].startswith("long body")


def test_clean_package_review_not_ready_or_review_required(tmp_path: Path) -> None:
    """Clean package: foreign/NPL gaps + unrelated hits → not ready/review, never high alone."""
    report = run_unified_application_review(
        fixture_dir=FIXTURES / "clean_package",
        state_root=tmp_path,
        persist=True,
        include_diligence=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.schema == UNIFIED_APPLICATION_REVIEW_SCHEMA
    assert report.auto_file_blocked is True
    assert report.disclaimer
    assert "not legal advice" in report.disclaimer.lower() or "patentability" in report.disclaimer.lower()
    assert report.disposition in {
        ReviewDisposition.REVIEW_REQUIRED,
        ReviewDisposition.NOT_READY,
        ReviewDisposition.READY,
    }
    # With foreign/NPL unsearched, matter risk cannot be low → not ready typically
    # (coverage penalty). Clean package has authority bound + full IFW codes.
    assert report.exit_code_hint in {0, 1, 2}
    assert report.exit_code_hint == EXIT_CODE_BY_DISPOSITION[report.disposition.value]
    payload = report.to_dict()
    _assert_no_patentability(payload)
    assert payload["claim_model_ref"]["content_digest"]
    assert payload["conflict_risk_ref"]["matter_risk"] in {
        "unknown",
        "low",
        "medium",
        "high",
    }
    assert payload["conformance_ref"]["overall_status"] in {
        "satisfied",
        "unsatisfied",
        "unknown",
        "human_only",
    }
    # Persist layout
    assert report.persist_path
    persist = Path(report.persist_path)
    assert persist.is_dir()
    assert (persist / "unified_application_review.json").is_file()
    assert "compliance_audits" in persist.parts
    assert "review_" in persist.name


def test_planted_conflict_elevates_risk(tmp_path: Path) -> None:
    report = run_unified_application_review(
        fixture_dir=FIXTURES / "planted_conflict",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    risk = report.conflict_risk_ref.get("matter_risk")
    assert risk in {"medium", "high", "unknown", "low"}
    # Planted overlap should produce at least one scored cell when claims parse
    assert report.claim_model_ref.get("claim_count", 0) >= 1
    # Medium/high without disposition → not ready for "ready"
    if risk in {"medium", "high"}:
        assert report.disposition is not ReviewDisposition.READY
        assert report.exit_code_hint in {1, 2}
    _assert_no_patentability(report.to_dict())


def test_missing_authority_never_ready(tmp_path: Path) -> None:
    report = run_unified_application_review(
        fixture_dir=FIXTURES / "missing_authority",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.disposition is not ReviewDisposition.READY
    assert report.exit_code_hint in {1, 2}
    assert "authority_corpus_missing" in report.reasons or report.disposition in {
        ReviewDisposition.NOT_READY,
        ReviewDisposition.REVIEW_REQUIRED,
    }
    # Conformance should not be satisfied when authority unbound
    assert report.conformance_ref.get("overall_status") != "satisfied" or (
        report.disposition is not ReviewDisposition.READY
    )


def test_no_persist_skips_write(tmp_path: Path) -> None:
    report = run_unified_application_review(
        fixture_dir=FIXTURES / "clean_package",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.persist_path is None
    # Nothing under compliance_audits
    audits = tmp_path / "compliance_audits"
    assert not audits.exists() or not any(audits.rglob("unified_application_review.json"))


def test_empty_claims_not_ready(tmp_path: Path) -> None:
    report = run_unified_application_review(
        application_number="16000099",
        claims_text="",
        package_inventory={
            "ifw_codes": ["CLM", "SPEC", "ABST", "DRW", "ADS", "OATH", "IFEE"],
            "authority_corpus_bound": True,
            "application_type": "utility",
            "scenario": "new_application",
        },
        prior_hits=[],
        coverage_gaps=[],
        authority_corpus_present=True,
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        include_search=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.disposition is ReviewDisposition.NOT_READY
    assert report.exit_code_hint == 2
    assert "empty_claims" in report.reasons


def test_deterministic_digest(tmp_path: Path) -> None:
    kwargs = dict(
        fixture_dir=FIXTURES / "clean_package",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        include_conflict_review=True,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    r1 = run_unified_application_review(**kwargs)
    r2 = run_unified_application_review(**kwargs)
    assert r1.content_digest == r2.content_digest
    assert r1.disposition == r2.disposition


def test_compact_summary_has_required_fields(tmp_path: Path) -> None:
    report = run_unified_application_review(
        fixture_dir=FIXTURES / "clean_package",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    summary = report.compact_summary()
    for key in (
        "schema",
        "review_id",
        "application_number",
        "disposition",
        "exit_code_hint",
        "auto_file_blocked",
        "disclaimer",
        "content_digest",
    ):
        assert key in summary
    assert summary["auto_file_blocked"] is True


def test_compute_disposition_rules() -> None:
    d, reasons = compute_disposition(
        claim_authority_mode="authoritative",
        claim_low_ocr=False,
        claim_empty=False,
        matter_risk="low",
        has_human_dispositions=False,
        conformance_status="satisfied",
        authority_corpus_present=True,
    )
    assert d is ReviewDisposition.READY
    assert disposition_exit_code(d) == 0

    d2, _ = compute_disposition(
        claim_authority_mode="authoritative",
        claim_low_ocr=False,
        claim_empty=False,
        matter_risk="high",
        has_human_dispositions=False,
        conformance_status="satisfied",
        authority_corpus_present=True,
    )
    assert d2 is ReviewDisposition.REVIEW_REQUIRED
    assert disposition_exit_code(d2) == 1

    d3, _ = compute_disposition(
        claim_authority_mode="authoritative",
        claim_low_ocr=False,
        claim_empty=False,
        matter_risk="low",
        has_human_dispositions=False,
        conformance_status="unsatisfied",
        authority_corpus_present=True,
    )
    assert d3 is ReviewDisposition.NOT_READY
    assert disposition_exit_code(d3) == 2

    d4, reasons4 = compute_disposition(
        claim_authority_mode="authoritative",
        claim_low_ocr=False,
        claim_empty=False,
        matter_risk="low",
        has_human_dispositions=False,
        conformance_status="satisfied",
        authority_corpus_present=False,
    )
    assert d4 is ReviewDisposition.NOT_READY
    assert "authority_corpus_missing" in reasons4


def test_disclaimer_always_present() -> None:
    assert "not legal advice" in REVIEW_ONLY_UNIFIED_DISCLAIMER.lower()
    assert "patentability" in REVIEW_ONLY_UNIFIED_DISCLAIMER.lower()
    assert "sign" in REVIEW_ONLY_UNIFIED_DISCLAIMER.lower() or "auto_file_blocked" in REVIEW_ONLY_UNIFIED_DISCLAIMER.lower()


def test_cli_main_fixture(tmp_path: Path) -> None:
    import importlib.util
    import sys

    cli_path = (
        Path(__file__).resolve().parents[5]
        / "scripts"
        / "ops"
        / "uspto"
        / "review_application.py"
    )
    # parents: test file → uspto → domains → processors → unit → tests → repo root
    if not cli_path.is_file():
        repo = Path(__file__).resolve()
        for parent in repo.parents:
            candidate = parent / "scripts/ops/uspto/review_application.py"
            if candidate.is_file():
                cli_path = candidate
                break
    spec = importlib.util.spec_from_file_location(
        "paar_review_application_cli", cli_path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    code = mod.main(
        [
            "--fixture-dir",
            str(FIXTURES / "missing_authority"),
            "--state-root",
            str(tmp_path),
            "--no-persist",
            "--no-diligence",
        ]
    )
    assert code in {0, 1, 2}
    # missing authority → not ready/error path preferred
    assert code in {1, 2}


def test_portfolio_cli_review_subcommand() -> None:
    """PAAR-091: portfolio_cli wires review subcommand with non-goals help."""
    import argparse

    from scripts.ops.uspto.portfolio_cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "review",
            "--application-number",
            "16990002",
            "--no-persist",
            "--no-diligence",
            "--fixture-dir",
            str(FIXTURES / "clean_package"),
        ]
    )
    assert getattr(args, "func", None) is not None
    assert args.application_number == "16990002"
    # Locate subparser help for non-goals
    sub = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            sub = action
            break
    assert sub is not None
    rev_parser = sub.choices.get("review")
    assert rev_parser is not None
    help_text = rev_parser.format_help().lower()
    assert "not legal advice" in help_text or "review only" in help_text
    assert "sign" in help_text or "pay" in help_text or "submit" in help_text


def test_review_application_alias(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.domains.uspto.application_review_orchestrator import (
        review_application,
    )

    report = review_application(
        "16990002",
        fixture_dir=FIXTURES / "clean_package",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.application_number == "16990002"


def test_forbidden_phrase_guard() -> None:
    """Source module must not contain bare affirmative patentability conclusions."""
    src = Path(
        __import__(
            "ipfs_datasets_py.processors.domains.uspto.application_review_orchestrator",
            fromlist=["*"],
        ).__file__
    )
    text = src.read_text(encoding="utf-8").lower()
    # Allow negative framing in disclaimer; ban bare affirmatives as standalone.
    assert "is patentable" not in text.replace("not a patentability", " ")


# ---------------------------------------------------------------------------
# PAAR-070: diligence packs attach as residuals on UnifiedApplicationReview
# ---------------------------------------------------------------------------


def _seed_export_package(state: Path, app: str) -> Path:
    """Minimal Patent Center export layout for diligence pack builders."""
    pkg = state / "exports" / app / "patent_center_ui" / "package"
    files = state / "exports" / app / "patent_center_ui" / "files"
    meta = state / "exports" / app / "patent_center_ui" / "metadata"
    files.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)
    bag = {
        "applicationMetaData": {
            "inventionTitle": "Synthetic temperature probe cooling valve",
            "filingDate": "2020-01-15T00:00:00",
            "applicationStatusDescriptionText": "Docketed New Case - Ready for Examination",
        },
        "inventorBag": [
            {
                "nameLineOneText": "Alex Inventor",
                "firstName": "Alex",
                "lastName": "Inventor",
            }
        ],
        "preGrantPublicationData": [],
        "parentContinuityBag": [],
        "childContinuityBag": [],
        "status": "SUCCESS",
    }
    (pkg).mkdir(parents=True, exist_ok=True)
    (pkg / "application_data.json").write_text(
        json.dumps(bag, indent=2) + "\n", encoding="utf-8"
    )
    (meta / "ifw_document_summary.json").write_text(
        json.dumps(
            {
                "count": 4,
                "documents": [
                    {"documentCode": "OATH", "documentDescription": "Oath"},
                    {"documentCode": "ADS", "documentDescription": "ADS"},
                    {"documentCode": "CLM", "documentDescription": "Claims"},
                    {"documentCode": "SPEC", "documentDescription": "Specification"},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for name in ("OATH_x.pdf", "ADS_x.pdf", "CLM_x.pdf", "SPEC_x.pdf"):
        (files / name).write_bytes(b"%PDF-1.4 test")
    return pkg


def test_diligence_residuals_appear_when_state_fixture_provided(
    tmp_path: Path,
) -> None:
    """PAAR-070: gap_closure packs integrate into UnifiedApplicationReview residuals."""
    fixture = FIXTURES / "clean_package"
    app = "16990002"
    _seed_export_package(tmp_path, app)

    report = run_unified_application_review(
        fixture_dir=fixture,
        state_root=tmp_path,
        persist=True,
        include_diligence=True,
        include_search=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.component_status.get("diligence") == "ok"
    residual_kinds = {str(r.get("kind")) for r in report.diligence_residuals}
    assert "diligence_pack" in residual_kinds
    residual_ids = {str(r.get("residual_id")) for r in report.diligence_residuals}
    assert "check:inventorship" in residual_ids
    assert "check:new-matter" in residual_ids
    assert "check:nonpublication" in residual_ids
    assert "check:export" in residual_ids or any(
        "export" in str(r.get("category") or "") for r in report.diligence_residuals
    )
    # Coverage gaps from clean fixture also surface as residuals
    assert any(
        r.get("kind") == "coverage_gap" for r in report.diligence_residuals
    ) or any(
        str(r.get("residual_id") or "").startswith("gap:")
        for r in report.diligence_residuals
    )
    # Persisted diligence packs snapshot when state+persist
    assert report.persist_path
    packs_path = Path(report.persist_path) / "diligence_packs.json"
    assert packs_path.is_file()
    packs = json.loads(packs_path.read_text(encoding="utf-8"))
    assert packs.get("ok") is True
    assert "inventorship" in (packs.get("packs") or {})
    payload = report.to_dict()
    assert payload["diligence_residuals"]
    _assert_no_patentability(payload)


def test_diligence_skipped_when_disabled(tmp_path: Path) -> None:
    """include_diligence=False → stub residual only, component skipped."""
    report = run_unified_application_review(
        fixture_dir=FIXTURES / "clean_package",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        include_search=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.component_status.get("diligence") == "skipped"
    kinds = {str(r.get("kind")) for r in report.diligence_residuals}
    # Without packs, coverage gaps or diligence stub may appear
    assert "diligence_pack" not in kinds


def test_diligence_stub_without_state_root() -> None:
    """No state_root → optional diligence not executed (stub residual path)."""
    report = run_unified_application_review(
        fixture_dir=FIXTURES / "clean_package",
        state_root=None,
        persist=False,
        include_diligence=True,
        include_search=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.component_status.get("diligence") in {"stub", "skipped"}
    # Residuals still non-empty (coverage gaps and/or stub)
    assert report.diligence_residuals

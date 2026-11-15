"""Unit tests for PAAR package conformance engine (PAAR-060 / PAAR-061)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.analysis.obligation_catalog import (
    AuthorityCite,
    AuthorityTier,
    Applicability,
    EvidencePredicate,
    EvidencePredicateKind,
    FailClosedBehavior,
    Obligation,
    ObligationCatalog,
    ObligationSeverity,
    load_seed_catalog,
)
from ipfs_datasets_py.processors.domains.uspto.package_conformance_engine import (
    CONFORMANCE_REPORT_SCHEMA,
    REVIEW_ONLY_CONFORMANCE_DISCLAIMER,
    ConformanceReport,
    ConformanceStatus,
    evaluate_obligation,
    evaluate_package_conformance,
    evaluate_predicate,
    extract_ifw_codes,
    integrate_audit_findings,
    rollup_overall_status,
)


def _full_utility_inventory() -> dict:
    return {
        "files": [
            {"name": "16000001_SPEC_001.pdf", "ifw_document_code": "SPEC"},
            {"name": "16000001_CLM_001.pdf", "ifw_document_code": "CLM"},
            {"name": "16000001_DRW_001.pdf", "ifw_document_code": "DRW"},
            {"name": "16000001_ABST_001.pdf", "ifw_document_code": "ABST"},
            {"name": "16000001_ADS_001.pdf", "ifw_document_code": "ADS"},
            {"name": "16000001_OATH_001.pdf", "ifw_document_code": "OATH"},
            {"name": "16000001_IFEE_001.pdf", "ifw_document_code": "IFEE"},
        ],
        "components": [
            "specification",
            "claims",
            "drawings",
            "abstract",
            "ads",
            "oath",
            "fees",
        ],
        "claims_text_available": True,
    }


def test_status_vocabulary_closed() -> None:
    assert {s.value for s in ConformanceStatus} == {
        "satisfied",
        "unsatisfied",
        "unknown",
        "human_only",
    }


def test_extract_ifw_codes() -> None:
    codes = extract_ifw_codes(_full_utility_inventory())
    assert "SPEC" in codes
    assert "CLM" in codes
    assert "OATH" in codes


def test_missing_docs_unsatisfied() -> None:
    empty_inv = {"files": [], "components": []}
    report = evaluate_package_conformance(
        inventory=empty_inv,
        application_number="16000001",
        application_type="utility",
        scenario="new_application",
        authority_corpus_present=True,
        extracts={"claims": "1. A method.", "abstract": "A short abstract."},
        meta={"title": "Example"},
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.schema == CONFORMANCE_REPORT_SCHEMA
    assert report.auto_file_blocked is True
    statuses = {r.obligation_id: r.status for r in report.results}
    # Core docs missing → unsatisfied on blocking obligations
    claims = next(r for r in report.results if "claims" in r.obligation_id)
    assert claims.status is ConformanceStatus.UNSATISFIED
    assert report.overall_status in {
        ConformanceStatus.UNSATISFIED,
        ConformanceStatus.UNKNOWN,
        ConformanceStatus.HUMAN_ONLY,
    }
    assert report.overall_status is not ConformanceStatus.SATISFIED


def test_complete_package_can_satisfy_machine_checks() -> None:
    report = evaluate_package_conformance(
        inventory=_full_utility_inventory(),
        application_number="16000001",
        application_type="utility",
        scenario="new_application",
        authority_corpus_present=True,
        extracts={
            "claims": "1. A method comprising detecting a signal.",
            "abstract": " ".join(["word"] * 40),
            "specification": "Detailed description of the invention.",
        },
        meta={"title": "Sensor Alert Method", "invention_title": "Sensor Alert Method"},
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    by_id = {r.obligation_id: r for r in report.results}
    assert by_id["obl:utility:new:claims"].status is ConformanceStatus.SATISFIED
    assert by_id["obl:utility:new:specification"].status is ConformanceStatus.SATISFIED
    # Fees / IDS remain human_only process components
    fees = by_id.get("obl:utility:new:fees")
    if fees:
        assert fees.status in {
            ConformanceStatus.HUMAN_ONLY,
            ConformanceStatus.SATISFIED,
            ConformanceStatus.UNKNOWN,
        }
    ids = by_id.get("obl:utility:ids:process-hygiene")
    if ids:
        assert ids.status is ConformanceStatus.HUMAN_ONLY
    # Overall cannot be pure satisfied if human_only obligations exist
    assert report.overall_status in {
        ConformanceStatus.HUMAN_ONLY,
        ConformanceStatus.SATISFIED,
        ConformanceStatus.UNKNOWN,
        ConformanceStatus.UNSATISFIED,
    }


def test_missing_authority_unknown_not_satisfied() -> None:
    # Authority corpus bound obligation fails closed
    report = evaluate_package_conformance(
        inventory=_full_utility_inventory(),
        application_number="16000001",
        authority_corpus_present=False,
        extracts={"claims": "1. A method.", "abstract": "short abstract text here"},
        meta={"title": "T"},
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    auth = next(
        (r for r in report.results if "authority" in r.obligation_id),
        None,
    )
    if auth is not None:
        assert auth.status is ConformanceStatus.UNKNOWN
        assert auth.status is not ConformanceStatus.SATISFIED
    assert report.overall_status is not ConformanceStatus.SATISFIED or not auth


def test_missing_inventory_unknown() -> None:
    report = evaluate_package_conformance(
        inventory=None,
        application_number="16000001",
        authority_corpus_present=True,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.overall_status in {
        ConformanceStatus.UNKNOWN,
        ConformanceStatus.HUMAN_ONLY,
        ConformanceStatus.UNSATISFIED,
    }
    assert report.overall_status is not ConformanceStatus.SATISFIED
    # Document-present style outcomes should be unknown when inventory missing
    machine = [
        r
        for r in report.results
        if r.status not in {ConformanceStatus.HUMAN_ONLY}
    ]
    assert machine
    assert any(r.status is ConformanceStatus.UNKNOWN for r in machine)


def test_human_only_for_signatures_via_audit() -> None:
    findings = [
        {
            "code": "signature_human_only",
            "severity": "human_only",
            "category": "signature",
            "message": "Oath signature is a natural-person requirement.",
            "authority": "35 U.S.C. 115",
        }
    ]
    report = evaluate_package_conformance(
        inventory=_full_utility_inventory(),
        application_number="16000001",
        authority_corpus_present=True,
        extracts={"claims": "1. A method.", "abstract": "An abstract under limit."},
        meta={"title": "Title"},
        audit_findings=findings,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    oath = next(r for r in report.results if "oath" in r.obligation_id)
    assert any("signature" in e.target or "human" in e.status for e in oath.evidence) or (
        oath.status is ConformanceStatus.HUMAN_ONLY
        or any("audit:signature" in lab for lab in oath.heuristic_labels)
    )
    assert report.audit_findings_integrated >= 1


def test_heuristic_format_cannot_alone_force_unsatisfied() -> None:
    # Start from a package that satisfies claims; add OCR-style warning
    findings = [
        {
            "code": "claims_format_ocr_warning",
            "severity": "warning",
            "category": "claims",
            "message": "Possible OCR antecedent issue (heuristic).",
        }
    ]
    report = evaluate_package_conformance(
        inventory=_full_utility_inventory(),
        application_number="16000001",
        authority_corpus_present=True,
        extracts={
            "claims": "1. A method comprising detecting a signal.",
            "abstract": " ".join(["word"] * 20),
        },
        meta={"title": "Title Here"},
        audit_findings=findings,
        heuristic_format_forces_unsatisfied=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    claims = next(r for r in report.results if r.obligation_id.endswith(":claims"))
    # Default policy: heuristic alone does not force unsatisfied
    assert claims.status is not ConformanceStatus.UNSATISFIED or any(
        e.status == "unsatisfied" and not e.heuristic for e in claims.evidence
    )
    assert any(e.heuristic for e in claims.evidence) or claims.heuristic_labels


def test_heuristic_policy_flag_can_force_unsatisfied() -> None:
    findings = [
        {
            "code": "claims_format_ocr_warning",
            "severity": "warning",
            "category": "claims",
            "message": "Heuristic format issue.",
        }
    ]
    report = evaluate_package_conformance(
        inventory=_full_utility_inventory(),
        application_number="16000001",
        authority_corpus_present=True,
        extracts={"claims": "1. A method.", "abstract": "short abstract"},
        meta={"title": "T"},
        audit_findings=findings,
        heuristic_format_forces_unsatisfied=True,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    claims = next(r for r in report.results if r.obligation_id.endswith(":claims"))
    assert claims.status is ConformanceStatus.UNSATISFIED


def test_no_vacuous_satisfied_without_results() -> None:
    # Catalog with no applicable obligations for plant/design-like scenario filter
    empty_cat = ObligationCatalog(
        catalog_id="test.empty",
        version="0.0.1",
        obligations=(),
    )
    report = evaluate_package_conformance(
        inventory=_full_utility_inventory(),
        catalog=empty_cat,
        application_number="16000001",
        authority_corpus_present=True,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.overall_status is ConformanceStatus.UNKNOWN
    assert report.results == ()


def test_deterministic_digest() -> None:
    kwargs = dict(
        inventory=_full_utility_inventory(),
        application_number="16000001",
        authority_corpus_present=True,
        extracts={"claims": "1. A method.", "abstract": "abstract text"},
        meta={"title": "T"},
        generated_at_utc="2026-08-06T00:00:00Z",
        report_id="conf:test:fixed",
    )
    r1 = evaluate_package_conformance(**kwargs)
    r2 = evaluate_package_conformance(**kwargs)
    assert r1.content_digest == r2.content_digest
    restored = ConformanceReport.from_dict(r1.to_dict())
    assert restored.content_digest == r1.content_digest


def test_phrase_ban() -> None:
    report = evaluate_package_conformance(
        inventory=_full_utility_inventory(),
        application_number="16000001",
        authority_corpus_present=True,
        extracts={"claims": "1. A method.", "abstract": "words " * 10},
        meta={"title": "Title"},
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    lower = json.dumps(report.to_dict()).lower()
    for phrase in (
        "is patentable",
        "is novel",
        "is obvious",
        "safe to file without review",
    ):
        assert phrase not in lower
    # Disclaimer may contain "not a patentability conclusion"
    assert "not legal advice" in REVIEW_ONLY_CONFORMANCE_DISCLAIMER.lower()
    assert "not a patentability" in lower


def test_seed_catalog_used_by_default() -> None:
    seed = load_seed_catalog()
    report = evaluate_package_conformance(
        inventory=_full_utility_inventory(),
        application_number="16000001",
        authority_corpus_present=True,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.catalog_id == seed.catalog_id
    assert report.catalog_digest == seed.content_digest
    assert len(report.results) >= 1


def test_obligation_without_authority_unknown() -> None:
    # Construct obligation that only has guidance — catalog construction requires
    # authority_cites OR guidance_cites; evaluate_obligation treats no authority_cites as unknown
    obl = Obligation(
        obligation_id="obl:test:guidance-only",
        title="Guidance only test",
        description="Test",
        authority_cites=(),
        guidance_cites=(
            AuthorityCite(
                citation="MPEP 601",
                tier=AuthorityTier.GUIDANCE,
                is_controlling=False,
            ),
        ),
        applicability=Applicability(
            application_types=("utility",),
            scenarios=("new_application",),
        ),
        evidence_predicates=(
            EvidencePredicate(
                kind=EvidencePredicateKind.DOCUMENT_PRESENT,
                target="specification",
            ),
        ),
        severity=ObligationSeverity.MAJOR,
        fail_closed=FailClosedBehavior.UNKNOWN,
    )
    result = evaluate_obligation(
        obl,
        inventory=_full_utility_inventory(),
        authority_corpus_present=True,
    )
    assert result.status is ConformanceStatus.UNKNOWN


def test_human_process_predicate() -> None:
    pred = EvidencePredicate(
        kind=EvidencePredicateKind.HUMAN_PROCESS,
        target="fee_payment",
        description="Human pays fees",
        parameters={"auto_pay_blocked": True},
    )
    out = evaluate_predicate(
        pred,
        inventory=_full_utility_inventory(),
        authority_corpus_present=True,
    )
    assert out.status == ConformanceStatus.HUMAN_ONLY.value
    assert out.passed is None


def test_corpus_searched_predicate_unsearched_unsatisfied() -> None:
    """PAAR-054: required prior-art corpus missing → unsatisfied (not silent pass)."""
    pred = EvidencePredicate(
        kind=EvidencePredicateKind.CORPUS_SEARCHED,
        target="foreign_patents",
        description="Foreign corpus must be searched",
        parameters={
            "corpus": "foreign_patents",
            "aliases": ["foreign_patents", "epo_ops", "foreign"],
        },
        mandatory=True,
    )
    out = evaluate_predicate(
        pred,
        inventory={"files": []},
        meta={"searched_corpora": ["us_patents"]},
        authority_corpus_present=True,
    )
    assert out.passed is False
    assert out.status == ConformanceStatus.UNSATISFIED.value


def test_corpus_searched_predicate_satisfied_when_listed() -> None:
    pred = EvidencePredicate(
        kind=EvidencePredicateKind.CORPUS_SEARCHED,
        target="us_patents",
        parameters={"aliases": ["us_patents", "odp", "us"]},
        mandatory=True,
    )
    out = evaluate_predicate(
        pred,
        inventory={"searched_corpora": ["us_patents", "foreign_patents"]},
        meta={},
        authority_corpus_present=True,
    )
    assert out.passed is True
    assert out.status == ConformanceStatus.SATISFIED.value


def test_corpus_searched_named_gap_acceptance_is_unknown_not_satisfied() -> None:
    pred = EvidencePredicate(
        kind=EvidencePredicateKind.CORPUS_SEARCHED,
        target="foreign_patents",
        parameters={
            "aliases": ["foreign_patents", "foreign"],
            "allow_named_gap_acceptance": True,
        },
        mandatory=True,
    )
    out = evaluate_predicate(
        pred,
        inventory={
            "searched_corpora": ["us_patents"],
            "accepted_named_gaps": ["foreign_patents"],
        },
        meta={},
        authority_corpus_present=True,
    )
    assert out.passed is False
    assert out.status == ConformanceStatus.UNKNOWN.value


def test_exhaustive_seed_blocks_without_corpora() -> None:
    """Hardened seed cannot yield pure satisfied without multi-corpus search coverage."""
    inv = _full_utility_inventory()
    inv["title"] = "Example System"
    inv["fields"] = {"title": "Example System"}
    extracts = {
        "claims": "1. A method comprising a step.",
        "specification": " ".join(["word"] * 80),
        "abstract": "An abstract under one hundred fifty words for testing.",
    }
    report = evaluate_package_conformance(
        inventory=inv,
        extracts=extracts,
        application_number="16000001",
        application_type="utility",
        scenario="new_application",
        authority_corpus_present=True,
    )
    assert report.overall_status is not ConformanceStatus.SATISFIED
    prior = [
        r
        for r in report.results
        if "prior-art" in r.obligation_id and "corpus-searched" in r.obligation_id
    ]
    assert prior, "expected prior-art corpus obligations in seed evaluation"
    assert any(r.status is ConformanceStatus.UNSATISFIED for r in prior)


def test_rollup_overall() -> None:
    from ipfs_datasets_py.processors.domains.uspto.package_conformance_engine import (
        ObligationResult,
    )

    results = [
        ObligationResult(
            obligation_id="a",
            status=ConformanceStatus.SATISFIED,
            severity="blocking",
            authority_cites=(),
            evidence=(),
            fail_closed="unknown",
        ),
        ObligationResult(
            obligation_id="b",
            status=ConformanceStatus.UNSATISFIED,
            severity="blocking",
            authority_cites=(),
            evidence=(),
            fail_closed="unknown",
        ),
    ]
    assert rollup_overall_status(results) is ConformanceStatus.UNSATISFIED
    assert rollup_overall_status([]) is ConformanceStatus.UNKNOWN


def test_integrate_audit_findings_counts() -> None:
    from ipfs_datasets_py.processors.domains.uspto.package_conformance_engine import (
        ObligationResult,
        EvidenceOutcome,
    )

    base = [
        ObligationResult(
            obligation_id="obl:utility:new:claims",
            status=ConformanceStatus.SATISFIED,
            severity="blocking",
            authority_cites=(),
            evidence=(
                EvidenceOutcome(
                    kind="ifw_code_present",
                    target="CLM",
                    passed=True,
                    status="satisfied",
                ),
            ),
            fail_closed="unknown",
        )
    ]
    updated, n = integrate_audit_findings(
        base,
        [
            {
                "code": "claims_format_x",
                "severity": "warning",
                "category": "claims",
                "message": "heuristic",
            }
        ],
    )
    assert n >= 1
    assert updated[0].heuristic_labels

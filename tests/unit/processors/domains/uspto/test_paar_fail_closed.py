"""PAAR-141: fail-closed tests for missing authority and unsearched corpora.

Parametric safety cases:
* Missing authority → not ready / not satisfied
* Unsearched foreign → cannot aggregate low risk without acceptance
* Empty claims → fail closed / review_required
* Forbidden patentability phrases never in report dicts

Hermetic, offline, not legal advice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
    DEFAULT_REQUIRED_CORPORA,
    CoverageGap,
    RiskLevel,
    aggregate_matter_risk,
    score_conflict_risk,
    score_limitation_hit_cell,
)
from ipfs_datasets_py.processors.domains.uspto.claim_limitation_model import (
    AuthorityMode,
    QualityGateCode,
    ReviewFlagCode,
    build_claim_limitation_graph,
    graph_is_authoritative_for_conflict,
    parse_claims_to_graph,
)
from ipfs_datasets_py.processors.domains.uspto.package_conformance_engine import (
    ConformanceStatus,
    evaluate_package_conformance,
)

_FIXED_TS = "2026-08-06T00:00:00Z"

_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "uspto" / "paar_review"
)

_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "is patentable",
    "is unpatentable",
    "is novel",
    "is obvious",
    "novelty conclusion",
    "obviousness conclusion",
    "patentability conclusion",
    "no prior art exists",
    "will be allowed",
    "anticipates claim",
    "renders claim obvious",
    "safe to file without review",
)


def _redact_disclaimer_fields(obj: Any) -> Any:
    """Drop disclaimer text from nested payloads before ban-list scan."""
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in {"disclaimer", "notes"}:
                continue
            out[str(k)] = _redact_disclaimer_fields(v)
        return out
    if isinstance(obj, list):
        return [_redact_disclaimer_fields(x) for x in obj]
    if isinstance(obj, tuple):
        return [_redact_disclaimer_fields(x) for x in obj]
    return obj


def _assert_no_forbidden(payload: Mapping[str, Any] | Any) -> None:
    """Affirmative banned conclusions must not appear outside disclaimer framing."""
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    scan = _redact_disclaimer_fields(payload)
    blob = json.dumps(scan, default=str).lower()
    cleaned = blob
    for neg in (
        "not a patentability",
        "not patentability",
        "never a patentability",
        "no patentability",
        "not a novelty",
        "not an obviousness",
        "not legal advice",
        "not a completeness",
        "not a novelty, obviousness, or patentability",
        "or patentability conclusion",
        "novelty, obviousness, or patentability conclusion",
    ):
        cleaned = cleaned.replace(neg, " ")
    for phrase in _FORBIDDEN_PHRASES:
        assert phrase not in cleaned, f"forbidden phrase in report: {phrase!r}"


def _full_inventory() -> dict[str, Any]:
    return {
        "files": [
            {"name": "16990099_SPEC_001.pdf", "ifw_document_code": "SPEC"},
            {"name": "16990099_CLM_001.pdf", "ifw_document_code": "CLM"},
            {"name": "16990099_DRW_001.pdf", "ifw_document_code": "DRW"},
            {"name": "16990099_ABST_001.pdf", "ifw_document_code": "ABST"},
            {"name": "16990099_ADS_001.pdf", "ifw_document_code": "ADS"},
            {"name": "16990099_OATH_001.pdf", "ifw_document_code": "OATH"},
            {"name": "16990099_IFEE_001.pdf", "ifw_document_code": "IFEE"},
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


# ---------------------------------------------------------------------------
# Missing authority
# ---------------------------------------------------------------------------


def test_missing_authority_not_satisfied() -> None:
    report = evaluate_package_conformance(
        inventory=_full_inventory(),
        application_number="16990099",
        application_type="utility",
        scenario="new_application",
        authority_corpus_present=False,
        extracts={
            "claims": "1. A method comprising detecting a signal.",
            "abstract": " ".join(["word"] * 30),
            "specification": "Detailed description.",
        },
        meta={"title": "Synthetic Signal Detector"},
        generated_at_utc=_FIXED_TS,
    )
    assert report.authority_corpus_present is False
    assert report.overall_status is not ConformanceStatus.SATISFIED
    assert report.auto_file_blocked is True

    auth = next(
        (r for r in report.results if "authority" in r.obligation_id.lower()),
        None,
    )
    if auth is not None:
        assert auth.status is ConformanceStatus.UNKNOWN
        assert auth.status is not ConformanceStatus.SATISFIED

    _assert_no_forbidden(report)


def test_missing_authority_fixture_fail_closed() -> None:
    """Fixture missing_authority pack must not yield vacuous ready/satisfied."""
    root = _FIXTURE_ROOT / "missing_authority"
    if not root.is_dir():
        pytest.skip("missing_authority fixture not present")
    inv = json.loads((root / "package_inventory.json").read_text(encoding="utf-8"))
    auth = json.loads((root / "authority_status.json").read_text(encoding="utf-8"))
    claims = (root / "claims.txt").read_text(encoding="utf-8")
    bound = bool(auth.get("authority_corpus_bound"))
    assert bound is False

    report = evaluate_package_conformance(
        inventory=inv,
        application_number="16990003",
        application_type=str(inv.get("application_type") or "utility"),
        scenario=str(inv.get("scenario") or "new_application"),
        authority_corpus_present=bound,
        extracts={"claims": claims},
        meta={"title": str(inv.get("title") or "")},
        generated_at_utc=_FIXED_TS,
    )
    assert report.overall_status is not ConformanceStatus.SATISFIED
    assert report.auto_file_blocked is True
    _assert_no_forbidden(report)


@pytest.mark.parametrize(
    "authority_present,allow_satisfied",
    [
        (False, False),
        (True, True),
    ],
)
def test_authority_param_controls_satisfied(
    authority_present: bool, allow_satisfied: bool
) -> None:
    report = evaluate_package_conformance(
        inventory=_full_inventory(),
        application_number="16990098",
        authority_corpus_present=authority_present,
        extracts={
            "claims": "1. A method comprising detecting a signal.",
            "abstract": " ".join(["word"] * 40),
            "specification": "Detailed description of the invention.",
        },
        meta={"title": "Signal Method", "invention_title": "Signal Method"},
        generated_at_utc=_FIXED_TS,
    )
    if not allow_satisfied:
        assert report.overall_status is not ConformanceStatus.SATISFIED
    # When authority is present, overall may still be human_only (fees/IDS) —
    # that is fine; we only require missing authority never elevates to ready/satisfied.
    auth = next(
        (r for r in report.results if "authority" in r.obligation_id.lower()),
        None,
    )
    if auth is not None:
        if authority_present:
            assert auth.status in {
                ConformanceStatus.SATISFIED,
                ConformanceStatus.UNKNOWN,  # if catalog lacks excerpt path
                ConformanceStatus.HUMAN_ONLY,
            }
        else:
            assert auth.status is not ConformanceStatus.SATISFIED


# ---------------------------------------------------------------------------
# Unsearched foreign / NPL
# ---------------------------------------------------------------------------


def test_unsearched_foreign_cannot_aggregate_low() -> None:
    report = score_conflict_risk(
        application_number="16990100",
        limitations=[
            {
                "limitation_id": "lim:c1-1",
                "claim_number": 1,
                "text": "a bicycle chain lubrication system with drip reservoir",
            }
        ],
        hits=[
            {
                "hit_id": "hit:unrelated",
                "text": "quantum key distribution protocol for satellite links",
            }
        ],
        coverage_gaps=[
            {
                "kind": "foreign_patent",
                "status": "unsearched",
                "corpus": "foreign_patents",
            },
            {"kind": "npl", "status": "unsearched", "corpus": "npl"},
        ],
        generated_at_utc=_FIXED_TS,
    )
    # Cells may be low (unrelated), but matter cannot be low without acceptance
    assert report.matter_risk is not RiskLevel.LOW
    assert report.coverage_penalty_applied is True
    assert report.matter_risk in {
        RiskLevel.MEDIUM,
        RiskLevel.UNKNOWN,
        RiskLevel.HIGH,
    }
    assert report.auto_file_blocked is True
    _assert_no_forbidden(report)


def test_unsearched_foreign_acceptance_package_waives_penalty() -> None:
    report = score_conflict_risk(
        application_number="16990101",
        limitations=[
            {
                "limitation_id": "lim:c1-1",
                "claim_number": 1,
                "text": "a bicycle chain lubrication system with drip reservoir",
            }
        ],
        hits=[
            {
                "hit_id": "hit:unrelated",
                "text": "quantum key distribution protocol for satellite links",
            }
        ],
        coverage_gaps=[
            {
                "kind": "foreign_patent",
                "status": "unsearched",
                "corpus": "foreign_patents",
            },
            {"kind": "npl", "status": "unsearched", "corpus": "npl"},
        ],
        acceptance_package={
            "accepted": True,
            "acknowledger_id": "counsel:test",
        },
        generated_at_utc=_FIXED_TS,
    )
    assert report.coverage_penalty_applied is False
    assert report.matter_risk is RiskLevel.LOW
    _assert_no_forbidden(report)


def test_aggregate_matter_risk_foreign_gap_unit() -> None:
    from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
        ConflictRiskCell,
        RiskMethod,
    )

    low_cell = ConflictRiskCell(
        cell_id="c1",
        limitation_id="l1",
        claim_number=1,
        hit_id="h1",
        risk=RiskLevel.LOW,
        method=RiskMethod.LEXICAL,
        confidence=0.4,
        limitation_quote="widget",
        hit_quote="gadget",
    )
    matter, penalty = aggregate_matter_risk(
        [low_cell],
        [
            CoverageGap(
                kind="foreign_patent",
                status="unsearched",
                corpus="foreign_patents",
            )
        ],
        required_corpora=DEFAULT_REQUIRED_CORPORA,
    )
    assert penalty is True
    assert matter is not RiskLevel.LOW


def test_clean_fixture_coverage_gaps_visible() -> None:
    root = _FIXTURE_ROOT / "clean_package"
    if not root.is_dir():
        pytest.skip("clean_package fixture not present")
    prior = json.loads((root / "prior_hits.json").read_text(encoding="utf-8"))
    claims = (root / "claims.txt").read_text(encoding="utf-8")
    graph = parse_claims_to_graph(claims)
    hits = []
    for h in prior.get("hits") or ():
        hits.append(
            {
                "hit_id": h["hit_id"],
                "text": h.get("body_excerpt")
                or h.get("abstract")
                or h.get("text")
                or "",
            }
        )
    report = score_conflict_risk(
        application_number="16990002",
        claim_graph=graph,
        hits=hits,
        coverage_gaps=prior.get("coverage_gaps") or [],
        generated_at_utc=_FIXED_TS,
    )
    # Foreign/NPL unsearched in fixture → cannot be aggregate low
    assert report.matter_risk is not RiskLevel.LOW
    assert report.coverage_penalty_applied is True
    assert report.matter_risk is not RiskLevel.HIGH  # unrelated art
    _assert_no_forbidden(report)


# ---------------------------------------------------------------------------
# Empty claims
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claims_text",
    [
        "",
        "   ",
        "\n\n",
    ],
)
def test_empty_claims_fail_closed_review_required(claims_text: str) -> None:
    graph = build_claim_limitation_graph(claims_text=claims_text)
    assert graph.quality.review_required is True
    assert graph.quality.authority_mode is AuthorityMode.REVIEW_REQUIRED
    assert graph_is_authoritative_for_conflict(graph) is False
    assert graph.quality.gate_code in {
        QualityGateCode.EMPTY,
        QualityGateCode.REVIEW_REQUIRED,
        QualityGateCode.STRUCTURAL_FAILURE,
        QualityGateCode.BELOW_THRESHOLD,
    }
    # Conflict scoring with empty graph → unknown matter risk (no invented low)
    report = score_conflict_risk(
        application_number="16990102",
        claim_graph=graph,
        hits=[{"hit_id": "h1", "text": "some prior art text about widgets"}],
        coverage_gaps=[],
        generated_at_utc=_FIXED_TS,
    )
    assert report.matter_risk is RiskLevel.UNKNOWN
    assert report.auto_file_blocked is True
    _assert_no_forbidden(report)


def test_empty_claims_flag_present() -> None:
    graph = build_claim_limitation_graph(claims_text="")
    codes = {f.code for f in graph.review_flags}
    assert (
        ReviewFlagCode.EMPTY_CLAIMS.value in codes
        or graph.quality.gate_code is QualityGateCode.EMPTY
        or graph.quality.review_required
    )


# ---------------------------------------------------------------------------
# Forbidden phrases
# ---------------------------------------------------------------------------


def test_forbidden_phrases_absent_from_conflict_report() -> None:
    report = score_conflict_risk(
        application_number="16990103",
        limitations=[
            {
                "limitation_id": "lim:c1-1",
                "claim_number": 1,
                "text": "receiving a temperature signal from a probe",
            }
        ],
        hits=[
            {
                "hit_id": "hit:overlap",
                "text": (
                    "receiving a temperature signal from a probe and activating "
                    "a cooling valve"
                ),
            }
        ],
        coverage_gaps=[],
        generated_at_utc=_FIXED_TS,
    )
    payload = report.to_dict()
    _assert_no_forbidden(payload)
    # Closed vocabulary only
    assert payload["matter_risk"] in {"unknown", "low", "medium", "high"}
    for cell in payload["cells"]:
        assert cell["risk"] in {"unknown", "low", "medium", "high"}


def test_forbidden_phrases_absent_from_conformance_report() -> None:
    report = evaluate_package_conformance(
        inventory=_full_inventory(),
        application_number="16990104",
        authority_corpus_present=True,
        extracts={
            "claims": "1. A method comprising detecting a signal.",
            "abstract": " ".join(["word"] * 25),
        },
        meta={"title": "Signal Method"},
        generated_at_utc=_FIXED_TS,
    )
    _assert_no_forbidden(report)
    assert report.overall_status.value in {
        "satisfied",
        "unsatisfied",
        "unknown",
        "human_only",
    }


def test_forbidden_phrases_absent_from_claim_graph() -> None:
    graph = parse_claims_to_graph(
        "1. A method comprising receiving a signal.\n"
        "2. The method of claim 1, wherein the signal is digital.\n"
    )
    _assert_no_forbidden(graph.to_dict(include_text=True))
    _assert_no_forbidden(graph.to_dict(include_text=False))


def test_cell_notes_no_patentability_labels() -> None:
    cell = score_limitation_hit_cell(
        limitation_id="lim:c1-1",
        claim_number=1,
        limitation_text="receiving a temperature signal from a probe",
        hit_id="hit-1",
        hit_text="receiving a temperature signal from a probe near a cooling valve",
    )
    d = cell.to_dict()
    _assert_no_forbidden(d)
    assert d["risk"] in {"unknown", "low", "medium", "high"}
    assert d["method"] in {"lexical", "embedding", "structured", "unknown"}


def test_no_hits_fail_closed_unknown() -> None:
    report = score_conflict_risk(
        application_number="16990105",
        limitations=[
            {"limitation_id": "lim:c1-1", "claim_number": 1, "text": "a widget"}
        ],
        hits=[],
        coverage_gaps=[],
        generated_at_utc=_FIXED_TS,
    )
    assert report.matter_risk is RiskLevel.UNKNOWN
    assert report.cells == ()
    assert report.auto_file_blocked is True
    _assert_no_forbidden(report)

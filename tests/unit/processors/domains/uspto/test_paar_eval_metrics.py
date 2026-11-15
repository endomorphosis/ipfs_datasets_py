"""Unit tests for PAAR-112 offline conflict/conformance eval metrics.

Hermetic: planted fixture recall proxy, false-high rate, fail-closed rates.
Metrics JSON schema only — no private bodies stored.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.paar_eval_metrics import (
    METRIC_CONFLICT_RECALL_PROXY,
    METRIC_FAIL_CLOSED_AUTHORITY,
    METRIC_FAIL_CLOSED_EMPTY_CLAIMS,
    METRIC_FAIL_CLOSED_UNSEARCHED,
    METRIC_FALSE_HIGH_RATE,
    PAAR_EVAL_METRICS_SCHEMA,
    REVIEW_ONLY_EVAL_DISCLAIMER,
    EvalCaseObservation,
    compute_conflict_recall_proxy,
    compute_fail_closed_empty_claims,
    compute_fail_closed_missing_authority,
    compute_fail_closed_unsearched,
    compute_false_high_rate,
    compute_paar_eval_metrics,
    evaluate_fixture_bundle_dir,
    observation_from_unified_review,
    strip_private_bodies,
)

FIXTURES = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "uspto"
    / "paar_review"
)


def _planted_case(**overrides: object) -> EvalCaseObservation:
    base = dict(
        case_id="planted-1",
        variant="planted_conflict",
        planted_overlap=True,
        matter_risk="high",
        disposition="review_required",
        conformance_status="unknown",
        authority_corpus_present=True,
        claims_empty=False,
    )
    base.update(overrides)
    return EvalCaseObservation(**base)  # type: ignore[arg-type]


def _clean_case(**overrides: object) -> EvalCaseObservation:
    base = dict(
        case_id="clean-1",
        variant="clean_package",
        planted_overlap=False,
        matter_risk="low",
        disposition="review_required",
        conformance_status="unsatisfied",
        authority_corpus_present=True,
        claims_empty=False,
        unsearched_required_corpora=("foreign_patent", "npl"),
    )
    base.update(overrides)
    return EvalCaseObservation(**base)  # type: ignore[arg-type]


def test_conflict_recall_proxy_on_planted() -> None:
    cases = [
        _planted_case(matter_risk="high"),
        _planted_case(case_id="planted-2", matter_risk="medium"),
        _planted_case(case_id="planted-miss", matter_risk="low"),
    ]
    m = compute_conflict_recall_proxy(cases, min_risk="medium", threshold=0.5)
    assert m.metric_id == METRIC_CONFLICT_RECALL_PROXY
    assert m.numerator == 2
    assert m.denominator == 3
    assert m.rate == pytest.approx(2 / 3)
    assert m.status == "pass"


def test_false_high_rate_clean() -> None:
    cases = [
        _clean_case(matter_risk="low"),
        _clean_case(case_id="clean-2", matter_risk="medium"),
        _clean_case(case_id="clean-bad", matter_risk="high"),
    ]
    m = compute_false_high_rate(cases, threshold=0.5)
    assert m.metric_id == METRIC_FALSE_HIGH_RATE
    assert m.numerator == 1
    assert m.denominator == 3
    assert m.status == "pass"  # 1/3 <= 0.5
    m_strict = compute_false_high_rate(cases, threshold=0.0)
    assert m_strict.status == "fail"


def test_fail_closed_rates() -> None:
    cases = [
        EvalCaseObservation(
            case_id="auth-1",
            variant="missing_authority",
            planted_overlap=False,
            matter_risk="unknown",
            disposition="not_ready",
            conformance_status="unknown",
            authority_corpus_present=False,
            claims_empty=False,
        ),
        EvalCaseObservation(
            case_id="empty-1",
            variant="empty_claims",
            planted_overlap=False,
            matter_risk="unknown",
            disposition="not_ready",
            conformance_status="unknown",
            authority_corpus_present=True,
            claims_empty=True,
        ),
        _clean_case(disposition="review_required", matter_risk="unknown"),
    ]
    a = compute_fail_closed_missing_authority(cases)
    assert a.metric_id == METRIC_FAIL_CLOSED_AUTHORITY
    assert a.status == "pass"
    assert a.rate == 1.0

    e = compute_fail_closed_empty_claims(cases)
    assert e.metric_id == METRIC_FAIL_CLOSED_EMPTY_CLAIMS
    assert e.status == "pass"

    u = compute_fail_closed_unsearched(cases)
    assert u.metric_id == METRIC_FAIL_CLOSED_UNSEARCHED
    assert u.denominator >= 1
    assert u.status == "pass"


def test_compute_bundle_schema_and_no_private_bodies(tmp_path: Path) -> None:
    cases = [
        _planted_case(),
        _clean_case(),
        EvalCaseObservation(
            case_id="auth-miss",
            variant="missing_authority",
            planted_overlap=False,
            matter_risk="unknown",
            disposition="not_ready",
            conformance_status="unknown",
            authority_corpus_present=False,
            claims_empty=False,
        ),
    ]
    # Inject poison into metadata that must be stripped from final JSON
    poisoned = EvalCaseObservation(
        case_id="poison",
        variant="clean_package",
        planted_overlap=False,
        matter_risk="low",
        disposition="not_ready",
        conformance_status="unknown",
        authority_corpus_present=True,
        claims_empty=False,
        metadata={
            "note": "ok",
            "api_key": "should-not-appear-7f3a",
        },
    )
    report = compute_paar_eval_metrics(
        list(cases) + [poisoned],
        conflict_recall_threshold=1.0,
        false_high_threshold=0.0,
        fail_closed_threshold=1.0,
    )
    assert report.schema == PAAR_EVAL_METRICS_SCHEMA
    assert report.auto_file_blocked is True
    assert "not legal advice" in REVIEW_ONLY_EVAL_DISCLAIMER.lower()
    payload = report.to_dict()
    assert payload["schema"] == PAAR_EVAL_METRICS_SCHEMA
    assert payload["case_count"] == 4
    assert payload["content_digest"]
    assert len(payload["content_digest"]) == 64
    metric_ids = {m["metric_id"] for m in payload["metrics"]}
    assert METRIC_CONFLICT_RECALL_PROXY in metric_ids
    assert METRIC_FALSE_HIGH_RATE in metric_ids
    assert METRIC_FAIL_CLOSED_AUTHORITY in metric_ids

    blob = json.dumps(payload)
    assert "should-not-appear-7f3a" not in blob
    assert "api_key" not in blob
    assert "%PDF" not in blob
    assert "claims_text" not in blob

    out = report.write_json(tmp_path / "metrics.json")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["schema"] == PAAR_EVAL_METRICS_SCHEMA
    assert "should-not-appear" not in json.dumps(loaded)


def test_strip_private_bodies() -> None:
    dirty = {
        "ok": "value",
        "claims_text": "A method comprising secret claim body",
        "nested": {
            "body_excerpt": "long prior art excerpt",
            "matter_risk": "high",
            "api_key": "x",
        },
        "note": "password=hunter2-not-real",
    }
    clean = strip_private_bodies(dirty)
    assert "claims_text" not in clean
    assert "api_key" not in clean["nested"]
    assert clean["nested"]["matter_risk"] == "high"
    assert "hunter2" not in json.dumps(clean)


def test_observation_from_unified_review(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.domains.uspto.application_review_orchestrator import (
        run_unified_application_review,
    )

    if not (FIXTURES / "planted_conflict").is_dir():
        pytest.skip("paar_review fixtures missing")

    report = run_unified_application_review(
        fixture_dir=FIXTURES / "planted_conflict",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        include_search=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    obs = observation_from_unified_review(
        report, case_id="planted-live", variant="planted_conflict", planted_overlap=True
    )
    assert obs.case_id == "planted-live"
    assert obs.planted_overlap is True
    assert obs.matter_risk in {"unknown", "low", "medium", "high"}
    assert obs.disposition in {"ready", "review_required", "not_ready"}
    assert obs.auto_file_blocked is True


def test_evaluate_fixture_bundle_dir(tmp_path: Path) -> None:
    if not FIXTURES.is_dir():
        pytest.skip("paar_review fixtures missing")

    report = evaluate_fixture_bundle_dir(
        FIXTURES,
        run_reviews=True,
        state_root=tmp_path,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.schema == PAAR_EVAL_METRICS_SCHEMA
    assert report.case_count >= 2
    payload = report.to_dict()
    assert payload["auto_file_blocked"] is True
    assert "not legal advice" in payload["disclaimer"].lower()

    by_id = {m["metric_id"]: m for m in payload["metrics"]}
    # Planted fixture should contribute to recall metric when scorable
    recall = by_id[METRIC_CONFLICT_RECALL_PROXY]
    assert recall["denominator"] >= 1
    # Clean package should contribute to false-high denominator
    fh = by_id[METRIC_FALSE_HIGH_RATE]
    assert fh["denominator"] >= 1
    # No private bodies in metrics JSON
    blob = json.dumps(payload).lower()
    assert "password=" not in blob
    assert "%pdf" not in blob
    for phrase in ("is patentable", "is unpatentable", "is novel", "is obvious"):
        assert phrase not in blob


def test_from_dict_roundtrip() -> None:
    c = _planted_case()
    restored = EvalCaseObservation.from_dict(c.to_dict())
    assert restored.case_id == c.case_id
    assert restored.planted_overlap is True
    assert restored.matter_risk == "high"

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.state_laws_verifier import (
    StateLawsVerifier,
    _build_operational_diagnostics,
    _write_operational_report,
)


def test_build_operational_diagnostics_sorts_weak_states():
    metadata = {
        "coverage_summary": {
            "states_targeted": 3,
            "states_returned": 2,
            "states_with_nonzero_statutes": 1,
            "coverage_gap_states": ["BB", "CC"],
        },
        "fetch_analytics": {
            "attempted": 10,
            "success": 6,
            "success_ratio": 0.6,
            "fallback_count": 4,
            "providers": {"unified_scraper": 7, "requests_direct": 3},
        },
        "fetch_analytics_by_state": {
            "AA": {"attempted": 6, "success": 2, "fallback_count": 4, "last_error": "timeout"},
            "BB": {"attempted": 4, "success": 4, "fallback_count": 0},
        },
        "etl_readiness": {
            "ready_for_kg_etl": False,
            "total_statutes": 12,
            "full_text_ratio": 0.8,
            "jsonld_ratio": 0.74,
            "citation_ratio": 0.41,
            "states_with_zero_statutes": 1,
        },
        "quality_by_state": {
            "AA": {"total": 6, "scaffold_ratio": 0.4, "nav_like_ratio": 0.3, "fallback_section_ratio": 0.2, "numeric_section_name_ratio": 0.1},
            "BB": {"total": 4, "scaffold_ratio": 0.0, "nav_like_ratio": 0.1, "fallback_section_ratio": 0.0, "numeric_section_name_ratio": 0.9},
        },
    }

    diagnostics = _build_operational_diagnostics(metadata)

    assert diagnostics["coverage"]["coverage_gap_states"] == ["BB", "CC"]
    assert diagnostics["fetch"]["success_ratio"] == 0.6
    assert diagnostics["fetch"]["weak_states"][0]["state"] == "AA"
    assert diagnostics["quality"]["weak_states"][0]["state"] == "AA"
    assert diagnostics["etl_readiness"]["ready_for_kg_etl"] is False


def test_verify_operational_readiness_fails_on_thresholds():
    verifier = StateLawsVerifier()
    verifier._last_scrape_metadata = {
        "coverage_summary": {
            "coverage_gap_states": ["AA", "BB", "CC"],
            "states_targeted": 5,
            "states_returned": 2,
            "states_with_nonzero_statutes": 2,
        },
        "fetch_analytics": {
            "attempted": 10,
            "success": 6,
            "success_ratio": 0.6,
            "fallback_count": 5,
            "providers": {},
        },
        "fetch_analytics_by_state": {},
        "etl_readiness": {
            "ready_for_kg_etl": False,
            "total_statutes": 20,
            "full_text_ratio": 0.81,
            "jsonld_ratio": 0.72,
            "citation_ratio": 0.4,
            "states_with_zero_statutes": 2,
        },
        "quality_by_state": {},
    }

    verifier.verify_operational_readiness(
        require_kg_ready=True,
        min_fetch_success_ratio=0.8,
        max_fetch_fallback_ratio=0.2,
        max_coverage_gap_states=1,
    )

    last = verifier.results["tests"][-1]
    assert last["name"] == "Operational Readiness"
    assert last["status"] == "FAIL"
    reasons = set(last["details"]["reasons"])
    assert "kg-etl-not-ready" in reasons
    assert "fetch-success-ratio-below-threshold" in reasons
    assert "fetch-fallback-ratio-above-threshold" in reasons
    assert "too-many-coverage-gap-states" in reasons


def test_verify_operational_readiness_warns_without_threshold_failure():
    verifier = StateLawsVerifier()
    verifier._last_scrape_metadata = {
        "coverage_summary": {
            "coverage_gap_states": ["ZZ"],
            "states_targeted": 3,
            "states_returned": 2,
            "states_with_nonzero_statutes": 2,
        },
        "fetch_analytics": {
            "attempted": 5,
            "success": 5,
            "success_ratio": 1.0,
            "fallback_count": 0,
            "providers": {"unified_scraper": 5},
        },
        "fetch_analytics_by_state": {},
        "etl_readiness": {
            "ready_for_kg_etl": False,
            "total_statutes": 9,
            "full_text_ratio": 0.9,
            "jsonld_ratio": 0.8,
            "citation_ratio": 0.2,
            "states_with_zero_statutes": 0,
        },
        "quality_by_state": {},
    }

    verifier.verify_operational_readiness()

    last = verifier.results["tests"][-1]
    assert last["name"] == "Operational Readiness"
    assert last["status"] == "WARN"


def test_build_operational_diagnostics_respects_top_n_limit():
    metadata = {
        "coverage_summary": {"coverage_gap_states": []},
        "fetch_analytics": {"attempted": 9, "success": 6, "success_ratio": 0.667, "fallback_count": 2, "providers": {}},
        "fetch_analytics_by_state": {
            "AA": {"attempted": 3, "success": 1, "fallback_count": 2},
            "BB": {"attempted": 3, "success": 2, "fallback_count": 0},
            "CC": {"attempted": 3, "success": 3, "fallback_count": 0},
        },
        "etl_readiness": {"ready_for_kg_etl": True, "total_statutes": 3},
        "quality_by_state": {
            "AA": {"total": 3, "scaffold_ratio": 0.4, "nav_like_ratio": 0.2, "fallback_section_ratio": 0.1, "numeric_section_name_ratio": 0.1},
            "BB": {"total": 3, "scaffold_ratio": 0.1, "nav_like_ratio": 0.1, "fallback_section_ratio": 0.1, "numeric_section_name_ratio": 0.7},
            "CC": {"total": 3, "scaffold_ratio": 0.0, "nav_like_ratio": 0.0, "fallback_section_ratio": 0.0, "numeric_section_name_ratio": 0.9},
        },
    }

    diagnostics = _build_operational_diagnostics(metadata, top_n=2)

    assert len(diagnostics["fetch"]["weak_states"]) == 2
    assert diagnostics["fetch"]["weak_states"][0]["state"] == "AA"
    assert len(diagnostics["quality"]["weak_states"]) == 2
    assert diagnostics["quality"]["weak_states"][0]["state"] == "AA"


def test_write_operational_report_outputs_json_and_csv(tmp_path: Path):
    diagnostics = {
        "coverage": {"coverage_gap_states": ["AA"]},
        "fetch": {
            "attempted": 4,
            "success": 2,
            "success_ratio": 0.5,
            "fallback_count": 2,
            "providers": {"unified_scraper": 2},
            "weak_states": [
                {
                    "state": "AA",
                    "attempted": 4,
                    "success": 2,
                    "success_ratio": 0.5,
                    "fallback_count": 2,
                    "fallback_ratio": 0.5,
                    "last_error": "timeout",
                }
            ],
        },
        "etl_readiness": {"ready_for_kg_etl": False, "total_statutes": 10},
        "quality": {
            "weak_states": [
                {
                    "state": "AA",
                    "total": 5,
                    "scaffold_ratio": 0.4,
                    "nav_like_ratio": 0.3,
                    "fallback_section_ratio": 0.2,
                    "numeric_section_name_ratio": 0.1,
                }
            ]
        },
    }

    result = _write_operational_report(output_dir=tmp_path, diagnostics=diagnostics, report_format="both")

    assert result["format"] == "both"
    assert "json" in result["paths"]
    assert "fetch_csv" in result["paths"]
    assert "quality_csv" in result["paths"]

    json_path = Path(result["paths"]["json"])
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["diagnostics"]["fetch"]["success_ratio"] == 0.5

    fetch_csv = Path(result["paths"]["fetch_csv"])
    quality_csv = Path(result["paths"]["quality_csv"])
    assert fetch_csv.exists()
    assert quality_csv.exists()
    assert "AA" in fetch_csv.read_text(encoding="utf-8")
    assert "scaffold_ratio" in quality_csv.read_text(encoding="utf-8")


def test_build_operational_diagnostics_separates_no_attempt_states():
    metadata = {
        "coverage_summary": {"coverage_gap_states": []},
        "fetch_analytics": {"attempted": 10, "success": 4, "success_ratio": 0.4, "fallback_count": 1, "providers": {}},
        "fetch_analytics_by_state": {
            "IN": {"attempted": 0, "success": 0, "fallback_count": 0},
            "LA": {"attempted": 0, "success": 0, "fallback_count": 0},
            "OK": {"attempted": 10, "success": 4, "fallback_count": 1, "last_error": "timeout"},
        },
        "etl_readiness": {"ready_for_kg_etl": True, "total_statutes": 10},
        "quality_by_state": {},
    }

    diagnostics = _build_operational_diagnostics(metadata)

    assert diagnostics["fetch"]["no_attempt_states"] == ["IN", "LA"]
    assert len(diagnostics["fetch"]["weak_states"]) == 1
    assert diagnostics["fetch"]["weak_states"][0]["state"] == "OK"

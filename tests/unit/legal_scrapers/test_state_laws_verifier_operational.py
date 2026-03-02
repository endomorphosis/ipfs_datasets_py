from ipfs_datasets_py.processors.legal_scrapers.state_laws_verifier import (
    StateLawsVerifier,
    _build_operational_diagnostics,
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

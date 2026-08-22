"""Fail-closed LCR-084 full-scrape acceptance tests."""

from __future__ import annotations

import scripts.ops.legal_data.audit_state_laws_full_scrape_acceptance as audit


def test_current_synthetic_union_cannot_satisfy_live_official() -> None:
    try:
        audit.inspect_full_scrape_acceptance(
            require_live_official=True,
            require_jurisdictions=51,
            require_production_candidate=True,
        )
    except audit.ScrapeAcceptanceError as exc:
        message = str(exc)
        assert "two-row" in message or "LCR-023" in message or "fixture" in message
        return
    raise AssertionError("synthetic LCR-023 union must not pass live official")


def test_inspect_without_live_flags_reports_blocked() -> None:
    report = audit.inspect_full_scrape_acceptance(
        require_live_official=False,
        require_jurisdictions=51,
        require_production_candidate=False,
    )
    assert report["authorizing_hub_upload"] is False
    assert report["authorizing_for_publication"] is False
    assert report["status"] == "blocked"
    assert report["two_row_cohorts"]["F"]
    assert report["two_row_cohorts"]["I"]


def test_cli_require_live_official_exits_nonzero() -> None:
    assert (
        audit.main(
            [
                "--require-live-official",
                "--require-jurisdictions",
                "51",
                "--require-production-candidate",
                "--check",
            ]
        )
        == 1
    )

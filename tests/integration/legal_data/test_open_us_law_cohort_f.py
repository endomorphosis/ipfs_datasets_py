"""Integration certification for Open US Law scrape cohort F (MA, MI, MN, MS).

OUL-014: official adapters emit live ``fetch_official`` results, Mississippi
is reacquired from official hosts, and synthetic two-row success is rejected.
The declared cohort report is fail-closed live evidence. Fixture transports
never complete the cohort.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping
from urllib.parse import urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    REJECTION_SYNTHETIC_TWO_ROW,
    cohort_codes,
    evaluate_prior_receipt,
    is_cohort_evidence_payload,
    is_synthetic_two_row_report,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (
    evaluate_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    OfficialFetch,
    check_declared_cohort_report,
    collect_certification_rejections,
    default_cohort_report_path,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts import (
    MassachusettsScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan import (
    MichiganScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
    MinnesotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import (
    MississippiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
    StateScraperRegistry,
)


COHORT = "F"
TASK_ID = "OUL-014"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("MA", "MI", "MN", "MS")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_F.json")

OFFICIAL_HOST_SUFFIXES = {
    "MA": ("malegislature.gov",),
    "MI": ("legislature.mi.gov",),
    "MN": ("revisor.mn.gov",),
    "MS": ("legislature.ms.gov", "ls.state.ms.us"),
}

SCRAPER_TYPES = {
    "MA": MassachusettsScraper,
    "MI": MichiganScraper,
    "MN": MinnesotaScraper,
    "MS": MississippiScraper,
}

SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _host_allowed(url: str, state: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if any(marker in host for marker in SECONDARY_HOST_MARKERS):
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in OFFICIAL_HOST_SUFFIXES[state])


def _load_declared_report() -> Dict[str, Any]:
    path = _repo_root() / REPORT_RELPATH
    assert path.is_file(), f"declared cohort F report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "MA":
        return (
            "<html><body>"
            "<a href='/Laws/GeneralLaws/PartI/TitleI'>Part I Title I</a>"
            "<a href='/Laws/GeneralLaws/PartI/TitleII'>Part I Title II</a>"
            "<a href='/Laws/GeneralLaws/PartIV/TitleI'>Part IV Title I</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "MI":
        return (
            "<html><body>"
            "<a href='/Laws/MCL?objectName=mcl-chap1'>Chapter 1</a>"
            "<a href='/Laws/MCL?objectName=mcl-chap750'>Chapter 750</a>"
            "<a href='/Laws/MCL?objectName=mcl-chap830'>Chapter 830</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "MN":
        return (
            "<html><body>"
            "<a href='/statutes/cite/1'>Chapter 1</a>"
            "<a href='/statutes/cite/609'>Chapter 609</a>"
            "<a href='/statutes/cite/645'>Chapter 645</a>"
            "</body></html>"
        ).encode("utf-8")
    return (
        "<html><body>"
        "<a href='https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/001/'>Title 1</a>"
        "<a href='https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/097/'>Title 97</a>"
        "<a href='https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/099/'>Title 99</a>"
        "</body></html>"
    ).encode("utf-8")


def test_cohort_f_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_mississippi_synthetic_two_row_success_is_rejected() -> None:
    two_row = {
        "jurisdiction": "MS",
        "status": "success",
        "row_count": 2,
        "fetched": 2,
        "disposition": {"discovered": 2, "fetched": 2, "excluded": 0, "quarantined": 0, "failed_final": 0},
        "frontier": {
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": 2,
            "visited_index_units": 2,
        },
    }
    assert is_synthetic_two_row_report(two_row) is True
    admission = evaluate_prior_receipt(two_row)
    assert admission.accepted is False
    assert REJECTION_SYNTHETIC_TWO_ROW in admission.rejection_kinds

    scraper = MississippiScraper("MS", "Mississippi")
    rows = scraper.enumerate_official_catalog(b"")
    assert len(rows) > 2
    assert len(rows) == MississippiScraper.OFFICIAL_TITLE_COUNT
    for row in rows:
        assert _host_allowed(str(row["source_url"]), "MS")
        assert "justia.com" not in str(row["source_url"]).lower()
        assert "unicourt" not in str(row["source_url"]).lower()


@pytest.mark.parametrize("state", EXPECTED_STATES)
def test_fetch_official_is_live_and_exhaustive(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    scraper_cls = SCRAPER_TYPES[state]
    scraper = scraper_cls(state, state)
    monkeypatch.setattr(
        scraper,
        "_official_http_get",
        lambda url, timeout_seconds=30: _compact_official_html(state),
    )
    fetch = scraper.fetch_official(state)
    assert isinstance(fetch, OfficialFetch)
    assert fetch.fixture is False
    assert fetch.transport_kind == "live_https"
    assert fetch.jurisdiction_code == state
    assert len(fetch.rows) >= 3
    if state == "MS":
        assert len(fetch.rows) > 2
        assert len(fetch.rows) == MississippiScraper.OFFICIAL_TITLE_COUNT
    assert fetch.frontier.get("closed") is True
    assert int(fetch.frontier.get("expected_index_units") or 0) == len(fetch.rows)
    assert fetch.source_domain
    assert _host_allowed(f"https://{fetch.source_domain}{fetch.source_path}", state)
    for row in fetch.rows:
        assert isinstance(row, Mapping)
        assert row.get("canonical_key")
        assert _host_allowed(str(row.get("source_url") or ""), state)
        assert str(row.get("source_link_disposition") or "") in {
            "official",
            "repaired_official_leginfo",
        }
        lowered = str(row.get("source_url") or "").lower()
        assert "justia.com" not in lowered
        assert "unicourt" not in lowered


def test_declared_cohort_f_report_is_live_certified() -> None:
    payload = _load_declared_report()
    assert is_cohort_evidence_payload(payload) is True
    assert payload["cohort"] == COHORT
    assert payload["task_id"] == TASK_ID
    assert payload["goal_id"] == GOAL_ID
    assert payload["program_id"] == PROGRAM_ID
    assert payload["jurisdictions"] == list(EXPECTED_STATES)
    assert payload["cohort_complete"] is True
    assert payload["fixture_execution"] is False
    assert payload["fixture_proves_cohort_completion"] is False
    assert payload["authorizing_for_publication"] is False
    assert payload["status"] in {"success", "passed"}
    assert payload["certification"]["raw_bytes_checked"] is True

    receipts = payload["jurisdiction_receipts"]
    for state in EXPECTED_STATES:
        receipt = receipts[state]
        assert receipt["jurisdiction"] == state
        assert receipt["transport"]["fixture"] is False
        assert str(receipt["transport"].get("kind") or "") not in {"fixture", "synthetic", "mock"}
        assert int(receipt["row_count"]) >= 3
        assert int(receipt["disposition"]["fetched"]) >= 3
        assert is_synthetic_two_row_report(receipt) is False
        assert receipt.get("admitted_body")
        kinds = collect_certification_rejections(receipt)
        assert kinds == [], f"{state} certification rejections: {kinds}"
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-014-{state.lower()}")
        assert verdict.complete is True, (
            f"{state} completeness failed: {[item.detail for item in verdict.findings]}"
        )
        units = json.loads(receipt["admitted_body"]).get("units") or []
        assert len(units) >= 3
        for item in units:
            assert _host_allowed(str(item.get("source_url") or ""), state)
            lowered = str(item.get("source_url") or "").lower()
            assert "justia.com" not in lowered
            assert "unicourt" not in lowered
        if state == "MS":
            assert int(receipt["row_count"]) > 2
            assert len(units) == MississippiScraper.OFFICIAL_TITLE_COUNT

    serialized = json.dumps(payload)
    assert "hf_" not in serialized
    assert "Bearer " not in serialized
    assert "/home/" not in serialized

    checked = check_declared_cohort_report(
        _repo_root() / REPORT_RELPATH,
        cohort=COHORT,
        require_live=True,
        repo_root=_repo_root(),
    )
    assert checked["status"] == "passed"
    assert checked["cohort_complete"] is True
    assert checked["fixture_execution"] is False
    assert checked["jurisdictions"] == list(EXPECTED_STATES)


def test_default_cohort_f_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_F.json"

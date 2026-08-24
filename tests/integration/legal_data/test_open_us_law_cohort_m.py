"""Integration certification for Open US Law scrape cohort M (WI, WY, DC).

OUL-021: official adapters emit live ``fetch_official`` results, Wyoming
linkless seed material is reacquired or quarantined, and DC is counted
exactly once in the required 51. The declared cohort report is fail-closed
live evidence. Fixture transports never complete the cohort.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping
from urllib.parse import urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    cohort_codes,
    evaluate_prior_receipt,
    is_cohort_evidence_payload,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    CANONICAL_JURISDICTIONS,
    evaluate_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    OfficialFetch,
    check_declared_cohort_report,
    collect_certification_rejections,
    default_cohort_report_path,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.district_of_columbia import (
    DistrictOfColumbiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
    StateScraperRegistry,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin import (
    WisconsinScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming import (
    WyomingScraper,
)


COHORT = "M"
TASK_ID = "OUL-021"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("WI", "WY", "DC")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_M.json")

OFFICIAL_HOST_SUFFIXES = {
    "WI": ("docs.legis.wisconsin.gov", "legis.wisconsin.gov"),
    "WY": ("wyoleg.gov",),
    "DC": ("code.dccouncil.gov", "code.dccouncil.us", "dccouncil.gov"),
}

SCRAPER_TYPES = {
    "WI": WisconsinScraper,
    "WY": WyomingScraper,
    "DC": DistrictOfColumbiaScraper,
}

SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)

WY_LINKLESS_HTML = """
<html>
  <body>
    <a href="/statutes/compress/title01.pdf">Title 1 General Provisions</a>
    <a href="/statutes/compress/title02.pdf">Title 2 Aeronautics</a>
    <span>Title 6 Crimes and Offenses</span>
    <a href="javascript:void(0)">Wyoming Statutes Title 8</a>
    <td>Wyoming statutes phantom chapter without a recoverable official identifier</td>
  </body>
</html>
"""


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
    assert path.is_file(), f"declared cohort M report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "WI":
        return (
            "<html><body>"
            "<a href='/document/statutes/1'>Chapter 1</a>"
            "<a href='/document/statutes/939'>Chapter 939</a>"
            "<a href='/document/statutes/995'>Chapter 995</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "WY":
        return WY_LINKLESS_HTML.encode("utf-8")
    return (
        "<html><body>"
        "<a href='/us/dc/council/code/titles/1'>Title 1</a>"
        "<a href='/us/dc/council/code/titles/22'>Title 22</a>"
        "<a href='/us/dc/council/code/titles/51'>Title 51</a>"
        "</body></html>"
    ).encode("utf-8")


def test_cohort_m_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_wyoming_linkless_seed_material_is_reacquired_or_quarantined() -> None:
    scraper = WyomingScraper("WY", "Wyoming")
    classified = scraper.classify_linkless_seed_rows(
        WY_LINKLESS_HTML,
        page_url="https://www.wyoleg.gov/stateStatutes/StatutesDownload",
    )
    repaired = {item["title_number"]: item for item in classified["repaired"]}
    assert repaired["1"]["source_url"] == "https://www.wyoleg.gov/statutes/compress/title01.pdf"
    assert repaired["2"]["source_url"] == "https://www.wyoleg.gov/statutes/compress/title02.pdf"
    assert repaired["6"]["repair_source"] == "repaired_from_linkless_row"
    assert repaired["6"]["source_url"] == "https://www.wyoleg.gov/statutes/compress/title06.pdf"
    assert repaired["8"]["repair_source"] == "repaired_from_linkless_row"
    assert repaired["8"]["source_url"] == "https://www.wyoleg.gov/statutes/compress/title08.pdf"
    assert all(_host_allowed(item["source_url"], "WY") for item in classified["repaired"])

    quarantines = classified["quarantines"]
    assert quarantines
    assert all(item["reason"] == WyomingScraper.LINKLESS_QUARANTINE_REASON for item in quarantines)
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any("phantom chapter" in item["label"].lower() for item in quarantines)

    seed_rows = [
        {"label": "1-1-101 Short title", "source_url": ""},
        {"label": "Wyoming bucket seed without a title or official host", "href": ""},
    ]
    from_seeds = scraper.classify_linkless_seed_rows(seed_rows)
    assert any(item["title_number"] == "1" for item in from_seeds["repaired"])
    assert any(item["reason"] == WyomingScraper.LINKLESS_QUARANTINE_REASON for item in from_seeds["quarantines"])


def test_dc_is_counted_exactly_once_in_required_51() -> None:
    assert CANONICAL_JURISDICTION_ORDER.count("DC") == 1
    assert list(CANONICAL_JURISDICTION_ORDER)[-1] == "DC"
    assert len(CANONICAL_JURISDICTION_ORDER) == 51
    assert len(CANONICAL_JURISDICTIONS) == 51
    assert cohort_codes(COHORT).count("DC") == 1
    assert "PR" not in CANONICAL_JURISDICTIONS

    scraper = DistrictOfColumbiaScraper("DC", "District of Columbia")
    rows = scraper.official_title_catalog()
    keys = [str(item["canonical_key"]) for item in rows]
    numbers = [str(item["title_number"]) for item in rows]
    assert len(keys) == len(set(keys))
    assert len(numbers) == len(set(numbers))
    assert all(str(item["canonical_key"]).startswith("dc:") for item in rows)


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
    if state == "WI":
        assert len(fetch.rows) == len(WisconsinScraper.OFFICIAL_CHAPTERS)
    if state == "WY":
        assert len(fetch.rows) == len(WyomingScraper.OFFICIAL_TITLE_NUMBERS)
        assert getattr(scraper, "last_official_quarantines", None)
    if state == "DC":
        assert fetch.jurisdiction_code == "DC"
        keys = [str(row["canonical_key"]) for row in fetch.rows]
        assert len(keys) == len(set(keys))
        assert fetch.frontier.get("dc_counted_once") is True
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
            "repaired_from_linkless_row",
        }
        lowered = str(row.get("source_url") or "").lower()
        assert "justia.com" not in lowered
        assert "unicourt" not in lowered


def test_declared_cohort_m_report_is_live_certified() -> None:
    payload = _load_declared_report()
    assert is_cohort_evidence_payload(payload) is True
    assert payload["cohort"] == COHORT
    assert payload["task_id"] == TASK_ID
    assert payload["goal_id"] == GOAL_ID
    assert payload["program_id"] == PROGRAM_ID
    assert payload["jurisdictions"] == list(EXPECTED_STATES)
    assert payload["jurisdictions"].count("DC") == 1
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
        assert receipt.get("admitted_body")
        kinds = collect_certification_rejections(receipt)
        assert kinds == [], f"{state} certification rejections: {kinds}"
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-021-{state.lower()}")
        assert verdict.complete is True, (
            f"{state} completeness failed: {[item.detail for item in verdict.findings]}"
        )
        admission = evaluate_prior_receipt(receipt)
        assert admission.accepted is True
        units = json.loads(receipt["admitted_body"]).get("units") or []
        assert len(units) >= 3
        for item in units:
            assert _host_allowed(str(item.get("source_url") or ""), state)
            lowered = str(item.get("source_url") or "").lower()
            assert "justia.com" not in lowered
            assert "unicourt" not in lowered
        if state == "WI":
            assert len(units) >= len(WisconsinScraper.OFFICIAL_CHAPTERS)
        if state == "WY":
            assert len(units) >= len(WyomingScraper.OFFICIAL_TITLE_NUMBERS)
            catalog = json.loads(receipt["admitted_body"])
            assert "quarantines" in catalog
        if state == "DC":
            keys = [str(item.get("canonical_key") or "") for item in units]
            assert len(keys) == len(set(keys))
            assert len(units) >= len(DistrictOfColumbiaScraper.OFFICIAL_TITLES)

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
    assert checked["dc_counted_once"] is True


def test_default_cohort_m_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_M.json"

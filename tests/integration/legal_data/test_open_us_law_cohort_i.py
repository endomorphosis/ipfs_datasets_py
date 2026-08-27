"""Integration certification for Open US Law scrape cohort I (NC, ND, OH, OK).

OUL-017: official adapters emit live ``fetch_official`` results, and the
absent contaminated North Carolina bucket object is replaced from official
clean text. The declared cohort report is fail-closed live evidence.
Fixture transports never complete the cohort.
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
    evaluate_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    OfficialFetch,
    check_declared_cohort_report,
    collect_certification_rejections,
    default_cohort_report_path,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
    NorthCarolinaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_dakota import (
    NorthDakotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio import OhioScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import (
    OklahomaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
    StateScraperRegistry,
)


COHORT = "I"
TASK_ID = "OUL-017"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("NC", "ND", "OH", "OK")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_I.json")

OFFICIAL_HOST_SUFFIXES = {
    "NC": ("ncleg.gov",),
    "ND": ("legis.nd.gov", "ndlegis.gov"),
    "OH": ("codes.ohio.gov",),
    "OK": ("oscn.net", "oklegislature.gov"),
}

SCRAPER_TYPES = {
    "NC": NorthCarolinaScraper,
    "ND": NorthDakotaScraper,
    "OH": OhioScraper,
    "OK": OklahomaScraper,
}

SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)

NAVIGATION_FOOTER_MARKERS = (
    "skip to main",
    "skip to navigation",
    "privacy policy",
    "footer navigation",
    "cookie policy",
)

NC_CONTAMINATED_BUCKET_HTML = """
<html>
  <nav>Skip to main content | Site Map | Privacy Policy</nav>
  <body>
    <a href="/Laws/GeneralStatuteSections/Chapter1">Chapter 1 Civil Procedure</a>
    <a href="/Laws/GeneralStatuteSections/Chapter14">Chapter 14 Criminal Law</a>
    <a href="https://law.justia.com/codes/north-carolina/chapter-14/">Chapter 14 Justia mirror</a>
    <td>North Carolina bucket phantom chapter without a recoverable official identifier</td>
    <div class="footer">Copyright © North Carolina General Assembly Footer navigation</div>
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
    assert path.is_file(), f"declared cohort I report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "NC":
        return (
            "<html><body>"
            "<a href='/Laws/GeneralStatuteSections/Chapter1'>Chapter 1 Civil Procedure</a>"
            "<a href='/Laws/GeneralStatuteSections/Chapter14'>Chapter 14 Criminal Law</a>"
            "<a href='/Laws/GeneralStatuteSections/Chapter105'>Chapter 105 Taxation</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "ND":
        return (
            "<html><body>"
            "<a href='/cencode/t01.html'>Title 1 General Provisions</a>"
            "<a href='/cencode/t12-1.html'>Title 12.1 Criminal Code</a>"
            "<a href='/cencode/t39.html'>Title 39 Motor Vehicles</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "OH":
        return (
            "<html><body>"
            "<a href='/ohio-revised-code/title-1'>Title 1 State Government</a>"
            "<a href='/ohio-revised-code/title-29'>Title 29 Crimes-Procedure</a>"
            "<a href='/ohio-revised-code/title-45'>Title 45 Motor Vehicles</a>"
            "</body></html>"
        ).encode("utf-8")
    anchors = "".join(
        (
            "<a href='/OK_Statutes/CompleteTitles/"
            f"os{'37a' if number == '37A' else number}.pdf'>"
            f"Title {number} {name}</a>"
        )
        for number, name in OklahomaScraper.OFFICIAL_TITLES
    )
    return f"<html><body>{anchors}</body></html>".encode("utf-8")


def test_cohort_i_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_north_carolina_contaminated_bucket_is_replaced_from_official_clean_text() -> None:
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    classified = scraper.replace_contaminated_bucket_object(
        NC_CONTAMINATED_BUCKET_HTML,
        page_url="https://www.ncleg.gov/Laws/GeneralStatutes",
    )
    replaced = {item["chapter_number"]: item for item in classified["replaced"]}
    assert replaced["1"]["source_url"] == (
        "https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter1"
    )
    assert replaced["14"]["source_url"] == (
        "https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter14"
    )
    assert all(_host_allowed(item["source_url"], "NC") for item in classified["replaced"])
    for item in classified["replaced"]:
        lowered = str(item["text"]).lower()
        assert not any(marker in lowered for marker in NAVIGATION_FOOTER_MARKERS)
        assert item["source_link_disposition"] in {"official", "official_replacement"}
        assert item["contaminated_replaced"] is True

    quarantines = classified["quarantines"]
    assert quarantines
    assert all(
        item["reason"] == NorthCarolinaScraper.CONTAMINATED_BUCKET_REPLACEMENT_REASON
        for item in quarantines
    )
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any("phantom" in item["label"].lower() for item in quarantines)

    from_seeds = scraper.replace_contaminated_bucket_object(
        list(NorthCarolinaScraper.DEFAULT_CONTAMINATED_BUCKET_SEEDS)
    )
    replaced_seeds = {item["chapter_number"]: item for item in from_seeds["replaced"]}
    assert replaced_seeds["1"]["source_url"].startswith(
        "https://www.ncleg.gov/Laws/GeneralStatuteSections/"
    )
    assert replaced_seeds["14"]["repair_source"] == "official_replacement"
    assert any(
        item["reason"] == NorthCarolinaScraper.CONTAMINATED_BUCKET_REPLACEMENT_REASON
        for item in from_seeds["quarantines"]
    )
    assert any(
        "without a recoverable" in item["label"] or item["unit_id"].startswith("nc:bucket")
        for item in from_seeds["quarantines"]
    )


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
    assert fetch.frontier.get("closed") is True
    assert int(fetch.frontier.get("expected_index_units") or 0) == len(fetch.rows)
    assert fetch.source_domain
    assert _host_allowed(f"https://{fetch.source_domain}{fetch.source_path}", state)
    if state == "NC":
        assert len(fetch.rows) == NorthCarolinaScraper.OFFICIAL_CHAPTER_COUNT
        assert fetch.frontier.get("nc_contaminated_bucket_replaced") is True
        assert getattr(scraper, "last_official_quarantines", None)
        assert any(
            item["reason"] == NorthCarolinaScraper.CONTAMINATED_BUCKET_REPLACEMENT_REASON
            for item in scraper.last_official_quarantines
        )
    if state == "ND":
        assert len(fetch.rows) == NorthDakotaScraper.OFFICIAL_TITLE_COUNT
    if state == "OH":
        assert len(fetch.rows) == OhioScraper.OFFICIAL_TITLE_COUNT
    if state == "OK":
        assert len(fetch.rows) == OklahomaScraper.OFFICIAL_TITLE_COUNT
    for row in fetch.rows:
        assert isinstance(row, Mapping)
        assert row.get("canonical_key")
        assert _host_allowed(str(row.get("source_url") or ""), state)
        assert str(row.get("source_link_disposition") or "") in {
            "official",
            "repaired_official_ncleg",
            "repaired_official_ndlegis",
            "repaired_official_ohcodes",
            "repaired_official_oscn",
            "official_replacement",
        }
        lowered = str(row.get("source_url") or "").lower()
        assert "justia.com" not in lowered
        assert "unicourt" not in lowered
        assert "findlaw.com" not in lowered
        if state == "NC":
            text = str(row.get("text") or "").lower()
            assert not any(marker in text for marker in NAVIGATION_FOOTER_MARKERS)
            assert row.get("contaminated_replaced") is True


def test_official_catalogs_are_exhaustive() -> None:
    carolina = NorthCarolinaScraper("NC", "North Carolina")
    nc_rows = carolina.enumerate_official_catalog(b"", page_url=carolina.OFFICIAL_ENTRY_URL)
    assert len(nc_rows) == NorthCarolinaScraper.OFFICIAL_CHAPTER_COUNT
    assert {row["chapter_number"] for row in nc_rows} == {
        number for number, _name in NorthCarolinaScraper.OFFICIAL_CHAPTERS
    }
    for row in nc_rows:
        assert _host_allowed(str(row["source_url"]), "NC")
        assert row["source_link_disposition"] in {
            "official",
            "repaired_official_ncleg",
            "official_replacement",
        }

    dakota = NorthDakotaScraper("ND", "North Dakota")
    nd_rows = dakota.enumerate_official_catalog(b"", page_url=dakota.OFFICIAL_ENTRY_URL)
    assert len(nd_rows) == NorthDakotaScraper.OFFICIAL_TITLE_COUNT
    for row in nd_rows:
        assert _host_allowed(str(row["source_url"]), "ND")
        assert row["source_link_disposition"] in {"official", "repaired_official_ndlegis"}

    ohio = OhioScraper("OH", "Ohio")
    oh_rows = ohio.enumerate_official_catalog(b"", page_url=ohio.OFFICIAL_ENTRY_URL)
    assert len(oh_rows) == OhioScraper.OFFICIAL_TITLE_COUNT
    for row in oh_rows:
        assert _host_allowed(str(row["source_url"]), "OH")
        assert row["source_link_disposition"] in {"official", "repaired_official_ohcodes"}

    oklahoma = OklahomaScraper("OK", "Oklahoma")
    ok_rows = oklahoma.enumerate_official_catalog(b"", page_url=oklahoma.OFFICIAL_ENTRY_URL)
    assert len(ok_rows) == OklahomaScraper.OFFICIAL_TITLE_COUNT
    for row in ok_rows:
        assert _host_allowed(str(row["source_url"]), "OK")
        assert row["source_link_disposition"] in {"official", "repaired_official_oscn"}


def test_declared_cohort_i_report_is_live_certified() -> None:
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
        assert receipt.get("admitted_body")
        kinds = collect_certification_rejections(receipt)
        assert kinds == [], f"{state} certification rejections: {kinds}"
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-017-{state.lower()}")
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
            assert "findlaw.com" not in lowered
        if state == "NC":
            catalog = json.loads(receipt["admitted_body"])
            assert catalog.get("contaminated_bucket_replaced") is True
            assert catalog.get("replacement_source") == "official_clean_text"
            quarantines = catalog.get("quarantines") or []
            assert quarantines
            assert all(
                item["reason"] == NorthCarolinaScraper.CONTAMINATED_BUCKET_REPLACEMENT_REASON
                for item in quarantines
            )
            assert len(units) == NorthCarolinaScraper.OFFICIAL_CHAPTER_COUNT
            for item in units:
                text = str(item.get("text") or "").lower()
                assert not any(marker in text for marker in NAVIGATION_FOOTER_MARKERS)
        if state == "ND":
            assert len(units) == NorthDakotaScraper.OFFICIAL_TITLE_COUNT
            assert "legis.nd.gov/cencode/" in json.dumps(units)
        if state == "OH":
            assert len(units) == OhioScraper.OFFICIAL_TITLE_COUNT
            assert "codes.ohio.gov/ohio-revised-code/title-" in json.dumps(units)
        if state == "OK":
            assert len(units) == OklahomaScraper.OFFICIAL_TITLE_COUNT
            assert "oscn.net/applications/oscn/Index.asp" in json.dumps(units)

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


def test_default_cohort_i_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_I.json"


def test_north_carolina_receipt_records_replaced_contaminated_bucket() -> None:
    payload = _load_declared_report()
    receipt = payload["jurisdiction_receipts"]["NC"]
    catalog = json.loads(receipt["admitted_body"])
    assert catalog.get("contaminated_bucket_replaced") is True
    assert catalog.get("replacement_source") == "official_clean_text"
    assert "nc:chapter-" in receipt["admitted_body"]
    assert "ncleg.gov/Laws/GeneralStatuteSections/" in receipt["admitted_body"]
    assert "justia.com" not in receipt["admitted_body"].lower()
    assert "findlaw.com" not in receipt["admitted_body"].lower()
    frontier = receipt.get("frontier") or {}
    assert frontier.get("nc_contaminated_bucket_replaced") is True
    quarantines = list(
        frontier.get("nc_contaminated_bucket_quarantines")
        or catalog.get("quarantines")
        or receipt.get("quarantines")
        or []
    )
    assert quarantines
    assert all(
        item["reason"] == NorthCarolinaScraper.CONTAMINATED_BUCKET_REPLACEMENT_REASON
        for item in quarantines
    )
    assert all(len(str(item["evidence_sha256"])) == 64 for item in quarantines)

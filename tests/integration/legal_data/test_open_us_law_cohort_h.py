"""Integration certification for Open US Law scrape cohort H (NH, NJ, NM, NY).

OUL-016: official adapters emit live ``fetch_official`` results. New Jersey
source-link gaps are repaired to official LIS URLs or quarantined, and New
Mexico linkless bucket seed material is replaced from official NMOneSource
chapters or quarantined with a typed disposition. The declared cohort report
is fail-closed live evidence. Fixture transports never complete the cohort.
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
    NewHampshireScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_jersey import (
    NewJerseyScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico import (
    NewMexicoScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import (
    NewYorkScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
    StateScraperRegistry,
)


COHORT = "H"
TASK_ID = "OUL-016"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("NH", "NJ", "NM", "NY")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_H.json")

OFFICIAL_HOST_SUFFIXES = {
    "NH": ("gencourt.state.nh.us", "gc.nh.gov"),
    "NJ": ("njleg.state.nj.us",),
    "NM": ("nmonesource.com", "nmlegis.gov"),
    "NY": ("nysenate.gov",),
}

SCRAPER_TYPES = {
    "NH": NewHampshireScraper,
    "NJ": NewJerseyScraper,
    "NM": NewMexicoScraper,
    "NY": NewYorkScraper,
}

SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)

NJ_LINK_GAP_HTML = """
<html>
  <body>
    <a href="/nxt/gateway.dll/statutes/1/2c">Title 2C Criminal Justice</a>
    <a href="/nxt/gateway.dll/statutes/1/39">Title 39 Motor Vehicles</a>
    <span data-title="54A">Title 54A Gross Income Tax</span>
    <td>New Jersey phantom title without a recoverable official identifier</td>
    <p>open-us-law-bucket New Jersey seed row without an official source link</p>
  </body>
</html>
"""

NM_LINKLESS_HTML = """
<html>
  <body>
    <a href="/nmos/nmsa/en/nav_date.do#chapter-30">Chapter 30 Criminal Offenses</a>
    <a href="/nmos/nmsa/en/nav_date.do#chapter-7">Chapter 7 Taxation</a>
    <span data-chapter="66">Chapter 66 Motor Vehicles</span>
    <td>New Mexico phantom chapter without a recoverable official identifier</td>
    <p>open-us-law-bucket New Mexico seed row without an official source link</p>
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
    assert path.is_file(), f"declared cohort H report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "NH":
        return (
            "<html><body>"
            "<a href='/rsa/html/NHTOC/NHTOC-I.htm'>TITLE I: The State and Its Government</a>"
            "<a href='/rsa/html/NHTOC/NHTOC-LXII.htm'>TITLE LXII: Criminal Code</a>"
            "<a href='/rsa/html/NHTOC/NHTOC-LXIV.htm'>TITLE LXIV: Planning and Zoning</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "NJ":
        return (
            "<html><body>"
            "<a href='/nxt/gateway.dll/statutes/1/2c'>Title 2C Criminal Justice</a>"
            "<a href='/nxt/gateway.dll/statutes/1/39'>Title 39 Motor Vehicles</a>"
            "<a href='/nxt/gateway.dll/statutes/1/59'>Title 59 Claims Against Public Entities</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "NM":
        return (
            "<html><body>"
            "<a href='/nmos/nmsa/en/nav_date.do#chapter-1'>Chapter 1 Elections</a>"
            "<a href='/nmos/nmsa/en/nav_date.do#chapter-30'>Chapter 30 Criminal Offenses</a>"
            "<a href='/nmos/nmsa/en/nav_date.do#chapter-77'>Chapter 77 Animals and Livestock</a>"
            "</body></html>"
        ).encode("utf-8")
    return (
        "<html><body>"
        "<a href='/legislation/laws/PEN'>Penal Law</a>"
        "<a href='/legislation/laws/CPL'>Criminal Procedure Law</a>"
        "<a href='/legislation/laws/VAT'>Vehicle and Traffic Law</a>"
        "</body></html>"
    ).encode("utf-8")


def test_cohort_h_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_new_jersey_link_gaps_are_repaired_or_quarantined() -> None:
    scraper = NewJerseyScraper("NJ", "New Jersey")
    classified = scraper.classify_source_link_gaps(
        list(NewJerseyScraper.DEFAULT_LINK_GAP_SEEDS)
    )
    repaired = {item["canonical_key"]: item for item in classified["repaired"]}
    assert repaired["nj:title-2c"]["source_url"] == (
        "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1/2c"
    )
    assert repaired["nj:title-2c"]["repair_source"] == "repaired_from_linkless_row"
    assert repaired["nj:title-39"]["source_url"] == (
        "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1/39"
    )
    assert all(_host_allowed(item["source_url"], "NJ") for item in classified["repaired"])
    quarantines = classified["quarantines"]
    assert quarantines
    assert all(
        item["reason"]
        in {
            NewJerseyScraper.LINK_GAP_QUARANTINE_REASON,
            NewJerseyScraper.MISSING_LINK_DISPOSITION,
        }
        for item in quarantines
    )
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any(
        "untitled" in item["unit_id"] or "without an official" in item["label"].lower()
        for item in quarantines
    )
    assert any("phantom" in item["label"].lower() for item in quarantines)

    html_classified = scraper.classify_source_link_gaps(
        NJ_LINK_GAP_HTML,
        page_url="https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1",
    )
    html_repaired = {item["title_number"]: item for item in html_classified["repaired"]}
    assert "2C" in html_repaired
    assert "39" in html_repaired
    assert "54A" in html_repaired
    assert html_repaired["54A"]["repair_source"] == "repaired_from_linkless_row"
    assert html_classified["quarantines"]
    assert any("phantom" in item["label"].lower() for item in html_classified["quarantines"])


def test_new_mexico_linkless_seed_material_is_replaced_or_quarantined() -> None:
    scraper = NewMexicoScraper("NM", "New Mexico")
    classified = scraper.classify_linkless_seed_rows(
        list(NewMexicoScraper.DEFAULT_LINKLESS_SEED_ROWS)
    )
    repaired = {item["canonical_key"]: item for item in classified["repaired"]}
    assert repaired["nm:chapter-30"]["source_url"] == (
        "https://nmonesource.com/nmos/nmsa/en/nav_date.do#chapter-30"
    )
    assert repaired["nm:chapter-30"]["repair_source"] == "official_replacement"
    assert all(_host_allowed(item["source_url"], "NM") for item in classified["repaired"])
    quarantines = classified["quarantines"]
    assert quarantines
    assert all(
        item["reason"]
        in {
            NewMexicoScraper.LINKLESS_SEED_DISPOSITION,
            NewMexicoScraper.MISSING_LINK_DISPOSITION,
        }
        for item in quarantines
    )
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any(
        "untitled" in item["unit_id"] or "without an official" in item["label"].lower()
        for item in quarantines
    )
    assert any("phantom" in item["label"].lower() for item in quarantines)

    html_classified = scraper.classify_linkless_seed_rows(
        NM_LINKLESS_HTML,
        page_url="https://nmonesource.com/nmos/nmsa/en/nav_date.do",
    )
    html_repaired = {item["chapter_number"]: item for item in html_classified["repaired"]}
    assert "30" in html_repaired
    assert "7" in html_repaired
    assert "66" in html_repaired
    assert html_repaired["66"]["repair_source"] == "repaired_from_linkless_row"
    assert html_classified["quarantines"]
    assert any("phantom" in item["label"].lower() for item in html_classified["quarantines"])


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
    if state == "NH":
        assert len(fetch.rows) == NewHampshireScraper.OFFICIAL_TITLE_COUNT
    if state == "NJ":
        assert len(fetch.rows) == NewJerseyScraper.OFFICIAL_TITLE_COUNT
        assert fetch.frontier.get("nj_link_gaps_repaired") is True
        assert getattr(scraper, "last_official_quarantines", None)
        assert any(
            item["reason"]
            in {
                NewJerseyScraper.LINK_GAP_QUARANTINE_REASON,
                NewJerseyScraper.MISSING_LINK_DISPOSITION,
            }
            for item in scraper.last_official_quarantines
        )
    if state == "NM":
        assert len(fetch.rows) == NewMexicoScraper.OFFICIAL_CHAPTER_COUNT
        assert fetch.frontier.get("nm_linkless_seeds_replaced") is True
        assert getattr(scraper, "last_official_quarantines", None)
        assert any(
            item["reason"]
            in {
                NewMexicoScraper.LINKLESS_SEED_DISPOSITION,
                NewMexicoScraper.MISSING_LINK_DISPOSITION,
            }
            for item in scraper.last_official_quarantines
        )
    if state == "NY":
        assert len(fetch.rows) == NewYorkScraper.OFFICIAL_LAW_COUNT
    for row in fetch.rows:
        assert isinstance(row, Mapping)
        assert row.get("canonical_key")
        assert _host_allowed(str(row.get("source_url") or ""), state)
        assert str(row.get("source_link_disposition") or "") in {
            "official",
            "repaired_official_gencourt",
            "repaired_official_lis",
            "repaired_official_nmonesource",
            "repaired_official_nysenate",
            "official_replacement",
        }
        lowered = str(row.get("source_url") or "").lower()
        assert "justia.com" not in lowered
        assert "unicourt" not in lowered
        assert "findlaw.com" not in lowered


def test_official_catalogs_are_exhaustive() -> None:
    hampshire = NewHampshireScraper("NH", "New Hampshire")
    nh_rows = hampshire.enumerate_official_catalog(b"", page_url=hampshire.OFFICIAL_ENTRY_URL)
    assert len(nh_rows) == NewHampshireScraper.OFFICIAL_TITLE_COUNT
    assert {row["title_number"] for row in nh_rows} == {
        number for number, _name in NewHampshireScraper.OFFICIAL_TITLES
    }
    for row in nh_rows:
        assert _host_allowed(str(row["source_url"]), "NH")
        assert row["source_link_disposition"] in {"official", "repaired_official_gencourt"}

    jersey = NewJerseyScraper("NJ", "New Jersey")
    nj_rows = jersey.enumerate_official_catalog(b"", page_url=jersey.OFFICIAL_ENTRY_URL)
    assert len(nj_rows) == NewJerseyScraper.OFFICIAL_TITLE_COUNT
    for row in nj_rows:
        assert _host_allowed(str(row["source_url"]), "NJ")
        assert row["source_link_disposition"] in {
            "official",
            "repaired_official_lis",
            "official_replacement",
        }

    mexico = NewMexicoScraper("NM", "New Mexico")
    nm_rows = mexico.enumerate_official_catalog(b"", page_url=mexico.OFFICIAL_ENTRY_URL)
    assert len(nm_rows) == NewMexicoScraper.OFFICIAL_CHAPTER_COUNT
    for row in nm_rows:
        assert _host_allowed(str(row["source_url"]), "NM")
        assert row["source_link_disposition"] in {
            "official",
            "repaired_official_nmonesource",
            "official_replacement",
        }

    york = NewYorkScraper("NY", "New York")
    ny_rows = york.enumerate_official_catalog(b"", page_url=york.OFFICIAL_ENTRY_URL)
    assert len(ny_rows) == NewYorkScraper.OFFICIAL_LAW_COUNT
    for row in ny_rows:
        assert _host_allowed(str(row["source_url"]), "NY")
        assert row["source_link_disposition"] in {"official", "repaired_official_nysenate"}


def test_declared_cohort_h_report_is_live_certified() -> None:
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-016-{state.lower()}")
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
        if state == "NH":
            assert len(units) == NewHampshireScraper.OFFICIAL_TITLE_COUNT
            assert "gencourt.state.nh.us/rsa/html/NHTOC/" in json.dumps(units)
        if state == "NJ":
            catalog = json.loads(receipt["admitted_body"])
            assert catalog.get("link_gaps_repaired") is True
            quarantines = catalog.get("quarantines") or []
            assert quarantines
            assert all(
                item["reason"]
                in {
                    NewJerseyScraper.LINK_GAP_QUARANTINE_REASON,
                    NewJerseyScraper.MISSING_LINK_DISPOSITION,
                }
                for item in quarantines
            )
            assert len(units) == NewJerseyScraper.OFFICIAL_TITLE_COUNT
            assert "lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1/" in json.dumps(units)
        if state == "NM":
            catalog = json.loads(receipt["admitted_body"])
            assert catalog.get("linkless_seeds_replaced") is True
            assert catalog.get("replacement_source") == "official_nmonesource"
            quarantines = catalog.get("quarantines") or []
            assert quarantines
            assert all(
                item["reason"]
                in {
                    NewMexicoScraper.LINKLESS_SEED_DISPOSITION,
                    NewMexicoScraper.MISSING_LINK_DISPOSITION,
                }
                for item in quarantines
            )
            assert len(units) == NewMexicoScraper.OFFICIAL_CHAPTER_COUNT
            assert "nmonesource.com/nmos/nmsa/en/nav_date.do#chapter-" in json.dumps(units)
        if state == "NY":
            assert len(units) == NewYorkScraper.OFFICIAL_LAW_COUNT
            assert "nysenate.gov/legislation/laws/" in json.dumps(units)

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


def test_default_cohort_h_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_H.json"


def test_new_jersey_receipt_records_repaired_or_quarantined_link_gaps() -> None:
    payload = _load_declared_report()
    receipt = payload["jurisdiction_receipts"]["NJ"]
    catalog = json.loads(receipt["admitted_body"])
    assert catalog.get("link_gaps_repaired") is True
    assert "nj:title-2c" in receipt["admitted_body"]
    assert "lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1/" in receipt["admitted_body"]
    assert "justia.com" not in receipt["admitted_body"].lower()
    frontier = receipt.get("frontier") or {}
    assert frontier.get("nj_link_gaps_repaired") is True
    quarantines = list(
        frontier.get("nj_link_gap_quarantines")
        or catalog.get("quarantines")
        or receipt.get("quarantines")
        or []
    )
    assert quarantines
    assert all(
        item["reason"]
        in {
            NewJerseyScraper.LINK_GAP_QUARANTINE_REASON,
            NewJerseyScraper.MISSING_LINK_DISPOSITION,
        }
        for item in quarantines
    )
    assert all(len(str(item["evidence_sha256"])) == 64 for item in quarantines)


def test_new_mexico_receipt_records_replaced_or_quarantined_linkless_seeds() -> None:
    payload = _load_declared_report()
    receipt = payload["jurisdiction_receipts"]["NM"]
    catalog = json.loads(receipt["admitted_body"])
    assert catalog.get("linkless_seeds_replaced") is True
    assert catalog.get("replacement_source") == "official_nmonesource"
    assert "nm:chapter-30" in receipt["admitted_body"]
    assert "nmonesource.com/nmos/nmsa/en/nav_date.do#chapter-" in receipt["admitted_body"]
    assert "justia.com" not in receipt["admitted_body"].lower()
    frontier = receipt.get("frontier") or {}
    assert frontier.get("nm_linkless_seeds_replaced") is True
    quarantines = list(
        frontier.get("nm_linkless_seed_quarantines")
        or catalog.get("quarantines")
        or receipt.get("quarantines")
        or []
    )
    assert quarantines
    assert all(
        item["reason"]
        in {
            NewMexicoScraper.LINKLESS_SEED_DISPOSITION,
            NewMexicoScraper.MISSING_LINK_DISPOSITION,
        }
        for item in quarantines
    )
    assert all(len(str(item["evidence_sha256"])) == 64 for item in quarantines)

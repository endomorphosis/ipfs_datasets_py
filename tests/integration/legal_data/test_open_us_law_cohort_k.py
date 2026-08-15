"""Integration certification for Open US Law scrape cohort K (SD, TN, TX, UT).

OUL-019: official adapters emit live ``fetch_official`` results. Tennessee
linkless seed material is independently reacquired or quarantined, and
Texas mixed HTML/zip acquisition is fully reconciled. The declared cohort
report is fail-closed live evidence. Fixture transports never complete the
cohort.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
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


def _ensure_pkg(name: str, path: Path) -> None:
    existing = sys.modules.get(name)
    if existing is not None:
        return
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(path)]
    pkg.__package__ = name
    pkg.__file__ = str(path / "__init__.py")
    sys.modules[name] = pkg
    parent_name, _, child = name.rpartition(".")
    if parent_name and parent_name in sys.modules:
        setattr(sys.modules[parent_name], child, pkg)


def _load_state_module(name: str):
    root = Path(__file__).resolve().parents[3]
    legal_root = root / "ipfs_datasets_py/processors/legal_scrapers"
    state_root = legal_root / "state_scrapers"
    _ensure_pkg("ipfs_datasets_py.processors.legal_scrapers", legal_root)
    _ensure_pkg("ipfs_datasets_py.processors.legal_scrapers.state_scrapers", state_root)
    fullname = f"ipfs_datasets_py.processors.legal_scrapers.state_scrapers.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]
    path = state_root / f"{name}.py"
    spec = importlib.util.spec_from_file_location(fullname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {fullname}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


_citation_history = _load_state_module("citation_history")
_registry_mod = _load_state_module("registry")
_base_mod = _load_state_module("base_scraper")
_south_dakota_mod = _load_state_module("south_dakota")
_tennessee_mod = _load_state_module("tennessee")
_texas_mod = _load_state_module("texas")
_utah_mod = _load_state_module("utah")

SouthDakotaScraper = _south_dakota_mod.SouthDakotaScraper
TennesseeScraper = _tennessee_mod.TennesseeScraper
TexasScraper = _texas_mod.TexasScraper
UtahScraper = _utah_mod.UtahScraper
StateScraperRegistry = _registry_mod.StateScraperRegistry


COHORT = "K"
TASK_ID = "OUL-019"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("SD", "TN", "TX", "UT")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_K.json")

OFFICIAL_HOST_SUFFIXES = {
    "SD": ("sdlegislature.gov",),
    "TN": ("tn.gov", "capitol.tn.gov"),
    "TX": ("statutes.capitol.texas.gov", "tcss.legis.texas.gov", "capitol.texas.gov"),
    "UT": ("le.utah.gov",),
}

SCRAPER_TYPES = {
    "SD": SouthDakotaScraper,
    "TN": TennesseeScraper,
    "TX": TexasScraper,
    "UT": UtahScraper,
}

SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)

TN_LINKLESS_HTML = """
<html>
  <body>
    <a href="/tga/statutes/title-1/">Title 1 Code and Statutes</a>
    <a href="/tga/statutes/title-2/">Title 2 Elections</a>
    <span>Title 39 Criminal Offenses</span>
    <a href="javascript:void(0)">Title 40 Criminal Procedure</a>
    <td>Tennessee statutes phantom chapter without a recoverable official identifier</td>
    <p>TCA appendix reserved without a title number</p>
  </body>
</html>
"""

TN_LINKLESS_SEED_ROWS = (
    {
        "statute_id": "Tenn. Code Ann. § 39-17-402",
        "section_number": "39-17-402",
        "source_url": "",
        "text": "Definitions",
    },
    {
        "statute_id": "TCA 40-35-104",
        "source_url": "https://law.justia.com/codes/tennessee/title-40/chapter-35/section-40-35-104/",
        "text": "Sentencing alternatives",
    },
    {
        "name": "Unlabeled Tennessee bucket remnant",
        "source_url": "",
        "text": "legacy snapshot row with no citation",
    },
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
    assert path.is_file(), f"declared cohort K report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "SD":
        return (
            "<html><body>"
            "<a href='/Statutes/Codified_Laws/1'>Title 1 State Affairs</a>"
            "<a href='/Statutes/Codified_Laws/22'>Title 22 Crimes</a>"
            "<a href='/Statutes/Codified_Laws/62'>Title 62 Workers Compensation</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "TN":
        return TN_LINKLESS_HTML.encode("utf-8")
    if state == "TX":
        return (
            "<html><body>"
            "<a href='/Docs/AG/htm/AG.1.htm'>Agriculture Code</a>"
            "<a href='/Docs/PE/htm/PE.1.htm'>Penal Code</a>"
            "<a href='/Docs/WA/htm/WA.1.htm'>Water Code</a>"
            "<a href='https://tcss.legis.texas.gov/resources/Zips/PE.htm.zip'>PE zip</a>"
            "<a href='https://texreg.sos.state.tx.us/public/readtac$ext.ViewTAC'>Texas Administrative Code</a>"
            "</body></html>"
        ).encode("utf-8")
    return (
        "<html><body>"
        "<a href='/xcode/Title1/'>Title 1 General Provisions</a>"
        "<a href='/xcode/Title76/'>Title 76 Utah Criminal Code</a>"
        "<a href='/xcode/Title81/'>Title 81 Utah Uniform Probate Code</a>"
        "</body></html>"
    ).encode("utf-8")


def test_cohort_k_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_south_dakota_synthetic_two_row_success_is_rejected() -> None:
    two_row = {
        "jurisdiction": "SD",
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

    scraper = SouthDakotaScraper("SD", "South Dakota")
    rows = scraper.enumerate_official_catalog(b"")
    assert len(rows) > 2
    assert len(rows) == SouthDakotaScraper.OFFICIAL_TITLE_COUNT
    for row in rows:
        assert _host_allowed(str(row["source_url"]), "SD")
        assert "justia.com" not in str(row["source_url"]).lower()


def test_tennessee_linkless_material_is_reacquired_or_quarantined() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    classified = scraper.classify_linkless_seed_rows(TN_LINKLESS_SEED_ROWS)
    repaired = {item["title_number"]: item for item in classified["repaired"]}
    assert repaired["39"]["source_url"] == "https://www.tn.gov/tga/statutes/title-39/"
    assert repaired["39"]["repair_source"] == "repaired_from_linkless_row"
    assert repaired["40"]["source_url"] == "https://www.tn.gov/tga/statutes/title-40/"
    assert "justia.com" not in repaired["40"]["source_url"].lower()
    assert all(_host_allowed(item["source_url"], "TN") for item in classified["repaired"])

    quarantines = classified["quarantines"]
    assert quarantines
    assert all(item["reason"] == TennesseeScraper.LINKLESS_QUARANTINE_REASON for item in quarantines)
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any("Unlabeled" in item["label"] or "legacy snapshot" in item["label"] for item in quarantines)

    html_classified = scraper.classify_linkless_seed_rows(
        TN_LINKLESS_HTML,
        page_url="https://www.tn.gov/tga/statutes.html",
    )
    html_repaired = {item["title_number"]: item for item in html_classified["repaired"]}
    assert "1" in html_repaired
    assert "2" in html_repaired
    assert "39" in html_repaired
    assert "40" in html_repaired
    assert html_repaired["39"]["repair_source"] == "repaired_from_linkless_row"
    assert html_repaired["40"]["repair_source"] == "repaired_from_linkless_row"
    html_quarantines = html_classified["quarantines"]
    assert html_quarantines
    assert all(
        item["reason"] == TennesseeScraper.LINKLESS_QUARANTINE_REASON
        for item in html_quarantines
    )
    assert any(
        "phantom" in item["label"].lower() or "appendix" in item["label"].lower()
        for item in html_quarantines
    )


def test_texas_mixed_acquisition_is_fully_reconciled() -> None:
    scraper = TexasScraper("TX", "Texas")
    html_codes = {
        "PE": "https://statutes.capitol.texas.gov/Docs/PE/htm/PE.1.htm",
        "AG": "https://law.justia.com/codes/texas/agriculture/",
    }
    zip_codes = {
        "PE": "https://tcss.legis.texas.gov/resources/Zips/PE.htm.zip",
    }
    extra = (
        {
            "name": "Texas Administrative Code",
            "source_url": "https://texreg.sos.state.tx.us/public/readtac$ext.ViewTAC",
        },
    )
    reconciled = scraper.reconcile_mixed_acquisition(
        html_codes,
        zip_codes,
        extra_candidates=extra,
    )
    assert reconciled["reconciled"] is True
    units = {item["code_abbrev"]: item for item in reconciled["units"]}
    assert set(units) == {abbrev for abbrev, _name in TexasScraper.OFFICIAL_CODES}
    assert len(units) == TexasScraper.OFFICIAL_CODE_COUNT
    assert units["PE"]["mixed_reconciled"] is True
    assert units["PE"]["acquisition_channels"] == ["html", "zip"]
    assert units["AG"]["source_url"] == scraper.official_html_url("AG")
    assert "justia.com" not in units["AG"]["source_url"].lower()
    for item in reconciled["units"]:
        assert _host_allowed(str(item["source_url"]), "TX")
        assert _host_allowed(str(item["zip_url"]), "TX")
        assert item["mixed_reconciled"] is True
        assert item["acquisition_channels"] == ["html", "zip"]
    assert reconciled["excluded"]
    assert any(item["code_abbrev"] == "TAC" for item in reconciled["excluded"])


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
    if state == "SD":
        assert len(fetch.rows) == SouthDakotaScraper.OFFICIAL_TITLE_COUNT
    if state == "TN":
        assert len(fetch.rows) == TennesseeScraper.OFFICIAL_TITLE_COUNT
        assert getattr(scraper, "last_official_quarantines", None)
    if state == "TX":
        assert len(fetch.rows) == TexasScraper.OFFICIAL_CODE_COUNT
        assert fetch.frontier.get("tx_mixed_reconciled") is True
        assert all(item.get("mixed_reconciled") for item in fetch.rows)
    if state == "UT":
        assert len(fetch.rows) == UtahScraper.OFFICIAL_TITLE_COUNT
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
        assert "findlaw.com" not in lowered
        assert "texreg.sos" not in lowered


def test_declared_cohort_k_report_is_live_certified() -> None:
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-019-{state.lower()}")
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
            assert "findlaw.com" not in lowered
            assert "texreg.sos" not in lowered
        if state == "SD":
            assert len(units) == SouthDakotaScraper.OFFICIAL_TITLE_COUNT
            assert "sdlegislature.gov/Statutes/Codified_Laws/" in json.dumps(units)
        if state == "TN":
            assert len(units) == TennesseeScraper.OFFICIAL_TITLE_COUNT
            assert "tn.gov/tga/statutes/title-" in json.dumps(units)
        if state == "TX":
            assert len(units) == TexasScraper.OFFICIAL_CODE_COUNT
            serialized_units = json.dumps(units)
            assert "statutes.capitol.texas.gov/Docs/" in serialized_units
            assert "tcss.legis.texas.gov/resources/Zips/" in serialized_units
            assert all(item.get("mixed_reconciled") for item in units)
        if state == "UT":
            assert len(units) == UtahScraper.OFFICIAL_TITLE_COUNT
            assert "le.utah.gov/xcode/Title" in json.dumps(units)

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


def test_default_cohort_k_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_K.json"


def test_tennessee_receipt_records_replaced_or_quarantined_linkless_seed() -> None:
    payload = _load_declared_report()
    receipt = payload["jurisdiction_receipts"]["TN"]
    disposition = receipt["disposition"]
    quarantined = int(disposition.get("quarantined") or 0)
    discovered = int(disposition["discovered"])
    fetched = int(disposition["fetched"])
    excluded = int(disposition.get("excluded") or 0)
    failed_final = int(disposition.get("failed_final") or 0)
    assert discovered == fetched + excluded + quarantined + failed_final
    admitted_body = str(receipt.get("admitted_body") or "")
    assert "tn:title-" in admitted_body
    assert "tn.gov/tga/statutes/title-" in admitted_body
    assert "justia.com" not in admitted_body.lower()
    frontier = receipt.get("frontier") or {}
    catalog = json.loads(admitted_body)
    quarantines = list(
        frontier.get("tn_linkless_seed_quarantines")
        or catalog.get("quarantines")
        or receipt.get("quarantines")
        or []
    )
    if quarantined:
        assert len(quarantines) == quarantined
        for item in quarantines:
            assert item["reason"] == TennesseeScraper.LINKLESS_QUARANTINE_REASON
            assert str(item["unit_id"]).startswith("tn:")
            assert len(str(item["evidence_sha256"])) == 64
    else:
        assert quarantines
        assert any(
            item["reason"] == TennesseeScraper.LINKLESS_QUARANTINE_REASON
            for item in quarantines
        )


def test_texas_receipt_records_reconciled_mixed_acquisition() -> None:
    payload = _load_declared_report()
    receipt = payload["jurisdiction_receipts"]["TX"]
    catalog = json.loads(receipt["admitted_body"])
    units = catalog.get("units") or []
    assert len(units) == TexasScraper.OFFICIAL_CODE_COUNT
    assert catalog.get("mixed_reconciled") is True
    assert receipt["frontier"].get("tx_mixed_reconciled") is True
    for item in units:
        assert item.get("mixed_reconciled") is True
        assert item.get("acquisition_channels") == ["html", "zip"]
        assert _host_allowed(str(item.get("source_url") or ""), "TX")
        assert _host_allowed(str(item.get("zip_url") or ""), "TX")
        assert "texreg.sos" not in str(item.get("source_url") or "").lower()

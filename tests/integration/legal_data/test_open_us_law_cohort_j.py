"""Integration certification for Open US Law scrape cohort J (OR, PA, RI, SC).

OUL-018: official adapters emit live ``fetch_official`` results, and unofficial
Oregon seed text is replaced with official ORS URLs or quarantined with a
typed disposition. The declared cohort report is fail-closed live evidence.
Fixture transports never complete the cohort.
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
_oregon_admin = _load_state_module("oregon_admin_rules")
_oregon_mod = _load_state_module("oregon")
_pennsylvania_mod = _load_state_module("pennsylvania")
_rhode_island_mod = _load_state_module("rhode_island")
_south_carolina_mod = _load_state_module("south_carolina")

OregonScraper = _oregon_mod.OregonScraper
PennsylvaniaScraper = _pennsylvania_mod.PennsylvaniaScraper
RhodeIslandScraper = _rhode_island_mod.RhodeIslandScraper
SouthCarolinaScraper = _south_carolina_mod.SouthCarolinaScraper
StateScraperRegistry = _registry_mod.StateScraperRegistry


COHORT = "J"
TASK_ID = "OUL-018"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("OR", "PA", "RI", "SC")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_J.json")

OFFICIAL_HOST_SUFFIXES = {
    "OR": ("oregonlegislature.gov",),
    "PA": ("palegis.us", "legis.state.pa.us"),
    "RI": ("rilegislature.gov",),
    "SC": ("scstatehouse.gov",),
}

SCRAPER_TYPES = {
    "OR": OregonScraper,
    "PA": PennsylvaniaScraper,
    "RI": RhodeIslandScraper,
    "SC": SouthCarolinaScraper,
}

SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)

OR_NONOFFICIAL_SEED_HTML = """
<html>
  <body>
    <a href="/bills_laws/ors/ors001.html">ORS Chapter 1</a>
    <a href="/bills_laws/ors/ors161.html">ORS Chapter 161</a>
    <span data-chapter="163">ORS 163 Criminal homicide</span>
    <a href="https://law.justia.com/codes/oregon/ors-164.html">ORS Chapter 164</a>
    <td>Oregon statutes phantom chapter without a recoverable official identifier</td>
    <p>ORS appendix reserved without a chapter number</p>
  </body>
</html>
"""

OR_NONOFFICIAL_SEED_ROWS = (
    {
        "statute_id": "ORS 161.205",
        "section_number": "161.205",
        "source_url": "https://law.justia.com/codes/oregon/ors-161-205.html",
        "text": "Use of physical force generally",
    },
    {
        "statute_id": "Oregon Revised Statutes 163.005",
        "source_url": "https://codes.findlaw.com/or/title-16-crimes-and-punishments/or-rev-st-sect-163-005.html",
        "text": "Criminal homicide",
    },
    {
        "name": "Unlabeled Oregon bucket remnant",
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
    assert path.is_file(), f"declared cohort J report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "OR":
        return (
            "<html><body>"
            "<a href='/bills_laws/ors/ors001.html'>Volume 1 Courts</a>"
            "<a href='/bills_laws/ors/ors131.html'>Volume 4 Criminal Procedure</a>"
            "<a href='/bills_laws/ors/ors801.html'>Volume 19 Vehicle Code</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "PA":
        return (
            "<html><body>"
            "<a href='/statutes/consolidated/view-statute?txtType=HTM&ttl=1'>Title 1</a>"
            "<a href='/statutes/consolidated/view-statute?txtType=HTM&ttl=18'>Title 18</a>"
            "<a href='/statutes/consolidated/view-statute?txtType=HTM&ttl=75'>Title 75</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "RI":
        return (
            "<html><body>"
            "<a href='/Statutes/TITLE1/INDEX.HTM'>Title 1 Aeronautics</a>"
            "<a href='/Statutes/TITLE11/INDEX.HTM'>Title 11 Criminal Offenses</a>"
            "<a href='/Statutes/TITLE47/INDEX.HTM'>Title 47 Weights and Measures</a>"
            "</body></html>"
        ).encode("utf-8")
    return (
        "<html><body>"
        "<a href='/code/title1.php'>Title 1 Administration</a>"
        "<a href='/code/title16.php'>Title 16 Crimes and Offenses</a>"
        "<a href='/code/title63.php'>Title 63 Children's Code</a>"
        "</body></html>"
    ).encode("utf-8")


def test_cohort_j_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_oregon_synthetic_two_row_success_is_rejected() -> None:
    two_row = {
        "jurisdiction": "OR",
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

    scraper = OregonScraper("OR", "Oregon")
    rows = scraper.enumerate_official_catalog(b"")
    assert len(rows) > 2
    assert len(rows) == OregonScraper.OFFICIAL_VOLUME_COUNT
    for row in rows:
        assert _host_allowed(str(row["source_url"]), "OR")
        assert "justia.com" not in str(row["source_url"]).lower()
        assert "unicourt" not in str(row["source_url"]).lower()


def test_oregon_nonofficial_seed_text_is_replaced_or_quarantined() -> None:
    scraper = OregonScraper("OR", "Oregon")
    classified = scraper.classify_nonofficial_seed_rows(OR_NONOFFICIAL_SEED_ROWS)
    repaired = {item["canonical_key"]: item for item in classified["repaired"]}
    assert repaired["or:chapter-161"]["source_url"] == (
        "https://www.oregonlegislature.gov/bills_laws/ors/ors161.html"
    )
    assert repaired["or:chapter-161"]["repair_source"] == "repaired_from_linkless_row"
    assert repaired["or:chapter-163"]["source_url"] == (
        "https://www.oregonlegislature.gov/bills_laws/ors/ors163.html"
    )
    assert "justia.com" not in repaired["or:chapter-161"]["source_url"].lower()
    assert "findlaw.com" not in repaired["or:chapter-163"]["source_url"].lower()
    quarantines = classified["quarantines"]
    assert quarantines
    assert all(item["reason"] == OregonScraper.NONOFFICIAL_SEED_DISPOSITION for item in quarantines)
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any(
        "Unlabeled" in item["label"] or "legacy snapshot" in item["label"] for item in quarantines
    )

    html_classified = scraper.classify_nonofficial_seed_rows(
        OR_NONOFFICIAL_SEED_HTML,
        page_url="https://www.oregonlegislature.gov/bills_laws/Pages/ORS.aspx",
    )
    html_repaired = {item["chapter"]: item for item in html_classified["repaired"]}
    assert "1" in html_repaired
    assert "161" in html_repaired
    assert "163" in html_repaired
    assert "164" in html_repaired
    assert html_repaired["163"]["repair_source"] == "repaired_from_linkless_row"
    assert html_repaired["164"]["source_url"] == (
        "https://www.oregonlegislature.gov/bills_laws/ors/ors164.html"
    )
    html_quarantines = html_classified["quarantines"]
    assert html_quarantines
    assert all(
        item["reason"]
        in {
            OregonScraper.MISSING_LINK_DISPOSITION,
            OregonScraper.NONOFFICIAL_SEED_DISPOSITION,
        }
        for item in html_quarantines
    )
    assert any(
        "appendix" in item["label"].lower() or "Phantom" in item["label"] for item in html_quarantines
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
    if state == "OR":
        assert len(fetch.rows) > 2
        assert len(fetch.rows) == OregonScraper.OFFICIAL_VOLUME_COUNT
        assert getattr(scraper, "last_official_quarantines", None)
    if state == "PA":
        assert len(fetch.rows) == PennsylvaniaScraper.OFFICIAL_TITLE_COUNT
    if state == "RI":
        assert len(fetch.rows) == RhodeIslandScraper.OFFICIAL_TITLE_COUNT
    if state == "SC":
        assert len(fetch.rows) == SouthCarolinaScraper.OFFICIAL_TITLE_COUNT
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
        assert "findlaw.com" not in lowered


def test_declared_cohort_j_report_is_live_certified() -> None:
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-018-{state.lower()}")
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
        if state == "OR":
            assert int(receipt["row_count"]) > 2
            assert len(units) == OregonScraper.OFFICIAL_VOLUME_COUNT
            serialized_units = json.dumps(units)
            assert "oregonlegislature.gov/bills_laws/ors/" in serialized_units
        if state == "PA":
            assert len(units) == PennsylvaniaScraper.OFFICIAL_TITLE_COUNT
            assert "palegis.us/statutes/consolidated" in json.dumps(units)
        if state == "RI":
            assert len(units) == RhodeIslandScraper.OFFICIAL_TITLE_COUNT
            assert "rilegislature.gov/Statutes/TITLE" in json.dumps(units)
        if state == "SC":
            assert len(units) == SouthCarolinaScraper.OFFICIAL_TITLE_COUNT
            assert "scstatehouse.gov/code/title" in json.dumps(units)

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


def test_default_cohort_j_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_J.json"


def test_oregon_receipt_records_replaced_or_quarantined_nonofficial_seed() -> None:
    payload = _load_declared_report()
    receipt = payload["jurisdiction_receipts"]["OR"]
    disposition = receipt["disposition"]
    quarantined = int(disposition.get("quarantined") or 0)
    discovered = int(disposition["discovered"])
    fetched = int(disposition["fetched"])
    excluded = int(disposition.get("excluded") or 0)
    failed_final = int(disposition.get("failed_final") or 0)
    assert discovered == fetched + excluded + quarantined + failed_final
    admitted_body = str(receipt.get("admitted_body") or "")
    assert "or:volume-" in admitted_body
    assert "oregonlegislature.gov/bills_laws/ors/" in admitted_body
    assert "justia.com" not in admitted_body.lower()
    assert "findlaw.com" not in admitted_body.lower()
    frontier = receipt.get("frontier") or {}
    catalog = json.loads(admitted_body)
    quarantines = list(
        frontier.get("or_nonofficial_seed_quarantines")
        or catalog.get("quarantines")
        or receipt.get("quarantines")
        or []
    )
    if quarantined:
        assert len(quarantines) == quarantined
        for item in quarantines:
            assert item["reason"] in {
                OregonScraper.MISSING_LINK_DISPOSITION,
                OregonScraper.NONOFFICIAL_SEED_DISPOSITION,
            }
            assert str(item["unit_id"]).startswith("or:")
            assert len(str(item["evidence_sha256"])) == 64
    else:
        assert quarantines
        assert any(
            item["reason"]
            in {
                OregonScraper.MISSING_LINK_DISPOSITION,
                OregonScraper.NONOFFICIAL_SEED_DISPOSITION,
            }
            for item in quarantines
        )

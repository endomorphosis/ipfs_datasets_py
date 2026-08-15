"""Integration certification for Open US Law scrape cohort L (VT, VA, WA, WV).

OUL-020: official adapters emit live ``fetch_official`` results. Every
continuation is exhausted and no partial checkpoint is promoted. The
declared cohort report is fail-closed live evidence. Fixture transports
never complete the cohort.
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
_vermont_mod = _load_state_module("vermont")
_virginia_mod = _load_state_module("virginia")
_washington_mod = _load_state_module("washington")
_west_virginia_mod = _load_state_module("west_virginia")

VermontScraper = _vermont_mod.VermontScraper
VirginiaScraper = _virginia_mod.VirginiaScraper
WashingtonScraper = _washington_mod.WashingtonScraper
WestVirginiaScraper = _west_virginia_mod.WestVirginiaScraper
StateScraperRegistry = _registry_mod.StateScraperRegistry


COHORT = "L"
TASK_ID = "OUL-020"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("VT", "VA", "WA", "WV")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_L.json")

OFFICIAL_HOST_SUFFIXES = {
    "VT": ("legislature.vermont.gov",),
    "VA": ("law.lis.virginia.gov", "lis.virginia.gov"),
    "WA": ("app.leg.wa.gov", "leg.wa.gov"),
    "WV": ("code.wvlegislature.gov",),
}

SCRAPER_TYPES = {
    "VT": VermontScraper,
    "VA": VirginiaScraper,
    "WA": WashingtonScraper,
    "WV": WestVirginiaScraper,
}

SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)

ALLOWED_DISPOSITIONS = {
    "official",
    "repaired_official_leginfo",
    "repaired_official_vtleg",
    "repaired_official_valis",
    "repaired_official_waleg",
    "repaired_official_wvcode",
}


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
    assert path.is_file(), f"declared cohort L report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "VT":
        return (
            "<html><body>"
            "<a href='/statutes/title/01'>Title 1 General Provisions</a>"
            "<a href='/statutes/title/13'>Title 13 Crimes and Criminal Procedure</a>"
            "<a href='/statutes/title/33'>Title 33 Human Services</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "VA":
        return (
            "<html><body>"
            "<a href='/vacode/title1/'>Title 1 General Provisions</a>"
            "<a href='/vacode/title18.2/'>Title 18.2 Crimes and Offenses Generally</a>"
            "<a href='/vacode/title67/'>Title 67 Virginia Energy Plan</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "WA":
        return (
            "<html><body>"
            "<a href='/RCW/default.aspx?cite=1'>Title 1 General Provisions</a>"
            "<a href='/RCW/default.aspx?cite=9A'>Title 9A Washington Criminal Code</a>"
            "<a href='/RCW/default.aspx?cite=91'>Title 91 Waterways</a>"
            "</body></html>"
        ).encode("utf-8")
    return (
        "<html><body>"
        "<select id='sel-chapter'>"
        "<option value='1'>Chapter 1 The State and Its Subdivisions</option>"
        "<option value='61'>Chapter 61 Crimes and Their Punishment</option>"
        "<option value='64'>Chapter 64 Legislative Rules</option>"
        "</select>"
        "<a href='/1/'>Chapter 1 The State and Its Subdivisions</a>"
        "<a href='/61/'>Chapter 61 Crimes and Their Punishment</a>"
        "<a href='/64/'>Chapter 64 Legislative Rules</a>"
        "</body></html>"
    ).encode("utf-8")


def _expected_unit_count(state: str) -> int:
    if state == "VT":
        return VermontScraper.OFFICIAL_TITLE_COUNT
    if state == "VA":
        return VirginiaScraper.OFFICIAL_TITLE_COUNT
    if state == "WA":
        return WashingtonScraper.OFFICIAL_TITLE_COUNT
    return WestVirginiaScraper.OFFICIAL_CHAPTER_COUNT


def test_cohort_l_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


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
    assert len(fetch.rows) == _expected_unit_count(state)
    assert fetch.frontier.get("closed") is True
    assert fetch.frontier.get("pagination_closed") is True
    assert fetch.frontier.get("toc_exhausted") is True
    assert list(fetch.frontier.get("unvisited_continuation_links") or []) == []
    assert int(fetch.frontier.get("expected_index_units") or 0) == len(fetch.rows)
    assert fetch.source_domain
    assert _host_allowed(f"https://{fetch.source_domain}{fetch.source_path}", state)
    checkpoint = getattr(scraper, "last_official_checkpoint", None)
    assert isinstance(checkpoint, Mapping)
    assert checkpoint.get("partial") is False
    assert checkpoint.get("promoted_success") is False
    assert checkpoint.get("completion_basis") == "source_frontier"
    for row in fetch.rows:
        assert isinstance(row, Mapping)
        assert row.get("canonical_key")
        assert _host_allowed(str(row.get("source_url") or ""), state)
        assert str(row.get("source_link_disposition") or "") in ALLOWED_DISPOSITIONS
        lowered = str(row.get("source_url") or "").lower()
        assert "justia.com" not in lowered
        assert "unicourt" not in lowered
        assert "findlaw.com" not in lowered


def test_official_catalogs_are_exhaustive() -> None:
    vermont = VermontScraper("VT", "Vermont")
    vt_rows = vermont.enumerate_official_catalog(b"", page_url=vermont.OFFICIAL_ENTRY_URL)
    assert len(vt_rows) == VermontScraper.OFFICIAL_TITLE_COUNT
    assert {row["title_number"] for row in vt_rows} == {
        number for number, _name in VermontScraper.OFFICIAL_TITLES
    }
    for row in vt_rows:
        assert _host_allowed(str(row["source_url"]), "VT")
        assert row["source_link_disposition"] in ALLOWED_DISPOSITIONS

    virginia = VirginiaScraper("VA", "Virginia")
    va_rows = virginia.enumerate_official_catalog(b"", page_url=virginia.OFFICIAL_ENTRY_URL)
    assert len(va_rows) == VirginiaScraper.OFFICIAL_TITLE_COUNT
    for row in va_rows:
        assert _host_allowed(str(row["source_url"]), "VA")
        assert row["source_link_disposition"] in ALLOWED_DISPOSITIONS

    washington = WashingtonScraper("WA", "Washington")
    wa_rows = washington.enumerate_official_catalog(b"", page_url=washington.OFFICIAL_ENTRY_URL)
    assert len(wa_rows) == WashingtonScraper.OFFICIAL_TITLE_COUNT
    for row in wa_rows:
        assert _host_allowed(str(row["source_url"]), "WA")
        assert row["source_link_disposition"] in ALLOWED_DISPOSITIONS

    west_virginia = WestVirginiaScraper("WV", "West Virginia")
    wv_rows = west_virginia.enumerate_official_catalog(b"", page_url=west_virginia.OFFICIAL_ENTRY_URL)
    assert len(wv_rows) == WestVirginiaScraper.OFFICIAL_CHAPTER_COUNT
    assert {row["chapter_number"] for row in wv_rows} == {
        number for number, _name in WestVirginiaScraper.OFFICIAL_CHAPTERS
    }
    for row in wv_rows:
        assert _host_allowed(str(row["source_url"]), "WV")
        assert row["source_link_disposition"] in ALLOWED_DISPOSITIONS


def test_continuations_are_exhausted_and_partial_checkpoints_are_not_promoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_urls: Dict[str, list[str]] = {code: [] for code in EXPECTED_STATES}

    def _tracking_get(state: str):
        def _get(url: str, timeout_seconds: int = 30) -> bytes:
            seen_urls[state].append(url)
            return _compact_official_html(state)

        return _get

    for state in EXPECTED_STATES:
        scraper = SCRAPER_TYPES[state](state, state)
        monkeypatch.setattr(scraper, "_official_http_get", _tracking_get(state))
        monkeypatch.setattr(
            scraper,
            "_load_partial_checkpoint_statutes",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("partial checkpoint must not be promoted")
            ),
            raising=False,
        )
        fetch = scraper.fetch_official(state)
        assert fetch.frontier.get("unvisited_continuation_links") == []
        assert fetch.frontier.get("toc_exhausted") is True
        assert fetch.frontier.get("pagination_closed") is True
        assert fetch.frontier.get("closed") is True
        assert getattr(scraper, "last_official_checkpoint")["partial"] is False
        assert getattr(scraper, "last_official_checkpoint")["promoted_success"] is False
        assert seen_urls[state]
        assert all(_host_allowed(url, state) for url in seen_urls[state])


def test_declared_cohort_l_report_is_live_certified() -> None:
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
        assert int(receipt["row_count"]) >= _expected_unit_count(state)
        assert int(receipt["disposition"]["fetched"]) >= _expected_unit_count(state)
        assert receipt.get("admitted_body")
        assert receipt["checkpoint"]["partial"] is False
        assert receipt["checkpoint"]["promoted_success"] is False
        assert receipt["frontier"]["closed"] is True
        assert list(receipt["frontier"].get("unvisited_continuation_links") or []) == []
        kinds = collect_certification_rejections(receipt)
        assert kinds == [], f"{state} certification rejections: {kinds}"
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-020-{state.lower()}")
        assert verdict.complete is True, (
            f"{state} completeness failed: {[item.detail for item in verdict.findings]}"
        )
        admission = evaluate_prior_receipt(receipt)
        assert admission.accepted is True
        units = json.loads(receipt["admitted_body"]).get("units") or []
        assert len(units) >= _expected_unit_count(state)
        for item in units:
            assert _host_allowed(str(item.get("source_url") or ""), state)
            lowered = str(item.get("source_url") or "").lower()
            assert "justia.com" not in lowered
            assert "unicourt" not in lowered
            assert "findlaw.com" not in lowered

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


def test_default_cohort_l_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_L.json"

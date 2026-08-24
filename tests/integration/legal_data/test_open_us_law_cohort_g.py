"""Integration certification for Open US Law scrape cohort G (MO, MT, NE, NV).

OUL-015: official adapters emit live ``fetch_official`` results, and Nevada
linkless bucket material is replaced with official NRS URLs or quarantined
with a typed disposition. The declared cohort report is fail-closed live
evidence. Fixture transports never complete the cohort.
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri import (
    MissouriScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana import (
    MontanaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska import (
    NebraskaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada import (
    NevadaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
    StateScraperRegistry,
)


COHORT = "G"
TASK_ID = "OUL-015"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("MO", "MT", "NE", "NV")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_G.json")

OFFICIAL_HOST_SUFFIXES = {
    "MO": ("revisor.mo.gov",),
    "MT": ("leg.mt.gov",),
    "NE": ("nebraskalegislature.gov",),
    "NV": ("leg.state.nv.us",),
}

SCRAPER_TYPES = {
    "MO": MissouriScraper,
    "MT": MontanaScraper,
    "NE": NebraskaScraper,
    "NV": NevadaScraper,
}

SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)

NV_LINKLESS_HTML = """
<html>
  <body>
    <a href="NRS-001.html">NRS Chapter 1</a>
    <a href="/NRS/NRS-200.html">NRS Chapter 200</a>
    <span data-chapter="62A">NRS 62A Juvenile justice</span>
    <td>Title 99 Phantom chapter without an official source link</td>
    <p>NRS appendix reserved without a chapter number</p>
  </body>
</html>
"""

NV_LINKLESS_BUCKET_ROWS = (
    {
        "statute_id": "NRS 200.010",
        "section_number": "200.010",
        "source_url": "",
        "text": "Murder defined",
    },
    {
        "statute_id": "Nevada Revised Statutes 1.010",
        "source_url": "https://law.justia.com/codes/nevada/nrs-1-010.html",
        "text": "Definitions",
    },
    {
        "name": "Unlabeled NV bucket remnant",
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
    assert path.is_file(), f"declared cohort G report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "MO":
        return (
            "<html><body>"
            "<a href='/main/OneChapter.aspx?chapter=1'>Chapter 1</a>"
            "<a href='/main/OneChapter.aspx?chapter=565'>Chapter 565</a>"
            "<a href='/main/OneChapter.aspx?chapter=701'>Chapter 701</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "MT":
        return (
            "<html><body>"
            "<a href='title_0010/chapters_index.html'>Title 1</a>"
            "<a href='title_0450/chapters_index.html'>Title 45</a>"
            "<a href='title_0900/chapters_index.html'>Title 90</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "NE":
        return (
            "<html><body>"
            "<a href='/laws/browse-chapters.php?chapter=1'>Chapter 1</a>"
            "<a href='/laws/browse-chapters.php?chapter=28'>Chapter 28</a>"
            "<a href='/laws/browse-chapters.php?chapter=90'>Chapter 90</a>"
            "</body></html>"
        ).encode("utf-8")
    return (
        "<html><body>"
        "<b>Title 1 State Judicial Department</b>"
        "<a href='NRS-001.html'>NRS 1</a>"
        "<b>Title 15 Crimes and Punishments</b>"
        "<a href='NRS-200.html'>NRS 200</a>"
        "<b>Title 59 Electronic Records</b>"
        "<a href='NRS-722.html'>NRS 722</a>"
        "</body></html>"
    ).encode("utf-8")


def test_cohort_g_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_nevada_synthetic_two_row_success_is_rejected() -> None:
    two_row = {
        "jurisdiction": "NV",
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

    scraper = NevadaScraper("NV", "Nevada")
    rows = scraper.enumerate_official_catalog(b"")
    assert len(rows) > 2
    assert len(rows) == NevadaScraper.OFFICIAL_TITLE_COUNT
    for row in rows:
        assert _host_allowed(str(row["source_url"]), "NV")
        assert "justia.com" not in str(row["source_url"]).lower()
        assert "unicourt" not in str(row["source_url"]).lower()


def test_nevada_linkless_bucket_material_is_replaced_or_quarantined() -> None:
    scraper = NevadaScraper("NV", "Nevada")
    classified = scraper.classify_linkless_bucket_rows(NV_LINKLESS_BUCKET_ROWS)
    repaired = {item["canonical_key"]: item for item in classified["repaired"]}
    assert repaired["nv:chapter-200"]["source_url"] == "https://www.leg.state.nv.us/NRS/NRS-200.html"
    assert repaired["nv:chapter-200"]["repair_source"] == "repaired_from_linkless_row"
    assert repaired["nv:chapter-1"]["source_url"] == "https://www.leg.state.nv.us/NRS/NRS-001.html"
    assert "justia.com" not in repaired["nv:chapter-1"]["source_url"].lower()
    quarantines = classified["quarantines"]
    assert quarantines
    assert all(item["reason"] == NevadaScraper.LINKLESS_BUCKET_DISPOSITION for item in quarantines)
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any("Unlabeled" in item["label"] or "legacy snapshot" in item["label"] for item in quarantines)

    html_classified = scraper.classify_linkless_bucket_rows(
        NV_LINKLESS_HTML,
        page_url="https://www.leg.state.nv.us/NRS/",
    )
    html_repaired = {item["chapter"]: item for item in html_classified["repaired"]}
    assert "1" in html_repaired
    assert "200" in html_repaired
    assert "62A" in html_repaired
    assert html_repaired["62A"]["repair_source"] == "repaired_from_linkless_row"
    html_quarantines = html_classified["quarantines"]
    assert html_quarantines
    assert all(item["reason"] == NevadaScraper.MISSING_LINK_DISPOSITION for item in html_quarantines)
    assert any("appendix" in item["label"].lower() or "Phantom" in item["label"] for item in html_quarantines)


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
    if state == "NV":
        assert len(fetch.rows) > 2
        assert len(fetch.rows) == NevadaScraper.OFFICIAL_TITLE_COUNT
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


def test_declared_cohort_g_report_is_live_certified() -> None:
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-015-{state.lower()}")
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
        if state == "NV":
            assert int(receipt["row_count"]) > 2
            assert len(units) == NevadaScraper.OFFICIAL_TITLE_COUNT
            serialized_units = json.dumps(units)
            assert "leg.state.nv.us/NRS/" in serialized_units

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


def test_default_cohort_g_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_G.json"


def test_nevada_receipt_records_replaced_or_quarantined_linkless_material() -> None:
    payload = _load_declared_report()
    receipt = payload["jurisdiction_receipts"]["NV"]
    disposition = receipt["disposition"]
    quarantined = int(disposition.get("quarantined") or 0)
    discovered = int(disposition["discovered"])
    fetched = int(disposition["fetched"])
    excluded = int(disposition.get("excluded") or 0)
    failed_final = int(disposition.get("failed_final") or 0)
    assert discovered == fetched + excluded + quarantined + failed_final
    admitted_body = str(receipt.get("admitted_body") or "")
    assert "nv:title-" in admitted_body
    assert "leg.state.nv.us/NRS/" in admitted_body
    assert "justia.com" not in admitted_body.lower()
    frontier = receipt.get("frontier") or {}
    quarantines = list(frontier.get("nv_linkless_quarantines") or receipt.get("quarantines") or [])
    if quarantined:
        assert len(quarantines) == quarantined
        for item in quarantines:
            assert item["reason"] in {
                NevadaScraper.MISSING_LINK_DISPOSITION,
                NevadaScraper.LINKLESS_BUCKET_DISPOSITION,
            }
            assert str(item["unit_id"]).startswith("nv:")
            assert len(str(item["evidence_sha256"])) == 64

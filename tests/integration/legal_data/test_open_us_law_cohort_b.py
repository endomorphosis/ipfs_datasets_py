"""Integration certification for Open US Law scrape cohort B (CA, CO, CT, DE).

OUL-010: official adapters emit live ``fetch_official`` results, California
missing-link rows are repaired or typed, and the declared cohort report is
fail-closed live evidence. Fixture transports never complete the cohort.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping
from urllib.parse import urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    cohort_codes,
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import (
    CaliforniaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado import (
    ColoradoScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut import (
    ConnecticutScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import (
    DelawareScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
    StateScraperRegistry,
)


COHORT = "B"
TASK_ID = "OUL-010"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("CA", "CO", "CT", "DE")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_B.json")

OFFICIAL_HOST_SUFFIXES = {
    "CA": ("legislature.ca.gov",),
    "CO": ("leg.colorado.gov",),
    "CT": ("cga.ct.gov",),
    "DE": ("delcode.delaware.gov",),
}

SCRAPER_TYPES = {
    "CA": CaliforniaScraper,
    "CO": ColoradoScraper,
    "CT": ConnecticutScraper,
    "DE": DelawareScraper,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _host_allowed(url: str, state: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in OFFICIAL_HOST_SUFFIXES[state])


def _load_declared_report() -> Dict[str, Any]:
    path = _repo_root() / REPORT_RELPATH
    assert path.is_file(), f"declared cohort B report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "CA":
        return (
            "<html><body>"
            "<a href='/faces/codedisplayexpand.xhtml?tocCode=PEN'>Penal Code</a>"
            "<a href='/faces/codedisplayexpand.xhtml?tocCode=CIV'>Civil Code</a>"
            "<a href='/faces/codedisplayexpand.xhtml?tocCode=BPC'>Business and Professions Code</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "CO":
        return (
            "<html><body><div class='views-row'>"
            "<a href='/publications/18-1-101'>C.R.S. Title 18</a>"
            "</div></body></html>"
        ).encode("utf-8")
    if state == "CT":
        scraper = ConnecticutScraper("CT", "Connecticut")
        reserved = set(scraper.OFFICIAL_RESERVED_TITLE_NUMBERS)
        inactive = set(scraper.OFFICIAL_INACTIVE_TITLE_NUMBERS)
        rows = []
        for token in scraper.OFFICIAL_TITLE_NUMBERS:
            designation = f"<span class='toc_ttl_desig'>Title {token}</span>"
            if token in reserved:
                linked = designation
                name = "Reserved for future use"
            else:
                filename = scraper.official_title_url(token).rsplit("/", 1)[-1]
                linked = f"<a href='{filename}'>{designation}</a>"
                name = (
                    "All sections transferred or repealed"
                    if token in inactive
                    else "Current statutory provisions"
                )
            rows.append(
                f"<tr><td>{linked}</td>"
                f"<td><span class='toc_ttl_name'>{name}</span></td></tr>"
            )
        return (
            "<html><body><h2>Revised to January 1, 2025</h2>"
            "<a href='/2026/sup/titles.htm'>Readers should refer to the "
            "2026 Supplement</a><table>"
            + "".join(rows)
            + "</table></body></html>"
        ).encode()
    return (
        "<html><body>"
        "<a href='/title1/index.html'>Title 1</a>"
        "<a href='/title8/index.html'>Title 8</a>"
        "<a href='/title11/index.html'>Title 11</a>"
        "</body></html>"
    ).encode("utf-8")


def _compact_connecticut_supplement_html() -> bytes:
    scraper = ConnecticutScraper("CT", "Connecticut")
    rows = []
    for token in scraper.OFFICIAL_SUPPLEMENT_TITLE_NUMBERS:
        filename = scraper.official_supplement_title_url(token).rsplit("/", 1)[-1]
        rows.append(
            "<tr><td>"
            f"<a href='{filename}'><span class='toc_ttl_desig'>"
            f"Title {token}</span></a></td>"
            "<td><span class='toc_ttl_name'>Supplement changes</span></td></tr>"
        )
    return (
        "<html><body><h1>2026 Supplement to the General Statutes of "
        "Connecticut</h1><h2>Revised to January 1, 2026</h2>"
        "<a href='/current/pub/titles.htm'>This 2026 Supplement is intended "
        "to be used in conjunction with the General Statutes of Connecticut</a>"
        "<table>" + "".join(rows) + "</table></body></html>"
    ).encode()


def test_cohort_b_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_california_missing_link_rows_are_repaired_or_typed() -> None:
    scraper = CaliforniaScraper("CA", "California")
    repaired = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="CA",
            state_name="California",
            statute_id="Penal Code § 187",
            code_name="Penal Code",
            section_number="187",
            section_name="Murder defined",
            full_text=("Murder is the unlawful killing of a human being. " * 8),
            source_url="",
            official_cite="Cal. Penal Code § 187",
            metadata=StatuteMetadata(),
            structured_data={"law_code": "PEN"},
        )
    )
    assert repaired.source_url
    assert _host_allowed(repaired.source_url, "CA")
    assert "sectionNum=187" in repaired.source_url
    assert repaired.structured_data["source_link_disposition"] == "repaired_official_leginfo"

    already_official = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="CA",
            state_name="California",
            statute_id="Civil Code § 1",
            code_name="Civil Code",
            section_number="1",
            section_name="Title",
            full_text=("This code shall be known as the Civil Code. " * 8),
            source_url=(
                "https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml"
                "?lawCode=CIV&sectionNum=1."
            ),
            official_cite="Cal. Civil Code § 1",
            metadata=StatuteMetadata(),
            structured_data={"law_code": "CIV"},
        )
    )
    assert already_official.structured_data["source_link_disposition"] == "official"

    quarantined = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="CA",
            state_name="California",
            statute_id="unknown",
            code_name="Unknown Code",
            section_number="",
            section_name="Untitled",
            full_text=("Row without an official code family or section number. " * 6),
            source_url="",
            official_cite="",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert quarantined.structured_data["source_link_disposition"] == "typed_quarantine"
    assert (
        quarantined.structured_data["quarantine_reason"]
        == CaliforniaScraper.MISSING_LINK_QUARANTINE_REASON
    )


@pytest.mark.parametrize("state", EXPECTED_STATES)
def test_fetch_official_is_live_and_exhaustive(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    scraper_cls = SCRAPER_TYPES[state]
    scraper = scraper_cls(state, state)
    monkeypatch.setattr(
        scraper,
        "_official_http_get",
        lambda url, timeout_seconds=30: (
            _compact_connecticut_supplement_html()
            if state == "CT" and "/2026/sup/" in url
            else _compact_official_html(state)
        ),
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
    for row in fetch.rows:
        assert isinstance(row, Mapping)
        assert row.get("canonical_key")
        assert _host_allowed(str(row.get("source_url") or ""), state)
        assert str(row.get("source_link_disposition") or "") in {
            "official",
            "repaired_official_leginfo",
        }


def test_california_official_catalog_repairs_missing_code_links() -> None:
    scraper = CaliforniaScraper("CA", "California")
    rows = scraper.enumerate_official_catalog(b"", page_url=scraper.OFFICIAL_ENTRY_URL)
    assert len(rows) == len(CaliforniaScraper.CODE_TYPE_MAP)
    assert {row["code_type"] for row in rows} == set(CaliforniaScraper.CODE_TYPE_MAP.values())
    for row in rows:
        assert _host_allowed(str(row["source_url"]), "CA")
        assert row["source_link_disposition"] in {"official", "repaired_official_leginfo"}


def test_declared_cohort_b_report_is_live_certified() -> None:
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-010-{state.lower()}")
        assert verdict.complete is True, (
            f"{state} completeness failed: {[item.detail for item in verdict.findings]}"
        )
        if state == "CA":
            units = json.loads(receipt["admitted_body"]).get("units") or []
            dispositions = {str(item.get("source_link_disposition") or "") for item in units}
            assert dispositions <= {"official", "repaired_official_leginfo", "typed_quarantine"}
            assert "typed_quarantine" in dispositions or "repaired_official_leginfo" in dispositions or "official" in dispositions

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


def test_default_cohort_b_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_B.json"

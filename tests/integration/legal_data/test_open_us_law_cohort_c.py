"""Integration certification for Open US Law scrape cohort C (FL, GA, HI, ID).

OUL-011: official adapters emit live ``fetch_official`` results, Florida,
Hawaii, and Idaho missing-link rows are repaired or typed, the absent
contaminated Georgia bucket object is replaced from official clean text,
and the declared cohort report is fail-closed live evidence. Fixture
transports never complete the cohort.
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida import (
    FloridaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import (
    GeorgiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii import (
    HawaiiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.idaho import (
    IdahoScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
    StateScraperRegistry,
)


COHORT = "C"
TASK_ID = "OUL-011"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("FL", "GA", "HI", "ID")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_C.json")

OFFICIAL_HOST_SUFFIXES = {
    "FL": ("leg.state.fl.us",),
    "GA": ("legis.ga.gov",),
    "HI": ("capitol.hawaii.gov",),
    "ID": ("legislature.idaho.gov",),
}

SCRAPER_TYPES = {
    "FL": FloridaScraper,
    "GA": GeorgiaScraper,
    "HI": HawaiiScraper,
    "ID": IdahoScraper,
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

GA_CONTAMINATED_BUCKET_HTML = """
<html>
  <nav>Skip to main content | Site Map | Privacy Policy</nav>
  <body>
    <a href="/legislation/georgia-code/title-1">Title 1 General Provisions</a>
    <a href="/legislation/georgia-code/title-16">Title 16 Crimes and Offenses</a>
    <a href="https://law.justia.com/codes/georgia/title-16/">Title 16 Justia mirror</a>
    <td>Georgia bucket phantom chapter without a recoverable official identifier</td>
    <div class="footer">Copyright © Georgia General Assembly Footer navigation</div>
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
    assert path.is_file(), f"declared cohort C report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "FL":
        return (
            "<html><body>"
            "<a href='/Statutes/index.cfm?App_mode=Display_Index&Title_Request=I'>Title I Construction of Statutes</a>"
            "<a href='/Statutes/index.cfm?App_mode=Display_Index&Title_Request=VI'>Title VI Civil Practice</a>"
            "<a href='/Statutes/index.cfm?App_mode=Display_Index&Title_Request=XLVI'>Title XLVI Crimes</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "GA":
        return GA_CONTAMINATED_BUCKET_HTML.encode("utf-8")
    if state == "HI":
        return (
            "<html><body>"
            "<a href='/hrscurrent/?hrsTitle=1'>Title 1 General Provisions</a>"
            "<a href='/hrscurrent/?hrsTitle=18'>Title 18 Education</a>"
            "<a href='/hrscurrent/?hrsTitle=37'>Title 37 Hawaii Penal Code</a>"
            "</body></html>"
        ).encode("utf-8")
    return (
        "<html><body>"
        "<a href='/statutesrules/idstat/title1/'>Title 1 Courts and Court Officials</a>"
        "<a href='/statutesrules/idstat/title18/'>Title 18 Crimes and Punishments</a>"
        "<a href='/statutesrules/idstat/title67/'>Title 67 State Government</a>"
        "</body></html>"
    ).encode("utf-8")


def test_cohort_c_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_florida_missing_link_rows_are_repaired_or_typed() -> None:
    scraper = FloridaScraper("FL", "Florida")
    repaired = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="FL",
            state_name="Florida",
            statute_id="Fla. Stat. § 782.04",
            code_name="Florida Statutes",
            section_number="782.04",
            section_name="Murder",
            full_text=("The unlawful killing of a human being. " * 8),
            source_url="",
            official_cite="Fla. Stat. § 782.04",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert repaired.source_url
    assert _host_allowed(repaired.source_url, "FL")
    assert "782.04" in repaired.source_url
    assert repaired.structured_data["source_link_disposition"] == "repaired_official_flleg"

    already_official = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="FL",
            state_name="Florida",
            statute_id="Fla. Stat. § 1.01",
            code_name="Florida Statutes",
            section_number="1.01",
            section_name="Definitions",
            full_text=("In construing these statutes. " * 8),
            source_url=(
                "https://www.leg.state.fl.us/Statutes/index.cfm"
                "?App_mode=Display_Statute&Statute=1.01"
            ),
            official_cite="Fla. Stat. § 1.01",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert already_official.structured_data["source_link_disposition"] == "official"

    quarantined = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="FL",
            state_name="Florida",
            statute_id="unknown",
            code_name="Unknown Code",
            section_number="",
            section_name="Untitled",
            full_text=("Row without an official section number. " * 6),
            source_url="",
            official_cite="",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert quarantined.structured_data["source_link_disposition"] == "typed_quarantine"
    assert (
        quarantined.structured_data["quarantine_reason"]
        == FloridaScraper.MISSING_LINK_QUARANTINE_REASON
    )


def test_hawaii_missing_link_rows_are_repaired_or_typed() -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    repaired = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="HI",
            state_name="Hawaii",
            statute_id="Haw. Rev. Stat. § 707-701",
            code_name="Hawaii Revised Statutes",
            section_number="707-701",
            section_name="Murder in the first degree",
            full_text=("A person commits the offense of murder. " * 8),
            source_url="",
            official_cite="Haw. Rev. Stat. § 707-701",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert repaired.source_url
    assert _host_allowed(repaired.source_url, "HI")
    assert "707-701" in repaired.source_url
    assert repaired.structured_data["source_link_disposition"] == "repaired_official_hicapitol"

    already_official = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="HI",
            state_name="Hawaii",
            statute_id="Haw. Rev. Stat. § 1-1",
            code_name="Hawaii Revised Statutes",
            section_number="1-1",
            section_name="Common law of the State",
            full_text=("The common law of England. " * 8),
            source_url="https://www.capitol.hawaii.gov/hrscurrent/?section=1-1",
            official_cite="Haw. Rev. Stat. § 1-1",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert already_official.structured_data["source_link_disposition"] == "official"

    quarantined = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="HI",
            state_name="Hawaii",
            statute_id="unknown",
            code_name="Unknown Code",
            section_number="",
            section_name="Untitled",
            full_text=("Row without an official section number. " * 6),
            source_url="",
            official_cite="",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert quarantined.structured_data["source_link_disposition"] == "typed_quarantine"
    assert (
        quarantined.structured_data["quarantine_reason"]
        == HawaiiScraper.MISSING_LINK_QUARANTINE_REASON
    )


def test_idaho_missing_link_rows_are_repaired_or_typed() -> None:
    scraper = IdahoScraper("ID", "Idaho")
    repaired = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="ID",
            state_name="Idaho",
            statute_id="Idaho Code § 18-4001",
            code_name="Idaho Statutes",
            section_number="18-4001",
            section_name="Murder defined",
            full_text=("Murder is the unlawful killing of a human being. " * 8),
            source_url="",
            official_cite="Idaho Code § 18-4001",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert repaired.source_url
    assert _host_allowed(repaired.source_url, "ID")
    assert "18-4001" in repaired.source_url
    assert repaired.structured_data["source_link_disposition"] == "repaired_official_idleg"

    already_official = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="ID",
            state_name="Idaho",
            statute_id="Idaho Code § 1-101",
            code_name="Idaho Statutes",
            section_number="1-101",
            section_name="Courts of justice",
            full_text=("The courts of justice of this state. " * 8),
            source_url="https://legislature.idaho.gov/statutesrules/idstat/title1/",
            official_cite="Idaho Code § 1-101",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert already_official.structured_data["source_link_disposition"] == "official"

    quarantined = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="ID",
            state_name="Idaho",
            statute_id="unknown",
            code_name="Unknown Code",
            section_number="",
            section_name="Untitled",
            full_text=("Row without an official section number. " * 6),
            source_url="",
            official_cite="",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert quarantined.structured_data["source_link_disposition"] == "typed_quarantine"
    assert (
        quarantined.structured_data["quarantine_reason"]
        == IdahoScraper.MISSING_LINK_QUARANTINE_REASON
    )


def test_georgia_contaminated_bucket_is_replaced_from_official_clean_text() -> None:
    scraper = GeorgiaScraper("GA", "Georgia")
    classified = scraper.replace_contaminated_bucket_object(
        GA_CONTAMINATED_BUCKET_HTML,
        page_url="https://www.legis.ga.gov/legislation/georgia-code",
    )
    replaced = {item["title_number"]: item for item in classified["replaced"]}
    assert replaced["1"]["source_url"] == "https://www.legis.ga.gov/legislation/georgia-code/title-1"
    assert replaced["16"]["source_url"] == "https://www.legis.ga.gov/legislation/georgia-code/title-16"
    assert all(_host_allowed(item["source_url"], "GA") for item in classified["replaced"])
    for item in classified["replaced"]:
        lowered = str(item["text"]).lower()
        assert not any(marker in lowered for marker in NAVIGATION_FOOTER_MARKERS)
        assert item["source_link_disposition"] in {"official", "official_replacement"}
        assert item["contaminated_replaced"] is True

    quarantines = classified["quarantines"]
    assert quarantines
    assert all(
        item["reason"] == GeorgiaScraper.CONTAMINATED_BUCKET_REPLACEMENT_REASON
        for item in quarantines
    )
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any("phantom" in item["label"].lower() for item in quarantines)

    from_seeds = scraper.replace_contaminated_bucket_object(
        list(GeorgiaScraper.DEFAULT_CONTAMINATED_BUCKET_SEEDS)
    )
    replaced_seeds = {item["title_number"]: item for item in from_seeds["replaced"]}
    assert replaced_seeds["1"]["source_url"].startswith("https://www.legis.ga.gov/legislation/georgia-code/")
    assert replaced_seeds["16"]["repair_source"] == "official_replacement"
    assert any(
        item["reason"] == GeorgiaScraper.CONTAMINATED_BUCKET_REPLACEMENT_REASON
        for item in from_seeds["quarantines"]
    )
    assert any(
        "without a recoverable" in item["label"] or item["unit_id"].startswith("ga:bucket")
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
    if state == "FL":
        assert len(fetch.rows) == len(FloridaScraper.OFFICIAL_TITLES)
    if state == "GA":
        assert len(fetch.rows) == len(GeorgiaScraper.OFFICIAL_TITLES)
        assert fetch.frontier.get("ga_contaminated_bucket_replaced") is True
        assert getattr(scraper, "last_official_quarantines", None)
        assert any(
            item["reason"] == GeorgiaScraper.CONTAMINATED_BUCKET_REPLACEMENT_REASON
            for item in scraper.last_official_quarantines
        )
    if state == "HI":
        assert len(fetch.rows) == len(HawaiiScraper.OFFICIAL_TITLES)
    if state == "ID":
        assert len(fetch.rows) == len(IdahoScraper.OFFICIAL_TITLES)
    for row in fetch.rows:
        assert isinstance(row, Mapping)
        assert row.get("canonical_key")
        assert _host_allowed(str(row.get("source_url") or ""), state)
        assert str(row.get("source_link_disposition") or "") in {
            "official",
            "repaired_official_flleg",
            "repaired_official_galeg",
            "repaired_official_hicapitol",
            "repaired_official_idleg",
            "official_replacement",
        }
        lowered = str(row.get("source_url") or "").lower()
        assert "justia.com" not in lowered
        assert "unicourt" not in lowered
        if state == "GA":
            text = str(row.get("text") or "").lower()
            assert not any(marker in text for marker in NAVIGATION_FOOTER_MARKERS)
            assert row.get("contaminated_replaced") is True


def test_official_catalogs_repair_missing_code_links() -> None:
    florida = FloridaScraper("FL", "Florida")
    fl_rows = florida.enumerate_official_catalog(b"", page_url=florida.OFFICIAL_ENTRY_URL)
    assert len(fl_rows) == len(FloridaScraper.OFFICIAL_TITLES)
    assert {row["title_number"] for row in fl_rows} == {
        number for number, _roman, _name in FloridaScraper.OFFICIAL_TITLES
    }
    for row in fl_rows:
        assert _host_allowed(str(row["source_url"]), "FL")
        assert row["source_link_disposition"] in {"official", "repaired_official_flleg"}

    hawaii = HawaiiScraper("HI", "Hawaii")
    hi_rows = hawaii.enumerate_official_catalog(b"", page_url=hawaii.OFFICIAL_ENTRY_URL)
    assert len(hi_rows) == len(HawaiiScraper.OFFICIAL_TITLES)
    for row in hi_rows:
        assert _host_allowed(str(row["source_url"]), "HI")
        assert row["source_link_disposition"] in {"official", "repaired_official_hicapitol"}


def test_declared_cohort_c_report_is_live_certified() -> None:
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-011-{state.lower()}")
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
        if state == "FL":
            dispositions = {str(item.get("source_link_disposition") or "") for item in units}
            assert dispositions <= {"official", "repaired_official_flleg", "typed_quarantine"}
            assert len(units) == len(FloridaScraper.OFFICIAL_TITLES)
        if state == "GA":
            catalog = json.loads(receipt["admitted_body"])
            assert catalog.get("contaminated_bucket_replaced") is True
            assert catalog.get("replacement_source") == "official_clean_text"
            quarantines = catalog.get("quarantines") or []
            assert quarantines
            assert all(
                item["reason"] == GeorgiaScraper.CONTAMINATED_BUCKET_REPLACEMENT_REASON
                for item in quarantines
            )
            assert len(units) == len(GeorgiaScraper.OFFICIAL_TITLES)
            for item in units:
                text = str(item.get("text") or "").lower()
                assert not any(marker in text for marker in NAVIGATION_FOOTER_MARKERS)
        if state == "HI":
            assert len(units) == len(HawaiiScraper.OFFICIAL_TITLES)
        if state == "ID":
            assert len(units) == len(IdahoScraper.OFFICIAL_TITLES)

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


def test_default_cohort_c_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_C.json"

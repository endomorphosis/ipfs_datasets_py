"""Integration certification for Open US Law scrape cohort A (AL, AK, AZ, AR).

OUL-009: official adapters emit live ``fetch_official`` results, Alabama and
Alaska missing-link rows are repaired or typed, Arkansas bucket seed rows
remain quarantined until official replacement is proven, and the declared
cohort report is fail-closed live evidence. Fixture transports never
complete the cohort.
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama import (
    AlabamaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska import (
    AlaskaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arizona import (
    ArizonaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
    ArkansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
    StateScraperRegistry,
)


COHORT = "A"
TASK_ID = "OUL-009"
GOAL_ID = "OUL-G021"
PROGRAM_ID = "open-us-law-reindex-v1"
EXPECTED_STATES = ("AL", "AK", "AZ", "AR")
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_A.json")

OFFICIAL_HOST_SUFFIXES = {
    "AL": ("legislature.state.al.us",),
    "AK": ("akleg.gov", "legis.state.ak.us"),
    "AZ": ("azleg.gov",),
    "AR": ("arkleg.state.ar.us",),
}

SCRAPER_TYPES = {
    "AL": AlabamaScraper,
    "AK": AlaskaScraper,
    "AZ": ArizonaScraper,
    "AR": ArkansasScraper,
}

SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)

AR_BUCKET_SEED_HTML = """
<html>
  <body>
    <a href="/ArkansasCode/?title=1">Title 1 General Provisions</a>
    <a href="/ArkansasCode/?title=5">Title 5 Criminal Offenses</a>
    <a href="https://law.justia.com/codes/arkansas/title-6/">Title 6 Education</a>
    <td>Arkansas bucket seed phantom chapter without a recoverable official identifier</td>
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
    assert path.is_file(), f"declared cohort A report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compact_official_html(state: str) -> bytes:
    if state == "AL":
        return (
            "<html><body>"
            "<a href='/code-of-alabama?title=1'>Title 1 General Provisions</a>"
            "<a href='/code-of-alabama?title=13A'>Title 13A Criminal Code</a>"
            "<a href='/code-of-alabama?title=45'>Title 45 Local Laws</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "AK":
        return (
            "<html><body>"
            "<a href='/basis/statutes.asp#01'>Title 1 General Provisions</a>"
            "<a href='/basis/statutes.asp#11'>Title 11 Criminal Law</a>"
            "<a href='/basis/statutes.asp#47'>Title 47 Welfare</a>"
            "</body></html>"
        ).encode("utf-8")
    if state == "AZ":
        return (
            "<html><body>"
            "<a href='/arsDetail/?title=1'>Title 1 General Provisions</a>"
            "<a href='/arsDetail/?title=13'>Title 13 Criminal Code</a>"
            "<a href='/arsDetail/?title=49'>Title 49 The Environment</a>"
            "</body></html>"
        ).encode("utf-8")
    return AR_BUCKET_SEED_HTML.encode("utf-8")


def test_cohort_a_jurisdiction_set_is_exact() -> None:
    assert cohort_codes(COHORT) == EXPECTED_STATES
    for code in EXPECTED_STATES:
        scraper_cls = StateScraperRegistry.get_scraper(code)
        assert scraper_cls is SCRAPER_TYPES[code]
        assert callable(getattr(scraper_cls, "fetch_official", None))


def test_alabama_missing_link_rows_are_repaired_or_typed() -> None:
    scraper = AlabamaScraper("AL", "Alabama")
    repaired = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="AL",
            state_name="Alabama",
            statute_id="Ala. Code § 13A-6-2",
            code_name="Alabama Code",
            section_number="13A-6-2",
            section_name="Murder",
            full_text=("A person commits the crime of murder if he or she. " * 8),
            source_url="",
            official_cite="Ala. Code § 13A-6-2",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert repaired.source_url
    assert _host_allowed(repaired.source_url, "AL")
    assert "section=13A-6-2" in repaired.source_url
    assert repaired.structured_data["source_link_disposition"] == "repaired_official_alison"

    already_official = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="AL",
            state_name="Alabama",
            statute_id="Ala. Code § 1-1-1",
            code_name="Alabama Code",
            section_number="1-1-1",
            section_name="Short title",
            full_text=("This Code shall be known as the Code of Alabama. " * 8),
            source_url="https://alison.legislature.state.al.us/code-of-alabama?section=1-1-1",
            official_cite="Ala. Code § 1-1-1",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert already_official.structured_data["source_link_disposition"] == "official"

    quarantined = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="AL",
            state_name="Alabama",
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
        == AlabamaScraper.MISSING_LINK_QUARANTINE_REASON
    )


def test_alaska_missing_link_rows_are_repaired_or_typed() -> None:
    scraper = AlaskaScraper("AK", "Alaska")
    repaired = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="AK",
            state_name="Alaska",
            statute_id="AK-11.41.100",
            code_name="Alaska Statutes",
            section_number="11.41.100",
            section_name="Murder in the first degree",
            full_text=("A person commits the crime of murder in the first degree. " * 6),
            source_url="",
            official_cite="Alaska Stat. § 11.41.100",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert repaired.source_url
    assert _host_allowed(repaired.source_url, "AK")
    assert "11.41.100" in repaired.source_url
    assert repaired.structured_data["source_link_disposition"] == "repaired_official_akleg"

    already_official = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="AK",
            state_name="Alaska",
            statute_id="AK-01.10.010",
            code_name="Alaska Statutes",
            section_number="01.10.010",
            section_name="Short title",
            full_text=("This title may be cited as the Alaska Statutes. " * 6),
            source_url="https://www.akleg.gov/basis/statutes.asp#01.10.010",
            official_cite="Alaska Stat. § 01.10.010",
            metadata=StatuteMetadata(),
            structured_data={},
        )
    )
    assert already_official.structured_data["source_link_disposition"] == "official"

    quarantined = scraper.repair_or_type_missing_source_link(
        NormalizedStatute(
            state_code="AK",
            state_name="Alaska",
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
        == AlaskaScraper.MISSING_LINK_QUARANTINE_REASON
    )


def test_arkansas_bucket_seed_rows_remain_quarantined_until_official_replacement() -> None:
    scraper = ArkansasScraper("AR", "Arkansas")
    classified = scraper.classify_bucket_seed_rows(
        AR_BUCKET_SEED_HTML,
        page_url="https://www.arkleg.state.ar.us/ArkansasCode/",
    )
    repaired = {item["title_number"]: item for item in classified["repaired"]}
    assert repaired["1"]["source_url"] == "https://www.arkleg.state.ar.us/ArkansasCode/?title=1"
    assert repaired["5"]["source_url"] == "https://www.arkleg.state.ar.us/ArkansasCode/?title=5"
    assert repaired["6"]["source_url"] == "https://www.arkleg.state.ar.us/ArkansasCode/?title=6"
    assert repaired["6"]["repair_source"] == "official_replacement"
    assert all(_host_allowed(item["source_url"], "AR") for item in classified["repaired"])

    quarantines = classified["quarantines"]
    assert quarantines
    assert all(
        item["reason"] == ArkansasScraper.BUCKET_SEED_QUARANTINE_REASON for item in quarantines
    )
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any("phantom" in item["label"].lower() for item in quarantines)

    from_seeds = scraper.classify_bucket_seed_rows(list(ArkansasScraper.DEFAULT_BUCKET_SEED_ROWS))
    replaced = {item["title_number"]: item for item in from_seeds["repaired"]}
    assert replaced["1"]["source_url"].startswith("https://www.arkleg.state.ar.us/ArkansasCode/")
    assert any(
        item["reason"] == ArkansasScraper.BUCKET_SEED_QUARANTINE_REASON
        for item in from_seeds["quarantines"]
    )
    assert any(
        "without an official host" in item["label"] or item["unit_id"].startswith("ar:bucket")
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
    if state == "AL":
        assert len(fetch.rows) == len(AlabamaScraper.OFFICIAL_TITLES)
    if state == "AK":
        assert len(fetch.rows) == len(AlaskaScraper.OFFICIAL_TITLES)
    if state == "AZ":
        assert len(fetch.rows) == len(ArizonaScraper.OFFICIAL_TITLES)
    if state == "AR":
        assert len(fetch.rows) == len(ArkansasScraper.OFFICIAL_TITLES)
        assert getattr(scraper, "last_official_quarantines", None)
        assert any(
            item["reason"] == ArkansasScraper.BUCKET_SEED_QUARANTINE_REASON
            for item in scraper.last_official_quarantines
        )
    for row in fetch.rows:
        assert isinstance(row, Mapping)
        assert row.get("canonical_key")
        assert _host_allowed(str(row.get("source_url") or ""), state)
        assert str(row.get("source_link_disposition") or "") in {
            "official",
            "repaired_official_alison",
            "repaired_official_akleg",
            "repaired_official_azleg",
            "repaired_official_arkleg",
            "official_replacement",
        }
        lowered = str(row.get("source_url") or "").lower()
        assert "justia.com" not in lowered
        assert "unicourt" not in lowered


def test_official_catalogs_repair_missing_code_links() -> None:
    alabama = AlabamaScraper("AL", "Alabama")
    al_rows = alabama.enumerate_official_catalog(b"", page_url=alabama.OFFICIAL_ENTRY_URL)
    assert len(al_rows) == len(AlabamaScraper.OFFICIAL_TITLES)
    assert {row["title_number"] for row in al_rows} == {
        number for number, _name in AlabamaScraper.OFFICIAL_TITLES
    }
    for row in al_rows:
        assert _host_allowed(str(row["source_url"]), "AL")
        assert row["source_link_disposition"] in {"official", "repaired_official_alison"}

    alaska = AlaskaScraper("AK", "Alaska")
    ak_rows = alaska.enumerate_official_catalog(b"", page_url=alaska.OFFICIAL_ENTRY_URL)
    assert len(ak_rows) == len(AlaskaScraper.OFFICIAL_TITLES)
    for row in ak_rows:
        assert _host_allowed(str(row["source_url"]), "AK")
        assert row["source_link_disposition"] in {"official", "repaired_official_akleg"}


def test_declared_cohort_a_report_is_live_certified() -> None:
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"oul-009-{state.lower()}")
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
        if state == "AL":
            dispositions = {str(item.get("source_link_disposition") or "") for item in units}
            assert dispositions <= {"official", "repaired_official_alison", "typed_quarantine"}
        if state == "AR":
            catalog = json.loads(receipt["admitted_body"])
            assert "quarantines" in catalog
            quarantines = catalog.get("quarantines") or []
            assert quarantines
            assert all(
                item["reason"] == ArkansasScraper.BUCKET_SEED_QUARANTINE_REASON
                for item in quarantines
            )
            assert len(units) == len(ArkansasScraper.OFFICIAL_TITLES)

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


def test_default_cohort_a_report_path_is_declared_output() -> None:
    path = default_cohort_report_path(COHORT, _repo_root())
    assert path == (_repo_root() / REPORT_RELPATH).resolve()
    assert path.name == "cohort_A.json"

"""Integration certification for Open US Law scrape cohort E (KY, LA, ME, MD).

OUL-013: each jurisdiction has an exhaustive official-source receipt. Louisiana
missing-link rows are repaired to official Law.aspx URLs or quarantined with a
typed disposition. The committed cohort report is the live evidence; this
module stays offline-safe and never treats fixtures as completion.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    COHORT_JURISDICTIONS,
    cohort_task_id,
    evaluate_prior_receipt,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    check_declared_cohort_report,
    default_cohort_report_path,
    is_cohort_evidence_payload,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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
    root = _repo_root()
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
_kentucky_mod = _load_state_module("kentucky")
_louisiana_mod = _load_state_module("louisiana")
_maine_mod = _load_state_module("maine")
_maryland_mod = _load_state_module("maryland")

KentuckyScraper = _kentucky_mod.KentuckyScraper
LouisianaScraper = _louisiana_mod.LouisianaScraper
MaineScraper = _maine_mod.MaineScraper
MarylandScraper = _maryland_mod.MarylandScraper
StateScraperRegistry = _registry_mod.StateScraperRegistry


COHORT = "E"
EXPECTED_STATES = COHORT_JURISDICTIONS[COHORT]
TASK_ID = "OUL-013"
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_E.json")

SCRAPER_TYPES = {
    "KY": KentuckyScraper,
    "LA": LouisianaScraper,
    "ME": MaineScraper,
    "MD": MarylandScraper,
}

OFFICIAL_DOMAINS = {
    "KY": ("apps.legislature.ky.gov", "legislature.ky.gov"),
    "LA": ("legis.la.gov", "www.legis.la.gov"),
    "ME": ("legislature.maine.gov",),
    "MD": ("mgaleg.maryland.gov",),
}

LA_MISSING_LINK_HTML = """
<html>
  <body>
    <a href="Law.aspx?d=100114">RS 1:1 Official sources of law</a>
    <a href="/Legis/Law.aspx?d=100115">RS 1:2 Interpretation</a>
    <span data-d="100117">RS 1:3 Construction of revised statutes</span>
    <td>Title 99 Phantom chapter without an official source link</td>
    <a href="javascript:void(0)" onclick="openLaw('d=100122')">RS 1:8 Repealed</a>
  </body>
</html>
"""


def _load_report() -> dict[str, Any]:
    path = _repo_root() / REPORT_RELPATH
    assert path.is_file(), f"declared cohort E report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_cohort_e_adapters_are_registered_with_fetch_official() -> None:
    assert EXPECTED_STATES == ("KY", "LA", "ME", "MD")
    assert cohort_task_id("KY") == TASK_ID
    for code, scraper_cls in SCRAPER_TYPES.items():
        registered = StateScraperRegistry.get_scraper(code)
        assert registered is scraper_cls
        scraper = scraper_cls(code, code)
        assert callable(getattr(scraper, "fetch_official", None))


KY_INDEX_HTML = """
<html><body>
<a href="/law/statutes/chapter.aspx?id=1">CHAPTER 1 Sovereignty and Jurisdiction</a>
<a href="/law/statutes/chapter.aspx?id=2">CHAPTER 2 Citizenship</a>
<a href="/law/statutes/chapter.aspx?id=3">CHAPTER 3 Grants and Patents</a>
<a href="/law/statutes/statute.aspx?id=9">1.010 Definitions</a>
</body></html>
"""

ME_INDEX_HTML = """
<html><body>
<a href="/statutes/1/title1ch0sec0.html">Title 1 General Provisions</a>
<a href="/statutes/14/title14ch0sec0.html">Title 14 Court Procedure -- Civil</a>
<a href="/statutes/17-A/title17-Ach0sec0.html">Title 17-A Maine Criminal Code</a>
</body></html>
"""

MD_ARTICLES = [
    {"DisplayText": "Agriculture (AG)", "Value": "gag"},
    {"DisplayText": "Criminal Law (CR)", "Value": "gcr"},
    {"DisplayText": "State Government (SG)", "Value": "gsg"},
]


def test_official_index_parsers_emit_closed_catalog_units() -> None:
    ky = KentuckyScraper("KY", "Kentucky")
    ky_units = ky._parse_official_chapter_index(
        KY_INDEX_HTML, "https://apps.legislature.ky.gov/law/statutes/"
    )
    assert [item["canonical_key"] for item in ky_units] == [
        "ky:chapter-1",
        "ky:chapter-2",
        "ky:chapter-3",
    ]
    assert all("apps.legislature.ky.gov/law/statutes/chapter.aspx" in item["source_url"] for item in ky_units)

    me = MaineScraper("ME", "Maine")
    me_units = me._parse_official_title_index(
        ME_INDEX_HTML, "https://legislature.maine.gov/statutes/"
    )
    assert [item["canonical_key"] for item in me_units] == [
        "me:title-1",
        "me:title-14",
        "me:title-17-a",
    ]
    assert all(item["source_url"].startswith("https://legislature.maine.gov/statutes/") for item in me_units)

    md = MarylandScraper("MD", "Maryland")
    md_units = md._parse_official_article_index(MD_ARTICLES)
    assert [item["canonical_key"] for item in md_units] == [
        "md:article-ag",
        "md:article-cr",
        "md:article-sg",
    ]
    assert all("mgaleg.maryland.gov" in item["source_url"] for item in md_units)


def test_louisiana_missing_links_are_repaired_or_quarantined() -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    classified = scraper.classify_official_index_rows(
        LA_MISSING_LINK_HTML,
        page_url="https://legis.la.gov/legis/Laws.aspx",
    )
    repaired = {item["law_id"]: item for item in classified["repaired"]}
    assert "100114" in repaired
    assert repaired["100114"]["source_url"] == "https://legis.la.gov/Legis/Law.aspx?d=100114"
    assert "100115" in repaired
    assert "100117" in repaired
    assert repaired["100117"]["repair_source"] == "repaired_from_linkless_row"
    assert "100122" in repaired
    quarantines = classified["quarantines"]
    assert quarantines
    assert all(item["reason"] == LouisianaScraper.MISSING_LINK_DISPOSITION for item in quarantines)
    assert all(len(item["evidence_sha256"]) == 64 for item in quarantines)
    assert any("Phantom chapter" in item["label"] for item in quarantines)


def test_committed_cohort_e_report_is_live_certified() -> None:
    path = _repo_root() / REPORT_RELPATH
    assert path == default_cohort_report_path("E", _repo_root())
    payload = _load_report()
    assert is_cohort_evidence_payload(payload)
    assert payload["cohort"] == COHORT
    assert payload["task_id"] == TASK_ID
    assert payload["jurisdictions"] == list(EXPECTED_STATES)
    assert payload["cohort_complete"] is True
    assert payload["fixture_execution"] is False
    assert payload["fixture_proves_cohort_completion"] is False
    assert payload["authorizing_for_publication"] is False
    assert payload["status"] in {"success", "passed"}
    assert payload["certification"]["raw_bytes_checked"] is True

    report = check_declared_cohort_report(
        path,
        cohort=COHORT,
        require_live=True,
        repo_root=_repo_root(),
    )
    assert report["status"] == "passed"
    assert report["cohort_complete"] is True
    assert report["fixture_proves_cohort_completion"] is False


def test_all_cohort_e_receipts_are_exhaustive_and_official() -> None:
    for code in EXPECTED_STATES:
        test_each_cohort_e_receipt_is_exhaustive_and_official(code)


def test_each_cohort_e_receipt_is_exhaustive_and_official(code: str) -> None:
    payload = _load_report()
    receipt = payload["jurisdiction_receipts"][code]
    assert receipt["jurisdiction"] == code
    assert receipt["official_source"] is True
    assert receipt["source_authority_class"] == "official"
    assert str(receipt["source_domain"]).lower() in {
        item.lower() for item in OFFICIAL_DOMAINS[code]
    } or any(
        str(receipt["source_domain"]).lower().endswith("." + item)
        for item in OFFICIAL_DOMAINS[code]
    )
    assert receipt["transport"]["fixture"] is False
    assert receipt["transport"]["kind"] == "live_https"
    assert receipt["sample_cap"] in {None, 0, False}
    assert receipt["runtime_caps"] in {None, 0, False} or receipt["runtime_caps"] == {}
    assert receipt["mode"] == "full"
    assert int(receipt["row_count"]) >= 3
    assert int(receipt["disposition"]["fetched"]) >= 3
    assert receipt["frontier"]["closed"] is True
    assert receipt["frontier"]["enumerator_closed"] is True
    assert receipt["frontier"]["expected_index_units"] == receipt["frontier"]["visited_index_units"]
    assert receipt["frontier"]["expected_index_units"] == receipt["row_count"]
    assert receipt["boundary_probes"]["first_probe_ok"] is True
    assert receipt["boundary_probes"]["last_probe_ok"] is True
    admitted = receipt.get("admitted_body")
    assert isinstance(admitted, str) and admitted.strip()
    certification = payload["certification"]["jurisdictions"][code]
    assert certification["ok"] is True
    assert certification["raw_bytes_checked"] is True
    assert certification["fixture"] is False
    admission = evaluate_prior_receipt(receipt)
    assert admission.accepted is True
    assert admission.byte_verification is not None
    assert admission.byte_verification.raw_bytes_checked is True
    assert admission.frontier_verification is not None
    assert admission.frontier_verification.closed is True


def test_louisiana_receipt_records_typed_missing_link_disposition() -> None:
    payload = _load_report()
    receipt = payload["jurisdiction_receipts"]["LA"]
    disposition = receipt["disposition"]
    quarantined = int(disposition.get("quarantined") or 0)
    discovered = int(disposition["discovered"])
    fetched = int(disposition["fetched"])
    excluded = int(disposition.get("excluded") or 0)
    failed_final = int(disposition.get("failed_final") or 0)
    assert discovered == fetched + excluded + quarantined + failed_final
    if quarantined:
        quarantines = receipt.get("quarantines") or []
        assert len(quarantines) == quarantined
        for item in quarantines:
            assert item["reason"] == LouisianaScraper.MISSING_LINK_DISPOSITION
            assert str(item["unit_id"]).startswith("la:")
            assert len(str(item["evidence_sha256"])) == 64
    # Every admitted LA row must have a repaired official Law.aspx source.
    admitted_body = str(receipt.get("admitted_body") or "")
    assert "la:law-" in admitted_body
    assert "legis.la.gov/Legis/Law.aspx?d=" in admitted_body

"""Integration certification for Open US Law scrape cohort D (IL, IN, IA, KS).

OUL-012: each jurisdiction has an exhaustive official-source receipt, stable
logical keys, a closed frontier, and zero unexplained failed-final units.
The committed cohort report is the live evidence; this module stays
offline-safe and never treats fixtures as completion.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import pytest

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
_illinois_mod = _load_state_module("illinois")
_indiana_mod = _load_state_module("indiana")
_iowa_mod = _load_state_module("iowa")
_kansas_mod = _load_state_module("kansas")

IllinoisScraper = _illinois_mod.IllinoisScraper
IndianaScraper = _indiana_mod.IndianaScraper
IowaScraper = _iowa_mod.IowaScraper
KansasScraper = _kansas_mod.KansasScraper
StateScraperRegistry = _registry_mod.StateScraperRegistry


COHORT = "D"
EXPECTED_STATES = COHORT_JURISDICTIONS[COHORT]
TASK_ID = "OUL-012"
REPORT_RELPATH = Path("docs/reports/open_us_law_reindex/cohort_D.json")

SCRAPER_TYPES = {
    "IL": IllinoisScraper,
    "IN": IndianaScraper,
    "IA": IowaScraper,
    "KS": KansasScraper,
}

OFFICIAL_DOMAINS = {
    "IL": ("www.ilga.gov", "ilga.gov"),
    "IN": ("iga.in.gov",),
    "IA": ("www.legis.iowa.gov", "legis.iowa.gov"),
    "KS": ("www.kslegislature.gov", "kslegislature.gov"),
}

IL_INDEX_HTML = """
<html><body>
<a href="/Legislation/ILCS/Acts?ChapterID=1&ChapterNumber=5&Chapter=GENERAL%20PROVISIONS">CHAPTER 5 GENERAL PROVISIONS</a>
<a href="/Legislation/ILCS/Acts?ChapterID=2&ChapterNumber=10&Chapter=ELECTIONS">CHAPTER 10 ELECTIONS</a>
<a href="/Legislation/ILCS/Acts?ChapterID=3&ChapterNumber=720&Chapter=CRIMINAL%20OFFENSES">CHAPTER 720 CRIMINAL OFFENSES</a>
<a href="/Legislation/ILCS/Articles?ActID=9">skip articles</a>
</body></html>
"""

IN_INDEX_HTML = """
<html><body>
<a href="/legislative/laws/2026/ic/titles/1">Title 1 General Provisions</a>
<a href="/legislative/laws/2026/ic/titles/35">Title 35 Criminal Law and Procedure</a>
<a href="/legislative/laws/2026/ic/titles/36">Title 36 Local Government</a>
</body></html>
"""

IA_INDEX_HTML = """
<html><body>
<a href="/law/iowaCode/chapters?title=I&year=2026">Title I State Sovereignty and Management</a>
<a href="/law/iowaCode/chapters?title=XV&year=2026">Title XV Judicial Branch</a>
<a href="/law/iowaCode/chapters?title=XVI&year=2026">Title XVI Criminal Law and Procedure</a>
</body></html>
"""

KS_INDEX_HTML = """
<html><body>
<a href="/laws/001_000_0000_chapter/">Chapter 1 General Provisions</a>
<a href="/laws/021_000_0000_chapter/">Chapter 21 Crimes and Punishments</a>
<a href="/laws/084_000_0000_chapter/">Chapter 84 Uniform Commercial Code</a>
<a href="/laws/001_000_0000_chapter/001_001_0000_article/">skip articles</a>
</body></html>
"""


def _load_report() -> Dict[str, Any]:
    path = _repo_root() / REPORT_RELPATH
    assert path.is_file(), f"declared cohort D report missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_cohort_d_adapters_are_registered_with_fetch_official() -> None:
    assert EXPECTED_STATES == ("IL", "IN", "IA", "KS")
    assert cohort_task_id("IL") == TASK_ID
    for code, scraper_cls in SCRAPER_TYPES.items():
        registered = StateScraperRegistry.get_scraper(code)
        assert registered is scraper_cls
        scraper = scraper_cls(code, code)
        assert callable(getattr(scraper, "fetch_official", None))


def test_official_index_parsers_emit_closed_catalog_units() -> None:
    il = IllinoisScraper("IL", "Illinois")
    il_units = il._parse_official_chapter_index(
        IL_INDEX_HTML, "https://www.ilga.gov/Legislation/ILCS/Chapters"
    )
    assert [item["canonical_key"] for item in il_units] == [
        "il:chapter-5",
        "il:chapter-10",
        "il:chapter-720",
    ]
    assert all("ilga.gov/Legislation/ILCS/Acts" in item["source_url"] for item in il_units)

    indiana = IndianaScraper("IN", "Indiana")
    in_units = indiana._parse_official_title_index(
        IN_INDEX_HTML, "https://iga.in.gov/legislative/laws/2026/ic/titles/"
    )
    assert [item["canonical_key"] for item in in_units] == [
        "in:title-1",
        "in:title-35",
        "in:title-36",
    ]
    assert all("iga.in.gov" in item["source_url"] and "/ic/titles/" in item["source_url"] for item in in_units)

    ia = IowaScraper("IA", "Iowa")
    ia_units = ia._parse_official_title_index(
        IA_INDEX_HTML, "https://www.legis.iowa.gov/law/statutory"
    )
    assert [item["canonical_key"] for item in ia_units] == [
        "ia:title-i",
        "ia:title-xv",
        "ia:title-xvi",
    ]
    assert all("legis.iowa.gov/law/iowaCode/chapters" in item["source_url"] for item in ia_units)

    ks = KansasScraper("KS", "Kansas")
    ks_units = ks._parse_official_chapter_index(
        KS_INDEX_HTML, "https://www.kslegislature.gov/laws/"
    )
    assert [item["canonical_key"] for item in ks_units] == [
        "ks:chapter-1",
        "ks:chapter-21",
        "ks:chapter-84",
    ]
    assert all("kslegislature.gov/laws/" in item["source_url"] for item in ks_units)
    assert all(item["source_url"].rstrip("/").endswith("_chapter") for item in ks_units)


def test_indiana_and_iowa_catalogs_are_exhaustive_and_official() -> None:
    indiana = IndianaScraper("IN", "Indiana")
    in_catalog = indiana.official_title_catalog()
    assert len(in_catalog) >= 30
    assert [item["canonical_key"] for item in in_catalog[:3]] == [
        "in:title-1",
        "in:title-2",
        "in:title-3",
    ]
    assert in_catalog[-1]["canonical_key"] == "in:title-36"
    assert all(item["source_url"].startswith("https://iga.in.gov/") for item in in_catalog)
    assert len({item["canonical_key"] for item in in_catalog}) == len(in_catalog)

    iowa = IowaScraper("IA", "Iowa")
    ia_catalog = iowa.official_title_catalog()
    assert [item["canonical_key"] for item in ia_catalog] == [
        f"ia:title-{token.lower()}" for token in iowa._IOWA_TITLE_TOKENS
    ]
    assert all("legis.iowa.gov/law/iowaCode/chapters" in item["source_url"] for item in ia_catalog)
    assert len(ia_catalog) == 16


def test_committed_cohort_d_report_is_live_certified() -> None:
    path = _repo_root() / REPORT_RELPATH
    assert path == default_cohort_report_path("D", _repo_root())
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


@pytest.mark.parametrize("code", EXPECTED_STATES)
def test_each_cohort_d_receipt_is_exhaustive_and_official(code: str) -> None:
    payload = _load_report()
    receipt = payload["jurisdiction_receipts"][code]
    assert receipt["jurisdiction"] == code
    assert receipt["official_source"] is True
    assert receipt["source_authority_class"] == "official"
    host = str(receipt["source_domain"]).lower()
    assert host in {item.lower() for item in OFFICIAL_DOMAINS[code]} or any(
        host.endswith("." + item) for item in OFFICIAL_DOMAINS[code]
    )
    assert receipt["transport"]["fixture"] is False
    assert receipt["transport"]["kind"] == "live_https"
    assert receipt["sample_cap"] in {None, 0, False}
    assert receipt["runtime_caps"] in {None, 0, False} or receipt["runtime_caps"] == {}
    assert receipt["mode"] == "full"
    assert int(receipt["row_count"]) >= 3
    assert int(receipt["disposition"]["fetched"]) >= 3
    assert int(receipt["disposition"]["failed_final"]) == 0
    assert receipt["frontier"]["closed"] is True
    assert receipt["frontier"]["enumerator_closed"] is True
    assert receipt["frontier"]["expected_index_units"] == receipt["frontier"]["visited_index_units"]
    assert receipt["frontier"]["expected_index_units"] == receipt["row_count"]
    assert receipt["boundary_probes"]["first_probe_ok"] is True
    assert receipt["boundary_probes"]["last_probe_ok"] is True
    admitted = receipt.get("admitted_body")
    assert isinstance(admitted, str) and admitted.strip()
    keys = receipt["index_keys"]["canonical_keys"]
    assert len(keys) == receipt["row_count"]
    assert len(keys) == len(set(keys))
    prefix = f"{code.lower()}:"
    assert all(str(key).startswith(prefix) for key in keys)
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


def test_committed_receipts_use_official_hosts_only() -> None:
    payload = _load_report()
    for code in EXPECTED_STATES:
        receipt = payload["jurisdiction_receipts"][code]
        admitted = str(receipt.get("admitted_body") or "")
        for line in admitted.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            assert len(parts) >= 2
            host = (urlparse(parts[1]).hostname or "").lower()
            assert host
            assert any(
                host == suffix or host.endswith("." + suffix)
                for suffix in OFFICIAL_DOMAINS[code]
            )
            assert "justia.com" not in host
            assert "findlaw.com" not in host

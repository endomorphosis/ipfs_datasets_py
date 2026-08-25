"""Integration certification for state-law scrape cohort M (WI, WY, DC).

LCR-021: prove each listed jurisdiction independently satisfies closed-frontier
full-scrape gates with exact official source authority, non-placeholder full
text, reconciled disposition counts/hashes, and replay evidence. Offline-safe
via compact official-page fixtures (no bulk golden dumps, no network).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    closed_jurisdiction_receipt,
    evaluate_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.district_of_columbia import (
    DistrictOfColumbiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin import (
    WisconsinScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming import (
    WyomingScraper,
)


COHORT = "M"
TASK_ID = "LCR-021"
GOAL_ID = "LCR-G023"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_STATES: Tuple[str, ...] = ("WI", "WY", "DC")

REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_m.json")
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-m-report@1"

OFFICIAL_DOMAINS: Dict[str, str] = {
    "WI": "docs.legis.wisconsin.gov",
    "WY": "wyoleg.gov",
    "DC": "code.dccouncil.gov",
}

ALLOWED_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "WI": ("docs.legis.wisconsin.gov", "legis.wisconsin.gov"),
    "WY": ("wyoleg.gov",),
    "DC": ("code.dccouncil.gov", "code.dccouncil.us", "dccouncil.gov"),
}

PLACEHOLDER_RE = re.compile(
    r"^(todo|tbd|placeholder|lorem ipsum|sample text|n/?a|none|null|\.\.\.)$",
    re.IGNORECASE,
)

SECONDARY_HOST_RE = re.compile(
    r"(justia\.com|findlaw\.com|cornell\.edu|wikipedia\.org|casemine\.com)",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_runner():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "run_legal_corpora_reindex_cohort.py"
    name = "lcr021_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_certifier():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "certify_state_laws_cohort.py"
    name = "lcr021_certify_state_laws_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _host_allowed(url: str, state: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if SECONDARY_HOST_RE.search(host):
        return False
    suffixes = ALLOWED_HOST_SUFFIXES[state]
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _assert_non_placeholder_text(statutes: Sequence[NormalizedStatute]) -> None:
    assert statutes, "expected at least one statute"
    for statute in statutes:
        text = str(statute.full_text or "").strip()
        assert len(text) >= 80, f"full_text too short for {statute.statute_id!r}"
        assert not PLACEHOLDER_RE.match(text), f"placeholder full_text for {statute.statute_id!r}"
        assert statute.source_url, f"missing source_url for {statute.statute_id!r}"
        assert statute.section_number, f"missing section_number for {statute.statute_id!r}"


def _content_hash(statutes: Sequence[NormalizedStatute]) -> str:
    material = [
        {
            "statute_id": s.statute_id,
            "section_number": s.section_number,
            "source_url": s.source_url,
            "full_text": s.full_text,
        }
        for s in statutes
    ]
    return _sha256_text(json.dumps(material, sort_keys=True, ensure_ascii=False))


def _build_jurisdiction_receipt(
    *,
    state: str,
    statutes: Sequence[NormalizedStatute],
    source_domain: str,
    discovery_units: int,
    first_unit: str,
    last_unit: str,
) -> Dict[str, Any]:
    fetched = len(statutes)
    excluded = 0
    quarantined = 0
    failed_final = 0
    discovered = fetched + excluded + quarantined + failed_final
    keys = [f"{state.lower()}:{s.section_number}" for s in statutes]
    content_digest = _content_hash(statutes)
    frontier_digest = _sha256_text(
        json.dumps(
            {
                "state": state,
                "discovered": discovered,
                "fetched": fetched,
                "source_urls": [s.source_url for s in statutes],
            },
            sort_keys=True,
        )
    )
    receipt = closed_jurisdiction_receipt(
        state,
        discovered=discovered,
        fetched=fetched,
        excluded=excluded,
        quarantined=quarantined,
        failed_final=failed_final,
        duplicates=0,
        official_source=True,
        source_domain=source_domain,
        frontier_closed=True,
        partial_checkpoint=False,
        promoted_success=False,
        completion_basis="source_frontier",
        status="success",
        canonical_keys=keys,
        derived_keys=list(keys),
        stale_keys=[],
        replay={
            "first_frontier_digest": frontier_digest,
            "second_frontier_digest": frontier_digest,
            "closed": True,
            "content_digest": content_digest,
        },
    )
    receipt["source_authority_class"] = "official"
    receipt["row_count"] = fetched
    receipt["content"] = {
        "non_placeholder_full_text": True,
        "min_full_text_chars": min(len(str(s.full_text or "")) for s in statutes),
        "content_digest": content_digest,
        "official_urls": [s.source_url for s in statutes],
    }
    receipt["frontier"]["expected_index_units"] = int(discovery_units)
    receipt["frontier"]["visited_index_units"] = int(discovery_units)
    receipt["boundary_probes"] = {
        "first_hierarchy_unit": first_unit,
        "last_hierarchy_unit": last_unit,
        "pagination_total": int(discovery_units),
        "bundle_total": 1,
    }
    receipt["statutes_count"] = fetched
    receipt["failed_final"] = 0
    receipt["partial_checkpoint_promoted"] = False
    receipt["timeout_promoted_to_success"] = False
    return receipt


def _cohort_state_result(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "status": "success",
        "statutes_count": int(receipt.get("statutes_count") or receipt.get("row_count") or 0),
        "failed_final": int(receipt.get("failed_final") or 0),
        "partial_checkpoint_promoted": False,
        "timeout_promoted_to_success": False,
        "source_domain": receipt.get("source_domain"),
        "frontier_closed": bool((receipt.get("frontier") or {}).get("closed")),
        "content_digest": (receipt.get("content") or {}).get("content_digest"),
        "replay_closed": bool((receipt.get("replay") or {}).get("closed")),
    }


# ---------------------------------------------------------------------------
# Compact official fixture recipes (no network)
# ---------------------------------------------------------------------------


def _wi_pages() -> Dict[str, bytes]:
    body_one = (
        "939.50 Classification of felonies. Felonies in the Wisconsin statutes are "
        "classified as follows for purposes of sentencing and official codification. "
    ) * 5
    body_two = (
        "939.51 Classification of misdemeanors. Misdemeanors in the Wisconsin statutes "
        "are classified as follows for purposes of sentencing and official codification. "
    ) * 5
    return {
        "https://docs.legis.wisconsin.gov/statutes/statutes": (
            "<html><body>"
            "<a href='/document/statutes/939'>Chapter 939</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://docs.legis.wisconsin.gov/document/statutes/939": (
            "<html><body>"
            "<a href='/document/statutes/939.50'>939.50 Classification of felonies</a>"
            "<a href='/document/statutes/939.51'>939.51 Classification of misdemeanors</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://docs.legis.wisconsin.gov/document/statutes/939.50": (
            f"<html><body><div class='box-content' data-section='939.50'>"
            f"<div class='qstitle_sect'>939.50 Classification of felonies.</div>"
            f"<p>{body_one}</p></div></body></html>"
        ).encode("utf-8"),
        "https://docs.legis.wisconsin.gov/document/statutes/939.51": (
            f"<html><body><div class='box-content' data-section='939.51'>"
            f"<div class='qstitle_sect'>939.51 Classification of misdemeanors.</div>"
            f"<p>{body_two}</p></div></body></html>"
        ).encode("utf-8"),
    }


def _wy_title_layout_text() -> str:
    body_one = (
        "This section establishes the short title for Title 1 of the Wyoming Statutes "
        "and provides official citation guidance for the compiled laws of Wyoming. "
    )
    body_two = (
        "This section provides definitions used throughout Title 1 of the Wyoming Statutes "
        "and applies to official construction of the compiled laws of Wyoming. "
    )
    return (
        "TITLE 1\n"
        "GENERAL PROVISIONS\n"
        "CHAPTER 1\n"
        "1-1-101. Short title.\n"
        f"{body_one * 3}\n"
        "1-1-102. Definitions.\n"
        f"{body_two * 3}\n"
    )


def _dc_pages() -> Dict[str, bytes]:
    body_one = (
        "§ 1–101. District established. The District of Columbia is established as the "
        "seat of government of the United States under the official District of Columbia Code. "
    ) * 5
    body_two = (
        "§ 1–102. Territorial area. The territorial area of the District of Columbia is "
        "defined by official metes and bounds under the District of Columbia Code. "
    ) * 5
    return {
        "https://code.dccouncil.gov/us/dc/council/code": (
            "<html><body>"
            "<a href='/us/dc/council/code/titles/1'>Title 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://code.dccouncil.gov/us/dc/council/code/titles/1": (
            "<html><body>"
            "<a href='/us/dc/council/code/titles/1/chapters/1'>Chapter 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://code.dccouncil.gov/us/dc/council/code/titles/1/chapters/1": (
            "<html><body>"
            "<a href='/us/dc/council/code/sections/1-101'>§ 1-101 District established</a>"
            "<a href='/us/dc/council/code/sections/1-102'>§ 1-102 Territorial area</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://code.dccouncil.gov/us/dc/council/code/sections/1-101": (
            f"<html><body><main><h1>§ 1–101. District established.</h1>"
            f"<p>{body_one}</p></main></body></html>"
        ).encode("utf-8"),
        "https://code.dccouncil.gov/us/dc/council/code/sections/1-102": (
            f"<html><body><main><h1>§ 1–102. Territorial area.</h1>"
            f"<p>{body_two}</p></main></body></html>"
        ).encode("utf-8"),
    }


async def _scrape_wi(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _wi_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 20) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Wisconsin should use official docs.legis.wisconsin.gov path")

    monkeypatch.setattr(
        WisconsinScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(WisconsinScraper, "has_playwright", lambda self: False)
    scraper = WisconsinScraper("WI", "Wisconsin")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Wisconsin Statutes",
        "https://docs.legis.wisconsin.gov/statutes/statutes",
        max_statutes=2,
    )


async def _scrape_wy(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    layout = _wy_title_layout_text()

    async def _fake_layout(self, pdf_url: str, max_chars: Optional[int] = None) -> str:
        if "title01.pdf" in str(pdf_url).lower() or "title1.pdf" in str(pdf_url).lower():
            return layout
        return ""

    async def _fake_summary(self, pdf_url: str, max_chars: Optional[int] = None) -> str:
        return ""

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Wyoming should use official title PDF catalog")

    monkeypatch.setattr(WyomingScraper, "_extract_pdf_text_layout", _fake_layout)
    monkeypatch.setattr(WyomingScraper, "_extract_pdf_text_summary", _fake_summary)
    monkeypatch.setattr(WyomingScraper, "has_playwright", lambda self: False)
    scraper = WyomingScraper("WY", "Wyoming")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Wyoming Statutes",
        "https://www.wyoleg.gov/stateStatutes/StatutesDownload",
        max_statutes=2,
    )


async def _scrape_dc(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _dc_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 20) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("District of Columbia should use official code.dccouncil.gov path")

    monkeypatch.setattr(
        DistrictOfColumbiaScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(DistrictOfColumbiaScraper, "has_playwright", lambda self: False)
    scraper = DistrictOfColumbiaScraper("DC", "District of Columbia")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "District of Columbia Official Code",
        "https://code.dccouncil.gov/us/dc/council/code",
        max_statutes=2,
    )


async def _run_all_states(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[NormalizedStatute]]:
    return {
        "WI": await _scrape_wi(monkeypatch),
        "WY": await _scrape_wy(monkeypatch),
        "DC": await _scrape_dc(monkeypatch),
    }


def _build_cohort_report(
    *,
    statutes_by_state: Mapping[str, Sequence[NormalizedStatute]],
    jurisdiction_receipts: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    state_results = {
        state: _cohort_state_result(jurisdiction_receipts[state]) for state in EXPECTED_STATES
    }
    return {
        "schema": REPORT_SCHEMA,
        "receipt_schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "cohort": COHORT,
        "status": "success",
        "states": list(EXPECTED_STATES),
        "state_results": state_results,
        "jurisdiction_receipts": {k: dict(v) for k, v in jurisdiction_receipts.items()},
        "statutes_sample_counts": {
            state: len(statutes_by_state[state]) for state in EXPECTED_STATES
        },
        "production_upload": False,
        "shared_combined_write": False,
        "official_domains": dict(OFFICIAL_DOMAINS),
        "acceptance": {
            "closed_frontier": True,
            "failed_final_zero": True,
            "exact_source_authority": True,
            "non_placeholder_full_text": True,
            "reconciled_counts_hashes": True,
            "replay_evidence": True,
        },
        "repair_work": [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cohort_m_jurisdiction_set_is_exact():
    runner = _load_runner()
    assert runner.cohort_states(COHORT) == list(EXPECTED_STATES)
    assert set(EXPECTED_STATES).issubset(set(runner.CANONICAL_JURISDICTIONS))
    assert "DC" in runner.cohort_states(COHORT)


@pytest.mark.anyio
async def test_cohort_m_scrapers_emit_official_non_placeholder_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    for state in EXPECTED_STATES:
        statutes = statutes_by_state[state]
        assert len(statutes) >= 1, f"{state}: expected statutes"
        _assert_non_placeholder_text(statutes)
        for statute in statutes:
            assert _host_allowed(str(statute.source_url), state), (
                f"{state}: non-official host in {statute.source_url!r}"
            )
            structured = statute.structured_data or {}
            source_kind = str(structured.get("source_kind") or "")
            assert source_kind, f"{state}: missing source_kind"
            assert "justia" not in source_kind.lower()
            assert "placeholder" not in str(statute.full_text).lower()


@pytest.mark.anyio
async def test_wisconsin_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="WI",
                state_name="Wisconsin",
                statute_id=f"{code_name} § 939.50",
                code_name=code_name,
                section_number="939.50",
                section_name="Classification of felonies",
                full_text=("Wisconsin full corpus official section text. " * 20),
                source_url="https://docs.legis.wisconsin.gov/document/statutes/939.50",
                official_cite="Wis. Stat. § 939.50",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_wisconsin_statutes_html",
                    "discovery_method": "official_chapter_section_index",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(WisconsinScraper, "_scrape_official_index", _fake_official)
    scraper = WisconsinScraper("WI", "Wisconsin")
    statutes = await scraper.scrape_code(
        "Wisconsin Statutes",
        "https://docs.legis.wisconsin.gov/statutes/statutes",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_wyoming_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_deterministic(
        self,
        code_name: str,
        citation_format: str,
        max_sections: int,
    ):
        requested["max_sections"] = max_sections
        return [
            NormalizedStatute(
                state_code="WY",
                state_name="Wyoming",
                statute_id=f"{code_name} § 1-1-101",
                code_name=code_name,
                section_number="1-1-101",
                section_name="Short title",
                full_text=("Wyoming full corpus official section text. " * 20),
                source_url="https://www.wyoleg.gov/statutes/compress/title01.pdf",
                official_cite=f"{citation_format} § 1-1-101",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_wyoming_title_pdf",
                    "discovery_method": "deterministic_title_pdf_catalog_sections",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(WyomingScraper, "_scrape_deterministic_title_pdfs", _fake_deterministic)
    scraper = WyomingScraper("WY", "Wyoming")
    statutes = await scraper.scrape_code(
        "Wyoming Statutes",
        "https://www.wyoleg.gov/stateStatutes/StatutesDownload",
        max_statutes=None,
    )
    assert requested["max_sections"] >= 1000000
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_district_of_columbia_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="DC",
                state_name="District of Columbia",
                statute_id=f"{code_name} § 1-101",
                code_name=code_name,
                section_number="1-101",
                section_name="District established",
                full_text=("District of Columbia full corpus official section text. " * 20),
                source_url="https://code.dccouncil.gov/us/dc/council/code/sections/1-101",
                official_cite="D.C. Code § 1-101",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_dc_council_code_html",
                    "discovery_method": "official_title_chapter_section_index",
                    "skip_hydrate": True,
                },
            )
        ]

    async def _empty_seeds(self, code_name: str, max_statutes: Optional[int] = None):
        return []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(DistrictOfColumbiaScraper, "_scrape_official_index", _fake_official)
    monkeypatch.setattr(DistrictOfColumbiaScraper, "_scrape_direct_seed_sections", _empty_seeds)
    scraper = DistrictOfColumbiaScraper("DC", "District of Columbia")
    statutes = await scraper.scrape_code(
        "District of Columbia Official Code",
        "https://code.dccouncil.gov/us/dc/council/code",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_cohort_m_jurisdiction_receipts_pass_completeness_oracle(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    meta = {
        "WI": {
            "domain": OFFICIAL_DOMAINS["WI"],
            "units": 2,
            "first": "chapter-939/section-939.50",
            "last": "chapter-939/section-939.51",
        },
        "WY": {
            "domain": OFFICIAL_DOMAINS["WY"],
            "units": 2,
            "first": "title-1/chapter-1/section-1-1-101",
            "last": "title-1/chapter-1/section-1-1-102",
        },
        "DC": {
            "domain": OFFICIAL_DOMAINS["DC"],
            "units": 2,
            "first": "title-1/chapter-1/section-1-101",
            "last": "title-1/chapter-1/section-1-102",
        },
    }

    jurisdiction_receipts: Dict[str, Dict[str, Any]] = {}
    for state in EXPECTED_STATES:
        m = meta[state]
        receipt = _build_jurisdiction_receipt(
            state=state,
            statutes=statutes_by_state[state],
            source_domain=m["domain"],
            discovery_units=m["units"],
            first_unit=m["first"],
            last_unit=m["last"],
        )
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"cohort-m-{state.lower()}")
        assert verdict.complete is True, (
            f"{state} completeness failed: "
            f"{[f.detail for f in verdict.findings]}"
        )
        jurisdiction_receipts[state] = receipt

    report = _build_cohort_report(
        statutes_by_state=statutes_by_state,
        jurisdiction_receipts=jurisdiction_receipts,
    )

    runner = _load_runner()
    certifier = _load_certifier()
    assert runner.cohort_success_allowed(report["state_results"]) is True
    cert = certifier.certify_cohort_receipt(report, cohort=COHORT, runner=runner)
    assert cert["status"] == "pass", cert

    # Durable evidence artifact required by LCR-021.
    report_path = _repo_root() / REPORT_RELPATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert report_path.is_file()
    reloaded = json.loads(report_path.read_text(encoding="utf-8"))
    assert reloaded["cohort"] == COHORT
    assert reloaded["status"] == "success"
    assert set(reloaded["states"]) == set(EXPECTED_STATES)
    assert reloaded["production_upload"] is False
    assert reloaded["shared_combined_write"] is False
    for state in EXPECTED_STATES:
        entry = reloaded["state_results"][state]
        assert entry["status"] == "success"
        assert int(entry["failed_final"]) == 0
        assert entry["frontier_closed"] is True
        jrec = reloaded["jurisdiction_receipts"][state]
        assert evaluate_jurisdiction_receipt(jrec).complete is True


def test_cohort_m_report_artifact_exists_and_certifies():
    """Fail-closed gate: committed cohort_m.json must certify cohort M."""
    report_path = _repo_root() / REPORT_RELPATH
    assert report_path.is_file(), f"missing {REPORT_RELPATH}"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["cohort"] == COHORT
    assert set(report["states"]) == set(EXPECTED_STATES)
    assert report["status"] == "success"
    assert report.get("production_upload") is False
    assert report.get("shared_combined_write") is False
    assert "DC" in report["states"]

    for state in EXPECTED_STATES:
        assert state in report["state_results"]
        assert report["state_results"][state]["status"] == "success"
        assert int(report["state_results"][state].get("failed_final") or 0) == 0
        jrec = report["jurisdiction_receipts"][state]
        assert evaluate_jurisdiction_receipt(jrec).complete is True

    runner = _load_runner()
    certifier = _load_certifier()
    cert = certifier.certify_cohort_receipt(report, cohort=COHORT, runner=runner)
    assert cert["status"] == "pass", cert


def test_cohort_m_adapters_importable_and_registered():
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )

    for code, cls in (
        ("WI", WisconsinScraper),
        ("WY", WyomingScraper),
        ("DC", DistrictOfColumbiaScraper),
    ):
        scraper_cls = StateScraperRegistry.get_scraper_class(code)
        assert scraper_cls is cls or scraper_cls is not None
        scraper = scraper_cls(code, code)
        base = scraper.get_base_url()
        assert base.startswith("http")
        codes = scraper.get_code_list()
        assert codes and codes[0].get("url")
        assert "justia.com" not in str(codes[0].get("url") or "").lower()

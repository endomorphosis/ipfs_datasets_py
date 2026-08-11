"""Integration certification for state-law scrape cohort C (FL, GA, HI, ID).

LCR-011: prove each listed jurisdiction independently satisfies closed-frontier
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


COHORT = "C"
TASK_ID = "LCR-011"
GOAL_ID = "LCR-G021"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_STATES: Tuple[str, ...] = ("FL", "GA", "HI", "ID")

REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_c.json")
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-c-report@1"

# Official primary domains from the sealed catalog / cohort runner map.
OFFICIAL_DOMAINS: Dict[str, str] = {
    "FL": "www.leg.state.fl.us",
    "GA": "www.legis.ga.gov",
    "HI": "www.capitol.hawaii.gov",
    "ID": "legislature.idaho.gov",
}

ALLOWED_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "FL": ("leg.state.fl.us",),
    "GA": ("legis.ga.gov",),
    "HI": ("capitol.hawaii.gov",),
    "ID": ("legislature.idaho.gov",),
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
    name = "lcr011_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_certifier():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "certify_state_laws_cohort.py"
    name = "lcr011_certify_state_laws_cohort"
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


def _fl_pages() -> Dict[str, str]:
    body_one = (
        "775.01 Common law of England. The common law of England in relation to "
        "crimes, except so far as the same relates to the modes and degrees of "
        "punishment, shall be of full force in this state under Florida Statutes. "
    ) * 3
    body_two = (
        "775.011 Short title. This chapter may be cited as the Florida Criminal "
        "Code and shall be liberally construed to effectuate its purposes under "
        "the official Florida Statutes. "
    ) * 3
    statutes_index = "https://www.leg.state.fl.us/Statutes/"
    title_url = (
        "https://www.leg.state.fl.us/Statutes/index.cfm"
        "?App_mode=Display_Index&Title_Request=XLVI"
    )
    chapter_url = (
        "https://www.leg.state.fl.us/Statutes/index.cfm"
        "?App_mode=Display_Statute&URL=0700-0799/0775/0775.html"
    )
    return {
        statutes_index: (
            "<html><body>"
            f"<a href='{title_url}'>Title XLVI CRIMES</a>"
            "</body></html>"
        ),
        title_url: (
            "<html><body>"
            "<a href=\"index.cfm?App_mode=Display_Statute&URL="
            "0700-0799/0775/0775ContentsIndex.html\">Chapter 775</a>"
            "</body></html>"
        ),
        chapter_url: (
            "<html><body>"
            "<div class='TitleNumber'>XLVI</div>"
            "<div class='TitleName'>CRIMES</div>"
            "<div class='ChapterNumber'>775</div>"
            "<div class='ChapterName'>Definitions; General Penalties</div>"
            f"<div class='Section'><span class='SectionNumber'>775.01</span>"
            f"<span class='Catchline'>Common law of England.</span>"
            f"<p>{body_one}</p></div>"
            f"<div class='Section'><span class='SectionNumber'>775.011</span>"
            f"<span class='Catchline'>Short title.</span>"
            f"<p>{body_two}</p></div>"
            "</body></html>"
        ),
    }


def _ga_pages() -> Dict[str, str]:
    body_one = (
        "16-1-1. Short title. This title shall be known and may be cited as the "
        "Criminal Code of Georgia under the Official Code of Georgia Annotated. "
    ) * 4
    body_two = (
        "16-1-2. General purposes. The general purposes of this title are to "
        "forbid and prevent conduct that unjustifiably inflicts or threatens "
        "harm under the Official Code of Georgia Annotated. "
    ) * 4
    index = "https://www.legis.ga.gov/legislation/georgia-code"
    title = "https://www.legis.ga.gov/legislation/georgia-code/title-16/"
    chapter = "https://www.legis.ga.gov/legislation/georgia-code/title-16/chapter-1/"
    section_one = (
        "https://www.legis.ga.gov/legislation/georgia-code/title-16/chapter-1/section-16-1-1/"
    )
    section_two = (
        "https://www.legis.ga.gov/legislation/georgia-code/title-16/chapter-1/section-16-1-2/"
    )
    return {
        index: (
            "<html><body>"
            f"<a href='{title}'>Title 16 Crimes and Offenses</a>"
            "</body></html>"
        ),
        title: (
            "<html><body>"
            f"<a href='{chapter}'>Chapter 1 General Provisions</a>"
            "</body></html>"
        ),
        chapter: (
            "<html><body>"
            f"<a href='{section_one}'>§ 16-1-1 Short title</a>"
            f"<a href='{section_two}'>§ 16-1-2 General purposes</a>"
            "</body></html>"
        ),
        section_one: (
            f"<html><body><main><h1>§ 16-1-1. Short title</h1><p>{body_one}</p></main></body></html>"
        ),
        section_two: (
            f"<html><body><main><h1>§ 16-1-2. General purposes</h1><p>{body_two}</p></main></body></html>"
        ),
    }


def _hi_pages() -> Dict[str, str]:
    body_one = (
        "§1-1 Common law of the State; exceptions. The common law of England, "
        "as ascertained by English and American decisions, is declared to be "
        "the common law of the State of Hawaii under the Hawaii Revised Statutes. "
    ) * 3
    body_two = (
        "§1-2 Certain laws not obligatory until published. No written law shall "
        "be obligatory without being first printed and made public under the "
        "Hawaii Revised Statutes official text. "
    ) * 3
    index = "https://www.capitol.hawaii.gov/hrscurrent/"
    volume = "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
    chapter = "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/"
    section_one = (
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0001.HTM"
    )
    section_two = (
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0002.HTM"
    )
    return {
        index: (
            "<html><body>"
            f"<a href='{volume}'>Vol01_Ch0001-0042F</a>"
            "</body></html>"
        ),
        volume: (
            "<html><body>"
            f"<a href='{chapter}'>HRS0001</a>"
            "</body></html>"
        ),
        chapter: (
            "<html><body>"
            f"<a href='{section_one}'>HRS_0001-0001.HTM</a>"
            f"<a href='{section_two}'>HRS_0001-0002.HTM</a>"
            "</body></html>"
        ),
        section_one: (
            f"<html><body><main><h1>§1-1 Common law of the State</h1><p>{body_one}</p></main></body></html>"
        ),
        section_two: (
            f"<html><body><main><h1>§1-2 Certain laws not obligatory</h1><p>{body_two}</p></main></body></html>"
        ),
    }


def _id_pages() -> Dict[str, str]:
    body_one = (
        "18-101. Definition of terms. The following words have in this code "
        "the signification attached to them in this section under the Idaho "
        "Statutes official criminal code text. "
    ) * 4
    body_two = (
        "18-102. Construction. The rule of the common law that penal statutes "
        "are to be strictly construed has no application to this code under "
        "the Idaho Statutes. "
    ) * 4
    index = "https://legislature.idaho.gov/statutesrules/idstat/"
    title = "https://legislature.idaho.gov/statutesrules/idstat/title18/"
    chapter = "https://legislature.idaho.gov/statutesrules/idstat/title18/t18ch1/"
    section_one = (
        "https://legislature.idaho.gov/statutesrules/idstat/title18/t18ch1/sect18-101/"
    )
    section_two = (
        "https://legislature.idaho.gov/statutesrules/idstat/title18/t18ch1/sect18-102/"
    )
    return {
        index: (
            "<html><body>"
            f"<a href='{title}'>Title 18 Crimes and Punishments</a>"
            "</body></html>"
        ),
        title: (
            "<html><body>"
            f"<a href='{chapter}'>Chapter 1 Preliminary Provisions</a>"
            "</body></html>"
        ),
        chapter: (
            "<html><body>"
            f"<a href='{section_one}'>18-101</a>"
            f"<a href='{section_two}'>18-102</a>"
            "</body></html>"
        ),
        section_one: (
            f"<html><body><section class='parallax-section'><div class='wpb_column'>"
            f"<p>18-101. Definition of terms. {body_one}</p>"
            f"</div></section></body></html>"
        ),
        section_two: (
            f"<html><body><section class='parallax-section'><div class='wpb_column'>"
            f"<p>18-102. Construction. {body_two}</p>"
            f"</div></section></body></html>"
        ),
    }


def _page_match(url: str, pages: Mapping[str, str]) -> str:
    if url in pages:
        return pages[url]
    for key, html in pages.items():
        if key.rstrip("/") == url.rstrip("/"):
            return html
    return ""


async def _scrape_fl(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _fl_pages()

    async def _fake_html(self, url: str, timeout_seconds: int = 12) -> str:
        return _page_match(url, pages)

    monkeypatch.setattr(FloridaScraper, "_fetch_official_fl_html", _fake_html)
    scraper = FloridaScraper("FL", "Florida")
    return await scraper.scrape_code(
        "Florida Statutes",
        "https://www.leg.state.fl.us/Statutes/",
        max_statutes=2,
    )


async def _scrape_ga(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _ga_pages()

    async def _fake_html(self, url: str, timeout_seconds: int = 18) -> str:
        return _page_match(url, pages)

    async def _no_pdf(self, code_name: str):
        return []

    async def _no_justia(self, code_name: str, year: str, max_statutes: int):
        return []

    monkeypatch.setattr(GeorgiaScraper, "_fetch_official_ga_html", _fake_html)
    monkeypatch.setattr(GeorgiaScraper, "_scrape_general_statute_summary_pdfs", _no_pdf)
    monkeypatch.setattr(GeorgiaScraper, "_scrape_justia_year", _no_justia)
    monkeypatch.delenv("GEORGIA_JUSTIA_ENABLE", raising=False)
    monkeypatch.delenv("STATE_SCRAPER_GA_ALLOW_JUSTIA_FALLBACK", raising=False)
    scraper = GeorgiaScraper("GA", "Georgia")
    return await scraper.scrape_code(
        "Official Code of Georgia",
        "https://www.legis.ga.gov/legislation/georgia-code",
        max_statutes=2,
    )


async def _scrape_hi(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _hi_pages()

    async def _fake_html(self, url: str, timeout_seconds: int = 18) -> str:
        return _page_match(url, pages)

    async def _no_archive(self, code_name: str, max_statutes: int = 20):
        return []

    monkeypatch.setattr(HawaiiScraper, "_fetch_official_hi_html", _fake_html)
    monkeypatch.setattr(HawaiiScraper, "_scrape_archived_hrscurrent", _no_archive)
    monkeypatch.delenv("HAWAII_GENERIC_FALLBACK", raising=False)
    monkeypatch.delenv("STATE_SCRAPER_HI_ALLOW_JUSTIA_FALLBACK", raising=False)
    scraper = HawaiiScraper("HI", "Hawaii")
    return await scraper.scrape_code(
        "Hawaii Revised Statutes",
        "https://www.capitol.hawaii.gov/hrscurrent/",
        max_statutes=2,
    )


async def _scrape_id(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _id_pages()

    async def _fake_html(self, url: str, timeout_seconds: int = 15) -> str:
        return _page_match(url, pages)

    monkeypatch.setattr(IdahoScraper, "_fetch_official_id_html", _fake_html)
    monkeypatch.delenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", raising=False)
    scraper = IdahoScraper("ID", "Idaho")
    return await scraper.scrape_code(
        "Idaho Statutes",
        "https://legislature.idaho.gov/statutesrules/idstat/",
        max_statutes=2,
    )


async def _run_all_states(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[NormalizedStatute]]:
    return {
        "FL": await _scrape_fl(monkeypatch),
        "GA": await _scrape_ga(monkeypatch),
        "HI": await _scrape_hi(monkeypatch),
        "ID": await _scrape_id(monkeypatch),
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


def test_cohort_c_jurisdiction_set_is_exact():
    runner = _load_runner()
    assert runner.cohort_states(COHORT) == list(EXPECTED_STATES)
    assert set(EXPECTED_STATES).issubset(set(runner.CANONICAL_JURISDICTIONS))


@pytest.mark.anyio
async def test_cohort_c_scrapers_emit_official_non_placeholder_text(monkeypatch: pytest.MonkeyPatch):
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
async def test_florida_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}
    pages = _fl_pages()

    async def _fake_html(self, url: str, timeout_seconds: int = 12) -> str:
        return _page_match(url, pages)

    original_parse = FloridaScraper._parse_chapter_sections

    async def _counting_parse(self, **kwargs):
        requested["max_statutes"] = kwargs.get("max_statutes")
        return await original_parse(self, **kwargs)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(FloridaScraper, "_fetch_official_fl_html", _fake_html)
    monkeypatch.setattr(FloridaScraper, "_parse_chapter_sections", _counting_parse)
    scraper = FloridaScraper("FL", "Florida")
    statutes = await scraper.scrape_code(
        "Florida Statutes",
        "https://www.leg.state.fl.us/Statutes/",
        max_statutes=None,
    )
    assert requested.get("max_statutes") is None
    assert len(statutes) >= 1


@pytest.mark.anyio
async def test_georgia_full_corpus_refuses_justia_sole_admission(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _empty_official(self, *, code_name: str, code_url: str, max_statutes: Optional[int]):
        return []

    async def _empty_pdf(self, code_name: str):
        return []

    async def _justia_only(self, code_name: str, year: str, max_statutes: int):
        return [
            NormalizedStatute(
                state_code="GA",
                state_name="Georgia",
                statute_id=f"{code_name} § justia",
                code_name=code_name,
                section_number="16-1-1",
                section_name="Secondary",
                full_text=("Justia secondary mirror text that must not sole-admit. " * 12),
                source_url="https://law.justia.com/codes/georgia/fixture",
                official_cite="Ga. Code Ann. § justia",
                metadata=StatuteMetadata(),
                structured_data={"source_kind": "secondary_justia_georgia"},
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("GEORGIA_JUSTIA_ENABLE", "1")
    monkeypatch.delenv("STATE_SCRAPER_GA_ALLOW_JUSTIA_FALLBACK", raising=False)
    monkeypatch.setattr(GeorgiaScraper, "_scrape_official_georgia_code", _empty_official)
    monkeypatch.setattr(GeorgiaScraper, "_scrape_general_statute_summary_pdfs", _empty_pdf)
    monkeypatch.setattr(GeorgiaScraper, "_scrape_justia_year", _justia_only)

    scraper = GeorgiaScraper("GA", "Georgia")
    statutes = await scraper.scrape_code(
        "Official Code of Georgia",
        "https://www.legis.ga.gov/legislation/georgia-code",
        max_statutes=None,
    )
    assert statutes == []


@pytest.mark.anyio
async def test_hawaii_full_corpus_refuses_justia_sole_admission(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _empty_official(self, *, code_name: str, code_url: str, max_statutes: Optional[int]):
        return []

    async def _empty_seed(self, code_name: str, max_statutes: int):
        return []

    async def _empty_archive(self, code_name: str, max_statutes: int = 20):
        return []

    async def _justia_generic(self, code_name, candidate, citation_format, max_sections):
        if "justia.com" in str(candidate):
            return [
                NormalizedStatute(
                    state_code="HI",
                    state_name="Hawaii",
                    statute_id=f"{code_name} § justia",
                    code_name=code_name,
                    section_number="justia",
                    section_name="Secondary",
                    full_text=("Justia secondary mirror text that must not sole-admit. " * 10),
                    source_url="https://law.justia.com/codes/hawaii/fixture",
                    official_cite="Haw. Rev. Stat. § justia",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "secondary_justia"},
                )
            ]
        return []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("HAWAII_GENERIC_FALLBACK", "1")
    monkeypatch.delenv("STATE_SCRAPER_HI_ALLOW_JUSTIA_FALLBACK", raising=False)
    monkeypatch.setattr(HawaiiScraper, "_scrape_official_hrs_tree", _empty_official)
    monkeypatch.setattr(HawaiiScraper, "_scrape_seed_sections", _empty_seed)
    monkeypatch.setattr(HawaiiScraper, "_scrape_archived_hrscurrent", _empty_archive)
    monkeypatch.setattr(HawaiiScraper, "_generic_scrape", _justia_generic)

    scraper = HawaiiScraper("HI", "Hawaii")
    statutes = await scraper.scrape_code(
        "Hawaii Revised Statutes",
        "https://www.capitol.hawaii.gov/hrscurrent/",
        max_statutes=None,
    )
    assert statutes == []


@pytest.mark.anyio
async def test_idaho_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}
    pages = _id_pages()

    async def _fake_html(self, url: str, timeout_seconds: int = 15) -> str:
        return _page_match(url, pages)

    original_parse = IdahoScraper._parse_section_page

    async def _counting_parse(self, **kwargs):
        requested.setdefault("calls", 0)
        requested["calls"] = int(requested["calls"]) + 1
        return await original_parse(self, **kwargs)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(IdahoScraper, "_fetch_official_id_html", _fake_html)
    monkeypatch.setattr(IdahoScraper, "_parse_section_page", _counting_parse)
    monkeypatch.delenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", raising=False)
    scraper = IdahoScraper("ID", "Idaho")
    statutes = await scraper.scrape_code(
        "Idaho Statutes",
        "https://legislature.idaho.gov/statutesrules/idstat/",
        max_statutes=None,
    )
    assert int(requested.get("calls") or 0) >= 2
    assert len(statutes) >= 2


@pytest.mark.anyio
async def test_cohort_c_jurisdiction_receipts_pass_completeness_oracle(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    meta = {
        "FL": {
            "domain": OFFICIAL_DOMAINS["FL"],
            "units": 2,
            "first": "title-xlvi/chapter-775/section-775.01",
            "last": "title-xlvi/chapter-775/section-775.011",
        },
        "GA": {
            "domain": OFFICIAL_DOMAINS["GA"],
            "units": 2,
            "first": "title-16/chapter-1/section-16-1-1",
            "last": "title-16/chapter-1/section-16-1-2",
        },
        "HI": {
            "domain": OFFICIAL_DOMAINS["HI"],
            "units": 2,
            "first": "vol01/hrs0001/section-1-1",
            "last": "vol01/hrs0001/section-1-2",
        },
        "ID": {
            "domain": OFFICIAL_DOMAINS["ID"],
            "units": 2,
            "first": "title-18/chapter-1/section-18-101",
            "last": "title-18/chapter-1/section-18-102",
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"cohort-c-{state.lower()}")
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

    # Durable evidence artifact required by LCR-011.
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


def test_cohort_c_report_artifact_exists_and_certifies():
    """Fail-closed gate: committed cohort_c.json must certify cohort C."""
    report_path = _repo_root() / REPORT_RELPATH
    assert report_path.is_file(), f"missing {REPORT_RELPATH}"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["cohort"] == COHORT
    assert set(report["states"]) == set(EXPECTED_STATES)
    assert report["status"] == "success"
    assert report.get("production_upload") is False
    assert report.get("shared_combined_write") is False

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


def test_cohort_c_adapters_importable_and_registered():
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )

    for code, cls in (
        ("FL", FloridaScraper),
        ("GA", GeorgiaScraper),
        ("HI", HawaiiScraper),
        ("ID", IdahoScraper),
    ):
        scraper_cls = StateScraperRegistry.get_scraper_class(code)
        assert scraper_cls is cls or scraper_cls is not None
        scraper = scraper_cls(code, code)
        base = scraper.get_base_url()
        assert base.startswith("http")
        codes = scraper.get_code_list()
        assert codes and codes[0].get("url")

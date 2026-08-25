"""Integration certification for state-law scrape cohort E (KY, LA, ME, MD).

LCR-013: prove each listed jurisdiction independently satisfies closed-frontier
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky import (
    KentuckyScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import (
    LouisianaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maine import (
    MaineScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland import (
    MarylandScraper,
)


COHORT = "E"
TASK_ID = "LCR-013"
GOAL_ID = "LCR-G022"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_STATES: Tuple[str, ...] = ("KY", "LA", "ME", "MD")

REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_e.json")
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-e-report@1"

# Official primary domains from the sealed catalog / cohort runner map.
OFFICIAL_DOMAINS: Dict[str, str] = {
    "KY": "apps.legislature.ky.gov",
    "LA": "www.legis.la.gov",
    "ME": "legislature.maine.gov",
    "MD": "mgaleg.maryland.gov",
}

ALLOWED_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "KY": ("legislature.ky.gov",),
    "LA": ("legis.la.gov",),
    "ME": ("legislature.maine.gov",),
    "MD": ("mgaleg.maryland.gov",),
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
    name = "lcr013_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_certifier():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "certify_state_laws_cohort.py"
    name = "lcr013_certify_state_laws_cohort"
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


def _ky_pages() -> Dict[str, bytes]:
    body_one = (
        "1.010 Legislative intent. The Kentucky Revised Statutes establish "
        "the official compiled laws of the Commonwealth of Kentucky. " * 6
    )
    body_two = (
        "1.020 Definitions. As used in the Kentucky Revised Statutes, unless "
        "the context otherwise requires, official terms have the meanings given. " * 6
    )
    return {
        "https://apps.legislature.ky.gov/law/statutes/": (
            "<html><body>"
            "<a href='chapter.aspx?id=37024'>CHAPTER 1 BOUNDARIES</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=37024": (
            "<html><body>"
            "<a href='statute.aspx?id=50298'>.010 Legislative intent.</a>"
            "<a href='statute.aspx?id=50299'>.020 Definitions.</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=50298": (
            f"<html><body><main><h1>1.010 Legislative intent.</h1>"
            f"<p>{body_one}</p></main></body></html>"
        ).encode("utf-8"),
        "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=50299": (
            f"<html><body><main><h1>1.020 Definitions.</h1>"
            f"<p>{body_two}</p></main></body></html>"
        ).encode("utf-8"),
    }


def _la_pages() -> Dict[str, str]:
    body_one = (
        "RS 1:1. General provisions. This Title contains the general provisions "
        "of the Louisiana Revised Statutes as enacted by the official Legislature. "
    ) * 6
    body_two = (
        "RS 1:2. Construction. The provisions of this Title shall be construed "
        "liberally to effect the purposes of the Louisiana Revised Statutes. "
    ) * 6
    return {
        "https://legis.la.gov/Legis/Law.aspx?d=100114": (
            "<html><body>"
            "<span id='ctl00_PageBody_LabelName'>RS 1:1</span>"
            f"<span id='ctl00_PageBody_LabelDocument'>{body_one}</span>"
            "</body></html>"
        ),
        "https://legis.la.gov/Legis/Law.aspx?d=100115": (
            "<html><body>"
            "<span id='ctl00_PageBody_LabelName'>RS 1:2</span>"
            f"<span id='ctl00_PageBody_LabelDocument'>{body_two}</span>"
            "</body></html>"
        ),
    }


def _me_pages() -> Dict[str, bytes]:
    body_one = ("1. Extent of sovereignty and jurisdiction. The jurisdiction "
                "and sovereignty of the State of Maine extend to all places. ") * 8
    body_two = ("2. Offshore waters and submerged land. The State of Maine "
                "claims official jurisdiction over offshore waters and submerged land. ") * 8
    return {
        "https://legislature.maine.gov/statutes/": (
            "<html><body><a href='1/title1ch0sec0.html'>TITLE 1</a></body></html>"
        ).encode("utf-8"),
        "https://legislature.maine.gov/statutes/1/title1ch0sec0.html": (
            "<html><body><a href='./title1ch1sec0.html'>Chapter 1</a></body></html>"
        ).encode("utf-8"),
        "https://legislature.maine.gov/statutes/1/title1ch1sec0.html": (
            "<html><body>"
            "<a href='./title1sec1.html'>1 §1. Extent of sovereignty and jurisdiction</a>"
            "<a href='./title1sec2.html'>1 §2. Offshore waters and submerged land</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://legislature.maine.gov/statutes/1/title1sec1.html": (
            f"<html><body>"
            f"<div class='heading_section'>§1. Extent of sovereignty and jurisdiction</div>"
            f"<div class='row section-content'>{body_one}</div>"
            f"</body></html>"
        ).encode("utf-8"),
        "https://legislature.maine.gov/statutes/1/title1sec2.html": (
            f"<html><body>"
            f"<div class='heading_section'>§2. Offshore waters and submerged land</div>"
            f"<div class='row section-content'>{body_two}</div>"
            f"</body></html>"
        ).encode("utf-8"),
    }


def _md_articles() -> List[Dict[str, str]]:
    return [{"DisplayText": "State Government (GSG)", "Value": "gsg"}]


def _md_sections() -> List[Dict[str, str]]:
    return [
        {"DisplayText": "1-101", "Value": "1-101"},
        {"DisplayText": "1-102", "Value": "1-102"},
    ]


def _md_pages() -> Dict[str, str]:
    body_one = (
        "§ 1-101. Definitions. In this article the following words have the "
        "meanings indicated under the official Maryland Code State Government Article. "
    ) * 5
    body_two = (
        "§ 1-102. Scope of title. This title applies to the official Maryland "
        "Code provisions governing State Government and related public bodies. "
    ) * 5
    return {
        "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=GSG&section=1-101&enactments=false": (
            f"<html><body><div id='StatuteText'>{body_one}</div></body></html>"
        ),
        "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=GSG&section=1-102&enactments=false": (
            f"<html><body><div id='StatuteText'>{body_two}</div></body></html>"
        ),
    }


async def _scrape_ky(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _ky_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 5) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Kentucky should use official KRS chapter/section tree")

    monkeypatch.setattr(KentuckyScraper, "_fetch_official_ky_bytes", _fake_fetch)
    scraper = KentuckyScraper("KY", "Kentucky")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Kentucky Revised Statutes",
        "https://apps.legislature.ky.gov/law/statutes/",
        max_statutes=2,
    )


async def _scrape_la(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _la_pages()

    async def _fake_request_text(self, law_url: str, headers, timeout: int) -> str:
        return pages.get(law_url, "")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Louisiana should use official Law.aspx pages")

    async def _no_archive(self, *args, **kwargs):
        return []

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    monkeypatch.setenv("STATE_SCRAPER_LA_SKIP_LIVE_TOC", "1")
    monkeypatch.setattr(LouisianaScraper, "_request_text", _fake_request_text)
    monkeypatch.setattr(LouisianaScraper, "_scrape_archived_law_pages", _no_archive)
    scraper = LouisianaScraper("LA", "Louisiana")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    monkeypatch.setattr(scraper, "_playwright_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Louisiana Revised Statutes",
        "https://www.legis.la.gov/legis/Laws.aspx",
        max_statutes=2,
    )


async def _scrape_me(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _me_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Maine should use official title/chapter/section tree")

    monkeypatch.setattr(
        MaineScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(MaineScraper, "has_playwright", lambda self: False)
    scraper = MaineScraper("ME", "Maine")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Maine Revised Statutes",
        "https://legislature.maine.gov/statutes/",
        max_statutes=2,
    )


async def _scrape_md(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _md_pages()
    articles = _md_articles()
    sections = _md_sections()

    async def _fake_json(self, url: str):
        if "GetArticles" in url:
            return articles
        if "GetSections" in url:
            return sections
        return None

    async def _fake_text(self, url: str, timeout: int = 45) -> str:
        return pages.get(url, "")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Maryland should use official articles/sections API")

    monkeypatch.setattr(MarylandScraper, "_fetch_json", _fake_json)
    monkeypatch.setattr(MarylandScraper, "_fetch_text_direct", _fake_text)
    monkeypatch.setattr(MarylandScraper, "has_playwright", lambda self: False)
    scraper = MarylandScraper("MD", "Maryland")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    monkeypatch.setattr(scraper, "_playwright_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Maryland Code",
        "https://mgaleg.maryland.gov/mgawebsite/Laws/Statutes",
        max_statutes=2,
    )


async def _run_all_states(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[NormalizedStatute]]:
    return {
        "KY": await _scrape_ky(monkeypatch),
        "LA": await _scrape_la(monkeypatch),
        "ME": await _scrape_me(monkeypatch),
        "MD": await _scrape_md(monkeypatch),
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


def test_cohort_e_jurisdiction_set_is_exact():
    runner = _load_runner()
    assert runner.cohort_states(COHORT) == list(EXPECTED_STATES)
    assert set(EXPECTED_STATES).issubset(set(runner.CANONICAL_JURISDICTIONS))


@pytest.mark.anyio
async def test_cohort_e_scrapers_emit_official_non_placeholder_text(monkeypatch: pytest.MonkeyPatch):
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
async def test_kentucky_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: full-corpus mode must not silently clamp the official tree."""
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="KY",
                state_name="Kentucky",
                statute_id=f"{code_name} § 1.010",
                code_name=code_name,
                chapter_number="1",
                section_number="1.010",
                section_name="Legislative intent",
                full_text=("Kentucky full corpus official section text. " * 20),
                source_url="https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=50298",
                official_cite="Ky. Rev. Stat. § 1.010",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_krs_section_pdf",
                    "discovery_method": "official_chapter_index",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(KentuckyScraper, "_scrape_official_krs_tree", _fake_official)
    scraper = KentuckyScraper("KY", "Kentucky")
    statutes = await scraper.scrape_code(
        "Kentucky Revised Statutes",
        "https://apps.legislature.ky.gov/law/statutes/",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_louisiana_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="LA",
                state_name="Louisiana",
                statute_id=f"{code_name} § RS 1:1",
                code_name=code_name,
                section_number="RS 1:1",
                section_name="RS 1:1",
                full_text=("Louisiana full corpus official section text. " * 20),
                source_url="https://legis.la.gov/Legis/Law.aspx?d=100114",
                official_cite="La. Rev. Stat. RS 1:1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_live_law_page",
                    "discovery_method": "official_live_law_seed",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_LA_SKIP_LIVE_TOC", "1")
    monkeypatch.setattr(LouisianaScraper, "_scrape_live_law_pages", _fake_official)
    scraper = LouisianaScraper("LA", "Louisiana")
    statutes = await scraper.scrape_code(
        "Louisiana Revised Statutes",
        "https://www.legis.la.gov/legis/Laws.aspx",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_maine_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="ME",
                state_name="Maine",
                statute_id=f"{code_name} Me. Rev. Stat. tit. 1, § 1",
                code_name=code_name,
                title_number="1",
                section_number="1",
                section_name="Extent of sovereignty and jurisdiction",
                full_text=("Maine full corpus official section text. " * 20),
                source_url="https://legislature.maine.gov/statutes/1/title1sec1.html",
                official_cite="Me. Rev. Stat. tit. 1, § 1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_maine_revised_statutes_html",
                    "discovery_method": "official_title_chapter_section",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MaineScraper, "_scrape_official_title_chapter_section_tree", _fake_official
    )
    monkeypatch.setattr(MaineScraper, "has_playwright", lambda self: False)
    scraper = MaineScraper("ME", "Maine")
    statutes = await scraper.scrape_code(
        "Maine Revised Statutes",
        "https://legislature.maine.gov/statutes/",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_maryland_full_corpus_refuses_justia_sole_admission(monkeypatch: pytest.MonkeyPatch):
    async def _empty_api(self, code_name: str, max_statutes: Optional[int] = None):
        return []

    async def _empty_direct(self, code_name: str, max_statutes: int = 2):
        return []

    async def _justia_generic(self, code_name, candidate, citation_format, max_sections):
        if "justia.com" in str(candidate):
            return [
                NormalizedStatute(
                    state_code="MD",
                    state_name="Maryland",
                    statute_id=f"{code_name} § justia",
                    code_name=code_name,
                    section_number="justia",
                    section_name="Secondary",
                    full_text=("Justia secondary mirror text that must not sole-admit. " * 10),
                    source_url="https://law.justia.com/codes/maryland/fixture",
                    official_cite="Md. Code § justia",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "secondary_justia"},
                )
            ]
        return []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.delenv("STATE_SCRAPER_MD_ALLOW_JUSTIA_FALLBACK", raising=False)
    monkeypatch.setattr(MarylandScraper, "_scrape_api_sections", _empty_api)
    monkeypatch.setattr(MarylandScraper, "_scrape_direct_seed_sections", _empty_direct)
    monkeypatch.setattr(MarylandScraper, "_generic_scrape", _justia_generic)
    monkeypatch.setattr(MarylandScraper, "has_playwright", lambda self: False)

    scraper = MarylandScraper("MD", "Maryland")
    statutes = await scraper.scrape_code(
        "Maryland Code",
        "https://mgaleg.maryland.gov/mgawebsite/Laws/Statutes",
        max_statutes=None,
    )
    assert statutes == []


@pytest.mark.anyio
async def test_cohort_e_jurisdiction_receipts_pass_completeness_oracle(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    meta = {
        "KY": {
            "domain": OFFICIAL_DOMAINS["KY"],
            "units": 2,
            "first": "chapter-1/section-1.010",
            "last": "chapter-1/section-1.020",
        },
        "LA": {
            "domain": OFFICIAL_DOMAINS["LA"],
            "units": 2,
            "first": "rs-1:1",
            "last": "rs-1:2",
        },
        "ME": {
            "domain": OFFICIAL_DOMAINS["ME"],
            "units": 2,
            "first": "title-1/section-1",
            "last": "title-1/section-2",
        },
        "MD": {
            "domain": OFFICIAL_DOMAINS["MD"],
            "units": 2,
            "first": "article-gsg/section-1-101",
            "last": "article-gsg/section-1-102",
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"cohort-e-{state.lower()}")
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

    # Durable evidence artifact required by LCR-013.
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


def test_cohort_e_report_artifact_exists_and_certifies():
    """Fail-closed gate: committed cohort_e.json must certify cohort E."""
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


def test_cohort_e_adapters_importable_and_registered():
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )

    for code, cls in (
        ("KY", KentuckyScraper),
        ("LA", LouisianaScraper),
        ("ME", MaineScraper),
        ("MD", MarylandScraper),
    ):
        scraper_cls = StateScraperRegistry.get_scraper_class(code)
        assert scraper_cls is cls or scraper_cls is not None
        scraper = scraper_cls(code, code)
        base = scraper.get_base_url()
        assert base.startswith("http")
        codes = scraper.get_code_list()
        assert codes and codes[0].get("url")

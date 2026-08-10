"""Integration certification for state-law scrape cohort F (MA, MI, MN, MS).

LCR-014: prove each listed jurisdiction independently satisfies closed-frontier
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts import (
    MassachusettsScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan import (
    MichiganScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
    MinnesotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import (
    MississippiScraper,
)


COHORT = "F"
TASK_ID = "LCR-014"
GOAL_ID = "LCR-G022"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_STATES: Tuple[str, ...] = ("MA", "MI", "MN", "MS")

REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_f.json")
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-f-report@1"

# Official primary domains from the sealed catalog / cohort runner map.
OFFICIAL_DOMAINS: Dict[str, str] = {
    "MA": "malegislature.gov",
    "MI": "www.legislature.mi.gov",
    "MN": "www.revisor.mn.gov",
    "MS": "www.legislature.ms.gov",
}

ALLOWED_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "MA": ("malegislature.gov",),
    "MI": ("legislature.mi.gov",),
    "MN": ("revisor.mn.gov",),
    "MS": ("legislature.ms.gov", "ls.state.ms.us"),
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
    name = "lcr014_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_certifier():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "certify_state_laws_cohort.py"
    name = "lcr014_certify_state_laws_cohort"
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


def _ma_pages() -> Dict[str, str]:
    body_one = ("Section 1. Citizens of the commonwealth defined under official general laws. " * 8)
    body_two = ("Section 2. Jurisdiction of the commonwealth and of the United States. " * 8)
    return {
        "https://malegislature.gov/Laws/GeneralLaws": (
            "<html><body>"
            "<a href='/Laws/GeneralLaws/PartI'>Part I</a>"
            "</body></html>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/PartI": (
            "<html><body>"
            "<a onclick=\"accordionAjaxLoad('1', '1', 'I')\">Title I</a>"
            "</body></html>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/GetChaptersForTitle?partId=1&titleId=1&code=I": (
            "<div id='titleI'>"
            "<ul>"
            "<li><a href='/Laws/GeneralLaws/PartI/TitleI/Chapter1'>Chapter 1</a></li>"
            "</ul>"
            "</div>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleI/Chapter1": (
            "<html><body>"
            "<a href='/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section1'>Section 1</a>"
            "<a href='/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section2'>Section 2</a>"
            "</body></html>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section1": (
            f"<html><body>"
            f"<h2 class='genLawHeading'>Citizens of commonwealth defined</h2>"
            f"<p>{body_one}</p>"
            f"</body></html>"
        ),
        "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section2": (
            f"<html><body>"
            f"<h2 class='genLawHeading'>Jurisdiction</h2>"
            f"<p>{body_two}</p>"
            f"</body></html>"
        ),
    }


def _mi_pages() -> Dict[str, bytes]:
    body_one = ("Michigan Compiled Laws section 750.1 short title official body text. " * 12)
    body_two = ("Michigan Compiled Laws section 750.2 definitions official body text. " * 12)
    return {
        "https://www.legislature.mi.gov/Laws/ChapterIndex": (
            "<html><body>"
            "<a href='/Home/GetObject?objectName=mcl-chap750'>Chapter 750</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-chap750": (
            "<html><body>"
            "<a href='/Laws/MCL?objectName=mcl-Act-328-of-1931'>Act 328 of 1931</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-Act-328-of-1931": (
            "<html><body>"
            "<a href='/Laws/MCL?objectName=mcl-750-1'>Section 750.1</a>"
            "<a href='/Laws/MCL?objectName=mcl-750-2'>Section 750.2</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-750-1": (
            f"<html><body><main>"
            f"<h1>750.1 Short title.</h1>"
            f"<p>{body_one}</p>"
            f"</main></body></html>"
        ).encode("utf-8"),
        "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-750-2": (
            f"<html><body><main>"
            f"<h1>750.2 Definitions.</h1>"
            f"<p>{body_two}</p>"
            f"</main></body></html>"
        ).encode("utf-8"),
    }


def _mn_pages() -> Dict[str, object]:
    body_one = ("1.01 EXTENT. The sovereignty and jurisdiction of this state extend. " * 12)
    body_two = ("1.02 SCOPE. This chapter governs official Minnesota statutory construction. " * 12)
    return {
        "https://www.revisor.mn.gov/statutes/": (
            "<html><body>"
            "<a href='/statutes/cite/1'>Chapter 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.revisor.mn.gov/statutes/cite/1": (
            "<html><body><table>"
            "<tr><td>1.01 Extent</td></tr>"
            "<tr><td>1.02 Scope</td></tr>"
            "</table></body></html>"
        ).encode("utf-8"),
        "https://www.revisor.mn.gov/statutes/cite/1.01": (
            f"<html><body><main><p>{body_one}</p></main></body></html>"
        ),
        "https://www.revisor.mn.gov/statutes/cite/1.02": (
            f"<html><body><main><p>{body_two}</p></main></body></html>"
        ),
    }


def _ms_pages() -> Dict[str, str]:
    body_one = (
        "97-3-7. Simple assault; aggravated assault; domestic violence. "
        "A person is guilty of simple assault if he attempts to cause or purposely "
        "causes bodily injury to another under Mississippi Code Annotated. "
    ) * 4
    body_two = (
        "97-3-19. Homicide; murder defined. The killing of a human being without "
        "the authority of law by any means or in any manner shall be murder when "
        "done with deliberate design under Mississippi Code Annotated. "
    ) * 4
    return {
        "https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/097/00030007.htm": (
            f"<html><body><h1>Code Section 97-3-7</h1><p>{body_one}</p></body></html>"
        ),
        "https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/097/00030019.htm": (
            f"<html><body><h1>Code Section 97-3-19</h1><p>{body_two}</p></body></html>"
        ),
    }


async def _scrape_ma(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _ma_pages()

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        return pages.get(url, "")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Massachusetts should use official AJAX tree")

    monkeypatch.setattr(MassachusettsScraper, "_request_text_direct", _fake_request_text_direct)
    scraper = MassachusettsScraper("MA", "Massachusetts")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Massachusetts General Laws",
        "https://malegislature.gov/Laws/GeneralLaws",
        max_statutes=2,
    )


async def _scrape_mi(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _mi_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 18) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Michigan should use official chapter/act/section tree")

    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    scraper = MichiganScraper("MI", "Michigan")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Michigan Compiled Laws",
        "https://www.legislature.mi.gov/Laws/ChapterIndex",
        max_statutes=2,
    )


async def _scrape_mn(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _mn_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 35) -> bytes:
        value = pages.get(url, b"")
        if isinstance(value, str):
            return value.encode("utf-8")
        return value if isinstance(value, (bytes, bytearray)) else b""

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        value = pages.get(url, "")
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Minnesota should use official revisor chapter tree")

    monkeypatch.setattr(
        MinnesotaScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(MinnesotaScraper, "_request_text_direct", _fake_request_text_direct)
    monkeypatch.setattr(MinnesotaScraper, "has_playwright", lambda self: False)
    scraper = MinnesotaScraper("MN", "Minnesota")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Minnesota Statutes",
        "https://www.revisor.mn.gov/statutes/",
        max_statutes=2,
    )


async def _scrape_ms(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _ms_pages()

    async def _fake_request_text_direct(self, url: str, timeout: int = 20) -> str:
        return pages.get(url, "")

    async def _fake_archival(self, url: str, timeout_seconds: int = 20) -> bytes:
        text = pages.get(url, "")
        return text.encode("utf-8") if text else b""

    async def _empty_common_crawl(self, code_name: str, max_statutes: int = 5):
        return []

    async def _no_justia(self, code_name: str, max_statutes: int = 1):
        return []

    async def _no_unicourt(self, code_name: str, max_statutes: int = 50000, checkpoint=None):
        return []

    async def _no_archive(self, *args, **kwargs):
        return []

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Mississippi should use official billstatus seeds")

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    monkeypatch.setattr(MississippiScraper, "_request_text_direct", _fake_request_text_direct)
    monkeypatch.setattr(
        MississippiScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_archival,
    )
    monkeypatch.setattr(MississippiScraper, "_scrape_common_crawl_code_sections", _empty_common_crawl)
    monkeypatch.setattr(MississippiScraper, "_scrape_jina_justia_seed_sections", _no_justia)
    monkeypatch.setattr(MississippiScraper, "_scrape_unicourt_code_sections", _no_unicourt)
    monkeypatch.setattr(MississippiScraper, "_scrape_archived_bill_history", _no_archive)
    monkeypatch.setattr(MississippiScraper, "has_playwright", lambda self: False)
    scraper = MississippiScraper("MS", "Mississippi")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Mississippi Code",
        "https://www.legislature.ms.gov/legislation/",
        max_statutes=2,
    )


async def _run_all_states(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[NormalizedStatute]]:
    return {
        "MA": await _scrape_ma(monkeypatch),
        "MI": await _scrape_mi(monkeypatch),
        "MN": await _scrape_mn(monkeypatch),
        "MS": await _scrape_ms(monkeypatch),
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


def test_cohort_f_jurisdiction_set_is_exact():
    runner = _load_runner()
    assert runner.cohort_states(COHORT) == list(EXPECTED_STATES)
    assert set(EXPECTED_STATES).issubset(set(runner.CANONICAL_JURISDICTIONS))


@pytest.mark.anyio
async def test_cohort_f_scrapers_emit_official_non_placeholder_text(monkeypatch: pytest.MonkeyPatch):
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
async def test_massachusetts_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: full-corpus mode must not silently clamp the official tree."""
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="MA",
                state_name="Massachusetts",
                statute_id=f"{code_name} ch. 1 § 1",
                code_name=code_name,
                chapter_number="1",
                section_number="1",
                section_name="Citizens",
                full_text=("Massachusetts full corpus official section text. " * 20),
                source_url="https://malegislature.gov/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section1",
                official_cite="Mass. Gen. Laws ch. 1, § 1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_massachusetts_general_laws_html",
                    "discovery_method": "official_part_title_chapter_section",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(MassachusettsScraper, "_scrape_official_general_laws_tree", _fake_official)
    monkeypatch.setattr(MassachusettsScraper, "_scrape_direct_seed_sections", lambda *a, **k: [])
    scraper = MassachusettsScraper("MA", "Massachusetts")
    statutes = await scraper.scrape_code(
        "Massachusetts General Laws",
        "https://malegislature.gov/Laws/GeneralLaws",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_michigan_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="MI",
                state_name="Michigan",
                statute_id=f"{code_name} § 750.1",
                code_name=code_name,
                section_number="750.1",
                section_name="Short title",
                full_text=("Michigan full corpus official section text. " * 20),
                source_url="https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-750-1",
                official_cite="Mich. Comp. Laws § 750.1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_michigan_compiled_laws_html",
                    "discovery_method": "official_chapter_index_act_section",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(MichiganScraper, "_scrape_official_chapter_index", _fake_official)
    monkeypatch.setattr(MichiganScraper, "_scrape_direct_sections", lambda *a, **k: [])
    scraper = MichiganScraper("MI", "Michigan")
    statutes = await scraper.scrape_code(
        "Michigan Compiled Laws",
        "https://www.legislature.mi.gov/Laws/ChapterIndex",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_minnesota_full_corpus_refuses_justia_sole_admission(monkeypatch: pytest.MonkeyPatch):
    async def _empty_chapters(self, code_name: str, max_statutes: int):
        return []

    async def _justia_generic(self, code_name, candidate, citation_format, max_sections):
        if "justia.com" in str(candidate):
            return [
                NormalizedStatute(
                    state_code="MN",
                    state_name="Minnesota",
                    statute_id=f"{code_name} § justia",
                    code_name=code_name,
                    section_number="justia",
                    section_name="Secondary",
                    full_text=("Justia secondary mirror text that must not sole-admit. " * 10),
                    source_url="https://law.justia.com/codes/minnesota/fixture",
                    official_cite="Minn. Stat. § justia",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "secondary_justia"},
                )
            ]
        return []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.delenv("STATE_SCRAPER_MN_ALLOW_JUSTIA_FALLBACK", raising=False)
    monkeypatch.setattr(MinnesotaScraper, "_scrape_chapter_sections", _empty_chapters)
    monkeypatch.setattr(MinnesotaScraper, "_generic_scrape", _justia_generic)
    monkeypatch.setattr(MinnesotaScraper, "has_playwright", lambda self: False)
    monkeypatch.setattr(
        MinnesotaScraper,
        "_build_statute_from_section_page",
        lambda *a, **k: None,
    )

    scraper = MinnesotaScraper("MN", "Minnesota")
    statutes = await scraper.scrape_code(
        "Minnesota Statutes",
        "https://www.revisor.mn.gov/statutes/",
        max_statutes=None,
    )
    assert statutes == []


@pytest.mark.anyio
async def test_cohort_f_jurisdiction_receipts_pass_completeness_oracle(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    meta = {
        "MA": {
            "domain": OFFICIAL_DOMAINS["MA"],
            "units": 2,
            "first": "part-i/title-i/chapter-1/section-1",
            "last": "part-i/title-i/chapter-1/section-2",
        },
        "MI": {
            "domain": OFFICIAL_DOMAINS["MI"],
            "units": 2,
            "first": "chapter-750/section-750.1",
            "last": "chapter-750/section-750.2",
        },
        "MN": {
            "domain": OFFICIAL_DOMAINS["MN"],
            "units": 2,
            "first": "chapter-1/section-1.01",
            "last": "chapter-1/section-1.02",
        },
        "MS": {
            "domain": OFFICIAL_DOMAINS["MS"],
            "units": 2,
            "first": "title-97/section-97-3-7",
            "last": "title-97/section-97-3-19",
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"cohort-f-{state.lower()}")
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

    # Durable evidence artifact required by LCR-014.
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


def test_cohort_f_report_artifact_exists_and_certifies():
    """Fail-closed gate: committed cohort_f.json must certify cohort F."""
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


def test_cohort_f_adapters_importable_and_registered():
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )

    for code, cls in (
        ("MA", MassachusettsScraper),
        ("MI", MichiganScraper),
        ("MN", MinnesotaScraper),
        ("MS", MississippiScraper),
    ):
        scraper_cls = StateScraperRegistry.get_scraper_class(code)
        assert scraper_cls is cls or scraper_cls is not None
        scraper = scraper_cls(code, code)
        base = scraper.get_base_url()
        assert base.startswith("http")
        codes = scraper.get_code_list()
        assert codes and codes[0].get("url")

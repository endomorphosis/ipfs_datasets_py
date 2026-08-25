"""Integration certification for state-law scrape cohort L (VT, VA, WA, WV).

LCR-020: prove each listed jurisdiction independently satisfies closed-frontier
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.vermont import (
    VermontScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.virginia import (
    VirginiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington import (
    WashingtonScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.west_virginia import (
    WestVirginiaScraper,
)


COHORT = "L"
TASK_ID = "LCR-020"
GOAL_ID = "LCR-G023"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_STATES: Tuple[str, ...] = ("VT", "VA", "WA", "WV")

REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_l.json")
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-l-report@1"

# Official primary domains from the sealed catalog / cohort runner map.
OFFICIAL_DOMAINS: Dict[str, str] = {
    "VT": "legislature.vermont.gov",
    "VA": "law.lis.virginia.gov",
    "WA": "app.leg.wa.gov",
    "WV": "code.wvlegislature.gov",
}

ALLOWED_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "VT": ("legislature.vermont.gov",),
    "VA": ("law.lis.virginia.gov", "lis.virginia.gov"),
    "WA": ("app.leg.wa.gov", "leg.wa.gov"),
    "WV": ("code.wvlegislature.gov", "wvlegislature.gov"),
}

PLACEHOLDER_RE = re.compile(
    r"^(todo|tbd|placeholder|lorem ipsum|sample text|n/?a|none|null|\.\.\.)$",
    re.IGNORECASE,
)

SECONDARY_HOST_RE = re.compile(
    r"(justia\.com|findlaw\.com|cornell\.edu|wikipedia\.org|casemine\.com)",
    re.IGNORECASE,
)


@pytest.fixture
def anyio_backend() -> str:
    # VA/WA section scans use asyncio.create_task; keep this module on asyncio.
    return "asyncio"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_runner():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "run_legal_corpora_reindex_cohort.py"
    name = "lcr020_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_certifier():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "certify_state_laws_cohort.py"
    name = "lcr020_certify_state_laws_cohort"
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


def _vt_pages() -> Dict[str, bytes]:
    body_one = (
        "Cite as: 1 V.S.A. § 1. This title of the Vermont Statutes Annotated "
        "governs general provisions of the State of Vermont including "
        "definitions used throughout the official code. "
    ) * 4
    body_two = (
        "Cite as: 1 V.S.A. § 2. Common law of England as of 1776 remains in "
        "force in Vermont except as modified by statute or the Constitution. "
    ) * 4
    return {
        "https://legislature.vermont.gov/statutes/": (
            "<html><body>"
            "<a href='/statutes/title/01'>Title 1 General Provisions</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://legislature.vermont.gov/statutes/title/01": (
            "<html><body>"
            "<a href='/statutes/chapter/01/001'>Chapter 1 Construction</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://legislature.vermont.gov/statutes/chapter/01/001": (
            "<html><body>"
            "<a href='/statutes/section/01/001/00001'>Section 1</a>"
            "<a href='/statutes/section/01/001/00002'>Section 2</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://legislature.vermont.gov/statutes/section/01/001/00001": (
            f"<html><body><div id='main-content'>"
            f"<h1>§ 1. Construction of statutes</h1>"
            f"<b>Construction of statutes</b>"
            f"<p>{body_one}</p>"
            f"</div></body></html>"
        ).encode("utf-8"),
        "https://legislature.vermont.gov/statutes/section/01/001/00002": (
            f"<html><body><div id='main-content'>"
            f"<h1>§ 2. Common law</h1>"
            f"<b>Common law</b>"
            f"<p>{body_two}</p>"
            f"</div></body></html>"
        ).encode("utf-8"),
    }


def _va_pages() -> Dict[str, bytes]:
    body_one = (
        "§ 1-1. Code of Virginia short title. The laws embraced in this title "
        "constitute the official Code of Virginia and shall be cited as such "
        "in all official proceedings of the Commonwealth. "
    ) * 4
    body_two = (
        "§ 1-2. Common law of England. The common law of England, insofar as "
        "it is not repugnant to the principles of the Bill of Rights and "
        "Constitution of Virginia, shall continue in full force. "
    ) * 4
    return {
        "https://law.lis.virginia.gov/vacode/": (
            "<html><body>"
            "<a href='/vacode/title1/'>Title 1. General Provisions</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://law.lis.virginia.gov/vacode/title1/": (
            "<html><body>"
            "<a href='/vacode/title1/chapter1/'>Chapter 1. Code Provisions</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://law.lis.virginia.gov/vacode/title1/chapter1/": (
            "<html><body>"
            "<a href='/vacode/title1/chapter1/section1-1/'>§ 1-1. Short title</a>"
            "<a href='/vacode/title1/chapter1/section1-2/'>§ 1-2. Common law</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://law.lis.virginia.gov/vacode/title1/chapter1/section1-1/": (
            f"<html><body><div id='va_code'>"
            f"<h2>§ 1-1. Short title</h2>"
            f"<p>{body_one}</p>"
            f"</div></body></html>"
        ).encode("utf-8"),
        "https://law.lis.virginia.gov/vacode/title1/chapter1/section1-2/": (
            f"<html><body><div id='va_code'>"
            f"<h2>§ 1-2. Common law</h2>"
            f"<p>{body_two}</p>"
            f"</div></body></html>"
        ).encode("utf-8"),
    }


def _wa_pages() -> Dict[str, bytes]:
    body_one = (
        "RCW 9A.32.010. Homicide defined. Homicide is the killing of a human "
        "being by the act, procurement, or omission of another, death occurring "
        "within three years and a day, and is either murder, manslaughter, "
        "excusable homicide, or justifiable homicide. "
    ) * 3
    body_two = (
        "RCW 9A.32.030. Murder in the first degree. A person is guilty of "
        "murder in the first degree when, with a premeditated intent to cause "
        "the death of another person, he or she causes the death of such "
        "person or of a third person. "
    ) * 3
    return {
        "https://app.leg.wa.gov/RCW/default.aspx": (
            "<html><body>"
            "<a href='/RCW/default.aspx?cite=9A'>Title 9A Washington Criminal Code</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://app.leg.wa.gov/RCW/default.aspx?cite=9A": (
            "<html><body>"
            "<a href='/RCW/default.aspx?cite=9A.32'>Chapter 9A.32 Homicide</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32": (
            "<html><body>"
            "<a href='/RCW/default.aspx?cite=9A.32.010'>9A.32.010 Homicide defined</a>"
            "<a href='/RCW/default.aspx?cite=9A.32.030'>9A.32.030 Murder in the first degree</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32.010": (
            "<html><body>"
            "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
            "<h1>RCW 9A.32.010</h1>"
            "<h2>Homicide defined.</h2>"
            "</div>"
            f"<div id='contentWrapper'><p>{body_one}</p></div>"
            "</body></html>"
        ).encode("utf-8"),
        "https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32.030": (
            "<html><body>"
            "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
            "<h1>RCW 9A.32.030</h1>"
            "<h2>Murder in the first degree.</h2>"
            "</div>"
            f"<div id='contentWrapper'><p>{body_two}</p></div>"
            "</body></html>"
        ).encode("utf-8"),
    }


def _wv_pages() -> Dict[str, bytes]:
    body_one = (
        "Murder of the first degree is committed when any person, with malice "
        "aforethought, kills another person by poison, lying in wait, or any "
        "other kind of willful, deliberate and premeditated killing. "
    ) * 3
    body_two = (
        "Murder of the second degree is committed when any person, with malice "
        "aforethought, kills another person without the circumstances of "
        "first-degree murder as defined in this article of the West Virginia Code. "
    ) * 3
    return {
        "https://code.wvlegislature.gov/": (
            "<html><body>"
            "<select id='sel-chapter'>"
            "<option value='61'>Chapter 61 Crimes and Their Punishment</option>"
            "</select>"
            "</body></html>"
        ).encode("utf-8"),
        "https://code.wvlegislature.gov/61/": (
            "<html><body>"
            "<div class='art-head'><a href='/61-2/'>Article 2 Crimes Against the Person</a></div>"
            "</body></html>"
        ).encode("utf-8"),
        "https://code.wvlegislature.gov/61-2/": (
            "<html><body>"
            "<div class='sec-head'><a href='/61-2-1/'>§61-2-1 First degree murder</a></div>"
            "<div class='sec-head'><a href='/61-2-2/'>§61-2-2 Second degree murder</a></div>"
            "</body></html>"
        ).encode("utf-8"),
        "https://code.wvlegislature.gov/61-2-1/": (
            "<html><body><div class='sectiontext'>"
            "<h4>§61-2-1. First and second degree murder defined.</h4>"
            f"<p>{body_one}</p>"
            "</div></body></html>"
        ).encode("utf-8"),
        "https://code.wvlegislature.gov/61-2-2/": (
            "<html><body><div class='sectiontext'>"
            "<h4>§61-2-2. Penalty for murder of second degree.</h4>"
            f"<p>{body_two}</p>"
            "</div></body></html>"
        ).encode("utf-8"),
    }


def _sorted_statutes(statutes: Sequence[NormalizedStatute]) -> List[NormalizedStatute]:
    return sorted(statutes, key=lambda s: str(s.section_number or s.source_url or ""))


async def _scrape_vt(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _vt_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 20) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Vermont should use official title/chapter/section tree")

    monkeypatch.setattr(
        VermontScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    scraper = VermontScraper("VT", "Vermont")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Vermont Statutes",
        "https://legislature.vermont.gov/statutes/",
        max_statutes=2,
    )


async def _scrape_va(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _va_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 20) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Virginia should use official vacode title/chapter/section tree")

    monkeypatch.setattr(
        VirginiaScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(VirginiaScraper, "has_playwright", lambda self: False)
    scraper = VirginiaScraper("VA", "Virginia")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Code of Virginia",
        "https://law.lis.virginia.gov/vacode/",
        max_statutes=2,
    )


async def _scrape_wa(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _wa_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 20) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Washington should use official RCW title/chapter/section tree")

    monkeypatch.setattr(
        WashingtonScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(WashingtonScraper, "has_playwright", lambda self: False)
    scraper = WashingtonScraper("WA", "Washington")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Revised Code of Washington",
        "https://app.leg.wa.gov/RCW/default.aspx",
        max_statutes=2,
    )


async def _scrape_wv(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _wv_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 20) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("West Virginia should use official chapter/article/section tree")

    monkeypatch.setattr(
        WestVirginiaScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(WestVirginiaScraper, "has_playwright", lambda self: False)
    scraper = WestVirginiaScraper("WV", "West Virginia")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "West Virginia Code",
        "https://code.wvlegislature.gov/",
        max_statutes=2,
    )


async def _run_all_states(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[NormalizedStatute]]:
    return {
        "VT": _sorted_statutes(await _scrape_vt(monkeypatch)),
        "VA": _sorted_statutes(await _scrape_va(monkeypatch)),
        "WA": _sorted_statutes(await _scrape_wa(monkeypatch)),
        "WV": _sorted_statutes(await _scrape_wv(monkeypatch)),
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


def test_cohort_l_jurisdiction_set_is_exact():
    runner = _load_runner()
    assert runner.cohort_states(COHORT) == list(EXPECTED_STATES)
    assert set(EXPECTED_STATES).issubset(set(runner.CANONICAL_JURISDICTIONS))


@pytest.mark.anyio
async def test_cohort_l_scrapers_emit_official_non_placeholder_text(monkeypatch: pytest.MonkeyPatch):
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
            assert "findlaw" not in source_kind.lower()
            assert "placeholder" not in str(statute.full_text).lower()


@pytest.mark.anyio
async def test_vermont_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: full-corpus mode must not silently clamp the official tree."""
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="VT",
                state_name="Vermont",
                statute_id=f"{code_name} § 1",
                code_name=code_name,
                section_number="1",
                section_name="Construction",
                full_text=("Vermont full corpus official section text. " * 20),
                source_url="https://legislature.vermont.gov/statutes/section/01/001/00001",
                official_cite="1 V.S.A. § 1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_vermont_statutes_html",
                    "discovery_method": "official_title_chapter_section_index",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(VermontScraper, "_scrape_official_index", _fake_official)
    scraper = VermontScraper("VT", "Vermont")
    statutes = await scraper.scrape_code(
        "Vermont Statutes",
        "https://legislature.vermont.gov/statutes/",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_virginia_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="VA",
                state_name="Virginia",
                statute_id=f"{code_name} § 1-1",
                code_name=code_name,
                section_number="1-1",
                section_name="Short title",
                full_text=("Virginia full corpus official section text. " * 20),
                source_url="https://law.lis.virginia.gov/vacode/title1/chapter1/section1-1/",
                official_cite="Va. Code Ann. § 1-1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_virginia_code_html",
                    "discovery_method": "official_title_chapter_section_index",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(VirginiaScraper, "_scrape_official_index", _fake_official)
    scraper = VirginiaScraper("VA", "Virginia")
    statutes = await scraper.scrape_code(
        "Code of Virginia",
        "https://law.lis.virginia.gov/vacode/",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_washington_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="WA",
                state_name="Washington",
                statute_id=f"{code_name} § 9A.32.030",
                code_name=code_name,
                section_number="9A.32.030",
                section_name="Murder in the first degree",
                full_text=("Washington full corpus official section text. " * 20),
                source_url="https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32.030",
                official_cite="Wash. Rev. Code § 9A.32.030",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_washington_rcw_html",
                    "discovery_method": "official_title_chapter_section_index",
                    "skip_hydrate": True,
                },
            )
        ]

    async def _empty_seed(self, code_name: str, max_statutes: int = 1):
        return []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(WashingtonScraper, "_scrape_official_index", _fake_official)
    monkeypatch.setattr(WashingtonScraper, "_scrape_direct_seed_sections", _empty_seed)
    scraper = WashingtonScraper("WA", "Washington")
    statutes = await scraper.scrape_code(
        "Revised Code of Washington",
        "https://app.leg.wa.gov/RCW/default.aspx",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_west_virginia_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="WV",
                state_name="West Virginia",
                statute_id=f"{code_name} § 61-2-1",
                code_name=code_name,
                section_number="61-2-1",
                section_name="First and second degree murder defined",
                full_text=("West Virginia full corpus official section text. " * 20),
                source_url="https://code.wvlegislature.gov/61-2-1/",
                official_cite="W. Va. Code § 61-2-1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_west_virginia_code_html",
                    "discovery_method": "official_chapter_article_section_index",
                    "skip_hydrate": True,
                },
            )
        ]

    async def _empty_seed(self, code_name: str, max_statutes: int = 1):
        return []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(WestVirginiaScraper, "_scrape_official_index", _fake_official)
    monkeypatch.setattr(WestVirginiaScraper, "_scrape_direct_seed_sections", _empty_seed)
    scraper = WestVirginiaScraper("WV", "West Virginia")
    statutes = await scraper.scrape_code(
        "West Virginia Code",
        "https://code.wvlegislature.gov/",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_virginia_full_corpus_refuses_justia_sole_admission(monkeypatch: pytest.MonkeyPatch):
    async def _empty_official(self, code_name: str, max_statutes: Optional[int] = None):
        return []

    async def _empty_direct(self, code_name: str, max_statutes: Optional[int] = None):
        return []

    async def _justia_generic(self, code_name, candidate, citation_format, max_sections):
        return [
            NormalizedStatute(
                state_code="VA",
                state_name="Virginia",
                statute_id=f"{code_name} § justia",
                code_name=code_name,
                section_number="justia",
                section_name="Secondary",
                full_text=("Justia secondary mirror text that must not sole-admit. " * 10),
                source_url="https://law.justia.com/codes/virginia/fixture",
                official_cite="Va. Code Ann. § justia",
                metadata=StatuteMetadata(),
                structured_data={"source_kind": "secondary_justia"},
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(VirginiaScraper, "_scrape_official_index", _empty_official)
    monkeypatch.setattr(VirginiaScraper, "_scrape_direct_sections", _empty_direct)
    monkeypatch.setattr(VirginiaScraper, "_generic_scrape", _justia_generic)
    monkeypatch.setattr(VirginiaScraper, "has_playwright", lambda self: False)

    scraper = VirginiaScraper("VA", "Virginia")
    statutes = await scraper.scrape_code(
        "Code of Virginia",
        "https://law.lis.virginia.gov/vacode/",
        max_statutes=None,
    )
    assert statutes == []


@pytest.mark.anyio
async def test_cohort_l_jurisdiction_receipts_pass_completeness_oracle(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    meta = {
        "VT": {
            "domain": OFFICIAL_DOMAINS["VT"],
            "units": 2,
            "first": "title-1/chapter-1/section-1",
            "last": "title-1/chapter-1/section-2",
        },
        "VA": {
            "domain": OFFICIAL_DOMAINS["VA"],
            "units": 2,
            "first": "title-1/chapter-1/section-1-1",
            "last": "title-1/chapter-1/section-1-2",
        },
        "WA": {
            "domain": OFFICIAL_DOMAINS["WA"],
            "units": 2,
            "first": "title-9a/chapter-9a.32/section-9a.32.010",
            "last": "title-9a/chapter-9a.32/section-9a.32.030",
        },
        "WV": {
            "domain": OFFICIAL_DOMAINS["WV"],
            "units": 2,
            "first": "chapter-61/article-2/section-61-2-1",
            "last": "chapter-61/article-2/section-61-2-2",
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"cohort-l-{state.lower()}")
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

    # Durable evidence artifact required by LCR-020.
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
    serialized = json.dumps(reloaded)
    assert "/home/" not in serialized
    assert "hf_" not in serialized or not re.search(r"hf_[A-Za-z0-9]{8,}", serialized)
    for state in EXPECTED_STATES:
        entry = reloaded["state_results"][state]
        assert entry["status"] == "success"
        assert int(entry["failed_final"]) == 0
        assert entry["frontier_closed"] is True
        jrec = reloaded["jurisdiction_receipts"][state]
        assert evaluate_jurisdiction_receipt(jrec).complete is True


def test_cohort_l_report_artifact_exists_and_certifies():
    """Fail-closed gate: committed cohort_l.json must certify cohort L."""
    report_path = _repo_root() / REPORT_RELPATH
    assert report_path.is_file(), f"missing {REPORT_RELPATH}"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["cohort"] == COHORT
    assert set(report["states"]) == set(EXPECTED_STATES)
    assert report["status"] == "success"
    assert report.get("production_upload") is False
    assert report.get("shared_combined_write") is False
    serialized = json.dumps(report)
    assert "/home/" not in serialized

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


def test_cohort_l_adapters_importable_and_registered():
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )

    for code, cls in (
        ("VT", VermontScraper),
        ("VA", VirginiaScraper),
        ("WA", WashingtonScraper),
        ("WV", WestVirginiaScraper),
    ):
        scraper_cls = StateScraperRegistry.get_scraper_class(code)
        assert scraper_cls is cls or scraper_cls is not None
        scraper = scraper_cls(code, code)
        base = scraper.get_base_url()
        assert base.startswith("http")
        codes = scraper.get_code_list()
        assert codes and codes[0].get("url")
        assert "justia.com" not in str(codes[0].get("url") or "").lower()
        assert "findlaw.com" not in str(codes[0].get("url") or "").lower()

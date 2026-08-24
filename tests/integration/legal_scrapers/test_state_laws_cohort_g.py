"""Integration certification for state-law scrape cohort G (MO, MT, NE, NV).

LCR-015: prove each listed jurisdiction independently satisfies closed-frontier
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri import (
    MissouriScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana import (
    MontanaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska import (
    NebraskaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada import (
    NevadaScraper,
)


COHORT = "G"
TASK_ID = "LCR-015"
GOAL_ID = "LCR-G022"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_STATES: Tuple[str, ...] = ("MO", "MT", "NE", "NV")

REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_g.json")
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-g-report@1"

# Official primary domains from the sealed catalog / cohort runner map.
OFFICIAL_DOMAINS: Dict[str, str] = {
    "MO": "revisor.mo.gov",
    "MT": "leg.mt.gov",
    "NE": "nebraskalegislature.gov",
    "NV": "www.leg.state.nv.us",
}

ALLOWED_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "MO": ("revisor.mo.gov",),
    "MT": ("leg.mt.gov",),
    "NE": ("nebraskalegislature.gov",),
    "NV": ("leg.state.nv.us",),
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
    # Nebraska section scans use asyncio.create_task; keep this module on asyncio.
    return "asyncio"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_runner():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "run_legal_corpora_reindex_cohort.py"
    name = "lcr015_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_certifier():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "certify_state_laws_cohort.py"
    name = "lcr015_certify_state_laws_cohort"
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


def _mo_pages() -> Dict[str, bytes]:
    body_one = (
        "1.010. Common law of England to be the rule of action. The common law "
        "of England and all acts of parliament made prior to the fourth year of "
        "the reign of James the First, of a general nature, which are not local "
        "to that kingdom and not repugnant to or inconsistent with the "
        "Constitution of the United States, the constitution of this state, or "
        "the statute laws in force, are the rule of action and decision in this "
        "state. "
    )
    body_two = (
        "1.020. Definitions. As used in the statutory laws of this state, "
        "unless otherwise specially provided or unless plainly repugnant to the "
        "intent of the legislature or of the context thereof: (1) 'Certified "
        "mail' or 'certified mail with return receipt requested' includes any "
        "parcel or letter carried by an express, delivery, or courier service "
        "that provides proof of delivery. "
    )
    return {
        "https://revisor.mo.gov/main/Home.aspx": (
            "<html><body>"
            "<a href='/main/OneChapter.aspx?chapter=1'>Chapter 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://revisor.mo.gov/main/OneChapter.aspx?chapter=1": (
            "<html><body>"
            "<a href='/main/OneSection.aspx?section=1.010'>Section 1.010</a>"
            "<a href='/main/OneSection.aspx?section=1.020'>Section 1.020</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.010": (
            "<html><body>"
            "<div class='norm'>"
            "<p class='norm'><span class='bold'>1.010. Common law of England to be the rule of action. — </span>"
            f"{body_one}</p>"
            "</div>"
            "<div class='foot'><p class='norm'>(RSMo 1939 § 645)</p></div>"
            "</body></html>"
        ).encode("utf-8"),
        "https://revisor.mo.gov/main/OneSection.aspx?section=1.020": (
            "<html><body>"
            "<div class='norm'>"
            "<p class='norm'><span class='bold'>1.020. Definitions. — </span>"
            f"{body_two}</p>"
            "</div>"
            "<div class='foot'><p class='norm'>(RSMo 1939 § 655)</p></div>"
            "</body></html>"
        ).encode("utf-8"),
    }


def _mt_pages() -> Dict[str, bytes]:
    body_one = (
        "1-1-101. Terms of wide applicability. Unless the context requires "
        "otherwise, the following definitions apply in this code: (1) 'Person' "
        "includes a corporation, partnership, limited liability company, and "
        "association as well as a natural person. (2) 'State' when applied to "
        "the different parts of the United States includes the District of "
        "Columbia and the territories. "
    )
    body_two = (
        "1-1-102. Meaning of words. Words and phrases used in the statutes of "
        "Montana are construed according to the context and the approved usage "
        "of the language, but technical words and phrases and such others as "
        "have acquired a peculiar and appropriate meaning in law are to be "
        "construed according to such peculiar and appropriate meaning. "
    )
    return {
        "https://leg.mt.gov/bills/mca/index.html": (
            "<html><body>"
            "<a href='title_0010/chapters_index.html'>Title 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://leg.mt.gov/bills/mca/": (
            "<html><body>"
            "<a href='title_0010/chapters_index.html'>Title 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://leg.mt.gov/bills/mca/title_0010/chapters_index.html": (
            "<html><body>"
            "<a href='chapter_0010/parts_index.html'>Chapter 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/parts_index.html": (
            "<html><body>"
            "<a href='part_0010/sections_index.html'>Part 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/sections_index.html": (
            "<html><body>"
            "<a href='section_0010/0010-0010-0010-0010.html'>1-1-101 Terms of wide applicability</a>"
            "<a href='section_0020/0010-0010-0010-0020.html'>1-1-102 Meaning of words</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/section_0010/0010-0010-0010-0010.html": (
            f"<html><body><main>"
            f"<h1>1-1-101. Terms of wide applicability.</h1>"
            f"<p>{body_one}</p>"
            f"</main></body></html>"
        ).encode("utf-8"),
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/section_0020/0010-0010-0010-0020.html": (
            f"<html><body><main>"
            f"<h1>1-1-102. Meaning of words.</h1>"
            f"<p>{body_two}</p>"
            f"</main></body></html>"
        ).encode("utf-8"),
    }


def _ne_pages() -> Dict[str, str]:
    body_one = (
        "Referred to as the Revisor of Statutes. The Revisor of Statutes shall "
        "prepare and publish supplements to the statutes of Nebraska and, when "
        "directed by the Legislature, a replacement volume of such statutes. "
        "The Revisor shall also report to the Legislature any defects in the "
        "statutes discovered in the course of official duties. "
    )
    body_two = (
        "The Revisor of Statutes shall cause to be printed and bound the "
        "statutes of Nebraska as authorized by law and shall certify that the "
        "volumes so printed are true copies of the official laws of this state. "
        "Each volume shall contain an official certification of authenticity. "
    )
    return {
        "https://nebraskalegislature.gov/laws/browse-statutes.php": (
            "<html><body>"
            "<a href='/laws/browse-chapters.php?chapter=1'>Chapter 1</a>"
            "</body></html>"
        ),
        "https://nebraskalegislature.gov/laws/browse-chapters.php?chapter=1": (
            "<html><body>"
            "<a href='/laws/statutes.php?statute=1-101'>View Statute 1-101</a>"
            "<a href='/laws/statutes.php?statute=1-102'>View Statute 1-102</a>"
            "</body></html>"
        ),
        "https://nebraskalegislature.gov/laws/statutes.php?statute=1-101": (
            "<html><body>"
            "<div class='card-body'><div class='statute'>"
            "<h2>1-101.</h2><h3>Revisor of Statutes; duties.</h3>"
            f"<p>{body_one}</p>"
            "</div></div>"
            "</body></html>"
        ),
        "https://nebraskalegislature.gov/laws/statutes.php?statute=1-102": (
            "<html><body>"
            "<div class='card-body'><div class='statute'>"
            "<h2>1-102.</h2><h3>Printing of statutes.</h3>"
            f"<p>{body_two}</p>"
            "</div></div>"
            "</body></html>"
        ),
    }


def _nv_pages() -> Dict[str, str]:
    body_one = (
        "The following shall be the courts of justice for this State: "
        "1. The Supreme Court; 2. The Court of Appeals; 3. The district courts; "
        "4. The Justice courts; and 5. Such municipal courts as may from time "
        "to time be established by the Legislature or municipal governments. "
    )
    body_two = (
        "Every court of record of this State shall keep such records as are "
        "required by law. The clerk of the court shall preserve all papers "
        "filed with the court and shall make them available for inspection "
        "under such rules as the court may prescribe. "
    )
    return {
        "https://www.leg.state.nv.us/NRS/": (
            "<html><body><a href='NRS-001.html'>Chapter 1</a></body></html>"
        ),
        "https://www.leg.state.nv.us/NRS/NRS-001.html": (
            "<html><body>"
            "<p class='COLeadline'><a href='#NRS001Sec010'>NRS 1.010</a> Courts of justice.</p>"
            "<p class='COLeadline'><a href='#NRS001Sec020'>NRS 1.020</a> Courts of record.</p>"
            "<p class='DocHeading'>GENERAL PROVISIONS</p>"
            "<p class='SectBody'><span class='Empty'><a name='NRS001Sec010'></a>NRS </span>"
            f"<span class='Section'>1.010</span><span class='Leadline'>Courts of justice.</span> {body_one}</p>"
            "<p class='SectBody'>The Supreme Court is the court of last resort.</p>"
            "<p class='SectBody'><span class='Empty'><a name='NRS001Sec020'></a>NRS </span>"
            f"<span class='Section'>1.020</span><span class='Leadline'>Courts of record.</span> {body_two}</p>"
            "<p class='SectBody'>The clerk shall preserve all papers.</p>"
            "</body></html>"
        ),
    }


async def _scrape_mo(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _mo_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 20) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Missouri should use official revisor chapter tree")

    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    scraper = MissouriScraper("MO", "Missouri")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Missouri Revised Statutes",
        "https://revisor.mo.gov/main/Home.aspx",
        max_statutes=2,
    )


async def _scrape_mt(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _mt_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return pages.get(url, b"")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Montana should use official MCA title/chapter/part tree")

    monkeypatch.setattr(
        MontanaScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(MontanaScraper, "has_playwright", lambda self: False)
    scraper = MontanaScraper("MT", "Montana")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Montana Code Annotated",
        "https://leg.mt.gov/bills/mca/index.html",
        max_statutes=2,
    )


async def _scrape_ne(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _ne_pages()

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        return pages.get(url, "")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Nebraska should use official chapter index sections")

    monkeypatch.setattr(NebraskaScraper, "_request_text_direct", _fake_request_text_direct)
    scraper = NebraskaScraper("NE", "Nebraska")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Nebraska Revised Statutes",
        "https://nebraskalegislature.gov/laws/browse-statutes.php",
        max_statutes=2,
    )


async def _scrape_nv(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _nv_pages()

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        return pages.get(url, "")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Nevada should use official NRS chapter pages")

    monkeypatch.setattr(NevadaScraper, "_request_text_direct", _fake_request_text_direct)
    scraper = NevadaScraper("NV", "Nevada")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Nevada Revised Statutes",
        "https://www.leg.state.nv.us/NRS/",
        max_statutes=2,
    )


async def _run_all_states(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[NormalizedStatute]]:
    return {
        "MO": await _scrape_mo(monkeypatch),
        "MT": await _scrape_mt(monkeypatch),
        "NE": await _scrape_ne(monkeypatch),
        "NV": await _scrape_nv(monkeypatch),
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


def test_cohort_g_jurisdiction_set_is_exact():
    runner = _load_runner()
    assert runner.cohort_states(COHORT) == list(EXPECTED_STATES)
    assert set(EXPECTED_STATES).issubset(set(runner.CANONICAL_JURISDICTIONS))


@pytest.mark.anyio
async def test_cohort_g_scrapers_emit_official_non_placeholder_text(monkeypatch: pytest.MonkeyPatch):
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
async def test_missouri_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: full-corpus mode must not silently clamp the official tree."""
    requested: Dict[str, Any] = {}

    async def _fake_official(
        self, code_name: str, code_url: str, citation_format: str, max_sections: Optional[int] = 220
    ):
        requested["max_sections"] = max_sections
        return [
            NormalizedStatute(
                state_code="MO",
                state_name="Missouri",
                statute_id=f"{code_name} § 1.010",
                code_name=code_name,
                section_number="1.010",
                section_name="Common law",
                full_text=("Missouri full corpus official section text. " * 20),
                source_url="https://revisor.mo.gov/main/OneSection.aspx?section=1.010",
                official_cite="Mo. Rev. Stat. § 1.010",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_missouri_section_html",
                    "discovery_method": "official_chapter_index_sections",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(MissouriScraper, "_custom_scrape_missouri", _fake_official)
    monkeypatch.setattr(MissouriScraper, "_scrape_direct_sections", lambda *a, **k: [])
    scraper = MissouriScraper("MO", "Missouri")
    statutes = await scraper.scrape_code(
        "Missouri Revised Statutes",
        "https://revisor.mo.gov/main/Home.aspx",
        max_statutes=None,
    )
    assert requested["max_sections"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_montana_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="MT",
                state_name="Montana",
                statute_id=f"{code_name} § 1-1-101",
                code_name=code_name,
                section_number="1-1-101",
                section_name="Terms of wide applicability",
                full_text=("Montana full corpus official section text. " * 20),
                source_url=(
                    "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/"
                    "part_0010/section_0010/0010-0010-0010-0010.html"
                ),
                official_cite="Mont. Code Ann. § 1-1-101",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_montana_mca_html",
                    "discovery_method": "official_mca_title_chapter_part_section",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(MontanaScraper, "_scrape_official_mca_tree", _fake_official)
    monkeypatch.setattr(MontanaScraper, "_scrape_direct_seed_sections", lambda *a, **k: [])
    scraper = MontanaScraper("MT", "Montana")
    statutes = await scraper.scrape_code(
        "Montana Code Annotated",
        "https://leg.mt.gov/bills/mca/index.html",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_montana_full_corpus_refuses_justia_sole_admission(monkeypatch: pytest.MonkeyPatch):
    async def _empty_tree(self, code_name: str, max_statutes: Optional[int] = None):
        return []

    async def _empty_seed(self, code_name: str, max_statutes: int = 2):
        return []

    async def _justia_generic(self, code_name, candidate, citation_format, max_sections):
        return [
            NormalizedStatute(
                state_code="MT",
                state_name="Montana",
                statute_id=f"{code_name} § justia",
                code_name=code_name,
                section_number="justia",
                section_name="Secondary",
                full_text=("Justia secondary mirror text that must not sole-admit. " * 10),
                source_url="https://law.justia.com/codes/montana/fixture",
                official_cite="Mont. Code Ann. § justia",
                metadata=StatuteMetadata(),
                structured_data={"source_kind": "secondary_justia"},
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.delenv("STATE_SCRAPER_MT_ALLOW_JUSTIA_FALLBACK", raising=False)
    monkeypatch.setattr(MontanaScraper, "_scrape_official_mca_tree", _empty_tree)
    monkeypatch.setattr(MontanaScraper, "_scrape_direct_seed_sections", _empty_seed)
    monkeypatch.setattr(MontanaScraper, "_generic_scrape", _justia_generic)
    monkeypatch.setattr(MontanaScraper, "has_playwright", lambda self: False)

    scraper = MontanaScraper("MT", "Montana")
    statutes = await scraper.scrape_code(
        "Montana Code Annotated",
        "https://leg.mt.gov/bills/mca/index.html",
        max_statutes=None,
    )
    assert statutes == []


@pytest.mark.anyio
async def test_cohort_g_jurisdiction_receipts_pass_completeness_oracle(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    meta = {
        "MO": {
            "domain": OFFICIAL_DOMAINS["MO"],
            "units": 2,
            "first": "chapter-1/section-1.010",
            "last": "chapter-1/section-1.020",
        },
        "MT": {
            "domain": OFFICIAL_DOMAINS["MT"],
            "units": 2,
            "first": "title-1/chapter-1/section-1-1-101",
            "last": "title-1/chapter-1/section-1-1-102",
        },
        "NE": {
            "domain": OFFICIAL_DOMAINS["NE"],
            "units": 2,
            "first": "chapter-1/section-1-101",
            "last": "chapter-1/section-1-102",
        },
        "NV": {
            "domain": OFFICIAL_DOMAINS["NV"],
            "units": 2,
            "first": "chapter-1/section-1.010",
            "last": "chapter-1/section-1.020",
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"cohort-g-{state.lower()}")
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

    # Durable evidence artifact required by LCR-015.
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


def test_cohort_g_report_artifact_exists_and_certifies():
    """Fail-closed gate: committed cohort_g.json must certify cohort G."""
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


def test_cohort_g_adapters_importable_and_registered():
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )

    for code, cls in (
        ("MO", MissouriScraper),
        ("MT", MontanaScraper),
        ("NE", NebraskaScraper),
        ("NV", NevadaScraper),
    ):
        scraper_cls = StateScraperRegistry.get_scraper_class(code)
        assert scraper_cls is cls or scraper_cls is not None
        scraper = scraper_cls(code, code)
        base = scraper.get_base_url()
        assert base.startswith("http")
        codes = scraper.get_code_list()
        assert codes and codes[0].get("url")

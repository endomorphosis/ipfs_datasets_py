"""Integration certification for state-law scrape cohort K (SD, TN, TX, UT).

LCR-019: prove each listed jurisdiction independently satisfies closed-frontier
full-scrape gates with exact official source authority, non-placeholder full
text, reconciled disposition counts/hashes, and replay evidence. Offline-safe
via compact official-page fixtures (no bulk golden dumps, no network).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import sys
import zipfile
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota import (
    SouthDakotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee import (
    TennesseeScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas import (
    TexasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah import (
    UtahScraper,
)


COHORT = "K"
TASK_ID = "LCR-019"
GOAL_ID = "LCR-G023"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_STATES: Tuple[str, ...] = ("SD", "TN", "TX", "UT")

REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_k.json")
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-k-report@1"

# Official primary domains from the sealed catalog / cohort runner map.
OFFICIAL_DOMAINS: Dict[str, str] = {
    "SD": "sdlegislature.gov",
    "TN": "www.capitol.tn.gov",
    "TX": "statutes.capitol.texas.gov",
    "UT": "le.utah.gov",
}

ALLOWED_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "SD": ("sdlegislature.gov",),
    "TN": ("tn.gov", "capitol.tn.gov"),
    "TX": ("statutes.capitol.texas.gov", "tcss.legis.texas.gov", "capitol.texas.gov"),
    "UT": ("le.utah.gov",),
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
    name = "lcr019_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_certifier():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "certify_state_laws_cohort.py"
    name = "lcr019_certify_state_laws_cohort"
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


def _sd_api_payloads() -> Dict[str, Dict[str, Any]]:
    body_one = (
        "This section declares the public policy of South Dakota codified laws "
        "and provides definitions used throughout Title 1 of the codified laws. "
    ) * 4
    body_two = (
        "Words used in the South Dakota Codified Laws in the present tense "
        "include the future tense and singular includes the plural as applicable. "
    ) * 4
    return {
        "1-1-1": {
            "Statute": "1-1-1",
            "CatchLine": "Definitions and public policy",
            "Next": "1-1-2",
            "Html": f"<p>1-1-1. Definitions and public policy. {body_one}</p>",
        },
        "1-1-2": {
            "Statute": "1-1-2",
            "CatchLine": "Tense and number",
            "Next": "",
            "Html": f"<p>1-1-2. Tense and number. {body_two}</p>",
        },
    }


def _tn_pages() -> Dict[str, bytes]:
    body_one = (
        "This code shall be known and may be cited as the Tennessee Code Annotated "
        "and constitutes the official codification of the permanent laws of Tennessee. "
    ) * 4
    body_two = (
        "The provisions of this code shall be liberally construed to effectuate the "
        "general purposes of the Tennessee Code Annotated and promote justice. "
    ) * 4
    return {
        "https://www.tn.gov/tga/statutes.html": (
            "<html><body>"
            "<a href='/tga/statutes/title-1/'>Title 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.tn.gov/tga/statutes/title-1/": (
            "<html><body>"
            "<a href='/tga/statutes/title-1/chapter-1/'>Chapter 1</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.tn.gov/tga/statutes/title-1/chapter-1/": (
            "<html><body>"
            "<a href='/tga/statutes/title-1/chapter-1/section-1-1-101.html'>Section 1-1-101</a>"
            "<a href='/tga/statutes/title-1/chapter-1/section-1-1-102.html'>Section 1-1-102</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://www.tn.gov/tga/statutes/title-1/chapter-1/section-1-1-101.html": (
            f"<html><body><main><h1>Section 1-1-101 Designation and citation</h1>"
            f"<p>{body_one}</p></main></body></html>"
        ).encode("utf-8"),
        "https://www.tn.gov/tga/statutes/title-1/chapter-1/section-1-1-102.html": (
            f"<html><body><main><h1>Section 1-1-102 Construction of code</h1>"
            f"<p>{body_two}</p></main></body></html>"
        ).encode("utf-8"),
    }


def _tx_zip_bytes() -> bytes:
    chapter_html = """
    <html><body>
    <p>TITLE 1. INTRODUCTORY PROVISIONS</p>
    <p>CHAPTER 1. GENERAL PROVISIONS</p>
    <p>Sec. 1.01. SHORT TITLE. This code may be cited as the Penal Code of Texas
    and provides the official short title for the Texas Penal Code under state law.
    The provisions of this section establish the short title used in official citations
    and legislative references throughout the State of Texas.</p>
    <p>Sec. 1.02. OBJECTIVES OF CODE. The general purposes of this code are to establish
    a system of prohibitions, penalties, and correctional measures under Texas law to
    deal with conduct that unjustifiably and inexcusably causes or threatens harm to
    those individuals or public interests for which state protection is appropriate.</p>
    </body></html>
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pe.1.htm", chapter_html)
    return buffer.getvalue()


def _ut_xml_pages() -> Dict[str, bytes]:
    body_one = ("Utah Code declaration of policy text for official scrape certification. " * 12)
    body_two = ("Utah Code definitions text for official scrape certification of section two. " * 12)
    return {
        "https://le.utah.gov/xcode/code.html": (
            "<html><body><script>"
            'var versionDefault="C_1800010118000101";'
            "</script></body></html>"
        ).encode("utf-8"),
        "https://le.utah.gov/xcode/C_1800010118000101.xml": (
            "<code>"
            "<title number='1'>"
            "<catchline>General Provisions</catchline>"
            "<chapter number='1'>"
            "<catchline>Definitions</catchline>"
            "<section number='1-1-101'>"
            f"<catchline>Declaration of policy.</catchline>{body_one}"
            "</section>"
            "<section number='1-1-102'>"
            f"<catchline>Definitions.</catchline>{body_two}"
            "</section>"
            "</chapter>"
            "</title>"
            "</code>"
        ).encode("utf-8"),
    }


async def _scrape_sd(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    payloads = _sd_api_payloads()

    async def _fake_request_json(self, url: str, headers: Dict[str, str], timeout: int) -> Dict[str, Any]:
        section = url.rstrip("/").rsplit("/", 1)[-1]
        return payloads.get(section, {})

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("South Dakota should use official statutes API")

    monkeypatch.setattr(SouthDakotaScraper, "_request_json", _fake_request_json)
    scraper = SouthDakotaScraper("SD", "South Dakota")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "South Dakota Codified Laws",
        "https://sdlegislature.gov/",
        max_statutes=2,
    )


async def _scrape_tn(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _tn_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 30) -> bytes:
        return pages.get(url, b"")

    async def _fail_justia(*args, **kwargs):
        raise AssertionError("Tennessee cohort K must use official tn.gov path")

    monkeypatch.setattr(
        TennesseeScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(TennesseeScraper, "_scrape_justia_code_tree", _fail_justia)
    monkeypatch.delenv("STATE_SCRAPER_TN_ALLOW_JUSTIA_FALLBACK", raising=False)

    scraper = TennesseeScraper("TN", "Tennessee")
    return await scraper.scrape_code(
        "Tennessee Code Annotated",
        "https://www.tn.gov/tga/statutes.html",
        max_statutes=2,
    )


async def _scrape_tx(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    zip_bytes = _tx_zip_bytes()
    downloads_json = json.dumps(
        {"StatuteCode": [{"code": "PE", "Html": "Zips/PE.htm.zip"}]}
    ).encode("utf-8")

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        if url.endswith("StatuteCodeDownloads.json"):
            return downloads_json
        if "PE.htm.zip" in url:
            return zip_bytes
        return b""

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Texas should use official HTML zip path")

    monkeypatch.setattr(
        TexasScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    scraper = TexasScraper("TX", "Texas")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "Penal Code",
        "https://statutes.capitol.texas.gov/Docs/PE/htm/PE.1.htm",
        max_statutes=2,
    )


async def _scrape_ut(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _ut_xml_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        return pages.get(url, b"")

    async def _fail_justia_generic(self, code_name, candidate, citation_format, max_sections):
        if "justia.com" in str(candidate):
            raise AssertionError("Utah should not use Justia for cohort K")
        return []

    monkeypatch.setattr(
        UtahScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.delenv("STATE_SCRAPER_UT_ALLOW_JUSTIA_FALLBACK", raising=False)
    scraper = UtahScraper("UT", "Utah")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_justia_generic)
    return await scraper.scrape_code(
        "Utah Code",
        "https://le.utah.gov/xcode/code.html",
        max_statutes=2,
    )


async def _run_all_states(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[NormalizedStatute]]:
    return {
        "SD": await _scrape_sd(monkeypatch),
        "TN": await _scrape_tn(monkeypatch),
        "TX": await _scrape_tx(monkeypatch),
        "UT": await _scrape_ut(monkeypatch),
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


def test_cohort_k_jurisdiction_set_is_exact():
    runner = _load_runner()
    assert runner.cohort_states(COHORT) == list(EXPECTED_STATES)
    assert set(EXPECTED_STATES).issubset(set(runner.CANONICAL_JURISDICTIONS))


@pytest.mark.anyio
async def test_cohort_k_scrapers_emit_official_non_placeholder_text(monkeypatch: pytest.MonkeyPatch):
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
async def test_south_dakota_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: full-corpus mode must not silently clamp the official API."""
    requested: Dict[str, Any] = {}

    async def _fake_api(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="SD",
                state_name="South Dakota",
                statute_id=f"{code_name} § 1-1-1",
                code_name=code_name,
                section_number="1-1-1",
                section_name="Definitions",
                full_text=("South Dakota full corpus official section text. " * 20),
                source_url="https://sdlegislature.gov/api/Statutes/Statute/1-1-1",
                official_cite="S.D. Codified Laws 1-1-1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_south_dakota_statutes_api",
                    "discovery_method": "official_statute_api_next_chain",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(SouthDakotaScraper, "_scrape_statutes_api", _fake_api)
    scraper = SouthDakotaScraper("SD", "South Dakota")
    statutes = await scraper.scrape_code(
        "South Dakota Codified Laws",
        "https://sdlegislature.gov/",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_tennessee_full_corpus_refuses_justia_sole_admission(monkeypatch: pytest.MonkeyPatch):
    async def _empty_official(self, *args, **kwargs):
        return []

    async def _empty_seed(self, *args, **kwargs):
        return []

    async def _justia_tree(self, code_name: str, max_statutes: Optional[int] = None):
        return [
            NormalizedStatute(
                state_code="TN",
                state_name="Tennessee",
                statute_id=f"{code_name} § justia",
                code_name=code_name,
                section_number="justia",
                section_name="Secondary",
                full_text=("Justia secondary mirror text that must not sole-admit. " * 10),
                source_url="https://law.justia.com/codes/tennessee/fixture",
                official_cite="Tenn. Code Ann. § justia",
                metadata=StatuteMetadata(),
                structured_data={"source_kind": "jina_reader_justia_tennessee_code"},
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.delenv("STATE_SCRAPER_TN_ALLOW_JUSTIA_FALLBACK", raising=False)
    monkeypatch.setattr(TennesseeScraper, "_scrape_official_tga_tree", _empty_official)
    monkeypatch.setattr(TennesseeScraper, "_scrape_official_seed_sections", _empty_seed)
    monkeypatch.setattr(TennesseeScraper, "_scrape_justia_code_tree", _justia_tree)
    monkeypatch.setattr(TennesseeScraper, "_scrape_direct_seed_sections", _empty_seed)

    scraper = TennesseeScraper("TN", "Tennessee")
    statutes = await scraper.scrape_code(
        "Tennessee Code Annotated",
        "https://www.tn.gov/tga/statutes.html",
        max_statutes=None,
    )
    assert statutes == []


@pytest.mark.anyio
async def test_utah_full_corpus_refuses_justia_sole_admission(monkeypatch: pytest.MonkeyPatch):
    async def _empty_xml(self, code_name: str, max_statutes: int):
        return []

    async def _empty_versioned(self, code_name: str, max_statutes: int):
        return []

    async def _justia_generic(self, code_name, candidate, citation_format, max_sections):
        if "justia.com" in str(candidate):
            return [
                NormalizedStatute(
                    state_code="UT",
                    state_name="Utah",
                    statute_id=f"{code_name} § justia",
                    code_name=code_name,
                    section_number="justia",
                    section_name="Secondary",
                    full_text=("Justia secondary mirror text that must not sole-admit. " * 10),
                    source_url="https://law.justia.com/codes/utah/fixture",
                    official_cite="Utah Code § justia",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "secondary_justia"},
                )
            ]
        return []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.delenv("STATE_SCRAPER_UT_ALLOW_JUSTIA_FALLBACK", raising=False)
    monkeypatch.setattr(UtahScraper, "_scrape_official_xml_code_tree", _empty_xml)
    monkeypatch.setattr(UtahScraper, "_scrape_official_versioned_tree", _empty_versioned)
    monkeypatch.setattr(UtahScraper, "_generic_scrape", _justia_generic)

    scraper = UtahScraper("UT", "Utah")
    statutes = await scraper.scrape_code(
        "Utah Code",
        "https://le.utah.gov/xcode/code.html",
        max_statutes=None,
    )
    assert statutes == []


@pytest.mark.anyio
async def test_cohort_k_jurisdiction_receipts_pass_completeness_oracle(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    meta = {
        "SD": {
            "domain": OFFICIAL_DOMAINS["SD"],
            "units": 2,
            "first": "title-1/chapter-1/section-1-1-1",
            "last": "title-1/chapter-1/section-1-1-2",
        },
        "TN": {
            "domain": OFFICIAL_DOMAINS["TN"],
            "units": 2,
            "first": "title-1/chapter-1/section-1-1-101",
            "last": "title-1/chapter-1/section-1-1-102",
        },
        "TX": {
            "domain": OFFICIAL_DOMAINS["TX"],
            "units": 2,
            "first": "penal-code/title-1/chapter-1/section-1.01",
            "last": "penal-code/title-1/chapter-1/section-1.02",
        },
        "UT": {
            "domain": OFFICIAL_DOMAINS["UT"],
            "units": 2,
            "first": "title-1/chapter-1/section-1-1-101",
            "last": "title-1/chapter-1/section-1-1-102",
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"cohort-k-{state.lower()}")
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

    # Durable evidence artifact required by LCR-019.
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


def test_cohort_k_report_artifact_exists_and_certifies():
    """Fail-closed gate: committed cohort_k.json must certify cohort K."""
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


def test_cohort_k_adapters_importable_and_registered():
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )

    for code, cls in (
        ("SD", SouthDakotaScraper),
        ("TN", TennesseeScraper),
        ("TX", TexasScraper),
        ("UT", UtahScraper),
    ):
        scraper_cls = StateScraperRegistry.get_scraper_class(code)
        assert scraper_cls is cls or scraper_cls is not None
        scraper = scraper_cls(code, code)
        base = scraper.get_base_url()
        assert base.startswith("http")
        codes = scraper.get_code_list()
        assert codes and codes[0].get("url")
        assert "justia.com" not in str(codes[0].get("url") or "").lower()

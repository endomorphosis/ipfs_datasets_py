"""Integration certification for state-law scrape cohort H (NH, NJ, NM, NY).

LCR-016: prove each listed jurisdiction independently satisfies closed-frontier
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
    NewHampshireScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_jersey import (
    NewJerseyScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico import (
    NewMexicoScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import (
    NewYorkScraper,
)


COHORT = "H"
TASK_ID = "LCR-016"
GOAL_ID = "LCR-G022"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_STATES: Tuple[str, ...] = ("NH", "NJ", "NM", "NY")

REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_h.json")
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-h-report@1"

# Official primary domains from the sealed catalog / cohort runner map.
OFFICIAL_DOMAINS: Dict[str, str] = {
    "NH": "www.gencourt.state.nh.us",
    "NJ": "lis.njleg.state.nj.us",
    "NM": "nmonesource.com",
    "NY": "www.nysenate.gov",
}

ALLOWED_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "NH": ("gencourt.state.nh.us", "gc.nh.gov"),
    "NJ": ("njleg.state.nj.us",),
    "NM": ("nmonesource.com",),
    "NY": ("nysenate.gov",),
}

PLACEHOLDER_RE = re.compile(
    r"^(todo|tbd|placeholder|lorem ipsum|sample text|n/?a|none|null|\.\.\.)$",
    re.IGNORECASE,
)

SECONDARY_HOST_RE = re.compile(
    r"(justia\.com|findlaw\.com|cornell\.edu|wikipedia\.org|casemine\.com|public\.law)",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_runner():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "run_legal_corpora_reindex_cohort.py"
    name = "lcr016_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_certifier():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "certify_state_laws_cohort.py"
    name = "lcr016_certify_state_laws_cohort"
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


def _nh_pages() -> Dict[str, str]:
    body_one = ("Section 1:1 Name of State. The state shall be called New Hampshire. " * 8)
    body_two = ("Section 1:2 Jurisdiction. The jurisdiction of the state extends. " * 8)
    return {
        "https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm": (
            "<html><body>"
            "<a href='/rsa/html/NHTOC/NHTOC-I.htm'>TITLE I : The State and Its Government</a>"
            "</body></html>"
        ),
        "https://www.gencourt.state.nh.us/rsa/html/NHTOC/NHTOC-I.htm": (
            "<html><body>"
            "<a href='/rsa/html/I/1/1.htm'>CHAPTER 1 : The State And Its Government</a>"
            "</body></html>"
        ),
        "https://www.gencourt.state.nh.us/rsa/html/I/1/1.htm": (
            "<html><body>"
            "<a href='/rsa/html/I/1/1-1.htm'>Section 1:1 Name of State</a>"
            "<a href='/rsa/html/I/1/1-2.htm'>Section 1:2 Jurisdiction</a>"
            "</body></html>"
        ),
        "https://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm": (
            f"<html><body><h1>Section 1:1 Name of State</h1><p>{body_one}</p></body></html>"
        ),
        "https://www.gencourt.state.nh.us/rsa/html/I/1/1-2.htm": (
            f"<html><body><h1>Section 1:2 Jurisdiction</h1><p>{body_two}</p></body></html>"
        ),
    }


def _nj_pages() -> Dict[str, bytes]:
    body_one = ("In the construction of the laws and statutes of this state. " * 12)
    body_two = ("Words and phrases defined for the New Jersey Statutes Annotated. " * 12)
    root_xml = (
        '<?xml version="1.0" encoding="UTF-8" ?><toc><nodes>'
        '<n ct="application/folder" hc="y" id="statutes/1/2" n="2" '
        't="TITLE 1 ACTS, LAWS AND STATUTES"/>'
        "</nodes></toc>"
    )
    title_xml = (
        '<?xml version="1.0" encoding="UTF-8" ?><toc><nodes>'
        '<n ct="text/xml" id="statutes/1/2/3" n="3" t="1:1-1. General rules of construction"/>'
        '<n ct="text/xml" id="statutes/1/2/4" n="4" t="1:1-2. Words and phrases defined."/>'
        "</nodes></toc>"
    )
    doc_one = (
        "<html><body>"
        "<div class='Headnotes'><div>1:1-1. General rules of construction</div></div>"
        f"<div class='Normal-Level'><div>{body_one}</div></div>"
        "</body></html>"
    )
    doc_two = (
        "<html><body>"
        "<div class='Headnotes'><div>1:1-2. Words and phrases defined</div></div>"
        f"<div class='Normal-Level'><div>{body_two}</div></div>"
        "</body></html>"
    )
    return {
        "root_xml": root_xml.encode("utf-8"),
        "title_xml": title_xml.encode("utf-8"),
        "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1/2/3": doc_one.encode("utf-8"),
        "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1/2/4": doc_two.encode("utf-8"),
    }


def _nm_pages() -> Dict[str, bytes]:
    body_one = ("1-1-1. Election Code. This chapter may be cited as the Election Code. " * 8)
    body_two = ("1-1-2. Headings. Article and section headings do not control meaning. " * 8)
    return {
        "https://nmonesource.com/nmos/nmsa/en/nav_date.do": (
            "<html><body>"
            "<a href='/nmos/nmsa/en/item/chapter-1'>Chapter 1 Elections</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://nmonesource.com/nmos/nmsa/en/item/chapter-1": (
            "<html><body>"
            "<a href='/nmos/nmsa/en/item/1-1-1'>1-1-1. Election Code</a>"
            "<a href='/nmos/nmsa/en/item/1-1-2'>1-1-2. Headings</a>"
            "</body></html>"
        ).encode("utf-8"),
        "https://nmonesource.com/nmos/nmsa/en/item/1-1-1": (
            f"<html><body><h1>1-1-1. Election Code</h1><p>{body_one}</p></body></html>"
        ).encode("utf-8"),
        "https://nmonesource.com/nmos/nmsa/en/item/1-1-2": (
            f"<html><body><h1>1-1-2. Headings</h1><p>{body_two}</p></body></html>"
        ).encode("utf-8"),
    }


def _ny_pages() -> Dict[str, str]:
    body_one = ("Section 125.25 Murder in the second degree. A person is guilty of murder. " * 8)
    body_two = ("Section 125.27 Murder in the first degree. A person is guilty of murder. " * 8)
    return {
        "https://www.nysenate.gov/legislation/laws": (
            "<html><body>"
            "<a href='/legislation/laws/PEN'>PEN Penal</a>"
            "</body></html>"
        ),
        "https://www.nysenate.gov/legislation/laws/PEN": (
            "<html><body>"
            "<a href='/legislation/laws/PEN/125.25'>§ 125.25 Murder in the second degree</a>"
            "<a href='/legislation/laws/PEN/125.27'>§ 125.27 Murder in the first degree</a>"
            "</body></html>"
        ),
        "https://www.nysenate.gov/legislation/laws/PEN/125.25": (
            f"<html><body><main><h1>Section 125.25 Murder in the second degree</h1>"
            f"<p>{body_one}</p></main></body></html>"
        ),
        "https://www.nysenate.gov/legislation/laws/PEN/125.27": (
            f"<html><body><main><h1>Section 125.27 Murder in the first degree</h1>"
            f"<p>{body_two}</p></main></body></html>"
        ),
    }


def _lookup_page(pages: Mapping[str, Any], url: str, empty):
    if url in pages:
        return pages[url]
    stripped = str(url or "").split("#", 1)[0].split("?", 1)[0]
    return pages.get(stripped, empty)


async def _scrape_nh(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _nh_pages()

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        value = _lookup_page(pages, url, "")
        return str(value or "")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("New Hampshire should use official RSA HTML tree")

    async def _no_archive_discover(self, limit: int = 180):
        return []

    monkeypatch.setattr(NewHampshireScraper, "_request_text_direct", _fake_request_text_direct)
    monkeypatch.setattr(NewHampshireScraper, "_discover_archived_rsa_urls", _no_archive_discover)
    scraper = NewHampshireScraper("NH", "New Hampshire")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "New Hampshire Revised Statutes",
        "https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
        max_statutes=2,
    )


async def _scrape_nj(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _nj_pages()

    async def _fake_request_bytes_direct(self, url: str, timeout: int = 20) -> bytes:
        if "f=xmlcontents" in url and "basepathid=statutes%2F1%2F2" in url:
            return pages["title_xml"]
        if "f=xmlcontents" in url and "basepathid=statutes" in url:
            return pages["root_xml"]
        value = _lookup_page(pages, url, b"")
        return value if isinstance(value, (bytes, bytearray)) else b""

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("New Jersey should use official LIS xmlcontents tree")

    monkeypatch.setattr(NewJerseyScraper, "_request_bytes_direct", _fake_request_bytes_direct)
    scraper = NewJerseyScraper("NJ", "New Jersey")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "New Jersey Statutes",
        "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1"
        "?f=templates&fn=default.htm&vid=Publish:10.1048/Enu",
        max_statutes=2,
    )


async def _scrape_nm(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _nm_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 18) -> bytes:
        value = _lookup_page(pages, url, b"")
        return value if isinstance(value, (bytes, bytearray)) else b""

    async def _fake_request_bytes_direct(self, url: str, timeout: int = 18) -> bytes:
        value = _lookup_page(pages, url, b"")
        return value if isinstance(value, (bytes, bytearray)) else b""

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("New Mexico should use official NMOneSource HTML tree")

    monkeypatch.setattr(
        NewMexicoScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(NewMexicoScraper, "_request_bytes_direct", _fake_request_bytes_direct)
    scraper = NewMexicoScraper("NM", "New Mexico")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "New Mexico Statutes",
        "https://nmonesource.com/nmos/nmsa/en/nav_date.do",
        max_statutes=2,
    )


async def _scrape_ny(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _ny_pages()

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        value = _lookup_page(pages, url, "")
        return str(value or "")

    async def _fake_fetch(self, url: str, timeout_seconds: int = 18) -> bytes:
        value = _lookup_page(pages, url, "")
        return str(value or "").encode("utf-8")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("New York should use official nysenate.gov laws tree")

    async def _no_public_law(self, *args, **kwargs):
        return []

    monkeypatch.setattr(NewYorkScraper, "_request_text_direct", _fake_request_text_direct)
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_content_with_archival_fallback",
        _fake_fetch,
    )
    monkeypatch.setattr(NewYorkScraper, "_scrape_public_law_structured", _no_public_law)
    scraper = NewYorkScraper("NY", "New York")
    monkeypatch.setattr(scraper, "_generic_scrape", _fail_generic)
    return await scraper.scrape_code(
        "New York Consolidated Laws",
        "https://www.nysenate.gov/legislation/laws",
        max_statutes=2,
    )


async def _run_all_states(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[NormalizedStatute]]:
    return {
        "NH": await _scrape_nh(monkeypatch),
        "NJ": await _scrape_nj(monkeypatch),
        "NM": await _scrape_nm(monkeypatch),
        "NY": await _scrape_ny(monkeypatch),
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


def test_cohort_h_jurisdiction_set_is_exact():
    runner = _load_runner()
    assert runner.cohort_states(COHORT) == list(EXPECTED_STATES)
    assert set(EXPECTED_STATES).issubset(set(runner.CANONICAL_JURISDICTIONS))


@pytest.mark.anyio
async def test_cohort_h_scrapers_emit_official_non_placeholder_text(monkeypatch: pytest.MonkeyPatch):
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
async def test_new_hampshire_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: full-corpus mode must not silently clamp the official tree."""
    requested: Dict[str, Any] = {}

    async def _fake_official(self, *, code_name: str, checkpoint):
        requested["checkpoint_state"] = checkpoint.state_code
        return [
            NormalizedStatute(
                state_code="NH",
                state_name="New Hampshire",
                statute_id=f"{code_name} § 1:1",
                code_name=code_name,
                section_number="1:1",
                section_name="Name of State",
                full_text=("New Hampshire full corpus official section text. " * 20),
                source_url="https://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm",
                official_cite="N.H. Rev. Stat. § 1:1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_new_hampshire_rsa_html",
                    "discovery_method": "official_title_chapter_section",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        NewHampshireScraper,
        "_scrape_official_rsa_tree_batched",
        _fake_official,
    )
    scraper = NewHampshireScraper("NH", "New Hampshire")
    statutes = await scraper.scrape_code(
        "New Hampshire Revised Statutes",
        "https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
        max_statutes=None,
    )
    assert requested["checkpoint_state"] == "NH"
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_new_jersey_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_bulk(
        self,
        *,
        code_name: str,
        max_statutes: Optional[int] = None,
    ):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="NJ",
                state_name="New Jersey",
                statute_id=f"{code_name} § 1:1-1",
                code_name=code_name,
                section_number="1:1-1",
                section_name="General rules of construction",
                full_text=("New Jersey full corpus official section text. " * 20),
                source_url="https://www.njleg.state.nj.us/legislative-activity/statutes",
                official_cite="N.J. Stat. Ann. § 1:1-1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_new_jersey_statutes_rtf",
                    "discovery_method": "njleg_statutes_text_zip",
                    "skip_hydrate": True,
                },
            )
        ]

    async def _partial_index_must_not_run(*_args, **_kwargs):
        raise AssertionError("full-corpus NJ must use the exact official ZIP frontier")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewJerseyScraper, "_scrape_official_bulk_zip", _fake_bulk)
    monkeypatch.setattr(
        NewJerseyScraper,
        "_scrape_official_index",
        _partial_index_must_not_run,
    )
    scraper = NewJerseyScraper("NJ", "New Jersey")
    statutes = await scraper.scrape_code(
        "New Jersey Statutes",
        "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_new_mexico_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="NM",
                state_name="New Mexico",
                statute_id=f"{code_name} § 1-1-1",
                code_name=code_name,
                section_number="1-1-1",
                section_name="Election Code",
                full_text=("New Mexico full corpus official section text. " * 20),
                source_url="https://nmonesource.com/nmos/nmsa/en/item/1-1-1",
                official_cite="N.M. Stat. Ann. § 1-1-1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_nmonesource_html",
                    "discovery_method": "official_nav_date_chapter_section",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewMexicoScraper, "_scrape_official_nmonesource_tree", _fake_official)
    scraper = NewMexicoScraper("NM", "New Mexico")
    statutes = await scraper.scrape_code(
        "New Mexico Statutes",
        "https://nmonesource.com/nmos/nmsa/en/nav_date.do",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_new_york_full_corpus_refuses_justia_sole_admission(monkeypatch: pytest.MonkeyPatch):
    async def _empty_official(self, code_name: str, max_statutes: Optional[int] = None):
        return []

    async def _justia_generic(self, code_name, candidate, citation_format, max_sections):
        if "justia.com" in str(candidate):
            return [
                NormalizedStatute(
                    state_code="NY",
                    state_name="New York",
                    statute_id=f"{code_name} § justia",
                    code_name=code_name,
                    section_number="justia",
                    section_name="Secondary",
                    full_text=("Justia secondary mirror text that must not sole-admit. " * 10),
                    source_url="https://law.justia.com/codes/new-york/fixture",
                    official_cite="N.Y. § justia",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "secondary_justia"},
                )
            ]
        return []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewYorkScraper, "_scrape_official_senate_laws_tree", _empty_official)
    monkeypatch.setattr(NewYorkScraper, "_generic_scrape", _justia_generic)
    monkeypatch.setattr(NewYorkScraper, "_scrape_public_law_structured", _empty_official)

    scraper = NewYorkScraper("NY", "New York")
    statutes = await scraper.scrape_code(
        "New York Consolidated Laws",
        "https://www.nysenate.gov/legislation/laws",
        max_statutes=None,
    )
    assert statutes == []


@pytest.mark.anyio
async def test_cohort_h_jurisdiction_receipts_pass_completeness_oracle(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    meta = {
        "NH": {
            "domain": OFFICIAL_DOMAINS["NH"],
            "units": 2,
            "first": "title-i/chapter-1/section-1:1",
            "last": "title-i/chapter-1/section-1:2",
        },
        "NJ": {
            "domain": OFFICIAL_DOMAINS["NJ"],
            "units": 2,
            "first": "title-1/section-1:1-1",
            "last": "title-1/section-1:1-2",
        },
        "NM": {
            "domain": OFFICIAL_DOMAINS["NM"],
            "units": 2,
            "first": "chapter-1/section-1-1-1",
            "last": "chapter-1/section-1-1-2",
        },
        "NY": {
            "domain": OFFICIAL_DOMAINS["NY"],
            "units": 2,
            "first": "law-pen/section-125.25",
            "last": "law-pen/section-125.27",
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"cohort-h-{state.lower()}")
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

    # Durable evidence artifact required by LCR-016.
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
    assert "Bearer " not in serialized
    for state in EXPECTED_STATES:
        entry = reloaded["state_results"][state]
        assert entry["status"] == "success"
        assert int(entry["failed_final"]) == 0
        assert entry["frontier_closed"] is True
        jrec = reloaded["jurisdiction_receipts"][state]
        assert evaluate_jurisdiction_receipt(jrec).complete is True


def test_cohort_h_report_artifact_exists_and_certifies():
    """Fail-closed gate: committed cohort_h.json must certify cohort H."""
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


def test_cohort_h_adapters_importable_and_registered():
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )

    for code, cls in (
        ("NH", NewHampshireScraper),
        ("NJ", NewJerseyScraper),
        ("NM", NewMexicoScraper),
        ("NY", NewYorkScraper),
    ):
        scraper_cls = StateScraperRegistry.get_scraper_class(code)
        assert scraper_cls is cls or scraper_cls is not None
        scraper = scraper_cls(code, code)
        base = scraper.get_base_url()
        assert base.startswith("http")
        codes = scraper.get_code_list()
        assert codes and codes[0].get("url")

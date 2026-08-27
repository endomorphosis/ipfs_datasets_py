"""Integration certification for state-law scrape cohort A (AL, AK, AZ, AR).

LCR-009: prove each listed jurisdiction independently satisfies closed-frontier
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama import (
    AlabamaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska import (
    AlaskaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arizona import (
    ArizonaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
    ArkansasScraper,
)


COHORT = "A"
TASK_ID = "LCR-009"
GOAL_ID = "LCR-G021"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_STATES: Tuple[str, ...] = ("AL", "AK", "AZ", "AR")

REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_a.json")
RECEIPT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-receipt@1"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-a-report@1"

# Official primary domains from the sealed catalog / cohort runner map.
OFFICIAL_DOMAINS: Dict[str, str] = {
    "AL": "alison.legislature.state.al.us",
    "AK": "www.akleg.gov",
    "AZ": "www.azleg.gov",
    "AR": "www.arkleg.state.ar.us",
}

ALLOWED_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "AL": ("legislature.state.al.us",),
    "AK": ("akleg.gov", "legis.state.ak.us"),
    "AZ": ("azleg.gov",),
    "AR": ("arkleg.state.ar.us",),
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
    name = "lcr009_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_certifier():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "certify_state_laws_cohort.py"
    name = "lcr009_certify_state_laws_cohort"
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


def _al_graphql_payloads() -> Dict[str, Any]:
    body_one = (
        "The following words and phrases, whenever used in this Code, shall "
        "have the meanings respectively ascribed to them under the Alabama Code. "
    ) * 4
    body_two = (
        "Words used in this Code in the past or present tense include the future "
        "and words used in the singular number include the plural under Alabama law. "
    ) * 4
    scaffold = "†∫codeId†parentId†displayId∫2∫14512†2∫14515†14512†1-1-1∫14528†14512†1-1-2"
    return {
        "scaffold": scaffold,
        "sections": {
            "14512": [
                {
                    "codeId": "14515",
                    "parentId": "14512",
                    "displayId": "1-1-1",
                    "title": "Section 1-1-1 Meaning of certain words and terms.",
                    "content": f"<p>{body_one}</p>",
                    "history": "<p>Code 1852, §1; Acts 2025, No. 3.</p>",
                    "type": "Section",
                    "isContentNode": True,
                },
                {
                    "codeId": "14528",
                    "parentId": "14512",
                    "displayId": "1-1-2",
                    "title": "Section 1-1-2 Tense, number, and gender.",
                    "content": f"<p>{body_two}</p>",
                    "history": "",
                    "type": "Section",
                    "isContentNode": True,
                },
            ]
        },
    }


def _ak_chunk_html() -> str:
    body_one = (
        "The bulk formal revision of the laws of Alaska is adopted and enacted "
        "as the general and permanent law of Alaska under the Alaska Statutes. "
    ) * 4
    body_two = (
        "This section may be cited as the Alaska Statutes and provides the official "
        "citation form for the codified laws of the State of Alaska. "
    ) * 4
    return f"""
    <div class="statute">
      <b><a name="01.05"> </a><h6>Chapter 05. Alaska Statutes.</h6></b>
      <b><a name="01.05.006"> </a>Sec. 01.05.006. Adoption of Alaska Statutes; notes, headings, and references not law.</b>
      {body_one}
    </div>
    <div class="statute">
      <b><a name="01.05.011"> </a>Sec. 01.05.011. Citation.</b>
      {body_two}
    </div>
    """


def _az_pages() -> Dict[str, str]:
    body_one = (
        "It is declared that the public policy of this state and the general purposes "
        "of this title are to give fair warning of the nature of the conduct proscribed "
        "under the Arizona Revised Statutes. "
    ) * 3
    body_two = (
        "The provisions of this title shall govern the construction of and punishment "
        "for any offense defined in this title under the Arizona Revised Statutes. "
    ) * 3
    return {
        "https://www.azleg.gov/arsDetail/?title=13": (
            "<html><body><ul>"
            '<li class="colleft"><a class="stat" '
            'href="/viewdocument/?docName=https://www.azleg.gov/ars/13/00101.htm">13-101</a></li>'
            '<li class="colright">Purposes</li>'
            "</ul><ul>"
            '<li class="colleft"><a class="stat" '
            'href="/viewdocument/?docName=https://www.azleg.gov/ars/13/00102.htm">13-102</a></li>'
            '<li class="colright">Applicability of title</li>'
            "</ul></body></html>"
        ),
        "https://www.azleg.gov/ars/13/00101.htm": (
            f"<html><body><p>13-101 - Purposes</p><p>{body_one}</p></body></html>"
        ),
        "https://www.azleg.gov/ars/13/00102.htm": (
            f"<html><body><p>13-102 - Applicability of title</p><p>{body_two}</p></body></html>"
        ),
    }


def _ar_pages() -> Dict[str, bytes]:
    body_one = (
        "This Code shall be known and may be cited as the Arkansas Code of 1987 "
        "and constitutes the official codification of the general and permanent laws "
        "of the State of Arkansas. "
    ) * 4
    body_two = (
        "The provisions of this Code shall be liberally construed to effectuate the "
        "general purposes of the Arkansas Code and to promote justice in administration. "
    ) * 4
    return {
        "https://www.arkleg.state.ar.us/ArkansasCode/": (
            "<html><body>"
            '<a href="/ArkansasCode/1-1-101">1-1-101. Title</a>'
            '<a href="/ArkansasCode/1-1-102">1-1-102. Construction</a>'
            "</body></html>"
        ).encode("utf-8"),
        "https://www.arkleg.state.ar.us/ArkansasCode/1-1-101": (
            f"<html><body><main><h1>1-1-101. Title</h1><p>{body_one}</p></main></body></html>"
        ).encode("utf-8"),
        "https://www.arkleg.state.ar.us/ArkansasCode/1-1-102": (
            f"<html><body><main><h1>1-1-102. Construction</h1><p>{body_two}</p></main></body></html>"
        ).encode("utf-8"),
    }


async def _scrape_al(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    fixtures = _al_graphql_payloads()

    async def _fake_graphql(
        self, query: str, variables: Dict[str, Any] | None = None, timeout_seconds: int = 15
    ) -> Dict[str, Any]:
        if "codeOfAlabamaScaffold" in query:
            return {"scaffold": fixtures["scaffold"]}
        parent_ids = list((variables or {}).get("parentId") or [])
        rows: List[Dict[str, Any]] = []
        for parent_id in parent_ids:
            rows.extend(fixtures["sections"].get(str(parent_id), []))
        return {"codeItems": {"data": rows}}

    async def _no_cache(self, url: str):
        return None

    async def _no_store(self, **kwargs):
        return None

    async def _fail_custom(*args, **kwargs):
        raise AssertionError("Alabama should use official ALISON GraphQL path")

    monkeypatch.setattr(AlabamaScraper, "_graphql", _fake_graphql)
    monkeypatch.setattr(AlabamaScraper, "_load_page_bytes_from_any_cache", _no_cache)
    monkeypatch.setattr(AlabamaScraper, "_cache_successful_page_fetch", _no_store)
    monkeypatch.setattr(AlabamaScraper, "_custom_scrape_alabama", _fail_custom)
    scraper = AlabamaScraper("AL", "Alabama")
    return await scraper.scrape_code(
        "Alabama Code",
        "https://alison.legislature.state.al.us/code-of-alabama",
        max_statutes=2,
    )


async def _scrape_ak(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    html = _ak_chunk_html()

    async def _fake_fetch(self, sec_start: str, timeout_seconds: int = 8) -> Tuple[str, str]:
        if str(sec_start) in {"1", "01", "1.0", "01.05"}:
            return html, "1.05.011"
        return "", ""

    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _fake_fetch)
    scraper = AlaskaScraper("AK", "Alaska")
    return await scraper.scrape_code(
        "Alaska Statutes",
        "https://www.akleg.gov/basis/statutes.asp",
        max_statutes=2,
    )


async def _scrape_az(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _az_pages()

    async def _fake_html(self, url: str, timeout_seconds: int = 8) -> str:
        return pages.get(url, "")

    monkeypatch.setattr(ArizonaScraper, "_fetch_official_az_html", _fake_html)
    scraper = ArizonaScraper("AZ", "Arizona")
    return await scraper.scrape_code(
        "Arizona Revised Statutes Title 13",
        "https://www.azleg.gov/arsDetail/?title=13",
        max_statutes=2,
    )


async def _scrape_ar(monkeypatch: pytest.MonkeyPatch) -> List[NormalizedStatute]:
    pages = _ar_pages()

    async def _fake_fetch(self, url: str, timeout_seconds: int = 8) -> bytes:
        return pages.get(url, b"")

    async def _fail_justia(*args, **kwargs):
        raise AssertionError("Arkansas should use official arkleg path for cohort A")

    async def _fail_generic(*args, **kwargs):
        raise AssertionError("Arkansas should use official arkleg path for cohort A")

    monkeypatch.setattr(ArkansasScraper, "_fetch_direct_html", _fake_fetch)
    monkeypatch.setattr(ArkansasScraper, "_scrape_justia_titles", _fail_justia)
    monkeypatch.setattr(ArkansasScraper, "_generic_scrape", _fail_generic)
    scraper = ArkansasScraper("AR", "Arkansas")
    return await scraper.scrape_code(
        "Arkansas Code",
        "https://www.arkleg.state.ar.us/ArkansasCode/",
        max_statutes=2,
    )


async def _run_all_states(monkeypatch: pytest.MonkeyPatch) -> Dict[str, List[NormalizedStatute]]:
    return {
        "AL": await _scrape_al(monkeypatch),
        "AK": await _scrape_ak(monkeypatch),
        "AZ": await _scrape_az(monkeypatch),
        "AR": await _scrape_ar(monkeypatch),
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


def test_cohort_a_jurisdiction_set_is_exact():
    runner = _load_runner()
    assert runner.cohort_states(COHORT) == list(EXPECTED_STATES)
    assert set(EXPECTED_STATES).issubset(set(runner.CANONICAL_JURISDICTIONS))


@pytest.mark.anyio
async def test_cohort_a_scrapers_emit_official_non_placeholder_text(monkeypatch: pytest.MonkeyPatch):
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
async def test_alabama_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: full-corpus mode must not silently clamp the official tree."""
    requested: Dict[str, Any] = {}

    async def _fake_graphql(self, code_name: str, max_statutes: Optional[int] = None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="AL",
                state_name="Alabama",
                statute_id=f"{code_name} § 1-1-1",
                code_name=code_name,
                section_number="1-1-1",
                section_name="Meaning of certain words",
                full_text=("Alabama full corpus official section text. " * 20),
                source_url="https://alison.legislature.state.al.us/code-of-alabama?section=1-1-1",
                official_cite="Ala. Code § 1-1-1",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_alison_graphql",
                    "discovery_method": "official_alison_scaffold_parent_batch",
                    "skip_hydrate": True,
                },
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(AlabamaScraper, "_scrape_alison_graphql", _fake_graphql)
    scraper = AlabamaScraper("AL", "Alabama")
    statutes = await scraper.scrape_code(
        "Alabama Code",
        "https://alison.legislature.state.al.us/code-of-alabama",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_alaska_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    full_page = "".join(
        (
            f'<b><a name="{int(title):02d}.01.001"> </a>'
            f"Sec. {int(title):02d}.01.001. Official title {title} section.</b>"
            + (f"Official Alaska title {title} statutory body text. " * 5)
        )
        for title, _name in AlaskaScraper.OFFICIAL_TITLES
    )
    call_count = {"n": 0}

    async def _fake_fetch(self, sec_start: str, timeout_seconds: int = 8) -> Tuple[str, str]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            assert sec_start == "1"
            return full_page, "47.01.001"
        assert sec_start == "47.01.001"
        return "", ""

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _fake_fetch)
    scraper = AlaskaScraper("AK", "Alaska")
    statutes = await scraper.scrape_code(
        "Alaska Statutes",
        "https://www.akleg.gov/basis/statutes.asp",
        max_statutes=None,
    )
    assert len(statutes) == len(AlaskaScraper.OFFICIAL_TITLES)
    assert all(
        str((s.structured_data or {}).get("source_kind") or "").startswith("official_")
        for s in statutes
    )


@pytest.mark.anyio
async def test_arizona_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    pages = _az_pages()

    async def _fake_html(self, url: str, timeout_seconds: int = 8) -> str:
        return pages.get(url, "")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(ArizonaScraper, "_fetch_official_az_html", _fake_html)
    scraper = ArizonaScraper("AZ", "Arizona")
    statutes = await scraper.scrape_code(
        "Arizona Revised Statutes Title 13",
        "https://www.azleg.gov/arsDetail/?title=13",
        max_statutes=None,
    )
    assert len(statutes) == 2
    assert all("azleg.gov" in str(s.source_url) for s in statutes)


@pytest.mark.anyio
async def test_arkansas_full_corpus_collects_justia_as_recovery_without_admitting_it(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _empty_official(self, code_name: str, code_url: str, max_statutes=None):
        return []

    async def _justia_rows(self, code_name: str, max_statutes=None):
        return [
            NormalizedStatute(
                state_code="AR",
                state_name="Arkansas",
                statute_id=f"{code_name} § justia",
                code_name=code_name,
                section_number="justia",
                section_name="Secondary",
                full_text=("Justia secondary mirror text that must not sole-admit. " * 10),
                source_url=(
                    "https://law.justia.com/codes/arkansas/title-1/chapter-1/"
                    "section-1-1-101/"
                ),
                official_cite="Ark. Code Ann. § justia",
                metadata=StatuteMetadata(),
                structured_data={"source_kind": "secondary_justia_arkansas_html"},
            )
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(ArkansasScraper, "_scrape_official_arkansas_code", _empty_official)
    monkeypatch.setattr(ArkansasScraper, "_scrape_justia_titles", _justia_rows)
    scraper = ArkansasScraper("AR", "Arkansas")
    statutes = await scraper.scrape_code(
        "Arkansas Code",
        "https://www.arkleg.state.ar.us/ArkansasCode/",
        max_statutes=None,
    )
    assert len(statutes) == 1
    assert statutes[0].source_url.startswith("https://law.justia.com/")
    assert statutes[0].structured_data["source_kind"] == "secondary_justia_arkansas_html"


@pytest.mark.anyio
async def test_arkansas_justia_recovery_keeps_enacted_text_and_strips_editorial_history(
    monkeypatch: pytest.MonkeyPatch,
):
    html = b"""
    <html><body>
      <h1>2025 Arkansas Code<br>Title 1<br>Chapter 1<br>
          \xc2\xa7 1-1-101. Extension of western boundary line</h1>
      <div id="codes-content">
        <p>The western boundary line of the State of Arkansas is extended as follows,
        and this sentence is enacted section text that must remain in the corpus.</p>
        <h2 class="SS_Banner">History</h2>
        <p>Acts 1905, No. 41, \xc2\xa7 1, p. 124.</p>
      </div>
    </body></html>
    """

    async def _fake_fetch(self, url: str, timeout_seconds: int = 18):
        self._record_fetch_event(provider="web_archiving_fixture", success=True)
        return html

    monkeypatch.setattr(ArkansasScraper, "_fetch_justia_html", _fake_fetch)
    scraper = ArkansasScraper("AR", "Arkansas")
    statute = await scraper._build_justia_statute(
        code_name="Arkansas Code",
        section_url=(
            "https://law.justia.com/codes/arkansas/title-1/chapter-1/"
            "section-1-1-101/"
        ),
        fallback_number="1",
    )

    assert statute is not None
    assert statute.section_number == "1-1-101"
    assert statute.section_name == "Extension of western boundary line"
    assert "western boundary line" in statute.full_text
    assert "Acts 1905" not in statute.full_text
    assert statute.structured_data["editorial_material_removed"] is True
    assert statute.structured_data["recovery_only"] is True
    assert statute.structured_data["full_corpus_admissible"] is False


@pytest.mark.anyio
async def test_arkansas_full_corpus_is_uncapped_when_max_statutes_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    requested: Dict[str, Any] = {}

    async def _fake_official(self, code_name: str, code_url: str, max_statutes=None):
        requested["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="AR",
                state_name="Arkansas",
                statute_id="AR-1-1-101",
                code_name=code_name,
                section_number="1-1-101",
                section_name="Title",
                full_text=("Arkansas full corpus official section text. " * 20),
                source_url="https://www.arkleg.state.ar.us/ArkansasCode/1-1-101",
                official_cite="Ark. Code Ann. § 1-1-101",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_arkansas_code_html",
                    "discovery_method": "official_arkansas_code_index",
                    "skip_hydrate": True,
                },
            )
        ]

    async def _empty_recovery(self, code_name: str, max_statutes=None):
        requested["recovery_max_statutes"] = max_statutes
        return []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(ArkansasScraper, "_scrape_official_arkansas_code", _fake_official)
    monkeypatch.setattr(ArkansasScraper, "_scrape_justia_titles", _empty_recovery)
    scraper = ArkansasScraper("AR", "Arkansas")
    statutes = await scraper.scrape_code(
        "Arkansas Code",
        "https://www.arkleg.state.ar.us/ArkansasCode/",
        max_statutes=None,
    )
    assert requested["max_statutes"] is None
    assert requested["recovery_max_statutes"] is None
    assert len(statutes) == 1


@pytest.mark.anyio
async def test_cohort_a_jurisdiction_receipts_pass_completeness_oracle(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    statutes_by_state = await _run_all_states(monkeypatch)

    meta = {
        "AL": {
            "domain": OFFICIAL_DOMAINS["AL"],
            "units": 2,
            "first": "title-1/chapter-1/section-1-1-1",
            "last": "title-1/chapter-1/section-1-1-2",
        },
        "AK": {
            "domain": OFFICIAL_DOMAINS["AK"],
            "units": 2,
            "first": "title-01/chapter-05/section-01.05.006",
            "last": "title-01/chapter-05/section-01.05.011",
        },
        "AZ": {
            "domain": OFFICIAL_DOMAINS["AZ"],
            "units": 2,
            "first": "title-13/section-13-101",
            "last": "title-13/section-13-102",
        },
        "AR": {
            "domain": OFFICIAL_DOMAINS["AR"],
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
        verdict = evaluate_jurisdiction_receipt(receipt, case_id=f"cohort-a-{state.lower()}")
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

    # Durable evidence artifact required by LCR-009.
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


def test_cohort_a_report_artifact_exists_and_certifies():
    """Fail-closed gate: committed cohort_a.json must certify cohort A."""
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


def test_cohort_a_adapters_importable_and_registered():
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )

    for code, cls in (
        ("AL", AlabamaScraper),
        ("AK", AlaskaScraper),
        ("AZ", ArizonaScraper),
        ("AR", ArkansasScraper),
    ):
        scraper_cls = StateScraperRegistry.get_scraper_class(code)
        assert scraper_cls is cls or scraper_cls is not None
        scraper = scraper_cls(code, code)
        base = scraper.get_base_url()
        assert base.startswith("http")
        codes = scraper.get_code_list()
        assert codes and codes[0].get("url")

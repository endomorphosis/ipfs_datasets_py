"""LCR-089: Montana direct-only residual catalog and leaf closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, Title 0 identity drift, fenced
staging-mt-v11 reuse, and 2016 Wayback bodies as current.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana import (
    MontanaScraper,
    _EXACT_TITLE_SCOPE_EXCLUSIONS,
    _source_bound_title_scope_exclusions_from_root_html,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_isolated_worker import (
    IsolatedRetainedReplayWorkerError,
    build_host_retained_replay_command,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.strict_frontier_closure import (
    retain_exact_state_frontier_closure,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "montana_residual_closure_v1.md"
)

DIRECT_PROJECTION_INPUTS = 40132
DIRECT_PROJECTION_BYTES = 441443821
DIRECT_PROJECTION_SHA256 = (
    "6b8d0baca081c937728b75bd9177fa8654f97dc63a1985e797f3a5017915c271"
)
DIRECT_PROJECTION_SHA256_PREFIX = "6b8d0baca081"
V4_UNIQUE_RECEIPTS = 40136
V4_WAYBACK_RECEIPTS = 4
TITLE_PAGES = 54
STATUTORY_TITLE_CATALOGS = 53
TITLE_0_EXCLUSIONS = 1
TITLE_0_ARTICLE_COUNT = 16
KNOWN_STATUTORY_CHAPTERS = 880
MISSING_LETTERED_CATALOGS = 5
RETAINED_PARTS = 4063
KNOWN_LEAVES = 44433
TYPED_TERMINALS = 14418
ACTIVE_CANDIDATES = 30015
DIRECT_RETAINED_ACTIVE_LEAVES = 23363
RESIDUAL_ACTIVE_LEAVES = 6652
KNOWN_REQUEST_FLOOR = 6657
RESIDUAL_COUNT = 6657
RESIDUAL_SHA256_PREFIX = "2af9f839be75"
RESIDUAL_ACTIVE_LEAF_SHA256 = (
    "2af9f839be756d401a45a07642d9e7fe1da00ce0bbfdae518c9ef74386450970"
)
ALL_TRANSPORT_RESIDUAL_SHA256_PREFIX = "b949f71312a4"
CATALOG_WAVE_NAME = "chapter-index"
RESIDUAL_WAVE_NAME = "section"
PART_WAVE_NAME = "part-index"
TITLE_WAVE_NAME = "title-index"
OFFICIAL_ENTRY = "https://leg.mt.gov/bills/mca/index.html"
TITLE_0_URL = "https://leg.mt.gov/bills/mca/title_0000/chapters_index.html"
FIRST_RESIDUAL_URL = (
    "https://leg.mt.gov/bills/mca/title_0250/chapter_030A/parts_index.html"
)
LAST_MISSING_CATALOG_URL = (
    "https://leg.mt.gov/bills/mca/title_0300/chapter_012A/parts_index.html"
)
MISSING_CATALOG_URLS = (
    "https://leg.mt.gov/bills/mca/title_0250/chapter_030A/parts_index.html",
    "https://leg.mt.gov/bills/mca/title_0300/chapter_002A/parts_index.html",
    "https://leg.mt.gov/bills/mca/title_0300/chapter_004A/parts_index.html",
    "https://leg.mt.gov/bills/mca/title_0300/chapter_009A/parts_index.html",
    "https://leg.mt.gov/bills/mca/title_0300/chapter_012A/parts_index.html",
)
MISSING_LETTERED_CATALOG_IDS = (
    "25-030A",
    "30-002A",
    "30-004A",
    "30-009A",
    "30-012A",
)
WAYBACK_2016_ONLY_SECTIONS = ("39-71-2319", "39-71-2325", "39-71-2328")
REPEALED_NEAR_WAYBACK = "39-71-2324"
INVENTED_CATALOG_URL = (
    "https://leg.mt.gov/bills/mca/title_0990/chapter_099A/parts_index.html"
)
INVENTED_LEAF_URL = (
    "https://leg.mt.gov/bills/mca/title_0990/chapter_099A/part_0010/"
    "section_0010/0990-099A-0010-0010.html"
)
WAYBACK_2016_CAPTURE_URL = (
    "https://web.archive.org/web/20160101000000/"
    "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/part_0230/"
    "section_0190/0390-0710-0230-0190.html"
)
FENCED_STAGING_ROOT = "staging-mt-v11"
DIAGNOSTIC_PRODUCER_PREFIX = "MontanaScraper@sha256:bb4ed1ef"
TITLE_0_ROOT_SHA256_PREFIX = "c945f15a4564"
TITLE_0_ROOT_RECEIPT_PREFIX = "2aed70c22680"
TITLE_0_TITLE_SHA256_PREFIX = "ffd3643dab4e"
TITLE_0_TITLE_RECEIPT_PREFIX = "545e7837b38a"


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _lettered_chapter_catalog_url(title: int, chapter: str) -> str:
    title_url = MontanaScraper("MT", "Montana").official_title_url(title)
    match = re.fullmatch(r"(\d+)([A-Za-z])", chapter)
    if match is None:
        raise AssertionError(f"not a lettered chapter: {chapter!r}")
    token = f"{int(match.group(1)):03d}{match.group(2).upper()}"
    return title_url.replace("chapters_index.html", f"chapter_{token}/parts_index.html")


def _section_html(section_number: str) -> bytes:
    body = (
        f"Official Montana statutory text for section {section_number}. "
        "This public-law provision supplies substantive normalized text. "
    ) * 4
    return (
        "<html><body><main>"
        f"<h1>{section_number}. Official heading.</h1>"
        f"<p>{body}</p>"
        "</main></body></html>"
    ).encode()


def _frontier_result(
    urls: list[str],
    payloads: list[bytes],
) -> StateLawPageMultiFetchResult:
    receipts = []
    envelopes = []
    retrieved_at = "2026-08-27T12:00:00Z"
    for url, payload in zip(urls, payloads, strict=True):
        content_sha256 = hashlib.sha256(payload).hexdigest()
        transport = {
            "content_sha256": content_sha256,
            "official_url": url,
            "source_transport": "direct",
        }
        receipts.append(dict(transport))
        envelopes.append(
            {
                "acquisition": {
                    "receipt": {
                        "endpoint": url,
                        "content": {"sha256": content_sha256},
                        "retrieved_at": retrieved_at,
                    }
                }
            }
        )
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=[None] * len(urls),
        transport_receipts=receipts,
        parser_input_envelopes=envelopes,
        stats={
            "network_requested_pages": 0,
            "direct_initial_successes": len(urls),
            "per_page_archive_fallback_disabled": True,
            "common_crawl": {
                "range_fetch_calls": 1,
                "naive_range_fetches": len(urls),
                "range_fetches_avoided": max(0, len(urls) - 1),
            },
        },
    )


class _MontanaRetainedLedger:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = dict(pages)
        self.refresh_calls = 0
        self.requests: list[str] = []

    def refresh_existing_entries(self) -> int:
        self.refresh_calls += 1
        return 0

    def replay_retained_parser_input(self, *, official_url: str, sanitized_request):
        assert dict(sanitized_request) == {"method": "GET", "url": official_url}
        self.requests.append(official_url)
        payload = self.pages.get(official_url)
        if payload is None:
            return None
        digest = hashlib.sha256(payload).hexdigest()
        return SimpleNamespace(
            envelope=SimpleNamespace(body=payload),
            receipt=SimpleNamespace(content=SimpleNamespace(sha256=digest)),
            transport_receipt={
                "content_sha256": digest,
                "official_url": official_url,
                "source_transport": "direct",
            },
        )


def _source_ordered_catalog_then_leaf_residual(
    catalog_urls: list[str],
    leaf_urls: list[str],
    retained_urls: set[str],
) -> list[str]:
    residual: list[str] = []
    seen: set[str] = set()
    for url in [*catalog_urls, *leaf_urls]:
        if url in retained_urls:
            continue
        if url in seen:
            raise AssertionError("Montana residual frontier repeated a URL")
        seen.add(url)
        residual.append(url)
    return residual


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Montana residual closure report is empty")
    return payload


def _report_table(report: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw_line in report.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        field, value = cells
        if field in {"Field", "---"} or set(field) == {"-"}:
            continue
        rows[field] = value.strip("`")
    return rows


def test_montana_residual_closure_report_records_exact_catalog_and_leaf_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "MT"
    assert table["official domain"] == "leg.mt.gov"
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_title0_url"] == TITLE_0_URL
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == (
        "official MCA root/title/chapter/part/section HTML tree"
    )
    assert table["seed"] == "verified direct-only projection 40132"
    assert table["resume_fenced_staging_mt_v11"] == "forbidden"
    assert table["v11_35072_checkpoint"] == "output_inadmissible"
    assert table["title_0_identity_drift"] == "forbidden"
    assert table["wayback_2016_current_without_equivalence_proof"] == (
        "forbidden"
    )
    assert table["static_residual_list"] == "forbidden"
    assert table["invent_later_lettered_catalogs"] == "forbidden"
    assert table["direct_projection_inputs"] == str(DIRECT_PROJECTION_INPUTS)
    assert table["direct_projection_bytes"] == str(DIRECT_PROJECTION_BYTES)
    assert table["direct_projection_sha256"] == DIRECT_PROJECTION_SHA256
    assert table["direct_projection_sha256_prefix"] == (
        DIRECT_PROJECTION_SHA256_PREFIX
    )
    assert table["v4_unique_receipts"] == str(V4_UNIQUE_RECEIPTS)
    assert table["v4_direct_receipts"] == str(DIRECT_PROJECTION_INPUTS)
    assert table["v4_wayback_receipts"] == str(V4_WAYBACK_RECEIPTS)
    assert table["title_pages"] == str(TITLE_PAGES)
    assert table["statutory_title_catalogs"] == str(STATUTORY_TITLE_CATALOGS)
    assert table["title_0_constitution_exclusions"] == str(TITLE_0_EXCLUSIONS)
    assert table["title_0_article_catalog_count"] == str(TITLE_0_ARTICLE_COUNT)
    assert table["title_0_root_content_sha256_prefix"] == (
        TITLE_0_ROOT_SHA256_PREFIX
    )
    assert table["title_0_root_receipt_sha256_prefix"] == (
        TITLE_0_ROOT_RECEIPT_PREFIX
    )
    assert table["title_0_title_content_sha256_prefix"] == (
        TITLE_0_TITLE_SHA256_PREFIX
    )
    assert table["title_0_title_receipt_sha256_prefix"] == (
        TITLE_0_TITLE_RECEIPT_PREFIX
    )
    assert table["known_statutory_chapters"] == str(KNOWN_STATUTORY_CHAPTERS)
    assert table["missing_lettered_catalogs"] == str(MISSING_LETTERED_CATALOGS)
    assert table["missing_lettered_catalog_ids"] == ", ".join(
        MISSING_LETTERED_CATALOG_IDS
    )
    assert table["retained_parts"] == str(RETAINED_PARTS)
    assert table["known_leaves"] == str(KNOWN_LEAVES)
    assert table["typed_terminals"] == str(TYPED_TERMINALS)
    assert table["active_candidates"] == str(ACTIVE_CANDIDATES)
    assert table["direct_retained_active_leaves"] == str(
        DIRECT_RETAINED_ACTIVE_LEAVES
    )
    assert table["residual_active_leaves"] == str(RESIDUAL_ACTIVE_LEAVES)
    assert table["all_transport_retained_active_leaves"] == "23366"
    assert table["all_transport_residual_active_leaves"] == "6649"
    assert table["wayback_2016_only_active_sections"] == ", ".join(
        WAYBACK_2016_ONLY_SECTIONS
    )
    assert table["source_typed_repealed_near_wayback_actives"] == (
        REPEALED_NEAR_WAYBACK
    )
    assert table["known_request_floor"] == str(KNOWN_REQUEST_FLOOR)
    assert table["catalog_descendant_count"] == (
        "source_dependent_after_five_catalogs"
    )
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == (
        "five missing lettered chapter catalogs then unique ordered "
        "active leaves plus catalog descendants"
    )
    assert table["residual_first_url"] == FIRST_RESIDUAL_URL
    assert table["residual_last_missing_catalog_url"] == LAST_MISSING_CATALOG_URL
    assert table["catalog_wave_name"] == CATALOG_WAVE_NAME
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["part_wave_name"] == PART_WAVE_NAME
    assert table["title_wave_name"] == TITLE_WAVE_NAME
    assert table["catalog_acquisition_wave_count"] == "1"
    assert table["leaf_acquisition_wave_count"] == "1"
    assert table["derive_descendants_of_five_catalogs"] == "true"
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["residual_active_leaf_sha256"] == RESIDUAL_ACTIVE_LEAF_SHA256
    assert table["all_transport_residual_sha256_prefix"] == (
        ALL_TRANSPORT_RESIDUAL_SHA256_PREFIX
    )
    assert table["diagnostic_producer"].startswith(DIAGNOSTIC_PRODUCER_PREFIX)
    assert table["diagnostic_hashes_authorizing"] == "false"
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert (
        int(table["statutory_title_catalogs"])
        + int(table["title_0_constitution_exclusions"])
        == TITLE_PAGES
    )
    assert TYPED_TERMINALS + ACTIVE_CANDIDATES == KNOWN_LEAVES
    assert (
        DIRECT_RETAINED_ACTIVE_LEAVES + RESIDUAL_ACTIVE_LEAVES
        == ACTIVE_CANDIDATES
    )
    assert (
        MISSING_LETTERED_CATALOGS + RESIDUAL_ACTIVE_LEAVES
        == KNOWN_REQUEST_FLOOR
        == RESIDUAL_COUNT
    )
    assert DIRECT_PROJECTION_INPUTS + V4_WAYBACK_RECEIPTS == V4_UNIQUE_RECEIPTS
    assert DIRECT_PROJECTION_SHA256.startswith(DIRECT_PROJECTION_SHA256_PREFIX)
    assert RESIDUAL_ACTIVE_LEAF_SHA256.startswith(RESIDUAL_SHA256_PREFIX)

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "hub mutation" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "title 0" in lowered
    assert "staging-mt-v11" in lowered
    assert "2016" in report and "wayback" in lowered
    assert "6,652" in report
    assert "40,132" in report
    assert "6,657" in report
    assert FIRST_RESIDUAL_URL in report
    assert LAST_MISSING_CATALOG_URL in report
    assert OFFICIAL_ENTRY in report
    assert TITLE_0_URL in report
    for catalog_url in MISSING_CATALOG_URLS:
        assert catalog_url in report
    for section in WAYBACK_2016_ONLY_SECTIONS:
        assert section in report
    assert REPEALED_NEAR_WAYBACK in report
    assert INVENTED_CATALOG_URL not in report
    assert INVENTED_LEAF_URL not in report
    assert WAYBACK_2016_CAPTURE_URL not in report
    assert report.count("/section_") < 8
    assert FENCED_STAGING_ROOT in report


def test_montana_lettered_catalog_locators_are_exact_and_not_inferred() -> None:
    scraper = MontanaScraper("MT", "Montana")
    assert scraper.get_base_url() == "https://leg.mt.gov"
    assert scraper.OFFICIAL_ENTRY_URL == OFFICIAL_ENTRY
    assert scraper.official_title_url(25) == (
        "https://leg.mt.gov/bills/mca/title_0250/chapters_index.html"
    )
    assert scraper.official_title_url(30) == (
        "https://leg.mt.gov/bills/mca/title_0300/chapters_index.html"
    )
    derived = (
        _lettered_chapter_catalog_url(25, "30A"),
        _lettered_chapter_catalog_url(30, "2A"),
        _lettered_chapter_catalog_url(30, "4A"),
        _lettered_chapter_catalog_url(30, "9A"),
        _lettered_chapter_catalog_url(30, "12A"),
    )
    assert derived == MISSING_CATALOG_URLS
    assert derived[0] == FIRST_RESIDUAL_URL
    assert derived[-1] == LAST_MISSING_CATALOG_URL
    assert _lettered_chapter_catalog_url(99, "99A") == INVENTED_CATALOG_URL
    assert INVENTED_CATALOG_URL not in MISSING_CATALOG_URLS

    title_html = (
        "<a href='./chapter_0010/parts_index.html'>Chapter 1</a>"
        "<a href='./chapter_030A/parts_index.html'>Chapter 30A</a>"
    )
    extracted = scraper._extract_html_mca_links(
        title_html,
        scraper.official_title_url(25),
        scraper._MT_CHAPTER_INDEX_HREF_RE,
    )
    assert extracted == [
        (
            "Chapter 1",
            "https://leg.mt.gov/bills/mca/title_0250/chapter_0010/parts_index.html",
        ),
        ("Chapter 30A", FIRST_RESIDUAL_URL),
    ]
    lettered_section = (
        "https://leg.mt.gov/bills/mca/title_0250/chapter_030A/part_0010/"
        "section_0010/0250-030A-0010-0010.html"
    )
    assert scraper._section_number_from_mca_url(
        lettered_section,
        section_label="25-30A-101 Official provision.",
    ) == "25-30A-101"


def test_montana_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(MontanaScraper)
    html_tree = inspect.getsource(MontanaScraper._scrape_official_mca_html_tree)
    frontier = inspect.getsource(MontanaScraper._scrape_official_mca_html_frontier)
    scrape_source = inspect.getsource(MontanaScraper.scrape_code)
    assert str(RESIDUAL_ACTIVE_LEAVES) not in adapter
    assert str(DIRECT_PROJECTION_INPUTS) not in adapter
    assert str(KNOWN_REQUEST_FLOOR) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert DIRECT_PROJECTION_SHA256_PREFIX not in adapter
    assert FIRST_RESIDUAL_URL not in adapter
    assert INVENTED_CATALOG_URL not in adapter
    assert INVENTED_LEAF_URL not in adapter
    assert WAYBACK_2016_CAPTURE_URL not in adapter
    assert "chapter_030A" not in adapter
    assert "chapter_002A" not in adapter
    assert "chapter_099A" not in adapter
    assert "39-71-2319" not in adapter
    assert "OFFICIAL_TITLES" not in html_tree
    assert "OFFICIAL_TITLES" not in frontier
    assert "_extract_html_mca_links" in html_tree
    assert 'frontier_name="chapter-index"' in frontier
    assert 'frontier_name="section"' in frontier
    assert "return []" in scrape_source
    assert adapter.count("https://leg.mt.gov/bills/mca/") < 20


def test_montana_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    compact = [FIRST_RESIDUAL_URL, LAST_MISSING_CATALOG_URL]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://leg.mt.gov/bills/mca/title_0250/chapter_030A/parts_index.html",'
        b'"https://leg.mt.gov/bills/mca/title_0300/chapter_012A/parts_index.html"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert compact_digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    catalog_digest = _canonical_residual_sha256(list(MISSING_CATALOG_URLS))
    assert len(catalog_digest) == 64
    assert catalog_digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert CATALOG_WAVE_NAME in report
    assert DIRECT_PROJECTION_SHA256 in report
    assert RESIDUAL_ACTIVE_LEAF_SHA256 in report


def test_montana_one_global_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(MontanaScraper._fetch_montana_frontier_batch)
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert "common_crawl_domain_terms=" in fetch_source
    assert '("leg.mt.gov",)' in fetch_source
    assert "common_crawl_url_terms=" in fetch_source
    assert '"/bills/mca/"' in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "Acquire one complete ordered dependency level as one plural wave" in (
        fetch_source
    )

    retry_source = inspect.getsource(
        MontanaScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in (
        retry_source
    )
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        MontanaScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"residual_only_retries": True' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"wayback_prefix_inventory": True' in closure_source
    assert '"repeat_grouped_archive_inventory_on_residual": False' in (
        closure_source
    )
    assert '"leaf_frontier_plural_waves": 1' in closure_source
    assert '"source_ordered_cross_parent_union": True' in closure_source


def test_montana_seed_and_host_replay_forbid_hub_docker_v11_and_wayback_current(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source
    assert "unverifiable Wayback receipts" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "MT",
            "--scrape",
            "--retained-replay-only",
            "--strict-acquisition-evidence",
            "--no-incremental-state-publish",
        ],
        workdir=tmp_path,
    )
    joined = " ".join(command)
    assert "docker" not in command
    assert "--network" not in command
    assert "--publish-to-hf" not in command
    assert "--retained-replay-only" in command
    assert "--no-incremental-state-publish" in command
    assert "docker" not in joined.casefold()

    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="must not invoke docker",
    ):
        build_host_retained_replay_command(
            argv=["docker", "run", "--network", "none"],
            workdir=tmp_path,
        )

    report = " ".join(_report_text().casefold().split())
    assert "hub mutation" in report
    assert "docker-copying" in report or "docker-copy" in report
    assert "staging-mt-v11" in report
    assert "2016" in report and "wayback" in report
    assert "title 0" in report


def test_montana_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    montana_source = inspect.getsource(
        MontanaScraper.produce_state_law_frontier_closure
    )
    replay_source = inspect.getsource(MontanaScraper._replay_montana_source_frontier)
    assert "public_law_no_state_copyright" in montana_source or (
        "rights" in closure_source.casefold()
    )
    assert "retained_replay_network_requests" in montana_source
    assert montana_source.index('"retained_replay_network_requests": 0') > 0
    assert "Reparse every retained MCA hierarchy input with zero network I/O" in (
        replay_source
    )
    assert "Montana retained title membership changed" in replay_source
    assert "Montana retained chapter membership changed" in replay_source


def test_montana_title_0_constitution_identity_cannot_drift() -> None:
    expected = _EXACT_TITLE_SCOPE_EXCLUSIONS[TITLE_0_URL]
    assert expected["disposition"] == "separate_constitution_scope"
    assert expected["non_default_configuration"] == "constitutions"
    assert expected["root_url"] == OFFICIAL_ENTRY
    assert expected["source_label"] == "THE CONSTITUTION OF THE STATE OF MONTANA"
    assert len(expected["article_links"]) == TITLE_0_ARTICLE_COUNT
    assert expected["root_content_sha256"].startswith(TITLE_0_ROOT_SHA256_PREFIX)
    assert expected["root_receipt_sha256"].startswith(TITLE_0_ROOT_RECEIPT_PREFIX)
    assert expected["title_content_sha256"].startswith(TITLE_0_TITLE_SHA256_PREFIX)
    assert expected["title_receipt_sha256"].startswith(
        TITLE_0_TITLE_RECEIPT_PREFIX
    )
    assert int(expected["root_content_byte_size"]) == 20653
    assert int(expected["title_content_byte_size"]) == 10748

    drifted = _source_bound_title_scope_exclusions_from_root_html(
        b"<html>not the retained MCA root</html>",
        source_url=OFFICIAL_ENTRY,
    )
    assert drifted == {}

    digest = hashlib.sha256(b"retained parser input").hexdigest()
    scraper = MontanaScraper("MT", "Montana")
    with pytest.raises(
        RuntimeError,
        match="separate constitutional scope is not source-bound",
    ):
        scraper._montana_exact_frontier(
            root_report={
                "content_sha256": digest,
                "source_url": OFFICIAL_ENTRY,
                "title_count": 2,
                "title_scope_exclusion_count": 1,
                "title_scope_exclusions": [
                    {
                        "disposition": "separate_constitution_scope",
                        "source_url": TITLE_0_URL,
                    }
                ],
            },
            title_reports=[
                {
                    "chapter_count": 0,
                    "content_sha256": digest,
                    "disposition": "separate_constitution_scope",
                    "evidence_kind": "source_bound_separate_configuration",
                    "non_default_configuration": "default",
                    "root_catalog_content_sha256": digest,
                    "source_url": TITLE_0_URL,
                },
                {
                    "chapter_count": 1,
                    "content_sha256": digest,
                    "disposition": "statutory_hierarchy",
                    "source_url": scraper.official_title_url(1),
                },
            ],
            chapter_reports=[
                {
                    "content_sha256": digest,
                    "part_count": 1,
                    "source_url": (
                        "https://leg.mt.gov/bills/mca/title_0010/"
                        "chapter_0010/parts_index.html"
                    ),
                }
            ],
            part_reports=[
                {
                    "content_sha256": digest,
                    "section_count": 1,
                    "source_url": (
                        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/"
                        "part_0010/sections_index.html"
                    ),
                }
            ],
            section_reports=[
                {
                    "canonical_identity": "1-1-101",
                    "content_sha256": digest,
                    "disposition": "operative",
                    "source_url": (
                        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/"
                        "part_0010/section_0010/0010-0010-0010-0010.html"
                    ),
                }
            ],
            terminal_dispositions={},
        )

    report = " ".join(_report_text().casefold().split())
    assert "title 0" in report
    assert "separate_constitution_scope" in _report_text()
    assert TITLE_0_URL in _report_text()


def test_montana_compact_catalog_recipe_emits_descendants_not_invented_or_wayback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    base = "https://leg.mt.gov/bills/mca"
    title_1 = f"{base}/title_0010/chapters_index.html"
    title_25 = f"{base}/title_0250/chapters_index.html"
    chapter_1 = f"{base}/title_0010/chapter_0010/parts_index.html"
    chapter_25_1 = f"{base}/title_0250/chapter_0010/parts_index.html"
    missing_catalog = FIRST_RESIDUAL_URL
    part_1 = f"{base}/title_0010/chapter_0010/part_0010/sections_index.html"
    part_25_1 = f"{base}/title_0250/chapter_0010/part_0010/sections_index.html"
    part_25_30a = (
        f"{base}/title_0250/chapter_030A/part_0010/sections_index.html"
    )
    leaf_1 = (
        f"{base}/title_0010/chapter_0010/part_0010/section_0010/"
        "0010-0010-0010-0010.html"
    )
    leaf_25_1 = (
        f"{base}/title_0250/chapter_0010/part_0010/section_0010/"
        "0250-0010-0010-0010.html"
    )
    descendant_leaf = (
        f"{base}/title_0250/chapter_030A/part_0010/section_0010/"
        "0250-030A-0010-0010.html"
    )
    terminal_url = (
        f"{base}/title_0010/chapter_0010/part_0010/section_0020/"
        "0010-0010-0010-0020.html"
    )
    titles = [
        ("Title 1", title_1),
        ("Title 25", title_25),
    ]
    pages = {
        title_1: (
            "<a href='chapter_0010/parts_index.html'>Chapter 1</a>"
        ).encode(),
        title_25: (
            "<a href='chapter_0010/parts_index.html'>Chapter 1</a>"
            "<a href='chapter_030A/parts_index.html'>Chapter 30A</a>"
        ).encode(),
        chapter_1: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
        ).encode(),
        chapter_25_1: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
        ).encode(),
        missing_catalog: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
        ).encode(),
        part_1: (
            "<a href='./section_0010/0010-0010-0010-0010.html'>"
            "1-1-101 Active</a>"
            "<a href='./section_0020/0010-0010-0010-0020.html'>"
            "1-1-102 Repealed</a>"
        ).encode(),
        part_25_1: (
            "<a href='./section_0010/0250-0010-0010-0010.html'>"
            "25-1-101 Active</a>"
        ).encode(),
        part_25_30a: (
            "<a href='./section_0010/0250-030A-0010-0010.html'>"
            "25-30A-101 Active</a>"
        ).encode(),
        leaf_1: _section_html("1-1-101"),
        leaf_25_1: _section_html("25-1-101"),
        descendant_leaf: _section_html("25-30A-101"),
    }
    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(urls, *, frontier_name: str, reader: bool = False):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        assert INVENTED_CATALOG_URL not in requested
        assert INVENTED_LEAF_URL not in requested
        assert WAYBACK_2016_CAPTURE_URL not in requested
        assert terminal_url not in requested
        assert TITLE_0_URL not in requested
        return [pages[url] for url in requested]

    monkeypatch.setattr(scraper, "_fetch_montana_frontier_batch", _batch)
    monkeypatch.setattr(
        scraper, "_write_partial_checkpoint", lambda *args, **kwargs: True
    )

    rows = asyncio.run(
        scraper._scrape_official_mca_html_frontier(
            "Montana Code Annotated",
            titles,
        )
    )

    assert [name for name, _urls in batch_calls] == [
        TITLE_WAVE_NAME,
        CATALOG_WAVE_NAME,
        PART_WAVE_NAME,
        RESIDUAL_WAVE_NAME,
    ]
    assert batch_calls[0][1] == [title_1, title_25]
    assert batch_calls[1][1] == [chapter_1, chapter_25_1, missing_catalog]
    assert batch_calls[2][1] == [part_1, part_25_1, part_25_30a]
    assert batch_calls[3][1] == [leaf_1, leaf_25_1, descendant_leaf]
    assert [row.section_number for row in rows] == [
        "1-1-101",
        "25-1-101",
        "25-30A-101",
    ]
    retained = {chapter_1, chapter_25_1, leaf_1, leaf_25_1}
    residual = _source_ordered_catalog_then_leaf_residual(
        [chapter_1, chapter_25_1, missing_catalog],
        [leaf_1, leaf_25_1, descendant_leaf],
        retained,
    )
    assert residual == [missing_catalog, descendant_leaf]
    assert INVENTED_CATALOG_URL not in residual
    assert WAYBACK_2016_CAPTURE_URL not in residual
    digest = _canonical_residual_sha256(residual)
    assert digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    assert len(digest) == 64


def test_montana_invented_later_lettered_catalog_is_not_residual_membership() -> None:
    retained = {MISSING_CATALOG_URLS[0]}
    residual = _source_ordered_catalog_then_leaf_residual(
        list(MISSING_CATALOG_URLS),
        [],
        retained,
    )
    assert residual == list(MISSING_CATALOG_URLS[1:])
    assert INVENTED_CATALOG_URL not in residual
    assert FIRST_RESIDUAL_URL not in residual
    invented_union = [*MISSING_CATALOG_URLS, INVENTED_CATALOG_URL]
    invented_residual = _source_ordered_catalog_then_leaf_residual(
        invented_union,
        [INVENTED_LEAF_URL],
        set(MISSING_CATALOG_URLS),
    )
    assert invented_residual == [INVENTED_CATALOG_URL, INVENTED_LEAF_URL]
    report = _report_text()
    assert INVENTED_CATALOG_URL not in report
    assert "invent" in report.casefold()
    assert "title_0990/chapter_099A" in report or "lettered" in report.casefold()


def test_montana_retained_replay_only_miss_does_not_invent_catalog_or_per_page_loop() -> None:
    scraper = MontanaScraper("MT", "Montana")
    scraper._state_law_acquisition_ledger = _MontanaRetainedLedger({})
    with pytest.raises(
        RuntimeError,
        match="Montana chapter-index retained replay is missing",
    ):
        scraper._replay_montana_retained_inputs(
            [FIRST_RESIDUAL_URL],
            frontier_name=CATALOG_WAVE_NAME,
        )
    assert scraper._state_law_acquisition_ledger.requests == [FIRST_RESIDUAL_URL]

    fetch_source = inspect.getsource(MontanaScraper._fetch_montana_frontier_batch)
    replay_source = inspect.getsource(MontanaScraper._replay_montana_retained_inputs)
    assert "never through a network" in replay_source
    assert INVENTED_CATALOG_URL not in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "per-page" not in fetch_source.casefold()


def test_montana_wayback_2016_bodies_are_not_current_without_equivalence_proof() -> None:
    scraper = MontanaScraper("MT", "Montana")
    wayback_section = (
        "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/part_0230/"
        "section_0190/0390-0710-0230-0190.html"
    )
    assert scraper._section_number_from_mca_url(
        wayback_section,
        section_label="39-71-2319 Official provision.",
    ) == "39-71-2319"
    adapter = inspect.getsource(MontanaScraper)
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert WAYBACK_2016_CAPTURE_URL not in adapter
    assert "39-71-2319" not in adapter
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    report = _report_text()
    assert "current-equivalence proof" in report
    for section in WAYBACK_2016_ONLY_SECTIONS:
        assert section in report
    assert REPEALED_NEAR_WAYBACK in report
    assert "2016 Wayback" in report or "2016-only" in report.casefold()
    lowered = " ".join(report.casefold().split())
    assert "wayback" in lowered
    assert "without an equivalence proof" in lowered or (
        "without an explicit current-equivalence proof" in lowered
    )

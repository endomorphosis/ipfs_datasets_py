"""LCR-091: Minnesota current-edition leaf residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, guessed later cite URLs, merging
residuals across states, and stamping 2018-2024 Wayback bodies current.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
    MinnesotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota_section import (
    BASE,
    minnesota_statutes_edition_from_html,
    parse_minnesota_section_html,
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
    / "minnesota_residual_closure_v1.md"
)
SEED_SOURCE_PATH = (
    REPO_ROOT
    / "ipfs_datasets_py"
    / "processors"
    / "legal_data"
    / "state_laws_retained_evidence_seed.py"
)

SOURCE_LEAVES = 54435
REQUIRED_DETAIL_URLS = 54383
CATALOG_BOUND_RENUMBERED_TERMINALS = 52
PARSER_INPUT_FRONTIER = 55622
ROOT_PAGES = 1
TOC_PART_COUNT = 105
CHAPTER_CATALOG_COUNT = 1133
DIRECT_PROJECTION_UNIQUE_IDENTITIES = 38875
CURRENT_PARSER_INPUTS = 38824
EXCLUDED_CATALOG_TERMINAL_RETAINED_DETAILS = 51
REQUIRED_RETAINED_DETAIL_BODIES = 37585
RETAINED_OPERATIVE_DETAILS = 18990
RETAINED_TYPED_TERMINAL_DETAILS = 18595
RETAINED_LEAF_CLOSURE = 37637
WAYBACK_HISTORICAL_EDITION_RECEIPTS = 48
DIAGNOSTIC_AUDIT_RESIDUAL_COUNT = 16750
RESIDUAL_COUNT = 16798
RESIDUAL_SHA256 = (
    "105c435137f5aef76b5f48662feb9aaa7ea150a5f962a82b29ad2d0032a583fd"
)
RESIDUAL_SHA256_PREFIX = "105c435137f5"
RESIDUAL_WAVE_NAME = "section"
TOC_PART_WAVE_NAME = "toc-part"
CATALOG_WAVE_NAME = "chapter-index"
OFFICIAL_EDITION = "2025 Minnesota Statutes"
FIRST_SECTION = "84A.50"
LAST_SECTION = "648.51"
FIRST_RESIDUAL_URL = "https://www.revisor.mn.gov/statutes/cite/84A.50"
LAST_RESIDUAL_URL = "https://www.revisor.mn.gov/statutes/cite/648.51"
OFFICIAL_ENTRY = "https://www.revisor.mn.gov/statutes/"
OFFICIAL_SECTION_LOCATOR = "https://www.revisor.mn.gov/statutes/cite/"
GUESSED_NEXT_URL = "https://www.revisor.mn.gov/statutes/cite/84A.51"
INVENTED_SECTION_URL = "https://www.revisor.mn.gov/statutes/cite/99.99"
SUPERSEDED_DIAGNOSTIC_FIRST_URL = (
    "https://www.revisor.mn.gov/statutes/cite/336.1-301"
)
CROSS_STATE_MO_URL = (
    "https://revisor.mo.gov/main/OneSection.aspx?section=70.655"
)
CROSS_STATE_WA_URL = (
    "https://app.leg.wa.gov/RCW/default.aspx?cite=7.05.230"
)
WAYBACK_2018_CAPTURE_URL = (
    "https://web.archive.org/web/20180101000000/"
    "https://www.revisor.mn.gov/statutes/cite/84A.50"
)
HISTORICAL_EDITIONS = (
    "2018 Minnesota Statutes",
    "2019 Minnesota Statutes",
    "2020 Minnesota Statutes",
    "2024 Minnesota Statutes",
)
DIAGNOSTIC_PRODUCER_PREFIX = "MinnesotaScraper@sha256:703b99e425ee"


def _section_url(section: str) -> str:
    return f"{OFFICIAL_SECTION_LOCATOR}{section}"


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _source_ordered_detail_residual(
    detail_urls: list[str],
    retained_detail_urls: set[str],
) -> list[str]:
    residual: list[str] = []
    seen: set[str] = set()
    for url in detail_urls:
        if url in retained_detail_urls:
            continue
        if url in seen:
            raise AssertionError(
                "Minnesota current-edition residual frontier repeated a URL"
            )
        seen.add(url)
        residual.append(url)
    return residual


def _current_page(body: str, *, edition: str = OFFICIAL_EDITION) -> bytes:
    return (
        "<html><body>"
        f"<div id='header'><h1>{edition}</h1></div>"
        f"{body}"
        "</body></html>"
    ).encode()


def _root_html(parts: list[tuple[str, str, str]]) -> bytes:
    rows = "".join(
        f"<tr><td><a href='{href}'>{chapter_range}</a></td>"
        f"<td>{name}</td></tr>"
        for href, chapter_range, name in parts
    )
    return _current_page(f"<table id='toc_table'>{rows}</table>")


def _toc_part_html(chapters: list[tuple[str, str]]) -> bytes:
    rows = "".join(
        f"<tr><td><a href='/statutes/cite/{number}'>{number}</a></td>"
        f"<td>{name}</td></tr>"
        for number, name in chapters
    )
    return _current_page(f"<table id='chapters_table'>{rows}</table>")


def _chapter_html(sections: list[str]) -> bytes:
    rows = "".join(
        "<tr><td><a href='/statutes/cite/"
        f"{section}'>{section}</a></td>"
        f"<td>Caption for {section}</td></tr>"
        for section in sections
    )
    return _current_page(
        f"<div id='chapter_analysis'><table>{rows}</table></div>"
    )


def _section_html(
    section: str,
    *,
    edition: str = OFFICIAL_EDITION,
) -> bytes:
    body = (
        f"Official Minnesota statutory text for section {section}. "
        "This public-law provision supplies substantive normalized text. "
    ) * 4
    return _current_page(
        f"<div class='section' id='stat.{section}'>"
        f"<h2 class='shn'>{section}. Official heading.</h2>"
        f"<p>{body}</p>"
        "</div>",
        edition=edition,
    )


def _frontier_result(
    urls: list[str],
    pages: dict[str, bytes],
) -> StateLawPageMultiFetchResult:
    payloads = [pages[url] for url in urls]
    transport_receipts: list[dict[str, str]] = []
    envelopes: list[dict[str, Any]] = []
    retrieved_at = "2026-08-26T00:00:00Z"
    for url, payload in zip(urls, payloads, strict=True):
        digest = hashlib.sha256(payload).hexdigest()
        transport = {
            "content_sha256": digest,
            "official_url": url,
            "source_transport": "direct",
        }
        transport_receipts.append(transport)
        envelopes.append(
            {
                "acquisition": {
                    "body_sha256": digest,
                    "receipt": {
                        "content": {"sha256": digest},
                        "endpoint": url,
                        "metadata": {"transport_receipt": dict(transport)},
                        "receipt_sha256": f"receipt-{digest}",
                        "retrieved_at": retrieved_at,
                    },
                }
            }
        )
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=[None] * len(urls),
        transport_receipts=transport_receipts,
        parser_input_envelopes=envelopes,
        stats={
            "network_requested_pages": 0,
            "per_page_archive_fallback_disabled": True,
            "requested_pages": len(urls),
        },
    )


def _compact_catalog_pages() -> tuple[
    dict[str, bytes],
    list[str],
    list[str],
    list[str],
    set[str],
]:
    toc_part_urls = [
        "https://www.revisor.mn.gov/statutes/cite/1?view=toc",
        "https://www.revisor.mn.gov/statutes/cite/648?view=toc",
    ]
    chapter_tokens = ["1", "84A", "648"]
    chapter_urls = [
        f"https://www.revisor.mn.gov/statutes/cite/{token}"
        for token in chapter_tokens
    ]
    retained_sections = ["1.01"]
    residual_sections = [FIRST_SECTION, LAST_SECTION]
    section_urls = [_section_url(section) for section in [
        *retained_sections,
        *residual_sections,
    ]]
    pages = {
        OFFICIAL_ENTRY: _root_html(
            [
                (toc_part_urls[0], "1-84A", "Sovereignty through lands"),
                (toc_part_urls[1], "648", "Process"),
            ]
        ),
        toc_part_urls[0]: _toc_part_html(
            [("1", "Sovereignty, Jurisdiction"), ("84A", "Lands Dedicated")]
        ),
        toc_part_urls[1]: _toc_part_html([("648", "Process; Publication")]),
        chapter_urls[0]: _chapter_html(retained_sections),
        chapter_urls[1]: _chapter_html([FIRST_SECTION]),
        chapter_urls[2]: _chapter_html([LAST_SECTION]),
        **{
            url: _section_html(url.rsplit("/", 1)[-1])
            for url in section_urls
        },
    }
    retained = {_section_url(section) for section in retained_sections}
    return pages, toc_part_urls, chapter_urls, section_urls, retained


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Minnesota residual closure report is empty")
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


def test_minnesota_residual_closure_report_records_exact_current_edition_leaf_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "MN"
    assert table["official domain"] == "www.revisor.mn.gov"
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_edition"] == OFFICIAL_EDITION
    assert table["official_section_locator"] == OFFICIAL_SECTION_LOCATOR
    assert table["edition_guard"] == (
        "exact #header > h1 bound to 2025 Minnesota Statutes"
    )
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["seed"] == "verified direct-only projection"
    assert table["historical_archive_edition_admission"] == "forbidden"
    assert table["wayback_2018_2024_current_without_equivalence_proof"] == (
        "forbidden"
    )
    assert table["hyphenated_citation_21853_checkpoint"] == (
        "output_inadmissible"
    )
    assert table["static_residual_list"] == "forbidden"
    assert table["guess_later_urls"] == "forbidden"
    assert table["merge_residuals_across_states"] == "forbidden"
    assert table["source_leaves"] == str(SOURCE_LEAVES)
    assert table["required_detail_urls"] == str(REQUIRED_DETAIL_URLS)
    assert table["catalog_bound_renumbered_terminals"] == str(
        CATALOG_BOUND_RENUMBERED_TERMINALS
    )
    assert table["parser_input_frontier"] == str(PARSER_INPUT_FRONTIER)
    assert table["root_pages"] == str(ROOT_PAGES)
    assert table["toc_part_count"] == str(TOC_PART_COUNT)
    assert table["chapter_catalog_count"] == str(CHAPTER_CATALOG_COUNT)
    assert table["direct_projection_unique_identities"] == str(
        DIRECT_PROJECTION_UNIQUE_IDENTITIES
    )
    assert table["current_parser_inputs"] == str(CURRENT_PARSER_INPUTS)
    assert table["excluded_catalog_terminal_retained_details"] == str(
        EXCLUDED_CATALOG_TERMINAL_RETAINED_DETAILS
    )
    assert table["required_retained_detail_bodies"] == str(
        REQUIRED_RETAINED_DETAIL_BODIES
    )
    assert table["retained_operative_details"] == str(
        RETAINED_OPERATIVE_DETAILS
    )
    assert table["retained_typed_terminal_details"] == str(
        RETAINED_TYPED_TERMINAL_DETAILS
    )
    assert table["unclassified_retained_details"] == "0"
    assert table["retained_leaf_closure"] == str(RETAINED_LEAF_CLOSURE)
    assert table["wayback_historical_edition_receipts"] == str(
        WAYBACK_HISTORICAL_EDITION_RECEIPTS
    )
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == "current-edition detail URLs"
    assert table["residual_first_section"] == FIRST_SECTION
    assert table["residual_last_section"] == LAST_SECTION
    assert table["residual_first_url"] == FIRST_RESIDUAL_URL
    assert table["residual_last_url"] == LAST_RESIDUAL_URL
    assert table["residual_ordered_sha256"] == RESIDUAL_SHA256
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["toc_part_wave_name"] == TOC_PART_WAVE_NAME
    assert table["catalog_wave_name"] == CATALOG_WAVE_NAME
    assert table["hierarchy_wave_count"] == "3"
    assert table["leaf_acquisition_wave_count"] == "1"
    assert table["source_ordered_cross_parent_union"] == "true"
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["diagnostic_producer"].startswith(DIAGNOSTIC_PRODUCER_PREFIX)
    assert table["diagnostic_hashes_authorizing"] == "false"

    assert (
        ROOT_PAGES
        + TOC_PART_COUNT
        + CHAPTER_CATALOG_COUNT
        + REQUIRED_DETAIL_URLS
        == PARSER_INPUT_FRONTIER
    )
    assert (
        REQUIRED_DETAIL_URLS + CATALOG_BOUND_RENUMBERED_TERMINALS
        == SOURCE_LEAVES
    )
    assert (
        ROOT_PAGES
        + TOC_PART_COUNT
        + CHAPTER_CATALOG_COUNT
        + REQUIRED_RETAINED_DETAIL_BODIES
        == CURRENT_PARSER_INPUTS
    )
    assert (
        CURRENT_PARSER_INPUTS + EXCLUDED_CATALOG_TERMINAL_RETAINED_DETAILS
        == DIRECT_PROJECTION_UNIQUE_IDENTITIES
    )
    assert (
        RETAINED_OPERATIVE_DETAILS + RETAINED_TYPED_TERMINAL_DETAILS
        == REQUIRED_RETAINED_DETAIL_BODIES
    )
    assert (
        REQUIRED_RETAINED_DETAIL_BODIES + CATALOG_BOUND_RENUMBERED_TERMINALS
        == RETAINED_LEAF_CLOSURE
    )
    assert (
        REQUIRED_DETAIL_URLS - REQUIRED_RETAINED_DETAIL_BODIES == RESIDUAL_COUNT
    )
    assert SOURCE_LEAVES - RETAINED_LEAF_CLOSURE == RESIDUAL_COUNT
    assert (
        DIAGNOSTIC_AUDIT_RESIDUAL_COUNT + WAYBACK_HISTORICAL_EDITION_RECEIPTS
        == RESIDUAL_COUNT
    )
    assert RESIDUAL_SHA256.startswith(RESIDUAL_SHA256_PREFIX)
    assert len(RESIDUAL_SHA256) == 64

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "hub mutation" in lowered
    assert "guess later" in lowered or "guessed later" in lowered
    assert "merge" in lowered and "across states" in lowered
    assert "verified direct" in lowered
    assert "2018" in report and "2024" in report
    assert "wayback" in lowered
    assert "21,853" in report
    assert "hyphenated" in lowered
    assert "16,750" in report
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "16,798" in report
    assert "54,383" in report
    assert "38,824" in report
    assert FIRST_RESIDUAL_URL in report
    assert LAST_RESIDUAL_URL in report
    assert RESIDUAL_SHA256 in report
    assert RESIDUAL_SHA256_PREFIX in report
    assert OFFICIAL_EDITION in report
    assert GUESSED_NEXT_URL not in report
    assert INVENTED_SECTION_URL not in report
    assert CROSS_STATE_MO_URL not in report
    assert CROSS_STATE_WA_URL not in report
    assert WAYBACK_2018_CAPTURE_URL not in report
    assert "336.1-301" in report
    assert SUPERSEDED_DIAGNOSTIC_FIRST_URL not in report
    assert report.count("https://www.revisor.mn.gov/statutes/cite/") < 12


def test_minnesota_section_locator_is_exact_and_not_guessed() -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    assert scraper.OFFICIAL_ENTRY_URL == OFFICIAL_ENTRY
    assert scraper.OFFICIAL_DOMAIN == "www.revisor.mn.gov"
    assert scraper.OFFICIAL_EDITION == OFFICIAL_EDITION
    assert scraper.official_chapter_url("84A") == (
        "https://www.revisor.mn.gov/statutes/cite/84A"
    )
    assert _section_url(FIRST_SECTION) == FIRST_RESIDUAL_URL
    assert _section_url(LAST_SECTION) == LAST_RESIDUAL_URL
    assert _section_url("84A.51") == GUESSED_NEXT_URL
    assert _section_url("84A.51") != FIRST_RESIDUAL_URL
    assert _section_url("99.99") == INVENTED_SECTION_URL
    assert FIRST_RESIDUAL_URL.startswith(OFFICIAL_SECTION_LOCATOR)
    assert LAST_RESIDUAL_URL.startswith(OFFICIAL_SECTION_LOCATOR)
    assert BASE == "https://www.revisor.mn.gov/statutes"

    match = scraper._MN_SECTION_NUMBER_RE.search(FIRST_RESIDUAL_URL)
    assert match is not None
    assert match.group(1) == FIRST_SECTION
    last_match = scraper._MN_SECTION_NUMBER_RE.search(LAST_RESIDUAL_URL)
    assert last_match is not None
    assert last_match.group(1) == LAST_SECTION

    unbounded = inspect.getsource(MinnesotaScraper._scrape_chapter_sections)
    assert 'frontier_name="section"' in unbounded
    assert "Acquire the exact source-ordered cross-chapter union once" in unbounded
    assert FIRST_RESIDUAL_URL not in unbounded
    assert LAST_RESIDUAL_URL not in unbounded
    assert GUESSED_NEXT_URL not in unbounded
    assert INVENTED_SECTION_URL not in unbounded
    assert re.search(
        r"/statutes/cite/\{match\.group\('section'\)\}",
        inspect.getsource(MinnesotaScraper._extract_section_urls_from_chapter_page),
    )


def test_minnesota_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(MinnesotaScraper)
    discover = inspect.getsource(MinnesotaScraper._discover_chapter_urls)
    unbounded = inspect.getsource(MinnesotaScraper._scrape_chapter_sections)
    assert str(RESIDUAL_COUNT) not in adapter
    assert str(REQUIRED_DETAIL_URLS) not in adapter
    assert str(CURRENT_PARSER_INPUTS) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert RESIDUAL_SHA256 not in unbounded
    assert FIRST_RESIDUAL_URL not in adapter
    assert LAST_RESIDUAL_URL not in adapter
    assert GUESSED_NEXT_URL not in adapter
    assert INVENTED_SECTION_URL not in adapter
    assert CROSS_STATE_MO_URL not in adapter
    assert CROSS_STATE_WA_URL not in adapter
    assert "336.1-301" not in adapter
    assert "OFFICIAL_NUMERIC_CHAPTERS" not in discover
    assert "OFFICIAL_LETTERED_CHAPTERS" not in discover
    assert "OFFICIAL_NUMERIC_CHAPTERS" not in unbounded
    assert "toc_part_rows" in discover
    assert "chapter_table_rows" in discover
    assert "_extract_section_urls_from_chapter_page" in unbounded
    cite_literals = set(
        re.findall(r"/statutes/cite/([0-9A-Za-z.\-]+)", adapter)
    )
    assert FIRST_SECTION not in cite_literals
    assert LAST_SECTION not in cite_literals
    assert "84A.51" not in cite_literals
    assert "99.99" not in cite_literals


def test_minnesota_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    compact = [FIRST_RESIDUAL_URL, LAST_RESIDUAL_URL]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://www.revisor.mn.gov/statutes/cite/84A.50",'
        b'"https://www.revisor.mn.gov/statutes/cite/648.51"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert not compact_digest.startswith(RESIDUAL_SHA256_PREFIX)
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    unbounded = inspect.getsource(MinnesotaScraper._scrape_chapter_sections)
    assert "Minnesota official chapter frontier repeated a section URL" in unbounded
    assert '"source_ordered_cross_parent_union": True' in inspect.getsource(
        MinnesotaScraper.produce_state_law_frontier_closure
    )


def test_minnesota_one_global_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(
        MinnesotaScraper._fetch_minnesota_frontier_batch
    )
    chunks_source = inspect.getsource(
        MinnesotaScraper._fetch_minnesota_frontier_in_chunks
    )
    unbounded = inspect.getsource(MinnesotaScraper._scrape_chapter_sections)
    assert '"wayback_prefix_inventory": True' in fetch_source
    assert '"common_crawl_domain_terms": ("www.revisor.mn.gov",)' in fetch_source
    assert '"common_crawl_url_terms": ("/statutes/",)' in fetch_source
    assert '"prefer_direct": True' in fetch_source
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert "repeat_grouped_archive_inventory_on_residual=True" not in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert fetch_source.count("common_crawl_url_terms") == 1
    assert 'frontier_name="section"' in unbounded
    assert unbounded.count('frontier_name="section"') == 1
    assert "not acquisition units" in unbounded
    assert "must not split a known same-domain union" in chunks_source

    retry_source = inspect.getsource(
        MinnesotaScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        MinnesotaScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"repeat_grouped_archive_inventory_on_residual": False' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"wayback_prefix_inventory": True' in closure_source
    assert '"source_ordered_cross_parent_union": True' in closure_source
    assert '"historical_archive_edition_admission": False' in closure_source
    assert '"statutes_edition_guard": True' in closure_source


def test_minnesota_edition_guard_rejects_historical_archive_editions() -> None:
    current = _section_html(FIRST_SECTION).decode()
    assert minnesota_statutes_edition_from_html(current) == OFFICIAL_EDITION
    assert parse_minnesota_section_html(
        current,
        source_url=FIRST_RESIDUAL_URL,
        expected_edition=OFFICIAL_EDITION,
        require_source_identity=True,
    ) is not None

    for historical in HISTORICAL_EDITIONS:
        payload = _section_html(FIRST_SECTION, edition=historical).decode()
        assert minnesota_statutes_edition_from_html(payload) == historical
        assert parse_minnesota_section_html(
            payload,
            source_url=FIRST_RESIDUAL_URL,
            expected_edition=OFFICIAL_EDITION,
            require_source_identity=True,
        ) is None
        assert MinnesotaScraper._minnesota_payload_matches_edition(
            payload,
            expected_edition=OFFICIAL_EDITION,
        ) is False

    fetch_source = inspect.getsource(
        MinnesotaScraper._fetch_minnesota_frontier_batch
    )
    assert "missing or historical Minnesota Statutes edition" in fetch_source
    closure_source = inspect.getsource(
        MinnesotaScraper.produce_state_law_frontier_closure
    )
    assert "cannot stamp an unpinned statutes edition as current" in closure_source
    replay_source = inspect.getsource(
        MinnesotaScraper._replay_minnesota_source_frontier
    )
    assert "lacks the pinned current edition" in replay_source


def test_minnesota_seed_and_host_replay_forbid_hub_docker_and_historical_editions(
    tmp_path: Path,
) -> None:
    seed_source = SEED_SOURCE_PATH.read_text(encoding="utf-8")
    if not seed_source.strip():
        raise AssertionError("direct-only seed module is empty")
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "MN",
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
    assert "merge" in report and "across states" in report
    assert "missouri" in report or "washington" in report
    assert "2018" in report and "wayback" in report


def test_minnesota_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    minnesota_source = inspect.getsource(
        MinnesotaScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in minnesota_source or (
        "rights" in closure_source.casefold()
    )
    assert "retained_replay_network_requests" in minnesota_source
    assert minnesota_source.index('"retained_replay_network_requests": 0') > 0
    assert '"statutes_edition_guard": True' in minnesota_source
    assert '"historical_archive_edition_admission": False' in minnesota_source


def test_minnesota_compact_catalog_recipe_emits_source_ordered_difference_not_guessed_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, toc_part_urls, chapter_urls, section_urls, retained = (
        _compact_catalog_pages()
    )
    residual = _source_ordered_detail_residual(section_urls, retained)
    batch_calls: list[tuple[str, list[str]]] = []

    async def _single(self, url: str, **_kwargs: Any) -> bytes:
        assert url == OFFICIAL_ENTRY
        return pages[url]

    async def _retrying(self, urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return _frontier_result(requested, pages)

    original_batch = MinnesotaScraper._fetch_minnesota_frontier_batch

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        expected_edition: str = "",
    ):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return await original_batch(
            self,
            urls,
            frontier_name=frontier_name,
            expected_edition=expected_edition,
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MinnesotaScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(
        MinnesotaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _retrying,
    )
    monkeypatch.setattr(MinnesotaScraper, "_fetch_minnesota_frontier_batch", _batch)
    monkeypatch.setattr(
        MinnesotaScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = MinnesotaScraper("MN", "Minnesota")
    rows = asyncio.run(
        scraper._scrape_chapter_sections(
            "Minnesota Statutes",
            max_statutes=None,
        )
    )

    assert batch_calls == [
        (TOC_PART_WAVE_NAME, toc_part_urls),
        (CATALOG_WAVE_NAME, chapter_urls),
        (RESIDUAL_WAVE_NAME, section_urls),
    ]
    assert GUESSED_NEXT_URL not in batch_calls[-1][1]
    assert INVENTED_SECTION_URL not in batch_calls[-1][1]
    assert CROSS_STATE_MO_URL not in batch_calls[-1][1]
    assert CROSS_STATE_WA_URL not in batch_calls[-1][1]
    assert SUPERSEDED_DIAGNOSTIC_FIRST_URL not in batch_calls[-1][1]
    assert residual == [FIRST_RESIDUAL_URL, LAST_RESIDUAL_URL]
    assert residual[0] == _section_url(FIRST_SECTION)
    assert residual[-1] == _section_url(LAST_SECTION)
    assert len(section_urls) == len(retained) + len(residual)
    digest = _canonical_residual_sha256(residual)
    assert digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    assert [row.source_url for row in rows] == section_urls
    assert scraper._last_minnesota_statutes_edition == OFFICIAL_EDITION
    frontier = scraper._last_minnesota_full_frontier["frontier"]
    assert frontier["edition"] == OFFICIAL_EDITION
    assert frontier["source_section_count"] == len(section_urls)
    assert frontier["chapter_document_count"] == 3
    assert frontier["toc_part_document_count"] == 2
    assert frontier["closed"] is True


def test_minnesota_historical_archive_edition_fails_closed_instead_of_stamping_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, _toc_part_urls, _chapter_urls, section_urls, _retained = (
        _compact_catalog_pages()
    )
    pages[FIRST_RESIDUAL_URL] = _section_html(
        FIRST_SECTION,
        edition="2024 Minnesota Statutes",
    )

    async def _single(self, url: str, **_kwargs: Any) -> bytes:
        return pages[url]

    async def _retrying(self, urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        result = _frontier_result(requested, pages)
        validator = kwargs.get("content_validator")
        if callable(validator):
            assert validator(pages[FIRST_RESIDUAL_URL]) is False
            assert validator(_section_html(FIRST_SECTION)) is True
        return result

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MinnesotaScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(
        MinnesotaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _retrying,
    )
    monkeypatch.setattr(
        MinnesotaScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = MinnesotaScraper("MN", "Minnesota")
    with pytest.raises(
        RuntimeError,
        match="historical Minnesota Statutes edition",
    ):
        asyncio.run(
            scraper._scrape_chapter_sections(
                "Minnesota Statutes",
                max_statutes=None,
            )
        )
    assert GUESSED_NEXT_URL not in section_urls
    assert INVENTED_SECTION_URL not in section_urls


def test_minnesota_complete_union_is_one_plural_wave_with_residual_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, _toc_part_urls, _chapter_urls, section_urls, retained = (
        _compact_catalog_pages()
    )
    residual = _source_ordered_detail_residual(section_urls, retained)
    batch_calls: list[tuple[str, list[str]]] = []

    async def _single(self, url: str, **_kwargs: Any) -> bytes:
        return pages[url]

    async def _retrying(self, urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return _frontier_result(requested, pages)

    original_batch = MinnesotaScraper._fetch_minnesota_frontier_batch

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        expected_edition: str = "",
    ):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        if frontier_name == RESIDUAL_WAVE_NAME:
            assert requested == section_urls
            assert GUESSED_NEXT_URL not in requested
            assert expected_edition == OFFICIAL_EDITION
        return await original_batch(
            self,
            urls,
            frontier_name=frontier_name,
            expected_edition=expected_edition,
        )

    async def _single_leaf_must_not_run(*_args: Any, **_kwargs: Any):
        raise AssertionError(
            "unbounded Minnesota must parse retained plural payloads"
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MinnesotaScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(
        MinnesotaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _retrying,
    )
    monkeypatch.setattr(MinnesotaScraper, "_fetch_minnesota_frontier_batch", _batch)
    monkeypatch.setattr(
        MinnesotaScraper,
        "_build_statute_from_section_page",
        _single_leaf_must_not_run,
    )
    monkeypatch.setattr(
        MinnesotaScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = MinnesotaScraper("MN", "Minnesota")
    rows = asyncio.run(
        scraper._scrape_chapter_sections(
            "Minnesota Statutes",
            max_statutes=None,
        )
    )

    leaf_waves = [name for name, _urls in batch_calls if name == RESIDUAL_WAVE_NAME]
    assert leaf_waves == [RESIDUAL_WAVE_NAME]
    assert residual == section_urls[1:]
    assert [row.source_url for row in rows] == section_urls
    observation = scraper._last_minnesota_full_frontier
    assert observation["frontier"]["source_section_count"] == 3
    assert observation["edition"] == OFFICIAL_EDITION
    assert observation["boundary_first"] == section_urls[0]
    assert observation["boundary_last"] == section_urls[-1]

"""LCR-093: Washington source-ordered leaf residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, guessed later URLs, and merging
residuals across states.
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

from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_isolated_worker import (
    IsolatedRetainedReplayWorkerError,
    build_host_retained_replay_command,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.strict_frontier_closure import (
    retain_exact_state_frontier_closure,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington import (
    WashingtonScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington_section import (
    section_cite_belongs_to_chapter,
    section_url,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "washington_residual_closure_v1.md"
)

SOURCE_HIERARCHY_INPUTS = 54923
TITLE_CATALOG_COUNT = 101
CHAPTER_CATALOG_COUNT = 2785
SOURCE_SECTION_LEAVES = 52036
SOURCE_OUTCOME_UNITS = 52046
CHAPTER_MATERIAL_RECORDS = 2
TYPED_CHAPTER_TERMINALS = 8
V15_UNIQUE_INPUTS = 4423
V15_SECTION_PAGES = 1536
RETAINED_OPERATIVE_SECTIONS = 1536
RETAINED_TERMINAL_SECTIONS = 0
RESIDUAL_COUNT = 50500
RESIDUAL_SHA256 = (
    "e41a7baf281a3d6aea92693f7263020f441f86e5f0da7efb596726b2f14a0489"
)
RESIDUAL_SHA256_PREFIX = "e41a7baf281a"
RESIDUAL_WAVE_NAME = "section-frontier"
FIRST_SECTION = "7.05.230"
LAST_SECTION = "91.08.900"
FIRST_RESIDUAL_URL = (
    "https://app.leg.wa.gov/RCW/default.aspx?cite=7.05.230"
)
LAST_RESIDUAL_URL = (
    "https://app.leg.wa.gov/RCW/default.aspx?cite=91.08.900"
)
OFFICIAL_ENTRY = "https://app.leg.wa.gov/RCW/"
OFFICIAL_ROOT = "https://app.leg.wa.gov/RCW/default.aspx"
OFFICIAL_SECTION_LOCATOR = "https://app.leg.wa.gov/RCW/default.aspx?cite="
GUESSED_NEXT_URL = "https://app.leg.wa.gov/RCW/default.aspx?cite=7.05.231"
INVENTED_SECTION_URL = (
    "https://app.leg.wa.gov/RCW/default.aspx?cite=99.99.999"
)
CROSS_STATE_MO_URL = (
    "https://revisor.mo.gov/main/OneSection.aspx?section=70.655"
)
CROSS_STATE_MN_URL = (
    "https://www.revisor.mn.gov/statutes/cite/1.01"
)
FENCED_STAGING_ROOTS = tuple(f"staging-wa-v{index}" for index in range(1, 11))
SOURCE_BUNDLE_PREFIX = "ae7af2834278"
DIAGNOSTIC_PRODUCER_PREFIX = "WashingtonScraper@sha256:ae7af2834278"


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _source_ordered_section_residual(
    section_urls: list[str],
    retained_section_urls: set[str],
) -> list[str]:
    residual: list[str] = []
    seen: set[str] = set()
    for url in section_urls:
        if url in retained_section_urls:
            continue
        if url in seen:
            raise AssertionError(
                "Washington section residual frontier repeated a URL"
            )
        seen.add(url)
        residual.append(url)
    return residual


def _root_html(titles: list[str]) -> bytes:
    anchors = "".join(
        f"<a href='default.aspx?Cite={title}'>Title {title}</a>"
        for title in titles
    )
    return f"<html><body>{anchors}</body></html>".encode()


def _title_html(title: str, chapters: list[str]) -> bytes:
    anchors = "".join(
        f"<a href='default.aspx?cite={chapter}'>{chapter}</a>"
        for chapter in chapters
    )
    return (
        f"<html><head><title>Title {title} RCW:</title></head><body>"
        "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
        f"<h1>Title {title} RCW</h1></div>"
        f"<div id='contentWrapper' class='title-page'>{anchors}</div>"
        "</body></html>"
    ).encode()


def _chapter_html(chapter: str, sections: list[str]) -> bytes:
    rows = "".join(
        "<tr><td><a href='print'>HTML</a></td>"
        f"<td><a href='default.aspx?cite={section}'>{section}</a></td>"
        f"<td>Caption for {section}</td></tr>"
        for section in sections
    )
    return (
        f"<html><head><title>Chapter {chapter} RCW:</title></head><body>"
        "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
        f"<h1>Chapter {chapter} RCW</h1></div>"
        f"<div id='contentWrapper' class='chapter-page'><table>{rows}</table></div>"
        "</body></html>"
    ).encode()


def _section_html(section: str) -> bytes:
    return (
        f"<html><head><title>RCW {section}:</title></head><body>"
        "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
        f"<h1>RCW {section}</h1><h2>Current official section.</h2></div>"
        "<div id='contentWrapper' class='section-page'>"
        "<div></div><div></div><div>"
        + ("Current Washington statutory text. " * 8)
        + "</div></div></body></html>"
    ).encode()


def _frontier_result(
    urls: list[str],
    pages: dict[str, bytes],
) -> StateLawPageMultiFetchResult:
    payloads = [pages[url] for url in urls]
    transport_receipts: list[dict[str, str]] = []
    envelopes: list[dict[str, Any]] = []
    retrieved_at = "2026-08-25T11:06:45.054000Z"
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


def _compact_catalog_pages() -> tuple[dict[str, bytes], list[str], list[str], set[str]]:
    root_url = OFFICIAL_ROOT
    title_urls = [
        f"{root_url}?cite=1",
        f"{root_url}?cite=7",
        f"{root_url}?cite=91",
    ]
    chapter_urls = [
        f"{root_url}?cite=1.01",
        f"{root_url}?cite=7.05",
        f"{root_url}?cite=91.08",
    ]
    retained_sections = ["1.01.010", "7.05.220"]
    residual_sections = [FIRST_SECTION, LAST_SECTION]
    section_urls = [
        f"{root_url}?cite={cite}"
        for cite in [*retained_sections, *residual_sections]
    ]
    pages = {
        root_url: _root_html(["1", "7", "91"]),
        title_urls[0]: _title_html("1", ["1.01"]),
        title_urls[1]: _title_html("7", ["7.05"]),
        title_urls[2]: _title_html("91", ["91.08"]),
        chapter_urls[0]: _chapter_html("1.01", ["1.01.010"]),
        chapter_urls[1]: _chapter_html("7.05", ["7.05.220", FIRST_SECTION]),
        chapter_urls[2]: _chapter_html("91.08", [LAST_SECTION]),
        **{url: _section_html(url.rsplit("=", 1)[-1]) for url in section_urls},
    }
    retained = {
        f"{root_url}?cite={cite}" for cite in retained_sections
    }
    return pages, title_urls, chapter_urls, retained


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Washington residual closure report is empty")
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


def test_washington_residual_closure_report_records_exact_source_ordered_leaf_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "WA"
    assert table["official domain"] == "app.leg.wa.gov"
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_root"] == OFFICIAL_ROOT
    assert table["official_section_locator"] == OFFICIAL_SECTION_LOCATOR
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["seed"] == "strict v15 only"
    assert table["catalog_first_snapshot"] == "forbidden"
    assert table["staging_wa_v1_through_v10"] == "forbidden"
    assert table["shared_cache_residual_reuse"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["guess_later_urls"] == "forbidden"
    assert table["merge_residuals_across_states"] == "forbidden"
    assert table["source_hierarchy_inputs"] == str(SOURCE_HIERARCHY_INPUTS)
    assert table["title_catalog_count"] == str(TITLE_CATALOG_COUNT)
    assert table["chapter_catalog_count"] == str(CHAPTER_CATALOG_COUNT)
    assert table["source_section_leaves"] == str(SOURCE_SECTION_LEAVES)
    assert table["source_outcome_units"] == str(SOURCE_OUTCOME_UNITS)
    assert table["chapter_material_records"] == str(CHAPTER_MATERIAL_RECORDS)
    assert table["typed_chapter_terminals"] == str(TYPED_CHAPTER_TERMINALS)
    assert table["v15_unique_inputs"] == str(V15_UNIQUE_INPUTS)
    assert table["v15_root_pages"] == "1"
    assert table["v15_title_catalogs"] == str(TITLE_CATALOG_COUNT)
    assert table["v15_chapter_catalogs"] == str(CHAPTER_CATALOG_COUNT)
    assert table["v15_section_pages"] == str(V15_SECTION_PAGES)
    assert table["retained_operative_sections"] == str(RETAINED_OPERATIVE_SECTIONS)
    assert table["retained_terminal_sections"] == str(RETAINED_TERMINAL_SECTIONS)
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == "source-ordered RCW section URLs"
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
    assert table["source_bundle_prefix"] == SOURCE_BUNDLE_PREFIX
    assert table["diagnostic_producer"].startswith(DIAGNOSTIC_PRODUCER_PREFIX)
    assert table["diagnostic_hashes_authorizing"] == "false"

    assert (
        int(table["v15_root_pages"])
        + int(table["v15_title_catalogs"])
        + int(table["v15_chapter_catalogs"])
        + int(table["v15_section_pages"])
        == V15_UNIQUE_INPUTS
    )
    assert (
        1 + TITLE_CATALOG_COUNT + CHAPTER_CATALOG_COUNT + SOURCE_SECTION_LEAVES
        == SOURCE_HIERARCHY_INPUTS
    )
    assert RETAINED_OPERATIVE_SECTIONS + RETAINED_TERMINAL_SECTIONS + RESIDUAL_COUNT == (
        SOURCE_SECTION_LEAVES
    )
    assert SOURCE_SECTION_LEAVES + CHAPTER_MATERIAL_RECORDS + TYPED_CHAPTER_TERMINALS == (
        SOURCE_OUTCOME_UNITS
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
    assert "strict v15" in lowered
    assert "catalog-first/wa" in lowered
    assert "staging-wa-v1" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "50,500" in report
    assert "52,036" in report
    assert "4,423" in report
    assert FIRST_RESIDUAL_URL in report
    assert LAST_RESIDUAL_URL in report
    assert RESIDUAL_SHA256 in report
    assert RESIDUAL_SHA256_PREFIX in report
    assert GUESSED_NEXT_URL not in report
    assert INVENTED_SECTION_URL not in report
    assert CROSS_STATE_MO_URL not in report
    assert CROSS_STATE_MN_URL not in report
    assert report.count("https://app.leg.wa.gov/RCW/default.aspx?cite=") < 12


def test_washington_section_locator_is_exact_and_not_guessed() -> None:
    assert section_url(FIRST_SECTION) == FIRST_RESIDUAL_URL
    assert section_url(LAST_SECTION) == LAST_RESIDUAL_URL
    assert section_url("7.05.231") == GUESSED_NEXT_URL
    assert section_url("7.05.231") != FIRST_RESIDUAL_URL
    assert section_url("99.99.999") == INVENTED_SECTION_URL
    assert section_cite_belongs_to_chapter(FIRST_SECTION, "7.05")
    assert section_cite_belongs_to_chapter(LAST_SECTION, "91.08")
    assert not section_cite_belongs_to_chapter("99.99.999", "7.05")
    assert not section_cite_belongs_to_chapter("7.05.230", "7.04")

    unbounded = inspect.getsource(
        WashingtonScraper._scrape_unbounded_washington_frontier
    )
    assert "section_urls = [row[3] for row in section_frontier]" in unbounded
    assert 'frontier_name="section-frontier"' in unbounded
    assert "Submit the complete cross-chapter leaf union once" in unbounded
    assert FIRST_RESIDUAL_URL not in unbounded
    assert LAST_RESIDUAL_URL not in unbounded
    assert GUESSED_NEXT_URL not in unbounded
    assert INVENTED_SECTION_URL not in unbounded
    assert re.search(
        r"default\.aspx\?cite=\{cite\}",
        inspect.getsource(section_url),
    )


def test_washington_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(WashingtonScraper)
    section_adapter = inspect.getsource(section_url)
    unbounded = inspect.getsource(
        WashingtonScraper._scrape_unbounded_washington_frontier
    )
    assert str(RESIDUAL_COUNT) not in adapter
    assert str(SOURCE_SECTION_LEAVES) not in adapter
    assert str(V15_UNIQUE_INPUTS) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert RESIDUAL_SHA256_PREFIX not in section_adapter
    assert RESIDUAL_SHA256 not in unbounded
    assert FIRST_RESIDUAL_URL not in adapter
    assert LAST_RESIDUAL_URL not in adapter
    assert GUESSED_NEXT_URL not in adapter
    assert INVENTED_SECTION_URL not in adapter
    assert CROSS_STATE_MO_URL not in adapter
    assert CROSS_STATE_MN_URL not in adapter
    for fenced in FENCED_STAGING_ROOTS:
        assert fenced not in adapter
    assert "catalog-first/WA" not in adapter
    cite_literals = set(
        re.findall(r"default\.aspx\?cite=([0-9A-Za-z.\-]+)", adapter)
    )
    assert FIRST_SECTION not in cite_literals
    assert LAST_SECTION not in cite_literals
    assert "7.05.231" not in cite_literals
    assert "99.99.999" not in cite_literals
    assert "section_urls = [row[3] for row in section_frontier]" in unbounded
    assert "_section_links_from_payload" in unbounded


def test_washington_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    compact = [FIRST_RESIDUAL_URL, LAST_RESIDUAL_URL]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://app.leg.wa.gov/RCW/default.aspx?cite=7.05.230",'
        b'"https://app.leg.wa.gov/RCW/default.aspx?cite=91.08.900"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert not compact_digest.startswith(RESIDUAL_SHA256_PREFIX)
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    unbounded = inspect.getsource(
        WashingtonScraper._scrape_unbounded_washington_frontier
    )
    assert "Washington chapter frontier repeated section identity" in unbounded
    assert '"source_ordered_cross_parent_union": True' in inspect.getsource(
        WashingtonScraper.produce_state_law_frontier_closure
    )


def test_washington_one_global_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(
        WashingtonScraper._fetch_washington_frontier_batch
    )
    unbounded = inspect.getsource(
        WashingtonScraper._scrape_unbounded_washington_frontier
    )
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,)" in fetch_source
    assert 'common_crawl_url_terms=("/RCW/",)' in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert "repeat_grouped_archive_inventory_on_residual=True" not in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert fetch_source.count("common_crawl_url_terms") == 1
    assert 'frontier_name="section-frontier"' in unbounded
    assert unbounded.count('frontier_name="section-frontier"') == 1
    assert "one request cycle per slice" in unbounded

    retry_source = inspect.getsource(
        WashingtonScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        WashingtonScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"repeat_grouped_archive_inventory_on_residual": False' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"wayback_prefix_inventory": True' in closure_source
    assert '"source_ordered_cross_parent_union": True' in closure_source


def test_washington_seed_and_host_replay_forbid_hub_docker_and_cross_state_merge(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "WA",
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
    assert "minnesota" in report or "missouri" in report


def test_washington_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    washington_source = inspect.getsource(
        WashingtonScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in washington_source or (
        "rights" in closure_source.casefold()
    )
    assert "retained_replay_network_requests" in washington_source
    assert washington_source.index('"retained_replay_network_requests": 0') > 0
    assert "Washington retained hierarchy changed on replay" in washington_source
    assert '"retained_replay_network_requests": 0' in washington_source


def test_washington_compact_catalog_recipe_emits_source_ordered_difference_not_guessed_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, title_urls, chapter_urls, retained = _compact_catalog_pages()
    section_urls = [
        f"{OFFICIAL_ROOT}?cite=1.01.010",
        f"{OFFICIAL_ROOT}?cite=7.05.220",
        FIRST_RESIDUAL_URL,
        LAST_RESIDUAL_URL,
    ]
    residual = _source_ordered_section_residual(section_urls, retained)
    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return _frontier_result(requested, pages)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        WashingtonScraper,
        "OFFICIAL_TITLES",
        (("1", "One"), ("7", "Seven"), ("91", "Waterways")),
    )
    monkeypatch.setattr(WashingtonScraper, "_fetch_washington_frontier_batch", _batch)
    monkeypatch.setattr(
        WashingtonScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = WashingtonScraper("WA", "Washington")
    rows = asyncio.run(
        scraper._scrape_unbounded_washington_frontier("Revised Code of Washington")
    )

    assert batch_calls == [
        ("root-index", [OFFICIAL_ROOT]),
        ("title-index", title_urls),
        ("chapter-index", chapter_urls),
        (RESIDUAL_WAVE_NAME, section_urls),
    ]
    assert GUESSED_NEXT_URL not in batch_calls[-1][1]
    assert INVENTED_SECTION_URL not in batch_calls[-1][1]
    assert CROSS_STATE_MO_URL not in batch_calls[-1][1]
    assert CROSS_STATE_MN_URL not in batch_calls[-1][1]
    assert residual == [FIRST_RESIDUAL_URL, LAST_RESIDUAL_URL]
    assert residual[0] == section_url(FIRST_SECTION)
    assert residual[-1] == section_url(LAST_SECTION)
    assert len(section_urls) == len(retained) + len(residual)
    digest = _canonical_residual_sha256(residual)
    assert digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    assert [row.source_url for row in rows] == section_urls
    frontier = scraper._last_washington_full_frontier["frontier"]
    assert frontier["source_section_count"] == len(section_urls)
    assert frontier["title_document_count"] == 3
    assert frontier["chapter_document_count"] == 3
    assert frontier["closed"] is True


def test_washington_invented_later_section_fails_closed_on_catalog_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, _title_urls, _chapter_urls, _retained = _compact_catalog_pages()
    chapter_705 = f"{OFFICIAL_ROOT}?cite=7.05"
    pages[chapter_705] = _chapter_html(
        "7.05",
        ["7.05.220", FIRST_SECTION, "99.99.999"],
    )
    pages[INVENTED_SECTION_URL] = _section_html("99.99.999")

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        return _frontier_result(requested, pages)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        WashingtonScraper,
        "OFFICIAL_TITLES",
        (("1", "One"), ("7", "Seven"), ("91", "Waterways")),
    )
    monkeypatch.setattr(WashingtonScraper, "_fetch_washington_frontier_batch", _batch)
    monkeypatch.setattr(
        WashingtonScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = WashingtonScraper("WA", "Washington")
    with pytest.raises(
        RuntimeError,
        match="noncanonical section locator",
    ):
        asyncio.run(
            scraper._scrape_unbounded_washington_frontier(
                "Revised Code of Washington"
            )
        )


def test_washington_complete_union_is_one_plural_wave_with_residual_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, _title_urls, _chapter_urls, retained = _compact_catalog_pages()
    section_urls = [
        f"{OFFICIAL_ROOT}?cite=1.01.010",
        f"{OFFICIAL_ROOT}?cite=7.05.220",
        FIRST_RESIDUAL_URL,
        LAST_RESIDUAL_URL,
    ]
    residual = _source_ordered_section_residual(section_urls, retained)
    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        if frontier_name == RESIDUAL_WAVE_NAME:
            assert requested == section_urls
            assert GUESSED_NEXT_URL not in requested
        return _frontier_result(requested, pages)

    async def _single_must_not_run(*_args, **_kwargs):
        raise AssertionError("unbounded Washington must use the plural frontier path")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        WashingtonScraper,
        "OFFICIAL_TITLES",
        (("1", "One"), ("7", "Seven"), ("91", "Waterways")),
    )
    monkeypatch.setattr(WashingtonScraper, "_fetch_washington_frontier_batch", _batch)
    monkeypatch.setattr(
        WashingtonScraper,
        "_fetch_page_content_with_archival_fallback",
        _single_must_not_run,
    )
    monkeypatch.setattr(
        WashingtonScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )
    scraper = WashingtonScraper("WA", "Washington")
    rows = asyncio.run(
        scraper._scrape_official_index(
            "Revised Code of Washington",
            max_statutes=None,
        )
    )

    leaf_waves = [name for name, _urls in batch_calls if name == RESIDUAL_WAVE_NAME]
    assert leaf_waves == [RESIDUAL_WAVE_NAME]
    assert residual == section_urls[2:]
    assert [row.source_url for row in rows] == section_urls
    observation = scraper._last_washington_full_frontier
    assert observation["frontier"]["source_section_count"] == 4
    assert observation["boundary_first"] == section_urls[0]
    assert observation["boundary_last"] == section_urls[-1]

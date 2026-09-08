"""LCR-105: Wisconsin viewer-frontier residual closure without historical cache.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, the receiptless historical cache,
the repaired 480-row catalog, and guessed later continuation URLs.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace

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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin import (
    WisconsinScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin_chapter import (
    parse_wisconsin_chapter_frontier_window,
    section_url,
    toc_chapter_links,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "wisconsin_residual_closure_v1.md"
)

OFFICIAL_ENTRY = "https://docs.legis.wisconsin.gov/statutes/statutes"
OFFICIAL_DOMAIN = "docs.legis.wisconsin.gov"
OFFICIAL_SOURCE_CHAPTERS = 470
REPAIRED_CATALOG_CHAPTERS = 480
INITIAL_CHAPTER_VIEWERS = 470
INITIAL_SECTION_LOCATORS = 13396
FIRST_CHAPTER_CONTINUATIONS = 131
FIRST_SECTION_CONTINUATIONS = 834
KNOWN_LOWER_BOUND_URLS = 14832
RETAINED_AUTHORIZING_INPUTS = 0
HISTORICAL_CACHE_OBJECTS = 14337
HISTORICAL_CACHE_BYTES = 1402013000
CACHED_INITIAL_OPERATIVE = 12561
CACHED_CONTINUATION_REQUIRED = 834
DIAGNOSTIC_ROOT_BYTES = 317921
DIAGNOSTIC_ROOT_SHA256_PREFIX = "66bcea27111f"
SOURCE_BUNDLE_PREFIX = "02f8bef4e00a"
RESIDUAL_SHA256_PREFIX = "source_dependent_after_continuation_waves"
ROOT_WAVE_NAME = "statutes-index"
CHAPTER_WAVE_PREFIX = "chapter-toc-wave-"
SECTION_WAVE_PREFIX = "section-body-wave-"
RESIDUAL_WAVE_NAME = "source-derived-viewer-continuation-waves"
SOURCE_LISTED_ABSENT_SECTION = "854.30"
CITATION_LINK_NON_TOC_SECTION = "344.579"
INVENTED_CONTINUATION_URL = (
    "https://docs.legis.wisconsin.gov/statutes/statutes/999/_60?down=1"
)
INVENTED_SECTION_URL = "https://docs.legis.wisconsin.gov/document/statutes/999.99"
CHAPTER_PDF_URL = "https://docs.legis.wisconsin.gov/document/statutes/854.pdf"


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _html(body: str, *, title: str = "Wisconsin Legislature: Statutes") -> bytes:
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<div id='document'>{body}</div><!--{'x' * 1_200}--></body></html>"
    ).encode()


def _toc(section: str, heading: str = "Provision") -> str:
    return (
        f"<div class='qstoc_entry'><a href='/document/statutes/{section}'>"
        f"{section}</a> {heading}</div>"
    )


def _unlinked_toc(section: str, heading: str = "Provision") -> str:
    return f"<div class='qstoc_entry'>{section} {heading}</div>"


def _block(
    section: str,
    text: str,
    *,
    path: str,
    title: str = "Operative provision.",
) -> str:
    return (
        f"<div class='qsatxt_1sect level3' data-section='{section}' "
        f"data-path='{path}'><a class='reference' href='/document/statutes/{section}'>"
        f"{section}</a><span class='qsnum_sect'>{section}</span>"
        f"<span class='qstitle_sect'>{title}</span>{text}</div>"
    )


def _down(href: str) -> str:
    return f"<div class='navigation'><a href='{href}'>Down</a></div>"


def _frontier_result(
    urls: list[str],
    payloads: list[bytes],
) -> StateLawPageMultiFetchResult:
    receipts = []
    envelopes = []
    retrieved_at = "2026-08-26T00:00:00Z"
    for url, payload in zip(urls, payloads, strict=True):
        content_sha256 = hashlib.sha256(payload).hexdigest()
        transport = {
            "content_sha256": content_sha256,
            "official_url": url,
            "source_transport": "direct",
        }
        receipts.append(dict(transport))
        envelopes.append(
            SimpleNamespace(
                body=payload,
                acquisition=SimpleNamespace(
                    receipt=SimpleNamespace(retrieved_at=retrieved_at)
                ),
            )
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
            "requested_pages": len(urls),
            "common_crawl_inventory_queries": 1,
            "common_crawl": {
                "range_fetch_calls": 1,
                "naive_range_fetches": len(urls),
                "range_fetches_avoided": max(0, len(urls) - 1),
            },
        },
    )


class _ReceiptlessHistoricalCache:
    """Shape of the WI historical fetch cache: digest/size/url only."""

    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = dict(pages)
        self.requests: list[str] = []

    def refresh_existing_entries(self) -> None:
        return None

    def replay_retained_parser_input(self, *, official_url: str, sanitized_request):
        self.requests.append(official_url)
        payload = self.pages.get(official_url)
        if payload is None:
            return None
        digest = hashlib.sha256(payload).hexdigest()
        return SimpleNamespace(
            envelope=None,
            transport_receipt={
                "cached_at": "2024-01-01T00:00:00Z",
                "provider": "requests_direct",
                "sha256": digest,
                "size": len(payload),
                "state_code": "WI",
                "url": official_url,
            },
        )


def _synthetic_pages(scraper: WisconsinScraper) -> dict[str, bytes]:
    base = scraper.get_base_url()
    chapter_1 = f"{base}/document/statutes/1"
    chapter_2 = f"{base}/document/statutes/2"
    chapter_2_next = f"{base}/statutes/statutes/2/_60?down=1"
    section_201_next = f"{base}/statutes/statutes/2/01/_60?down=1"
    return {
        scraper.OFFICIAL_ENTRY_URL: _html(
            "<p><a href='/document/statutes/1'>Chapter 1 - Government</a></p>"
            "<p><a href='/document/statutes/2'>Chapter 2 - Administration</a></p>",
            title="Wisconsin Legislature: Statutes",
        ),
        chapter_1: _html(
            _toc("1.01")
            + _unlinked_toc("1.03", "Source-listed row whose self-link is omitted.")
            + "<div><a href='/document/statutes/344.579'>body citation only</a></div>"
            + _block(
                "1.01",
                "This official Wisconsin provision contains enough complete statutory text.",
                path="/statutes/statutes/1/01",
            )
            + _block(
                "1.03",
                "This unlinked TOC identity is still an official source row.",
                path="/statutes/statutes/1/03",
            ),
            title="Wisconsin Legislature: Chapter 1",
        ),
        chapter_2: _html(
            _toc("2.01")
            + _down("/statutes/statutes/2/_60?down=1"),
            title="Wisconsin Legislature: Chapter 2",
        ),
        chapter_2_next: _html(
            _toc("2.02")
            + _block(
                "2.01",
                "The chapter body begins only after the final source-derived TOC entry.",
                path="/statutes/statutes/2/01",
            ),
            title="Wisconsin Legislature: Chapter 2",
        ),
        f"{base}/document/statutes/1.01": _html(
            _block(
                "1.01",
                "This complete official section governs public administration in Wisconsin.",
                path="/statutes/statutes/1/01",
            )
            + _block(
                "1.03",
                "The next section proves that the requested section body has ended.",
                path="/statutes/statutes/1/03",
            ),
            title="Wisconsin Legislature: 1.01",
        ),
        f"{base}/document/statutes/1.03": _html(
            _block(
                "1.03",
                "This source-listed Wisconsin section is complete without a TOC self-link.",
                path="/statutes/statutes/1/03",
            ),
            title="Wisconsin Legislature: 1.03",
        ),
        f"{base}/document/statutes/2.01": _html(
            _block(
                "2.01",
                "The first retained window begins a long operative statutory provision",
                path="/statutes/statutes/2/01/1",
            )
            + _down("/statutes/statutes/2/01/_60?down=1"),
            title="Wisconsin Legislature: 2.01",
        ),
        section_201_next: _html(
            _block(
                "2.01",
                "and this second retained window completes that provision without truncation.",
                path="/statutes/statutes/2/01/2",
                title="",
            )
            + _block(
                "2.02",
                "The next section is a source-bound completion sentinel.",
                path="/statutes/statutes/2/02",
            ),
            title="Wisconsin Legislature: 2.01",
        ),
        f"{base}/document/statutes/2.02": _html(
            _block(
                "2.02",
                "This separate official Wisconsin section is complete at the document boundary.",
                path="/statutes/statutes/2/02",
            ),
            title="Wisconsin Legislature: 2.02",
        ),
        f"{base}/document/statutes/{CITATION_LINK_NON_TOC_SECTION}": _html(
            _block(
                CITATION_LINK_NON_TOC_SECTION,
                "Legacy citation-link traversal must not invent this locator.",
                path="/statutes/statutes/344/579",
            ),
            title=f"Wisconsin Legislature: {CITATION_LINK_NON_TOC_SECTION}",
        ),
        CHAPTER_PDF_URL: b"%PDF-1.4 historical chapter pdf" + (b"x" * 1_200),
    }


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Wisconsin residual closure report is empty")
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


def test_wisconsin_residual_closure_report_records_exact_viewer_frontier_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "WI"
    assert table["official domain"] == OFFICIAL_DOMAIN
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == "source-derived sliding viewer from one official root"
    assert table["seed"] == "zero authorizing ledger inputs; start at the official root"
    assert table["historical_cache_admission"] == "forbidden"
    assert table["receiptless_historical_cache"] == "forbidden"
    assert table["repaired_480_catalog"] == "forbidden"
    assert table["chapter_pdf_as_html_substitute"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["invent_later_continuation_urls"] == "forbidden"
    assert table["citation_link_344_579_without_toc"] == "forbidden"
    assert table["unlinked_source_row_854_30"] == (
        "leading TOC identity; not a cache miss to drop"
    )
    assert table["diagnostic_root_bytes"] == str(DIAGNOSTIC_ROOT_BYTES)
    assert table["diagnostic_root_sha256_prefix"] == DIAGNOSTIC_ROOT_SHA256_PREFIX
    assert table["official_source_chapters"] == str(OFFICIAL_SOURCE_CHAPTERS)
    assert table["repaired_catalog_chapters"] == str(REPAIRED_CATALOG_CHAPTERS)
    assert table["initial_chapter_viewers"] == str(INITIAL_CHAPTER_VIEWERS)
    assert table["initial_section_locators"] == str(INITIAL_SECTION_LOCATORS)
    assert table["first_chapter_continuations"] == str(FIRST_CHAPTER_CONTINUATIONS)
    assert table["first_section_continuations"] == str(FIRST_SECTION_CONTINUATIONS)
    assert table["known_lower_bound_urls"] == str(KNOWN_LOWER_BOUND_URLS)
    assert table["retained_authorizing_inputs"] == str(RETAINED_AUTHORIZING_INPUTS)
    assert table["historical_cache_objects"] == str(HISTORICAL_CACHE_OBJECTS)
    assert table["historical_cache_bytes"] == str(HISTORICAL_CACHE_BYTES)
    assert table["historical_cache_receipts"] == "0"
    assert table["historical_cache_parser_input_envelopes"] == "0"
    assert table["cached_initial_operative_bodies"] == str(CACHED_INITIAL_OPERATIVE)
    assert table["cached_continuation_required_bodies"] == str(
        CACHED_CONTINUATION_REQUIRED
    )
    assert table["source_listed_body_absent_from_cache"] == SOURCE_LISTED_ABSENT_SECTION
    assert table["cached_citation_link_not_in_initial_toc"] == (
        CITATION_LINK_NON_TOC_SECTION
    )
    assert table["residual_count"] == str(KNOWN_LOWER_BOUND_URLS)
    assert table["residual_kind"] == (
        "unique ordered viewer URLs from one root; later continuations source-dependent"
    )
    assert table["residual_first_url"] == OFFICIAL_ENTRY
    assert table["residual_floor_kind"] == (
        "known lower bound; later continuations remain source-dependent"
    )
    assert table["later_continuation_count"] == (
        "source_dependent_after_continuation_waves"
    )
    assert table["root_wave_name"] == ROOT_WAVE_NAME
    assert table["chapter_wave_name_prefix"] == CHAPTER_WAVE_PREFIX
    assert table["section_wave_name_prefix"] == SECTION_WAVE_PREFIX
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["root_acquisition_wave_count"] == "1"
    assert table["chapter_acquisition_wave_count"] == "source_dependent_at_least_2"
    assert table["leaf_acquisition_wave_count"] == "source_dependent_at_least_2"
    assert table["close_each_source_derived_continuation_wave"] == "true"
    assert table["per_page_archive_loop"] == "false"
    assert table["archive_recovery_enabled"] == "true"
    assert table["grouped_warc_recovery"] == "false"
    assert table["wayback_prefix_inventory"] == "false"
    assert table["current_authorizing_transport"] == "direct_or_grouped_archive_cdx"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["diagnostic_hashes_authorizing"] == "false"
    assert table["source_bundle_prefix"] == SOURCE_BUNDLE_PREFIX
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert (
        1
        + INITIAL_CHAPTER_VIEWERS
        + INITIAL_SECTION_LOCATORS
        + FIRST_CHAPTER_CONTINUATIONS
        + FIRST_SECTION_CONTINUATIONS
        == KNOWN_LOWER_BOUND_URLS
    )
    assert (
        CACHED_INITIAL_OPERATIVE + CACHED_CONTINUATION_REQUIRED + 1
        == INITIAL_SECTION_LOCATORS
    )
    assert RETAINED_AUTHORIZING_INPUTS + KNOWN_LOWER_BOUND_URLS == KNOWN_LOWER_BOUND_URLS
    assert HISTORICAL_CACHE_OBJECTS != KNOWN_LOWER_BOUND_URLS

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "receiptless historical" in lowered
    assert "14,832" in report
    assert "hub mutation" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "docker-copying" in lowered or "docker-copy" in lowered
    assert SOURCE_LISTED_ABSENT_SECTION in report
    assert CITATION_LINK_NON_TOC_SECTION in report
    assert OFFICIAL_ENTRY in report
    assert INVENTED_CONTINUATION_URL not in report
    assert INVENTED_SECTION_URL not in report
    assert CHAPTER_PDF_URL not in report
    assert report.count("https://docs.legis.wisconsin.gov/document/statutes/") < 8
    assert not re.search(r"residual_ordered_sha256_prefix.*[0-9a-f]{12}", report)


def test_wisconsin_viewer_frontier_is_source_derived_from_one_root() -> None:
    scraper = WisconsinScraper("WI", "Wisconsin")
    assert scraper.get_base_url() == f"https://{OFFICIAL_DOMAIN}"
    assert scraper.OFFICIAL_ENTRY_URL == OFFICIAL_ENTRY
    assert scraper.OFFICIAL_DOMAIN == OFFICIAL_DOMAIN
    assert section_url(SOURCE_LISTED_ABSENT_SECTION) == (
        f"https://{OFFICIAL_DOMAIN}/document/statutes/{SOURCE_LISTED_ABSENT_SECTION}"
    )
    assert len(scraper.OFFICIAL_CHAPTERS) == REPAIRED_CATALOG_CHAPTERS
    assert len(scraper.OFFICIAL_CHAPTERS) != OFFICIAL_SOURCE_CHAPTERS

    root_html = _html(
        "<p><a href='/document/statutes/1'>Chapter 1 - Government</a></p>"
        "<p><a href='/document/statutes/2'>Chapter 2 - Administration</a></p>",
    ).decode()
    catalog = toc_chapter_links(root_html, base_url=scraper.get_base_url())
    assert [row[0] for row in catalog] == ["1", "2"]
    assert [row[2] for row in catalog] == [
        f"{scraper.get_base_url()}/document/statutes/1",
        f"{scraper.get_base_url()}/document/statutes/2",
    ]

    unbounded = inspect.getsource(WisconsinScraper._scrape_wisconsin_strict_frontier)
    assert "toc_chapter_links" in unbounded
    assert 'frontier_name="statutes-index"' in unbounded
    assert 'frontier_name=f"chapter-toc-wave-{chapter_wave}"' in unbounded
    assert 'frontier_name=f"section-body-wave-{section_wave}"' in unbounded
    assert "OFFICIAL_CHAPTERS" not in unbounded
    assert "official_chapter_catalog" not in unbounded
    assert SOURCE_LISTED_ABSENT_SECTION not in unbounded
    assert CITATION_LINK_NON_TOC_SECTION not in unbounded
    assert INVENTED_CONTINUATION_URL not in unbounded
    assert CHAPTER_PDF_URL not in unbounded


def test_wisconsin_adapter_has_no_static_residual_url_list() -> None:
    scraper_source = inspect.getsource(WisconsinScraper)
    chapter_module = inspect.getmodule(parse_wisconsin_chapter_frontier_window)
    assert chapter_module is not None
    chapter_source = inspect.getsource(chapter_module)
    unbounded = inspect.getsource(WisconsinScraper._scrape_wisconsin_strict_frontier)
    for payload in (scraper_source, chapter_source, unbounded):
        assert str(KNOWN_LOWER_BOUND_URLS) not in payload
        assert str(HISTORICAL_CACHE_OBJECTS) not in payload
        assert str(HISTORICAL_CACHE_BYTES) not in payload
        assert RESIDUAL_SHA256_PREFIX not in payload
        assert INVENTED_CONTINUATION_URL not in payload
        assert INVENTED_SECTION_URL not in payload
        assert CHAPTER_PDF_URL not in payload
    assert CITATION_LINK_NON_TOC_SECTION not in unbounded
    assert "344.579" not in unbounded
    pdf_note = inspect.getsource(chapter_module.pdf_front_toc_sections)
    assert "PDFs are never auto-downloaded here" in pdf_note
    continuation_literals = re.findall(
        r"/statutes/statutes/\d+/_60\?down=1",
        unbounded,
    )
    assert continuation_literals == []


def test_wisconsin_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    compact = [
        OFFICIAL_ENTRY,
        "https://docs.legis.wisconsin.gov/document/statutes/1",
        section_url(SOURCE_LISTED_ABSENT_SECTION),
    ]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://docs.legis.wisconsin.gov/statutes/statutes",'
        b'"https://docs.legis.wisconsin.gov/document/statutes/1",'
        b'"https://docs.legis.wisconsin.gov/document/statutes/854.30"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert compact_digest != RESIDUAL_SHA256_PREFIX
    assert not compact_digest.startswith(DIAGNOSTIC_ROOT_SHA256_PREFIX)
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert ROOT_WAVE_NAME in report
    assert CHAPTER_WAVE_PREFIX in report
    assert SECTION_WAVE_PREFIX in report


def test_wisconsin_current_wave_uses_identity_archive_without_prefix_inventory() -> None:
    fetch_source = inspect.getsource(WisconsinScraper._fetch_wisconsin_frontier_batch)
    assert "wayback_prefix_inventory=False" in fetch_source
    assert "archive_recovery_enabled=True" in fetch_source
    assert 'common_crawl_domain_terms=(self.OFFICIAL_DOMAIN, "wisconsin.gov")' in (
        fetch_source
    )
    assert 'common_crawl_url_terms=("/statutes/statutes", "/document/statutes/")' in (
        fetch_source
    )
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert fetch_source.count("common_crawl_domain_terms") == 1

    retry_source = inspect.getsource(
        WisconsinScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        WisconsinScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"residual_only_retries": True' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"archive_recovery_enabled": True' in closure_source
    assert '"grouped_warc_recovery": False' in closure_source
    assert '"wayback_prefix_inventory": False' in closure_source
    assert '"kind": "shared_direct_plural_html_viewer"' in closure_source
    assert "network=False" in closure_source


def test_wisconsin_seed_and_host_replay_forbid_hub_docker_and_historical_cache(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "WI",
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
    assert "receiptless historical" in report
    assert "14,337" in _report_text()


def test_wisconsin_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    wisconsin_source = inspect.getsource(
        WisconsinScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in wisconsin_source or (
        "rights" in closure_source.casefold()
    )
    assert "retained_replay_network_requests" in wisconsin_source
    assert wisconsin_source.index('"retained_replay_network_requests": 0') > 0
    assert "network=False" in wisconsin_source
    replay_source = inspect.getsource(WisconsinScraper._replay_wisconsin_retained_input)
    assert "Wisconsin retained replay is missing exact input" in replay_source
    assert "falling through to network" in inspect.getdoc(
        WisconsinScraper._replay_wisconsin_retained_input
    ) or "without falling through to network" in replay_source


def test_wisconsin_unlinked_854_30_is_admitted_and_citation_344_579_is_not() -> None:
    html = _html(
        _toc("854.01")
        + _unlinked_toc(
            SOURCE_LISTED_ABSENT_SECTION,
            "A source-listed operative section whose self-link is omitted.",
        )
        + "<div><a href='/document/statutes/344.579'>body citation only</a></div>"
        + _block(
            "854.01",
            "A complete statutory body that is long enough for normalized output.",
            path="/statutes/statutes/854/01",
        ),
        title="Wisconsin Legislature: Chapter 854",
    ).decode()
    window = parse_wisconsin_chapter_frontier_window(
        html,
        chapter="854",
        page_url="https://docs.legis.wisconsin.gov/document/statutes/854",
    )
    assert [row[0] for row in window.section_rows] == [
        "854.01",
        SOURCE_LISTED_ABSENT_SECTION,
    ]
    assert [row[2] for row in window.section_rows] == [
        section_url("854.01"),
        section_url(SOURCE_LISTED_ABSENT_SECTION),
    ]
    assert CITATION_LINK_NON_TOC_SECTION not in {
        row[0] for row in window.section_rows
    }
    assert section_url(CITATION_LINK_NON_TOC_SECTION) not in {
        row[2] for row in window.section_rows
    }
    assert window.residuals == ()


def test_wisconsin_receiptless_historical_cache_cannot_authorize_aligned_evidence() -> None:
    scraper = WisconsinScraper("WI", "Wisconsin")
    payload = _html(
        _toc("1.01")
        + _block(
            "1.01",
            "Historical cache body without a transport receipt or envelope.",
            path="/statutes/statutes/1/01",
        ),
        title="Wisconsin Legislature: Chapter 1",
    )
    digest = hashlib.sha256(payload).hexdigest()
    scraper._state_law_acquisition_ledger = _ReceiptlessHistoricalCache(
        {scraper.official_chapter_url(1): payload}
    )
    historical_record = {
        "cached_at": "2024-01-01T00:00:00Z",
        "provider": "requests_direct",
        "sha256": digest,
        "size": len(payload),
        "state_code": "WI",
        "url": scraper.official_chapter_url(1),
    }
    with pytest.raises(RuntimeError, match="receipt lacks URL/digest"):
        scraper._validate_wisconsin_aligned_evidence(
            url=scraper.official_chapter_url(1),
            payload=payload,
            transport_receipt=historical_record,
            parser_input_envelope=SimpleNamespace(body=payload),
            frontier_name="historical-cache",
        )
    with pytest.raises(RuntimeError, match="lacks retained evidence"):
        scraper._validate_wisconsin_aligned_evidence(
            url=scraper.official_chapter_url(1),
            payload=payload,
            transport_receipt=None,
            parser_input_envelope=None,
            frontier_name="historical-cache",
        )


def test_wisconsin_compact_recipe_closes_each_source_derived_continuation_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(WisconsinScraper, "STRICT_MINIMUM_CHAPTERS", 2)
    scraper = WisconsinScraper("WI", "Wisconsin")
    pages = _synthetic_pages(scraper)
    batch_calls: list[tuple[list[str], dict]] = []

    async def _plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        batch_calls.append((requested, {"retries": residual_retry_attempts, **kwargs}))
        missing = [url for url in requested if url not in pages]
        if missing:
            raise AssertionError(f"compact recipe requested unknown URL {missing}")
        return _frontier_result(requested, [pages[url] for url in requested])

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict Wisconsin must not use a per-page archive loop")

    monkeypatch.setattr(
        WisconsinScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(
        WisconsinScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )

    rows = asyncio.run(
        scraper.scrape_code(
            "Wisconsin Statutes",
            scraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
    )

    stats = list(getattr(scraper, "_wisconsin_frontier_batch_stats", []))
    wave_names = [str(row.get("frontier_name") or "") for row in stats]
    requested_urls = [url for urls, _kwargs in batch_calls for url in urls]
    assert wave_names == [
        ROOT_WAVE_NAME,
        f"{CHAPTER_WAVE_PREFIX}1",
        f"{CHAPTER_WAVE_PREFIX}2",
        f"{SECTION_WAVE_PREFIX}1",
        f"{SECTION_WAVE_PREFIX}2",
    ]
    assert [row.section_number for row in rows] == ["1.01", "1.03", "2.01", "2.02"]
    assert section_url("1.03") in requested_urls
    assert section_url(CITATION_LINK_NON_TOC_SECTION) not in requested_urls
    assert INVENTED_CONTINUATION_URL not in requested_urls
    assert INVENTED_SECTION_URL not in requested_urls
    assert CHAPTER_PDF_URL not in requested_urls
    assert all(not url.endswith(".pdf") for url in requested_urls)
    assert all(kwargs["retries"] == 1 for _urls, kwargs in batch_calls)
    assert all(
        kwargs["wayback_prefix_inventory"] is False for _urls, kwargs in batch_calls
    )
    assert all(
        kwargs["archive_recovery_enabled"] is True for _urls, kwargs in batch_calls
    )
    assert all(
        kwargs["repeat_grouped_archive_inventory_on_residual"] is False
        for _urls, kwargs in batch_calls
    )
    assert all(kwargs["prefer_direct"] is True for _urls, kwargs in batch_calls)
    digest = _canonical_residual_sha256(requested_urls)
    assert digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    assert len(digest) == 64


def test_wisconsin_invented_later_continuation_fails_closed_on_missing_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(WisconsinScraper, "STRICT_MINIMUM_CHAPTERS", 2)
    scraper = WisconsinScraper("WI", "Wisconsin")
    pages = _synthetic_pages(scraper)
    pages.pop(f"{scraper.get_base_url()}/statutes/statutes/2/_60?down=1")

    async def _plural(self, urls, **_kwargs):
        requested = list(urls)
        assert INVENTED_CONTINUATION_URL not in requested
        return _frontier_result(
            requested,
            [pages.get(url, b"") for url in requested],
        )

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("missing continuation must not fall back to a per-page loop")

    monkeypatch.setattr(
        WisconsinScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(
        WisconsinScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )
    with pytest.raises(RuntimeError, match="unresolved exact URLs"):
        asyncio.run(
            scraper.scrape_code(
                "Wisconsin Statutes",
                scraper.OFFICIAL_ENTRY_URL,
                max_statutes=None,
            )
        )

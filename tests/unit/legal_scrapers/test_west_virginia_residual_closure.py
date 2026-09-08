"""LCR-098: West Virginia fresh-root plus 139-chapter residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, importing catalog descriptions,
singleton artifacts, or source-recovery experiments, resuming absent
staging-wv-v1 roots, and admitting obsolete repaired-static chapter 48A.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_isolated_worker import (
    IsolatedRetainedReplayWorkerError,
    build_host_retained_replay_command,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.strict_frontier_closure import (
    retain_exact_state_frontier_closure,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.west_virginia import (
    WestVirginiaScraper,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "west_virginia_residual_closure_v1.md"
)

OFFICIAL_DOMAIN = "code.wvlegislature.gov"
CURRENT_ROOT = "https://code.wvlegislature.gov/"
CHAPTER_01 = "https://code.wvlegislature.gov/1/"
CHAPTER_05A = "https://code.wvlegislature.gov/5A/"
CHAPTER_64 = "https://code.wvlegislature.gov/64/"
ARTICLE_01 = "https://code.wvlegislature.gov/1-1/"
ARTICLE_05A = "https://code.wvlegislature.gov/5A-1/"
ARTICLE_11_13AA = "https://code.wvlegislature.gov/11-13AA/"
SECTION_01 = "https://code.wvlegislature.gov/1-1-1/"
SECTION_05A = "https://code.wvlegislature.gov/5A-1-1/"
SECTION_11_13AA = "https://code.wvlegislature.gov/11-13AA-3/"
SECTION_11_2_5_56 = "https://code.wvlegislature.gov/11-2-5(56)/"
SECTION_48_1_233_1 = "https://code.wvlegislature.gov/48-1-233.1/"
INVENTED_ARTICLE_13AAA = "https://code.wvlegislature.gov/11-13AAA/"
INVENTED_CHAPTER_48A = "https://code.wvlegislature.gov/48A/"
SINGLETON_61_2_1 = "https://code.wvlegislature.gov/61-2-1/"
CONSTITUTION_URL = "https://home.wvlegislature.gov/constitution-of-west-virginia/"
RETAINED_STRICT_PARSER_INPUTS = 0
RESIDUAL_COUNT = 140
CHAPTER_COUNT = 139
DIAGNOSTIC_ROOT_BYTES = 37628
DIAGNOSTIC_ROOT_SHA256_PREFIX = "cf36b6769ae"
DIAGNOSTIC_CHAPTER_ID_SHA256_PREFIX = "5189c5177146"
DIAGNOSTIC_CHAPTER_URL_SHA256_PREFIX = "6c2473b0371b"
DIAGNOSTIC_LABEL_SHA256_PREFIX = "b2e241965274"
CATALOG_FIRST_UNITS = 140
SINGLETON_ARTIFACT_ROWS = 2
SOURCE_RECOVERY_EXPERIMENTS = 12
SOURCE_RECOVERY_HTML_CANDIDATES = 8
LIVE_PROBE_CHAPTER_1_ARTICLES = 8
LIVE_PROBE_ARTICLE_1_SECTIONS = 6
LIVE_PROBE_SECTION_CHARS = 679
SOURCE_BUNDLE_PREFIX = "3cf4048dd5f3"
RESIDUAL_SHA256_PREFIX = "fresh_root_plus_139_chapters_code_wvlegislature_gov"
DIAGNOSTIC_PRODUCER_PREFIX = "WestVirginiaScraper@sha256:3cf4048dd5f3"
ROOT_WAVE_NAME = "root-index"
CHAPTER_WAVE_NAME = "chapter-index"
ARTICLE_WAVE_NAME = "article-index"
SECTION_WAVE_PREFIX = "sections-"
OBSOLETE_REPAIRED_IDS = ("48A",)
FENCED_ABSENT_ROOTS = (
    "staging-wv-v1",
    "full-acquisition-evidence-v20-wv-v1",
)
COMPACT_CHAPTERS = (
    ("1", "The State and Its Subdivisions"),
    ("5A", "Department of Administration"),
)


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _section_page(*, chapter: str, text: str) -> bytes:
    return (
        "<html><head><title>West Virginia Code</title></head><body>"
        f"<h3>CHAPTER {chapter}. TEST.</h3>"
        "<div class='art-head'>ARTICLE 1. TEST.</div>"
        "<div class='sectiontext'>"
        f"<h4>§{chapter}-1-1. Synthetic operative section.</h4>"
        f"<p>{text}</p>"
        "</div></body></html>"
    ).encode()


def _compact_root_html(*chapters: tuple[str, str], extra: str = "") -> bytes:
    items = []
    for number, name in chapters:
        items.append(
            f"<option value='{number}'>CHAPTER {number}. {name}</option>"
        )
    return (
        "<html><head><title>West Virginia Code</title></head><body>"
        "<select id='sel-chapter'>"
        + "".join(items)
        + extra
        + "</select></body></html>"
    ).encode()


def _compact_current_root_pages() -> dict[str, bytes]:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    chapter_1 = scraper.official_chapter_url("1")
    chapter_5a = scraper.official_chapter_url("5A")
    operative = (
        "This West Virginia Code provision contains operative synthetic "
        "legal text for an exact offline hierarchy test. It is intentionally "
        "long enough to satisfy the retained section parser without fallback. "
        "The provision continues with additional enforceable words and clauses."
    )
    return {
        CURRENT_ROOT: _compact_root_html(
            *COMPACT_CHAPTERS,
            extra=(
                "<option value='48A'>CHAPTER 48A. Enforcement of Family "
                "Obligations</option>"
            ),
        ),
        chapter_1: (
            "<html><head><title>West Virginia Code</title></head><body>"
            "<h3>CHAPTER 1. The State and Its Subdivisions</h3>"
            "<div class='art-head'><a href='/1-1/'>ARTICLE 1. TEST.</a></div>"
            "</body></html>"
        ).encode(),
        chapter_5a: (
            "<html><head><title>West Virginia Code</title></head><body>"
            "<h3>CHAPTER 5A. Department of Administration</h3>"
            "<div class='art-head'><a href='/5A-1/'>ARTICLE 1. TEST.</a></div>"
            "</body></html>"
        ).encode(),
        ARTICLE_01: (
            "<html><head><title>West Virginia Code</title></head><body>"
            "<h3>CHAPTER 1. TEST.</h3>"
            "<div class='art-head'>ARTICLE 1. TEST.</div>"
            "<div class='sec-head'><a href='/1-1-1/'>§1-1-1. Synthetic section."
            "</a></div>"
            "<div id='all-sections' class='sec-head' data-id='ah-1' "
            "data-mode='hide'>Display all Article 1 Sections</div>"
            "</body></html>"
        ).encode(),
        ARTICLE_05A: (
            "<html><head><title>West Virginia Code</title></head><body>"
            "<h3>CHAPTER 5A. TEST.</h3>"
            "<div class='art-head'>ARTICLE 1. TEST.</div>"
            "<div class='sec-head'><a href='/5A-1-1/'>§5A-1-1. Synthetic "
            "section.</a></div>"
            "<div id='all-sections' class='sec-head' data-id='ah-1' "
            "data-mode='hide'>Display all Article 1 Sections</div>"
            "</body></html>"
        ).encode(),
        SECTION_01: _section_page(chapter="1", text=operative),
        SECTION_05A: _section_page(chapter="5A", text=operative),
        INVENTED_CHAPTER_48A: (
            "<html><head><title>West Virginia Code</title></head><body>"
            "<h3>CHAPTER 48A. Invented</h3>"
            "<div class='art-head'><a href='/48A-1/'>ARTICLE 1. Invented</a>"
            "</div></body></html>"
        ).encode(),
        CONSTITUTION_URL: (
            "<html><head><title>West Virginia Constitution</title></head><body>"
            "<p>Constitutional text is outside the statutory corpus.</p>"
            "</body></html>"
        ).encode(),
    }


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
) -> StateLawPageMultiFetchResult:
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=[None] * len(urls),
        transport_receipts=[
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "source_transport": "direct",
            }
            for url, payload in zip(urls, payloads, strict=True)
        ],
        parser_input_envelopes=[
            SimpleNamespace(body=payload) for payload in payloads
        ],
        stats={
            "network_requested_pages": 0,
            "requested_pages": len(urls),
            "per_page_archive_fallback_disabled": True,
            "range_fetches_avoided": max(0, len(urls) - 1),
        },
    )


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("West Virginia residual closure report is empty")
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
        if field in {"Field", "---", "Step"} or set(field) == {"-"}:
            continue
        rows[field] = value.strip("`")
    return rows


def _source_ordered_chapters(root_html: bytes) -> list[str]:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    units = scraper._west_virginia_root_chapter_units(root_html)
    urls = [str(unit["source_url"]) for unit in units]
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            raise AssertionError(
                "West Virginia current-root chapter frontier repeated a URL"
            )
        seen.add(url)
    return urls


def _official_chapter_urls() -> list[str]:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    return [
        scraper.official_chapter_url(number)
        for number, _name in scraper.OFFICIAL_CHAPTERS
    ]


def test_west_virginia_residual_closure_report_records_exact_fresh_root_and_chapter_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "WV"
    assert table["official domain"] == OFFICIAL_DOMAIN
    assert table["official entry"] == CURRENT_ROOT
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == (
        "official HTML tree root → chapter → article → section"
    )
    assert table["seed"] == (
        "zero authorizing current-ledger inputs; start from absent "
        "staging-wv-v1 and full-acquisition-evidence-v20-wv-v1"
    )
    assert table["start_from_absent_staging_roots"] == "true"
    assert table["resume_staging_wv_v1"] == "forbidden"
    assert table["resume_full_acquisition_evidence_v20_wv_v1"] == "forbidden"
    assert table["import_catalog_descriptions"] == "forbidden"
    assert table["import_singleton_artifacts"] == "forbidden"
    assert table["import_source_recovery_experiments"] == "forbidden"
    assert table["import_west_virginia_dump"] == "forbidden"
    assert table["legacy_insecure_tls_authorizing"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["invent_later_chapter_targets"] == "forbidden"
    assert table["obsolete_repaired_chapter_ids"] == "48A forbidden"
    assert table["per_page_archive_loop"] == "false"
    assert table["retained_strict_parser_inputs"] == str(
        RETAINED_STRICT_PARSER_INPUTS
    )
    assert table["diagnostic_root_bytes"] == str(DIAGNOSTIC_ROOT_BYTES)
    assert table["diagnostic_root_sha256"].startswith(DIAGNOSTIC_ROOT_SHA256_PREFIX)
    assert table["diagnostic_root_authorizing"] == "false"
    assert table["diagnostic_chapter_count"] == str(CHAPTER_COUNT)
    assert table["diagnostic_chapter_id_sha256"].startswith(
        DIAGNOSTIC_CHAPTER_ID_SHA256_PREFIX
    )
    assert table["diagnostic_chapter_url_sha256"].startswith(
        DIAGNOSTIC_CHAPTER_URL_SHA256_PREFIX
    )
    assert table["diagnostic_label_sha256"].startswith(DIAGNOSTIC_LABEL_SHA256_PREFIX)
    assert table["diagnostic_chapter_id_sha256_prefix"] == (
        DIAGNOSTIC_CHAPTER_ID_SHA256_PREFIX
    )
    assert table["diagnostic_chapter_url_sha256_prefix"] == (
        DIAGNOSTIC_CHAPTER_URL_SHA256_PREFIX
    )
    assert table["diagnostic_label_sha256_prefix"] == DIAGNOSTIC_LABEL_SHA256_PREFIX
    assert table["catalog_first_reported_units"] == str(CATALOG_FIRST_UNITS)
    assert table["catalog_first_bundle_closed"] == "false"
    assert table["catalog_first_includes_obsolete_48A"] == "true"
    assert table["catalog_first_authorizing"] == "false"
    assert table["catalog_first_receipt"] == "absent"
    assert table["singleton_artifact_rows"] == str(SINGLETON_ARTIFACT_ROWS)
    assert table["singleton_artifact_sections"] == "61-2-1, 61-2-2"
    assert table["singleton_artifact_authorizing"] == "false"
    assert table["source_recovery_experiments"] == str(SOURCE_RECOVERY_EXPERIMENTS)
    assert table["source_recovery_section"] == "61-2-9"
    assert table["source_recovery_html_candidates"] == str(
        SOURCE_RECOVERY_HTML_CANDIDATES
    )
    assert table["source_recovery_distinct_digests"] == "8"
    assert table["source_recovery_transport_receipt"] == "absent"
    assert table["source_recovery_authorizing"] == "false"
    assert table["legal_page_cache_wv_urls"] == "0"
    assert table["live_probe_chapter_1_articles"] == str(
        LIVE_PROBE_CHAPTER_1_ARTICLES
    )
    assert table["live_probe_article_1_section_locators"] == str(
        LIVE_PROBE_ARTICLE_1_SECTIONS
    )
    assert table["live_probe_section_1_1_1_chars"] == str(LIVE_PROBE_SECTION_CHARS)
    assert table["live_probe_authorizing"] == "false"
    assert "div.sec-head" in table["display_all_article_sections_scaffold"]
    assert table["constitution_in_corpus"] == "false"
    assert table["court_rules_in_corpus"] == "false"
    assert table["editorial_secondary_in_corpus"] == "false"
    assert table["chapter_membership_count"] == str(CHAPTER_COUNT)
    assert table["article_membership_count"] == (
        "source_dependent_after_139_chapters"
    )
    assert table["section_membership_count"] == (
        "source_dependent_after_139_chapters"
    )
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_floor"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == (
        "fresh official root plus 139 source-ordered chapters"
    )
    assert table["residual_first_url"] == CURRENT_ROOT
    assert table["residual_first_chapter_url"] == CHAPTER_01
    assert table["residual_last_chapter_url"] == CHAPTER_64
    assert table["residual_wave_name"] == ROOT_WAVE_NAME
    assert table["chapter_wave_name"] == CHAPTER_WAVE_NAME
    assert table["article_wave_name"] == ARTICLE_WAVE_NAME
    assert table["section_wave_name_prefix"] == SECTION_WAVE_PREFIX
    assert table["root_acquisition_wave_count"] == "1"
    assert table["chapter_acquisition_wave_count"] == "1"
    assert table["fetch_root_before_chapters"] == "true"
    assert table["fetch_chapters_before_articles"] == "true"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["source_bundle_prefix"] == SOURCE_BUNDLE_PREFIX
    assert table["diagnostic_producer"].startswith(DIAGNOSTIC_PRODUCER_PREFIX)
    assert table["diagnostic_hashes_authorizing"] == "false"
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert RETAINED_STRICT_PARSER_INPUTS + RESIDUAL_COUNT == 140
    assert int(table["diagnostic_chapter_count"]) + 1 == RESIDUAL_COUNT
    assert int(table["catalog_first_reported_units"]) == CHAPTER_COUNT + 1

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "fresh" in lowered and "139" in report
    assert "hub mutation" in lowered
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "catalog descriptions" in lowered
    assert "source-recovery" in lowered or "source recovery" in lowered
    assert "insecure-tls" in lowered or "insecure tls" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert CURRENT_ROOT in report
    assert CHAPTER_01 in report
    assert CHAPTER_64 in report
    assert CHAPTER_05A in report
    assert DIAGNOSTIC_CHAPTER_URL_SHA256_PREFIX in report
    assert INVENTED_CHAPTER_48A not in report
    assert CONSTITUTION_URL not in report
    assert SINGLETON_61_2_1 not in report
    chapter_url_mentions = re.findall(
        r"https://code\.wvlegislature\.gov/[0-9A-Za-z]+/",
        report,
    )
    assert len(chapter_url_mentions) < 10
    assert "source_dependent_after_139_chapters" in report
    for fenced in FENCED_ABSENT_ROOTS:
        assert fenced in report


def test_west_virginia_root_and_chapters_are_source_derived_and_not_catalog_first() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    assert scraper.get_base_url() == f"https://{OFFICIAL_DOMAIN}"
    assert scraper.OFFICIAL_DOMAIN == OFFICIAL_DOMAIN
    assert scraper.OFFICIAL_ENTRY_URL == CURRENT_ROOT
    assert scraper.get_code_list()[0]["url"] == CURRENT_ROOT
    assert scraper.official_chapter_url("1") == CHAPTER_01
    assert scraper.official_chapter_url("5A") == CHAPTER_05A
    assert scraper.official_chapter_url("64") == CHAPTER_64
    assert scraper.OFFICIAL_CHAPTER_COUNT == CHAPTER_COUNT
    assert len(scraper.OFFICIAL_CHAPTERS) == CHAPTER_COUNT

    numbers = [number for number, _name in scraper.OFFICIAL_CHAPTERS]
    assert numbers[0] == "1"
    assert numbers[-1] == "64"
    assert "5A" in numbers
    for obsolete in OBSOLETE_REPAIRED_IDS:
        assert obsolete not in numbers

    chapter_urls = _official_chapter_urls()
    assert chapter_urls[0] == CHAPTER_01
    assert chapter_urls[-1] == CHAPTER_64
    assert CHAPTER_05A in chapter_urls
    assert INVENTED_CHAPTER_48A not in chapter_urls
    assert len(chapter_urls) == CHAPTER_COUNT

    compact_root = _compact_root_html(*COMPACT_CHAPTERS)
    derived = _source_ordered_chapters(compact_root)
    assert derived == [CHAPTER_01, CHAPTER_05A]
    assert INVENTED_CHAPTER_48A not in derived
    assert CONSTITUTION_URL not in derived

    strict = inspect.getsource(WestVirginiaScraper._scrape_strict_full_corpus_frontier)
    assert f'frontier_name="{ROOT_WAVE_NAME}"' in strict
    assert f'frontier_name="{CHAPTER_WAVE_NAME}"' in strict
    assert f'frontier_name="{ARTICLE_WAVE_NAME}"' in strict
    assert f'"{SECTION_WAVE_PREFIX}' in strict or "sections-" in strict
    assert strict.index(f'frontier_name="{ROOT_WAVE_NAME}"') < strict.index(
        f'frontier_name="{CHAPTER_WAVE_NAME}"'
    )
    assert strict.index(f'frontier_name="{CHAPTER_WAVE_NAME}"') < strict.index(
        f'frontier_name="{ARTICLE_WAVE_NAME}"'
    )
    assert "[self.OFFICIAL_ENTRY_URL]" in strict
    assert "_official_http_get" not in strict
    assert "ssl._create_unverified_context" not in strict
    assert INVENTED_CHAPTER_48A not in strict
    assert "web.archive.org" not in strict
    assert "_discover_chapter_links" not in strict
    assert "west_virginia_dump" not in strict
    assert SINGLETON_61_2_1 not in strict


def test_west_virginia_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(WestVirginiaScraper)
    fetch_source = inspect.getsource(
        WestVirginiaScraper._fetch_west_virginia_frontier_batch
    )
    strict = inspect.getsource(WestVirginiaScraper._scrape_strict_full_corpus_frontier)
    assert str(DIAGNOSTIC_ROOT_BYTES) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert DIAGNOSTIC_CHAPTER_URL_SHA256_PREFIX not in adapter
    assert DIAGNOSTIC_ROOT_SHA256_PREFIX not in adapter
    for fenced in FENCED_ABSENT_ROOTS:
        assert fenced not in adapter
    assert INVENTED_CHAPTER_48A not in adapter
    assert INVENTED_CHAPTER_48A not in strict
    assert INVENTED_CHAPTER_48A not in fetch_source
    assert '[unit["source_url"] for unit in chapter_units]' in strict
    assert "[self.OFFICIAL_ENTRY_URL]" in strict
    assert adapter.count("https://code.wvlegislature.gov/61-2-1/") <= 1


def test_west_virginia_chapter_identity_strips_bom_prefix() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    payload = (
        "<html><body>"
        "<h3>Primary menu</h3>"
        "<h3>\ufeffCHAPTER 37B. MINERAL DEVELOPMENT.</h3>"
        "<h3>Loading Articles</h3>"
        "</body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="chapter") == "37B"


def test_west_virginia_admits_official_double_letter_article_urls() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    article_url, article_groups = scraper._canonical_west_virginia_hierarchy_url(
        ARTICLE_11_13AA,
        level="article",
        chapter_number="11",
    )
    section_url, section_groups = scraper._canonical_west_virginia_hierarchy_url(
        SECTION_11_13AA,
        level="section",
        chapter_number="11",
        article_number="13AA",
    )
    assert article_url == ARTICLE_11_13AA
    assert article_groups == {"chapter": "11", "article": "13AA"}
    assert section_url == SECTION_11_13AA
    assert section_groups == {
        "chapter": "11",
        "article": "13AA",
        "section": "3",
    }
    with pytest.raises(RuntimeError, match="non-canonical URL"):
        scraper._canonical_west_virginia_hierarchy_url(
            INVENTED_ARTICLE_13AAA,
            level="article",
            chapter_number="11",
        )


def test_west_virginia_admits_official_parenthetical_section_urls() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    section_url, section_groups = scraper._canonical_west_virginia_hierarchy_url(
        SECTION_11_2_5_56,
        level="section",
        chapter_number="11",
        article_number="2",
    )
    assert section_url == SECTION_11_2_5_56
    assert section_groups == {
        "chapter": "11",
        "article": "2",
        "section": "5(56)",
    }
    payload = (
        "<html><body><h4>§ 11-2-5(56). Restricted accounts.</h4></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "11-2-5(56)"


def test_west_virginia_admits_official_dotted_section_urls() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    section_url, section_groups = scraper._canonical_west_virginia_hierarchy_url(
        SECTION_48_1_233_1,
        level="section",
        chapter_number="48",
        article_number="1",
    )
    assert section_url == SECTION_48_1_233_1
    assert section_groups == {
        "chapter": "48",
        "article": "1",
        "section": "233.1",
    }
    payload = (
        "<html><body><h4>§ 48-1-233.1. Definitions.</h4></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "48-1-233.1"


def test_west_virginia_captioned_acts_repeal_is_source_bound_terminal() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/1-2-2A/"
    payload = (
        "<html><body>"
        "<h4>§1-2-2a. Legislative findings.</h4>"
        "<div class='sectiontext'>"
        "§1-2-2a. Legislative findings. Repealed. Acts, 1971 2nd Ex. Sess., Ch. 60."
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "1-2-2A"
    assert scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="1-2-2A",
        payload=payload,
        discovery_method="test",
    ) is None
    assert scraper._source_bound_west_virginia_terminal_disposition(
        payload,
        source_url=url,
        source_label="§1-2-2a. Legislative findings.",
        level="section",
        expected_identity="1-2-2A",
        observed_on=date(2026, 8, 30),
    ) == {
        "disposition": "repealed",
        "source_label": "§1-2-2a. Legislative findings.",
        "source_url": url,
    }
    assert scraper._west_virginia_terminal_disposition(
        "§1-2-2. Priority of repealed statutes.",
        observed_on=date(2026, 8, 30),
    ) is None


def test_west_virginia_short_operative_repeal_section_is_not_dropped() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/1-5-4/"
    payload = (
        "<html><body>"
        "<h4>§1-5-4. Repeal.</h4>"
        "<div class='sectiontext'><h4>§1-5-4. Repeal.</h4>"
        "<p>All acts or parts of acts which are inconsistent with the provisions "
        "of this article are hereby repealed to the extent of such inconsistency.</p>"
        "</div></body></html>"
    ).encode("utf-8")
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="1-5-4",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "1-5-4"
    assert "inconsistent with the provisions of this article" in (row.full_text or "")
    assert scraper._source_bound_west_virginia_terminal_disposition(
        payload,
        source_url=url,
        source_label="§1-5-4. Repeal.",
        level="section",
        expected_identity="1-5-4",
        observed_on=date(2026, 8, 30),
    ) is None


def test_west_virginia_section_identity_reads_sectiontext_without_h4() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/5-1C-1/"
    payload = (
        "<html><body>"
        "<div class='sectiontext'>"
        "§5-1C-1. Repealed. Acts, 2003 Reg. Sess., Ch. 197."
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "5-1C-1"
    assert scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="5-1C-1",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    ) is None
    assert scraper._source_bound_west_virginia_terminal_disposition(
        payload,
        source_url=url,
        source_label="§5-1C-1",
        level="section",
        expected_identity="5-1C-1",
        observed_on=date(2026, 8, 30),
    ) == {
        "disposition": "repealed",
        "source_label": "§5-1C-1",
        "source_url": url,
    }


def test_west_virginia_en_dash_heading_and_glued_acts_repeal() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/5A-3-14/"
    payload = (
        "<html><body>"
        "<h4>§5A–3-14.</h4>"
        "<div class='sectiontext'>§5A–3-14. Repealed.Acts, 2010 Reg. Sess., Ch 169.</div>"
        "</body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "5A-3-14"
    assert scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="5A-3-14",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    ) is None
    assert scraper._source_bound_west_virginia_terminal_disposition(
        payload,
        source_url=url,
        source_label="§5A-3-14",
        level="section",
        expected_identity="5A-3-14",
        observed_on=date(2026, 8, 30),
    ) == {
        "disposition": "repealed",
        "source_label": "§5A-3-14",
        "source_url": url,
    }


def test_west_virginia_heading_without_section_sign_and_bracketed_repeal() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/5A-11-6/"
    payload = (
        "<html><head><title>West Virginia Code | §5A-11-6</title></head><body>"
        "<h4>5A-11-6. Competitive bidding and notice requirements before the "
        "development or extraction of minerals on certain lands; related "
        "standards.</h4>"
        "<div class='sectiontext'>5A-11-6. Competitive bidding and notice "
        "requirements before the development or extraction of minerals on "
        "certain lands; related standards. [Repealed.]</div>"
        "</body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "5A-11-6"
    assert scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="5A-11-6",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    ) is None
    assert scraper._source_bound_west_virginia_terminal_disposition(
        payload,
        source_url=url,
        source_label="5A-11-6",
        level="section",
        expected_identity="5A-11-6",
        observed_on=date(2026, 8, 30),
    ) == {
        "disposition": "repealed",
        "source_label": "5A-11-6",
        "source_url": url,
    }


def test_west_virginia_part_header_does_not_mask_section_heading() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/7-27-4/"
    payload = (
        "<html><head><title>West Virginia Code | §7-27-4</title></head><body>"
        "<div class='sectiontext'>"
        "<h4>PART II. COUNTY ROAD AND BRIDGE CONSTRUCTION PROJECTS.</h4>"
        "<h4>§7-27-4. Creation of county road construction project plan.</h4>"
        "<p>A county commission may, upon its own initiative or upon application of "
        "a highway authority, propose creation of a road construction project plan "
        "for the county.</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "7-27-4"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="7-27-4",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "7-27-4"
    assert "propose creation of a road construction project plan" in (row.full_text or "")
    assert scraper._source_bound_west_virginia_terminal_disposition(
        payload,
        source_url=url,
        source_label="§7-27-4",
        level="section",
        expected_identity="7-27-4",
        observed_on=date(2026, 8, 30),
    ) is None


def test_west_virginia_heading_collapses_spaces_around_cite_hyphens() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/30-10-24/"
    payload = (
        "<html><head><title>West Virginia Code | §30-10-24</title></head><body>"
        "<div class='sectiontext'>"
        "<h4>§30-10- 24. Telehealth practice.</h4>"
        "<p>(a) For purposes of this section, these terms have the following "
        "meaning:</p>"
        "<p>(1) Interstate telehealth services means the provision of telehealth "
        "services to a patient located in West Virginia by a registered "
        "veterinary care professional located in any other state.</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert (
        scraper._west_virginia_normalize_heading("§30-10- 24. Telehealth practice.")
        == "§30-10-24. Telehealth practice."
    )
    assert scraper._west_virginia_page_identity(payload, level="section") == "30-10-24"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="30-10-24",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "30-10-24"
    assert "telehealth" in (row.full_text or "").casefold()


def test_west_virginia_operative_body_in_h5() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/48-31-103/"
    payload = (
        "<html><head><title>West Virginia Code | §48-31-103</title></head><body>"
        "<div class='sectiontext'>"
        "<h4>§48-31-103. Remedies for noncompliance.</h4>"
        "<h4></h4>"
        "<h5>In addition to other remedies under law of this state other than this "
        "article, if a court finds that a party to a proceeding under this article "
        "has acted in bad faith or intentionally failed to comply with this article "
        "or a court order issued under this article, the court may assess reasonable "
        "attorney's fees and costs against the party and order other appropriate "
        "relief.</h5>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "48-31-103"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="48-31-103",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "48-31-103"
    assert "reasonable attorney" in (row.full_text or "")


def test_west_virginia_heading_strips_duplicate_chapter_section_sign() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/31B-11-1104/"
    payload = (
        "<html><head><title>West Virginia Code | §31B-11-1104</title></head><body>"
        "<div class='sectiontext'>"
        "<h4>§31B-§31B-11-1104. Expenses.</h4>"
        "<p>If a derivative action for a limited liability company is successful, "
        "in whole or in part, or if anything is received by the plaintiff as a "
        "result of a judgment, compromise or settlement of an action or claim, "
        "the court may award the plaintiff reasonable expenses, including "
        "reasonable attorney's fees.</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert (
        scraper._west_virginia_normalize_heading("§31B-§31B-11-1104. Expenses.")
        == "§31B-11-1104. Expenses."
    )
    assert scraper._west_virginia_page_identity(payload, level="section") == "31B-11-1104"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="31B-11-1104",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "31B-11-1104"
    assert "reasonable expenses" in (row.full_text or "")


def test_west_virginia_operative_body_in_second_h4() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/30-9-34/"
    payload = (
        "<html><head><title>West Virginia Code | §30-9-34</title></head><body>"
        "<div class='sectiontext'>"
        "<h4>§30-9-34. Indemnification.</h4>"
        "<h4>In the event that a lawsuit is filed alleging violation of federal "
        "antitrust laws, the board may indemnify its board members and current "
        "and former employees for expenses reasonably incurred in connection with "
        "judicial or administrative proceedings.</h4>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "30-9-34"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="30-9-34",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "30-9-34"
    assert "indemnify its board members" in (row.full_text or "")


def test_west_virginia_paragraph_cite_ignores_later_cross_references() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/5-3-3/"
    payload = (
        "<html><head><title>West Virginia Code | §5-3-3</title></head><body>"
        "<div class='sectiontext'>"
        "<p>§5-3-3. Assistants to Attorney General.</p>"
        "<p>The Attorney General may appoint such deputy or assistant attorneys "
        "general as may be necessary. Contingency appointments must follow "
        "W. Va. Code §5-3-3a(a)(1).</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "5-3-3"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="5-3-3",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "5-3-3"


def test_west_virginia_part_title_h4_reads_cite_from_h2() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/22A-2-7/"
    payload = (
        "<html><head><title>West Virginia Code | §22A-2-7</title></head><body>"
        "<div class='sectiontext'><h4>MINE FOREMAN</h4>"
        "<h2>§22A-2-7. When underground mine foreman-fire boss required; assistants; "
        "certification.</h2>"
        "<p>(a) In every underground mine where five or more persons are employed "
        "in a period of twenty-four hours, the operator shall employ at least one "
        "person certified as a mine foreman-fire boss.</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "22A-2-7"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="22A-2-7",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "22A-2-7"
    assert "mine foreman-fire boss" in (row.full_text or "")


def test_west_virginia_empty_h4_reads_cite_from_first_paragraph() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/22-16-1/"
    payload = (
        "<html><head><title>West Virginia Code | §22-16-1</title></head><body>"
        "<div class='sectiontext'><h4></h4>"
        "<p>§22-16-1. Legislative findings and purpose.</p>"
        "<p>The Legislature finds that there are numerous landfills throughout the "
        "state that must be closed because they cannot be operated in an "
        "environmentally sound manner.</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "22-16-1"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="22-16-1",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "22-16-1"
    assert "landfills throughout the state" in (row.full_text or "")


def test_west_virginia_heading_strips_control_char_before_cite() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/18-9A-8A/"
    payload = (
        "<html><head><title>West Virginia Code | §18-9A-8A</title></head><body>"
        "<div class='sectiontext'>"
        "<h4>\x1518-9A-8a. Foundation allowance for regional education service "
        "agencies.</h4>"
        "<p>[Repealed.]</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "18-9A-8A"
    assert scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="18-9A-8A",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    ) is None
    assert scraper._source_bound_west_virginia_terminal_disposition(
        payload,
        source_url=url,
        source_label="§18-9A-8A",
        level="section",
        expected_identity="18-9A-8A",
        observed_on=date(2026, 8, 30),
    ) == {
        "disposition": "repealed",
        "source_label": "§18-9A-8A",
        "source_url": url,
    }


def test_west_virginia_heading_strips_cms_digit_before_section_sign() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/11-17-7/"
    payload = (
        "<html><head><title>West Virginia Code | §11-17-7</title></head><body>"
        "<div class='sectiontext'>"
        "<h4>0§11-17-7. Form of stamps; custody; discounts; security for payments.</h4>"
        "<p>The commissioner shall design and procure stamps to be used as herein "
        "provided for, affixed and attached to containers, packages or receptacle "
        "of whatever kind that may be used for containing cigarettes.</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "11-17-7"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="11-17-7",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "11-17-7"
    assert "design and procure stamps" in (row.full_text or "")


def test_west_virginia_heading_without_section_sign_is_operative() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    url = "https://code.wvlegislature.gov/11-13HH-2/"
    payload = (
        "<html><head><title>West Virginia Code | §11-13HH-2</title></head><body>"
        "<div class='sectiontext'><h4>11-13HH-2. Definitions.</h4>"
        "<p>(a) General. When used in this article, terms defined in subsection "
        "(b) have the meanings ascribed to them by this section.</p>"
        "<p>(b) Terms defined. Affiliate means an individual, corporation, "
        "partnership, affiliate, association or trust controlled by the taxpayer.</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(payload, level="section") == "11-13HH-2"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url=url,
        section_number="11-13HH-2",
        payload=payload,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "11-13HH-2"
    assert "meanings ascribed to them" in (row.full_text or "")


def test_west_virginia_catalog_href_defers_to_printed_section_cite() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    payload = (
        "<html><body>"
        "<div class='art-head'>ARTICLE 29. INTERGOVERNMENTAL RELATIONS -- "
        "REGIONAL AIRPORTS.</div>"
        "<div class='sec-head' data-id='ah-29'>"
        "<a href='/8-29-8A/'>§8-29B-8a. Abandoned or derelict aircraft.</a>"
        "</div></body></html>"
    ).encode("utf-8")
    units = scraper._west_virginia_child_units(
        payload,
        level="section",
        chapter_number="8",
        article_number="29",
    )
    assert units == [
        {
            "article": "29B",
            "chapter": "8",
            "section": "8A",
            "source_label": "§8-29B-8a. Abandoned or derelict aircraft.",
            "source_url": "https://code.wvlegislature.gov/8-29-8A/",
        }
    ]
    page = (
        "<html><head><title>West Virginia Code | §8-29-8A</title></head><body>"
        "<div class='sectiontext'>"
        "<h4>§8-29B-8a. Abandoned or derelict aircraft.</h4>"
        "<p>If an abandoned or derelict aircraft is discovered on an airport, "
        "the airport authority shall make a record of the date the aircraft was "
        "discovered on the airport.</p>"
        "</div></body></html>"
    ).encode("utf-8")
    assert scraper._west_virginia_page_identity(page, level="section") == "8-29B-8A"
    row = scraper._parse_west_virginia_section_payload(
        code_name="West Virginia Code",
        source_url="https://code.wvlegislature.gov/8-29-8A/",
        section_number="8-29B-8A",
        payload=page,
        discovery_method="test",
        observed_on=date(2026, 8, 30),
    )
    assert row is not None
    assert row.section_number == "8-29B-8A"
    assert "abandoned or derelict aircraft" in (row.full_text or "").lower()


def test_west_virginia_intra_article_alias_prefers_printed_href() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    payload = (
        "<html><body>"
        "<div class='art-head'>ARTICLE 5. HOSPITALS.</div>"
        "<div class='sec-head'><a href='/16B-5-16A/'>§16B-5-16. Duplicate alias.</a></div>"
        "<div class='sec-head'><a href='/16B-5-16/'>§16B-5-16. Canonical row.</a></div>"
        "</body></html>"
    ).encode("utf-8")
    units = scraper._west_virginia_child_units(
        payload,
        level="section",
        chapter_number="16B",
        article_number="5",
    )
    assert [row["source_url"] for row in units] == [
        "https://code.wvlegislature.gov/16B-5-16/"
    ]
    assert units[0]["section"] == "16"


def test_west_virginia_cross_article_alias_prefers_printed_href() -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    section_units: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    alias = {
        "article": "5P",
        "chapter": "16",
        "section": "15",
        "source_label": "§16-5P-15. Establishment of In-home Care Registry.",
        "source_url": "https://code.wvlegislature.gov/16-5O-15/",
    }
    canonical = {
        **alias,
        "source_url": "https://code.wvlegislature.gov/16-5P-15/",
    }
    scraper._west_virginia_record_section_unit(
        alias, section_units=section_units, seen_sections=seen
    )
    scraper._west_virginia_record_section_unit(
        canonical, section_units=section_units, seen_sections=seen
    )
    assert [row["source_url"] for row in section_units] == [
        "https://code.wvlegislature.gov/16-5P-15/"
    ]
    scraper._west_virginia_record_section_unit(
        alias, section_units=section_units, seen_sections=seen
    )
    assert [row["source_url"] for row in section_units] == [
        "https://code.wvlegislature.gov/16-5P-15/"
    ]


def test_west_virginia_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    chapter_urls = _official_chapter_urls()
    residual = [CURRENT_ROOT, *chapter_urls]
    assert len(residual) == RESIDUAL_COUNT
    residual_digest = _canonical_residual_sha256(residual)
    chapter_digest = _canonical_residual_sha256(chapter_urls)
    assert residual_digest == hashlib.sha256(
        json.dumps(residual, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert len(residual_digest) == 64
    assert len(chapter_digest) == 64
    assert residual_digest != chapter_digest
    assert not residual_digest.startswith(RESIDUAL_SHA256_PREFIX)
    compact = [CURRENT_ROOT, CHAPTER_01, CHAPTER_05A]
    compact_digest = _canonical_residual_sha256(compact)
    assert not compact_digest.startswith(RESIDUAL_SHA256_PREFIX)
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert ROOT_WAVE_NAME in report
    assert CHAPTER_WAVE_NAME in report
    assert ARTICLE_WAVE_NAME in report
    assert SECTION_WAVE_PREFIX in report
    assert DIAGNOSTIC_CHAPTER_URL_SHA256_PREFIX in report


def test_west_virginia_one_domain_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(
        WestVirginiaScraper._fetch_west_virginia_frontier_batch
    )
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,)" in fetch_source
    assert "self.OFFICIAL_DOMAIN" in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "repeat_grouped_archive_inventory_on_residual=True" not in fetch_source
    assert fetch_source.count("common_crawl_domain_terms") == 1
    assert "_fetch_page_contents_with_archival_fallback_retrying_residuals" in (
        fetch_source
    )

    retry_source = inspect.getsource(
        BaseStateScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        WestVirginiaScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"residual_only_retries": True' in closure_source
    assert '"wayback_prefix_inventory": True' in closure_source
    assert '"retained_replay_network_requested_pages": replay_network' in (
        closure_source
    )

    strict = inspect.getsource(WestVirginiaScraper._scrape_strict_full_corpus_frontier)
    assert "_fetch_page_content_with_archival_fallback(" not in strict
    assert "_fetch_west_virginia_frontier_batch" in strict


def test_west_virginia_seed_and_host_replay_forbid_hub_docker_and_absent_staging(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "WV",
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
    assert "staging-wv-v1" in report
    assert "full-acquisition-evidence-v20-wv-v1" in report
    assert "catalog descriptions" in report
    assert "source-recovery" in report or "source recovery" in report


def test_west_virginia_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    west_virginia_source = inspect.getsource(
        WestVirginiaScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in closure_source
    assert "public_law_no_state_copyright" in west_virginia_source
    assert "replay_network != 0" in west_virginia_source
    assert '"retained_replay_network_requested_pages": replay_network' in (
        west_virginia_source
    )
    assert "retained_only=True" in west_virginia_source
    assert "West Virginia first and replayed exact frontiers differ" in (
        west_virginia_source
    )
    assert "_scrape_strict_full_corpus_frontier" in west_virginia_source


def test_west_virginia_legacy_insecure_tls_helper_cannot_authorize_strict_acquisition() -> None:
    helper = inspect.getsource(WestVirginiaScraper._official_http_get)
    assert "ssl._create_unverified_context" in helper
    strict = inspect.getsource(WestVirginiaScraper._scrape_strict_full_corpus_frontier)
    fetch_source = inspect.getsource(
        WestVirginiaScraper._fetch_west_virginia_frontier_batch
    )
    assert "_official_http_get" not in strict
    assert "_official_http_get" not in fetch_source
    assert "ssl._create_unverified_context" not in strict
    assert "ssl._create_unverified_context" not in fetch_source
    table = _report_table(_report_text())
    assert table["legacy_insecure_tls_authorizing"] == "forbidden"
    assert "tls" in " ".join(_report_text().casefold().split())


def test_west_virginia_compact_root_plus_chapter_recipe_fetches_root_before_chapters_and_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _compact_current_root_pages()
    # Compact root HTML intentionally includes obsolete 48A so the recipe can
    # prove it is not requested. Catalog parity uses only COMPACT_CHAPTERS, so
    # rebuild the root without extras for the successful traversal.
    pages[CURRENT_ROOT] = _compact_root_html(*COMPACT_CHAPTERS)
    derived_chapters = _source_ordered_chapters(pages[CURRENT_ROOT])
    assert derived_chapters == [CHAPTER_01, CHAPTER_05A]
    assert INVENTED_CHAPTER_48A not in derived_chapters
    assert CONSTITUTION_URL not in derived_chapters
    digest = _canonical_residual_sha256([CURRENT_ROOT, *derived_chapters])
    assert not digest.startswith(RESIDUAL_SHA256_PREFIX)

    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        retained_only: bool = False,
    ) -> list[bytes]:
        del self, retained_only
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return [pages[url] for url in requested]

    async def _singleton_must_not_run(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError(
            "West Virginia root-plus-chapter residual must remain a plural wave"
        )

    def _legacy_tls_must_not_run(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError(
            "West Virginia strict residual must not use the legacy TLS-bypass seam"
        )

    monkeypatch.setattr(
        WestVirginiaScraper, "_fetch_west_virginia_frontier_batch", _batch
    )
    monkeypatch.setattr(
        WestVirginiaScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton_must_not_run,
    )
    monkeypatch.setattr(
        WestVirginiaScraper, "_official_http_get", _legacy_tls_must_not_run
    )
    monkeypatch.setattr(
        WestVirginiaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = WestVirginiaScraper("WV", "West Virginia")
    monkeypatch.setattr(scraper, "OFFICIAL_CHAPTERS", COMPACT_CHAPTERS)
    monkeypatch.setattr(scraper, "OFFICIAL_CHAPTER_COUNT", 2)

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "West Virginia Code",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    wave_names = [name for name, _urls in batch_calls]
    assert wave_names.index(ROOT_WAVE_NAME) < wave_names.index(CHAPTER_WAVE_NAME)
    assert wave_names.index(CHAPTER_WAVE_NAME) < wave_names.index(ARTICLE_WAVE_NAME)
    assert batch_calls[0] == (ROOT_WAVE_NAME, [CURRENT_ROOT])
    assert batch_calls[1] == (CHAPTER_WAVE_NAME, [CHAPTER_01, CHAPTER_05A])
    assert batch_calls[2] == (ARTICLE_WAVE_NAME, [ARTICLE_01, ARTICLE_05A])
    assert INVENTED_CHAPTER_48A not in batch_calls[1][1]
    assert CONSTITUTION_URL not in batch_calls[0][1]
    assert CONSTITUTION_URL not in batch_calls[1][1]
    requested_urls = [url for _name, urls in batch_calls for url in urls]
    assert INVENTED_CHAPTER_48A not in requested_urls
    assert CONSTITUTION_URL not in requested_urls
    assert SINGLETON_61_2_1 not in requested_urls
    assert wave_names.count(ROOT_WAVE_NAME) == 1
    assert wave_names.count(CHAPTER_WAVE_NAME) == 1
    assert wave_names.count(ARTICLE_WAVE_NAME) == 1
    assert any(name.startswith(SECTION_WAVE_PREFIX) for name in wave_names)
    assert [row.source_url for row in rows] == [SECTION_01, SECTION_05A]
    frontier = scraper._last_west_virginia_full_frontier["frontier"]
    assert frontier["closed"] is True
    assert frontier["chapter_count"] == 2
    assert frontier["catalog_parity"] is True


def test_west_virginia_invented_or_obsolete_chapter_is_not_admitted_from_current_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _compact_current_root_pages()
    extra_root = _compact_root_html(
        *COMPACT_CHAPTERS,
        extra=(
            "<option value='48A'>CHAPTER 48A. Enforcement of Family "
            "Obligations</option>"
        ),
    )
    derived = _source_ordered_chapters(_compact_root_html(*COMPACT_CHAPTERS))
    assert derived == [CHAPTER_01, CHAPTER_05A]
    assert INVENTED_CHAPTER_48A not in derived

    extra_derived = _source_ordered_chapters(extra_root)
    assert INVENTED_CHAPTER_48A in extra_derived

    pages[CURRENT_ROOT] = extra_root
    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        retained_only: bool = False,
    ) -> list[bytes]:
        del self, retained_only
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return [pages[url] for url in requested]

    monkeypatch.setattr(
        WestVirginiaScraper, "_fetch_west_virginia_frontier_batch", _batch
    )
    monkeypatch.setattr(
        WestVirginiaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    scraper = WestVirginiaScraper("WV", "West Virginia")
    monkeypatch.setattr(scraper, "OFFICIAL_CHAPTERS", COMPACT_CHAPTERS)
    monkeypatch.setattr(scraper, "OFFICIAL_CHAPTER_COUNT", 2)

    with pytest.raises(RuntimeError, match="catalog parity failed"):
        asyncio.run(
            scraper._scrape_strict_full_corpus_frontier(
                "West Virginia Code",
                record_primary=True,
                write_checkpoints=False,
            )
        )

    assert batch_calls[0] == (ROOT_WAVE_NAME, [CURRENT_ROOT])
    chapter_waves = [
        urls for name, urls in batch_calls if name == CHAPTER_WAVE_NAME
    ]
    assert chapter_waves == []


def test_west_virginia_retained_replay_only_miss_does_not_open_per_page_archive_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_source = inspect.getsource(
        WestVirginiaScraper._fetch_west_virginia_frontier_batch
    )
    strict = inspect.getsource(WestVirginiaScraper._scrape_strict_full_corpus_frontier)
    assert "_fetch_page_contents_with_archival_fallback_retrying_residuals" in (
        fetch_source
    )
    assert "_fetch_page_content_with_archival_fallback(" not in strict
    assert "for chapter_url in" not in strict

    singleton_calls: list[str] = []

    async def _singleton(self, url: str, timeout_seconds: int = 25) -> bytes:
        del self, timeout_seconds
        singleton_calls.append(url)
        raise AssertionError(
            "West Virginia residual must not open a per-page archive loop"
        )

    pages = _compact_current_root_pages()
    pages[CURRENT_ROOT] = _compact_root_html(*COMPACT_CHAPTERS)
    batch_calls: list[list[str]] = []

    async def _plain_batch(
        self,
        urls,
        *,
        frontier_name: str,
        retained_only: bool = False,
    ) -> list[bytes]:
        del self, frontier_name, retained_only
        requested = list(urls)
        batch_calls.append(requested)
        return [pages[url] for url in requested]

    monkeypatch.setattr(
        WestVirginiaScraper, "_fetch_west_virginia_frontier_batch", _plain_batch
    )
    monkeypatch.setattr(
        WestVirginiaScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton,
    )
    monkeypatch.setattr(
        WestVirginiaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    scraper = WestVirginiaScraper("WV", "West Virginia")
    monkeypatch.setattr(scraper, "OFFICIAL_CHAPTERS", COMPACT_CHAPTERS)
    monkeypatch.setattr(scraper, "OFFICIAL_CHAPTER_COUNT", 2)

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "West Virginia Code",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert singleton_calls == []
    assert batch_calls[0] == [CURRENT_ROOT]
    assert INVENTED_CHAPTER_48A not in batch_calls[0]
    assert CONSTITUTION_URL not in batch_calls[0]
    assert [row.source_url for row in rows] == [SECTION_01, SECTION_05A]

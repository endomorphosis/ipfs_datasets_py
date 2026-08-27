"""LCR-097: Vermont fresh-root plus 46-title residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, importing the receiptless May generic
cache, resuming absent staging-vt-v1 roots, and admitting obsolete
repaired-static title identities.
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.vermont import (
    VermontScraper,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "vermont_residual_closure_v1.md"
)

OFFICIAL_DOMAIN = "legislature.vermont.gov"
CURRENT_ROOT = "https://legislature.vermont.gov/statutes/"
TITLE_01 = "https://legislature.vermont.gov/statutes/title/01"
TITLE_03APPENDIX = "https://legislature.vermont.gov/statutes/title/03APPENDIX"
TITLE_33 = "https://legislature.vermont.gov/statutes/title/33"
CHAPTER_01 = "https://legislature.vermont.gov/statutes/chapter/01/001"
CHAPTER_03APPENDIX = (
    "https://legislature.vermont.gov/statutes/chapter/03APPENDIX/001"
)
SUBCHAPTER_01 = "https://legislature.vermont.gov/statutes/subchapter/01/001/001"
SECTION_01 = "https://legislature.vermont.gov/statutes/section/01/001/00001"
SECTION_03APPENDIX = (
    "https://legislature.vermont.gov/statutes/section/03APPENDIX/001/00001"
)
INVENTED_TITLE_10A = "https://legislature.vermont.gov/statutes/title/10A"
INVENTED_TITLE_16A = "https://legislature.vermont.gov/statutes/title/16A"
INVENTED_TITLE_24A = "https://legislature.vermont.gov/statutes/title/24A"
CONSTITUTION_URL = "https://legislature.vermont.gov/statutes/constitution"
RETAINED_STRICT_PARSER_INPUTS = 0
RESIDUAL_COUNT = 47
TITLE_COUNT = 46
DIAGNOSTIC_ROOT_BYTES = 60954
DIAGNOSTIC_ROOT_SHA256 = (
    "108a4010a1a2ceb7e72d7051d902c812dabbed6efe62a36ee93bc553ab2468c9"
)
DIAGNOSTIC_TITLE_ID_SHA256 = (
    "2955d0d4679a05d164c8bfff9a3357cbd69db76dfe01c387cb15c5b42f928d56"
)
DIAGNOSTIC_TITLE_URL_SHA256 = (
    "c103bbe938a745dc394f9c337ed12145d90038f94e2a0bcbd7718a4eb81b4266"
)
MAY_CACHE_ENTRIES = 7438
MAY_CACHE_BYTES = 443382994
MAY_CACHE_TITLES = 12
MAY_CACHE_CHAPTERS = 491
MAY_CACHE_SECTIONS = 6934
MAY_CACHE_SHA_CONFLICTS = 129
CATALOG_FIRST_UNITS = 45
SOURCE_BUNDLE_PREFIX = "897c6c17ecb5"
RESIDUAL_SHA256_PREFIX = "fresh_root_plus_46_titles_legislature_vermont_gov"
DIAGNOSTIC_PRODUCER_PREFIX = "VermontScraper@sha256:897c6c17ecb5"
ROOT_WAVE_NAME = "root-index"
TITLE_WAVE_NAME = "title-index"
CHAPTER_WAVE_NAME = "chapter-index"
SUBCHAPTER_WAVE_NAME = "subchapter-index"
SECTION_WAVE_PREFIX = "sections-"
APPENDIX_TITLE_IDS = ("3APPENDIX", "10APPENDIX", "16APPENDIX", "24APPENDIX")
OBSOLETE_REPAIRED_IDS = ("10A", "16A", "24A")
FENCED_ABSENT_ROOTS = (
    "staging-vt-v1",
    "full-acquisition-evidence-v19-vt-v1",
)
COMPACT_TITLES = (
    ("1", "General Provisions"),
    ("3APPENDIX", "Executive Orders"),
)


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _section_page(*, title: str, text: str) -> bytes:
    return (
        "<html><head><title>Vermont Statutes</title></head><body>"
        "<ul class='item-list statutes-detail'><li>"
        f"<p><b>§ 1. {title}</b></p>"
        f"<p>{text}</p>"
        "</li></ul></body></html>"
    ).encode()


def _compact_root_html(*titles: tuple[str, str], extra: str = "") -> bytes:
    scraper = VermontScraper("VT", "Vermont")
    items = []
    for number, name in titles:
        slug = scraper.official_title_slug(number)
        items.append(
            f"<a href='/statutes/title/{slug}'>Title {number}: {name}</a>"
        )
    return (
        "<html><head><title>Vermont Statutes</title></head><body>"
        + "".join(items)
        + extra
        + "</body></html>"
    ).encode()


def _compact_current_root_pages() -> dict[str, bytes]:
    scraper = VermontScraper("VT", "Vermont")
    title_1 = scraper.official_title_url("1")
    title_3appendix = scraper.official_title_url("3APPENDIX")
    return {
        CURRENT_ROOT: _compact_root_html(
            *COMPACT_TITLES,
            extra=(
                f"<a href='/statutes/constitution'>Vermont Constitution</a>"
                f"<a href='{INVENTED_TITLE_10A}'>Title 10A: Obsolete Repair</a>"
            ),
        ),
        title_1: (
            "<html><head><title>Vermont Statutes</title></head><body>"
            "<a href='/statutes/chapter/01/001'>Chapter 001: Test</a>"
            "</body></html>"
        ).encode(),
        title_3appendix: (
            "<html><head><title>Vermont Statutes</title></head><body>"
            "<a href='/statutes/chapter/03APPENDIX/001'>Chapter 001: Test</a>"
            "</body></html>"
        ).encode(),
        CHAPTER_01: (
            "<html><head><title>Vermont Statutes</title></head><body>"
            "<a href='/statutes/section/01/001/00001'>§ 1. Test</a>"
            "</body></html>"
        ).encode(),
        CHAPTER_03APPENDIX: (
            "<html><head><title>Vermont Statutes</title></head><body>"
            "<a href='/statutes/section/03APPENDIX/001/00001'>§ 1. Test</a>"
            "</body></html>"
        ).encode(),
        SUBCHAPTER_01: (
            "<html><head><title>Vermont Statutes</title></head><body>"
            "<a href='/statutes/section/01/001/00001'>§ 1. Test</a>"
            "</body></html>"
        ).encode(),
        SECTION_01: _section_page(
            title="Synthetic operative section",
            text=(
                "This Vermont statute supplies operative synthetic legal text "
                "for exact offline residual testing and contains enough words "
                "to parse."
            ),
        ),
        SECTION_03APPENDIX: _section_page(
            title="Executive order operative section",
            text=(
                "This Vermont executive-order statute supplies operative "
                "synthetic legal text for exact offline residual testing."
            ),
        ),
        INVENTED_TITLE_10A: (
            "<html><head><title>Vermont Statutes</title></head><body>"
            "<a href='/statutes/chapter/10A/001'>Chapter 001: Invented</a>"
            "</body></html>"
        ).encode(),
        CONSTITUTION_URL: (
            "<html><head><title>Vermont Constitution</title></head><body>"
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
        raise AssertionError("Vermont residual closure report is empty")
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


def _source_ordered_titles(root_html: bytes) -> list[str]:
    scraper = VermontScraper("VT", "Vermont")
    units = scraper._vermont_hierarchy_units(root_html, level="title")
    urls = [str(unit["source_url"]) for unit in units]
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            raise AssertionError(
                "Vermont current-root title frontier repeated a URL"
            )
        seen.add(url)
    return urls


def _official_title_urls() -> list[str]:
    scraper = VermontScraper("VT", "Vermont")
    return [scraper.official_title_url(number) for number, _name in scraper.OFFICIAL_TITLES]


def test_vermont_residual_closure_report_records_exact_fresh_root_and_title_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "VT"
    assert table["official domain"] == OFFICIAL_DOMAIN
    assert table["official entry"] == CURRENT_ROOT
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == (
        "official HTML tree root → title → chapter → optional "
        "subchapter/article → section"
    )
    assert table["seed"] == (
        "zero authorizing current-ledger inputs; start from absent "
        "staging-vt-v1 and full-acquisition-evidence-v19-vt-v1"
    )
    assert table["start_from_absent_staging_roots"] == "true"
    assert table["resume_staging_vt_v1"] == "forbidden"
    assert table["resume_full_acquisition_evidence_v19_vt_v1"] == "forbidden"
    assert table["import_may_generic_cache"] == "forbidden"
    assert table["import_catalog_first_repaired_json"] == "forbidden"
    assert table["legacy_insecure_tls_authorizing"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["invent_later_title_targets"] == "forbidden"
    assert table["obsolete_repaired_title_ids"] == "10A, 16A, 24A forbidden"
    assert table["per_page_archive_loop"] == "false"
    assert table["retained_strict_parser_inputs"] == str(
        RETAINED_STRICT_PARSER_INPUTS
    )
    assert table["diagnostic_root_bytes"] == str(DIAGNOSTIC_ROOT_BYTES)
    assert table["diagnostic_root_sha256"] == DIAGNOSTIC_ROOT_SHA256
    assert table["diagnostic_root_authorizing"] == "false"
    assert table["diagnostic_title_count"] == str(TITLE_COUNT)
    assert table["diagnostic_title_id_sha256"] == DIAGNOSTIC_TITLE_ID_SHA256
    assert table["diagnostic_title_url_sha256"] == DIAGNOSTIC_TITLE_URL_SHA256
    assert table["catalog_first_reported_units"] == str(CATALOG_FIRST_UNITS)
    assert table["catalog_first_bundle_closed"] == "false"
    assert table["catalog_first_authorizing"] == "false"
    assert table["may_cache_entries"] == str(MAY_CACHE_ENTRIES)
    assert table["may_cache_bytes"] == str(MAY_CACHE_BYTES)
    assert table["may_cache_title_pages"] == str(MAY_CACHE_TITLES)
    assert table["may_cache_chapter_pages"] == str(MAY_CACHE_CHAPTERS)
    assert table["may_cache_section_pages"] == str(MAY_CACHE_SECTIONS)
    assert table["may_cache_sha_conflicts"] == str(MAY_CACHE_SHA_CONFLICTS)
    assert table["may_cache_transport_evidence"] == "absent"
    assert table["may_cache_authorizing"] == "false"
    assert table["appendix_title_ids"] == ", ".join(APPENDIX_TITLE_IDS)
    assert table["constitution_in_corpus"] == "false"
    assert table["regulations_in_corpus"] == "false"
    assert table["court_rules_in_corpus"] == "false"
    assert table["title_membership_count"] == str(TITLE_COUNT)
    assert table["chapter_membership_count"] == "source_dependent_after_46_titles"
    assert table["subchapter_membership_count"] == (
        "source_dependent_after_46_titles"
    )
    assert table["section_membership_count"] == "source_dependent_after_46_titles"
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_floor"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == "fresh official root plus 46 source-ordered titles"
    assert table["residual_first_url"] == CURRENT_ROOT
    assert table["residual_first_title_url"] == TITLE_01
    assert table["residual_last_title_url"] == TITLE_33
    assert table["residual_wave_name"] == ROOT_WAVE_NAME
    assert table["title_wave_name"] == TITLE_WAVE_NAME
    assert table["chapter_wave_name"] == CHAPTER_WAVE_NAME
    assert table["subchapter_wave_name"] == SUBCHAPTER_WAVE_NAME
    assert table["section_wave_name_prefix"] == SECTION_WAVE_PREFIX
    assert table["root_acquisition_wave_count"] == "1"
    assert table["title_acquisition_wave_count"] == "1"
    assert table["fetch_root_before_titles"] == "true"
    assert table["fetch_titles_before_chapters"] == "true"
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
    assert RETAINED_STRICT_PARSER_INPUTS + RESIDUAL_COUNT == 47
    assert int(table["diagnostic_title_count"]) + 1 == RESIDUAL_COUNT
    assert (
        int(table["may_cache_root_pages"])
        + int(table["may_cache_title_pages"])
        + int(table["may_cache_chapter_pages"])
        + int(table["may_cache_section_pages"])
        == MAY_CACHE_ENTRIES
    )

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "fresh" in lowered and "46" in report
    assert "hub mutation" in lowered
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "may generic cache" in lowered or "may legacy cache" in lowered
    assert "insecure-tls" in lowered or "insecure tls" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert CURRENT_ROOT in report
    assert TITLE_01 in report
    assert TITLE_33 in report
    assert TITLE_03APPENDIX in report
    assert DIAGNOSTIC_ROOT_SHA256 in report
    assert DIAGNOSTIC_TITLE_URL_SHA256 in report
    assert INVENTED_TITLE_10A not in report
    assert INVENTED_TITLE_16A not in report
    assert INVENTED_TITLE_24A not in report
    assert CONSTITUTION_URL not in report
    assert report.count("/statutes/title/") < 10
    assert "source_dependent_after_46_titles" in report
    for fenced in FENCED_ABSENT_ROOTS:
        assert fenced in report


def test_vermont_root_and_titles_are_source_derived_and_not_may_cache() -> None:
    scraper = VermontScraper("VT", "Vermont")
    assert scraper.get_base_url() == f"https://{OFFICIAL_DOMAIN}"
    assert scraper.OFFICIAL_DOMAIN == OFFICIAL_DOMAIN
    assert scraper.OFFICIAL_ENTRY_URL == CURRENT_ROOT
    assert scraper.get_code_list()[0]["url"] == CURRENT_ROOT
    assert scraper.official_title_url("1") == TITLE_01
    assert scraper.official_title_url("3APPENDIX") == TITLE_03APPENDIX
    assert scraper.official_title_url("33") == TITLE_33
    assert scraper.OFFICIAL_TITLE_COUNT == TITLE_COUNT
    assert len(scraper.OFFICIAL_TITLES) == TITLE_COUNT

    numbers = [number for number, _name in scraper.OFFICIAL_TITLES]
    assert numbers[0] == "1"
    assert numbers[-1] == "33"
    for appendix in APPENDIX_TITLE_IDS:
        assert appendix in numbers
    for obsolete in OBSOLETE_REPAIRED_IDS:
        assert obsolete not in numbers

    title_urls = _official_title_urls()
    assert title_urls[0] == TITLE_01
    assert title_urls[-1] == TITLE_33
    assert TITLE_03APPENDIX in title_urls
    assert INVENTED_TITLE_10A not in title_urls
    assert len(title_urls) == TITLE_COUNT

    compact_root = _compact_root_html(*COMPACT_TITLES)
    derived = _source_ordered_titles(compact_root)
    assert derived == [TITLE_01, TITLE_03APPENDIX]
    assert INVENTED_TITLE_10A not in derived
    assert CONSTITUTION_URL not in derived

    strict = inspect.getsource(VermontScraper._scrape_strict_full_corpus_frontier)
    assert f'frontier_name="{ROOT_WAVE_NAME}"' in strict
    assert f'frontier_name="{TITLE_WAVE_NAME}"' in strict
    assert f'frontier_name="{CHAPTER_WAVE_NAME}"' in strict
    assert f'frontier_name="{SUBCHAPTER_WAVE_NAME}"' in strict
    assert f'"{SECTION_WAVE_PREFIX}' in strict or "sections-" in strict
    assert strict.index(f'frontier_name="{ROOT_WAVE_NAME}"') < strict.index(
        f'frontier_name="{TITLE_WAVE_NAME}"'
    )
    assert strict.index(f'frontier_name="{TITLE_WAVE_NAME}"') < strict.index(
        f'frontier_name="{CHAPTER_WAVE_NAME}"'
    )
    assert "[self.OFFICIAL_ENTRY_URL]" in strict
    assert "_official_http_get" not in strict
    assert "ssl._create_unverified_context" not in strict
    assert INVENTED_TITLE_10A not in strict
    assert "web.archive.org" not in strict


def test_vermont_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(VermontScraper)
    fetch_source = inspect.getsource(VermontScraper._fetch_vermont_frontier_batch)
    strict = inspect.getsource(VermontScraper._scrape_strict_full_corpus_frontier)
    assert str(MAY_CACHE_ENTRIES) not in adapter
    assert str(MAY_CACHE_BYTES) not in adapter
    assert str(DIAGNOSTIC_ROOT_BYTES) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert DIAGNOSTIC_TITLE_URL_SHA256 not in adapter
    assert DIAGNOSTIC_ROOT_SHA256 not in adapter
    for fenced in FENCED_ABSENT_ROOTS:
        assert fenced not in adapter
    for invented in (INVENTED_TITLE_10A, INVENTED_TITLE_16A, INVENTED_TITLE_24A):
        assert invented not in adapter
        assert invented not in strict
        assert invented not in fetch_source
    obsolete_literals = re.findall(
        r"/statutes/title/1[06]A(?!PPENDIX)|/statutes/title/24A(?!PPENDIX)",
        adapter,
    )
    assert obsolete_literals == []
    assert '[unit["source_url"] for unit in title_units]' in strict
    assert "[self.OFFICIAL_ENTRY_URL]" in strict


def test_vermont_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    title_urls = _official_title_urls()
    residual = [CURRENT_ROOT, *title_urls]
    assert len(residual) == RESIDUAL_COUNT
    residual_digest = _canonical_residual_sha256(residual)
    title_digest = _canonical_residual_sha256(title_urls)
    assert residual_digest == hashlib.sha256(
        json.dumps(residual, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert len(residual_digest) == 64
    assert len(title_digest) == 64
    assert residual_digest != title_digest
    assert not residual_digest.startswith(RESIDUAL_SHA256_PREFIX)
    compact = [CURRENT_ROOT, TITLE_01, TITLE_03APPENDIX]
    compact_digest = _canonical_residual_sha256(compact)
    assert not compact_digest.startswith(RESIDUAL_SHA256_PREFIX)
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert ROOT_WAVE_NAME in report
    assert TITLE_WAVE_NAME in report
    assert CHAPTER_WAVE_NAME in report
    assert SECTION_WAVE_PREFIX in report
    assert DIAGNOSTIC_TITLE_URL_SHA256 in report


def test_vermont_one_domain_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(VermontScraper._fetch_vermont_frontier_batch)
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert "wayback_prefix_inventory=True" in fetch_source
    assert 'common_crawl_url_terms=("/statutes/",)' in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "self.OFFICIAL_DOMAIN" in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "title/{id}" not in fetch_source
    assert fetch_source.count("common_crawl_url_terms") == 1

    retry_source = inspect.getsource(
        BaseStateScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        VermontScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"residual_only_retries": True' in closure_source
    assert '"retained_replay_network_requested_pages": replay_network' in (
        closure_source
    )

    strict = inspect.getsource(VermontScraper._scrape_strict_full_corpus_frontier)
    assert "_fetch_page_content_with_archival_fallback(" not in strict
    assert "_fetch_vermont_frontier_batch" in strict


def test_vermont_seed_and_host_replay_forbid_hub_docker_and_absent_staging(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "VT",
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
    assert "staging-vt-v1" in report
    assert "full-acquisition-evidence-v19-vt-v1" in report
    assert "may generic cache" in report or "may legacy cache" in report


def test_vermont_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    vermont_source = inspect.getsource(
        VermontScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in closure_source
    assert "public_law_no_state_copyright" in vermont_source
    assert "replay_network != 0" in vermont_source
    assert '"retained_replay_network_requested_pages": replay_network' in (
        vermont_source
    )
    assert "retained_only=True" in vermont_source
    assert "Vermont first and replayed exact frontiers differ" in vermont_source
    assert "_scrape_strict_full_corpus_frontier" in vermont_source


def test_vermont_legacy_insecure_tls_helper_cannot_authorize_strict_acquisition() -> None:
    helper = inspect.getsource(VermontScraper._official_http_get)
    assert "ssl._create_unverified_context" in helper
    strict = inspect.getsource(VermontScraper._scrape_strict_full_corpus_frontier)
    fetch_source = inspect.getsource(VermontScraper._fetch_vermont_frontier_batch)
    assert "_official_http_get" not in strict
    assert "_official_http_get" not in fetch_source
    assert "ssl._create_unverified_context" not in strict
    assert "ssl._create_unverified_context" not in fetch_source
    table = _report_table(_report_text())
    assert table["legacy_insecure_tls_authorizing"] == "forbidden"
    assert "tls" in " ".join(_report_text().casefold().split())


def test_vermont_compact_root_plus_title_recipe_fetches_root_before_titles_and_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _compact_current_root_pages()
    # Compact root HTML intentionally includes a constitution link and an
    # obsolete 10A locator so the recipe can prove they are not requested.
    # Catalog parity uses only COMPACT_TITLES, so rebuild the root without
    # extras for the successful traversal.
    pages[CURRENT_ROOT] = _compact_root_html(*COMPACT_TITLES)
    derived_titles = _source_ordered_titles(pages[CURRENT_ROOT])
    assert derived_titles == [TITLE_01, TITLE_03APPENDIX]
    assert INVENTED_TITLE_10A not in derived_titles
    assert CONSTITUTION_URL not in derived_titles
    digest = _canonical_residual_sha256([CURRENT_ROOT, *derived_titles])
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
            "Vermont root-plus-title residual must remain a plural wave"
        )

    def _legacy_tls_must_not_run(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError(
            "Vermont strict residual must not use the legacy TLS-bypass seam"
        )

    monkeypatch.setattr(VermontScraper, "_fetch_vermont_frontier_batch", _batch)
    monkeypatch.setattr(
        VermontScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton_must_not_run,
    )
    monkeypatch.setattr(VermontScraper, "_official_http_get", _legacy_tls_must_not_run)
    monkeypatch.setattr(
        VermontScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = VermontScraper("VT", "Vermont")
    monkeypatch.setattr(scraper, "OFFICIAL_TITLES", COMPACT_TITLES)
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 2)

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "Vermont Statutes",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    wave_names = [name for name, _urls in batch_calls]
    assert wave_names.index(ROOT_WAVE_NAME) < wave_names.index(TITLE_WAVE_NAME)
    assert wave_names.index(TITLE_WAVE_NAME) < wave_names.index(CHAPTER_WAVE_NAME)
    assert batch_calls[0] == (ROOT_WAVE_NAME, [CURRENT_ROOT])
    assert batch_calls[1] == (TITLE_WAVE_NAME, [TITLE_01, TITLE_03APPENDIX])
    assert batch_calls[2] == (
        CHAPTER_WAVE_NAME,
        [CHAPTER_01, CHAPTER_03APPENDIX],
    )
    assert INVENTED_TITLE_10A not in batch_calls[1][1]
    assert CONSTITUTION_URL not in batch_calls[0][1]
    assert CONSTITUTION_URL not in batch_calls[1][1]
    requested_urls = [url for _name, urls in batch_calls for url in urls]
    assert INVENTED_TITLE_10A not in requested_urls
    assert CONSTITUTION_URL not in requested_urls
    assert SUBCHAPTER_01 not in requested_urls
    assert wave_names.count(ROOT_WAVE_NAME) == 1
    assert wave_names.count(TITLE_WAVE_NAME) == 1
    assert SUBCHAPTER_WAVE_NAME not in wave_names
    assert any(name.startswith(SECTION_WAVE_PREFIX) for name in wave_names)
    assert [row.source_url for row in rows] == [SECTION_01, SECTION_03APPENDIX]
    frontier = scraper._last_vermont_full_frontier["frontier"]
    assert frontier["closed"] is True
    assert frontier["title_count"] == 2
    assert frontier["title_pages_fetched"] == 2
    assert frontier["catalog_parity"] is True


def test_vermont_invented_or_obsolete_title_is_not_admitted_from_current_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _compact_current_root_pages()
    extra_root = _compact_root_html(
        *COMPACT_TITLES,
        extra=(
            "<a href='/statutes/title/10A'>Title 10A: Obsolete Repair</a>"
        ),
    )
    derived = _source_ordered_titles(_compact_root_html(*COMPACT_TITLES))
    assert derived == [TITLE_01, TITLE_03APPENDIX]
    assert INVENTED_TITLE_10A not in derived

    extra_derived = _source_ordered_titles(extra_root)
    assert INVENTED_TITLE_10A in extra_derived

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

    monkeypatch.setattr(VermontScraper, "_fetch_vermont_frontier_batch", _batch)
    monkeypatch.setattr(
        VermontScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    scraper = VermontScraper("VT", "Vermont")
    monkeypatch.setattr(scraper, "OFFICIAL_TITLES", COMPACT_TITLES)
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 2)

    with pytest.raises(RuntimeError, match="catalog parity failed"):
        asyncio.run(
            scraper._scrape_strict_full_corpus_frontier(
                "Vermont Statutes",
                record_primary=True,
                write_checkpoints=False,
            )
        )

    assert batch_calls[0] == (ROOT_WAVE_NAME, [CURRENT_ROOT])
    title_waves = [urls for name, urls in batch_calls if name == TITLE_WAVE_NAME]
    assert title_waves == []


def test_vermont_retained_replay_only_miss_does_not_open_per_page_archive_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_source = inspect.getsource(VermontScraper._fetch_vermont_frontier_batch)
    strict = inspect.getsource(VermontScraper._scrape_strict_full_corpus_frontier)
    assert "_fetch_page_contents_with_archival_fallback_retrying_residuals" in (
        fetch_source
    )
    assert "_fetch_page_content_with_archival_fallback(" not in strict
    assert "for title_url in" not in strict

    singleton_calls: list[str] = []

    async def _singleton(self, url: str, timeout_seconds: int = 25) -> bytes:
        del self, timeout_seconds
        singleton_calls.append(url)
        raise AssertionError(
            "Vermont residual must not open a per-page archive loop"
        )

    pages = _compact_current_root_pages()
    pages[CURRENT_ROOT] = _compact_root_html(*COMPACT_TITLES)
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

    monkeypatch.setattr(VermontScraper, "_fetch_vermont_frontier_batch", _plain_batch)
    monkeypatch.setattr(
        VermontScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton,
    )
    monkeypatch.setattr(
        VermontScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    scraper = VermontScraper("VT", "Vermont")
    monkeypatch.setattr(scraper, "OFFICIAL_TITLES", COMPACT_TITLES)
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 2)

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "Vermont Statutes",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert singleton_calls == []
    assert batch_calls[0] == [CURRENT_ROOT]
    assert INVENTED_TITLE_10A not in batch_calls[0]
    assert CONSTITUTION_URL not in batch_calls[0]
    assert [row.source_url for row in rows] == [SECTION_01, SECTION_03APPENDIX]

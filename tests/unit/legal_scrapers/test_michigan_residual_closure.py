"""LCR-101: Michigan XML residual closure without repeating CDX.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, repeating CDX for already selected
captures, the repaired 238-item diagnostic, and the capped 160-row corpus.
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan import (
    MichiganScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan_chapter_xml import (
    chapter_index_links,
    chapter_xml_url,
    parse_michigan_chapter_xml_closure,
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
    / "michigan_residual_closure_v1.md"
)

OFFICIAL_DOMAIN = "www.legislature.mi.gov"
OFFICIAL_ENTRY = "https://www.legislature.mi.gov/Laws/ChapterIndex"
OFFICIAL_XML_LOCATOR = (
    "https://www.legislature.mi.gov/documents/mcl/Chapter%20{N}.xml"
)
FIRST_XML_URL = "https://www.legislature.mi.gov/documents/mcl/Chapter%201.xml"
LAST_XML_URL = "https://www.legislature.mi.gov/documents/mcl/Chapter%20830.xml"
INVENTED_XML_URL = (
    "https://www.legislature.mi.gov/documents/mcl/Chapter%20999.xml"
)
REPAIRED_ONLY_XML_URL = (
    "https://www.legislature.mi.gov/documents/mcl/Chapter%2056.xml"
)
OFFICIAL_SOURCE_CHAPTERS = 227
REPAIRED_CATALOG_CHAPTERS = 238
CURRENT_ABSENT_FROM_REPAIRED = 45
REPAIRED_OMITTED_FROM_CURRENT = 56
RETAINED_AUTHORIZING_INPUTS = 1
RESIDUAL_COUNT = 227
PARSER_INPUT_ALGEBRA = 228
V20_FETCHES = 1
V20_OBJECTS = 1
V20_ROOT_BYTES = 106815
V20_ROOT_SHA256 = (
    "7476e7e983fe27d4d4faf273e07b57c51f551ccb21d8517606252d39d6a53ed1"
)
V20_ROOT_SHA256_PREFIX = "7476e7e983fe"
V20_RECEIPT_SHA256_PREFIX = "1fa879de6f4a"
V20_ARCHIVE_TIMESTAMP = "20240405225438"
DIAGNOSTIC_LIVE_ROOT_BYTES = 93710
DIAGNOSTIC_LIVE_ROOT_SHA256_PREFIX = "74e42ab3a205"
CHAPTER_NUMBER_SHA256 = (
    "8d7a03038de2065508c2d7ccb5846caf6dafaef312a5121af0e924df89036884"
)
CHAPTER_NUMBER_SHA256_PREFIX = "8d7a03038de2"
XML_URL_ORDERED_SHA256 = (
    "5b39edd9cdd67ae513beed0ebcae3862dba3e1174aba6a788e5293610fbd5293"
)
RESIDUAL_SHA256_PREFIX = "5b39edd9cdd6"
SOURCE_BUNDLE_PREFIX = "42c02e83f84c"
CAPPED_160_JSONLD_PREFIX = "e68fbbae841d"
REPAIRED_DIAGNOSTIC_BODY_PREFIX = "ab3ca517d38d"
ROOT_WAVE_NAME = "chapter-index"
RESIDUAL_WAVE_NAME = "chapter-xml-1-227"
FENCED_STAGING_ROOTS = (
    "staging-mi-v1",
    "staging-mi-v2",
    "staging-mi-v3",
)
COMPACT_CHAPTERS = ("1", "2")


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _ordered_chapter_sha256(*chapters: str) -> str:
    return hashlib.sha256("\n".join(chapters).encode("utf-8")).hexdigest()


def _newline_xml_sha256(urls: list[str]) -> str:
    return hashlib.sha256("\n".join(urls).encode("utf-8")).hexdigest()


def _mi_xml(chapter: str, section: str, *, repealed: bool = False) -> bytes:
    catchline = "Expired. 2020, Act 1." if repealed else "Operative provision."
    body = "" if repealed else (
        "&lt;Section-Body&gt;&lt;P&gt;This Michigan provision supplies complete "
        "official statutory text for exact source reconciliation and indexing."
        "&lt;/P&gt;&lt;/Section-Body&gt;"
    )
    padding = "x" * 700
    return f"""<?xml version="1.0" encoding="utf-8"?>
    <MCLChapterInfo>
      <Name>{chapter}</Name><Title>Chapter {chapter}</Title>
      <Commentary>{padding}</Commentary>
      <MCLDocumentInfoCollection><MCLStatuteInfo>
        <Name>Act {chapter} of 2000</Name>
        <MCLDocumentInfoCollection><MCLSectionInfo>
          <MCLNumber>{section}</MCLNumber><CatchLine>{catchline}</CatchLine>
          <Repealed>{str(repealed).lower()}</Repealed><BodyText>{body}</BodyText>
        </MCLSectionInfo></MCLDocumentInfoCollection>
      </MCLStatuteInfo></MCLDocumentInfoCollection>
    </MCLChapterInfo>""".encode()


def _chapter_index_html(chapters: tuple[str, ...]) -> bytes:
    links = "".join(
        f"<a href='/Home/GetObject?objectName=mcl-chap{chapter}'>"
        f"Chapter {chapter}</a>"
        for chapter in chapters
    )
    return (
        "<html><head><title>MCL Chapter Index</title></head><body>"
        f"{links}"
        + (" " * 6_000)
        + "</body></html>"
    ).encode()


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


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Michigan residual closure report is empty")
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


def test_michigan_residual_closure_report_records_exact_xml_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "MI"
    assert table["official domain"] == OFFICIAL_DOMAIN
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_xml_locator"] == OFFICIAL_XML_LOCATOR
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == (
        "official chapter-index HTML then bulk chapter XML"
    )
    assert table["seed"] == (
        "one authorizing v20 root; 227 XML documents remain residual"
    )
    assert table["retain_v20_root"] == "true"
    assert table["resume_staging_mi_v1"] == "forbidden"
    assert table["resume_staging_mi_v2"] == "forbidden"
    assert table["resume_staging_mi_v3"] == "forbidden"
    assert table["import_repaired_238_diagnostic"] == "forbidden"
    assert table["import_capped_160_row_corpus"] == "forbidden"
    assert table["html_only_wayback_filter"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["invent_later_chapter_xml_targets"] == "forbidden"
    assert table["repeat_cdx_for_selected_captures"] == "forbidden"
    assert table["media_aware_inventory"] == "required"
    assert table["diagnostic_live_root_bytes"] == str(DIAGNOSTIC_LIVE_ROOT_BYTES)
    assert table["diagnostic_live_root_sha256_prefix"] == (
        DIAGNOSTIC_LIVE_ROOT_SHA256_PREFIX
    )
    assert table["diagnostic_live_root_authorizing"] == "false"
    assert table["official_source_chapters"] == str(OFFICIAL_SOURCE_CHAPTERS)
    assert table["repaired_catalog_chapters"] == str(REPAIRED_CATALOG_CHAPTERS)
    assert table["current_absent_from_repaired"] == str(
        CURRENT_ABSENT_FROM_REPAIRED
    )
    assert table["repaired_omitted_from_current"] == str(
        REPAIRED_OMITTED_FROM_CURRENT
    )
    assert table["chapter_number_sha256"] == CHAPTER_NUMBER_SHA256
    assert table["chapter_number_sha256_prefix"] == CHAPTER_NUMBER_SHA256_PREFIX
    assert table["xml_url_ordered_sha256"] == XML_URL_ORDERED_SHA256
    assert table["xml_url_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["v20_fetches"] == str(V20_FETCHES)
    assert table["v20_objects"] == str(V20_OBJECTS)
    assert table["v20_ledgers"] == "0"
    assert table["v20_frontiers"] == "0"
    assert table["v20_root_bytes"] == str(V20_ROOT_BYTES)
    assert table["v20_root_sha256"] == V20_ROOT_SHA256
    assert table["v20_root_sha256_prefix"] == V20_ROOT_SHA256_PREFIX
    assert table["v20_receipt_sha256_prefix"] == V20_RECEIPT_SHA256_PREFIX
    assert table["v20_source_transport"] == "wayback"
    assert table["v20_archive_timestamp"] == V20_ARCHIVE_TIMESTAMP
    assert table["retained_authorizing_inputs"] == str(
        RETAINED_AUTHORIZING_INPUTS
    )
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["parser_input_algebra"] == str(PARSER_INPUT_ALGEBRA)
    assert table["residual_kind"] == (
        "unique ordered official chapter XML URLs after retained v20 root"
    )
    assert table["residual_first_url"] == FIRST_XML_URL
    assert table["residual_last_url"] == LAST_XML_URL
    assert table["root_wave_name"] == ROOT_WAVE_NAME
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["root_acquisition_wave_count"] == "1"
    assert table["leaf_acquisition_wave_count"] == "1"
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["chapter_1_corpus_identity"] == "Michigan Constitution"
    assert table["sectionless_repealed_example_chapters"] == "340, 804"
    assert table["capped_160_row_jsonld_sha256_prefix"] == CAPPED_160_JSONLD_PREFIX
    assert table["repaired_diagnostic_body_sha256_prefix"] == (
        REPAIRED_DIAGNOSTIC_BODY_PREFIX
    )
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["diagnostic_hashes_authorizing"] == "false"
    assert table["source_bundle_prefix"] == SOURCE_BUNDLE_PREFIX
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert RETAINED_AUTHORIZING_INPUTS + RESIDUAL_COUNT == PARSER_INPUT_ALGEBRA
    assert (
        REPAIRED_CATALOG_CHAPTERS
        - REPAIRED_OMITTED_FROM_CURRENT
        + CURRENT_ABSENT_FROM_REPAIRED
        == OFFICIAL_SOURCE_CHAPTERS
    )

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "227" in report
    assert "hub mutation" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "repaired" in lowered and "238" in report
    assert "160-row" in lowered or "capped 160" in lowered
    assert "media-aware" in lowered or "media_aware" in lowered
    assert "docker-copying" in lowered or "docker-copy" in lowered
    assert "do not repeat cdx" in lowered or "repeat cdx" in lowered
    assert OFFICIAL_ENTRY in report
    assert FIRST_XML_URL in report
    assert LAST_XML_URL in report
    assert INVENTED_XML_URL not in report
    assert REPAIRED_ONLY_XML_URL not in report
    assert report.count("https://www.legislature.mi.gov/documents/mcl/Chapter%") < 8
    for fenced in FENCED_STAGING_ROOTS:
        assert fenced in report


def test_michigan_catalog_is_source_derived_xml_from_one_root() -> None:
    scraper = MichiganScraper("MI", "Michigan")
    assert scraper.get_base_url() == f"https://{OFFICIAL_DOMAIN}"
    assert scraper.OFFICIAL_ENTRY_URL == OFFICIAL_ENTRY
    assert scraper.OFFICIAL_DOMAIN == OFFICIAL_DOMAIN
    assert chapter_xml_url("1") == FIRST_XML_URL
    assert chapter_xml_url("830") == LAST_XML_URL
    assert len(scraper.OFFICIAL_CHAPTERS) == OFFICIAL_SOURCE_CHAPTERS
    assert _ordered_chapter_sha256(
        *(str(number) for number in scraper.OFFICIAL_CHAPTERS)
    ) == CHAPTER_NUMBER_SHA256

    catalog = chapter_index_links(
        _chapter_index_html(COMPACT_CHAPTERS).decode(),
        base_url=scraper.get_base_url(),
    )
    assert [row[0] for row in catalog] == list(COMPACT_CHAPTERS)

    index_source = inspect.getsource(
        MichiganScraper._scrape_official_chapter_index
    )
    xml_source = inspect.getsource(
        MichiganScraper._scrape_official_chapter_xml_frontier
    )
    catalog_rows_source = inspect.getsource(
        MichiganScraper._michigan_source_catalog_rows
    )
    scrape_source = inspect.getsource(MichiganScraper.scrape_code)
    assert "return await self._scrape_official_chapter_xml_frontier(code_name)" in (
        index_source
    )
    assert "_scrape_official_chapter_index" in scrape_source
    assert "_scrape_official_chapter_xml_frontier" not in scrape_source
    assert "_michigan_source_catalog_rows" in xml_source
    assert "chapter_index_links" in catalog_rows_source
    assert "chapter_xml_url" in xml_source
    assert 'frontier_name="chapter-index"' in xml_source
    assert 'frontier_name=f"chapter-xml-1-{len(xml_urls)}"' in xml_source
    assert "OFFICIAL_CHAPTERS" not in xml_source
    assert INVENTED_XML_URL not in xml_source
    assert REPAIRED_ONLY_XML_URL not in xml_source


def test_michigan_adapter_has_no_static_xml_residual_url_list() -> None:
    scraper_source = inspect.getsource(MichiganScraper)
    xml_module = inspect.getmodule(chapter_xml_url)
    assert xml_module is not None
    chapter_source = inspect.getsource(xml_module)
    xml_frontier = inspect.getsource(
        MichiganScraper._scrape_official_chapter_xml_frontier
    )
    for payload in (scraper_source, chapter_source, xml_frontier):
        assert INVENTED_XML_URL not in payload
        assert REPAIRED_ONLY_XML_URL not in payload
        assert RESIDUAL_SHA256_PREFIX not in payload
        assert CAPPED_160_JSONLD_PREFIX not in payload
        assert REPAIRED_DIAGNOSTIC_BODY_PREFIX not in payload
        assert XML_URL_ORDERED_SHA256 not in payload
    assert "Chapter%20999" not in xml_frontier
    xml_literals = re.findall(
        r"https://www\.legislature\.mi\.gov/documents/mcl/Chapter%20\d+\.xml",
        xml_frontier,
    )
    assert xml_literals == []


def test_michigan_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    official = [str(number) for number in MichiganScraper.OFFICIAL_CHAPTERS]
    xml_urls = [chapter_xml_url(number) for number in official]
    assert len(xml_urls) == RESIDUAL_COUNT
    assert xml_urls[0] == FIRST_XML_URL
    assert xml_urls[-1] == LAST_XML_URL
    assert INVENTED_XML_URL not in xml_urls
    assert REPAIRED_ONLY_XML_URL not in xml_urls
    assert _newline_xml_sha256(xml_urls) == XML_URL_ORDERED_SHA256
    compact = [FIRST_XML_URL, LAST_XML_URL]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://www.legislature.mi.gov/documents/mcl/Chapter%201.xml",'
        b'"https://www.legislature.mi.gov/documents/mcl/Chapter%20830.xml"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert compact_digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert ROOT_WAVE_NAME in report


def test_michigan_one_global_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(MichiganScraper._fetch_michigan_frontier_batch)
    assert "prefer_direct=True" in fetch_source
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert "common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,)" in fetch_source
    assert (
        'common_crawl_mime_terms=("xml",) if media_type == "text/xml" else ("html",)'
        in fetch_source
    )
    assert "archive.is" not in fetch_source.casefold()
    assert fetch_source.count("common_crawl_domain_terms") == 1

    retry_source = inspect.getsource(
        MichiganScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in (
        retry_source
    )
    assert "no per-page archive loop" in retry_source

    xml_source = inspect.getsource(
        MichiganScraper._scrape_official_chapter_xml_frontier
    )
    assert 'common_crawl_url_terms=(self.OFFICIAL_ENTRY_PATH,)' in xml_source
    assert 'common_crawl_url_terms=("/documents/mcl/", "Chapter%20", ".xml")' in (
        xml_source
    )
    assert 'media_type="text/html"' in xml_source
    assert 'media_type="text/xml"' in xml_source

    closure_source = inspect.getsource(
        MichiganScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"kind": "shared_archive_aware_plural_xml"' in closure_source


def test_michigan_seed_and_host_replay_forbid_hub_docker_and_repaired_corpus(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "MI",
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
    assert "repaired" in report
    assert "160-row" in report or "capped 160" in report
    assert "238" in _report_text()


def test_michigan_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    michigan_source = inspect.getsource(
        MichiganScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in michigan_source or (
        "rights" in closure_source.casefold()
    )
    assert "retained_replay_network_requests" in michigan_source
    assert michigan_source.index('"retained_replay_network_requests": 0') > 0
    replay_source = inspect.getsource(MichiganScraper._replay_michigan_retained_input)
    assert "Michigan retained replay is missing exact input" in replay_source
    assert "without permitting network I/O" in inspect.getdoc(
        MichiganScraper._replay_michigan_retained_input
    ) or "without permitting network" in replay_source
    version = MichiganScraper("MI", "Michigan")._state_law_frontier_source_software_version()
    assert version.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan."
        "MichiganScraper@sha256:"
    )
    assert version.split("sha256:")[1].startswith(SOURCE_BUNDLE_PREFIX)


def test_michigan_compact_recipe_closes_one_xml_wave_not_invented_or_capped_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.delenv("MICHIGAN_CHAPTER_XML", raising=False)
    monkeypatch.delenv("MICHIGAN_CONSTITUTION_TEXT", raising=False)
    monkeypatch.setattr(MichiganScraper, "STRICT_MINIMUM_CHAPTERS", 2)
    monkeypatch.setattr(
        MichiganScraper,
        "STRICT_CURRENT_CHAPTER_NUMBER_SHA256",
        _ordered_chapter_sha256(*COMPACT_CHAPTERS),
    )
    scraper = MichiganScraper("MI", "Michigan")
    root = _chapter_index_html(COMPACT_CHAPTERS)
    xml_by_url = {
        chapter_xml_url(chapter): _mi_xml(chapter, f"{chapter}.1")
        for chapter in COMPACT_CHAPTERS
    }
    pages = {scraper.OFFICIAL_ENTRY_URL: root, **xml_by_url}
    batch_calls: list[tuple[list[str], dict]] = []

    async def _plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        batch_calls.append((requested, dict(kwargs)))
        missing = [url for url in requested if url not in pages]
        if missing:
            raise AssertionError(f"compact recipe requested unknown URL {missing}")
        assert residual_retry_attempts == 1
        return _frontier_result(requested, [pages[url] for url in requested])

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict Michigan must not use a per-page archive loop")

    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )

    rows = asyncio.run(
        scraper.scrape_code(
            "Michigan Compiled Laws",
            scraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
    )

    stats = list(getattr(scraper, "_michigan_frontier_batch_stats", []))
    wave_names = [str(row.get("frontier_name") or "") for row in stats]
    requested_urls = [url for urls, _kwargs in batch_calls for url in urls]
    assert wave_names == [ROOT_WAVE_NAME, f"chapter-xml-1-{len(COMPACT_CHAPTERS)}"]
    assert [len(urls) for urls, _kwargs in batch_calls] == [1, 2]
    assert [row.section_number for row in rows] == ["1.1", "2.1"]
    assert requested_urls[0] == OFFICIAL_ENTRY
    assert requested_urls[1:] == [chapter_xml_url(ch) for ch in COMPACT_CHAPTERS]
    assert INVENTED_XML_URL not in requested_urls
    assert REPAIRED_ONLY_XML_URL not in requested_urls
    assert all(kwargs["prefer_direct"] is True for _urls, kwargs in batch_calls)
    assert all(
        kwargs["wayback_prefix_inventory"] is True for _urls, kwargs in batch_calls
    )
    assert all(
        kwargs["repeat_grouped_archive_inventory_on_residual"] is False
        for _urls, kwargs in batch_calls
    )
    assert batch_calls[0][1]["media_type"] == "text/html"
    assert batch_calls[1][1]["media_type"] == "text/xml"
    assert batch_calls[0][1]["common_crawl_mime_terms"] == ("html",)
    assert batch_calls[1][1]["common_crawl_mime_terms"] == ("xml",)
    digest = _canonical_residual_sha256(requested_urls[1:])
    assert digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    assert len(digest) == 64


def test_michigan_invented_later_chapter_fails_closed_on_catalog_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(MichiganScraper, "STRICT_MINIMUM_CHAPTERS", 2)
    monkeypatch.setattr(
        MichiganScraper,
        "STRICT_CURRENT_CHAPTER_NUMBER_SHA256",
        _ordered_chapter_sha256(*COMPACT_CHAPTERS),
    )
    extra_root = _chapter_index_html((*COMPACT_CHAPTERS, "999"))

    async def _plural(self, urls, **_kwargs):
        requested = list(urls)
        assert INVENTED_XML_URL not in requested
        if requested == [self.OFFICIAL_ENTRY_URL]:
            return _frontier_result(requested, [extra_root])
        raise AssertionError("invented catalog must fail before the XML wave")

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("invented chapter must not fall back to a per-page loop")

    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )
    with pytest.raises(RuntimeError, match="changed exact ordered membership"):
        asyncio.run(
            MichiganScraper("MI", "Michigan").scrape_code(
                "Michigan Compiled Laws",
                OFFICIAL_ENTRY,
                max_statutes=None,
            )
        )


def test_michigan_full_corpus_refuses_160_cap_and_configured_xml_before_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("MICHIGAN_CHAPTER_XML", "/tmp/does-not-authorize-mi.xml")
    scrape_source = inspect.getsource(MichiganScraper.scrape_code)
    assert "default=160" in scrape_source
    assert "xml_path is not None and not strict_full" in scrape_source
    assert "_scrape_official_chapter_index" in scrape_source
    limit_source = inspect.getsource(MichiganScraper._effective_scrape_limit)
    assert "if self._full_corpus_enabled()" in limit_source
    assert "return None" in limit_source
    catalog_source = inspect.getsource(MichiganScraper.official_chapter_catalog)
    xml_source = inspect.getsource(
        MichiganScraper._scrape_official_chapter_xml_frontier
    )
    assert "OFFICIAL_CHAPTERS" in catalog_source
    assert "OFFICIAL_CHAPTERS" not in xml_source
    report = parse_michigan_chapter_xml_closure(
        _mi_xml("1", "1.1"),
        chapter_hint="1",
    )
    assert report.closed is True
    assert report.statutes[0].section_number == "1.1"

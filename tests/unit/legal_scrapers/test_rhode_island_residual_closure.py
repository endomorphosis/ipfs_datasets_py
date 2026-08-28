"""LCR-095: Rhode Island nested-catalog then leaf residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, per-slice archive inventory, and
resuming zero-row staging-ri-v1 through v3 as current.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    rhode_island_section,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_isolated_worker import (
    IsolatedRetainedReplayWorkerError,
    build_host_retained_replay_command,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island import (
    RhodeIslandScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island_section import (
    part_subpart_links,
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
    / "rhode_island_residual_closure_v1.md"
)

UNIQUE_DIRECT_INPUTS = 3018
ROOT_CATALOGS = 1
TITLE_CATALOGS = 49
CHAPTER_CATALOGS = 2817
PART_CATALOGS = 151
RETAINED_BYTES = 13860568
DIRECT_SECTION_CHAPTERS = 2788
PART_INDEX_CHAPTERS = 23
TYPED_TERMINAL_CHAPTERS = 6
DIRECT_SECTION_PARTS = 142
NESTED_INDEX_PARENTS = 9
KNOWN_SECTION_IDENTITIES = 34184
TEMPORAL_LOCATORS = 69
CHAPTER_RANGE_MATERIALS = 2
NESTED_CATALOG_RESIDUAL_COUNT = 29
RESIDUAL_SHA256 = (
    "1b8cf9c0d27a7e8eae3308f7d64fbd8c4dcaec9b320aa382966cc6db5eca66af"
)
RESIDUAL_SHA256_PREFIX = RESIDUAL_SHA256[:12]
SOURCE_BUNDLE_PREFIX = "daefc41326a0"
NESTED_CATALOG_WAVE_NAME = "subpart-index"
LEAF_UNION_WAVE_NAME = "sections"
RETAINED_DIRECT_EVIDENCE_ROOT = (
    Path.home()
    / ".ipfs_datasets"
    / "state_laws"
    / "legal-corpora-reindex-20260828-ri-evidence-6nKICq"
)
OFFICIAL_ROOT = "https://webserver.rilegislature.gov/Statutes/"
OFFICIAL_TITLE_ENTRY = (
    "https://webserver.rilegislature.gov/Statutes/TITLE1/INDEX.HTM"
)
INVENTED_NESTED_CATALOG_URL = (
    "https://webserver.rilegislature.gov/Statutes/TITLE6A/6A-2.1/6A-5/6A-Z/INDEX.htm"
)
INVENTED_NESTED_LEAF_URL = (
    "https://webserver.rilegislature.gov/Statutes/TITLE6A/6A-2.1/6A-5/6A-Z/6A-2.1-599.htm"
)
TITLE_6A_URL = f"{OFFICIAL_ROOT}TITLE6A/INDEX.HTM"
CHAPTER_6A_2_1_URL = f"{OFFICIAL_ROOT}TITLE6A/6A-2.1/INDEX.htm"
PART_6A_2_1_5_URL = f"{OFFICIAL_ROOT}TITLE6A/6A-2.1/6A-5/INDEX.htm"
SUBPART_6A_A_URL = f"{PART_6A_2_1_5_URL[:-9]}6A-A/INDEX.htm"
SUBPART_6A_B_URL = f"{PART_6A_2_1_5_URL[:-9]}6A-B/INDEX.htm"
KNOWN_LEAF_URL = f"{SUBPART_6A_A_URL[:-9]}6A-2.1-501.htm"
NEW_LEAF_URL = f"{SUBPART_6A_B_URL[:-9]}6A-2.1-508.htm"
FENCED_STAGING_ROOTS = (
    "staging-ri-v1",
    "staging-ri-v2",
    "staging-ri-v3",
)


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _root_html(*titles: str) -> bytes:
    return (
        "<html><body>"
        + "".join(
            f"<a href='TITLE{title}/INDEX.HTM'>TITLE {title}</a>"
            for title in titles
        )
        + "</body></html>"
    ).encode()


def _title_html(*chapters: str) -> bytes:
    return (
        "<html><body>"
        + "".join(
            f"<a href='{chapter}/INDEX.htm'>Chapter {chapter}</a>"
            for chapter in chapters
        )
        + "</body></html>"
    ).encode()


def _chapter_parts_html(chapter: str, *parts: tuple[str, str]) -> bytes:
    local_chapter = chapter.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h2><center>Chapter {local_chapter}<br>Official Chapter</center>"
        "</h2></div><center><h3>Index of Parts</h3></center>"
        + "".join(
            f"<p><a href='{part}/INDEX.htm'>Part {label}&nbsp;Official Part</a></p>"
            for part, label in parts
        )
        + "</body></html>"
    ).encode()


def _part_subparts_html(part: str, *subparts: tuple[str, str]) -> bytes:
    local_part = part.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h3><center>Part {local_part}<br>Official Part</center></h3></div>"
        "<center><h3>Index of Subparts</h3></center>"
        + "".join(
            f"<p><a href='{subpart}/INDEX.htm'>Subpart {label}&nbsp;"
            "Official Subpart</a></p>"
            for subpart, label in subparts
        )
        + "</body></html>"
    ).encode()


def _subpart_html(subpart: str, *sections: str) -> bytes:
    local_subpart = subpart.split("-", 1)[1]
    return (
        "<html><body>"
        f"<div><h4><center>Subpart {local_subpart}<br>Official Subpart"
        "</center></h4></div><center><h3>Index of Sections</h3></center>"
        + "".join(
            f"<p><a href='{section}.htm'>§ {section}. Official section</a></p>"
            for section in sections
        )
        + "</body></html>"
    ).encode()


def _section_html(section: str) -> bytes:
    return (
        "<html><body>"
        "<div>Rhode Island General Laws</div>"
        f"<div>Chapter {'-'.join(section.split('-')[:-1])}</div>"
        "<div>"
        f"<p><b>§ {section}. Official section {section}.</b></p>"
        f"<p>Official Rhode Island statutory text for {section}. "
        "This sufficiently long body is retained without a synthetic fallback.</p>"
        "<div><p>History of Section. P.L. 2025, ch. 1.</p></div>"
        "</div>"
        "</body></html>"
    ).encode()


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Rhode Island residual closure report is empty")
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


def _source_ordered_nested_catalogs(parent_html: str, parent_url: str) -> list[str]:
    rows = part_subpart_links(
        parent_html,
        part_url=parent_url,
        title_number="6A",
        chapter_number="6A-2.1",
        part_number="6A-5",
        intermediate_label="Part 5 Official Part",
    )
    urls = [url for url, _label in rows]
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            raise AssertionError(
                "Rhode Island nested-catalog residual frontier repeated a URL"
            )
        seen.add(url)
    return urls


def test_rhode_island_residual_closure_report_records_exact_nested_catalog_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "RI"
    assert table["official domain"] == "webserver.rilegislature.gov"
    assert table["official entry"] == OFFICIAL_ROOT
    assert table["scraper_official_entry_url"] == OFFICIAL_TITLE_ENTRY
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["seed"] == "3018 unique direct inputs"
    assert table["resume_zero_row_staging_ri_v1_v3"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["per_slice_archive_inventory"] == "forbidden"
    assert table["unique_direct_inputs"] == str(UNIQUE_DIRECT_INPUTS)
    assert table["root_catalogs"] == str(ROOT_CATALOGS)
    assert table["title_catalogs"] == str(TITLE_CATALOGS)
    assert table["chapter_catalogs"] == str(CHAPTER_CATALOGS)
    assert table["part_catalogs"] == str(PART_CATALOGS)
    assert table["retained_bytes"] == str(RETAINED_BYTES)
    assert table["direct_section_chapters"] == str(DIRECT_SECTION_CHAPTERS)
    assert table["part_index_chapters"] == str(PART_INDEX_CHAPTERS)
    assert table["typed_terminal_chapters"] == str(TYPED_TERMINAL_CHAPTERS)
    assert table["direct_section_parts"] == str(DIRECT_SECTION_PARTS)
    assert table["nested_index_parents"] == str(NESTED_INDEX_PARENTS)
    assert table["known_section_identities"] == str(KNOWN_SECTION_IDENTITIES)
    assert table["temporal_locators"] == str(TEMPORAL_LOCATORS)
    assert table["source_bound_chapter_range_materials"] == str(
        CHAPTER_RANGE_MATERIALS
    )
    assert table["residual_count"] == str(NESTED_CATALOG_RESIDUAL_COUNT)
    assert table["residual_kind"] == "unique ordered nested catalogs then leaf union"
    assert table["residual_wave_name"] == NESTED_CATALOG_WAVE_NAME
    assert table["leaf_union_wave_name"] == LEAF_UNION_WAVE_NAME
    assert table["nested_catalog_wave_count"] == "1"
    assert table["leaf_union_wave_count"] == "1"
    assert table["fetch_nested_catalogs_before_leaf_union"] == "true"
    assert table["known_leaves"] == str(KNOWN_SECTION_IDENTITIES)
    assert table["leaf_union_count"] == "source_dependent_after_29_nested_catalogs"
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_ordered_sha256"] == RESIDUAL_SHA256
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["source_bundle_prefix"] == SOURCE_BUNDLE_PREFIX
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert int(table["root_catalogs"]) + int(table["title_catalogs"]) + int(
        table["chapter_catalogs"]
    ) + int(table["part_catalogs"]) == UNIQUE_DIRECT_INPUTS
    assert (
        DIRECT_SECTION_CHAPTERS + PART_INDEX_CHAPTERS + TYPED_TERMINAL_CHAPTERS
        == CHAPTER_CATALOGS
    )
    assert DIRECT_SECTION_PARTS + NESTED_INDEX_PARENTS == PART_CATALOGS

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "nested catalogs first" in lowered
    assert "leaf union" in lowered
    assert "hub mutation" in lowered
    assert "per-slice" in lowered
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "3,018" in report
    assert "34,184" in report
    assert "13,860,568" in report
    assert RESIDUAL_SHA256 in report
    assert OFFICIAL_ROOT in report
    assert INVENTED_NESTED_CATALOG_URL not in report
    for fenced in FENCED_STAGING_ROOTS:
        assert fenced in report
        assert "forbidden" in lowered or "do not resume" in lowered
    assert report.count("/INDEX.htm") < 8
    assert "source_dependent_after_29_nested_catalogs" in report


def test_rhode_island_nested_catalogs_are_source_derived_from_nine_parents() -> None:
    parents = rhode_island_section._SOURCE_BOUND_SUBPART_INDEX_DIGESTS
    assert len(parents) == NESTED_INDEX_PARENTS
    assert all(len(digest) == 64 for digest in parents.values())
    assert all(
        len(identity) == 3 and not any(part.startswith("http") for part in identity)
        for identity in parents
    )
    assert (
        "6A",
        "6A-2.1",
        "6A-5",
    ) in parents
    assert ("99", "99-1", "99-1") not in parents

    unbounded = inspect.getsource(
        RhodeIslandScraper._scrape_unbounded_rhode_island_frontier
    )
    assert "toc_title_links" in unbounded
    assert "part_subpart_links" in unbounded
    assert 'frontier_name="root-index"' in unbounded
    assert 'frontier_name="title-index"' in unbounded
    assert 'frontier_name="chapter-index"' in unbounded
    assert 'frontier_name="part-index"' in unbounded
    assert f'frontier_name="{NESTED_CATALOG_WAVE_NAME}"' in unbounded
    assert f'frontier_name="{LEAF_UNION_WAVE_NAME}"' in unbounded
    assert unbounded.index('frontier_name="part-index"') < unbounded.index(
        f'frontier_name="{NESTED_CATALOG_WAVE_NAME}"'
    )
    assert unbounded.index(
        f'frontier_name="{NESTED_CATALOG_WAVE_NAME}"'
    ) < unbounded.index(f'frontier_name="{LEAF_UNION_WAVE_NAME}"')
    assert "OFFICIAL_TITLES" in unbounded
    assert "title_rows = toc_title_links(" in unbounded
    assert INVENTED_NESTED_CATALOG_URL not in unbounded


def test_rhode_island_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(RhodeIslandScraper)
    section_adapter = inspect.getsource(rhode_island_section)
    unbounded = inspect.getsource(
        RhodeIslandScraper._scrape_unbounded_rhode_island_frontier
    )
    assert str(KNOWN_SECTION_IDENTITIES) not in adapter
    assert str(RETAINED_BYTES) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert RESIDUAL_SHA256_PREFIX not in section_adapter
    assert INVENTED_NESTED_CATALOG_URL not in adapter
    assert INVENTED_NESTED_CATALOG_URL not in section_adapter
    assert RESIDUAL_SHA256 not in unbounded
    for fenced in FENCED_STAGING_ROOTS:
        assert fenced not in adapter
    nested_index_literals = re.findall(
        r"TITLE[0-9A]+/[0-9A.-]+/[0-9A.-]+/[0-9A.-]+/INDEX\.htm",
        adapter,
        flags=re.IGNORECASE,
    )
    assert nested_index_literals == []
    assert "subpart_urls = [row[5] for row in subpart_frontier]" in unbounded
    assert "section_urls = [row[6] for row in section_frontier]" in unbounded


def test_rhode_island_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    compact = [SUBPART_6A_A_URL, SUBPART_6A_B_URL]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://webserver.rilegislature.gov/Statutes/TITLE6A/6A-2.1/'
        b'6A-5/6A-A/INDEX.htm",'
        b'"https://webserver.rilegislature.gov/Statutes/TITLE6A/6A-2.1/'
        b'6A-5/6A-B/INDEX.htm"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert not compact_digest.startswith(RESIDUAL_SHA256_PREFIX)
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert NESTED_CATALOG_WAVE_NAME in report
    assert LEAF_UNION_WAVE_NAME in report


def test_rhode_island_retained_hierarchy_derives_full_nested_catalog_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetches = RETAINED_DIRECT_EVIDENCE_ROOT / "RI" / "fetches"
    objects = RETAINED_DIRECT_EVIDENCE_ROOT / "RI" / "objects"
    if not fetches.is_dir() or not objects.is_dir():
        pytest.skip("exact retained Rhode Island hierarchy is not installed")

    ledger = StateLawMultiFetchAcquisitionLedger(
        RETAINED_DIRECT_EVIDENCE_ROOT,
        jurisdiction="RI",
        parser_name="RhodeIslandScraper",
        retained_replay_only=True,
        allowed_source_transports=("direct",),
    )
    assert len(ledger.entries) == UNIQUE_DIRECT_INPUTS

    scraper = RhodeIslandScraper("RI", "Rhode Island")
    scraper.attach_state_law_acquisition_ledger(ledger)
    scraper._rhode_island_retained_replay = True
    original_fetch = scraper._fetch_rhode_island_frontier_batch
    observed_waves: list[tuple[str, int]] = []
    nested_catalog_urls: list[str] = []

    class _NestedCatalogResidualObserved(RuntimeError):
        pass

    async def _capture_source_derived_wave(
        urls: list[str],
        *,
        frontier_name: str,
    ):
        requested = list(urls)
        observed_waves.append((frontier_name, len(requested)))
        if frontier_name == NESTED_CATALOG_WAVE_NAME:
            nested_catalog_urls.extend(requested)
            raise _NestedCatalogResidualObserved
        return await original_fetch(requested, frontier_name=frontier_name)

    async def _network_forbidden(*_args, **_kwargs):
        raise AssertionError("Rhode Island retained hierarchy attempted network I/O")

    monkeypatch.setattr(
        scraper,
        "_fetch_rhode_island_frontier_batch",
        _capture_source_derived_wave,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _network_forbidden,
    )

    with pytest.raises(_NestedCatalogResidualObserved):
        asyncio.run(
            scraper._scrape_unbounded_rhode_island_frontier(
                "Rhode Island General Laws",
                "R.I. Gen. Laws",
            )
        )

    assert observed_waves == [
        ("root-index", ROOT_CATALOGS),
        ("title-index", TITLE_CATALOGS),
        ("chapter-index", CHAPTER_CATALOGS),
        ("part-index", PART_CATALOGS),
        (NESTED_CATALOG_WAVE_NAME, NESTED_CATALOG_RESIDUAL_COUNT),
    ]
    assert len(nested_catalog_urls) == len(set(nested_catalog_urls))
    retained_urls = {entry.receipt.endpoint for entry in ledger.entries}
    assert retained_urls.isdisjoint(nested_catalog_urls)
    assert _canonical_residual_sha256(nested_catalog_urls) == RESIDUAL_SHA256


def test_rhode_island_one_domain_wave_disables_per_page_and_per_slice_archive() -> None:
    fetch_source = inspect.getsource(
        RhodeIslandScraper._fetch_rhode_island_frontier_batch
    )
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,)" in fetch_source
    assert 'common_crawl_url_terms=("/Statutes/",)' in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "repeat_grouped_archive_inventory_on_residual=True" not in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "TITLE{title}" not in fetch_source
    assert fetch_source.count("common_crawl_url_terms") == 1

    retry_source = inspect.getsource(
        BaseStateScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        RhodeIslandScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source


def test_rhode_island_seed_and_host_replay_forbid_hub_docker_and_zero_row_staging(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "RI",
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
    assert "staging-ri-v1" in report
    assert "do not resume" in report or "forbidden" in report


def test_rhode_island_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    rhode_island_source = inspect.getsource(
        RhodeIslandScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in closure_source
    assert "retained_replay_network_requests" in rhode_island_source
    assert rhode_island_source.index('"retained_replay_network_requests": 0') > 0
    assert "_rhode_island_retained_replay" in rhode_island_source
    assert "Rhode Island retained hierarchy changed on replay" in rhode_island_source


def test_rhode_island_compact_nested_catalog_recipe_fetches_catalogs_before_leaf_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    part_html = _part_subparts_html("6A-5", ("6A-A", "A"), ("6A-B", "B"))
    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {
            ("6A", "6A-2.1", "6A-5"): hashlib.sha256(part_html).hexdigest(),
        },
    )
    nested_catalogs = _source_ordered_nested_catalogs(
        part_html.decode(),
        PART_6A_2_1_5_URL,
    )
    assert nested_catalogs == [SUBPART_6A_A_URL, SUBPART_6A_B_URL]
    assert INVENTED_NESTED_CATALOG_URL not in nested_catalogs
    digest = _canonical_residual_sha256(nested_catalogs)
    assert not digest.startswith(RESIDUAL_SHA256_PREFIX)

    pages = {
        OFFICIAL_ROOT: _root_html("6A"),
        TITLE_6A_URL: _title_html("6A-2.1"),
        CHAPTER_6A_2_1_URL: _chapter_parts_html("6A-2.1", ("6A-5", "5")),
        PART_6A_2_1_5_URL: part_html,
        SUBPART_6A_A_URL: _subpart_html("6A-A", "6A-2.1-501"),
        SUBPART_6A_B_URL: _subpart_html("6A-B", "6A-2.1-508"),
        KNOWN_LEAF_URL: _section_html("6A-2.1-501"),
        NEW_LEAF_URL: _section_html("6A-2.1-508"),
    }
    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return [pages[url] for url in requested]

    async def _singleton_must_not_run(*_args, **_kwargs):
        raise AssertionError(
            "Rhode Island nested-catalog residual must remain a plural wave"
        )

    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {
            ("6A", "6A-2.1", "6A-5"): hashlib.sha256(part_html).hexdigest(),
        },
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "OFFICIAL_TITLES",
        (("6A", "Uniform Commercial Code"),),
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _batch,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton_must_not_run,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = RhodeIslandScraper("RI", "Rhode Island")
    rows = asyncio.run(
        scraper._custom_scrape_rhode_island(
            "Rhode Island General Laws",
            OFFICIAL_ROOT,
            "R.I. Gen. Laws",
            max_sections=None,
        )
    )

    wave_names = [name for name, _urls in batch_calls]
    assert wave_names.index(NESTED_CATALOG_WAVE_NAME) < wave_names.index(
        LEAF_UNION_WAVE_NAME
    )
    assert batch_calls == [
        ("root-index", [OFFICIAL_ROOT]),
        ("title-index", [TITLE_6A_URL]),
        ("chapter-index", [CHAPTER_6A_2_1_URL]),
        ("part-index", [PART_6A_2_1_5_URL]),
        (NESTED_CATALOG_WAVE_NAME, nested_catalogs),
        (LEAF_UNION_WAVE_NAME, [KNOWN_LEAF_URL, NEW_LEAF_URL]),
    ]
    assert wave_names.count(NESTED_CATALOG_WAVE_NAME) == 1
    assert wave_names.count(LEAF_UNION_WAVE_NAME) == 1
    assert INVENTED_NESTED_CATALOG_URL not in batch_calls[4][1]
    assert INVENTED_NESTED_LEAF_URL not in batch_calls[5][1]
    assert [row.source_url for row in rows] == [KNOWN_LEAF_URL, NEW_LEAF_URL]
    frontier = scraper._last_rhode_island_full_frontier
    assert frontier["frontier"]["closed"] is True
    assert frontier["frontier"]["subpart_document_count"] == 2
    assert frontier["frontier"]["source_section_count"] == 2


def test_rhode_island_invented_nested_catalog_is_not_admitted_to_the_leaf_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    part_html = _part_subparts_html("6A-5", ("6A-A", "A"))
    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {
            ("6A", "6A-2.1", "6A-5"): hashlib.sha256(part_html).hexdigest(),
        },
    )
    derived = _source_ordered_nested_catalogs(part_html.decode(), PART_6A_2_1_5_URL)
    assert derived == [SUBPART_6A_A_URL]
    assert INVENTED_NESTED_CATALOG_URL not in derived
    assert part_subpart_links(
        part_html.decode(),
        part_url=PART_6A_2_1_5_URL,
        title_number="99",
        chapter_number="99-1",
        part_number="99-1",
        intermediate_label="Part 1 Official Part",
    ) == []

    pages = {
        OFFICIAL_ROOT: _root_html("6A"),
        TITLE_6A_URL: _title_html("6A-2.1"),
        CHAPTER_6A_2_1_URL: _chapter_parts_html("6A-2.1", ("6A-5", "5")),
        PART_6A_2_1_5_URL: part_html,
        SUBPART_6A_A_URL: _subpart_html("6A-A", "6A-2.1-501"),
        INVENTED_NESTED_CATALOG_URL: _subpart_html("6A-Z", "6A-2.1-599"),
        KNOWN_LEAF_URL: _section_html("6A-2.1-501"),
        INVENTED_NESTED_LEAF_URL: _section_html("6A-2.1-599"),
    }
    batch_calls: list[tuple[str, list[str]]] = []

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return [pages[url] for url in requested]

    monkeypatch.setattr(
        RhodeIslandScraper,
        "OFFICIAL_TITLES",
        (("6A", "Uniform Commercial Code"),),
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _batch,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = RhodeIslandScraper("RI", "Rhode Island")
    rows = asyncio.run(
        scraper._custom_scrape_rhode_island(
            "Rhode Island General Laws",
            OFFICIAL_ROOT,
            "R.I. Gen. Laws",
            max_sections=None,
        )
    )

    requested_by_wave = {name: urls for name, urls in batch_calls}
    assert requested_by_wave[NESTED_CATALOG_WAVE_NAME] == [SUBPART_6A_A_URL]
    assert INVENTED_NESTED_CATALOG_URL not in requested_by_wave[NESTED_CATALOG_WAVE_NAME]
    assert requested_by_wave[LEAF_UNION_WAVE_NAME] == [KNOWN_LEAF_URL]
    assert INVENTED_NESTED_LEAF_URL not in requested_by_wave[LEAF_UNION_WAVE_NAME]
    assert [row.source_url for row in rows] == [KNOWN_LEAF_URL]


def test_rhode_island_retained_replay_only_miss_does_not_open_per_slice_archive_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_source = inspect.getsource(
        RhodeIslandScraper._fetch_rhode_island_frontier_batch
    )
    unbounded = inspect.getsource(
        RhodeIslandScraper._scrape_unbounded_rhode_island_frontier
    )
    assert "_fetch_page_contents_with_archival_fallback_retrying_residuals" in (
        fetch_source
    )
    assert "common_crawl_url_terms=(\"/Statutes/\",)" in fetch_source
    assert "_fetch_page_content_with_archival_fallback(" not in unbounded
    assert "for title_url in title_urls" not in unbounded
    assert "for chapter_url in chapter_urls" not in unbounded

    singleton_calls: list[str] = []

    async def _singleton(self, url: str, timeout_seconds: int = 25) -> bytes:
        del self, timeout_seconds
        singleton_calls.append(url)
        raise AssertionError(
            "Rhode Island residual must not open a per-page archive loop"
        )

    part_html = _part_subparts_html("6A-5", ("6A-A", "A"))
    pages = {
        OFFICIAL_ROOT: _root_html("6A"),
        TITLE_6A_URL: _title_html("6A-2.1"),
        CHAPTER_6A_2_1_URL: _chapter_parts_html("6A-2.1", ("6A-5", "5")),
        PART_6A_2_1_5_URL: part_html,
        SUBPART_6A_A_URL: _subpart_html("6A-A", "6A-2.1-501"),
        KNOWN_LEAF_URL: _section_html("6A-2.1-501"),
    }
    batch_calls: list[str] = []

    async def _plain_batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append(frontier_name)
        return [pages[url] for url in requested]

    monkeypatch.setattr(
        rhode_island_section,
        "_SOURCE_BOUND_SUBPART_INDEX_DIGESTS",
        {
            ("6A", "6A-2.1", "6A-5"): hashlib.sha256(part_html).hexdigest(),
        },
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "OFFICIAL_TITLES",
        (("6A", "Uniform Commercial Code"),),
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_rhode_island_frontier_batch",
        _plain_batch,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton,
    )
    monkeypatch.setattr(
        RhodeIslandScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = RhodeIslandScraper("RI", "Rhode Island")
    rows = asyncio.run(
        scraper._custom_scrape_rhode_island(
            "Rhode Island General Laws",
            OFFICIAL_ROOT,
            "R.I. Gen. Laws",
            max_sections=None,
        )
    )

    assert singleton_calls == []
    assert batch_calls == [
        "root-index",
        "title-index",
        "chapter-index",
        "part-index",
        NESTED_CATALOG_WAVE_NAME,
        LEAF_UNION_WAVE_NAME,
    ]
    assert [row.source_url for row in rows] == [KNOWN_LEAF_URL]

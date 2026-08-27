"""LCR-096: New Hampshire fresh current-root residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, resuming v4 2025 Wayback roots as
exact-current, and deriving legal_as_of from wall-clock on 2025 bytes.
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
    NewHampshireScraper,
    _NewHampshireCheckpoint,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire_section import (
    nhtoc_title_units,
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
    / "new_hampshire_residual_closure_v1.md"
)

CURRENT_ROOT = "https://gc.nh.gov/rsa/html/NHTOC.htm"
LEGACY_ROOT = "https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm"
OFFICIAL_DOMAIN = "gc.nh.gov"
TITLE_I = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-I.htm"
TITLE_IV = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-IV.htm"
TITLE_IX = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-IX.htm"
INVENTED_TITLE_URL = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-XCIX.htm"
CHAPTER_1 = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-I-1.htm"
CHAPTER_2 = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-I-2.htm"
SECTION_1_1 = "https://gc.nh.gov/rsa/html/I/1/1-1.htm"
SECTION_1_2 = "https://gc.nh.gov/rsa/html/I/1/1-2.htm"
SECTION_2_1 = "https://gc.nh.gov/rsa/html/I/2/2-1.htm"
V4_WAYBACK_CAPTURE = "20250124114611"
V4_WAYBACK_ROOT = (
    "https://web.archive.org/web/20250124114611/"
    "https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm"
)
HISTORICAL_V4_PARSER_INPUTS = 12
HISTORICAL_V4_TITLES = 67
HISTORICAL_V4_ACTIVE_TITLES = 66
HISTORICAL_V4_TERMINAL_TITLES = 1
HISTORICAL_V4_TITLE_RESIDUAL = 55
HISTORICAL_V4_ROOT_BYTES = 16237
HISTORICAL_V4_CHAPTERS_FROM_11_TITLES = 603
HISTORICAL_V4_ROOT_BODY_SHA256 = (
    "5acb11bb3ab6aa7bae620f00d3c022ac08aabb0b3548a1bfe8d177a1d1165611"
)
HISTORICAL_V4_ROOT_RECEIPT_SHA256 = (
    "b579168a413c47791004e9a8c6d47171c1a00acecc6e7de12f50ca6a0aa75e6a"
)
RETAINED_CURRENT_ROOT_INPUTS = 0
RESIDUAL_COUNT = 1
RESIDUAL_WAVE_NAME = "root"
TITLE_WAVE_NAME = "titles"
CHAPTER_WAVE_NAME = "chapters"
SECTION_WAVE_PREFIX = "sections-"
RESIDUAL_SHA256_PREFIX = "fresh_current_root_gc_nh_gov"
DIAGNOSTIC_PRODUCER_PREFIX = "NewHampshireScraper@sha256:5ff723c9aa"
FENCED_V4_ROOTS = (
    "staging-nh-v4",
    "full-acquisition-evidence-v5-nh-current-v1",
)


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _section_page(citation: str, text: str) -> bytes:
    return (
        "<html><head>"
        f'<meta name="sectiontitle" content="Section {citation} Exact title.">'
        "</head><body>"
        f"<h3>Section {citation}</h3><b>{citation} Exact title. –</b>"
        f"<codesect>{text}</codesect>"
        "<sourcenote>Source. History excluded.</sourcenote>"
        "</body></html>"
    ).encode()


def _current_root_html(*titles: tuple[str, str, str]) -> bytes:
    items = []
    for roman, name, note in titles:
        items.append(
            f"<li><a href='NHTOC/NHTOC-{roman}.htm'>TITLE {roman}: {name}</a></li>"
            f"<p class='chapter_list'>{note}</p>"
        )
    return (
        "<html><body><h1>New Hampshire Statutes</h1><h2>Table of Contents</h2><ul>"
        + "".join(items)
        + "</ul></body></html>"
    ).encode()


def _title_html(roman: str, name: str, *chapters: tuple[str, str]) -> bytes:
    links = "".join(
        f"<a href='NHTOC-{roman}-{number}.htm'>CHAPTER {number}: {label}</a>"
        for number, label in chapters
    )
    return (
        "<html><body><h1>New Hampshire Statutes</h1><h2>Table of Contents</h2>"
        f"<h2>{roman}: {name}</h2>"
        f"{links}"
        "</body></html>"
    ).encode()


def _compact_current_root_pages() -> dict[str, bytes]:
    return {
        CURRENT_ROOT: _current_root_html(
            ("I", "THE STATE AND ITS GOVERNMENT", "(Includes Chapters 1 - 2)"),
            (
                "IV",
                "ELECTIONS",
                "(Entire Title Was Repealed - Chapters 54 - 70)",
            ),
        ),
        TITLE_I: _title_html(
            "I",
            "THE STATE AND ITS GOVERNMENT",
            ("1", "STATE BOUNDARIES"),
            ("2", "AERIAL SURVEY"),
        ),
        CHAPTER_1: (
            "<html><body><h1>New Hampshire Statutes</h1><h2>Table of Contents</h2>"
            "<h2><a href='../I/1/1-mrg.htm'>CHAPTER 1: STATE BOUNDARIES</a></h2>"
            "<a href='../I/1/1-1.htm'>Section 1:1 Exact title.</a>"
            "<a href='../I/1/1-2.htm'>Section 1:2 Repealed by 2020, 1:1.</a>"
            "</body></html>"
        ).encode(),
        CHAPTER_2: (
            "<html><body><h1>New Hampshire Statutes</h1><h2>Table of Contents</h2>"
            "<h2><a href='../I/2/2-mrg.htm'>CHAPTER 2: AERIAL SURVEY</a></h2>"
            "<a href='../I/2/2-1.htm'>Section: 2:1 Exact second title.</a>"
            "</body></html>"
        ).encode(),
        SECTION_1_1: _section_page(
            "1:1",
            "The boundary of New Hampshire shall remain as officially established.",
        ),
        SECTION_2_1: _section_page(
            "2:1",
            "The state may conduct an aerial survey for an official public purpose.",
        ),
        TITLE_IX: _title_html("IX", "HISTORICAL RESIDUAL", ("99", "NOT CURRENT")),
        INVENTED_TITLE_URL: _title_html("XCIX", "INVENTED", ("99", "NOT CURRENT")),
        V4_WAYBACK_ROOT: _current_root_html(
            ("I", "THE STATE AND ITS GOVERNMENT", "(Includes Chapters 1 - 2)"),
        ),
        LEGACY_ROOT: _current_root_html(
            ("I", "THE STATE AND ITS GOVERNMENT", "(Includes Chapters 1 - 2)"),
            (
                "IV",
                "ELECTIONS",
                "(Entire Title Was Repealed - Chapters 54 - 70)",
            ),
        ),
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
        raise AssertionError("New Hampshire residual closure report is empty")
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


def _source_ordered_titles(root_html: str, *, base_url: str) -> list[str]:
    units = nhtoc_title_units(root_html, base_url=base_url)
    urls = [str(unit["source_url"]) for unit in units]
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            raise AssertionError(
                "New Hampshire current-root title frontier repeated a URL"
            )
        seen.add(url)
    return urls


def test_new_hampshire_residual_closure_report_records_exact_current_root_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "NH"
    assert table["official domain"] == OFFICIAL_DOMAIN
    assert table["official entry"] == CURRENT_ROOT
    assert table["legacy_entry"] == LEGACY_ROOT
    assert table["current_official_entry"] == CURRENT_ROOT
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == "official RSA NHTOC title/chapter/section HTML tree"
    assert table["seed"] == (
        "zero authorizing current-ledger inputs; start at the current official root"
    )
    assert table["resume_v4_2025_wayback_root"] == "forbidden"
    assert table["resume_staging_nh_v4"] == "forbidden"
    assert table["seed_from_v4"] == "forbidden"
    assert table["carry_forward_historical_title_residual"] == "forbidden"
    assert table["equate_legacy_and_current_hosts_without_delegation_proof"] == (
        "forbidden"
    )
    assert table["legal_as_of_wall_clock_on_2025_bytes"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["invent_later_title_targets"] == "forbidden"
    assert table["per_page_archive_loop"] == "false"
    assert table["retained_current_root_inputs"] == str(RETAINED_CURRENT_ROOT_INPUTS)
    assert table["historical_v4_parser_inputs"] == str(HISTORICAL_V4_PARSER_INPUTS)
    assert table["historical_v4_root_plus_titles"] == "1 root + 11 titles"
    assert table["historical_v4_root_wayback_capture"] == V4_WAYBACK_CAPTURE
    assert table["historical_v4_root_bytes"] == str(HISTORICAL_V4_ROOT_BYTES)
    assert table["historical_v4_root_body_sha256"] == HISTORICAL_V4_ROOT_BODY_SHA256
    assert table["historical_v4_root_receipt_sha256"] == (
        HISTORICAL_V4_ROOT_RECEIPT_SHA256
    )
    assert table["historical_v4_titles_discovered"] == str(HISTORICAL_V4_TITLES)
    assert table["historical_v4_active_titles"] == str(HISTORICAL_V4_ACTIVE_TITLES)
    assert table["historical_v4_terminal_titles"] == str(
        HISTORICAL_V4_TERMINAL_TITLES
    )
    assert table["historical_v4_terminal_title"] == "IV repealed"
    assert table["historical_v4_title_residual"] == str(
        HISTORICAL_V4_TITLE_RESIDUAL
    )
    assert table["historical_v4_chapters_from_11_titles"] == str(
        HISTORICAL_V4_CHAPTERS_FROM_11_TITLES
    )
    assert table["title_membership_count"] == "source_dependent_after_current_root"
    assert table["chapter_membership_count"] == "source_dependent_after_current_root"
    assert table["section_membership_count"] == "source_dependent_after_current_root"
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == (
        "fresh current official root then source-derived title/chapter/section membership"
    )
    assert table["residual_first_url"] == CURRENT_ROOT
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["title_wave_name"] == TITLE_WAVE_NAME
    assert table["chapter_wave_name"] == CHAPTER_WAVE_NAME
    assert table["section_wave_name_prefix"] == SECTION_WAVE_PREFIX
    assert table["root_acquisition_wave_count"] == "1"
    assert table["title_acquisition_wave_count"] == "1"
    assert table["fetch_current_root_before_titles"] == "true"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["diagnostic_producer"].startswith(DIAGNOSTIC_PRODUCER_PREFIX)
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert (
        int(table["historical_v4_active_titles"])
        + int(table["historical_v4_terminal_titles"])
        == HISTORICAL_V4_TITLES
    )
    assert (
        int(table["historical_v4_root_plus_titles"].split()[0])
        + 11
        == HISTORICAL_V4_PARSER_INPUTS
    )
    assert RETAINED_CURRENT_ROOT_INPUTS + RESIDUAL_COUNT == 1

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "fresh current" in lowered
    assert "do not assume" in lowered and "55" in report
    assert "legal_as_of" in lowered or "legal as of" in lowered
    assert "wall-clock" in lowered
    assert "hub mutation" in lowered
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert CURRENT_ROOT in report
    assert LEGACY_ROOT in report
    assert V4_WAYBACK_CAPTURE in report
    assert INVENTED_TITLE_URL not in report
    assert TITLE_IX not in report
    assert V4_WAYBACK_ROOT not in report
    assert report.count("NHTOC-") < 8
    assert "source_dependent_after_current_root" in report
    assert "datetime.now" in report


def test_new_hampshire_current_root_is_source_derived_and_not_v4_wayback() -> None:
    scraper = NewHampshireScraper("NH", "New Hampshire")
    assert scraper.get_base_url() == f"https://{OFFICIAL_DOMAIN}"
    assert scraper.OFFICIAL_DOMAIN == OFFICIAL_DOMAIN
    assert scraper.CURRENT_OFFICIAL_ENTRY_URL == CURRENT_ROOT
    assert scraper.OFFICIAL_ENTRY_URL == LEGACY_ROOT
    assert scraper.get_code_list()[0]["url"] == CURRENT_ROOT
    assert scraper.official_title_url("I") == TITLE_I
    assert scraper.OFFICIAL_TITLE_COUNT == HISTORICAL_V4_TITLES
    assert scraper.OFFICIAL_ACTIVE_TITLE_COUNT == HISTORICAL_V4_ACTIVE_TITLES
    assert scraper.OFFICIAL_TERMINAL_TITLES == (("IV", "repealed"),)

    units = nhtoc_title_units(
        _compact_current_root_pages()[CURRENT_ROOT].decode(),
        base_url=CURRENT_ROOT,
    )
    assert [unit["title_number"] for unit in units] == ["I", "IV"]
    assert [unit["source_url"] for unit in units] == [TITLE_I, TITLE_IV]
    assert units[0]["terminal_disposition"] == ""
    assert units[1]["terminal_disposition"] == "repealed"
    assert INVENTED_TITLE_URL not in [unit["source_url"] for unit in units]
    assert TITLE_IX not in [unit["source_url"] for unit in units]

    batched = inspect.getsource(
        NewHampshireScraper._scrape_official_rsa_tree_batched
    )
    assert "nhtoc_title_units" in batched
    assert 'frontier_name="root"' in batched
    assert 'frontier_name="titles"' in batched
    assert 'frontier_name="chapters"' in batched
    assert f'"{SECTION_WAVE_PREFIX}' in batched or "sections-" in batched
    assert batched.index('frontier_name="root"') < batched.index(
        'frontier_name="titles"'
    )
    assert batched.index('frontier_name="titles"') < batched.index(
        'frontier_name="chapters"'
    )
    assert "base_url=self.CURRENT_OFFICIAL_ENTRY_URL" in batched
    assert "[self.OFFICIAL_ENTRY_URL]" in batched
    assert V4_WAYBACK_CAPTURE not in batched
    assert "web.archive.org" not in batched
    assert INVENTED_TITLE_URL not in batched
    assert TITLE_IX not in batched


def test_new_hampshire_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(NewHampshireScraper)
    batched = inspect.getsource(
        NewHampshireScraper._scrape_official_rsa_tree_batched
    )
    fetch_source = inspect.getsource(
        NewHampshireScraper._fetch_new_hampshire_frontier_batch
    )
    assert str(HISTORICAL_V4_TITLE_RESIDUAL) not in batched
    assert str(HISTORICAL_V4_CHAPTERS_FROM_11_TITLES) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert INVENTED_TITLE_URL not in adapter
    assert TITLE_IX not in adapter
    assert TITLE_IX not in batched
    assert V4_WAYBACK_ROOT not in batched
    assert V4_WAYBACK_ROOT not in fetch_source
    for fenced in ("staging-nh-v4", "staging-nh-v1"):
        assert fenced not in adapter
    invented_literals = re.findall(
        r"NHTOC/NHTOC-XCIX\.htm",
        adapter,
        flags=re.I,
    )
    assert invented_literals == []
    assert "title_units = nhtoc_title_units(" in batched
    assert "[str(unit[\"source_url\"]) for unit in active_title_units]" in batched


def test_new_hampshire_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    compact = [CURRENT_ROOT]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://gc.nh.gov/rsa/html/NHTOC.htm"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert not compact_digest.startswith(RESIDUAL_SHA256_PREFIX)
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert TITLE_WAVE_NAME in report
    assert CHAPTER_WAVE_NAME in report
    assert SECTION_WAVE_PREFIX in report


def test_new_hampshire_one_domain_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(
        NewHampshireScraper._fetch_new_hampshire_frontier_batch
    )
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert "wayback_prefix_inventory=True" in fetch_source
    assert 'common_crawl_url_terms=("/rsa/html/",)' in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert '"gc.nh.gov"' in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "NHTOC-{roman}" not in fetch_source
    assert fetch_source.count("common_crawl_url_terms") == 1

    retry_source = inspect.getsource(
        BaseStateScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        NewHampshireScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source

    batched = inspect.getsource(
        NewHampshireScraper._scrape_official_rsa_tree_batched
    )
    assert "_fetch_page_content_with_archival_fallback(" not in batched


def test_new_hampshire_seed_and_host_replay_forbid_hub_docker_and_v4_resume(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "NH",
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
    assert "do not seed it from v4" in report or "seed_from_v4" in report
    assert "20250124114611" in report
    for fenced in FENCED_V4_ROOTS:
        assert fenced in _report_text()


def test_new_hampshire_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    hampshire_source = inspect.getsource(
        NewHampshireScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in closure_source
    assert "retained_replay_network_requests" in hampshire_source
    assert hampshire_source.index('"retained_replay_network_requests": 0') > 0
    assert "_new_hampshire_retained_replay" in hampshire_source
    assert "New Hampshire retained hierarchy inputs changed on replay" in (
        hampshire_source
    )


def test_new_hampshire_legal_as_of_wall_clock_on_2025_bytes_is_recorded_proof_residual() -> None:
    batched = inspect.getsource(
        NewHampshireScraper._scrape_official_rsa_tree_batched
    )
    assert "datetime.now(timezone.utc)" in batched
    assert '"legal_as_of": observed_at[:10]' in batched
    report = _report_text()
    table = _report_table(report)
    assert table["legal_as_of_wall_clock_on_2025_bytes"] == "forbidden"
    lowered = " ".join(report.casefold().split())
    assert "wall-clock" in lowered
    assert "2025" in report
    assert "datetime.now" in report
    assert "source-bound" in lowered or "source or capture date" in lowered


def test_new_hampshire_compact_current_root_recipe_starts_before_titles_and_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _compact_current_root_pages()
    derived_titles = _source_ordered_titles(
        pages[CURRENT_ROOT].decode(),
        base_url=CURRENT_ROOT,
    )
    assert derived_titles == [TITLE_I, TITLE_IV]
    assert INVENTED_TITLE_URL not in derived_titles
    assert TITLE_IX not in derived_titles
    digest = _canonical_residual_sha256([CURRENT_ROOT])
    assert not digest.startswith(RESIDUAL_SHA256_PREFIX)

    plural_calls: list[tuple[str, list[str]]] = []

    async def _plural(self, urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        del self
        requested = list(urls)
        frontier_name = str(kwargs.get("frontier_name") or "")
        plural_calls.append((frontier_name, requested))
        assert kwargs["prefer_direct"] is True
        assert kwargs["wayback_prefix_inventory"] is True
        assert kwargs["repeat_grouped_archive_inventory_on_residual"] is False
        assert kwargs["common_crawl_url_terms"] == ("/rsa/html/",)
        return _aligned_result(requested, [pages[url] for url in requested])

    async def _singleton_must_not_run(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError(
            "New Hampshire current-root residual must remain a plural wave"
        )

    monkeypatch.setattr(
        NewHampshireScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(
        NewHampshireScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton_must_not_run,
    )
    scraper = NewHampshireScraper("NH", "New Hampshire")
    monkeypatch.setattr(scraper, "OFFICIAL_ENTRY_URL", CURRENT_ROOT)
    monkeypatch.setattr(
        scraper,
        "OFFICIAL_TITLES",
        (("I", "The State and Its Government"), ("IV", "Elections")),
    )
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 2)

    rows = asyncio.run(
        scraper._scrape_official_rsa_tree_batched(
            code_name="New Hampshire Revised Statutes",
            checkpoint=_NewHampshireCheckpoint("NH"),
        )
    )

    requested = [urls for _name, urls in plural_calls]
    assert requested[0] == [CURRENT_ROOT]
    assert requested[1] == [TITLE_I]
    assert requested[2] == [CHAPTER_1, CHAPTER_2]
    assert requested[3] == [SECTION_1_1, SECTION_2_1]
    assert LEGACY_ROOT not in requested[0]
    assert V4_WAYBACK_ROOT not in requested[0]
    assert TITLE_IX not in requested[1]
    assert INVENTED_TITLE_URL not in requested[1]
    assert TITLE_IV not in requested[1]
    assert [row.source_url for row in rows] == [SECTION_1_1, SECTION_2_1]
    frontier = scraper._last_new_hampshire_full_frontier
    assert frontier["closed"] is True
    assert frontier["titles_discovered"] == 2
    assert frontier["title_pages_fetched"] == 1
    assert len(frontier["terminal_titles"]) == 1


def test_new_hampshire_invented_or_historical_title_is_not_admitted_from_current_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _compact_current_root_pages()
    derived = _source_ordered_titles(
        pages[CURRENT_ROOT].decode(),
        base_url=CURRENT_ROOT,
    )
    assert derived == [TITLE_I, TITLE_IV]
    assert INVENTED_TITLE_URL not in derived
    assert TITLE_IX not in derived

    extra_root = _current_root_html(
        ("I", "THE STATE AND ITS GOVERNMENT", "(Includes Chapters 1 - 2)"),
        (
            "IV",
            "ELECTIONS",
            "(Entire Title Was Repealed - Chapters 54 - 70)",
        ),
        ("XCIX", "INVENTED TITLE", "(Includes Chapters 99 - 99)"),
    )
    with pytest.raises(RuntimeError, match="does not match the exact official"):
        scraper = NewHampshireScraper("NH", "New Hampshire")
        monkeypatch.setattr(scraper, "OFFICIAL_ENTRY_URL", CURRENT_ROOT)
        monkeypatch.setattr(
            scraper,
            "OFFICIAL_TITLES",
            (("I", "The State and Its Government"), ("IV", "Elections")),
        )
        monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 2)

        async def _plural(self, urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
            del self
            requested = list(urls)
            payloads = [extra_root if url == CURRENT_ROOT else pages[url] for url in requested]
            return _aligned_result(requested, payloads)

        monkeypatch.setattr(
            NewHampshireScraper,
            "_fetch_page_contents_with_archival_fallback_retrying_residuals",
            _plural,
        )
        asyncio.run(
            scraper._scrape_official_rsa_tree_batched(
                code_name="New Hampshire Revised Statutes",
                checkpoint=_NewHampshireCheckpoint("NH"),
            )
        )


def test_new_hampshire_retained_replay_only_miss_does_not_open_per_page_archive_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_source = inspect.getsource(
        NewHampshireScraper._fetch_new_hampshire_frontier_batch
    )
    batched = inspect.getsource(
        NewHampshireScraper._scrape_official_rsa_tree_batched
    )
    assert "_fetch_page_contents_with_archival_fallback_retrying_residuals" in (
        fetch_source
    )
    assert "_fetch_page_content_with_archival_fallback(" not in batched
    assert "for title_url in" not in batched

    singleton_calls: list[str] = []

    async def _singleton(self, url: str, timeout_seconds: int = 25) -> bytes:
        del self, timeout_seconds
        singleton_calls.append(url)
        raise AssertionError(
            "New Hampshire residual must not open a per-page archive loop"
        )

    pages = _compact_current_root_pages()
    batch_calls: list[list[str]] = []

    async def _plain_batch(self, urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        del self
        requested = list(urls)
        batch_calls.append(requested)
        return _aligned_result(requested, [pages[url] for url in requested])

    monkeypatch.setattr(
        NewHampshireScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plain_batch,
    )
    monkeypatch.setattr(
        NewHampshireScraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton,
    )
    scraper = NewHampshireScraper("NH", "New Hampshire")
    monkeypatch.setattr(scraper, "OFFICIAL_ENTRY_URL", CURRENT_ROOT)
    monkeypatch.setattr(
        scraper,
        "OFFICIAL_TITLES",
        (("I", "The State and Its Government"), ("IV", "Elections")),
    )
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 2)

    rows = asyncio.run(
        scraper._scrape_official_rsa_tree_batched(
            code_name="New Hampshire Revised Statutes",
            checkpoint=_NewHampshireCheckpoint("NH"),
        )
    )

    assert singleton_calls == []
    assert batch_calls[0] == [CURRENT_ROOT]
    assert INVENTED_TITLE_URL not in batch_calls[0]
    assert TITLE_IX not in batch_calls[0]
    assert V4_WAYBACK_ROOT not in batch_calls[0]
    assert [row.source_url for row in rows] == [SECTION_1_1, SECTION_2_1]

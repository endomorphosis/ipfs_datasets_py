"""LCR-090: Kentucky exact unique-leaf residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, double-counting duplicate
exact-request groups, and replaying mixed historical request identities as
current.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    StateLawRetainedReplayOnlyError,
)
from ipfs_datasets_py.processors.legal_data import (
    state_laws_retained_evidence_seed as seed_module,
)
from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky import (
    KentuckyScraper,
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
    / "kentucky_residual_closure_v1.md"
)

UNIQUE_SOURCE_ORDERED_LEAVES = 40569
RETAINED_ROOT_PAGES = 1
RETAINED_CHAPTER_CATALOGS = 753
RETAINED_UNIQUE_LEAVES = 28928
UNIQUE_REQUEST_URL_IDENTITIES = 29682
V4_RECEIPTS = 29854
DUPLICATE_EXACT_REQUEST_EXTRA_RECEIPTS = 172
UNIQUE_CONTENT_OBJECTS = 29670
UNIQUE_CONTENT_OBJECT_BYTES = 238948779
V4_DIRECT_RECEIPTS = 29839
V4_WAYBACK_RECEIPTS = 15
PARSER_INPUT_FRONTIER = 41323
RESIDUAL_COUNT = 11641
RESIDUAL_SHA256_PREFIX = "c96072a16cc6"
RESIDUAL_SHA256 = (
    "c96072a16cc6cf0def74d7d2d6b5a7420c936a5a28b7b35ffe2f2ec36da5cac1"
)
DIRECT_SEED_SELECTED_INPUTS = 29675
DIRECT_SEED_UNIQUE_CONTENT_OBJECTS = 29663
DIRECT_SEED_DUPLICATE_OBSERVATIONS_AVOIDED = 164
DIRECT_SEED_RETAINED_UNIQUE_LEAVES = 28921
CURRENT_LIVE_RESIDUAL_COUNT = 11648
CURRENT_LIVE_RESIDUAL_SHA256 = (
    "f2a7625b4f93fdb1fd05615c8e1e1a84c7e947870322995a1396de786e2a38bf"
)
CURRENT_LIVE_FIRST_SOURCE_RECORD_ID = "kentucky-statute-25144"
WAYBACK_ONLY_CURRENT_REACQUISITION_IDS = (
    "25144",
    "25481",
    "25491",
    "25501",
    "43841",
    "5613",
    "5626",
)
SOURCE_BUNDLE_PREFIX = "7ee7c0ed8855"
RESIDUAL_WAVE_NAME = "section"
CATALOG_WAVE_NAME = "chapter-index"
ROOT_WAVE_NAME = "root-index"
OFFICIAL_ENTRY = "https://apps.legislature.ky.gov/law/statutes/"
OFFICIAL_SECTION_LOCATOR = (
    "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id="
)
OFFICIAL_CHAPTER_LOCATOR = (
    "https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id="
)
FIRST_SOURCE_RECORD_ID = "kentucky-statute-29404"
LAST_SOURCE_RECORD_ID = "kentucky-statute-20428"
FIRST_RESIDUAL_URL = (
    "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=29404"
)
LAST_RESIDUAL_URL = (
    "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=20428"
)
GUESSED_NEXT_URL = (
    "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=29405"
)
INVENTED_SECTION_URL = (
    "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=999999"
)
WAYBACK_CAPTURE_URL = (
    "https://web.archive.org/web/20160101000000/"
    "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=29404"
)
LEGACY_ACCEPT = "text/html,application/pdf,*/*;q=0.8"
DIAGNOSTIC_PRODUCER_PREFIX = "KentuckyScraper@sha256:7ee7c0ed8855"
CHAPTER_URLS = [
    "https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=1",
    "https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=2",
]


def _section_url(source_id: int | str) -> str:
    return f"{OFFICIAL_SECTION_LOCATOR}{source_id}"


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _source_ordered_unique_leaf_residual(
    leaf_urls: list[str],
    retained_leaf_urls: set[str],
) -> list[str]:
    residual: list[str] = []
    seen: set[str] = set()
    for url in leaf_urls:
        if url in retained_leaf_urls:
            continue
        if url in seen:
            raise AssertionError(
                "Kentucky unique-leaf residual frontier repeated a URL"
            )
        seen.add(url)
        residual.append(url)
    return residual


def _unique_urls_and_duplicate_extras(
    observations: list[tuple[str, Mapping[str, Any], str]],
) -> tuple[list[str], int]:
    unique_urls: list[str] = []
    seen_urls: set[str] = set()
    grouped: dict[tuple[str, str], list[str]] = {}
    for url, sanitized_request, digest in observations:
        identity = (
            url,
            json.dumps(
                dict(sanitized_request),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        grouped.setdefault(identity, []).append(digest)
        if url not in seen_urls:
            seen_urls.add(url)
            unique_urls.append(url)
    extras = 0
    for digests in grouped.values():
        if len(set(digests)) != 1:
            raise AssertionError(
                "duplicate exact-request group bound disagreeing content"
            )
        extras += len(digests) - 1
    return unique_urls, extras


def _plain_get(url: str) -> dict[str, str]:
    return {"method": "GET", "url": url}


def _legacy_accept_get(url: str) -> dict[str, Any]:
    return {
        "headers": {"Accept": LEGACY_ACCEPT},
        "method": "GET",
        "url": url,
    }


def _chapter_payload(*section_rows: tuple[int, str]) -> bytes:
    links = "".join(
        f"<a href='statute.aspx?id={source_id}'>{label}</a>"
        for source_id, label in section_rows
    )
    return (
        "<html><body><h1>Kentucky Revised Statutes</h1>"
        f"{links}</body></html>"
    ).encode()


def _section_payload(section_number: str) -> bytes:
    body = (
        f"KRS {section_number} Official statutory text for section "
        f"{section_number}. This public-law provision supplies substantive "
        "normalized Kentucky text. "
    ) * 4
    return (
        "<html><body>"
        f"<h1>{section_number}. Official heading.</h1>"
        f"<p>{body}</p>"
        "</body></html>"
    ).encode()


def _chapter_unit(
    url: str,
    label: str,
    number: str,
) -> dict[str, object]:
    return {
        "chapter_label": label,
        "chapter_number": number,
        "is_structural_container": False,
        "unit_kind": "chapter",
        "unit_label": label,
        "url": url,
    }


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


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Kentucky residual closure report is empty")
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


def test_kentucky_residual_closure_report_records_exact_leaf_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "KY"
    assert table["official domain"] == "apps.legislature.ky.gov"
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_section_locator"] == OFFICIAL_SECTION_LOCATOR
    assert table["official_chapter_locator"] == OFFICIAL_CHAPTER_LOCATOR
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == (
        "official KRS root/chapter/section HTML-or-PDF tree"
    )
    assert table["seed"] == (
        "v4 direct-only projection; duplicate exact-request groups preserved "
        "in the source generation and never double-counted"
    )
    assert table["duplicate_exact_request_groups"] == (
        "preserved_never_double_counted"
    )
    assert table["mixed_historical_request_identities_as_current"] == (
        "forbidden"
    )
    assert table["wayback_current_without_equivalence_proof"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["invent_later_statute_ids"] == "forbidden"
    assert table["numeric_id_range_membership"] == "forbidden"
    assert table["unique_source_ordered_leaves"] == str(
        UNIQUE_SOURCE_ORDERED_LEAVES
    )
    assert table["retained_root_pages"] == str(RETAINED_ROOT_PAGES)
    assert table["retained_chapter_catalogs"] == str(RETAINED_CHAPTER_CATALOGS)
    assert table["retained_unique_leaves"] == str(RETAINED_UNIQUE_LEAVES)
    assert table["unique_request_url_identities"] == str(
        UNIQUE_REQUEST_URL_IDENTITIES
    )
    assert table["v4_receipts"] == str(V4_RECEIPTS)
    assert table["duplicate_exact_request_extra_receipts"] == str(
        DUPLICATE_EXACT_REQUEST_EXTRA_RECEIPTS
    )
    assert table["unique_content_objects"] == str(UNIQUE_CONTENT_OBJECTS)
    assert table["unique_content_object_bytes"] == str(
        UNIQUE_CONTENT_OBJECT_BYTES
    )
    assert table["v4_direct_receipts"] == str(V4_DIRECT_RECEIPTS)
    assert table["v4_wayback_receipts"] == str(V4_WAYBACK_RECEIPTS)
    assert table["parser_input_frontier"] == str(PARSER_INPUT_FRONTIER)
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_scope"] == "original all-transport v4 diagnostic"
    assert table["residual_kind"] == "unique ordered statute.aspx leaves"
    assert table["residual_first_source_record_id"] == FIRST_SOURCE_RECORD_ID
    assert table["residual_last_source_record_id"] == LAST_SOURCE_RECORD_ID
    assert table["residual_first_url"] == FIRST_RESIDUAL_URL
    assert table["residual_last_url"] == LAST_RESIDUAL_URL
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["residual_ordered_sha256"] == RESIDUAL_SHA256
    assert table["direct_seed_selected_parser_inputs"] == str(
        DIRECT_SEED_SELECTED_INPUTS
    )
    assert table["direct_seed_unique_content_objects"] == str(
        DIRECT_SEED_UNIQUE_CONTENT_OBJECTS
    )
    assert table["direct_seed_duplicate_request_observations_avoided"] == str(
        DIRECT_SEED_DUPLICATE_OBSERVATIONS_AVOIDED
    )
    assert table["direct_seed_skipped_wayback_receipts"] == str(
        V4_WAYBACK_RECEIPTS
    )
    assert table["direct_seed_retained_unique_leaves"] == str(
        DIRECT_SEED_RETAINED_UNIQUE_LEAVES
    )
    assert table["current_live_residual_count"] == str(
        CURRENT_LIVE_RESIDUAL_COUNT
    )
    assert (
        table["current_live_residual_first_source_record_id"]
        == CURRENT_LIVE_FIRST_SOURCE_RECORD_ID
    )
    assert (
        table["current_live_residual_last_source_record_id"]
        == LAST_SOURCE_RECORD_ID
    )
    assert (
        table["current_live_residual_ordered_sha256"]
        == CURRENT_LIVE_RESIDUAL_SHA256
    )
    assert table["wayback_only_current_reacquisition_ids"] == ", ".join(
        WAYBACK_ONLY_CURRENT_REACQUISITION_IDS
    )
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["catalog_wave_name"] == CATALOG_WAVE_NAME
    assert table["root_wave_name"] == ROOT_WAVE_NAME
    assert table["hierarchy_wave_count"] == "2"
    assert table["leaf_acquisition_wave_count"] == "1"
    assert table["request_batch_count"] == "3"
    assert table["source_ordered_cross_parent_union"] == "true"
    assert table["unique_url_residual"] == "true"
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["retained_request_identity_order"] == (
        "exact legacy Accept-header GET then plain GET, in live and "
        "replay-only modes"
    )
    assert table["live_residual_request_identity"] == (
        "shared plural plain GET"
    )
    assert table["legacy_accept_header"] == LEGACY_ACCEPT
    assert table["source_bundle_prefix"] == SOURCE_BUNDLE_PREFIX
    assert table["diagnostic_producer"].startswith(DIAGNOSTIC_PRODUCER_PREFIX)
    assert table["diagnostic_hashes_authorizing"] == "false"

    assert (
        RETAINED_ROOT_PAGES
        + RETAINED_CHAPTER_CATALOGS
        + RETAINED_UNIQUE_LEAVES
        == UNIQUE_REQUEST_URL_IDENTITIES
    )
    assert (
        UNIQUE_REQUEST_URL_IDENTITIES + DUPLICATE_EXACT_REQUEST_EXTRA_RECEIPTS
        == V4_RECEIPTS
    )
    assert V4_DIRECT_RECEIPTS + V4_WAYBACK_RECEIPTS == V4_RECEIPTS
    assert (
        RETAINED_ROOT_PAGES
        + RETAINED_CHAPTER_CATALOGS
        + UNIQUE_SOURCE_ORDERED_LEAVES
        == PARSER_INPUT_FRONTIER
    )
    assert (
        UNIQUE_SOURCE_ORDERED_LEAVES - RETAINED_UNIQUE_LEAVES == RESIDUAL_COUNT
    )
    assert (
        RETAINED_ROOT_PAGES
        + RETAINED_CHAPTER_CATALOGS
        + DIRECT_SEED_RETAINED_UNIQUE_LEAVES
        == DIRECT_SEED_SELECTED_INPUTS
    )
    assert (
        UNIQUE_SOURCE_ORDERED_LEAVES - DIRECT_SEED_RETAINED_UNIQUE_LEAVES
        == CURRENT_LIVE_RESIDUAL_COUNT
    )
    assert (
        RESIDUAL_COUNT + len(WAYBACK_ONLY_CURRENT_REACQUISITION_IDS)
        == CURRENT_LIVE_RESIDUAL_COUNT
    )
    assert len(RESIDUAL_SHA256_PREFIX) == 12
    assert RESIDUAL_SHA256.startswith(RESIDUAL_SHA256_PREFIX)
    assert int(FIRST_RESIDUAL_URL.rsplit("=", 1)[-1]) != int(
        LAST_RESIDUAL_URL.rsplit("=", 1)[-1]
    )
    assert int(FIRST_RESIDUAL_URL.rsplit("=", 1)[-1]) > int(
        LAST_RESIDUAL_URL.rsplit("=", 1)[-1]
    )

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
    assert "duplicate exact-request" in lowered
    assert "never double-count" in lowered or "never double-counted" in lowered
    assert "mixed historical request" in lowered
    assert "11,641" in report
    assert "11,648" in report
    assert "40,569" in report
    assert "28,928" in report
    assert "29,682" in report
    assert "172" in report
    assert FIRST_RESIDUAL_URL in report
    assert LAST_RESIDUAL_URL in report
    assert OFFICIAL_ENTRY in report
    assert FIRST_SOURCE_RECORD_ID in report
    assert LAST_SOURCE_RECORD_ID in report
    assert RESIDUAL_SHA256_PREFIX in report
    assert RESIDUAL_SHA256 in report
    assert CURRENT_LIVE_RESIDUAL_SHA256 in report
    for source_id in WAYBACK_ONLY_CURRENT_REACQUISITION_IDS:
        assert source_id in report
    assert SOURCE_BUNDLE_PREFIX in report
    assert LEGACY_ACCEPT in report
    assert GUESSED_NEXT_URL not in report
    assert INVENTED_SECTION_URL not in report
    assert WAYBACK_CAPTURE_URL not in report
    assert report.count("statute.aspx?id=") < 16


def test_kentucky_section_locators_are_exact_and_not_inferred() -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    assert scraper.get_base_url() == "https://apps.legislature.ky.gov"
    assert scraper._KY_STATUTES_BASE == OFFICIAL_ENTRY
    assert _section_url(29404) == FIRST_RESIDUAL_URL
    assert _section_url(20428) == LAST_RESIDUAL_URL
    assert _section_url(29405) == GUESSED_NEXT_URL
    assert GUESSED_NEXT_URL != FIRST_RESIDUAL_URL
    assert _section_url(999999) == INVENTED_SECTION_URL
    assert scraper._source_record_id_from_section_url(FIRST_RESIDUAL_URL) == (
        FIRST_SOURCE_RECORD_ID
    )
    assert scraper._source_record_id_from_section_url(LAST_RESIDUAL_URL) == (
        LAST_SOURCE_RECORD_ID
    )
    assert scraper._KY_SECTION_URL_RE.search(FIRST_RESIDUAL_URL)
    assert scraper._KY_SECTION_URL_RE.search(LAST_RESIDUAL_URL)
    assert not scraper._KY_SECTION_URL_RE.search(GUESSED_NEXT_URL + "&view=1")
    with pytest.raises(RuntimeError, match="exact official source-record identity"):
        scraper._source_record_id_from_section_url(GUESSED_NEXT_URL + "&view=1")
    with pytest.raises(RuntimeError, match="exact official source-record identity"):
        scraper._source_record_id_from_section_url(WAYBACK_CAPTURE_URL)


def test_kentucky_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(KentuckyScraper)
    batched = inspect.getsource(KentuckyScraper._scrape_official_krs_tree_batched)
    fetch_source = inspect.getsource(KentuckyScraper._fetch_official_ky_frontier)
    assert str(RESIDUAL_COUNT) not in adapter
    assert str(UNIQUE_SOURCE_ORDERED_LEAVES) not in adapter
    assert str(UNIQUE_REQUEST_URL_IDENTITIES) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert SOURCE_BUNDLE_PREFIX not in adapter
    assert FIRST_RESIDUAL_URL not in adapter
    assert LAST_RESIDUAL_URL not in adapter
    assert GUESSED_NEXT_URL not in adapter
    assert INVENTED_SECTION_URL not in adapter
    assert WAYBACK_CAPTURE_URL not in adapter
    assert "29404" not in adapter
    assert "20428" not in adapter
    assert "999999" not in adapter
    assert "_section_links_from_html" in batched
    assert 'frontier_name="chapter-index"' in batched
    assert 'frontier_name="section"' in batched
    assert "Kentucky section frontier duplicated URL" in batched
    assert "common_crawl_domain_terms=(" in fetch_source
    scrape_source = inspect.getsource(KentuckyScraper.scrape_code)
    assert "return []" in scrape_source


def test_kentucky_residual_sha256_uses_canonical_json_of_ordered_unique_urls() -> None:
    compact = [FIRST_RESIDUAL_URL, LAST_RESIDUAL_URL]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=29404",'
        b'"https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=20428"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert compact_digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    doubled = [FIRST_RESIDUAL_URL, FIRST_RESIDUAL_URL, LAST_RESIDUAL_URL]
    with pytest.raises(AssertionError, match="repeated a URL"):
        _source_ordered_unique_leaf_residual(doubled, set())
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert CATALOG_WAVE_NAME in report
    assert ROOT_WAVE_NAME in report
    assert RESIDUAL_SHA256_PREFIX in report
    assert "remaining hex" in report.casefold()


def test_kentucky_one_global_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(KentuckyScraper._fetch_official_ky_frontier)
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert "common_crawl_domain_terms=(" in fetch_source
    assert '"apps.legislature.ky.gov"' in fetch_source
    assert "common_crawl_url_terms=" in fetch_source
    assert '"/law/statutes/"' in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert fetch_source.count("common_crawl_url_terms") == 1

    retry_source = inspect.getsource(
        KentuckyScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in (
        retry_source
    )
    assert "no per-page archive loop" in retry_source

    batched = inspect.getsource(KentuckyScraper._scrape_official_krs_tree_batched)
    assert 'frontier_name="section"' in batched
    assert batched.count('frontier_name="section"') == 2
    assert "cross-chapter descendant union" in batched

    closure_source = inspect.getsource(
        KentuckyScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"residual_only_retries": True' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source


def test_kentucky_seed_and_host_replay_forbid_hub_docker_and_mixed_identities(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source
    assert "unverifiable Wayback receipts" in seed_source
    seed_module_source = inspect.getsource(seed_module)
    assert "deduplicates identical request identities" in seed_module_source
    assert "duplicate_request_observations_avoided" in seed_module_source
    assert "allowed retained observations disagree for one exact request" in (
        seed_module_source
    )

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "KY",
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
    assert "mixed historical request" in report
    assert "duplicate exact-request" in report


def test_kentucky_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    kentucky_source = inspect.getsource(
        KentuckyScraper.produce_state_law_frontier_closure
    )
    replay_source = inspect.getsource(KentuckyScraper._replay_official_ky_frontier)
    assert "public_law_no_state_copyright" in kentucky_source or (
        "rights" in closure_source.casefold()
    )
    assert "retained_replay_network_requests" in kentucky_source
    assert kentucky_source.index('"retained_replay_network_requests": 0') > 0
    assert "without permitting network I/O" in replay_source
    assert '"method": "GET", "url": url' in replay_source
    assert '"Accept": accept' in replay_source


def test_kentucky_duplicate_exact_request_groups_are_preserved_and_never_double_counted() -> None:
    retained_a = _section_url(101)
    retained_b = _section_url(102)
    residual_first = FIRST_RESIDUAL_URL
    residual_last = LAST_RESIDUAL_URL
    digest_a = hashlib.sha256(_section_payload("1.010")).hexdigest()
    digest_b = hashlib.sha256(_section_payload("1.020")).hexdigest()
    digest_first = hashlib.sha256(_section_payload("residual-first")).hexdigest()
    digest_last = hashlib.sha256(_section_payload("residual-last")).hexdigest()
    observations = [
        (retained_a, _plain_get(retained_a), digest_a),
        (retained_a, _plain_get(retained_a), digest_a),
        (retained_b, _legacy_accept_get(retained_b), digest_b),
        (retained_b, _plain_get(retained_b), digest_b),
        (residual_first, _plain_get(residual_first), digest_first),
        (residual_last, _plain_get(residual_last), digest_last),
    ]
    unique_urls, extras = _unique_urls_and_duplicate_extras(observations)
    assert unique_urls == [
        retained_a,
        retained_b,
        residual_first,
        residual_last,
    ]
    assert extras == 1
    residual = _source_ordered_unique_leaf_residual(
        unique_urls,
        {retained_a, retained_b},
    )
    assert residual == [residual_first, residual_last]
    assert GUESSED_NEXT_URL not in residual
    assert INVENTED_SECTION_URL not in residual
    assert WAYBACK_CAPTURE_URL not in residual
    assert len(residual) == 2
    disagreeing = [
        (retained_a, _plain_get(retained_a), digest_a),
        (retained_a, _plain_get(retained_a), digest_b),
    ]
    with pytest.raises(AssertionError, match="disagreeing content"):
        _unique_urls_and_duplicate_extras(disagreeing)

    report = " ".join(_report_text().casefold().split())
    assert "duplicate exact-request" in report
    assert "never double-count" in report or "never double-counted" in report
    assert "172" in _report_text()


def test_kentucky_replay_only_probes_plain_and_legacy_without_creating_residual_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    plain_url = CHAPTER_URLS[0]
    legacy_url = CHAPTER_URLS[1]
    plain_body = _chapter_payload((101, ".010 Legislative intent."))
    legacy_body = _chapter_payload((201, ".010 Public administration."))
    seed = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="KY",
        parser_name="KentuckyScraper",
    )
    seed.retain_parser_input(
        official_url=plain_url,
        body=plain_body,
        transport_receipt={
            "content_sha256": hashlib.sha256(plain_body).hexdigest(),
            "official_url": plain_url,
            "source_transport": "direct",
        },
        retrieved_at="2026-08-26T00:00:00+00:00",
        sanitized_request=_plain_get(plain_url),
    )
    seed.retain_parser_input(
        official_url=legacy_url,
        body=legacy_body,
        transport_receipt={
            "content_sha256": hashlib.sha256(legacy_body).hexdigest(),
            "official_url": legacy_url,
            "source_transport": "direct",
        },
        retrieved_at="2026-08-26T00:00:00+00:00",
        sanitized_request=_legacy_accept_get(legacy_url),
    )
    replay = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="KY",
        parser_name="KentuckyScraper",
        retained_replay_only=True,
    )
    scraper = KentuckyScraper("KY", "Kentucky")
    scraper.attach_state_law_acquisition_ledger(replay)

    async def _forbid_transport(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "Kentucky replay-only must not treat mixed identities as residual"
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _forbid_transport,
    )

    assert asyncio.run(
        scraper._fetch_official_ky_frontier(
            [plain_url, legacy_url],
            frontier_name=CATALOG_WAVE_NAME,
            timeout_seconds=1,
            content_validator=scraper._looks_like_kentucky_chapter_payload,
        )
    ) == [plain_body, legacy_body]
    unique_urls, extras = _unique_urls_and_duplicate_extras(
        [
            (
                plain_url,
                _plain_get(plain_url),
                hashlib.sha256(plain_body).hexdigest(),
            ),
            (
                legacy_url,
                _legacy_accept_get(legacy_url),
                hashlib.sha256(legacy_body).hexdigest(),
            ),
        ]
    )
    assert unique_urls == [plain_url, legacy_url]
    assert extras == 0
    assert _source_ordered_unique_leaf_residual(
        unique_urls,
        set(unique_urls),
    ) == []


def test_kentucky_live_frontier_reuses_plain_current_identity_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = FIRST_RESIDUAL_URL
    body = _section_payload("residual-first")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="KY",
        parser_name="KentuckyScraper",
    )
    ledger.retain_parser_input(
        official_url=url,
        body=body,
        transport_receipt={
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "official_url": url,
            "source_transport": "direct",
        },
        retrieved_at="2026-08-26T00:00:00+00:00",
        sanitized_request=_plain_get(url),
    )
    scraper = KentuckyScraper("KY", "Kentucky")
    scraper.attach_state_law_acquisition_ledger(ledger)
    replay_calls: list[dict[str, Any]] = []
    replay_retained = ledger.replay_retained_parser_input

    def _record_replay(*, official_url: str, sanitized_request: Mapping[str, Any]):
        replay_calls.append(dict(sanitized_request))
        return replay_retained(
            official_url=official_url,
            sanitized_request=sanitized_request,
        )

    async def _forbid_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a retained current plain GET must avoid network")

    monkeypatch.setattr(ledger, "replay_retained_parser_input", _record_replay)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _forbid_network,
    )

    assert asyncio.run(
        scraper._fetch_official_ky_frontier(
            [url],
            frontier_name=RESIDUAL_WAVE_NAME,
            timeout_seconds=1,
            content_validator=scraper._looks_like_kentucky_section_payload,
        )
    ) == [body]
    assert replay_calls == [_legacy_accept_get(url), _plain_get(url)]
    fetch_source = inspect.getsource(KentuckyScraper._fetch_official_ky_frontier)
    assert '{"method": "GET", "url": url}' in fetch_source
    report = " ".join(_report_text().casefold().split())
    assert "live residual" in report
    assert "ordinary get" in report
    assert "mixed historical request identities as current" in report


def test_kentucky_replay_only_probes_accept_then_plain_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = FIRST_RESIDUAL_URL
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="KY",
        parser_name="KentuckyScraper",
        retained_replay_only=True,
    )
    scraper = KentuckyScraper("KY", "Kentucky")
    scraper.attach_state_law_acquisition_ledger(ledger)
    replay_calls: list[dict[str, Any]] = []
    replay_retained = ledger.replay_retained_parser_input

    def _record_replay(*, official_url: str, sanitized_request: Mapping[str, Any]):
        replay_calls.append(dict(sanitized_request))
        return replay_retained(
            official_url=official_url,
            sanitized_request=sanitized_request,
        )

    monkeypatch.setattr(ledger, "replay_retained_parser_input", _record_replay)
    with pytest.raises(
        StateLawRetainedReplayOnlyError,
        match="every exact Kentucky parser request variant",
    ):
        asyncio.run(
            scraper._fetch_official_ky_frontier(
                [url],
                frontier_name=RESIDUAL_WAVE_NAME,
                timeout_seconds=1,
                content_validator=scraper._looks_like_kentucky_section_payload,
            )
        )

    assert replay_calls == [_legacy_accept_get(url), _plain_get(url)]


def test_kentucky_compact_recipe_emits_unique_leaves_not_invented_or_double_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    scraper._write_partial_checkpoint = lambda *_args, **_kwargs: False
    retained_url = _section_url(101)
    residual_urls = [FIRST_RESIDUAL_URL, LAST_RESIDUAL_URL]
    section_urls = [retained_url, *residual_urls]
    chapter_units = [
        _chapter_unit(CHAPTER_URLS[0], "CHAPTER 1 GENERAL PROVISIONS", "1"),
        _chapter_unit(CHAPTER_URLS[1], "CHAPTER 2 PUBLIC ADMINISTRATION", "2"),
    ]
    pages = {
        CHAPTER_URLS[0]: _chapter_payload(
            (101, ".010 Legislative intent."),
            (29404, ".020 Residual first."),
        ),
        CHAPTER_URLS[1]: _chapter_payload((20428, ".010 Residual last.")),
        retained_url: _section_payload("1.010"),
        FIRST_RESIDUAL_URL: _section_payload("1.020"),
        LAST_RESIDUAL_URL: _section_payload("2.010"),
    }
    batch_calls: list[tuple[str, list[str]]] = []

    async def _frontier(
        urls,
        *,
        frontier_name: str,
        **_kwargs: Any,
    ) -> list[bytes]:
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        assert INVENTED_SECTION_URL not in requested
        assert GUESSED_NEXT_URL not in requested
        assert WAYBACK_CAPTURE_URL not in requested
        assert len(requested) == len(set(requested))
        return [pages[url] for url in requested]

    async def _extract(*, source_url: str, raw_bytes: bytes) -> dict[str, str]:
        assert raw_bytes == pages[source_url]
        section_number = {
            retained_url: "1.010",
            FIRST_RESIDUAL_URL: "1.020",
            LAST_RESIDUAL_URL: "2.010",
        }[source_url]
        return {
            "text": (
                f"KRS {section_number} Complete official Kentucky statutory "
                "text retained for unique-leaf residual closure."
            ),
            "method": "test_html",
        }

    monkeypatch.setattr(scraper, "_fetch_official_ky_frontier", _frontier)
    monkeypatch.setattr(scraper, "_extract_text_from_document_bytes", _extract)

    rows = asyncio.run(
        scraper._scrape_official_krs_tree_batched(
            code_name="Kentucky Revised Statutes",
            chapter_units=chapter_units,
        )
    )

    assert [name for name, _urls in batch_calls] == [
        CATALOG_WAVE_NAME,
        RESIDUAL_WAVE_NAME,
    ]
    assert batch_calls[0][1] == CHAPTER_URLS
    assert batch_calls[1][1] == section_urls
    assert [row.source_url for row in rows] == section_urls
    residual = _source_ordered_unique_leaf_residual(
        section_urls,
        {retained_url},
    )
    assert residual == residual_urls
    assert residual[0] == FIRST_RESIDUAL_URL
    assert residual[-1] == LAST_RESIDUAL_URL
    digest = _canonical_residual_sha256(residual)
    assert digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    assert len(digest) == 64
    assert scraper._last_kentucky_full_frontier["section_locators_discovered"] == 3
    assert scraper._last_kentucky_full_frontier["statutes_emitted"] == 3


def test_kentucky_retained_replay_only_miss_does_not_invent_or_per_page_loop(
    tmp_path: Path,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    replay = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="KY",
        parser_name="KentuckyScraper",
        retained_replay_only=True,
    )
    scraper.attach_state_law_acquisition_ledger(replay)
    with pytest.raises(
        StateLawRetainedReplayOnlyError,
        match="every exact Kentucky parser request variant",
    ):
        scraper._replay_official_ky_frontier(
            [FIRST_RESIDUAL_URL],
            frontier_name=RESIDUAL_WAVE_NAME,
            content_validator=scraper._looks_like_kentucky_section_payload,
        )
    fetch_source = inspect.getsource(KentuckyScraper._fetch_official_ky_frontier)
    replay_source = inspect.getsource(
        KentuckyScraper._replay_retained_ky_request_variants
    )
    assert "probe both" in replay_source
    assert "without network" in replay_source
    assert INVENTED_SECTION_URL not in fetch_source
    assert GUESSED_NEXT_URL not in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "per-page" not in fetch_source.casefold()
    report = _report_text()
    assert FIRST_RESIDUAL_URL in report
    assert "numeric id range" in report.casefold()

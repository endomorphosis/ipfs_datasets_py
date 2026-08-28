"""LCR-100: Georgia catalog-then-current-body residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, legislative-summary PDFs, and the
two-row artifact.
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import (
    GeorgiaFullCorpusIncompleteError,
    GeorgiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archive import (
    official_section_url,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archived_official import (
    GeorgiaArchivedOfficialCorpusError,
    acquire_georgia_archived_official_corpus,
    acquire_georgia_archived_official_with_shared_transport,
    build_georgia_delegated_inventory,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_lexis import (
    ADVANCE_ORIGIN,
    EXPECTED_TITLE_NUMBERS,
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    GeorgiaLexisDiscoveryResult,
    _bind_live_toc_nodes,
    _mark_live_expansion_closed,
    discover_live_georgia_lexis_toc,
    parse_georgia_lexis_document_html,
    parse_toc_dom_rows,
    parse_toc_payload,
    toc_open_to_request,
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
    / "georgia_residual_closure_v1.md"
)

CATALOG_TITLES = 53
CATALOG_NODES = 36120
CATALOG_EXPANDABLE_NODES = 3970
CATALOG_ROOT_GETS = 1
CATALOG_TITLE_PATCHES = 53
CATALOG_INPUTS = 54
TEMPORAL_SECTION_LOCATORS = 29358
CURRENT_IDENTITIES = 29165
TEMPORAL_EXCLUSIONS = 193
EXPECTED_OPERATIVE_BODIES = 28417
SOURCE_MARKED_NONOPERATIVE_TERMINALS = 748
RETAINED_BODY_REQUESTS = 0
RESIDUAL_COUNT = 29165
RESIDUAL_WAVE_NAME = "source-ordered-current-section-bodies"
CATALOG_WAVE_NAME = "delegated-toc-title-open-to"
RESIDUAL_SHA256_PREFIX = "source_derived_after_retained_catalog"
DIAGNOSTIC_ROOT_RENDERED_PREFIX = "a31f9c8"
DIAGNOSTIC_CURRENT_LOCATOR_PREFIX = "2b9646e"
DIAGNOSTIC_CATALOG_FRONTIER_PREFIX = "5d3182a"
SOURCE_BUNDLE_PREFIX = "af026c4"
OFFICIAL_ENTRY = "https://www.legis.ga.gov/legislation/georgia-code"
INVENTED_SECTION_URL = (
    "https://www.legis.ga.gov/legislation/georgia-code/title-99/"
    "chapter-1/section-99-1-1"
)
SUMMARY_PDF_2025 = (
    "https://www.legis.ga.gov/api/document/docs/default-source/"
    "legislative-counsel-document-library/25sumdoc.pdf?sfvrsn=95973fc9_4"
)
SUMMARY_PDF_2024 = (
    "https://www.legis.ga.gov/api/document/docs/default-source/"
    "legislative-counsel-document-library/"
    "2024-general-statutes-summary-pdf.pdf?sfvrsn=38862f9_8"
)
OBSERVED_AT = "2026-08-26T00:34:55+00:00"


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _source_ordered_current_body_urls(inventory: dict[str, object]) -> list[str]:
    frontier = inventory["frontier"]
    assert isinstance(frontier, dict)
    urls: list[str] = []
    seen: set[str] = set()
    for row in frontier["sections"]:
        assert isinstance(row, dict)
        url = official_section_url(str(row["section_number"]))
        if url in seen:
            raise AssertionError(
                "Georgia current-section residual frontier repeated a URL"
            )
        seen.add(url)
        urls.append(url)
    return urls


def _section_html(section: str) -> bytes:
    heading = (
        f"{section}. [Repealed] Official provision."
        if section == "21-2-140"
        else f"{section}. Official provision."
    )
    return (
        "<html><body><main>"
        f"<h1>{heading}</h1>"
        "<p>"
        + ("The enacted text of this Georgia statute remains complete. " * 12)
        + "</p>"
        "<h2>Editor's Notes</h2>"
        "<p>Publisher editorial discussion must never enter the statute body.</p>"
        "</main></body></html>"
    ).encode()


def _toc_pricing() -> dict[str, object]:
    return {
        "currencycode": "USD",
        "listprice": 0,
        "netprice": 0,
        "purchaserequired": False,
        "usagetypecode": "subscription",
        "documentstatus": "Available",
    }


def _section_raw_node(
    *,
    node_id: str,
    node_path: str,
    heading: str,
    urn: str,
) -> dict[str, object]:
    return {
        "id": node_id,
        "props": {
            "linktemplatetitle": heading,
            "level": 3,
            "nodepath": node_path,
            "canopen": True,
            "haschildren": False,
            "linkhref": f"/shared/document/statutes-legislation/{urn}",
            "subscribed": True,
            "tocpricing": _toc_pricing(),
        },
        "data": {},
    }


def _compact_delegated_discovery(
    evidence_root: Path | None = None,
) -> GeorgiaLexisDiscoveryResult:
    """Title 1-53 catalog recipe with one temporal alternate and one terminal."""

    root_payload = b"<html><body>Exact Georgia Title 1-53 fixture catalog</body></html>"
    root_sha256 = hashlib.sha256(root_payload).hexdigest()
    root_relative = f"root-rendered-{root_sha256}.html"
    if evidence_root is not None:
        evidence_root.mkdir(parents=True, exist_ok=True)
        (evidence_root / root_relative).write_bytes(root_payload)
    root_rows = [
        {
            "nodeid": f"T{title:02d}",
            "title": f"TITLE {title} Fixture title",
            "level": "1",
            "nodepath": f"/ROOT/T{title:02d}",
            "haschildren": "true",
        }
        for title in range(1, 54)
    ]
    roots = _bind_live_toc_nodes(
        parse_toc_dom_rows(root_rows),
        source_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        receipt_sha256=root_sha256,
    )
    nodes: list[object] = []
    expanded: list[str] = []
    patch_hashes: list[tuple[str, str]] = []
    patch_paths: list[tuple[str, str]] = []
    for title, root in enumerate(roots, start=1):
        chapter_id = f"C{title:02d}"
        section_id = f"S{title:02d}"
        if title == 21:
            heading = "21-2-140. [Repealed] Mandatory drug testing."
        elif title == 25:
            heading = (
                "25-4-8. [Effective until July 1, 2027] Qualifications."
            )
        else:
            heading = f"{title}-1-1. Test provision for Title {title}."
        raw_nodes: list[dict[str, object]] = [
            {
                "id": chapter_id,
                "props": {
                    "linktemplatetitle": "CHAPTER 1 Fixture chapter",
                    "level": 2,
                    "nodepath": f"{root.node_path}/{chapter_id}",
                    "canexpand": True,
                    "haschildren": True,
                },
                "data": {},
            },
            _section_raw_node(
                node_id=section_id,
                node_path=f"{root.node_path}/{chapter_id}/{section_id}",
                heading=heading,
                urn=f"urn:contentItem:GA{title:02d}-TEST-BODY-00000-00",
            ),
        ]
        if title == 25:
            raw_nodes.append(
                _section_raw_node(
                    node_id="S25X",
                    node_path=f"{root.node_path}/{chapter_id}/S25X",
                    heading="25-4-8. [Effective July 1, 2027] Qualifications.",
                    urn="urn:contentItem:GA25-FUTURE-BODY-00000-00",
                )
            )
        patch_payload = json.dumps(
            {"collections": {"tocnodes": raw_nodes}},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        receipt_sha256 = hashlib.sha256(patch_payload).hexdigest()
        patch_relative = (
            f"title-open-to/{root.node_id}-{receipt_sha256}.json"
        )
        if evidence_root is not None:
            patch_path = evidence_root / patch_relative
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_path.write_bytes(patch_payload)
        bound = _bind_live_toc_nodes(
            parse_toc_payload({"collections": {"tocnodes": raw_nodes}}),
            source_url=PUBLIC_CONTAINER_URL,
            observed_at=OBSERVED_AT,
            receipt_sha256=receipt_sha256,
        )
        closed_root = _mark_live_expansion_closed(root)
        closed_chapter = _mark_live_expansion_closed(bound[0])
        assert closed_root is not None
        assert closed_chapter is not None
        nodes.extend([closed_root, closed_chapter, *bound[1:]])
        expanded.extend([root.node_id, chapter_id])
        patch_hashes.extend(
            [
                (root.node_id, receipt_sha256),
                (chapter_id, receipt_sha256),
            ]
        )
        patch_paths.extend(
            [
                (root.node_id, patch_relative),
                (chapter_id, patch_relative),
            ]
        )
    return GeorgiaLexisDiscoveryResult(
        status="official_toc",
        final_url=PUBLIC_CONTAINER_URL,
        delegation_verified=True,
        nodes=tuple(nodes),
        expanded_node_ids=tuple(expanded),
        diagnostics=(),
        observed_at=OBSERVED_AT,
        root_rendered_sha256=root_sha256,
        patch_response_sha256=tuple(patch_hashes),
        root_rendered_path=root_relative,
        patch_response_paths=tuple(patch_paths),
    )


def _frontier_result(
    urls: list[str],
    payloads: list[bytes],
) -> StateLawPageMultiFetchResult:
    receipts = []
    envelopes = []
    retrieved_at = OBSERVED_AT
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
                acquisition=SimpleNamespace(
                    receipt=SimpleNamespace(retrieved_at=retrieved_at)
                )
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
            "common_crawl_inventory_queries": 1,
            "common_crawl": {
                "range_fetch_calls": 1,
                "naive_range_fetches": len(urls),
                "range_fetches_avoided": max(0, len(urls) - 1),
            },
        },
    )


class _SharedPageBatchFetcher:
    def __init__(self) -> None:
        self.requests: list[tuple[list[str], dict[str, object]]] = []

    async def __call__(
        self,
        urls: list[str],
        **kwargs: object,
    ) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        self.requests.append((requested, dict(kwargs)))
        return _frontier_result(
            requested, [_section_html(url.rsplit("section-", 1)[-1]) for url in requested]
        )


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Georgia residual closure report is empty")
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


def test_georgia_residual_closure_report_records_exact_catalog_then_body_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "GA"
    assert table["official domain"] == "www.legis.ga.gov"
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_delegated_entry"] == PUBLIC_ENTRY_URL
    assert table["official_container"] == PUBLIC_CONTAINER_URL
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == (
        "delegated Lexis TOC then official legis.ga.gov bodies"
    )
    assert table["retain_root_and_title_patch_bytes_first"] == "true"
    assert table["fetch_catalog_before_bodies"] == "true"
    assert table["import_legislative_summary_pdfs"] == "forbidden"
    assert table["import_two_row_artifact"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["invent_later_section_targets"] == "forbidden"
    assert table["catalog_titles"] == str(CATALOG_TITLES)
    assert table["catalog_nodes"] == str(CATALOG_NODES)
    assert table["catalog_expandable_nodes"] == str(CATALOG_EXPANDABLE_NODES)
    assert table["catalog_root_gets"] == str(CATALOG_ROOT_GETS)
    assert table["catalog_title_patches"] == str(CATALOG_TITLE_PATCHES)
    assert table["catalog_inputs"] == str(CATALOG_INPUTS)
    assert table["catalog_bytes_retained"] == "0"
    assert table["temporal_section_locators"] == str(TEMPORAL_SECTION_LOCATORS)
    assert table["current_identities"] == str(CURRENT_IDENTITIES)
    assert table["temporal_exclusions"] == str(TEMPORAL_EXCLUSIONS)
    assert table["expected_operative_bodies"] == str(EXPECTED_OPERATIVE_BODIES)
    assert table["source_marked_nonoperative_terminals"] == str(
        SOURCE_MARKED_NONOPERATIVE_TERMINALS
    )
    assert table["retained_body_requests"] == str(RETAINED_BODY_REQUESTS)
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == (
        "catalog then unique ordered current official section URLs"
    )
    assert table["catalog_wave_name"] == CATALOG_WAVE_NAME
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["catalog_acquisition_wave_count"] == "1"
    assert table["leaf_acquisition_wave_count"] == "1"
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["diagnostic_root_rendered_sha256_prefix"] == (
        DIAGNOSTIC_ROOT_RENDERED_PREFIX
    )
    assert table["diagnostic_current_locator_digest_prefix"] == (
        DIAGNOSTIC_CURRENT_LOCATOR_PREFIX
    )
    assert table["diagnostic_catalog_frontier_digest_prefix"] == (
        DIAGNOSTIC_CATALOG_FRONTIER_PREFIX
    )
    assert table["diagnostic_hashes_authorizing"] == "false"
    assert table["source_bundle_prefix"] == SOURCE_BUNDLE_PREFIX
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert (
        int(table["catalog_root_gets"]) + int(table["catalog_title_patches"])
        == CATALOG_INPUTS
    )
    assert TEMPORAL_EXCLUSIONS + CURRENT_IDENTITIES == TEMPORAL_SECTION_LOCATORS
    assert (
        EXPECTED_OPERATIVE_BODIES + SOURCE_MARKED_NONOPERATIVE_TERMINALS
        == CURRENT_IDENTITIES
    )
    assert RETAINED_BODY_REQUESTS + RESIDUAL_COUNT == CURRENT_IDENTITIES

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "retain" in lowered and "title-patch" in lowered
    assert "catalog" in lowered and "29,165" in report
    assert "hub mutation" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "legislative-summary" in lowered or "25sumdoc.pdf" in report
    assert "two-row" in lowered
    assert "36,120" in report
    assert "3,970" in report
    assert PUBLIC_CONTAINER_URL in report
    assert PUBLIC_ENTRY_URL in report
    assert OFFICIAL_ENTRY in report
    assert INVENTED_SECTION_URL not in report
    assert report.count("https://www.legis.ga.gov/legislation/georgia-code/title-") < 8
    assert not re.search(r"residual_ordered_sha256_prefix.*[0-9a-f]{12}", report)


def test_georgia_catalog_is_delegated_toc_then_official_section_bodies() -> None:
    scraper = GeorgiaScraper("GA", "Georgia")
    assert scraper.get_base_url() == "https://www.legis.ga.gov"
    assert scraper.OFFICIAL_ENTRY_URL == OFFICIAL_ENTRY
    assert scraper.official_section_url("1-1-1") == official_section_url("1-1-1")
    assert list(EXPECTED_TITLE_NUMBERS) == [str(number) for number in range(1, 54)]
    assert len(scraper.OFFICIAL_TITLES) == CATALOG_TITLES

    discovery_source = inspect.getsource(discover_live_georgia_lexis_toc)
    assert "exhaustive" in discovery_source
    assert "toc_open_to_request" in discovery_source
    assert "title-open-to/" in discovery_source
    discovery_doc = inspect.getdoc(discover_live_georgia_lexis_toc) or ""
    assert "one nested `open-to`" in discovery_doc or "one nested ``open-to``" in (
        discovery_source
    )
    open_to_source = inspect.getsource(toc_open_to_request)
    assert '"action": "open-to"' in open_to_source
    assert parse_georgia_lexis_document_html(
        "<html><body>not a live receipt</body></html>",
        source_url=f"{ADVANCE_ORIGIN}/shared/document/statutes-legislation/urn:contentItem:GA01-TEST-00000-00",
        expected_section="1-1-1",
    ) is None

    acquire_source = inspect.getsource(acquire_georgia_archived_official_corpus)
    assert "official_section_url(row[\"section_number\"])" in acquire_source
    assert 'common_crawl_domain_terms=("www.legis.ga.gov", "legis.ga.gov")' in (
        acquire_source
    )
    assert 'common_crawl_url_terms=("/legislation/georgia-code/",)' in acquire_source
    assert "wayback_prefix_inventory=True" in acquire_source
    assert "require_batched_transport: bool = True" in acquire_source


def test_georgia_adapter_has_no_static_body_residual_url_list() -> None:
    scraper_source = inspect.getsource(GeorgiaScraper)
    archived_source = inspect.getsource(
        inspect.getmodule(acquire_georgia_archived_official_corpus)
    )
    lexis_module = inspect.getmodule(discover_live_georgia_lexis_toc)
    assert lexis_module is not None
    lexis_source = inspect.getsource(lexis_module)
    for payload in (scraper_source, archived_source, lexis_source):
        assert str(RESIDUAL_COUNT) not in payload
        assert str(CURRENT_IDENTITIES) not in payload
        assert str(TEMPORAL_SECTION_LOCATORS) not in payload
        assert RESIDUAL_SHA256_PREFIX not in payload
        assert INVENTED_SECTION_URL not in payload
    assert "99-1-1" not in scraper_source
    scrape_source = inspect.getsource(GeorgiaScraper.scrape_code)
    incomplete_index = scrape_source.index("GeorgiaFullCorpusIncompleteError")
    summary_index = scrape_source.index("_scrape_general_statute_summary_pdfs")
    assert incomplete_index < summary_index
    assert scraper_source.count("https://www.legis.ga.gov") < 20


def test_georgia_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    compact = [
        official_section_url("1-1-1"),
        official_section_url("53-1-1"),
    ]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://www.legis.ga.gov/legislation/georgia-code/title-1/'
        b'chapter-1/section-1-1-1",'
        b'"https://www.legis.ga.gov/legislation/georgia-code/title-53/'
        b'chapter-1/section-53-1-1"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert compact_digest != RESIDUAL_SHA256_PREFIX
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert CATALOG_WAVE_NAME in report


def test_georgia_one_global_wave_disables_per_page_archive_and_reinventory() -> None:
    acquire_source = inspect.getsource(acquire_georgia_archived_official_corpus)
    wrapper_source = inspect.getsource(
        acquire_georgia_archived_official_with_shared_transport
    )
    retry_source = inspect.getsource(
        GeorgiaScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "require_batched_transport: bool = True" in acquire_source
    assert (
        "exact body acquisition requires the shared archival multi-fetch transport"
        in acquire_source
    )
    assert "legacy_per_page_fallback" in acquire_source
    assert "second per-page archive path" in wrapper_source
    assert "page_batch_fetcher=scraper._fetch_page_contents_with_archival_fallback" in (
        wrapper_source
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source
    assert "archive.is" not in wrapper_source.casefold()

    closure_source = inspect.getsource(
        GeorgiaScraper.produce_state_law_frontier_closure
    )
    assert '"retained_replay_network_requests": 0' in closure_source
    assert "shared_archive_aware_plural_archived_html" in closure_source


def test_georgia_seed_and_host_replay_forbid_hub_docker_and_summary_pdfs(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "GA",
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
    assert "legislative-summary" in report or "25sumdoc.pdf" in report
    assert "two-row" in report


def test_georgia_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    georgia_source = inspect.getsource(
        GeorgiaScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in georgia_source or (
        "rights" in closure_source.casefold()
    )
    assert "retained_replay_network_requests" in georgia_source
    assert georgia_source.index('"retained_replay_network_requests": 0') > 0
    assert "the exact Title 1-53 set" in inspect.getsource(
        GeorgiaScraper._georgia_archived_exact_frontier
    )


def test_georgia_compact_catalog_recipe_emits_current_bodies_not_invented_or_summary_targets() -> None:
    discovery = _compact_delegated_discovery()
    inventory = build_georgia_delegated_inventory(
        discovery,
        edition_as_of="2026-08-26",
        edition_identifier="ocga-2026-08-26",
    )
    assert inventory["root_rendered_path"]
    assert inventory["patch_response_paths"]
    assert len(inventory["patch_response_sha256"]) == CATALOG_TITLES * 2
    frontier = inventory["frontier"]
    assert frontier["title_numbers"] == list(EXPECTED_TITLE_NUMBERS)
    assert frontier["discovered_section_count"] == CATALOG_TITLES
    assert frontier["discovered_temporal_locator_count"] == CATALOG_TITLES + 1
    assert frontier["temporal_exclusion_count"] == 1
    sections = {row["section_number"]: row for row in frontier["sections"]}
    assert "25-4-8" in sections
    assert sections["25-4-8"]["expected_disposition"] == "admit"
    assert sections["21-2-140"]["expected_disposition"] == "exclude_nonoperative"
    excluded = [row["section_number"] for row in frontier["temporal_exclusions"]]
    assert excluded == ["25-4-8"]

    residual = _source_ordered_current_body_urls(inventory)
    assert len(residual) == CATALOG_TITLES
    assert residual[0] == official_section_url("1-1-1")
    assert official_section_url("21-2-140") in residual
    assert official_section_url("25-4-8") in residual
    assert INVENTED_SECTION_URL not in residual
    assert SUMMARY_PDF_2025 not in residual
    assert SUMMARY_PDF_2024 not in residual
    assert all(url.startswith(f"{OFFICIAL_ENTRY}/title-") for url in residual)
    digest = _canonical_residual_sha256(residual)
    assert digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    assert len(digest) == 64


def test_georgia_invented_later_section_fails_closed_on_title_1_53_membership() -> None:
    discovery = _compact_delegated_discovery()
    extra_root = parse_toc_dom_rows(
        [
            {
                "nodeid": "T99",
                "title": "TITLE 99 Invented title",
                "level": "1",
                "nodepath": "/ROOT/T99",
                "haschildren": "true",
            }
        ]
    )
    with pytest.raises(
        GeorgiaArchivedOfficialCorpusError,
        match="exact ordered Title 1-53 frontier",
    ):
        build_georgia_delegated_inventory(
            GeorgiaLexisDiscoveryResult(
                status=discovery.status,
                final_url=discovery.final_url,
                delegation_verified=True,
                nodes=discovery.nodes + tuple(
                    _bind_live_toc_nodes(
                        extra_root,
                        source_url=PUBLIC_CONTAINER_URL,
                        observed_at=OBSERVED_AT,
                        receipt_sha256="a" * 64,
                    )
                ),
                expanded_node_ids=discovery.expanded_node_ids,
                diagnostics=(),
                observed_at=OBSERVED_AT,
                root_rendered_sha256=discovery.root_rendered_sha256,
                patch_response_sha256=discovery.patch_response_sha256,
            ),
            edition_as_of="2026-08-26",
            edition_identifier="ocga-2026-08-26",
        )


def test_georgia_full_corpus_refuses_summary_pdfs_and_two_row_artifact_before_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "GEORGIA_ARCHIVED_OFFICIAL_MANIFEST",
        "GEORGIA_TITLE_TEXT",
        "GEORGIA_TITLE_PDF",
        "GEORGIA_TITLE_TEXT_DIR",
        "GEORGIA_TITLE_PDF_DIR",
        "GEORGIA_SUMMARY_PDF_FALLBACK",
        "GEORGIA_JUSTIA_ENABLE",
        "STATE_SCRAPER_GA_ALLOW_JUSTIA_FALLBACK",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    scraper = GeorgiaScraper("GA", "Georgia")
    summary_calls: list[str] = []

    async def _summary(self, code_name: str):
        summary_calls.append(code_name)
        return []

    monkeypatch.setattr(
        GeorgiaScraper, "_scrape_general_statute_summary_pdfs", _summary
    )

    with pytest.raises(GeorgiaFullCorpusIncompleteError) as exc_info:
        asyncio.run(
            scraper.scrape_code(
                "Official Code of Georgia Annotated",
                OFFICIAL_ENTRY,
                max_statutes=None,
            )
        )

    assert summary_calls == []
    assert exc_info.value.evidence["full_corpus_admissible"] is False
    assert "delegated Lexis discovery is bounded" in str(exc_info.value)
    assert parse_georgia_lexis_document_html(
        "summary pdf text",
        source_url=SUMMARY_PDF_2025,
        expected_section="2025",
    ) is None


def test_georgia_complete_current_union_is_one_plural_wave_after_catalog(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "ga-residual"
    inventory = build_georgia_delegated_inventory(
        _compact_delegated_discovery(output_root),
        edition_as_of="2026-08-26",
        edition_identifier="ocga-2026-08-26",
    )
    residual = _source_ordered_current_body_urls(inventory)
    fetcher = _SharedPageBatchFetcher()

    result = asyncio.run(
        acquire_georgia_archived_official_corpus(
            inventory,
            output_root,
            page_batch_fetcher=fetcher,
            prefer_direct=True,
        )
    )

    assert fetcher.requests and len(fetcher.requests) == 1
    requested, kwargs = fetcher.requests[0]
    assert requested == residual
    assert INVENTED_SECTION_URL not in requested
    assert SUMMARY_PDF_2025 not in requested
    assert SUMMARY_PDF_2024 not in requested
    assert kwargs["prefer_direct"] is True
    assert kwargs["wayback_prefix_inventory"] is True
    assert kwargs["common_crawl_domain_terms"] == (
        "www.legis.ga.gov",
        "legis.ga.gov",
    )
    assert kwargs["common_crawl_url_terms"] == ("/legislation/georgia-code/",)
    assert result["closed"] is True
    assert result["manifest"]["transport_batch"]["common_crawl_inventory_queries"] == 1
    assert all(
        row["official_url"].startswith(f"{OFFICIAL_ENTRY}/title-")
        for row in result["manifest"]["artifacts"]
    )
    assert _canonical_residual_sha256(requested) == _canonical_residual_sha256(
        residual
    )

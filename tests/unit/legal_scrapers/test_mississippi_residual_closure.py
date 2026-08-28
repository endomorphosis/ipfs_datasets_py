"""LCR-102: Mississippi delegated Lexis catalog-then-body residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded 30,345-input residual and the production contracts that forbid
Hub mutation, static lists, per-page archive loops, invented even-numbered
titles, and the dead 2024 bill-status path.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    mississippi_lexis,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import (
    MississippiDelegatedCorpusBlockedError,
    MississippiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi_lexis import (
    ADVANCE_ORIGIN,
    EXPECTED_ROOT_COUNT,
    EXPECTED_ROOT_NODE_IDS,
    EXPECTED_TITLE_NUMBERS,
    OFFICIAL_LEGISLATURE_ENTRY_URL,
    OFFICIAL_LEGISLATURE_HELP_URL,
    OFFICIAL_SECRETARY_OF_STATE_URL,
    PUBLIC_CONTAINER_CONFIG,
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    TOC_ENDPOINT_PATH,
    MississippiLexisNode,
    _bind_live_nodes,
    document_disposition,
    document_page_url,
    grouped_body_acquisition_contract,
    node_from_mapping,
    parse_root_dom_rows,
    parse_title_subtree_payload,
    root_membership_error,
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
    / "mississippi_residual_closure_v1.md"
)

STATE_DELEGATION_GETS = 1
PUBLISHER_ENTRY_GETS = 1
RENDERED_ROOT_GETS = 1
TOC_PATCH_INPUTS = 51
AUTHORITY_CATALOG_RESIDUAL = 54
BODY_RESIDUAL = 30291
RESIDUAL_COUNT = 30345
TITLE_ROOTS = 50
RECENT_LEGISLATION_ROOTS = 1
CURRENT_SECTION_CANDIDATES = 30270
CURRENT_COLLECTIONS = 3
UNTYPED_CURRENT = 3
RECENT_LEGISLATION_LOCATORS = 15
FUTURE_EFFECTIVENESS = 80
FUTURE_PLACEHOLDERS = 2
EDITORIAL_STRUCTURAL = 59
CATALOG_EXCLUSIONS = 141
DOCUMENT_LIKE_NODES = 30432
DESCENDANT_NODES = 33600
ALL_NODES = 33651
UNIQUE_MAIN_SECTIONS = 30172
REPEATED_SECTION_IDENTITIES = 158
EXTRA_VARIANT_LOCATORS = 177
RESIDUAL_SHA256_PREFIX = "source_derived_after_retained_catalog"
DIAGNOSTIC_PRODUCER_PREFIX = "MississippiScraper@sha256:47adb7288b80"
DIAGNOSTIC_ROOT_RENDERED_SHA256 = (
    "69710a43c4c9f0f37606e8aed41a1e4bc9c3e5ec8bf1b1c7baa664bffc3d2da7"
)
DIAGNOSTIC_51_RESPONSE_MANIFEST_SHA256 = (
    "7e84b255f0806dd18af7cba3a3ea8a2b06049ff025393c110d431859af85fc88"
)
DIAGNOSTIC_ROOT_SEMANTIC_SHA256 = (
    "f5b4d0126272bd114e50a92f7dee937b543cb4ccb1181f73d6dc033f14849e69"
)
DIAGNOSTIC_ALL_NODE_SEMANTIC_SHA256 = (
    "85bff81bbb5b3af648dabbb0832e6d5af108ea4079d806b91b6bc1be3fb6660c"
)
DIAGNOSTIC_MAIN_DOCUMENT_SEMANTIC_SHA256 = (
    "cfa917901e8e03f35986047051e4877a07ea5b3972afae54a9f81e03a2adfea3"
)
RESIDUAL_WAVE_NAME = "source-ordered-current-bodies"
TOC_PATCH_WAVE_NAME = "51-root-open-to"
FIRST_RESIDUAL_URL = OFFICIAL_LEGISLATURE_ENTRY_URL
TOC_ENDPOINT_URL = f"{ADVANCE_ORIGIN}{TOC_ENDPOINT_PATH}"
DEAD_2024_CODE_ROOT = (
    "https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/"
)
INVENTED_EVEN_TITLE_URL = f"{DEAD_2024_CODE_ROOT}002/"
INVENTED_EVEN_TITLE_98_URL = f"{DEAD_2024_CODE_ROOT}098/"
OBSERVED_AT = "2026-08-26T01:33:48.867054+00:00"
BODY_RESIDUAL_DISPOSITIONS = frozenset(
    {
        "current_section_candidate",
        "current_section_collection_candidate",
        "untyped_current_document_residual",
        "recent_legislation_identity_residual",
    }
)
CATALOG_EXCLUSION_DISPOSITIONS = frozenset(
    {
        "future_effectiveness_excluded",
        "future_structural_placeholder",
        "publisher_editorial_structure_excluded",
    }
)


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _content_path(token: str, *, family: str = "statutes-legislation") -> str:
    return f"/shared/document/{family}/urn:contentItem:{token}"


def _evidence_container_url() -> str:
    return (
        f"{PUBLIC_CONTAINER_URL}&crid=request_1&prid=proof_1"
        if "?" in PUBLIC_CONTAINER_URL
        else PUBLIC_CONTAINER_URL
    )


def _root_rows() -> list[dict[str, str]]:
    labels = [
        mississippi_lexis.RECENT_LEGISLATION_ROOT_LABEL,
        *(f"TITLE {number} Test title" for number in EXPECTED_TITLE_NUMBERS),
    ]
    return [
        {
            "nodeid": node_id,
            "title": label,
            "level": "1",
            "nodepath": f"/ROOT/{node_id}",
            "canexpand": "true",
            "canopen": "false",
            "haschildren": "true",
        }
        for node_id, label in zip(EXPECTED_ROOT_NODE_IDS, labels, strict=True)
    ]


def _mapping(
    *,
    node_id: str,
    title: str,
    level: int,
    node_path: str,
    link_href: str = "",
    expandable: bool = False,
) -> dict[str, object]:
    return {
        "id": node_id,
        "props": {
            "nodeid": node_id,
            "linktemplatetitle": title,
            "level": level,
            "nodepath": node_path,
            "canexpand": expandable,
            "canopen": bool(link_href),
            "haschildren": expandable,
            "linkhref": link_href,
            "subscribed": True,
            "tocpricing": {
                "purchaserequired": False,
                "listprice": 0,
                "netprice": 0,
                "currencycode": "USD",
                "usagetypecode": "subscription",
                "documentstatus": "available",
            },
        },
    }


def _bind(nodes: list[MississippiLexisNode]) -> list[MississippiLexisNode]:
    bound = _bind_live_nodes(
        nodes,
        source_url=_evidence_container_url(),
        observed_at=OBSERVED_AT,
        receipt_sha256="a" * 64,
    )
    if len(bound) != len(nodes):
        raise AssertionError("Mississippi compact residual failed live evidence binding")
    return bound


def _document_node(
    *,
    node_id: str,
    title: str,
    node_path: str,
    link_href: str,
) -> MississippiLexisNode:
    node = node_from_mapping(
        _mapping(
            node_id=node_id,
            title=title,
            level=2,
            node_path=node_path,
            link_href=link_href,
        )
    )
    assert node is not None
    return _bind([node])[0]


def _compact_current_body_nodes() -> list[MississippiLexisNode]:
    title_one = "/ROOT/AAC"
    recent = "/ROOT/AAB"
    return [
        _document_node(
            node_id="UNIQUE1",
            title="§ 1-1-1. Unique.",
            node_path=f"{title_one}/UNIQUE1",
            link_href=_content_path("MS01-UNIQ-SECT-0001-00000-00"),
        ),
        _document_node(
            node_id="DUPA1",
            title="§ 1-1-3. Effective until July 1, 2026.",
            node_path=f"{title_one}/DUPA1",
            link_href=_content_path("MS01-DUPL-SECT-000A-00000-00"),
        ),
        _document_node(
            node_id="DUPB1",
            title="§ 1-1-3. Effective July 1, 2026.",
            node_path=f"{title_one}/DUPB1",
            link_href=_content_path("MS01-DUPL-SECT-000B-00000-00"),
        ),
        _document_node(
            node_id="COLL1",
            title="§§ Selected provisions.",
            node_path=f"{title_one}/COLL1",
            link_href=_content_path("MS01-COLL-SECT-0001-00000-00"),
        ),
        _document_node(
            node_id="UNTYPED1",
            title="",
            node_path=f"{title_one}/UNTYPED1",
            link_href=_content_path("MS01-UNTY-SECT-0001-00000-00"),
        ),
        _document_node(
            node_id="FUTURE1",
            title="§ 1-1-11. Effective January 1, 2027.",
            node_path=f"{title_one}/FUTURE1",
            link_href=_content_path(
                "MS01-FUTR-SECT-0001-00000-00",
                family="fe",
            ),
        ),
        _document_node(
            node_id="EDITORIAL1",
            title="Chapter 1 Editorial structure.",
            node_path=f"{title_one}/EDITORIAL1",
            link_href=_content_path("MS01-EDIT-SECT-0001-00000-00"),
        ),
        _document_node(
            node_id="RECENT1",
            title="§ 1. Needs catchline [Effective July 1, 2026].",
            node_path=f"{recent}/RECENT1",
            link_href=_content_path("MSAB-RCNT-SECT-0001-00000-00"),
        ),
    ]


def _source_ordered_current_body_urls(
    nodes: list[MississippiLexisNode],
) -> list[str]:
    residual: list[str] = []
    seen: set[str] = set()
    for node in sorted(nodes, key=lambda item: item.node_path):
        if document_disposition(node) not in BODY_RESIDUAL_DISPOSITIONS:
            continue
        url = document_page_url(node)
        if url in seen:
            raise AssertionError(
                "Mississippi delegated Lexis residual frontier repeated a URL"
            )
        seen.add(url)
        residual.append(url)
    return residual


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Mississippi residual closure report is empty")
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


def test_mississippi_residual_closure_report_records_exact_delegated_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "MS"
    assert table["authority_domain"] == "www.legislature.ms.gov"
    assert table["publisher_domain"] == "www.lexisnexis.com"
    assert table["container_domain"] == "advance.lexis.com"
    assert table["official entry"] == FIRST_RESIDUAL_URL
    assert table["official_help_url"] == OFFICIAL_LEGISLATURE_HELP_URL
    assert table["official_secretary_of_state_url"] == OFFICIAL_SECRETARY_OF_STATE_URL
    assert table["publisher_entry"] == PUBLIC_ENTRY_URL
    assert table["container_url"] == PUBLIC_CONTAINER_URL
    assert table["toc_endpoint"] == TOC_ENDPOINT_URL
    assert table["toc_root"] == "6gf5kkk"
    assert table["root_membership"].startswith("AAB recent-legislation")
    assert "odd Titles 1" in table["root_membership"]
    assert table["even_numbered_titles"] == "forbidden"
    assert table["dead_2024_billstatus_path"] == "forbidden"
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["seed"] == (
        "fresh isolated acquisition; zero authorizing retained inputs"
    )
    assert table["catalog_first_repaired_99_titles"] == "forbidden"
    assert table["unicourt_r78_secondary_cache"] == "forbidden"
    assert table["justia_singleton_secondary_cache"] == "forbidden"
    assert table["patch_archive_substitution"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["invent_even_titles"] == "forbidden"
    assert table["parser"] == (
        "Mississippi-specific delegated Lexis catalog then current bodies"
    )
    assert table["same_target_parser_for_live_and_replay"] == "true"
    assert table["retain_legislature_publisher_container_and_51_toc_bytes_first"] == (
        "true"
    )
    assert table["fetch_catalog_before_bodies"] == "true"
    assert table["strict_reusable_input_count"] == "0"
    assert table["root_nodes"] == str(EXPECTED_ROOT_COUNT)
    assert table["title_roots"] == str(TITLE_ROOTS)
    assert table["recent_legislation_roots"] == str(RECENT_LEGISLATION_ROOTS)
    assert table["complete_open_to_responses"] == str(TOC_PATCH_INPUTS)
    assert table["descendant_nodes"] == str(DESCENDANT_NODES)
    assert table["all_nodes_including_roots"] == str(ALL_NODES)
    assert table["document_like_nodes"] == str(DOCUMENT_LIKE_NODES)
    assert table["current_section_candidates"] == str(CURRENT_SECTION_CANDIDATES)
    assert table["current_section_collection_candidates"] == str(CURRENT_COLLECTIONS)
    assert table["untyped_current_document_residuals"] == str(UNTYPED_CURRENT)
    assert table["recent_legislation_locators"] == str(RECENT_LEGISLATION_LOCATORS)
    assert table["future_effectiveness_locators"] == str(FUTURE_EFFECTIVENESS)
    assert table["future_structural_placeholders"] == str(FUTURE_PLACEHOLDERS)
    assert table["publisher_editorial_structural_documents"] == str(
        EDITORIAL_STRUCTURAL
    )
    assert table["catalog_exclusions"] == str(CATALOG_EXCLUSIONS)
    assert table["unique_main_section_identities"] == str(UNIQUE_MAIN_SECTIONS)
    assert table["repeated_section_identities"] == str(REPEATED_SECTION_IDENTITIES)
    assert table["extra_variant_locators"] == str(EXTRA_VARIANT_LOCATORS)
    assert table["state_delegation_gets"] == str(STATE_DELEGATION_GETS)
    assert table["publisher_entry_gets"] == str(PUBLISHER_ENTRY_GETS)
    assert table["rendered_root_gets"] == str(RENDERED_ROOT_GETS)
    assert table["toc_patch_inputs"] == str(TOC_PATCH_INPUTS)
    assert table["authority_catalog_residual_count"] == str(AUTHORITY_CATALOG_RESIDUAL)
    assert table["body_residual_count"] == str(BODY_RESIDUAL)
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == (
        "delegated Lexis catalog then 30,291 current bodies"
    )
    assert table["residual_first_url"] == FIRST_RESIDUAL_URL
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["toc_patch_wave_name"] == TOC_PATCH_WAVE_NAME
    assert table["ordered_request_wave_counts"] == "1,1,1,51,30291"
    assert table["get_authority_wave_count"] == "3"
    assert table["toc_patch_wave_count"] == "1"
    assert table["body_get_wave_count"] == "1"
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["diagnostic_root_rendered_sha256"] == DIAGNOSTIC_ROOT_RENDERED_SHA256
    assert table["diagnostic_51_response_manifest_sha256"] == (
        DIAGNOSTIC_51_RESPONSE_MANIFEST_SHA256
    )
    assert table["diagnostic_root_semantic_sha256"] == DIAGNOSTIC_ROOT_SEMANTIC_SHA256
    assert table["diagnostic_all_node_semantic_sha256"] == (
        DIAGNOSTIC_ALL_NODE_SEMANTIC_SHA256
    )
    assert table["diagnostic_main_document_semantic_sha256"] == (
        DIAGNOSTIC_MAIN_DOCUMENT_SEMANTIC_SHA256
    )
    assert table["diagnostic_hashes_authorizing"] == "false"
    assert table["diagnostic_producer"].startswith(DIAGNOSTIC_PRODUCER_PREFIX)
    assert "ensure_ascii=False" in table["residual_sha_method"]
    assert "PATCH" in table["residual_sha_method"]

    assert (
        STATE_DELEGATION_GETS
        + PUBLISHER_ENTRY_GETS
        + RENDERED_ROOT_GETS
        + TOC_PATCH_INPUTS
        == AUTHORITY_CATALOG_RESIDUAL
    )
    assert AUTHORITY_CATALOG_RESIDUAL + BODY_RESIDUAL == RESIDUAL_COUNT
    assert TITLE_ROOTS + RECENT_LEGISLATION_ROOTS == EXPECTED_ROOT_COUNT
    assert (
        CURRENT_SECTION_CANDIDATES
        + CURRENT_COLLECTIONS
        + UNTYPED_CURRENT
        + RECENT_LEGISLATION_LOCATORS
        == BODY_RESIDUAL
    )
    assert (
        FUTURE_EFFECTIVENESS + FUTURE_PLACEHOLDERS + EDITORIAL_STRUCTURAL
        == CATALOG_EXCLUSIONS
    )
    assert BODY_RESIDUAL + CATALOG_EXCLUSIONS == DOCUMENT_LIKE_NODES
    assert DESCENDANT_NODES + EXPECTED_ROOT_COUNT == ALL_NODES
    assert UNIQUE_MAIN_SECTIONS + EXTRA_VARIANT_LOCATORS == 30349
    assert REPEATED_SECTION_IDENTITIES + EXTRA_VARIANT_LOCATORS == 335

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "even" in lowered and "title" in lowered
    assert "dead 2024" in lowered or "dead bill-status" in lowered
    assert "hub mutation" in lowered
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "patch archive substitution" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "30,291" in report
    assert "30,345" in report
    assert FIRST_RESIDUAL_URL in report
    assert PUBLIC_CONTAINER_URL in report
    assert TOC_ENDPOINT_URL in report
    assert PUBLIC_CONTAINER_CONFIG in report
    assert RESIDUAL_SHA256_PREFIX in report
    assert INVENTED_EVEN_TITLE_URL not in report
    assert INVENTED_EVEN_TITLE_98_URL not in report
    assert report.count("urn:contentItem:") < 8
    assert report.count("https://advance.lexis.com/documentpage/") < 4
    assert report.count("https://billstatus.ls.state.ms.us/documents/2024/") <= 2
    assert not re.search(r"residual_ordered_sha256_prefix.*[0-9a-f]{12}", report)


def test_mississippi_adapter_has_no_static_body_residual_url_list() -> None:
    adapter = inspect.getsource(MississippiScraper)
    lexis = inspect.getsource(mississippi_lexis)
    scrape_source = inspect.getsource(MississippiScraper.scrape_code)
    fetch_source = inspect.getsource(
        MississippiScraper._fetch_mississippi_frontier_batch
    )
    assert "30,291" not in adapter
    assert str(BODY_RESIDUAL) not in adapter
    assert str(RESIDUAL_COUNT) not in adapter
    assert str(BODY_RESIDUAL) not in lexis
    assert str(RESIDUAL_COUNT) not in lexis
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert RESIDUAL_SHA256_PREFIX not in lexis
    assert INVENTED_EVEN_TITLE_URL not in adapter
    assert INVENTED_EVEN_TITLE_URL not in lexis
    assert "_ARCHIVE_BODY_URLS" not in fetch_source
    assert "_discover_archived_body_urls" not in scrape_source
    assert "_probe_delegated_mississippi_code" in scrape_source
    assert "_fetch_mississippi_frontier_batch" not in scrape_source
    assert "_scrape_strict_official_code_tree" not in scrape_source
    content_item_literals = re.findall(
        r"urn:contentItem:[A-Za-z0-9:-]{8,}",
        adapter,
    )
    assert content_item_literals == []
    assert adapter.count("https://advance.lexis.com/documentpage/") == 0
    assert adapter.count("https://advance.lexis.com/shared/document/") == 0


def test_mississippi_residual_sha256_uses_canonical_json_of_ordered_get_urls() -> None:
    compact = [
        FIRST_RESIDUAL_URL,
        PUBLIC_ENTRY_URL,
        PUBLIC_CONTAINER_URL,
    ]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert len(compact_digest) == 64
    assert not compact_digest.startswith(RESIDUAL_SHA256_PREFIX)
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert TOC_PATCH_WAVE_NAME in report
    assert RESIDUAL_SHA256_PREFIX in report


def test_mississippi_one_domain_body_wave_disables_per_page_archive_and_reinventory() -> None:
    nodes = _compact_current_body_nodes()
    contract = grouped_body_acquisition_contract(nodes)
    assert contract["source_domain"] == "advance.lexis.com"
    assert contract["common_crawl_inventory_query_upper_bound"] == 1
    assert contract["group_warc_ranges_by_warc_filename"] is True
    assert contract["retry_residual_urls_only"] is True
    assert contract["per_page_archive_inventory_loop"] is False
    assert contract["wayback_prefix_inventory"] is True
    assert contract["full_corpus_admissible"] is False
    assert all(
        urlparse(url).hostname == "advance.lexis.com"
        for url in contract["request_urls"]
    )
    assert DEAD_2024_CODE_ROOT not in contract["request_urls"]
    assert INVENTED_EVEN_TITLE_URL not in contract["request_urls"]
    assert contract["request_urls"] == _source_ordered_current_body_urls(nodes)

    probe_source = inspect.getsource(
        MississippiScraper._probe_delegated_mississippi_code
    )
    assert '"per_page_archive_inventory_loop": False' in probe_source
    assert '"retry_residual_urls_only": True' in probe_source
    assert '"wayback_prefix_inventory": True' in probe_source
    assert '"source_domain": "advance.lexis.com"' in probe_source

    retry_source = inspect.getsource(
        BaseStateScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source
    assert "archive.is" not in inspect.getsource(
        grouped_body_acquisition_contract
    ).casefold()


def test_mississippi_catalog_is_odd_titles_plus_recent_and_rejects_even_titles() -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    roots = parse_root_dom_rows(_root_rows())
    assert len(roots) == EXPECTED_ROOT_COUNT == 51
    assert root_membership_error(roots) == ""
    assert roots[0].is_recent_legislation_root is True
    assert tuple(node.title_number for node in roots[1:]) == EXPECTED_TITLE_NUMBERS
    assert list(EXPECTED_TITLE_NUMBERS) == [str(number) for number in range(1, 100, 2)]
    assert all(int(number) % 2 == 1 for number in EXPECTED_TITLE_NUMBERS)
    assert "2" not in EXPECTED_TITLE_NUMBERS
    assert "98" not in EXPECTED_TITLE_NUMBERS
    assert scraper.OFFICIAL_TITLE_COUNT == TITLE_ROOTS
    assert sorted(scraper.OFFICIAL_TITLE_NAMES) == [
        int(number) for number in EXPECTED_TITLE_NUMBERS
    ]

    even_root = parse_root_dom_rows(
        [
            {
                "nodeid": "EVEN2",
                "title": "TITLE 2 Invented even title",
                "level": "1",
                "nodepath": "/ROOT/EVEN2",
                "canexpand": "true",
                "canopen": "false",
                "haschildren": "true",
            }
        ]
    )
    assert even_root[0].title_number is None
    broken = list(roots)
    broken[1] = replace(broken[1], title="TITLE 2 Invented even title")
    assert broken[1].node_id == EXPECTED_ROOT_NODE_IDS[1]
    assert broken[1].title_number is None
    assert "odd-numbered" in root_membership_error(broken)
    with pytest.raises(ValueError, match="invalid Mississippi root node id"):
        toc_open_to_request("EVEN2", target_level=4)

    parent = roots[1]
    even_section = node_from_mapping(
        _mapping(
            node_id="EVENSECTION",
            title="§ 2-1-1. Invented even title section.",
            level=3,
            node_path="/ROOT/AAC/CHAPTER1/EVENSECTION",
            link_href=_content_path("MS02-EVEN-SECT-0001-00000-00"),
        )
    )
    assert even_section is not None
    assert even_section.section_number is None
    assert even_section.title_number is None
    chapter = _mapping(
        node_id="CHAPTER1",
        title="Chapter 1 Test",
        level=2,
        node_path="/ROOT/AAC/CHAPTER1",
        expandable=True,
    )
    foreign_odd = _mapping(
        node_id="FOREIGN3",
        title="§ 3-1-1. Cross-title section.",
        level=3,
        node_path="/ROOT/AAC/CHAPTER1/FOREIGN3",
        link_href=_content_path("MS03-XTTL-SECT-0001-00000-00"),
    )
    _nodes, _closed, error = parse_title_subtree_payload(
        {"collections": {"nodes": [chapter, foreign_odd]}},
        parent=parent,
        target_level=3,
    )
    assert error == "statute citation crossed the requested title boundary"

    endpoint, body = toc_open_to_request("AAB", target_level=4)
    assert endpoint == TOC_ENDPOINT_URL
    assert body["props"]["action"] == "open-to"
    assert scraper.OFFICIAL_DELEGATED_CONTAINER_URL == PUBLIC_CONTAINER_URL
    assert scraper.OFFICIAL_DELEGATED_ENTRY_URL == PUBLIC_ENTRY_URL
    assert scraper.OFFICIAL_BILLSTATUS_CODE_ROOT == DEAD_2024_CODE_ROOT
    assert scraper.official_title_url(2) == INVENTED_EVEN_TITLE_URL
    assert scraper.official_title_url(1).startswith(DEAD_2024_CODE_ROOT)


def test_mississippi_seed_and_host_replay_forbid_hub_docker_and_dead_2024_path(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "MS",
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
    assert "even" in report and "title" in report
    assert "dead 2024" in report or "bill-status" in report
    assert "patch archive substitution" in report


def test_mississippi_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    fetch_source = inspect.getsource(MississippiScraper.fetch_official)
    assert "public_law_no_state_copyright" in closure_source
    assert "async delegated" in fetch_source
    assert "51-root inventory" in fetch_source
    assert "dead 2024" in fetch_source
    scraper = MississippiScraper("MS", "Mississippi")
    with pytest.raises(RuntimeError, match="async delegated Lexis 51-root"):
        scraper.fetch_official("MS")
    assert scraper.OFFICIAL_HELP_URL == OFFICIAL_LEGISLATURE_HELP_URL


def test_mississippi_compact_recipe_emits_catalog_then_current_bodies_not_even_or_dead_2024() -> None:
    roots = parse_root_dom_rows(_root_rows())
    assert root_membership_error(roots) == ""
    nodes = _compact_current_body_nodes()
    residual = _source_ordered_current_body_urls(nodes)
    assert residual[0].startswith(f"{ADVANCE_ORIGIN}/documentpage/")
    assert all(urlparse(url).hostname == "advance.lexis.com" for url in residual)
    assert INVENTED_EVEN_TITLE_URL not in residual
    assert INVENTED_EVEN_TITLE_98_URL not in residual
    assert DEAD_2024_CODE_ROOT not in residual
    assert FIRST_RESIDUAL_URL not in residual
    dispositions = {document_disposition(node) for node in nodes}
    assert "current_section_candidate" in dispositions
    assert "current_section_collection_candidate" in dispositions
    assert "untyped_current_document_residual" in dispositions
    assert "recent_legislation_identity_residual" in dispositions
    assert dispositions & CATALOG_EXCLUSION_DISPOSITIONS
    assert len(residual) == 6

    contract = grouped_body_acquisition_contract(nodes)
    assert contract["request_urls"] == residual
    assert contract["request_url_count"] == len(residual)
    assert contract["reusable_candidate_node_count"] == 2
    assert INVENTED_EVEN_TITLE_URL not in contract["request_urls"]
    residual_dispositions = {row["disposition"] for row in contract["residuals"]}
    assert "duplicate_current_citation_requires_body_reconciliation" in (
        residual_dispositions
    )
    assert "recent_legislation_identity_residual" in residual_dispositions
    assert "untyped_current_document_residual" in residual_dispositions
    exclusion_dispositions = {row["disposition"] for row in contract["exclusions"]}
    assert exclusion_dispositions <= CATALOG_EXCLUSION_DISPOSITIONS
    digest = _canonical_residual_sha256(residual)
    assert not digest.startswith(RESIDUAL_SHA256_PREFIX)
    assert len(digest) == 64

    authority = [FIRST_RESIDUAL_URL, PUBLIC_ENTRY_URL, PUBLIC_CONTAINER_URL]
    assert authority[0] == FIRST_RESIDUAL_URL
    assert DEAD_2024_CODE_ROOT not in authority
    assert INVENTED_EVEN_TITLE_URL not in authority


def test_mississippi_full_route_blocks_before_dead_billstatus_and_body_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    probe_calls: list[str] = []
    batch_calls: list[list[str]] = []

    async def _probe(*, code_name: str) -> dict[str, Any]:
        probe_calls.append(code_name)
        return {
            "schema_version": "mississippi-delegated-catalog-probe/v1",
            "status": "complete",
            "disposition": "delegated_toc_closed_body_frontier_unacquired",
            "frontier": {
                "toc_frontier_closed": True,
                "expected_root_count": EXPECTED_ROOT_COUNT,
                "title_count": TITLE_ROOTS,
                "document_body_count": 0,
                "body_frontier_closed": False,
            },
            "body_acquisition_contract": {
                "source_domain": "advance.lexis.com",
                "per_page_archive_inventory_loop": False,
            },
            "full_corpus_admissible": False,
        }

    async def _batch(urls: list[str], **_kwargs: Any) -> Any:
        batch_calls.append(list(urls))
        raise AssertionError(
            "Mississippi residual must not open the dead 2024 bill-status frontier"
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_probe_delegated_mississippi_code", _probe)
    monkeypatch.setattr(
        scraper,
        "_fetch_mississippi_frontier_batch",
        _batch,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: None)

    with pytest.raises(
        MississippiDelegatedCorpusBlockedError,
        match="delegated_toc_closed_body_frontier_unacquired",
    ) as captured:
        asyncio.run(
            scraper.scrape_code(
                "Mississippi Code",
                scraper.OFFICIAL_ENTRY_URL,
                max_statutes=None,
            )
        )

    assert probe_calls == ["Mississippi Code"]
    assert batch_calls == []
    assert captured.value.evidence["frontier"]["document_body_count"] == 0
    assert captured.value.evidence["full_corpus_admissible"] is False
    report = scraper.last_mississippi_full_corpus_report
    assert report["closed"] is False
    inventory_source = inspect.getsource(mississippi_lexis.discover_live_inventory)
    assert "does not open document" in inspect.getdoc(mississippi_lexis) or (
        "does not open document links" in inspect.getsource(mississippi_lexis)
    )
    assert "toc_open_to_request" in inventory_source
    assert "documentpage" not in inventory_source


def test_mississippi_patch_toc_identity_cannot_be_substituted_with_archive_get() -> None:
    endpoint, patch_body = toc_open_to_request("AAC", target_level=4)
    assert endpoint == TOC_ENDPOINT_URL
    assert patch_body["id"] == "6gf5kkk"
    assert patch_body["props"]["action"] == "open-to"
    request_body = json.dumps(patch_body, ensure_ascii=False, separators=(",", ":"))
    patch_identity = {
        "method": "PATCH",
        "url": endpoint,
        "request_body_sha256": hashlib.sha256(request_body.encode("utf-8")).hexdigest(),
    }
    get_identity = {"method": "GET", "url": endpoint}
    assert get_identity != patch_identity
    assert "request_body_sha256" not in get_identity

    inventory_source = inspect.getsource(mississippi_lexis.discover_live_inventory)
    patch_source = inspect.getsource(mississippi_lexis._live_toc_patch)
    assert "method: 'PATCH'" in patch_source or 'method: "PATCH"' in patch_source
    assert "_live_toc_patch" in inventory_source
    assert "grouped_body_acquisition_contract" not in inventory_source
    discovery_doc = inspect.getdoc(mississippi_lexis.discover_live_inventory) or ""
    assert "51 complete TOC" in discovery_doc
    grouped_source = inspect.getsource(grouped_body_acquisition_contract)
    assert "per_page_archive_inventory_loop" in grouped_source
    assert "document_page_url" in grouped_source

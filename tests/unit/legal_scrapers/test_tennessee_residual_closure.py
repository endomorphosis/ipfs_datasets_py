"""LCR-104: Tennessee delegated Lexis residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded 36,118-input residual and the production contracts that forbid
Hub mutation, static lists, per-page archive loops, PATCH archive
substitution, the synthetic v4 receipt, and secondary caches.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionError,
    StateLawMultiFetchAcquisitionLedger,
    StateLawRetainedReplayOnlyError,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    require_authoritative_admission,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    tennessee_lexis,
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee import (
    TennesseeScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee_lexis import (
    OBSERVED_AUTHORITY_CATALOG_RESIDUAL_COUNT,
    OBSERVED_BODY_RESIDUAL_COUNT,
    OBSERVED_CATALOG_TERMINAL_COUNT,
    OBSERVED_CATALOG_TERMINAL_COUNTS,
    OBSERVED_DOCUMENT_COUNT,
    OBSERVED_ORDERED_CONTENT_PATH_SHA256,
    OBSERVED_REPEATED_CITATION_IDENTITY_COUNT,
    OBSERVED_STRICT_REUSABLE_INPUT_COUNT,
    OBSERVED_TOTAL_RESIDUAL_COUNT,
    PUBLIC_CONTAINER_CONFIG,
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    TOC_ENDPOINT_URL,
    TennesseeLexisNode,
    canonical_toc_patch_request,
    document_url,
    grouped_get_acquisition_contract,
    publisher_container_delegation_present,
    parse_root_html,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee_lexis_live import (
    acquire_live_catalog,
    canonical_live_toc_patch_request,
    canonical_rendered_root_request,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "tennessee_residual_closure_v1.md"
)

STATE_DELEGATION_GETS = 1
PUBLISHER_ENTRY_GETS = 1
RENDERED_ROOT_GETS = 1
TOC_PATCH_INPUTS = 69
AUTHORITY_CATALOG_RESIDUAL = 72
BODY_RESIDUAL = 36046
RESIDUAL_COUNT = 36118
STATUTORY_TITLE_ROOTS = 71
EXPANDABLE_TITLE_ROOTS = 69
DIRECT_RESERVED_TITLE_ROOTS = 2
CATALOG_TERMINALS = 1359
BODY_UNCLASSIFIED = 34687
REPEATED_CITATIONS = 182
RESIDUAL_SHA256_PREFIX = "af6b3962a8ee"
DIAGNOSTIC_PRODUCER_PREFIX = "TennesseeScraper@sha256:42e4c260c2be"
RESIDUAL_WAVE_NAME = "document body wave"
TOC_PATCH_WAVE_NAME = "deepest title TOC wave"
FIRST_RESIDUAL_URL = "https://wapp.capitol.tn.gov/apps/WebPublications/"
DEAD_TN_GOV_ENTRY = "https://www.tn.gov/tga/statutes.html"
INVENTED_TN_GOV_TITLE_URL = "https://www.tn.gov/tga/statutes.html/title-1/"
SYNTHETIC_V4_RESPONSE_SHA_PREFIX = "89e20a95d9fd"
SYNTHETIC_V4_FRONTIER_PREFIX = "6850ed433c01"
COMPACT_TITLES = (
    ("1", "Code and Statutes"),
    ("19", "[Reserved]"),
    ("51", "[Reserved]"),
)
PHASE_ID = hashlib.sha256(b"tennessee-residual-test-phase").hexdigest()
PHASE_STARTED_AT = datetime.now(UTC).replace(microsecond=0).isoformat()
SESSION_ID = "residual-session-request-id"
SESSION_SHA256 = hashlib.sha256(SESSION_ID.encode()).hexdigest()


def _bind_phase(scraper: TennesseeScraper) -> None:
    scraper._tennessee_acquisition_phase_id = PHASE_ID
    scraper._tennessee_acquisition_phase_started_at = PHASE_STARTED_AT


def _root_request() -> dict[str, Any]:
    return canonical_rendered_root_request(
        acquisition_phase_id=PHASE_ID,
        acquisition_phase_started_at=PHASE_STARTED_AT,
    )


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _content_path(token: str) -> str:
    return (
        "/shared/document/statutes-legislation/"
        f"urn:contentItem:{token}"
    )


def _compact_root_html(*, target_level: int = 2) -> str:
    elements: list[str] = []
    for number, label in COMPACT_TITLES:
        node_id = f"T{int(number):03d}"
        common = (
            f'class="js-node" data-nodeid="{node_id}" '
            f'data-nodepath="/ROOT/{node_id}" data-level="1" '
            f'data-title="TITLE {number} - {label}"'
        )
        if number in {"19", "51"}:
            href = _content_path(f"TN{int(number):02d}-RSVD-0000-00000-00")
            elements.append(
                f"<li {common} data-canexpand='false' data-canopen='true' "
                f"data-haschildren='false' data-docfullpath='{href}'>"
                f"<div class='js-node-header'><a href='{href}'>Reserved</a></div>"
                "</li>"
            )
        else:
            elements.append(
                f"<li {common} data-canexpand='true' data-canopen='false' "
                "data-haschildren='true'><div class='js-node-header'>"
                f"<button data-command='open-to' data-targetlevel='{target_level}'>"
                "Open</button></div></li>"
            )
    elements.append(
        "<li class='js-node' data-nodeid='TAB13' "
        "data-nodepath='/ROOT/TAB13' data-level='1' "
        "data-title='Volume 13 Tables' data-canexpand='false' "
        "data-canopen='false' data-haschildren='false'>"
        "<div class='js-node-header'></div></li>"
    )
    return f"<html><body>{''.join(elements)}</body></html>"


def _node_mapping(
    *,
    node_id: str,
    title: str,
    level: int,
    path: str,
    href: str = "",
    expandable: bool = False,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "props": {
            "canexpand": expandable,
            "canopen": bool(href),
            "haschildren": expandable,
            "level": level,
            "linkhref": href,
            "linktemplatetitle": title,
            "nodeid": node_id,
            "nodepath": path,
        },
    }


def _title_one_subtree_payload(parent: TennesseeLexisNode) -> tuple[dict[str, Any], str]:
    href = _content_path("TN01-TEST-BODY-00000-00")
    return (
        {
            "collections": {
                "toccontainer": {
                    "collections": {
                        "tocnodes": [
                            _node_mapping(
                                node_id="D001",
                                title="1-1-1. Test provision",
                                level=2,
                                path=f"{parent.node_path}/D001",
                                href=href,
                            )
                        ]
                    }
                }
            }
        },
        href,
    )


def _receipt_sha256(url: str, content_sha256: str) -> str:
    return hashlib.sha256(f"{url}\n{content_sha256}".encode()).hexdigest()


class _Envelope(SimpleNamespace):
    def to_dict(self) -> dict[str, Any]:
        digest = hashlib.sha256(bytes(self.body)).hexdigest()
        return {
            "acquisition": {
                "body_sha256": digest,
                "receipt": {
                    "content": {"sha256": digest},
                    "endpoint": self.url,
                    "receipt_sha256": self.receipt_sha256,
                },
            }
        }


class _TennesseeRetainedLedger:
    retained_replay_only = True

    def __init__(self) -> None:
        self._rows: dict[str, Any] = {}
        self.calls: list[list[tuple[str, dict[str, Any]]]] = []
        self.refresh_count = 0

    @property
    def entries(self) -> tuple[Any, ...]:
        return tuple(self._rows.values())

    @staticmethod
    def _key(url: str, request: Mapping[str, Any]) -> str:
        return json.dumps([url, dict(request)], sort_keys=True, separators=(",", ":"))

    def add(self, url: str, request: Mapping[str, Any], body: bytes) -> None:
        digest = hashlib.sha256(body).hexdigest()
        envelope = _Envelope(
            body=body,
            receipt_sha256=_receipt_sha256(url, digest),
            url=url,
        )
        observed_at = datetime.now(UTC).isoformat()
        browser = request.get("method") == "PATCH" or request.get("rendered_by") == "playwright"
        browser_proof = {
            "final_url": TOC_ENDPOINT_URL if request.get("method") == "PATCH" else PUBLIC_CONTAINER_URL,
            "final_url_sha256": hashlib.sha256(PUBLIC_CONTAINER_URL.encode()).hexdigest(),
            "redirect_chain": [],
            "redirected": False,
            "response_observed_at": observed_at,
            "session_request_id_sha256": str(
                request.get("session_request_id_sha256") or SESSION_SHA256
            ),
        }
        self._rows[self._key(url, request)] = SimpleNamespace(
            envelope=envelope,
            receipt=SimpleNamespace(
                content=SimpleNamespace(sha256=digest),
                endpoint=url,
                pagination={
                    "tennessee_acquisition_phase": {
                        "phase_id": PHASE_ID,
                        "schema_version": TennesseeScraper.TN_PHASE_SCHEMA,
                        "started_at": PHASE_STARTED_AT,
                    },
                    **(
                        {"tennessee_browser_response": browser_proof}
                        if browser
                        else {}
                    ),
                },
                retrieved_at=observed_at,
                sanitized_request=dict(request),
            ),
            transport_receipt={
                "content_sha256": digest,
                "official_url": url,
                "retrieved_at": observed_at,
                "source_transport": (
                    "browser_rendered"
                    if request.get("method") == "PATCH"
                    or request.get("rendered_by") == "playwright"
                    else "direct"
                ),
            },
        )

    def refresh_existing_entries(self) -> None:
        self.refresh_count += 1

    def replay_retained_parser_inputs(
        self,
        *,
        requests: list[tuple[str, dict[str, Any]]],
    ) -> tuple[Any, ...]:
        normalized = [(url, dict(request)) for url, request in requests]
        self.calls.append(normalized)
        rows = []
        for url, request in normalized:
            retained = self._rows.get(self._key(url, request))
            if retained is None:
                raise StateLawRetainedReplayOnlyError(
                    f"retained-replay-only ledger miss: {url}"
                )
            rows.append(retained)
        return tuple(rows)


def _source_ordered_tennessee_residual(
    *,
    authority: list[tuple[str, dict[str, Any]]],
    patch_requests: list[tuple[str, dict[str, Any]]],
    body_requests: list[tuple[str, dict[str, Any]]],
    retained_keys: set[str],
) -> list[tuple[str, dict[str, Any]]]:
    residual: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for url, request in [*authority, *patch_requests, *body_requests]:
        key = json.dumps([url, request], sort_keys=True, separators=(",", ":"))
        if key in retained_keys:
            continue
        if key in seen:
            raise AssertionError(
                "Tennessee delegated Lexis residual frontier repeated a request identity"
            )
        seen.add(key)
        residual.append((url, request))
    return residual


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Tennessee residual closure report is empty")
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


def test_tennessee_residual_closure_report_records_exact_delegated_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "TN"
    assert table["authority_domain"] == "wapp.capitol.tn.gov"
    assert table["publisher_domain"] == "www.lexisnexis.com"
    assert table["container_domain"] == "advance.lexis.com"
    assert table["official entry"] == FIRST_RESIDUAL_URL
    assert table["publisher_entry"] == PUBLIC_ENTRY_URL
    assert table["container_url"] == PUBLIC_CONTAINER_URL
    assert table["toc_endpoint"] == TOC_ENDPOINT_URL
    assert table["toc_root"] == "6gf5kkk"
    assert table["excluded_root"] == "Volume 13 Tables"
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["seed"] == (
        "fresh isolated acquisition; zero authorizing retained inputs"
    )
    assert table["synthetic_v4_receipt"] == "forbidden"
    assert table["secondary_caches"] == "forbidden"
    assert table["patch_archive_substitution"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["dead_tn_gov_locators"] == "forbidden"
    assert table["parser"] == "Tennessee-specific strict Lexis parser"
    assert table["same_target_parser_for_live_and_replay"] == "true"
    assert table["strict_reusable_input_count"] == str(
        OBSERVED_STRICT_REUSABLE_INPUT_COUNT
    )
    assert table["statutory_title_roots"] == str(STATUTORY_TITLE_ROOTS)
    assert table["expandable_title_roots"] == str(EXPANDABLE_TITLE_ROOTS)
    assert table["direct_reserved_title_roots"] == str(DIRECT_RESERVED_TITLE_ROOTS)
    assert table["catalog_terminal_count"] == str(CATALOG_TERMINALS)
    assert table["catalog_repealed"] == str(OBSERVED_CATALOG_TERMINAL_COUNTS["repealed"])
    assert table["catalog_reserved"] == str(OBSERVED_CATALOG_TERMINAL_COUNTS["reserved"])
    assert table["catalog_transferred"] == str(
        OBSERVED_CATALOG_TERMINAL_COUNTS["transferred"]
    )
    assert table["catalog_expired"] == str(OBSERVED_CATALOG_TERMINAL_COUNTS["expired"])
    assert table["catalog_obsolete"] == str(OBSERVED_CATALOG_TERMINAL_COUNTS["obsolete"])
    assert table["body_unclassified_candidates"] == str(BODY_UNCLASSIFIED)
    assert table["repeated_citation_identity_count"] == str(REPEATED_CITATIONS)
    assert table["state_delegation_gets"] == str(STATE_DELEGATION_GETS)
    assert table["publisher_entry_gets"] == str(PUBLISHER_ENTRY_GETS)
    assert table["rendered_root_gets"] == str(RENDERED_ROOT_GETS)
    assert table["toc_patch_inputs"] == str(TOC_PATCH_INPUTS)
    assert table["authority_catalog_residual_count"] == str(AUTHORITY_CATALOG_RESIDUAL)
    assert table["body_residual_count"] == str(BODY_RESIDUAL)
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == "delegated Lexis frontier of 36,118 parser inputs"
    assert table["residual_first_url"] == FIRST_RESIDUAL_URL
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["toc_patch_wave_name"] == TOC_PATCH_WAVE_NAME
    assert table["ordered_request_wave_counts"] == "1,1,1,69,36046"
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
    assert table["ordered_content_path_sha256"] == OBSERVED_ORDERED_CONTENT_PATH_SHA256
    assert table["diagnostic_producer"].startswith(DIAGNOSTIC_PRODUCER_PREFIX)
    assert "ensure_ascii=False" in table["residual_sha_method"]
    assert "PATCH" in table["residual_sha_method"]

    assert OBSERVED_STRICT_REUSABLE_INPUT_COUNT == 0
    assert OBSERVED_AUTHORITY_CATALOG_RESIDUAL_COUNT == AUTHORITY_CATALOG_RESIDUAL
    assert OBSERVED_BODY_RESIDUAL_COUNT == OBSERVED_DOCUMENT_COUNT == BODY_RESIDUAL
    assert OBSERVED_TOTAL_RESIDUAL_COUNT == RESIDUAL_COUNT
    assert OBSERVED_CATALOG_TERMINAL_COUNT == CATALOG_TERMINALS
    assert OBSERVED_REPEATED_CITATION_IDENTITY_COUNT == REPEATED_CITATIONS
    assert (
        STATE_DELEGATION_GETS
        + PUBLISHER_ENTRY_GETS
        + RENDERED_ROOT_GETS
        + TOC_PATCH_INPUTS
        == AUTHORITY_CATALOG_RESIDUAL
    )
    assert AUTHORITY_CATALOG_RESIDUAL + BODY_RESIDUAL == RESIDUAL_COUNT
    assert EXPANDABLE_TITLE_ROOTS + DIRECT_RESERVED_TITLE_ROOTS == STATUTORY_TITLE_ROOTS
    assert (
        int(table["catalog_repealed"])
        + int(table["catalog_reserved"])
        + int(table["catalog_transferred"])
        + int(table["catalog_expired"])
        + int(table["catalog_obsolete"])
        == CATALOG_TERMINALS
    )
    assert CATALOG_TERMINALS + BODY_UNCLASSIFIED == BODY_RESIDUAL
    assert OBSERVED_ORDERED_CONTENT_PATH_SHA256.startswith(RESIDUAL_SHA256_PREFIX)

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "patch archive substitution" in lowered
    assert "synthetic v4" in lowered
    assert "hub mutation" in lowered
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "secondary" in lowered and "cache" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "36,118" in report
    assert "36,046" in report
    assert FIRST_RESIDUAL_URL in report
    assert PUBLIC_CONTAINER_URL in report
    assert TOC_ENDPOINT_URL in report
    assert RESIDUAL_SHA256_PREFIX in report
    assert INVENTED_TN_GOV_TITLE_URL not in report
    assert report.count("urn:contentItem:") < 8
    assert report.count("https://advance.lexis.com/shared/document/") < 4


def test_tennessee_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(TennesseeScraper)
    lexis = inspect.getsource(tennessee_lexis)
    fetch_source = inspect.getsource(TennesseeScraper._fetch_tennessee_lexis_get_wave)
    strict_source = inspect.getsource(
        TennesseeScraper._scrape_strict_tennessee_retained_frontier
    )
    assert "36,118" not in adapter
    assert str(RESIDUAL_COUNT) not in adapter
    assert str(BODY_RESIDUAL) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert SYNTHETIC_V4_RESPONSE_SHA_PREFIX not in adapter
    assert SYNTHETIC_V4_FRONTIER_PREFIX not in adapter
    assert INVENTED_TN_GOV_TITLE_URL not in adapter
    assert INVENTED_TN_GOV_TITLE_URL not in lexis
    assert "_ARCHIVE_BODY_URLS" not in fetch_source
    assert "_discover_archived_body_urls" not in fetch_source
    assert "document_url(node.link_href)" in strict_source
    assert "canonical_live_toc_patch_request" in strict_source
    content_item_literals = re.findall(
        r"urn:contentItem:[A-Za-z0-9:-]{8,}",
        adapter,
    )
    assert content_item_literals == []
    assert adapter.count("https://advance.lexis.com/shared/document/") == 0
    assert "observed[0:1]" not in adapter
    assert "observed[1:2]" not in adapter
    assert "observed[2:3]" not in adapter
    phase_source = inspect.getsource(TennesseeScraper._validate_tennessee_phase_reports)
    assert '"state_delegation": [observed[0]]' in phase_source
    assert '"publisher_entry": [observed[1]]' in phase_source
    assert '"rendered_container_root": [observed[2]]' in phase_source


def test_tennessee_residual_sha256_uses_canonical_json_of_ordered_get_urls() -> None:
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
    assert OBSERVED_ORDERED_CONTENT_PATH_SHA256 in report


def test_tennessee_one_domain_get_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(TennesseeScraper._fetch_tennessee_lexis_get_wave)
    assert "grouped_get_acquisition_contract" in fetch_source
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "prefer_direct=require_direct" in fetch_source
    assert "_fetch_page_contents_with_archival_fallback_retrying_residuals" in (
        fetch_source
    )
    assert "repeat_grouped_archive_inventory_on_residual=True" not in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "Lexis TOC ``PATCH``" in fetch_source
    assert "GET archive cannot bind" in fetch_source

    contract = grouped_get_acquisition_contract(
        [
            document_url(_content_path("TN01-TEST-BODY-00001-00")),
            document_url(_content_path("TN01-TEST-BODY-00002-00")),
        ]
    )
    assert contract["common_crawl_inventory_query_upper_bound"] == 1
    assert contract["group_warc_ranges_by_warc_filename"] is True
    assert contract["coalesce_compatible_warc_ranges"] is True
    assert contract["retry_residual_urls_only"] is True
    assert contract["per_page_archive_inventory_loop"] is False
    assert contract["wayback_prefix_inventory"] is True
    assert contract["source_domain"] == "advance.lexis.com"

    retry_source = inspect.getsource(
        BaseStateScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        TennesseeScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"archive_recovery_enabled": True' in closure_source
    assert '"body_get_transport": "direct_then_cdx"' in closure_source
    assert '"browser_transport": "browser_rendered"' in closure_source
    assert (
        '"get_acquisition_contract": "tennessee_current_authority_direct_only"'
        in closure_source
    )
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"toc_patch_archive_substitution_allowed": False' in closure_source


def test_tennessee_patch_identity_cannot_be_substituted_with_archive_get() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    scraper.OFFICIAL_TITLES = COMPACT_TITLES
    roots, tables = parse_root_html(
        _compact_root_html(),
        expected_titles=COMPACT_TITLES,
    )
    assert tables.title == "Volume 13 Tables"
    expandable = [node for node in roots if node.can_expand or node.has_children]
    assert len(expandable) == 1
    endpoint, request_body, patch_request = canonical_toc_patch_request(expandable[0])
    get_request = scraper._tennessee_get_request(endpoint)
    assert endpoint == TOC_ENDPOINT_URL
    assert patch_request["method"] == "PATCH"
    assert patch_request["request_body_sha256"] == hashlib.sha256(request_body).hexdigest()
    assert get_request == {
        "headers": {"Accept": TennesseeScraper.STRICT_GET_ACCEPT},
        "method": "GET",
        "url": endpoint,
    }
    assert get_request != patch_request
    assert "request_body_sha256" not in get_request

    fetch_source = inspect.getsource(TennesseeScraper._fetch_tennessee_lexis_get_wave)
    strict_source = inspect.getsource(
        TennesseeScraper._scrape_strict_tennessee_retained_frontier
    )
    assert "_fetch_tennessee_lexis_get_wave" not in strict_source
    assert "canonical_live_toc_patch_request" in strict_source
    assert "_replay_tennessee_retained_wave" in strict_source
    assert '"toc_patch_archive_substitution_allowed": False' in inspect.getsource(
        TennesseeScraper._scrape_strict_tennessee_retained_frontier
    )
    assert "PATCH" in fetch_source
    with pytest.raises(ValueError, match="exactly one source domain"):
        grouped_get_acquisition_contract([FIRST_RESIDUAL_URL, PUBLIC_CONTAINER_URL])


def test_tennessee_seed_and_host_replay_forbid_hub_docker_and_synthetic_v4(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "TN",
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
    assert "synthetic v4" in report
    assert "patch archive substitution" in report


def test_tennessee_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    tennessee_source = inspect.getsource(
        TennesseeScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in closure_source
    assert "retained_replay_network_requests" in tennessee_source
    assert tennessee_source.index('"retained_replay_network_requests": 0') > 0
    assert '"toc_patch_archive_substitution_allowed": False' in tennessee_source
    assert "Tennessee retained request/body identities changed on replay" in (
        tennessee_source
    )
    assert TennesseeScraper.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL == (
        FIRST_RESIDUAL_URL
    )


def test_tennessee_publisher_cookiesrequired_page_names_exact_container() -> None:
    live = (
        "<html><script>"
        "window.location.replace('/open/error/cookiesrequired?target=' + "
        "encodeURIComponent('/container?config="
        f"{PUBLIC_CONTAINER_CONFIG}"
        "&crid=78134f46-eb5a-4013-8166-2195b242c396'));"
        "</script>"
        "<a href='http://advance.lexis.com/open/entry/CaptureReturnUrl?"
        "target=%2Fcontainer%3Fconfig%3D"
        f"{PUBLIC_CONTAINER_CONFIG}"
        "'>continue</a></html>"
    )
    historic = (
        f"<html><a href='https://advance.lexis.com/container?config="
        f"{PUBLIC_CONTAINER_CONFIG}'>continue</a></html>"
    )
    assert publisher_container_delegation_present(live)
    assert publisher_container_delegation_present(historic)
    assert not publisher_container_delegation_present(
        "<html><script>window.location.replace('/open/error/cookiesrequired')"
        "</script></html>"
    )
    drifted = live.replace(
        PUBLIC_CONTAINER_CONFIG,
        "DRIFTED" + PUBLIC_CONTAINER_CONFIG[7:],
    )
    assert not publisher_container_delegation_present(drifted)


def _live_shaped_compact_root_html() -> str:
    href19 = _content_path("TN19-RSVD-0000-00000-00")
    href51 = _content_path("TN51-RSVD-0000-00000-00")
    title1 = (
        "<li class='js-node' data-nodeid='T001' data-nodepath='/ROOT/T001' "
        "data-level='1' data-title='TITLE 1 - Code and Statutes' "
        "data-haschildren='true'><div class='js-node-header'>"
        "<button data-command='open-to' data-targetlevel='2'>Open</button>"
        "<button data-command='open-to' data-targetlevel='3'>Open</button>"
        "</div></li>"
    )
    reserved19 = (
        '<li role="treeitem" class="js-node" data-nodeid="T019" '
        'data-nodepath="/ROOT/T019" data-level="1" data-haschildren="" '
        'data-title="Title 19 [Reserved]" '
        f'data-docfullpath="{href19}">'
        '<div class="js-node-header"><a href="#" data-action="toclink">'
        "<span>Title 19 [Reserved]</span></a></div></li>"
    )
    reserved51 = (
        '<li role="treeitem" class="js-node" data-nodeid="T051" '
        'data-nodepath="/ROOT/T051" data-level="1" data-haschildren="" '
        'data-title="Title 51 [Reserved]" '
        f'data-docfullpath="{href51}">'
        '<div class="js-node-header"><a href="#" data-action="toclink">'
        "<span>Title 51 [Reserved]</span></a></div></li>"
    )
    tables = (
        "<li class='js-node' data-nodeid='TAB13' data-nodepath='/ROOT/TAB13' "
        "data-level='1' data-title='Volume 13 Tables' data-haschildren='true'>"
        "<div class='js-node-header'></div></li>"
    )
    return (
        '<html><style>.la-NavigateTerms:before{content:"x"}</style><body>'
        '<td>Terms and Conditions by clicking "I Agree" below.</td>'
        f"{title1}{reserved19}{reserved51}{tables}</body></html>"
    )


def test_tennessee_free_public_access_toc_is_not_bootstrap_shell() -> None:
    roots, tables = parse_root_html(
        _live_shaped_compact_root_html(),
        expected_titles=COMPACT_TITLES,
    )
    reserved_node = next(node for node in roots if node.title_number == "19")
    assert reserved_node.title_label == "[Reserved]"
    assert reserved_node.is_document_locator
    assert not reserved_node.can_open
    assert "tables" in tables.title.casefold()
    with pytest.raises(ValueError, match="access or bootstrap shell"):
        parse_root_html(
            "<html><script>window.location.replace('/open/error/cookiesrequired')"
            "</script><p>Terms and Conditions I Agree</p></html>",
            expected_titles=COMPACT_TITLES,
        )


def test_tennessee_browser_waits_for_attached_toc_nodes() -> None:
    source = inspect.getsource(acquire_live_catalog)
    assert 'state="attached"' in source
    assert "I Agree" in source
    assert "timeout=min(timeout, 30_000)" not in source


def test_tennessee_compact_recipe_emits_ga_first_residual_not_static_bodies() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    scraper.OFFICIAL_TITLES = COMPACT_TITLES
    get_request = scraper._tennessee_get_request
    roots, _tables = parse_root_html(
        _compact_root_html(),
        expected_titles=COMPACT_TITLES,
    )
    expandable = [node for node in roots if node.can_expand or node.has_children]
    endpoint, _body, patch_request = canonical_toc_patch_request(expandable[0])
    payload, href = _title_one_subtree_payload(expandable[0])
    del payload
    document_nodes = [
        node for node in roots if node.is_document_locator
    ]
    body_urls = [
        document_url(href),
        *[document_url(node.link_href) for node in document_nodes],
    ]
    authority = [
        (FIRST_RESIDUAL_URL, get_request(FIRST_RESIDUAL_URL)),
        (PUBLIC_ENTRY_URL, get_request(PUBLIC_ENTRY_URL)),
        (PUBLIC_CONTAINER_URL, canonical_rendered_root_request()),
    ]
    patch_requests = [(endpoint, patch_request)]
    body_requests = [(url, get_request(url)) for url in body_urls]
    residual = _source_ordered_tennessee_residual(
        authority=authority,
        patch_requests=patch_requests,
        body_requests=body_requests,
        retained_keys=set(),
    )
    assert residual[0][0] == FIRST_RESIDUAL_URL
    assert residual[0][1]["method"] == "GET"
    assert residual[3][0] == TOC_ENDPOINT_URL
    assert residual[3][1]["method"] == "PATCH"
    assert INVENTED_TN_GOV_TITLE_URL not in [url for url, _request in residual]
    assert DEAD_TN_GOV_ENTRY not in [url for url, _request in residual]
    assert len(residual) == 3 + 1 + 3
    after_authority = _source_ordered_tennessee_residual(
        authority=authority,
        patch_requests=patch_requests,
        body_requests=body_requests,
        retained_keys={
            json.dumps([url, request], sort_keys=True, separators=(",", ":"))
            for url, request in authority
        },
    )
    assert after_authority[0][1]["method"] == "PATCH"
    assert after_authority[0][0] == TOC_ENDPOINT_URL
    digest = _canonical_residual_sha256([url for url, _request in residual if _request["method"] == "GET"])
    assert not digest.startswith(RESIDUAL_SHA256_PREFIX)


def test_tennessee_compact_retained_five_wave_replay_is_ledger_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    _bind_phase(scraper)
    scraper.OFFICIAL_TITLES = COMPACT_TITLES
    scraper.ENFORCE_OBSERVED_TN_FRONTIER = False
    ledger = _TennesseeRetainedLedger()
    scraper._state_law_acquisition_ledger = ledger
    get_request = scraper._tennessee_get_request
    authority_body = (
        b"<html><a href='https://www.lexisnexis.com/hottopics/tncode'>"
        b"Tennessee Code</a></html>"
    )
    publisher_body = (
        f"<html><a href='{PUBLIC_CONTAINER_URL}'>continue</a></html>"
    ).encode()
    root_body = _compact_root_html().encode()
    ledger.add(FIRST_RESIDUAL_URL, get_request(FIRST_RESIDUAL_URL), authority_body)
    ledger.add(PUBLIC_ENTRY_URL, get_request(PUBLIC_ENTRY_URL), publisher_body)
    ledger.add(PUBLIC_CONTAINER_URL, _root_request(), root_body)

    roots, _tables = parse_root_html(
        root_body.decode(),
        expected_titles=COMPACT_TITLES,
    )
    expandable = [node for node in roots if node.can_expand or node.has_children]
    payload, href = _title_one_subtree_payload(expandable[0])
    endpoint, _request_body, patch_request = canonical_live_toc_patch_request(
        expandable[0],
        acquisition_phase_id=PHASE_ID,
        acquisition_phase_started_at=PHASE_STARTED_AT,
        session_request_id_sha256=SESSION_SHA256,
    )
    ledger.add(endpoint, patch_request, json.dumps(payload).encode())
    body_nodes = [
        TennesseeLexisNode(
            node_id="D001",
            title="1-1-1. Test provision",
            level=2,
            node_path=f"{expandable[0].node_path}/D001",
            can_expand=False,
            can_open=True,
            has_children=False,
            link_href=href,
        ),
        *[node for node in roots if node.is_document_locator],
    ]
    for node in body_nodes:
        url = document_url(node.link_href)
        if node.title_number in {"19", "51"} or "[Reserved]" in node.title:
            body = b"<html><main data-document-content><p>[Reserved]</p></main></html>"
        else:
            body = (
                "<html><main data-document-content>"
                "<h1>1-1-1. Test provision</h1>"
                "<p>This retained official provision contains operative text.</p>"
                "</main></html>"
            ).encode()
        ledger.add(url, get_request(url), body)

    async def _get_wave_must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "Tennessee compact residual must not open a GET archive wave during ledger replay"
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        TennesseeScraper,
        "_fetch_tennessee_lexis_get_wave",
        _get_wave_must_not_run,
    )

    rows = asyncio.run(
        scraper.scrape_code(
            "Tennessee Code Annotated",
            scraper.AUTHORIZED_CODE_ENTRY_URL,
            max_statutes=None,
        )
    )

    assert [len(call) for call in ledger.calls] == [1, 1, 1, 3]
    assert all(request["method"] == "PATCH" for _url, request in ledger.calls[2])
    assert all(request["method"] == "GET" for _url, request in ledger.calls[3])
    assert ledger.calls[0][0][0] == FIRST_RESIDUAL_URL
    assert len(rows) == 1
    report = scraper.last_tennessee_full_corpus_report
    assert report["closed"] is True
    assert report["retained_replay_only"] is True
    assert report["network_requested_pages"] == 0
    assert report["ordered_request_wave_counts"] == [1, 1, 1, 1, 3]
    assert report["toc_patch_archive_substitution_allowed"] is False
    assert report["per_page_archive_inventory_loop"] is False
    assert report["source_input_count"] == 7


@pytest.mark.anyio
async def test_tennessee_real_closure_keeps_catalog_authority_truthful_and_binds_lexis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    _bind_phase(scraper)
    scraper.OFFICIAL_TITLES = COMPACT_TITLES
    scraper.ENFORCE_OBSERVED_TN_FRONTIER = False
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "ledger",
        jurisdiction="TN",
        parser_name="tennessee-integration-test",
        load_existing=False,
    )
    scraper.attach_state_law_acquisition_ledger(ledger)

    def _retain(
        url: str,
        request: Mapping[str, Any],
        body: bytes,
        *,
        browser: bool = False,
    ) -> None:
        observed_at = datetime.now(UTC).isoformat()
        pagination: dict[str, Any] = {
            "tennessee_acquisition_phase": {
                "phase_id": PHASE_ID,
                "schema_version": TennesseeScraper.TN_PHASE_SCHEMA,
                "started_at": PHASE_STARTED_AT,
            }
        }
        if browser:
            patch = request.get("method") == "PATCH"
            pagination["tennessee_browser_response"] = {
                "final_url": TOC_ENDPOINT_URL if patch else PUBLIC_CONTAINER_URL,
                "final_url_sha256": hashlib.sha256(
                    (TOC_ENDPOINT_URL if patch else PUBLIC_CONTAINER_URL).encode()
                ).hexdigest(),
                "redirect_chain": [],
                "redirected": False,
                "response_observed_at": observed_at,
                "session_request_id_sha256": SESSION_SHA256,
            }
        digest = hashlib.sha256(body).hexdigest()
        ledger.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt={
                "content_sha256": digest,
                "official_url": url,
                "source_transport": "browser_rendered" if browser else "direct",
            },
            retrieved_at=observed_at,
            response_status=200,
            media_type="application/json" if request.get("method") == "PATCH" else "text/html",
            sanitized_request=request,
            pagination=pagination,
            network_used=True,
        )

    root_body = _compact_root_html().encode()
    _retain(
        FIRST_RESIDUAL_URL,
        scraper._tennessee_get_request(FIRST_RESIDUAL_URL),
        (
            b"<html><a href='https://www.lexisnexis.com/hottopics/tncode'>"
            b"Tennessee Code</a></html>"
        ),
    )
    _retain(
        PUBLIC_ENTRY_URL,
        scraper._tennessee_get_request(PUBLIC_ENTRY_URL),
        f"<html><a href='{PUBLIC_CONTAINER_URL}'>continue</a></html>".encode(),
    )
    _retain(PUBLIC_CONTAINER_URL, _root_request(), root_body, browser=True)
    roots, _tables = parse_root_html(root_body.decode(), expected_titles=COMPACT_TITLES)
    expandable = next(node for node in roots if node.can_expand or node.has_children)
    subtree, href = _title_one_subtree_payload(expandable)
    endpoint, _request_body, patch_request = canonical_live_toc_patch_request(
        expandable,
        acquisition_phase_id=PHASE_ID,
        acquisition_phase_started_at=PHASE_STARTED_AT,
        session_request_id_sha256=SESSION_SHA256,
    )
    _retain(endpoint, patch_request, json.dumps(subtree).encode(), browser=True)
    body_nodes = [
        TennesseeLexisNode(
            node_id="D001",
            title="1-1-1. Test provision",
            level=2,
            node_path=f"{expandable.node_path}/D001",
            can_expand=False,
            can_open=True,
            has_children=False,
            link_href=href,
        ),
        *[node for node in roots if node.is_document_locator],
    ]
    for node in body_nodes:
        url = document_url(node.link_href)
        body = (
            b"<html><main data-document-content><p>[Reserved]</p></main></html>"
            if node.title_number in {"19", "51"} or "[Reserved]" in node.title
            else (
                b"<html><main data-document-content><h1>1-1-1. Test provision</h1>"
                b"<p>This retained official provision contains operative text.</p>"
                b"</main></html>"
            )
        )
        _retain(url, scraper._tennessee_get_request(url), body)
    ledger.retained_replay_only = True
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    rows = await scraper.scrape_code(
        "Tennessee Code Annotated",
        scraper.AUTHORIZED_CODE_ENTRY_URL,
        max_statutes=None,
    )
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="TN",
    )
    closure_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection
    )

    assert closure_path is not None and closure_path.is_file()
    retained = json.loads(closure_path.read_text(encoding="utf-8"))
    completion = retained["completion_receipt"]
    assert retained["official_source_url"] == FIRST_RESIDUAL_URL
    assert retained["acquisition_path_ids"] == ["tn-tga"]
    assert completion["source_domain"] == "wapp.capitol.tn.gov"
    assert completion["delegating_authority_url"] == FIRST_RESIDUAL_URL
    assert completion["delegated_body_source_domain"] == "advance.lexis.com"
    assert completion["transport"]["archive_recovery_enabled"] is True
    assert completion["transport"]["body_get_transport"] == "direct_then_cdx"
    assert completion["transport"]["browser_transport"] == "browser_rendered"
    assert (
        completion["transport"]["get_acquisition_contract"]
        == "tennessee_current_authority_direct_only"
    )
    assert completion["transport"]["grouped_warc_recovery"] is True
    body_authority = completion["delegated_body_authority"]
    assert body_authority["body_input_count"] == 3
    assert len(body_authority["acquisition_phase"]["input_receipt_sha256s"]) == 7
    assert require_authoritative_admission(
        "TN",
        ["tn-tga"],
        source_url=FIRST_RESIDUAL_URL,
        release_point=retained["release_point"],
    ).admitted is True


def test_real_ledger_partial_resume_selects_latest_coherent_root_observation(
    tmp_path: Path,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    _bind_phase(scraper)
    scraper.OFFICIAL_TITLES = COMPACT_TITLES
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "ledger",
        jurisdiction="TN",
        parser_name="tennessee-root-resume-test",
        load_existing=False,
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    request = canonical_rendered_root_request(
        acquisition_phase_id=PHASE_ID,
        acquisition_phase_started_at=PHASE_STARTED_AT,
    )
    first_body = _compact_root_html().encode()
    second_body = first_body + b"\n<!-- semantically coherent revalidation -->\n"
    first_boundary = datetime.now(UTC)
    second_boundary = first_boundary + timedelta(microseconds=1)
    second_session_sha256 = hashlib.sha256(b"second-browser-session").hexdigest()

    def _retain(body: bytes, observed_at: datetime, session_sha256: str) -> None:
        observed = observed_at.isoformat()
        scraper._retain_tennessee_browser_input(
            body=body,
            media_type="text/html",
            observed_at=observed,
            official_url=PUBLIC_CONTAINER_URL,
            response_proof={
                "final_url": PUBLIC_CONTAINER_URL,
                "final_url_sha256": hashlib.sha256(
                    PUBLIC_CONTAINER_URL.encode()
                ).hexdigest(),
                "redirect_chain": [],
                "redirected": False,
                "response_observed_at": observed,
                "session_request_id_sha256": session_sha256,
            },
            response_status=200,
            sanitized_request=request,
        )

    _retain(first_body, first_boundary, SESSION_SHA256)
    _retain(second_body, second_boundary, second_session_sha256)

    assert len(ledger.entries) == 2
    with pytest.raises(StateLawMultiFetchAcquisitionError, match="ambiguous"):
        ledger.replay_retained_parser_input(
            official_url=PUBLIC_CONTAINER_URL,
            sanitized_request=request,
        )
    selected = scraper._replay_optional_tennessee_input(
        PUBLIC_CONTAINER_URL,
        request,
    )
    assert selected.body == second_body
    assert (
        selected.response_proof["session_request_id_sha256"]
        == second_session_sha256
    )


def test_tennessee_retained_replay_only_patch_miss_does_not_open_get_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    _bind_phase(scraper)
    scraper.OFFICIAL_TITLES = COMPACT_TITLES
    scraper.ENFORCE_OBSERVED_TN_FRONTIER = False
    ledger = _TennesseeRetainedLedger()
    scraper._state_law_acquisition_ledger = ledger
    get_request = scraper._tennessee_get_request
    ledger.add(
        FIRST_RESIDUAL_URL,
        get_request(FIRST_RESIDUAL_URL),
        (
            b"<html><a href='https://www.lexisnexis.com/hottopics/tncode'>"
            b"Tennessee Code</a></html>"
        ),
    )
    ledger.add(
        PUBLIC_ENTRY_URL,
        get_request(PUBLIC_ENTRY_URL),
        f"<html><a href='{PUBLIC_CONTAINER_URL}'>continue</a></html>".encode(),
    )
    ledger.add(
        PUBLIC_CONTAINER_URL,
        _root_request(),
        _compact_root_html().encode(),
    )
    get_wave_calls: list[list[str]] = []

    async def _get_wave(self: Any, urls: Any, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        get_wave_calls.append(requested)
        raise AssertionError(
            "Tennessee PATCH miss must not fall back to a GET archive wave"
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(TennesseeScraper, "_fetch_tennessee_lexis_get_wave", _get_wave)

    with pytest.raises(StateLawRetainedReplayOnlyError, match="ledger miss"):
        asyncio.run(
            scraper.scrape_code(
                "Tennessee Code Annotated",
                scraper.AUTHORIZED_CODE_ENTRY_URL,
                max_statutes=None,
            )
        )
    assert get_wave_calls == []
    assert [len(call) for call in ledger.calls] == [1, 1, 1]
    assert ledger.calls[2][0][0] == TOC_ENDPOINT_URL
    assert ledger.calls[2][0][1]["method"] == "PATCH"


def test_tennessee_full_route_without_retained_ledger_remains_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    with pytest.raises(RuntimeError, match="retained-replay-only ledger"):
        asyncio.run(
            scraper.scrape_code(
                "Tennessee Code Annotated",
                scraper.AUTHORIZED_CODE_ENTRY_URL,
                max_statutes=None,
            )
        )
    assert "synthetic tn.gov" in scraper.STRICT_FULL_BLOCKER
    assert "Justia" in scraper.STRICT_FULL_BLOCKER

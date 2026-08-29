from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    strict_frontier_closure,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee import (
    TennesseeScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee_lexis import (
    OBSERVED_ALL_NODE_MEMBERSHIP_SHA256,
    OBSERVED_AUTHORITY_CATALOG_RESIDUAL_COUNT,
    OBSERVED_BODY_RESIDUAL_COUNT,
    OBSERVED_DOCUMENT_COUNT,
    OBSERVED_DOCUMENT_MEMBERSHIP_SHA256,
    OBSERVED_ORDERED_CONTENT_PATH_SHA256,
    OBSERVED_ROOT_MEMBERSHIP_SHA256,
    OBSERVED_STRICT_REUSABLE_INPUT_COUNT,
    OBSERVED_SUBTREE_MANIFEST_SHA256,
    OBSERVED_TOTAL_RESIDUAL_COUNT,
    PUBLIC_CONTAINER_URL,
    TOC_ENDPOINT_URL,
    TennesseeLexisNode,
    canonical_toc_patch_request,
    derive_exact_metadata_frontier,
    document_url,
    grouped_get_acquisition_contract,
    observed_metadata_drift,
    parse_root_html,
    parse_tennessee_lexis_document_html,
    parse_title_subtree_payload,
    unresolved_temporal_variant_groups,
    valid_document_payload,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee_lexis_live import (
    TennesseeLiveCatalog,
    TennesseeRetainedBrowserInput,
    acquire_live_catalog,
    assert_rendered_root_coherence,
    canonical_live_toc_patch_request,
    canonical_rendered_root_request,
)

PHASE_ID = hashlib.sha256(b"tennessee-test-phase").hexdigest()
PHASE_STARTED_AT = datetime.now(UTC).replace(microsecond=0).isoformat()
SESSION_ID = "test-session-request-id"
SESSION_SHA256 = hashlib.sha256(SESSION_ID.encode()).hexdigest()


def _bind_phase(scraper: TennesseeScraper) -> None:
    scraper._tennessee_acquisition_phase_id = PHASE_ID
    scraper._tennessee_acquisition_phase_started_at = PHASE_STARTED_AT


def _root_request() -> dict[str, Any]:
    return canonical_rendered_root_request(
        acquisition_phase_id=PHASE_ID,
        acquisition_phase_started_at=PHASE_STARTED_AT,
    )


def _content_path(token: str) -> str:
    return (
        "/shared/document/statutes-legislation/"
        f"urn:contentItem:{token}"
    )


def _root_html(scraper: TennesseeScraper, *, target_level: int = 2) -> str:
    elements: list[str] = []
    for number, label in scraper.OFFICIAL_TITLES:
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


def _subtree_payload(parent: TennesseeLexisNode) -> tuple[dict[str, Any], str]:
    number = str(parent.title_number)
    node_id = f"D{int(number):03d}"
    href = _content_path(f"TN{int(number):02d}-TEST-BODY-00000-00")
    return (
        {
            "collections": {
                "toccontainer": {
                    "collections": {
                        "tocnodes": [
                            _node_mapping(
                                node_id=node_id,
                                title=f"{number}-1-1. Test provision",
                                level=2,
                                path=f"{parent.node_path}/{node_id}",
                                href=href,
                            )
                        ]
                    }
                }
            }
        },
        href,
    )


def test_exact_root_parser_preserves_source_order_and_direct_reserved_titles() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    roots, tables = parse_root_html(
        _root_html(scraper),
        expected_titles=scraper.OFFICIAL_TITLES,
    )

    assert len(roots) == 71
    assert [node.title_number for node in roots] == [str(i) for i in range(1, 72)]
    assert tables.title == "Volume 13 Tables"
    assert [node.title_number for node in roots if node.is_document_locator] == [
        "19",
        "51",
    ]
    assert sum(bool(node.open_to_levels) for node in roots) == 69
    assert all(
        node.open_to_levels == (2,)
        for node in roots
        if node.title_number not in {"19", "51"}
    )


def test_root_parser_rejects_missing_title_and_nonstatutory_document_path() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    missing = _root_html(scraper).replace(
        "data-title=\"TITLE 71 - Welfare\"",
        "data-title=\"TITLE 70 - Welfare\"",
    )
    unsafe = _root_html(scraper).replace(
        _content_path("TN19-RSVD-0000-00000-00"),
        "/shared/document/cases/urn:contentItem:TN19-RSVD-0000-00000-00",
    )

    with pytest.raises(ValueError, match="source order or membership"):
        parse_root_html(missing, expected_titles=scraper.OFFICIAL_TITLES)
    with pytest.raises(ValueError, match="malformed or duplicate"):
        parse_root_html(unsafe, expected_titles=scraper.OFFICIAL_TITLES)


def test_deepest_toc_parser_closes_ancestry_and_preserves_duplicate_citations() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    roots, _tables = parse_root_html(
        _root_html(scraper, target_level=3),
        expected_titles=scraper.OFFICIAL_TITLES,
    )
    parent = roots[0]
    chapter = _node_mapping(
        node_id="C001",
        title="CHAPTER 1",
        level=2,
        path=f"{parent.node_path}/C001",
        expandable=True,
    )
    first = _node_mapping(
        node_id="D001A",
        title="1-1-1. First temporal source variant",
        level=3,
        path=f"{parent.node_path}/C001/D001A",
        href=_content_path("TN01-TEST-BODY-00001-00"),
    )
    second = _node_mapping(
        node_id="D001B",
        title="1-1-1. Second temporal source variant",
        level=3,
        path=f"{parent.node_path}/C001/D001B",
        href=_content_path("TN01-TEST-BODY-00002-00"),
    )
    payload = {"collections": {"toccontainer": {"collections": {"tocnodes": [chapter, first, second]}}}}

    nodes, closed_ids, error = parse_title_subtree_payload(
        payload,
        parent=parent,
        target_level=3,
    )

    assert error == ""
    assert [node.node_id for node in nodes] == ["C001", "D001A", "D001B"]
    assert closed_ids == (parent.node_id, "C001")
    frontier = derive_exact_metadata_frontier(
        [parent],
        subtrees_by_root_id={parent.node_id: nodes},
    )
    assert frontier["document_count"] == 2
    assert frontier["unique_citation_label_count"] == 1
    assert frontier["repeated_citation_identity_count"] == 1
    assert len(frontier["document_nodes"]) == 2


def test_deepest_toc_parser_rejects_orphan_and_cross_title_citation() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    roots, _tables = parse_root_html(
        _root_html(scraper, target_level=3),
        expected_titles=scraper.OFFICIAL_TITLES,
    )
    parent = roots[0]
    orphan = _node_mapping(
        node_id="D999",
        title="2-1-1. Crossed title",
        level=3,
        path=f"{parent.node_path}/MISSING/D999",
        href=_content_path("TN02-TEST-BODY-00999-00"),
    )
    payload = {"collections": {"toccontainer": {"collections": {"tocnodes": [orphan]}}}}

    nodes, closed, error = parse_title_subtree_payload(
        payload,
        parent=parent,
        target_level=3,
    )

    assert nodes == []
    assert closed == ()
    assert "outside its exact title hierarchy" in error


def test_canonical_patch_request_binds_method_body_and_maximum_level() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    roots, _tables = parse_root_html(
        _root_html(scraper, target_level=5),
        expected_titles=scraper.OFFICIAL_TITLES,
    )

    endpoint, body, request = canonical_toc_patch_request(roots[0])

    assert endpoint == TOC_ENDPOINT_URL
    assert request["method"] == "PATCH"
    assert request["request_body_length"] == len(body)
    assert request["request_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert json.loads(body)["props"]["items"][-1] == {
        "fieldName": "targetLevel",
        "value": 5,
    }
    assert request["headers"] == {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/json",
    }


def _document_node(*, node_id: str, token: str, title: str) -> TennesseeLexisNode:
    return TennesseeLexisNode(
        node_id=node_id,
        title=title,
        level=3,
        node_path=f"/ROOT/T001/C001/{node_id}",
        can_expand=False,
        can_open=True,
        has_children=False,
        link_href=_content_path(token),
    )


def test_document_parser_retains_history_removes_annotations_and_path_keys_variants() -> None:
    first = _document_node(
        node_id="D001A",
        token="TN01-TEST-BODY-00001-00",
        title="1-1-1. Test provision",
    )
    second = _document_node(
        node_id="D001B",
        token="TN01-TEST-BODY-00002-00",
        title="1-1-1. Test provision",
    )
    html = """
    <html><main data-document-content>
      <h1>1-1-1. Test provision</h1>
      <p>The General Assembly enacts this operative statutory sentence.</p>
      <h2>Case Notes</h2><p>Publisher-only annotation must disappear.</p>
      <h2>History</h2><p>Acts 2026, ch. 1, § 2.</p>
    </main></html>
    """

    rows_a, report_a = parse_tennessee_lexis_document_html(
        html,
        source_url=document_url(first.link_href),
        node=first,
        source_order=0,
    )
    rows_b, report_b = parse_tennessee_lexis_document_html(
        html,
        source_url=document_url(second.link_href),
        node=second,
        source_order=1,
    )

    assert report_a["closed"] is report_b["closed"] is True
    assert len(rows_a) == len(rows_b) == 1
    assert "operative statutory sentence" in rows_a[0].full_text
    assert "Acts 2026" in rows_a[0].full_text
    assert "Publisher-only annotation" not in rows_a[0].full_text
    assert (
        rows_a[0].structured_data["canonical_section_key"]
        != rows_b[0].structured_data["canonical_section_key"]
    )
    assert rows_a[0].source_url != rows_b[0].source_url
    temporal_residuals = unresolved_temporal_variant_groups([rows_a[0], rows_b[0]])
    assert len(temporal_residuals) == 1
    assert temporal_residuals[0]["candidate_count"] == 2
    assert temporal_residuals[0]["reason"] == (
        "repeated_citation_requires_source_bound_temporal_reconciliation"
    )


def test_document_parser_requires_body_confirmation_for_catalog_terminal() -> None:
    node = _document_node(
        node_id="D019",
        token="TN19-RSVD-0000-00000-00",
        title="[Reserved]",
    )
    terminal_rows, terminal_report = parse_tennessee_lexis_document_html(
        "<html><main data-document-content><p>[Reserved]</p></main></html>",
        source_url=document_url(node.link_href),
        node=node,
        source_order=0,
    )
    residual_rows, residual_report = parse_tennessee_lexis_document_html(
        "<html><main data-document-content><p>Substantive unexpected body.</p></main></html>",
        source_url=document_url(node.link_href),
        node=node,
        source_order=0,
    )

    assert terminal_rows == []
    assert terminal_report["closed"] is True
    assert terminal_report["terminal_dispositions"][0]["disposition"] == "reserved"
    assert residual_rows == []
    assert residual_report["closed"] is False
    assert residual_report["parser_residuals"][0]["reason"] == (
        "catalog_terminal_not_confirmed_by_document_body"
    )


@pytest.mark.parametrize(
    "shell",
    [
        b"<html><body>RobotValidation</body></html>",
        b"<html><body>Confirm you are human CAPTCHA</body></html>",
        b"<html><body>Sign in to continue</body></html>",
        b"<html><body>Results for: 1-1-1</body></html>",
    ],
)
def test_document_validator_rejects_access_and_search_shells(shell: bytes) -> None:
    assert valid_document_payload(shell) is False


@pytest.mark.anyio
async def test_future_get_wave_reuses_shared_plural_archive_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    urls = [
        f"https://advance.lexis.com{_content_path('TN01-TEST-BODY-00001-00')}",
        f"https://advance.lexis.com{_content_path('TN01-TEST-BODY-00002-00')}",
    ]
    payloads = [
        b"<html><main data-document-content>one</main></html>",
        b"<html><main data-document-content>two</main></html>",
    ]
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(
        requested: list[str],
        **kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        calls.append((list(requested), dict(kwargs)))
        return StateLawPageMultiFetchResult(
            urls=list(requested),
            payloads=list(payloads),
            errors=[None, None],
            transport_receipts=[{}, {}],
            parser_input_envelopes=[None, None],
            stats={},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    batch = await scraper._fetch_tennessee_lexis_get_wave(
        urls,
        frontier_name="body",
        content_validator=valid_document_payload,
    )

    assert batch.urls == urls
    assert len(calls) == 1
    assert calls[0][0] == urls
    kwargs = calls[0][1]
    assert kwargs["common_crawl_domain_terms"] == ("advance.lexis.com",)
    assert kwargs["wayback_prefix_inventory"] is True
    assert kwargs["prefer_direct"] is True
    assert kwargs["residual_retry_attempts"] in range(4)
    assert kwargs["headers"]["Accept"] == TennesseeScraper.STRICT_GET_ACCEPT
    assert scraper._tennessee_get_request(urls[0])["headers"] == {
        "Accept": TennesseeScraper.STRICT_GET_ACCEPT
    }
    assert canonical_rendered_root_request()["headers"] == {
        "Accept": TennesseeScraper.STRICT_GET_ACCEPT
    }
    contract = grouped_get_acquisition_contract(urls)
    assert contract["common_crawl_inventory_query_upper_bound"] == 1
    assert contract["group_warc_ranges_by_warc_filename"] is True
    assert contract["coalesce_compatible_warc_ranges"] is True
    assert contract["retry_residual_urls_only"] is True
    assert contract["per_page_archive_inventory_loop"] is False


@pytest.mark.anyio
async def test_current_get_wave_rejects_archival_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    url = scraper.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL
    payload = (
        b"<html><a href='https://www.lexisnexis.com/hottopics/tncode'>"
        b"Tennessee Code</a></html>"
    )

    async def _plural(
        requested: list[str],
        **kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        assert kwargs["archive_recovery_enabled"] is False
        return StateLawPageMultiFetchResult(
            urls=list(requested),
            payloads=[payload],
            errors=[None],
            transport_receipts=[{"source_transport": "common_crawl"}],
            parser_input_envelopes=[None],
            stats={"common_crawl_inventory_queries": 0},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    with pytest.raises(RuntimeError, match="non-direct"):
        await scraper._fetch_tennessee_lexis_get_wave(
            [url],
            frontier_name="General Assembly delegation",
            content_validator=lambda value: value == payload,
            require_direct=True,
        )


@pytest.mark.anyio
async def test_live_catalog_reuses_complete_retained_root_and_patch_wave() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    compact_titles = (
        ("1", "Code and Statutes"),
        ("19", "[Reserved]"),
        ("51", "[Reserved]"),
    )
    scraper.OFFICIAL_TITLES = compact_titles
    compact_root = _root_html(scraper).encode()
    roots, _tables = parse_root_html(
        compact_root.decode(),
        expected_titles=compact_titles,
    )
    parent = next(node for node in roots if node.can_expand or node.has_children)
    subtree, _href = _subtree_payload(parent)
    endpoint, _body, patch_request = canonical_toc_patch_request(parent)
    retained = {
        json.dumps(
            [PUBLIC_CONTAINER_URL, _root_request()],
            sort_keys=True,
            separators=(",", ":"),
        ): compact_root,
        json.dumps(
            [endpoint, patch_request],
            sort_keys=True,
            separators=(",", ":"),
        ): json.dumps(subtree).encode(),
    }

    def _replay(url: str, request: dict[str, Any]) -> bytes | None:
        return retained.get(
            json.dumps([url, request], sort_keys=True, separators=(",", ":"))
        )

    def _retain(**_kwargs: Any) -> None:
        raise AssertionError("complete retained catalog must not be reacquired")

    inventory = await acquire_live_catalog(
        acquisition_phase_id=PHASE_ID,
        acquisition_phase_started_at=PHASE_STARTED_AT,
        expected_titles=compact_titles,
        expected_patch_count=1,
        retain_parser_input=_retain,
        replay_parser_input=_replay,
    )

    assert inventory.network_patch_count == 0
    assert inventory.retained_patch_count == 1
    assert inventory.metadata["document_count"] == 3


def test_resumed_browser_root_must_match_retained_semantic_projection() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    retained = _root_html(scraper).encode()
    semantically_changed = retained.replace(
        b'data-nodeid="T001"',
        b'data-nodeid="DRIFT"',
        1,
    )

    assert_rendered_root_coherence(
        retained_payload=retained,
        live_payload=retained,
        expected_titles=scraper.OFFICIAL_TITLES,
    )
    with pytest.raises(RuntimeError, match="semantic"):
        assert_rendered_root_coherence(
            retained_payload=retained,
            live_payload=semantically_changed,
            expected_titles=scraper.OFFICIAL_TITLES,
        )


def test_publisher_delegation_receipt_accepts_only_named_locator_fields() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")

    assert scraper._tennessee_receipt_proves_container(
        {"final_url": PUBLIC_CONTAINER_URL}
    )
    assert scraper._tennessee_receipt_proves_container(
        {"redirect_chain": [{"location": PUBLIC_CONTAINER_URL}]}
    )
    assert not scraper._tennessee_receipt_proves_container(
        {"diagnostic": {"note": PUBLIC_CONTAINER_URL}}
    )
    assert not scraper._tennessee_receipt_proves_container(
        {"headers": {"X-Debug": PUBLIC_CONTAINER_URL}}
    )


def _compact_phase_reports(scraper: TennesseeScraper) -> list[dict[str, Any]]:
    roles_urls_transports = [
        (
            "state_delegation",
            scraper.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL,
            "direct",
        ),
        ("publisher_entry", scraper.AUTHORIZED_CODE_ENTRY_URL, "direct"),
        ("rendered_container_root", PUBLIC_CONTAINER_URL, "browser_rendered"),
        ("title_open_to_response", TOC_ENDPOINT_URL, "browser_rendered"),
        (
            "statute_document_body",
            f"https://advance.lexis.com{_content_path('TN01-TEST-BODY-00001-00')}",
            "direct",
        ),
    ]
    observed_at = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []
    for position, (role, url, transport) in enumerate(roles_urls_transports):
        row = {
            "acquisition_phase_id": PHASE_ID,
            "acquisition_phase_started_at": PHASE_STARTED_AT,
            "content_sha256": hashlib.sha256(f"content-{position}".encode()).hexdigest(),
            "observed_at": observed_at,
            "parser_input_receipt_sha256": hashlib.sha256(
                f"receipt-{position}".encode()
            ).hexdigest(),
            "request_identity_sha256": hashlib.sha256(
                f"request-{position}".encode()
            ).hexdigest(),
            "source_order": position,
            "source_role": role,
            "source_transport": transport,
            "source_url": url,
        }
        if role in {"rendered_container_root", "title_open_to_response"}:
            row.update(
                {
                    "response_redirected": False,
                    "session_request_id_sha256": SESSION_SHA256,
                }
            )
        rows.append(row)
    return rows


def test_phase_closure_rejects_cross_phase_and_malformed_temporal_inputs() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    _bind_phase(scraper)
    reports = _compact_phase_reports(scraper)

    projection = scraper._validate_tennessee_phase_reports(
        reports,
        patch_count=1,
        body_count=1,
    )
    assert projection["phase_id"] == PHASE_ID
    assert projection["delegating_authority_url"] == (
        scraper.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL
    )

    cross_phase = [dict(item) for item in reports]
    cross_phase[-1]["acquisition_phase_id"] = hashlib.sha256(
        b"different-phase"
    ).hexdigest()
    with pytest.raises(RuntimeError, match="mixed acquisition phases"):
        scraper._validate_tennessee_phase_reports(
            cross_phase,
            patch_count=1,
            body_count=1,
        )

    malformed = [dict(item) for item in reports]
    malformed[-1]["observed_at"] = "2026-08-29T12:00:00"
    with pytest.raises(RuntimeError, match="requires a timezone"):
        scraper._validate_tennessee_phase_reports(
            malformed,
            patch_count=1,
            body_count=1,
        )

    out_of_order = [dict(item) for item in reports]
    boundary = datetime.now(UTC)
    out_of_order[3]["observed_at"] = (boundary + timedelta(seconds=1)).isoformat()
    out_of_order[4]["observed_at"] = boundary.isoformat()
    with pytest.raises(RuntimeError, match="temporal wave order"):
        scraper._validate_tennessee_phase_reports(
            out_of_order,
            patch_count=1,
            body_count=1,
        )


def test_partial_browser_resume_rejects_cross_phase_before_ledger_lookup() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    _bind_phase(scraper)
    replay_calls: list[dict[str, Any]] = []
    scraper._state_law_acquisition_ledger = SimpleNamespace(
        entries=(),
        replay_retained_parser_input=lambda **kwargs: replay_calls.append(kwargs),
        retained_replay_only=False,
    )
    other_phase = hashlib.sha256(b"other-partial-phase").hexdigest()

    with pytest.raises(RuntimeError, match="crossed acquisition phases"):
        scraper._replay_optional_tennessee_input(
            PUBLIC_CONTAINER_URL,
            canonical_rendered_root_request(
                acquisition_phase_id=other_phase,
                acquisition_phase_started_at=PHASE_STARTED_AT,
            ),
        )

    assert replay_calls == []


def test_partial_browser_resume_rejects_stale_phase() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    stale_started_at = (
        datetime.now(UTC)
        - timedelta(seconds=TennesseeScraper.TN_PHASE_MAX_AGE_SECONDS + 1)
    ).isoformat()
    stale_request = canonical_rendered_root_request(
        acquisition_phase_id=PHASE_ID,
        acquisition_phase_started_at=stale_started_at,
    )
    scraper._state_law_acquisition_ledger = SimpleNamespace(
        entries=(
            SimpleNamespace(
                receipt=SimpleNamespace(sanitized_request=stale_request),
            ),
        ),
        retained_replay_only=False,
    )

    with pytest.raises(RuntimeError, match="phase is stale"):
        scraper._select_tennessee_acquisition_phase(allow_new=False)


class _FakeNavigationRequest:
    def __init__(self, url: str, redirected_from: Any = None) -> None:
        self.url = url
        self.redirected_from = redirected_from


class _FakeNavigation:
    status = 200

    def __init__(self, url: str) -> None:
        self.request = _FakeNavigationRequest(url)


class _FakePage:
    def __init__(self, *, root_html: str, patch_payload: Mapping[str, Any]) -> None:
        self.url = f"{PUBLIC_CONTAINER_URL}&crid={SESSION_ID}"
        self._root_html = root_html
        self._patch_payload = patch_payload

    async def goto(self, *_args: Any, **_kwargs: Any) -> _FakeNavigation:
        return _FakeNavigation(self.url)

    async def wait_for_selector(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def content(self) -> str:
        return self._root_html

    async def evaluate(self, _script: str, args: Mapping[str, Any]) -> Mapping[str, Any]:
        assert args["sessionRequestId"] == SESSION_ID
        return {
            "contentType": "application/json; charset=utf-8",
            "finalUrl": TOC_ENDPOINT_URL,
            "observedAt": datetime.now(UTC).isoformat(),
            "redirected": False,
            "status": 200,
            "text": json.dumps(self._patch_payload),
        }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("final_url", "redirected"),
    [
        (PUBLIC_CONTAINER_URL, False),
        (TOC_ENDPOINT_URL, True),
    ],
)
async def test_patch_wire_rejects_changed_final_url_or_redirect(
    final_url: str,
    redirected: bool,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        tennessee_lexis_live,
    )

    class _WirePage:
        async def evaluate(
            self,
            _script: str,
            _args: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            return {
                "contentType": "application/json",
                "finalUrl": final_url,
                "observedAt": datetime.now(UTC).isoformat(),
                "redirected": redirected,
                "status": 200,
                "text": "{}",
            }

    payload, proof, error = await tennessee_lexis_live._patch_with_retries(
        _WirePage(),
        endpoint=TOC_ENDPOINT_URL,
        request_body=b"{}",
        session_request_id=SESSION_ID,
        retry_count=1,
    )

    assert payload == b""
    assert proof == {}
    assert "final-URL/redirect proof" in error


@pytest.mark.anyio
async def test_patch_wire_uses_verifier_clock_not_page_javascript_clock() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        tennessee_lexis_live,
    )

    malicious_page_time = "1900-01-01T00:00:00+00:00"

    class _WirePage:
        async def evaluate(
            self,
            _script: str,
            _args: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            return {
                "contentType": "application/json",
                "finalUrl": TOC_ENDPOINT_URL,
                "observedAt": malicious_page_time,
                "redirected": False,
                "status": 200,
                "text": "{}",
            }

    before = datetime.now(UTC)
    payload, proof, error = await tennessee_lexis_live._patch_with_retries(
        _WirePage(),
        endpoint=TOC_ENDPOINT_URL,
        request_body=b"{}",
        session_request_id=SESSION_ID,
        retry_count=1,
    )
    after = datetime.now(UTC)

    observed = datetime.fromisoformat(str(proof["response_observed_at"]))
    assert payload == b"{}"
    assert error == ""
    assert proof["response_observed_at"] != malicious_page_time
    assert before <= observed <= after


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def new_context(self, **_kwargs: Any) -> Any:
        page = self._page
        return SimpleNamespace(new_page=lambda: None, _page=page)

    async def close(self) -> None:
        return None


class _FakeBrowserContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def new_page(self) -> _FakePage:
        return self._page


class _FakeChromium:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def launch(self, **_kwargs: Any) -> Any:
        page = self._page

        class Browser(_FakeBrowser):
            async def new_context(self, **_kwargs: Any) -> _FakeBrowserContext:
                return _FakeBrowserContext(page)

        return Browser(page)


class _FakePlaywrightManager:
    def __init__(self, page: _FakePage) -> None:
        self._playwright = SimpleNamespace(chromium=_FakeChromium(page))

    async def __aenter__(self) -> Any:
        return self._playwright

    async def __aexit__(self, *_args: Any) -> None:
        return None


@pytest.mark.anyio
@pytest.mark.parametrize("retained_root", [False, True])
async def test_live_browser_retains_missing_root_and_session_bound_patch(
    monkeypatch: pytest.MonkeyPatch,
    retained_root: bool,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        tennessee_lexis_live,
    )

    scraper = TennesseeScraper("TN", "Tennessee")
    compact_titles = (
        ("1", "Code and Statutes"),
        ("19", "[Reserved]"),
        ("51", "[Reserved]"),
    )
    scraper.OFFICIAL_TITLES = compact_titles
    root_html = _root_html(scraper)
    roots, _tables = parse_root_html(root_html, expected_titles=compact_titles)
    parent = next(node for node in roots if node.can_expand or node.has_children)
    subtree, _href = _subtree_payload(parent)
    page = _FakePage(root_html=root_html, patch_payload=subtree)
    monkeypatch.setattr(
        tennessee_lexis_live,
        "_playwright_manager",
        lambda: _FakePlaywrightManager(page),
    )
    retained_inputs: list[dict[str, Any]] = []

    def _replay(url: str, request: Mapping[str, Any]) -> Any:
        if retained_root and url == PUBLIC_CONTAINER_URL:
            return TennesseeRetainedBrowserInput(
                body=root_html.encode(),
                response_proof={
                    "final_url": PUBLIC_CONTAINER_URL,
                    "final_url_sha256": hashlib.sha256(
                        PUBLIC_CONTAINER_URL.encode()
                    ).hexdigest(),
                    "redirect_chain": [],
                    "redirected": False,
                    "response_observed_at": datetime.now(UTC).isoformat(),
                    "session_request_id_sha256": hashlib.sha256(
                        b"prior-session"
                    ).hexdigest(),
                },
            )
        return None

    inventory = await acquire_live_catalog(
        acquisition_phase_id=PHASE_ID,
        acquisition_phase_started_at=PHASE_STARTED_AT,
        expected_titles=compact_titles,
        expected_patch_count=1,
        retain_parser_input=lambda **kwargs: retained_inputs.append(dict(kwargs)),
        replay_parser_input=_replay,
    )

    assert inventory.network_patch_count == 1
    assert [item["sanitized_request"]["method"] for item in retained_inputs] == [
        "GET",
        "PATCH",
    ]
    patch_request = retained_inputs[1]["sanitized_request"]
    assert patch_request["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert patch_request["session_request_id_sha256"] == SESSION_SHA256
    assert SESSION_ID not in json.dumps(patch_request, sort_keys=True)
    assert retained_inputs[0]["observed_at"] != retained_inputs[1]["observed_at"]


@pytest.mark.anyio
async def test_live_ledger_route_derives_body_wave_then_uses_retained_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        tennessee_lexis_live,
    )

    scraper = TennesseeScraper("TN", "Tennessee")
    scraper.OFFICIAL_TITLES = (
        ("1", "Code and Statutes"),
        ("19", "[Reserved]"),
        ("51", "[Reserved]"),
    )
    scraper.ENFORCE_OBSERVED_TN_FRONTIER = False
    ledger = SimpleNamespace(
        retained_replay_only=False,
        refresh_count=0,
        retain_parser_input=lambda **_kwargs: None,
        replay_retained_parser_input=lambda **_kwargs: None,
    )

    def _refresh() -> None:
        ledger.refresh_count += 1

    ledger.refresh_existing_entries = _refresh
    scraper._state_law_acquisition_ledger = ledger
    root_payload = _root_html(scraper).encode()
    roots, tables = parse_root_html(
        root_payload.decode(),
        expected_titles=scraper.OFFICIAL_TITLES,
    )
    parent = next(node for node in roots if node.can_expand or node.has_children)
    subtree_payload, _href = _subtree_payload(parent)
    descendants, _closed, error = parse_title_subtree_payload(
        subtree_payload,
        parent=parent,
        target_level=max(parent.open_to_levels),
    )
    assert error == ""
    subtrees = {parent.node_id: tuple(descendants)}
    metadata = derive_exact_metadata_frontier(
        roots,
        subtrees_by_root_id=subtrees,
    )
    inventory = TennesseeLiveCatalog(
        title_roots=tuple(roots),
        tables_root=tables,
        subtrees_by_root_id=subtrees,
        metadata=metadata,
        observed_at="2026-08-29T00:00:00+00:00",
        network_patch_count=1,
        retained_patch_count=0,
    )
    catalog_calls: list[dict[str, Any]] = []

    async def _catalog(**kwargs: Any) -> TennesseeLiveCatalog:
        catalog_calls.append(dict(kwargs))
        return inventory

    body_urls = [document_url(node.link_href) for node in metadata["document_nodes"]]
    get_waves: list[tuple[str, list[str]]] = []

    async def _get_wave(
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Any,
        require_direct: bool = False,
    ) -> StateLawPageMultiFetchResult:
        assert require_direct is True
        requested = list(urls)
        get_waves.append((frontier_name, requested))
        if frontier_name == "General Assembly delegation":
            payloads = [
                b"<html><a href='https://www.lexisnexis.com/hottopics/tncode'>"
                b"Tennessee Code</a></html>"
            ]
        elif frontier_name == "publisher entry":
            payloads = [
                f"<html><a href='{PUBLIC_CONTAINER_URL}'>continue</a></html>".encode()
            ]
        else:
            assert frontier_name == "document body wave"
            assert requested == body_urls
            payloads = [b"<html><main data-document-content>body</main></html>"] * len(
                requested
            )
        assert all(content_validator(payload) for payload in payloads)
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=[{"source_transport": "direct"}] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={"network_requested_pages": len(requested)},
        )

    marker = [SimpleNamespace(section_number="1-1-1")]

    async def _retained(*, code_name: str) -> list[Any]:
        assert code_name == "Tennessee Code Annotated"
        return marker

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(tennessee_lexis_live, "acquire_live_catalog", _catalog)
    monkeypatch.setattr(scraper, "_fetch_tennessee_lexis_get_wave", _get_wave)
    monkeypatch.setattr(
        scraper,
        "_scrape_strict_tennessee_retained_frontier",
        _retained,
    )

    rows = await scraper.scrape_code(
        "Tennessee Code Annotated",
        scraper.AUTHORIZED_CODE_ENTRY_URL,
        max_statutes=None,
    )

    assert rows is marker
    assert [name for name, _urls in get_waves] == [
        "General Assembly delegation",
        "publisher entry",
        "document body wave",
    ]
    assert len(catalog_calls) == 1
    assert catalog_calls[0]["expected_patch_count"] == 1
    assert ledger.refresh_count == 1


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


class _FakeLedger:
    retained_replay_only = True

    def __init__(self) -> None:
        self._rows: dict[str, Any] = {}
        self.calls: list[list[tuple[str, dict[str, Any]]]] = []
        self.refresh_count = 0

    @property
    def entries(self) -> tuple[Any, ...]:
        return tuple(self._rows.values())

    @staticmethod
    def _key(url: str, request: dict[str, Any]) -> str:
        return json.dumps([url, request], sort_keys=True, separators=(",", ":"))

    def add(self, url: str, request: dict[str, Any], body: bytes) -> None:
        digest = hashlib.sha256(body).hexdigest()
        envelope = _Envelope(
            body=body,
            receipt_sha256=hashlib.sha256((url + digest).encode()).hexdigest(),
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
        return tuple(self._rows[self._key(url, request)] for url, request in normalized)


def test_retained_observed_at_comes_from_signed_acquisition_receipt() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    _bind_phase(scraper)
    url = scraper.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL
    body = b"<html>receipt-bound</html>"
    digest = hashlib.sha256(body).hexdigest()
    observed_at = "2026-08-29T03:04:05+00:00"
    retained = SimpleNamespace(
        envelope=_Envelope(
            body=body,
            receipt_sha256=hashlib.sha256((url + digest).encode()).hexdigest(),
            url=url,
        ),
        receipt=SimpleNamespace(
            pagination={
                "tennessee_acquisition_phase": {
                    "phase_id": PHASE_ID,
                    "schema_version": TennesseeScraper.TN_PHASE_SCHEMA,
                    "started_at": PHASE_STARTED_AT,
                }
            },
            retrieved_at=observed_at,
        ),
        transport_receipt={
            "content_sha256": digest,
            "official_url": url,
            "source_transport": "direct",
        },
    )
    scraper._tennessee_frontier_input_reports = []

    admitted = scraper._record_tennessee_retained_input(
        source_role="state_delegation",
        official_url=url,
        sanitized_request=scraper._tennessee_get_request(url),
        retained=retained,
    )

    assert admitted == body
    assert scraper._tennessee_frontier_input_reports[0]["observed_at"] == observed_at


def test_retained_current_get_role_rejects_archival_transport() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    _bind_phase(scraper)
    url = scraper.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL
    body = b"<html>archived authority</html>"
    digest = hashlib.sha256(body).hexdigest()
    retained = SimpleNamespace(
        envelope=_Envelope(
            body=body,
            receipt_sha256=hashlib.sha256((url + digest).encode()).hexdigest(),
            url=url,
        ),
        receipt=SimpleNamespace(
            pagination={
                "tennessee_acquisition_phase": {
                    "phase_id": PHASE_ID,
                    "schema_version": TennesseeScraper.TN_PHASE_SCHEMA,
                    "started_at": PHASE_STARTED_AT,
                }
            },
            retrieved_at=datetime.now(UTC).isoformat(),
        ),
        transport_receipt={
            "content_sha256": digest,
            "official_url": url,
            "source_transport": "wayback",
        },
    )
    scraper._tennessee_frontier_input_reports = []

    with pytest.raises(RuntimeError, match="inadmissible current-source transport"):
        scraper._record_tennessee_retained_input(
            source_role="state_delegation",
            official_url=url,
            sanitized_request=scraper._tennessee_get_request(url),
            retained=retained,
        )


def test_optional_browser_resume_rejects_nonbrowser_provenance_before_network() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    url = PUBLIC_CONTAINER_URL
    body = _root_html(scraper).encode()
    digest = hashlib.sha256(body).hexdigest()
    retained = SimpleNamespace(
        envelope=_Envelope(
            body=body,
            receipt_sha256=hashlib.sha256((url + digest).encode()).hexdigest(),
            url=url,
        ),
        receipt=SimpleNamespace(retrieved_at="2026-08-29T03:04:05+00:00"),
        transport_receipt={
            "content_sha256": digest,
            "official_url": url,
            "source_transport": "direct",
        },
    )
    scraper._state_law_acquisition_ledger = SimpleNamespace(
        retained_replay_only=False,
        replay_retained_parser_input=lambda **_kwargs: retained,
    )

    with pytest.raises(RuntimeError, match="invalid retained evidence"):
        scraper._replay_optional_tennessee_input(
            url,
            canonical_rendered_root_request(),
        )


@pytest.mark.anyio
async def test_strict_route_is_five_ordered_ledger_only_waves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    _bind_phase(scraper)
    scraper.ENFORCE_OBSERVED_TN_FRONTIER = False
    ledger = _FakeLedger()
    scraper._state_law_acquisition_ledger = ledger
    get_request = scraper._tennessee_get_request

    authority_body = (
        b"<html><a href='https://www.lexisnexis.com/hottopics/tncode'>"
        b"Tennessee Code</a></html>"
    )
    publisher_body = (
        f"<html><a href='{PUBLIC_CONTAINER_URL}'>continue</a></html>"
    ).encode()
    root_body = _root_html(scraper).encode()
    ledger.add(
        scraper.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL,
        get_request(scraper.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL),
        authority_body,
    )
    ledger.add(
        scraper.AUTHORIZED_CODE_ENTRY_URL,
        get_request(scraper.AUTHORIZED_CODE_ENTRY_URL),
        publisher_body,
    )
    ledger.add(
        scraper.AUTHORIZED_CODE_CONTAINER_URL,
        _root_request(),
        root_body,
    )

    roots, _tables = parse_root_html(
        root_body.decode(),
        expected_titles=scraper.OFFICIAL_TITLES,
    )
    document_nodes: list[TennesseeLexisNode] = []
    for parent in roots:
        if parent.is_document_locator:
            document_nodes.append(parent)
            continue
        payload, href = _subtree_payload(parent)
        endpoint, _body, request = canonical_live_toc_patch_request(
            parent,
            acquisition_phase_id=PHASE_ID,
            acquisition_phase_started_at=PHASE_STARTED_AT,
            session_request_id_sha256=SESSION_SHA256,
        )
        ledger.add(endpoint, request, json.dumps(payload).encode())
        document_nodes.append(
            _document_node(
                node_id=f"D{int(parent.title_number or 0):03d}",
                token=href.rsplit(":", 1)[-1],
                title=f"{parent.title_number}-1-1. Test provision",
            )
        )

    for node in document_nodes:
        url = document_url(node.link_href)
        if node.title_number in {"19", "51"}:
            body = b"<html><main data-document-content><p>[Reserved]</p></main></html>"
        else:
            body = (
                "<html><main data-document-content>"
                f"<h1>{node.section_number}. Test provision</h1>"
                "<p>This retained official provision contains operative text.</p>"
                "</main></html>"
            ).encode()
        ledger.add(url, get_request(url), body)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    rows = await scraper.scrape_code(
        "Tennessee Code Annotated",
        scraper.AUTHORIZED_CODE_ENTRY_URL,
        max_statutes=None,
    )

    assert len(rows) == 69
    assert [len(call) for call in ledger.calls] == [1, 1, 69, 71]
    assert all(call for call in ledger.calls)
    assert all(
        request["method"] == "PATCH"
        for _url, request in ledger.calls[2]
    )
    assert all(request["method"] == "GET" for _url, request in ledger.calls[3])
    report = scraper.last_tennessee_full_corpus_report
    assert report["closed"] is True
    assert report["retained_replay_only"] is True
    assert report["network_requested_pages"] == 0
    assert report["source_input_count"] == 143
    assert report["body_input_count"] == 71
    assert report["terminal_document_count"] == 2
    assert len(report["source_request_order_digest_sha256"]) == 64
    assert len(report["source_parser_body_order_digest_sha256"]) == 64
    assert len(report["row_binding_digest_sha256"]) == 64
    assert len(report["terminal_binding_digest_sha256"]) == 64
    assert all(
        len(row.structured_data["source_content_sha256"]) == 64 for row in rows
    )
    assert report["disposition"] == {
        "discovered": 71,
        "duplicates": 0,
        "excluded": 2,
        "failed_final": 0,
        "fetched": 69,
        "quarantined": 0,
    }

    captured: dict[str, Any] = {}

    def _retain(_scraper: Any, **kwargs: Any) -> Path:
        captured.update(kwargs)
        return Path("/tmp/tennessee-test-closure.json")

    monkeypatch.setattr(
        strict_frontier_closure,
        "retain_exact_state_frontier_closure",
        _retain,
    )
    first_wave_count = len(ledger.calls)
    closure_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection={"canonical_keys": []}
    )

    assert closure_path == Path("/tmp/tennessee-test-closure.json")
    assert [len(call) for call in ledger.calls[first_wave_count:]] == [
        1,
        1,
        69,
        71,
    ]
    assert captured["first_frontier"] == captured["replayed_frontier"]
    assert len(captured["replay_rows"]) == 69
    assert captured["transport"]["retained_replay_network_requests"] == 0
    assert captured["transport"]["per_page_archive_loop"] is False


@pytest.mark.anyio
async def test_full_route_without_retained_only_ledger_remains_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    with pytest.raises(RuntimeError, match="retained-replay-only ledger"):
        await scraper.scrape_code(
            "Tennessee Code Annotated",
            scraper.AUTHORIZED_CODE_ENTRY_URL,
            max_statutes=None,
        )


def test_current_diagnostic_residuals_are_explicitly_nonauthorizing() -> None:
    assert OBSERVED_STRICT_REUSABLE_INPUT_COUNT == 0
    assert OBSERVED_AUTHORITY_CATALOG_RESIDUAL_COUNT == 72
    assert OBSERVED_BODY_RESIDUAL_COUNT == OBSERVED_DOCUMENT_COUNT == 36_046
    assert OBSERVED_TOTAL_RESIDUAL_COUNT == 36_118
    assert 72 + 36_046 == 36_118
    assert {
        OBSERVED_ROOT_MEMBERSHIP_SHA256,
        OBSERVED_ALL_NODE_MEMBERSHIP_SHA256,
        OBSERVED_DOCUMENT_MEMBERSHIP_SHA256,
        OBSERVED_ORDERED_CONTENT_PATH_SHA256,
        OBSERVED_SUBTREE_MANIFEST_SHA256,
    } == {
        "88135a531583ec0784f72ab7ec436e282f61da93df58e0c86b98f65983620566",
        "ea80e34aff88bc2d289494ff1ab67c2d53193d1b5f086000510b7cafa31d8826",
        "8bfc62cda73e7529b30f5848d7cb9128c341d6c0f8910c6ed08dc0beb58d7286",
        "af6b3962a8eedc12d5f76d98608deee37c8398b30236829b504986c42234599b",
        "29570e7e953a0b80ba32a9245c94b05cbb0076e1c4283eb59e88853b90ccd40a",
    }
    assert observed_metadata_drift({"document_count": 71})


def test_producer_identity_binds_tennessee_and_shared_dependencies() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    dependencies = scraper.state_law_frontier_source_dependencies()
    labels = {getattr(item, "__name__", "") for item in dependencies}

    assert any(label.endswith(".tennessee_lexis") for label in labels)
    assert any(label.endswith(".tennessee_lexis_live") for label in labels)
    assert any(label.endswith(".tennessee_section") for label in labels)
    assert any(label.endswith(".strict_frontier_closure") for label in labels)
    assert any(label.endswith(".state_archival_fetch") for label in labels)
    producer = scraper._state_law_frontier_source_software_version()
    assert producer.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee."
        "TennesseeScraper@sha256:"
    )
    assert len(producer.rsplit(":", 1)[-1]) == 64

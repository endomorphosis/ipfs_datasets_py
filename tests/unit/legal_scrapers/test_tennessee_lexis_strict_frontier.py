from __future__ import annotations

import hashlib
import json
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
    contract = grouped_get_acquisition_contract(urls)
    assert contract["common_crawl_inventory_query_upper_bound"] == 1
    assert contract["group_warc_ranges_by_warc_filename"] is True
    assert contract["coalesce_compatible_warc_ranges"] is True
    assert contract["retry_residual_urls_only"] is True
    assert contract["per_page_archive_inventory_loop"] is False


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
        self._rows[self._key(url, request)] = SimpleNamespace(
            envelope=envelope,
            receipt=SimpleNamespace(content=SimpleNamespace(sha256=digest)),
            transport_receipt={
                "content_sha256": digest,
                "official_url": url,
                "retrieved_at": "2026-08-26T00:00:00+00:00",
                "source_transport": "retained_test_transport",
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


@pytest.mark.anyio
async def test_strict_route_is_five_ordered_ledger_only_waves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
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
        get_request(scraper.AUTHORIZED_CODE_CONTAINER_URL),
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
        endpoint, _body, request = canonical_toc_patch_request(parent)
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
    assert [len(call) for call in ledger.calls] == [1, 1, 1, 69, 71]
    assert all(call for call in ledger.calls)
    assert all(
        request["method"] == "PATCH"
        for _url, request in ledger.calls[3]
    )
    assert all(request["method"] == "GET" for _url, request in ledger.calls[4])
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
    assert any(label.endswith(".tennessee_section") for label in labels)
    assert any(label.endswith(".strict_frontier_closure") for label in labels)
    assert any(label.endswith(".state_archival_fetch") for label in labels)
    producer = scraper._state_law_frontier_source_software_version()
    assert producer.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee."
        "TennesseeScraper@sha256:"
    )
    assert len(producer.rsplit(":", 1)[-1]) == 64

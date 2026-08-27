"""Source-bound Arkansas H.R. 5330 resolution and delegated-page batching."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import arkansas_lexis
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
    ArkansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas_lexis import (
    ACT1032_URL,
    CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    HR5330_BILLSTATUS_URL,
    HR5330_IF_LINK_HREF,
    HR5330_IF_NODE_ID,
    HR5330_IF_TITLE,
    HR5330_UNTIL_LINK_HREF,
    HR5330_UNTIL_NODE_ID,
    HR5330_UNTIL_TITLE,
    HR5330_VARIANT_SECTION,
    PUBLIC_CONTAINER_URL,
    UNRESOLVED_VARIANT_DOCUMENT_CONTRACT,
    ArkansasLexisNode,
    _bind_live_nodes,
    document_page_url,
    exact_unresolved_variant_document_nodes,
    reconcile_current_statute_variants,
    resolve_hr5330_source_bound_variant,
    validate_hr5330_billstatus_xml,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)

OBSERVED_AT = "2026-08-25T04:32:58.722528+00:00"
TOC_RECEIPT_SHA256 = "4" * 64
ACT1032_FIXTURE_PDF = (
    b"%PDF-1.7\nExact synthetic Act 1032 fixture for retained-input tests.\n%%EOF\n"
)


def _billstatus_xml(*, latest_text: str | None = None, enacted: bool = False) -> bytes:
    law = (
        "<laws><item><type>Public Law</type><number>116-999</number></item></laws>"
        if enacted
        else ""
    )
    action_text = latest_text or arkansas_lexis.HR5330_LATEST_ACTION_TEXT
    return (
        '<?xml version="1.0" encoding="utf-8" standalone="no"?>'
        "<billStatus><version>3.0.0</version><bill>"
        "<number>5330</number>"
        f"<updateDate>{arkansas_lexis.HR5330_STATUS_UPDATE}</updateDate>"
        "<originChamber>House</originChamber><type>HR</type>"
        "<introducedDate>2019-12-05</introducedDate><congress>116</congress>"
        "<actions><item><actionDate>2020-12-15</actionDate>"
        f"<text>{action_text}</text><type>Calendars</type>"
        "<calendarNumber><calendar>U00537</calendar></calendarNumber>"
        "</item><item><actionDate>2019-12-05</actionDate>"
        "<text>Introduced in House</text></item></actions>"
        f"{law}<latestAction><actionDate>2020-12-15</actionDate>"
        f"<text>{action_text}</text></latestAction>"
        "</bill></billStatus>"
    ).encode()


def _pin_fixture(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    monkeypatch.setattr(
        arkansas_lexis,
        "HR5330_BILLSTATUS_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(
        arkansas_lexis,
        "HR5330_BILLSTATUS_BYTE_SIZE",
        len(payload),
    )
    monkeypatch.setattr(
        arkansas_lexis,
        "ACT1032_SHA256",
        hashlib.sha256(ACT1032_FIXTURE_PDF).hexdigest(),
    )
    monkeypatch.setattr(
        arkansas_lexis,
        "ACT1032_BYTE_SIZE",
        len(ACT1032_FIXTURE_PDF),
    )


def _bound_node(
    *,
    node_id: str,
    section_number: str,
    title: str,
    link_href: str,
) -> ArkansasLexisNode:
    raw = ArkansasLexisNode(
        node_id=node_id,
        title=title,
        level=5,
        node_path=f"/ROOT/A/{node_id}",
        can_expand=False,
        can_open=True,
        has_children=False,
        link_href=link_href,
        subscribed=True,
        purchase_required=False,
        list_price=0.0,
        net_price=0.0,
        pricing_present=True,
        currency_code="USD",
        usage_type_code="subscription",
        document_status="Available",
    )
    assert raw.section_number == section_number
    bound = _bind_live_nodes(
        [raw],
        source_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        receipt_sha256=TOC_RECEIPT_SHA256,
    )
    assert len(bound) == 1 and bound[0].evidence_verified
    return bound[0]


def _hr5330_nodes() -> tuple[ArkansasLexisNode, ArkansasLexisNode]:
    return (
        _bound_node(
            node_id=HR5330_UNTIL_NODE_ID,
            section_number=HR5330_VARIANT_SECTION,
            title=HR5330_UNTIL_TITLE,
            link_href=HR5330_UNTIL_LINK_HREF,
        ),
        _bound_node(
            node_id=HR5330_IF_NODE_ID,
            section_number=HR5330_VARIANT_SECTION,
            title=HR5330_IF_TITLE,
            link_href=HR5330_IF_LINK_HREF,
        ),
    )


def _retain_billstatus(
    tmp_path,
    payload: bytes,
) -> tuple[StateLawMultiFetchAcquisitionLedger, object, object]:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="AR",
        parser_name=CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    )
    act_digest = hashlib.sha256(ACT1032_FIXTURE_PDF).hexdigest()
    act_retained = ledger.retain_parser_input(
        official_url=ACT1032_URL,
        body=ACT1032_FIXTURE_PDF,
        transport_receipt={
            "official_url": ACT1032_URL,
            "content_sha256": act_digest,
            "source_transport": "direct",
        },
        retrieved_at=datetime(2026, 8, 25, tzinfo=UTC),
        response_status=200,
        media_type="application/pdf",
        sanitized_request={"method": "GET", "url": ACT1032_URL},
        network_used=True,
    )
    digest = hashlib.sha256(payload).hexdigest()
    retained = ledger.retain_parser_input(
        official_url=HR5330_BILLSTATUS_URL,
        body=payload,
        transport_receipt={
            "official_url": HR5330_BILLSTATUS_URL,
            "content_sha256": digest,
            "source_transport": "direct",
        },
        retrieved_at=datetime(2026, 8, 25, tzinfo=UTC),
        response_status=200,
        media_type="application/xml",
        sanitized_request={"method": "GET", "url": HR5330_BILLSTATUS_URL},
        network_used=True,
    )
    return ledger, retained, act_retained


def test_production_govinfo_identity_is_exactly_pinned() -> None:
    assert HR5330_BILLSTATUS_URL == (
        "https://www.govinfo.gov/bulkdata/BILLSTATUS/116/hr/"
        "BILLSTATUS-116hr5330.xml"
    )
    assert arkansas_lexis.HR5330_BILLSTATUS_BYTE_SIZE == 12_630
    assert arkansas_lexis.HR5330_BILLSTATUS_SHA256 == (
        "ff17b359294dd8923472fa3a6fea1f5640776e4b715b6bfc075dce3b2779d122"
    )
    assert arkansas_lexis.ACT1032_SHA256 == (
        "59534f794b626bf9d162fec606eb343c9c5f922a3340a34efd1d2ddfbbfae019"
    )
    assert arkansas_lexis.ACT1032_BYTE_SIZE == 308_537


def test_hr5330_xml_contract_accepts_pinned_no_enactment_and_rejects_drift(
    monkeypatch,
) -> None:
    payload = _billstatus_xml()
    _pin_fixture(monkeypatch, payload)

    semantics = validate_hr5330_billstatus_xml(payload)

    assert semantics["latest_action_date"] == "2020-12-15"
    assert semantics["latest_action_text"].startswith("Placed on the Union Calendar")
    assert semantics["law_node_count"] == 0
    assert semantics["congress_end_date"] == "2021-01-03"
    assert semantics["trigger_deadline"] == "2026-01-01"

    with pytest.raises(ValueError, match="SHA-256 drifted"):
        validate_hr5330_billstatus_xml(payload[:-1] + b" ")

    action_drift = _billstatus_xml(latest_text="Passed House.")
    _pin_fixture(monkeypatch, action_drift)
    with pytest.raises(ValueError, match="latest-action text drifted"):
        validate_hr5330_billstatus_xml(action_drift)

    enacted = _billstatus_xml(enacted=True)
    _pin_fixture(monkeypatch, enacted)
    with pytest.raises(ValueError, match="records enactment"):
        validate_hr5330_billstatus_xml(enacted)


def test_source_bound_resolution_requires_exact_nodes_and_retained_input(
    tmp_path,
    monkeypatch,
) -> None:
    payload = _billstatus_xml()
    _pin_fixture(monkeypatch, payload)
    _ledger, retained, act_retained = _retain_billstatus(tmp_path, payload)
    nodes = _hr5330_nodes()

    resolution = resolve_hr5330_source_bound_variant(
        nodes,
        billstatus_xml=payload,
        source_url=HR5330_BILLSTATUS_URL,
        transport_receipt=retained.transport_receipt,
        parser_input_envelope=retained.envelope,
        trigger_act_retained_input=act_retained,
    )
    decisions = reconcile_current_statute_variants(
        nodes,
        observed_at=OBSERVED_AT,
        source_bound_resolutions=(resolution,),
    )

    assert resolution.evidence_verified is True
    assert resolution.selected_node_id == HR5330_UNTIL_NODE_ID
    assert resolution.parser_input_receipt_sha256 == (
        retained.receipt.receipt_sha256
    )
    assert len(decisions) == 1
    assert decisions[0].disposition == "selected_current_locator"
    assert decisions[0].selected_node_id == HR5330_UNTIL_NODE_ID
    assert "not_enacted_before_trigger_deadline" in decisions[0].reason

    with pytest.raises(ValueError, match="requires two verified"):
        resolve_hr5330_source_bound_variant(
            nodes[:1],
            billstatus_xml=payload,
            source_url=HR5330_BILLSTATUS_URL,
            transport_receipt=retained.transport_receipt,
            parser_input_envelope=retained.envelope,
            trigger_act_retained_input=act_retained,
        )

    with pytest.raises(ValueError, match="Act 1032 retained PDF bytes drifted"):
        resolve_hr5330_source_bound_variant(
            nodes,
            billstatus_xml=payload,
            source_url=HR5330_BILLSTATUS_URL,
            transport_receipt=retained.transport_receipt,
            parser_input_envelope=retained.envelope,
            trigger_act_retained_input=retained,
        )

    wrong_request_ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "wrong-request",
        jurisdiction="AR",
        parser_name=CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    )
    wrong_request = wrong_request_ledger.retain_parser_input(
        official_url=HR5330_BILLSTATUS_URL,
        body=payload,
        transport_receipt=retained.transport_receipt,
        response_status=200,
        sanitized_request={
            "method": "GET",
            "url": HR5330_BILLSTATUS_URL,
            "headers": {"accept": "application/xml"},
        },
    )
    with pytest.raises(ValueError, match="request identity drifted"):
        resolve_hr5330_source_bound_variant(
            nodes,
            billstatus_xml=payload,
            source_url=HR5330_BILLSTATUS_URL,
            transport_receipt=wrong_request.transport_receipt,
            parser_input_envelope=wrong_request.envelope,
            trigger_act_retained_input=act_retained,
        )


def test_async_hr5330_resolver_replays_ledger_without_network(
    tmp_path,
    monkeypatch,
) -> None:
    payload = _billstatus_xml()
    _pin_fixture(monkeypatch, payload)
    ledger, retained, act_retained = _retain_billstatus(tmp_path, payload)
    scraper = ArkansasScraper("AR", "Arkansas")
    scraper.attach_state_law_acquisition_ledger(ledger)

    async def _network_forbidden(*_args, **_kwargs):
        raise AssertionError("retained GovInfo input must replay without network")

    monkeypatch.setattr(
        scraper,
        "_search_state_common_crawl_records",
        _network_forbidden,
    )
    resolution, diagnostic = asyncio.run(
        scraper._resolve_hr5330_current_variant(nodes=_hr5330_nodes())
    )

    assert resolution is not None and resolution.evidence_verified
    assert diagnostic["disposition"] == "selected_current_locator"
    assert diagnostic["transport_batch"]["network_requested_pages"] == 0
    assert diagnostic["retained_body_path"] == str(retained.body_path)
    assert diagnostic["retained_evidence_path"] == str(retained.evidence_path)
    assert diagnostic["trigger_act_retained_body_path"] == str(
        act_retained.body_path
    )


def _all_unresolved_nodes() -> tuple[ArkansasLexisNode, ...]:
    nodes = []
    for section_number, node_id, link_href in UNRESOLVED_VARIANT_DOCUMENT_CONTRACT:
        if node_id == HR5330_UNTIL_NODE_ID:
            title = HR5330_UNTIL_TITLE
        elif node_id == HR5330_IF_NODE_ID:
            title = HR5330_IF_TITLE
        else:
            title = (
                f"{section_number}. Exact delegated statute text locator "
                f"{node_id}."
            )
        nodes.append(
            _bound_node(
                node_id=node_id,
                section_number=section_number,
                title=title,
                link_href=link_href,
            )
        )
    return tuple(nodes)


def _body_html(section_number: str) -> bytes:
    return (
        "<!doctype html><html><body><div id='document-content'>"
        f"<h1>{section_number}. Exact delegated statute.</h1>"
        "<p>This is the exact enacted statutory body retained for citation "
        f"{section_number}, with enough substantive words for validation.</p>"
        "</div></body></html>"
    ).encode()


def test_exact_sixteen_delegated_urls_use_one_shared_prefix_batch(monkeypatch) -> None:
    nodes = _all_unresolved_nodes()
    assert len(exact_unresolved_variant_document_nodes(nodes)) == 16
    observed: dict[str, object] = {}
    scraper = ArkansasScraper("AR", "Arkansas")

    async def _batch(urls, **kwargs):
        observed["urls"] = list(urls)
        observed["kwargs"] = kwargs
        payloads = [_body_html(str(node.section_number)) for node in nodes]
        assert all(kwargs["content_validator"](payload) for payload in payloads)
        receipts = [
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "source_transport": "direct",
            }
            for url, payload in zip(urls, payloads, strict=True)
        ]
        return StateLawPageMultiFetchResult(
            urls=list(urls),
            payloads=payloads,
            errors=[None] * len(urls),
            transport_receipts=receipts,
            parser_input_envelopes=[None] * len(urls),
            stats={
                "common_crawl_inventory_queries": 1,
                "common_crawl": {
                    "warc_objects": 1,
                    "range_fetch_calls": 2,
                    "naive_range_fetches": 16,
                    "range_fetches_avoided": 14,
                },
            },
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _batch,
    )
    rows, diagnostics, stats = asyncio.run(
        scraper._fetch_exact_unresolved_delegated_lexis_variants(
            code_name="Arkansas Code",
            nodes=nodes,
        )
    )

    assert len(observed["urls"]) == 16
    assert all(
        document_page_url(node) == url
        for node, url in zip(nodes, observed["urls"], strict=True)
    )
    kwargs = observed["kwargs"]
    assert kwargs["common_crawl_domain_terms"] == ("advance.lexis.com",)
    assert kwargs["common_crawl_url_terms"] == ("/documentpage/",)
    assert kwargs["prefer_direct"] is True
    assert kwargs["wayback_prefix_inventory"] is True
    assert kwargs["residual_retry_attempts"] == 1
    assert kwargs["repeat_grouped_archive_inventory_on_residual"] is False
    assert all(row is not None for row in rows)
    assert [row.section_number for row in rows if row is not None] == [
        node.section_number for node in nodes
    ]
    assert all(item["disposition"] == "verified_body_probe" for item in diagnostics)
    assert stats["common_crawl_inventory_queries"] == 1
    assert stats["common_crawl"]["range_fetches_avoided"] == 14


def test_delegated_batch_rejects_per_row_citation_drift_and_missing_locator(
    monkeypatch,
) -> None:
    nodes = _all_unresolved_nodes()
    scraper = ArkansasScraper("AR", "Arkansas")

    async def _batch(urls, **_kwargs):
        payloads = [_body_html(str(node.section_number)) for node in nodes]
        payloads[0] = _body_html(str(nodes[2].section_number))
        receipts = [
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "source_transport": "direct",
            }
            for url, payload in zip(urls, payloads, strict=True)
        ]
        return StateLawPageMultiFetchResult(
            urls=list(urls),
            payloads=payloads,
            errors=[None] * len(urls),
            transport_receipts=receipts,
            parser_input_envelopes=[None] * len(urls),
            stats={"common_crawl_inventory_queries": 1},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _batch,
    )
    rows, diagnostics, _stats = asyncio.run(
        scraper._fetch_exact_unresolved_delegated_lexis_variants(
            code_name="Arkansas Code",
            nodes=nodes,
        )
    )

    assert rows[0] is None
    assert "exact delegated body rejected" in diagnostics[0]["error"]
    assert all(row is not None for row in rows[1:])

    with pytest.raises(ValueError, match="is missing"):
        asyncio.run(
            scraper._fetch_exact_unresolved_delegated_lexis_variants(
                code_name="Arkansas Code",
                nodes=nodes[:-1],
            )
        )

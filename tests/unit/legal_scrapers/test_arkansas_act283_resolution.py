"""Exact source-bound Arkansas Act 283 current-variant resolution."""

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
    ACT283_CRC_NONOCCURRENCE_URL,
    ACT283_DWS_CURRENT_FORM_URL,
    ACT283_EXCLUSION_DISPOSITION,
    ACT283_URL,
    ACT283_VARIANT_CONTRACT,
    CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    PUBLIC_CONTAINER_URL,
    UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT,
    ArkansasLexisNode,
    _bind_live_nodes,
    act283_selection_plan_sha256,
    document_page_url,
    exact_unresolved_variant_identity_document_nodes,
    reconcile_current_statute_variants,
    resolve_act283_source_bound_variants,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)

OBSERVED_AT = "2026-08-25T04:32:58.722528+00:00"
TOC_RECEIPT_SHA256 = "7" * 64
CURRENT_RETRIEVAL = datetime(2026, 8, 25, 9, tzinfo=UTC)
ACT283_FIXTURE = b"%PDF-1.7\nExact synthetic Arkansas Act 283.\n%%EOF\n"
CRC_FIXTURE = b"%PDF-1.7\nExact synthetic CRC nonoccurrence record.\n%%EOF\n"
DWS_FIXTURE = b"%PDF-1.7\nExact synthetic current DWS withholding form.\n%%EOF\n"


def _pin_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    for prefix, payload in (
        ("ACT283", ACT283_FIXTURE),
        ("ACT283_CRC_NONOCCURRENCE", CRC_FIXTURE),
        ("ACT283_DWS_CURRENT_FORM", DWS_FIXTURE),
    ):
        monkeypatch.setattr(
            arkansas_lexis,
            f"{prefix}_SHA256",
            hashlib.sha256(payload).hexdigest(),
        )
        monkeypatch.setattr(
            arkansas_lexis,
            f"{prefix}_BYTE_SIZE",
            len(payload),
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
        (raw,),
        source_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        receipt_sha256=TOC_RECEIPT_SHA256,
    )
    assert len(bound) == 1 and bound[0].evidence_verified
    return bound[0]


def _act283_nodes() -> tuple[ArkansasLexisNode, ...]:
    nodes: list[ArkansasLexisNode] = []
    for (
        section_number,
        until_node_id,
        until_link_href,
        until_title,
        if_node_id,
        if_link_href,
        if_title,
    ) in ACT283_VARIANT_CONTRACT:
        nodes.extend(
            (
                _bound_node(
                    node_id=until_node_id,
                    section_number=section_number,
                    title=until_title,
                    link_href=until_link_href,
                ),
                _bound_node(
                    node_id=if_node_id,
                    section_number=section_number,
                    title=if_title,
                    link_href=if_link_href,
                ),
            )
        )
    return tuple(nodes)


def _retain(
    ledger: StateLawMultiFetchAcquisitionLedger,
    *,
    url: str,
    payload: bytes,
    retrieved_at: datetime = CURRENT_RETRIEVAL,
    sanitized_request: dict[str, object] | None = None,
):
    digest = hashlib.sha256(payload).hexdigest()
    return ledger.retain_parser_input(
        official_url=url,
        body=payload,
        transport_receipt={
            "official_url": url,
            "content_sha256": digest,
            "source_transport": "direct",
        },
        retrieved_at=retrieved_at,
        response_status=200,
        media_type="application/pdf",
        sanitized_request=(
            sanitized_request
            if sanitized_request is not None
            else {"method": "GET", "url": url}
        ),
        network_used=True,
    )


def _retained_inputs(tmp_path, *, dws_retrieved_at: datetime = CURRENT_RETRIEVAL):
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="AR",
        parser_name=CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    )
    return (
        ledger,
        _retain(ledger, url=ACT283_URL, payload=ACT283_FIXTURE),
        _retain(
            ledger,
            url=ACT283_CRC_NONOCCURRENCE_URL,
            payload=CRC_FIXTURE,
        ),
        _retain(
            ledger,
            url=ACT283_DWS_CURRENT_FORM_URL,
            payload=DWS_FIXTURE,
            retrieved_at=dws_retrieved_at,
        ),
    )


def test_production_act283_official_input_and_locator_identities_are_pinned() -> None:
    assert arkansas_lexis.ACT283_SHA256 == (
        "3df754fb7c243c620289f2f05a0381a11f2e787a94b6e1998746ee870320b5a0"
    )
    assert arkansas_lexis.ACT283_BYTE_SIZE == 245_707
    assert arkansas_lexis.ACT283_CRC_NONOCCURRENCE_SHA256 == (
        "09fb6ff50d24402023c3446823629d6830864997fb87bc30ae3348ecb31473b1"
    )
    assert arkansas_lexis.ACT283_CRC_NONOCCURRENCE_BYTE_SIZE == 150_593
    assert arkansas_lexis.ACT283_DWS_CURRENT_FORM_SHA256 == (
        "00eca78717a0ce162e2d2d778348c2a25fc2f19c6e5da7c84e769ae349d5a40a"
    )
    assert arkansas_lexis.ACT283_DWS_CURRENT_FORM_BYTE_SIZE == 141_982
    assert arkansas_lexis.ACT283_CRC_NONOCCURRENCE_STATEMENT == (
        "According to the Division of Workforce Services, this contingency has "
        "not been met."
    )
    assert arkansas_lexis.ACT283_DWS_CURRENT_FORM_STATEMENT == (
        "The Arkansas Division of Workforce Services can make a deduction for "
        "federal income tax only."
    )
    assert [item[0] for item in ACT283_VARIANT_CONTRACT] == [
        "11-10-803",
        "26-51-905",
    ]
    assert [item[1] for item in ACT283_VARIANT_CONTRACT] == [
        "AALAAKAAJAAE",
        "ABAAAFAACAAKAAG",
    ]
    assert [item[4] for item in ACT283_VARIANT_CONTRACT] == [
        "AALAAKAAJAAF",
        "ABAAAFAACAAKAAH",
    ]
    assert act283_selection_plan_sha256() == (
        "ad29f34cc60ba5b095f46ca7bbffb3164a89ba39b05ec67d017c315bdfb03938"
    )


def test_act283_resolution_selects_both_until_nodes_and_preserves_if_nodes(
    tmp_path,
    monkeypatch,
) -> None:
    _pin_fixture(monkeypatch)
    _ledger, act, crc, dws = _retained_inputs(tmp_path)
    nodes = _act283_nodes()

    resolutions = resolve_act283_source_bound_variants(
        nodes,
        trigger_act_retained_input=act,
        crc_nonoccurrence_retained_input=crc,
        current_dws_form_retained_input=dws,
    )
    decisions = reconcile_current_statute_variants(
        nodes,
        observed_at=OBSERVED_AT,
        source_bound_resolutions=resolutions,
    )

    assert len(resolutions) == len(decisions) == 2
    assert all(item.evidence_verified for item in resolutions)
    assert [item.selected_node_id for item in resolutions] == [
        "AALAAKAAJAAE",
        "ABAAAFAACAAKAAG",
    ]
    assert [item.excluded_node_id for item in resolutions] == [
        "AALAAKAAJAAF",
        "ABAAAFAACAAKAAH",
    ]
    assert all(
        item.excluded_disposition == ACT283_EXCLUSION_DISPOSITION
        for item in resolutions
    )
    assert all(
        item.to_dict()["preserved_exclusions"][0]["disposition"]
        == "future_contingent_not_yet_effective"
        for item in resolutions
    )
    assert all(item.disposition == "selected_current_locator" for item in decisions)
    assert all("act283_contingency_not_met" in item.reason for item in decisions)


def test_async_act283_resolution_is_exact_retained_plural_replay(
    tmp_path,
    monkeypatch,
) -> None:
    _pin_fixture(monkeypatch)
    ledger, _act, _crc, _dws = _retained_inputs(tmp_path)
    scraper = ArkansasScraper("AR", "Arkansas")
    scraper.attach_state_law_acquisition_ledger(ledger)

    async def _network_forbidden(*_args, **_kwargs):
        raise AssertionError("Act 283 proof must use retained plural replay")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _network_forbidden,
    )
    resolutions, diagnostic = asyncio.run(
        scraper._resolve_act283_current_variants(nodes=_act283_nodes())
    )

    assert len(resolutions) == 2
    assert diagnostic["disposition"] == "selected_current_locators"
    assert [item["selected_node_id"] for item in diagnostic["resolutions"]] == [
        "AALAAKAAJAAE",
        "ABAAAFAACAAKAAG",
    ]
    assert len(diagnostic["retained_body_paths"]) == 3
    assert len(diagnostic["retained_evidence_paths"]) == 3

    missing_ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "missing",
        jurisdiction="AR",
        parser_name=CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    )
    _retain(missing_ledger, url=ACT283_URL, payload=ACT283_FIXTURE)
    scraper.attach_state_law_acquisition_ledger(missing_ledger)
    missing, missing_diagnostic = asyncio.run(
        scraper._resolve_act283_current_variants(nodes=_act283_nodes())
    )
    assert missing == ()
    assert "retained replay failed" in missing_diagnostic["error"]


@pytest.mark.parametrize(
    ("argument", "replacement", "message"),
    (
        (
            "trigger_act_retained_input",
            "crc",
            "Arkansas Act 283 retained PDF bytes drifted",
        ),
        (
            "crc_nonoccurrence_retained_input",
            "dws",
            "CRC Act 283 nonoccurrence record retained PDF bytes drifted",
        ),
        (
            "current_dws_form_retained_input",
            "crc",
            "DWS current withholding form retained PDF bytes drifted",
        ),
    ),
)
def test_act283_resolution_rejects_each_changed_official_input(
    tmp_path,
    monkeypatch,
    argument: str,
    replacement: str,
    message: str,
) -> None:
    _pin_fixture(monkeypatch)
    _ledger, act, crc, dws = _retained_inputs(tmp_path)
    inputs = {
        "trigger_act_retained_input": act,
        "crc_nonoccurrence_retained_input": crc,
        "current_dws_form_retained_input": dws,
    }
    inputs[argument] = {"act": act, "crc": crc, "dws": dws}[replacement]

    with pytest.raises(ValueError, match=message):
        resolve_act283_source_bound_variants(_act283_nodes(), **inputs)


def test_act283_resolution_rejects_missing_changed_request_and_stale_form(
    tmp_path,
    monkeypatch,
) -> None:
    _pin_fixture(monkeypatch)
    ledger, act, crc, dws = _retained_inputs(tmp_path)

    with pytest.raises(ValueError, match="ledger identity drifted"):
        resolve_act283_source_bound_variants(
            _act283_nodes(),
            trigger_act_retained_input=act,
            crc_nonoccurrence_retained_input=None,
            current_dws_form_retained_input=dws,
        )

    wrong_request = _retain(
        ledger,
        url=ACT283_CRC_NONOCCURRENCE_URL,
        payload=CRC_FIXTURE,
        sanitized_request={
            "method": "GET",
            "url": ACT283_CRC_NONOCCURRENCE_URL,
            "headers": {"accept": "application/pdf"},
        },
    )
    with pytest.raises(ValueError, match="request identity drifted"):
        resolve_act283_source_bound_variants(
            _act283_nodes(),
            trigger_act_retained_input=act,
            crc_nonoccurrence_retained_input=wrong_request,
            current_dws_form_retained_input=dws,
        )

    _stale_ledger, stale_act, stale_crc, stale_dws = _retained_inputs(
        tmp_path / "stale",
        dws_retrieved_at=datetime(2026, 8, 24, 23, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="predates the fixed inventory"):
        resolve_act283_source_bound_variants(
            _act283_nodes(),
            trigger_act_retained_input=stale_act,
            crc_nonoccurrence_retained_input=stale_crc,
            current_dws_form_retained_input=stale_dws,
        )

    with pytest.raises(ValueError, match="requires two verified"):
        resolve_act283_source_bound_variants(
            _act283_nodes()[:-1],
            trigger_act_retained_input=act,
            crc_nonoccurrence_retained_input=crc,
            current_dws_form_retained_input=dws,
        )


def test_act283_proof_does_not_resolve_the_other_five_conflicts(
    tmp_path,
    monkeypatch,
) -> None:
    _pin_fixture(monkeypatch)
    _ledger, act, crc, dws = _retained_inputs(tmp_path)
    act283_nodes = _act283_nodes()
    resolutions = resolve_act283_source_bound_variants(
        act283_nodes,
        trigger_act_retained_input=act,
        crc_nonoccurrence_retained_input=crc,
        current_dws_form_retained_input=dws,
    )
    remaining_contract = (
        (
            "19-42-201",
            "AATAAEAADAACAAC",
            "6J02-Y1M0-R03N-11YK-00008-00",
            "19-42-201. Special revenues enumerated.",
            "AATAAEAADAACAAD",
            "6JJX-0JB0-R03P-11YC-00008-00",
            "19-42-201. Special revenues enumerated.",
        ),
        (
            "23-4-909",
            "AAXAABAAFAAJAAK",
            "4WVJ-BCY0-R03N-60BF-00008-00",
            "23-4-909. Apportionment of rates and charges.",
            "AAXAABAAFAAJAAL",
            "6FHK-F8H0-R03M-P2W8-00008-00",
            "23-4-909. Apportionment of rates and charges.",
        ),
        (
            "27-14-802",
            "ABBAACAACAAJAAD",
            "4WVS-4PV0-R03K-72V1-00008-00",
            (
                "27-14-802. Application and documents. [Effective until "
                "contingency in Acts 2025, No. 926, § 12, is met.]"
            ),
            "ABBAACAACAAJAAE",
            "6G0S-8470-R03N-60JG-00008-00",
            (
                "27-14-802. Application and documents. [Effective if "
                "contingency in Acts 2025, No. 926, § 12, is met.]"
            ),
        ),
        (
            "27-14-803",
            "ABBAACAACAAJAAF",
            "4WVS-4PV0-R03K-72V2-00008-00",
            (
                "27-14-803. Filing and certification. [Effective until "
                "contingency in Acts 2025, No. 926, § 12, is met.]"
            ),
            "ABBAACAACAAJAAG",
            "6G0S-8FX0-R03N-60JH-00008-00",
            (
                "27-14-803. Filing and certification. [Effective if "
                "contingency in Acts 2025, No. 926, § 12, is met.]"
            ),
        ),
        (
            "5-64-308",
            "AAFAAHAAFAAEAAG",
            "4WPT-00W0-R03K-10WH-00008-00",
            (
                "5-64-308. Prescriptions. [Effective until contingent "
                "effective date as stated in Acts 2019, No. 447, § 2]"
            ),
            "AAFAAHAAFAAEAAH",
            "5VST-6VD0-R03M-70WR-00008-00",
            (
                "5-64-308. Prescriptions — Mandatory electronic prescribing. "
                "[Effective on contingent effective date as stated in Acts "
                "2019, No. 447, § 2]"
            ),
        ),
    )
    remaining_nodes = []
    for (
        section,
        first_id,
        first_urn,
        first_title,
        second_id,
        second_urn,
        second_title,
    ) in remaining_contract:
        for node_id, urn, title in (
            (first_id, first_urn, first_title),
            (second_id, second_urn, second_title),
        ):
            remaining_nodes.append(
                _bound_node(
                    node_id=node_id,
                    section_number=section,
                    title=title,
                    link_href=(
                        f"/shared/document/statutes-legislation/urn:contentItem:{urn}"
                    ),
                )
            )

    decisions = reconcile_current_statute_variants(
        (*act283_nodes, *remaining_nodes),
        observed_at=OBSERVED_AT,
        source_bound_resolutions=resolutions,
    )
    by_section = {item.section_number: item for item in decisions}
    assert len(by_section) == 7
    assert by_section["11-10-803"].disposition == "selected_current_locator"
    assert by_section["26-51-905"].disposition == "selected_current_locator"
    assert all(
        by_section[section].disposition == "unresolved"
        for section in (
            "19-42-201",
            "23-4-909",
            "27-14-802",
            "27-14-803",
            "5-64-308",
        )
    )


def test_four_identity_urns_use_one_same_domain_plural_archive_wave(
    monkeypatch,
) -> None:
    titles = {
        "AATAAEAADAACAAC": "19-42-201. Special revenues enumerated.",
        "AATAAEAADAACAAD": "19-42-201. Special revenues enumerated.",
        "AAXAABAAFAAJAAK": "23-4-909. Apportionment of rates and charges.",
        "AAXAABAAFAAJAAL": "23-4-909. Apportionment of rates and charges.",
    }
    nodes = tuple(
        _bound_node(
            node_id=node_id,
            section_number=section_number,
            title=titles[node_id],
            link_href=link_href,
        )
        for section_number, node_id, link_href in (
            UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT
        )
    )
    assert len(exact_unresolved_variant_identity_document_nodes(nodes)) == 4
    observed: dict[str, object] = {"calls": 0}
    scraper = ArkansasScraper("AR", "Arkansas")

    async def _batch(urls, **kwargs):
        observed["calls"] = int(observed["calls"]) + 1
        observed["urls"] = list(urls)
        observed["kwargs"] = kwargs
        payloads = [
            (
                "<!doctype html><html><body><div id='document-content'>"
                f"<h1>{node.section_number}. Exact delegated statute.</h1>"
                "<p>This exact enacted statutory body contains enough "
                "substantive words for strict Arkansas citation validation."
                "</p></div></body></html>"
            ).encode()
            for node in nodes
        ]
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
                    "range_fetch_calls": 1,
                    "naive_range_fetches": 4,
                    "range_fetches_avoided": 3,
                },
            },
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _batch,
    )
    rows, diagnostics, stats = asyncio.run(
        scraper._fetch_exact_unresolved_delegated_lexis_variant_identities(
            code_name="Arkansas Code",
            nodes=nodes,
        )
    )

    assert observed["calls"] == 1
    assert observed["urls"] == [document_page_url(node) for node in nodes]
    kwargs = observed["kwargs"]
    assert kwargs["common_crawl_domain_terms"] == ("advance.lexis.com",)
    assert kwargs["common_crawl_url_terms"] == ("/documentpage/",)
    assert kwargs["wayback_prefix_inventory"] is True
    assert kwargs["residual_retry_attempts"] == 1
    assert kwargs["repeat_grouped_archive_inventory_on_residual"] is False
    assert stats["common_crawl_inventory_queries"] == 1
    assert stats["common_crawl"]["warc_objects"] == 1
    assert stats["common_crawl"]["range_fetches_avoided"] == 3
    assert stats["arkansas_exact_identity_frontier"] is True
    assert all(row is not None for row in rows)
    assert all(item["disposition"] == "verified_body_probe" for item in diagnostics)


def test_four_identity_urn_retry_submits_only_exact_residuals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    titles = {
        "AATAAEAADAACAAC": "19-42-201. Special revenues enumerated.",
        "AATAAEAADAACAAD": "19-42-201. Special revenues enumerated.",
        "AAXAABAAFAAJAAK": "23-4-909. Apportionment of rates and charges.",
        "AAXAABAAFAAJAAL": "23-4-909. Apportionment of rates and charges.",
    }
    nodes = tuple(
        _bound_node(
            node_id=node_id,
            section_number=section_number,
            title=titles[node_id],
            link_href=link_href,
        )
        for section_number, node_id, link_href in (
            UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT
        )
    )
    urls = [document_page_url(node) for node in nodes]
    residual_urls = [urls[1], urls[3]]
    node_by_url = dict(zip(urls, nodes, strict=True))
    calls: list[tuple[list[str], dict[str, object]]] = []
    scraper = ArkansasScraper("AR", "Arkansas")

    async def _plural_attempt(attempt_urls, **kwargs):
        attempt = len(calls)
        current_urls = list(attempt_urls)
        calls.append((current_urls, dict(kwargs)))
        payloads: list[bytes] = []
        errors: list[str | None] = []
        receipts: list[dict[str, str] | None] = []
        for url in current_urls:
            if attempt == 0 and url in residual_urls:
                payloads.append(b"")
                errors.append("bounded initial miss")
                receipts.append(None)
                continue
            node = node_by_url[url]
            payload = (
                "<!doctype html><html><body><div id='document-content'>"
                f"<h1>{node.section_number}. Exact delegated statute.</h1>"
                "<p>This exact enacted statutory body contains enough "
                "substantive words for strict Arkansas citation validation."
                "</p></div></body></html>"
            ).encode()
            payloads.append(payload)
            errors.append(None)
            receipts.append(
                {
                    "official_url": url,
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "source_transport": "direct",
                }
            )
        return StateLawPageMultiFetchResult(
            urls=current_urls,
            payloads=payloads,
            errors=errors,
            transport_receipts=receipts,
            parser_input_envelopes=[None] * len(current_urls),
            stats={
                "network_requested_pages": len(current_urls),
                "common_crawl_inventory_queries": 1 if attempt == 0 else 0,
                "fallback_requests": 0,
                "per_page_archive_fallback_disabled": True,
                "common_crawl": {
                    "requested_pages": len(current_urls) if attempt == 0 else 0,
                },
            },
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural_attempt,
    )
    rows, diagnostics, stats = asyncio.run(
        scraper._fetch_exact_unresolved_delegated_lexis_variant_identities(
            code_name="Arkansas Code",
            nodes=nodes,
        )
    )

    assert [call_urls for call_urls, _kwargs in calls] == [urls, residual_urls]
    assert calls[0][1]["wayback_prefix_inventory"] is True
    assert calls[1][1]["archive_recovery_enabled"] is False
    assert calls[1][1]["wayback_prefix_inventory"] is True
    assert stats["common_crawl_inventory_queries"] == 1
    assert stats["fallback_requests"] == 0
    assert stats["per_page_archive_fallback_disabled"] is True
    assert stats["residual_retry_rounds_executed"] == 1
    assert stats["residual_retry_requested_pages"] == 2
    assert stats["residual_retry_unresolved_pages"] == 0
    assert all(row is not None for row in rows)
    assert all(item["disposition"] == "verified_body_probe" for item in diagnostics)

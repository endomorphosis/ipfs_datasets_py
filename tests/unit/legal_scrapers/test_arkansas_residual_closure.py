"""LCR-099: Arkansas exact proof and URN residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded Act 283 plus four identity-URN residual and the production
contracts that forbid Hub mutation, static lists, per-page archive loops,
unbounded locator hunts, and encoding diagnostic notes as decisions.
Arkansas remains fail-closed without Act 283 CRC and DWS proof inputs.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import arkansas_lexis
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
    ArkansasDelegatedCorpusBlockedError,
    ArkansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas_lexis import (
    ACT283_CRC_NONOCCURRENCE_URL,
    ACT283_DWS_CURRENT_FORM_URL,
    ACT283_EXCLUSION_DISPOSITION,
    ACT283_URL,
    ACT283_VARIANT_CONTRACT,
    ADVANCE_ORIGIN,
    ARKANSAS_DELEGATED_INVENTORY_SHA256,
    ARKANSAS_ENACTMENT_TOC_SELECTION_PLAN_SHA256,
    CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    TOC_DOCUMENT_CONFIG,
    TOC_SEARCH_MFID,
    UNRESOLVED_VARIANT_DOCUMENT_CONTRACT,
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
    / "arkansas_residual_closure_v1.md"
)

OFFICIAL_ENTRY = "https://www.arkleg.state.ar.us/ArkansasLaw/"
OBSERVED_AT = "2026-08-25T04:32:58.722528+00:00"
TOC_RECEIPT_SHA256 = "c" * 64
CURRENT_RETRIEVAL = datetime(2026, 8, 25, 9, tzinfo=UTC)
ACT283_FIXTURE = b"%PDF-1.7\nExact synthetic Arkansas Act 283.\n%%EOF\n"
CRC_FIXTURE = b"%PDF-1.7\nExact synthetic CRC nonoccurrence record.\n%%EOF\n"
DWS_FIXTURE = b"%PDF-1.7\nExact synthetic current DWS withholding form.\n%%EOF\n"
ENUMERABLE_EXACT_URL_RESIDUAL = 6
IDENTITY_URN_COUNT = 4
ACT283_MISSING_PROOF_URLS = 2
UNIDENTIFIED_CERTIFICATION_COUNT = 2
MINIMUM_PROOF_INPUT_RESIDUAL = 8
AUTHORIZING_PROOF_RECEIPTS = 65
DELEGATED_LOCATORS = 38317
UNIQUE_CITATIONS = 38183
CONCURRENT_GROUPS = 132
ORIGINAL_CONFLICT_SELECTED = 30
ORIGINAL_CONFLICT_UNRESOLVED = 7
AFTER_ACT283_SELECTED = 32
AFTER_ACT283_UNRESOLVED = 5
PREFLIGHT_SELECTED = 124
PREFLIGHT_UNRESOLVED = 7
INVENTORY_SHA256 = ARKANSAS_DELEGATED_INVENTORY_SHA256
DECISION_SHA256 = (
    "edb8578ae9029280f6bd134d89fd81722a2291e6e1a63158bf4dfbe8002b9450"
)
SOURCE_BUNDLE_PREFIX = "a7d971e83edb"
RESIDUAL_SHA256_PREFIX = "enumerable_six_known_urls"
ACT283_WAVE_NAME = "atomic-act283-crc-dws-proof-bundle"
IDENTITY_WAVE_NAME = "same-domain-identity-urn-bodies"
RESIDUAL_WAVE_NAME = "act283-proof-then-identity-urns"
UNRESOLVED_CITATIONS = (
    "11-10-803",
    "19-42-201",
    "23-4-909",
    "26-51-905",
    "27-14-802",
    "27-14-803",
    "5-64-308",
)
IDENTITY_TITLES = {
    "AATAAEAADAACAAC": "19-42-201. Special revenues enumerated.",
    "AATAAEAADAACAAD": "19-42-201. Special revenues enumerated.",
    "AAXAABAAFAAJAAK": "23-4-909. Apportionment of rates and charges.",
    "AAXAABAAFAAJAAL": "23-4-909. Apportionment of rates and charges.",
}
INVENTED_AG_CERT_URL = (
    "https://arkansasag.gov/opinions/act-447-certification.pdf"
)
INVENTED_OMV_CERT_URL = (
    "https://www.arkleg.state.ar.us/Acts/FTPDocument?"
    "path=%2FCERTS%2F&file=act926-omv.pdf&ddBienniumSession=2025%2F2025R"
)
INVENTED_LATER_URN = (
    f"{ADVANCE_ORIGIN}/documentpage/?pdmfid={TOC_SEARCH_MFID}&config="
    f"{TOC_DOCUMENT_CONFIG}&pddocfullpath=%2Fshared%2Fdocument%2F"
    "statutes-legislation%2Furn%3AcontentItem%3A9999-XXXX-R03N-0000-00000-00"
)
CRC_SHA256 = "09fb6ff50d24402023c3446823629d6830864997fb87bc30ae3348ecb31473b1"
DWS_SHA256 = "00eca78717a0ce162e2d2d778348c2a25fc2f19c6e5da7c84e769ae349d5a40a"
ACT283_SHA256 = "3df754fb7c243c620289f2f05a0381a11f2e787a94b6e1998746ee870320b5a0"
CONTINUATION_BASE_COMMIT = "c3156cac939f6b8b7d8186d172349dbb87964ef9"
CONTINUATION_SOURCE_IDENTITY = (
    "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas."
    "ArkansasScraper@sha256:"
    "cbefc80a992c56260dfdfaf8e3b3b324a5d87b96fc6126051c3b0cdb20962889"
)
CONTINUATION_SEED_RECEIPT_SHA256 = (
    "a8af6d5e97352d9e682c77cd20a32fa19093b4f4def4be1f31e4468382cd8afb"
)
CONTINUATION_SEED_PROJECTION_SHA256 = (
    "28e2d7e9fc154cfe23becb647fc132bfa885899497391bbfadc454de5e6ea980"
)
CONTINUATION_PROOF_PROJECTION_SHA256 = (
    "4fc241f23a60a514e6d71a9106c5d42738f63f21227dbf7b50bfd90dd23fc5e9"
)
CONTINUATION_CRC_RECEIPT_SHA256 = (
    "4281436044f1ffe26b9aaad07eaac05b2240b462205b0fbe6bb6060ca467857a"
)
CONTINUATION_CRC_TRANSPORT_SHA256 = (
    "847fa07cf60bc812b239c9f54fe31d886bdb843325d0a8b0f65fa15d2a0d2f35"
)
CONTINUATION_DWS_RECEIPT_SHA256 = (
    "e5b453930da56d30843b07e378e7923118f8ee7ee9fea657c8e6221bbd8a0382"
)
CONTINUATION_DWS_TRANSPORT_SHA256 = (
    "c57152da2e23382efe43af02a0bbfcb7355d2b61fa8d76d68b0ed69b1391968e"
)
CONTINUATION_IDENTITY_URL_SHA256 = (
    "e8c900cab34f8232c13fc355472d5f9ad90292b3ae98fe5b39a7ed9e10d3dddc"
)
CONTINUATION_DECISION_SHA256 = (
    "ade2bcb9dfb9595c9471654857fb40d7d959a8b94f5f045fa4ae0be43e3217e5"
)
READINESS_EVIDENCE_ROOT = (
    "/home/barberb/.ipfs_datasets/state_laws/"
    "legal-corpora-reindex-20260829-ar-source-readiness-research-v1-6CmeUd"
)
READINESS_PROJECTION_SHA256 = (
    "6b4bb50ee510e35b00f860c13a6074a29edec902ef7d1e6c9cbd0a26ae05c756"
)
READINESS_LEXIS_CONTAINER_BUNDLE_SHA256 = (
    "e0c36ce9b9cd33a109a683340faefdf957c695f27ac97d39542b67c2c2604ba3"
)
READINESS_LEXIS_CONTAINER_BUNDLE_RECEIPT_SHA256 = (
    "d307075788556a856c5263e805a82efee24580792dfbfa2fe560bf7ca6374f0c"
)
READINESS_ARKLEG_SEARCH_RECEIPT_SHA256 = (
    "31602e094c6be0a96821106eec4c39d3973a4836fc2eb163aae5e6786e112e93"
)
READINESS_AG_INDEX_UPDATED_AT = "2026-08-29T00:31:21.527062309Z"


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


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


def _identity_nodes() -> tuple[ArkansasLexisNode, ...]:
    return tuple(
        _bound_node(
            node_id=node_id,
            section_number=section_number,
            title=IDENTITY_TITLES[node_id],
            link_href=link_href,
        )
        for section_number, node_id, link_href in (
            UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT
        )
    )


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


def _identity_document_urls() -> list[str]:
    return [document_page_url(node) for node in _identity_nodes()]


def _enumerable_residual_urls() -> list[str]:
    return [
        ACT283_CRC_NONOCCURRENCE_URL,
        ACT283_DWS_CURRENT_FORM_URL,
        *_identity_document_urls(),
    ]


def _pin_act283_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _retain(
    ledger: StateLawMultiFetchAcquisitionLedger,
    *,
    url: str,
    payload: bytes,
    retrieved_at: datetime = CURRENT_RETRIEVAL,
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
        sanitized_request={"method": "GET", "url": url},
        network_used=True,
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
            "network_requested_pages": len(urls),
            "direct_initial_successes": len(urls),
            "per_page_archive_fallback_disabled": True,
            "fallback_requests": 0,
            "common_crawl_inventory_queries": 1,
            "common_crawl": {
                "range_fetch_calls": 1,
                "naive_range_fetches": len(urls),
                "range_fetches_avoided": max(0, len(urls) - 1),
            },
        },
    )


class _SharedPageBatchFetcher:
    def __init__(self, section_by_url: dict[str, str]) -> None:
        self.section_by_url = dict(section_by_url)
        self.requests: list[tuple[list[str], dict[str, object]]] = []

    async def __call__(
        self,
        urls: list[str],
        **kwargs: object,
    ) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        self.requests.append((requested, dict(kwargs)))
        payloads = []
        for url in requested:
            section = self.section_by_url[url]
            payloads.append(
                (
                    "<!doctype html><html><body><div id='document-content'>"
                    f"<h1>{section}. Exact delegated statute.</h1>"
                    "<p>This exact enacted statutory body contains enough "
                    "substantive words for strict Arkansas citation validation "
                    "and must never be treated as a guessed later URN.</p>"
                    "</div></body></html>"
                ).encode()
            )
        return _frontier_result(requested, payloads)


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Arkansas residual closure report is empty")
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


def test_arkansas_residual_closure_report_records_exact_proof_and_urn_residual() -> None:
    report = _report_text()
    table = _report_table(report)
    residual_urls = _enumerable_residual_urls()
    identity_urls = _identity_document_urls()

    assert table["jurisdiction"] == "AR"
    assert table["official domain"] == "www.arkleg.state.ar.us"
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_delegated_entry"] == PUBLIC_ENTRY_URL
    assert table["official_container"] == PUBLIC_CONTAINER_URL
    assert table["official_document_page"] == f"{ADVANCE_ORIGIN}/documentpage/"
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == (
        "delegated Lexis current-variant proof plus identity URN bodies"
    )
    assert table["fail_closed_without_act283_proof_inputs"] == "true"
    assert table["act283_already_retained_replay_only"] == "true"
    assert table["hr5330_already_closed"] == "true"
    assert table["unbounded_locator_hunt"] == "forbidden"
    assert table["encode_diagnostic_notes_as_decisions"] == "forbidden"
    assert table["invent_certification_urls"] == "forbidden"
    assert table["invent_later_urn_targets"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["delegated_inventory_sha256"] == INVENTORY_SHA256
    assert table["enactment_toc_selection_plan_sha256"] == (
        ARKANSAS_ENACTMENT_TOC_SELECTION_PLAN_SHA256
    )
    assert table["act283_selection_plan_sha256"] == act283_selection_plan_sha256()
    assert table["decision_sha256"] == DECISION_SHA256
    assert table["authorizing_proof_receipts"] == str(AUTHORIZING_PROOF_RECEIPTS)
    assert table["authorizing_proof_objects"] == str(AUTHORIZING_PROOF_RECEIPTS)
    assert table["delegated_locators"] == str(DELEGATED_LOCATORS)
    assert table["unique_citations"] == str(UNIQUE_CITATIONS)
    assert table["concurrent_citation_groups"] == str(CONCURRENT_GROUPS)
    assert table["original_conflict_selected"] == str(ORIGINAL_CONFLICT_SELECTED)
    assert table["original_conflict_unresolved"] == str(
        ORIGINAL_CONFLICT_UNRESOLVED
    )
    assert table["after_act283_selected"] == str(AFTER_ACT283_SELECTED)
    assert table["after_act283_unresolved"] == str(AFTER_ACT283_UNRESOLVED)
    assert table["preflight_selected"] == str(PREFLIGHT_SELECTED)
    assert table["preflight_unresolved"] == str(PREFLIGHT_UNRESOLVED)
    assert table["act283_missing_proof_urls"] == str(ACT283_MISSING_PROOF_URLS)
    assert table["identity_urn_urls"] == str(IDENTITY_URN_COUNT)
    assert table["enumerable_exact_url_residual"] == str(
        ENUMERABLE_EXACT_URL_RESIDUAL
    )
    assert table["unidentified_certification_count"] == str(
        UNIDENTIFIED_CERTIFICATION_COUNT
    )
    assert table["minimum_nonduplicative_proof_input_residual"] == str(
        MINIMUM_PROOF_INPUT_RESIDUAL
    )
    assert table["residual_count"] == str(ENUMERABLE_EXACT_URL_RESIDUAL)
    assert table["residual_kind"] == (
        "two Act 283 proof URLs plus four identity URNs; "
        "two unidentified certifications"
    )
    assert table["residual_first_url"] == ACT283_CRC_NONOCCURRENCE_URL
    assert table["act283_wave_name"] == ACT283_WAVE_NAME
    assert table["identity_wave_name"] == IDENTITY_WAVE_NAME
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["act283_acquisition_wave_count"] == "1"
    assert table["identity_acquisition_wave_count"] == "1"
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["diagnostic_hashes_authorizing"] == "false"
    assert table["source_bundle_prefix"] == SOURCE_BUNDLE_PREFIX
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert ACT283_MISSING_PROOF_URLS + IDENTITY_URN_COUNT == (
        ENUMERABLE_EXACT_URL_RESIDUAL
    )
    assert (
        ENUMERABLE_EXACT_URL_RESIDUAL + UNIDENTIFIED_CERTIFICATION_COUNT
        == MINIMUM_PROOF_INPUT_RESIDUAL
    )
    assert ORIGINAL_CONFLICT_SELECTED + 2 == AFTER_ACT283_SELECTED
    assert ORIGINAL_CONFLICT_UNRESOLVED - 2 == AFTER_ACT283_UNRESOLVED
    for citation in UNRESOLVED_CITATIONS:
        assert citation in table["unresolved_citations"]

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "fail-closed" in lowered or "fail closed" in lowered
    assert "act 283" in lowered
    assert "hub mutation" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "unbounded locator hunt" in lowered
    assert "diagnostic notes" in lowered
    assert ACT283_CRC_NONOCCURRENCE_URL in report
    assert ACT283_DWS_CURRENT_FORM_URL in report
    assert CRC_SHA256 in report
    assert DWS_SHA256 in report
    assert ACT283_SHA256 in report
    assert PUBLIC_CONTAINER_URL in report
    assert PUBLIC_ENTRY_URL in report
    assert OFFICIAL_ENTRY in report
    for url in residual_urls:
        assert url in report
    for url in identity_urls:
        assert url.startswith(f"{ADVANCE_ORIGIN}/documentpage/?")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        assert query["pdmfid"] == [TOC_SEARCH_MFID]
        assert query["config"] == [TOC_DOCUMENT_CONFIG]
    assert INVENTED_AG_CERT_URL not in report
    assert INVENTED_OMV_CERT_URL not in report
    assert INVENTED_LATER_URN not in report
    assert not re.search(r"residual_ordered_sha256_prefix.*[0-9a-f]{12}", report)


def test_arkansas_executed_continuation_records_exact_receipts_and_blockers() -> None:
    report = _report_text()
    table = _report_table(report)

    expected = {
        "continuation_status": "partial_evidence_closed",
        "continuation_base_commit": CONTINUATION_BASE_COMMIT,
        "continuation_source_identity": CONTINUATION_SOURCE_IDENTITY,
        "continuation_current_bundle_sealed": "false",
        "continuation_publication_authorized": "false",
        "continuation_hub_mutation": "none",
        "continuation_seed_selected_inputs": "65",
        "continuation_seed_unique_objects": "65",
        "continuation_seed_hardlinks": "130",
        "continuation_seed_copies": "0",
        "continuation_seed_network_requests": "0",
        "continuation_seed_migration_receipt_sha256": (
            CONTINUATION_SEED_RECEIPT_SHA256
        ),
        "continuation_seed_projection_sha256": (
            CONTINUATION_SEED_PROJECTION_SHA256
        ),
        "continuation_proof_parser_inputs": "67",
        "continuation_proof_unique_objects": "67",
        "continuation_proof_unique_urls": "67",
        "continuation_proof_total_bytes": "29342101",
        "continuation_proof_projection_sha256": (
            CONTINUATION_PROOF_PROJECTION_SHA256
        ),
        "continuation_crc_parser_receipt_sha256": (
            CONTINUATION_CRC_RECEIPT_SHA256
        ),
        "continuation_crc_transport_receipt_sha256": (
            CONTINUATION_CRC_TRANSPORT_SHA256
        ),
        "continuation_crc_retrieved_at": "2026-08-28T23:48:13.604000Z",
        "continuation_dws_parser_receipt_sha256": (
            CONTINUATION_DWS_RECEIPT_SHA256
        ),
        "continuation_dws_transport_receipt_sha256": (
            CONTINUATION_DWS_TRANSPORT_SHA256
        ),
        "continuation_dws_retrieved_at": "2026-08-28T23:48:13.868000Z",
        "continuation_preflight_network_requests": "0",
        "continuation_preflight_selected": "126",
        "continuation_preflight_no_current": "1",
        "continuation_preflight_unresolved": "5",
        "continuation_original_conflict_selected": "32",
        "continuation_original_conflict_unresolved": "5",
        "continuation_decision_sha256": CONTINUATION_DECISION_SHA256,
        "continuation_authorizing_for_materialization": "false",
        "continuation_identity_url_count": "4",
        "continuation_identity_url_sha256": (
            CONTINUATION_IDENTITY_URL_SHA256
        ),
        "continuation_identity_direct_request_count": "8",
        "continuation_identity_direct_success_count": "0",
        "continuation_identity_common_crawl_inventory_queries": "1",
        "continuation_identity_common_crawl_records": "0",
        "continuation_identity_wayback_prefix_requests": "8",
        "continuation_identity_fallback_requests": "0",
        "continuation_identity_retained_rows": "0",
        "continuation_identity_retained_entries": "0",
        "continuation_ag_opinions_index_documents": "10627",
        "continuation_ag_opinions_index_updated_at": (
            "2026-08-28T23:34:02.793261422Z"
        ),
        "continuation_ag_certification_matches": "0",
        "continuation_act926_certification_locator": "unidentified",
        "continuation_act447_certification_locator": "unidentified",
        "continuation_exact_url_residual_count": "4",
        "continuation_unidentified_certification_count": "2",
        "continuation_minimum_nonduplicative_proof_input_residual": "6",
    }
    for field, value in expected.items():
        assert table[field] == value

    assert _canonical_residual_sha256(_identity_document_urls()) == (
        CONTINUATION_IDENTITY_URL_SHA256
    )
    for expected_sha256, official_url, content_sha256 in (
        (
            CONTINUATION_CRC_TRANSPORT_SHA256,
            ACT283_CRC_NONOCCURRENCE_URL,
            CRC_SHA256,
        ),
        (
            CONTINUATION_DWS_TRANSPORT_SHA256,
            ACT283_DWS_CURRENT_FORM_URL,
            DWS_SHA256,
        ),
    ):
        transport = {
            "content_sha256": content_sha256,
            "official_url": official_url,
            "source_transport": "direct",
        }
        assert hashlib.sha256(
            json.dumps(
                transport,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest() == expected_sha256
    assert table["continuation_sanitized_request_identity"] == (
        "exact no-header GET URL"
    )
    assert table["continuation_parser_change"].startswith("none;")
    assert table["continuation_full_state_live_to_retained_run"].startswith(
        "not launched"
    )
    assert table["continuation_unresolved_citations"] == (
        "19-42-201, 23-4-909, 27-14-802, 27-14-803, 5-64-308"
    )
    continuation = report.split("## Executed continuation — 2026-08-28", 1)[1]
    normalized = " ".join(continuation.casefold().split())
    assert "no parser relaxation was needed" in normalized
    assert "source readiness gate failed" in normalized
    assert "neither occurrence nor nonoccurrence is encoded" in normalized
    assert "zero fallback requests" in normalized
    assert "no full corpus run" in normalized


def test_arkansas_source_readiness_research_is_exact_and_diagnostic_only() -> None:
    report = _report_text()
    table = _report_table(report)

    expected = {
        "readiness_status": "genuine_external_source_blockers",
        "readiness_current_bundle_sealed": "false",
        "readiness_authorizing_for_materialization": "false",
        "readiness_publication_authorized": "false",
        "readiness_evidence_root": READINESS_EVIDENCE_ROOT,
        "readiness_parser_name": (
            "ArkansasSourceReadinessResearchV1DiagnosticOnly"
        ),
        "readiness_parser_inputs": "61",
        "readiness_direct_get_inputs": "56",
        "readiness_direct_post_inputs": "5",
        "readiness_unique_objects": "42",
        "readiness_unique_urls": "57",
        "readiness_total_bytes": "10573969",
        "readiness_projection_sha256": READINESS_PROJECTION_SHA256,
        "readiness_retained_replay_inputs": "61",
        "readiness_retained_replay_network_requests": "0",
        "readiness_arkleg_exact_phrase_queries": "12",
        "readiness_arkleg_exact_phrase_rows": "31",
        "readiness_crc_unique_attachment_urls": "75",
        "readiness_ag_wp_search_requests": "26",
        "readiness_ag_wp_media_matches": "0",
        "readiness_ag_opinions_index_documents": "10627",
        "readiness_ag_opinions_index_updated_at": (
            READINESS_AG_INDEX_UPDATED_AT
        ),
        "readiness_ag_opinions_all_term_queries": "5",
        "readiness_ag_opinions_all_term_matches": "0",
        "readiness_lexis_exact_nodes_candeliver": "4",
        "readiness_lexis_exact_body_inputs": "0",
        "readiness_act926_certification_locator": "unidentified",
        "readiness_act447_certification_locator": "unidentified",
    }
    for field, value in expected.items():
        assert table[field] == value

    assert int(table["readiness_direct_get_inputs"]) + int(
        table["readiness_direct_post_inputs"]
    ) == int(table["readiness_parser_inputs"])
    assert table["readiness_parser_change"].startswith("none;")
    assert table["readiness_unresolved_citations"] == (
        "19-42-201, 23-4-909, 27-14-802, 27-14-803, 5-64-308"
    )
    assert table["readiness_full_state_live_to_retained_run"].startswith(
        "not launched"
    )

    continuation = report.split(
        "## Source-readiness continuation — 2026-08-29", 1
    )[1]
    normalized = " ".join(continuation.casefold().split())
    assert READINESS_LEXIS_CONTAINER_BUNDLE_SHA256 in continuation
    assert READINESS_LEXIS_CONTAINER_BUNDLE_RECEIPT_SHA256 in continuation
    assert READINESS_ARKLEG_SEARCH_RECEIPT_SHA256 in continuation
    assert "/r/tocprovider/6gf5kkk/cart/6gf5kkk" in continuation
    assert 'createsub("cart")' in continuation
    assert '"action":"add-document"' in continuation
    assert "x-ln-currentrequestid" in normalized
    assert "canselect" in normalized
    assert "canopen" in normalized
    assert "candeliver" in normalized
    assert "human-verification boundary" in normalized
    assert "no challenge body or error page was admitted" in normalized
    assert "search bodies are diagnostic evidence" in normalized
    assert "does not prove" in normalized
    assert "no full arkansas corpus proof was launched" in normalized


def test_arkansas_fail_closed_without_act283_proof_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_act283_fixtures(monkeypatch)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "act283-gap",
        jurisdiction="AR",
        parser_name=CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    )
    _retain(ledger, url=ACT283_URL, payload=ACT283_FIXTURE)
    scraper = ArkansasScraper("AR", "Arkansas")
    scraper.attach_arkansas_current_variant_resolution_ledger(ledger)

    resolutions, diagnostic = asyncio.run(
        scraper._resolve_act283_current_variants(nodes=_act283_nodes())
    )

    assert resolutions == ()
    assert diagnostic["disposition"] == "unresolved"
    assert diagnostic["section_numbers"] == ["11-10-803", "26-51-905"]
    missing = diagnostic["missing_source_urls"]
    assert ACT283_CRC_NONOCCURRENCE_URL in missing
    assert ACT283_DWS_CURRENT_FORM_URL in missing
    assert ACT283_URL not in missing
    assert "retained replay failed" in diagnostic["error"]
    assert diagnostic.get("authorizing_for_materialization") is not True

    with pytest.raises(ValueError, match="ledger identity drifted"):
        resolve_act283_source_bound_variants(
            _act283_nodes(),
            trigger_act_retained_input=_retain(
                ledger, url=ACT283_URL, payload=ACT283_FIXTURE
            ),
            crc_nonoccurrence_retained_input=None,
            current_dws_form_retained_input=None,
        )

    resolve_source = inspect.getsource(resolve_act283_source_bound_variants)
    assert "both Act 283 pairs atomically" in resolve_source
    assert "not a first/last, content-item-age" in resolve_source
    scraper_source = inspect.getsource(
        ArkansasScraper._resolve_act283_current_variants
    )
    assert "missing_source_urls" in scraper_source
    assert "Replay, never invent, the exact three-input Act 283" in (
        scraper_source
    )


def test_arkansas_identity_urn_contract_is_four_same_domain_document_pages() -> None:
    nodes = _identity_nodes()
    selected = exact_unresolved_variant_identity_document_nodes(nodes)
    urls = [document_page_url(node) for node in selected]

    assert UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT == tuple(
        item
        for item in UNRESOLVED_VARIANT_DOCUMENT_CONTRACT
        if item[0] in {"19-42-201", "23-4-909"}
    )
    assert len(UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT) == IDENTITY_URN_COUNT
    assert [node.section_number for node in selected] == [
        "19-42-201",
        "19-42-201",
        "23-4-909",
        "23-4-909",
    ]
    assert [node.node_id for node in selected] == [
        "AATAAEAADAACAAC",
        "AATAAEAADAACAAD",
        "AAXAABAAFAAJAAK",
        "AAXAABAAFAAJAAL",
    ]
    assert len(urls) == len(set(urls)) == IDENTITY_URN_COUNT
    assert all(url.startswith(f"{ADVANCE_ORIGIN}/documentpage/?") for url in urls)
    report = _report_text()
    for url in urls:
        assert url in report
        parsed = urlparse(url)
        assert parsed.hostname == "advance.lexis.com"
        assert parsed.path == "/documentpage/"
        query = parse_qs(parsed.query)
        assert query["pdmfid"] == [TOC_SEARCH_MFID]
        assert query["config"] == [TOC_DOCUMENT_CONFIG]
        assert "crid" not in query and "prid" not in query
    identity_source = inspect.getsource(
        exact_unresolved_variant_identity_document_nodes
    )
    assert "exact four still-unbound identity locators" in identity_source


def test_arkansas_adapter_has_no_static_body_residual_url_list_or_unbounded_hunt() -> None:
    scraper_source = inspect.getsource(ArkansasScraper)
    lexis_module = inspect.getmodule(document_page_url)
    assert lexis_module is not None
    lexis_source = inspect.getsource(lexis_module)
    for payload in (scraper_source, lexis_source):
        assert str(DELEGATED_LOCATORS) not in payload
        assert str(UNIQUE_CITATIONS) not in payload
        assert RESIDUAL_SHA256_PREFIX not in payload
        assert INVENTED_AG_CERT_URL not in payload
        assert INVENTED_OMV_CERT_URL not in payload
        assert INVENTED_LATER_URN not in payload
        assert "unbounded locator hunt" not in payload.casefold()
    identity_contract_source = inspect.getsource(lexis_module)
    assert "UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT" in (
        identity_contract_source
    )
    fetch_source = inspect.getsource(
        ArkansasScraper._fetch_verified_delegated_lexis_statutes
    )
    assert "require_exact_identity_frontier" in fetch_source
    assert 'common_crawl_domain_terms=("advance.lexis.com",)' in fetch_source
    assert 'common_crawl_url_terms=("/documentpage/",)' in fetch_source
    scrape_source = inspect.getsource(ArkansasScraper.scrape_code)
    assert "ArkansasDelegatedCorpusBlockedError" in scrape_source


def test_arkansas_enumerable_residual_sha256_uses_canonical_json_of_six_known_urls() -> None:
    residual = _enumerable_residual_urls()
    assert residual[:2] == [
        ACT283_CRC_NONOCCURRENCE_URL,
        ACT283_DWS_CURRENT_FORM_URL,
    ]
    assert residual[2:] == _identity_document_urls()
    assert len(residual) == ENUMERABLE_EXACT_URL_RESIDUAL
    digest = _canonical_residual_sha256(residual)
    assert len(digest) == 64
    assert digest != RESIDUAL_SHA256_PREFIX
    compact = residual[:2]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert ACT283_WAVE_NAME in report
    assert IDENTITY_WAVE_NAME in report
    assert "2 + 4 = 6" in report.replace(" ", "") or "2+4=6" in report.replace(
        " ", ""
    )
    assert "2 Act 283" in report and "4 identity" in report


def test_arkansas_one_identity_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(
        ArkansasScraper._fetch_verified_delegated_lexis_statutes
    )
    identity_source = inspect.getsource(
        ArkansasScraper._fetch_exact_unresolved_delegated_lexis_variant_identities
    )
    retry_source = inspect.getsource(
        ArkansasScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "Submit the exact four identity-gap URNs as one shared body wave" in (
        identity_source
    )
    assert "require_exact_identity_frontier=True" in identity_source
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "legacy per-page archive fallback" in fetch_source
    assert "Arkansas delegated frontier repeated Common Crawl inventory" in (
        fetch_source
    )
    assert "no per-page archive loop" in retry_source
    assert "archive.is" in retry_source.casefold()
    assert "archive.is" not in identity_source.casefold()


def test_arkansas_seed_and_host_replay_forbid_hub_docker_and_unbounded_hunts(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "AR",
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
    assert "unbounded locator hunt" in report
    assert "diagnostic notes" in report

    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    assert "public_law_no_state_copyright" in closure_source


def test_arkansas_compact_identity_recipe_emits_four_urns_not_invented_certifications() -> None:
    nodes = _identity_nodes()
    residual = [document_page_url(node) for node in nodes]
    assert residual == _identity_document_urls()
    assert len(residual) == IDENTITY_URN_COUNT
    assert INVENTED_AG_CERT_URL not in residual
    assert INVENTED_OMV_CERT_URL not in residual
    assert INVENTED_LATER_URN not in residual
    assert ACT283_CRC_NONOCCURRENCE_URL not in residual
    assert ACT283_DWS_CURRENT_FORM_URL not in residual
    digest = _canonical_residual_sha256(residual)
    assert len(digest) == 64
    assert digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    report = _report_text()
    for url in residual:
        assert url in report
    assert INVENTED_AG_CERT_URL not in report
    assert INVENTED_OMV_CERT_URL not in report
    assert INVENTED_LATER_URN not in report


def test_arkansas_complete_identity_union_is_one_plural_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = _identity_nodes()
    residual = [document_page_url(node) for node in nodes]
    fetcher = _SharedPageBatchFetcher(
        {document_page_url(node): str(node.section_number) for node in nodes}
    )
    scraper = ArkansasScraper("AR", "Arkansas")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        fetcher,
    )

    rows, diagnostics, stats = asyncio.run(
        scraper._fetch_exact_unresolved_delegated_lexis_variant_identities(
            code_name="Arkansas Code",
            nodes=nodes,
        )
    )

    assert fetcher.requests and len(fetcher.requests) == 1
    requested, kwargs = fetcher.requests[0]
    assert requested == residual
    assert kwargs["prefer_direct"] is True
    assert kwargs["wayback_prefix_inventory"] is True
    assert kwargs["repeat_grouped_archive_inventory_on_residual"] is False
    assert kwargs["common_crawl_domain_terms"] == ("advance.lexis.com",)
    assert kwargs["common_crawl_url_terms"] == ("/documentpage/",)
    assert stats["arkansas_exact_identity_frontier"] is True
    assert stats["arkansas_exact_unresolved_frontier"] is False
    assert stats["common_crawl_inventory_queries"] == 1
    assert len(rows) == IDENTITY_URN_COUNT
    assert len(diagnostics) == IDENTITY_URN_COUNT
    assert INVENTED_LATER_URN not in requested
    assert _canonical_residual_sha256(requested) == _canonical_residual_sha256(
        residual
    )


def test_arkansas_act283_atomic_bundle_does_not_close_identity_or_certification_residuals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_act283_fixtures(monkeypatch)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "act283-complete",
        jurisdiction="AR",
        parser_name=CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    )
    act = _retain(ledger, url=ACT283_URL, payload=ACT283_FIXTURE)
    crc = _retain(
        ledger, url=ACT283_CRC_NONOCCURRENCE_URL, payload=CRC_FIXTURE
    )
    dws = _retain(
        ledger, url=ACT283_DWS_CURRENT_FORM_URL, payload=DWS_FIXTURE
    )
    act283_nodes = _act283_nodes()
    identity_nodes = _identity_nodes()
    resolutions = resolve_act283_source_bound_variants(
        act283_nodes,
        trigger_act_retained_input=act,
        crc_nonoccurrence_retained_input=crc,
        current_dws_form_retained_input=dws,
    )
    decisions = reconcile_current_statute_variants(
        (*act283_nodes, *identity_nodes),
        observed_at=OBSERVED_AT,
        source_bound_resolutions=resolutions,
    )
    by_section = {item.section_number: item for item in decisions}
    assert by_section["11-10-803"].disposition == "selected_current_locator"
    assert by_section["26-51-905"].disposition == "selected_current_locator"
    assert by_section["19-42-201"].disposition == "unresolved"
    assert by_section["23-4-909"].disposition == "unresolved"
    assert all(
        item.excluded_disposition == ACT283_EXCLUSION_DISPOSITION
        for item in resolutions
    )
    report = " ".join(_report_text().casefold().split())
    assert "select neither" in report
    assert "does not authorize materialization" in report


def test_arkansas_invented_certification_and_diagnostic_urls_are_not_admitted_as_residual() -> None:
    report = _report_text()
    residual = _enumerable_residual_urls()
    assert INVENTED_AG_CERT_URL not in residual
    assert INVENTED_OMV_CERT_URL not in residual
    assert INVENTED_LATER_URN not in residual
    assert INVENTED_AG_CERT_URL not in report
    assert INVENTED_OMV_CERT_URL not in report
    assert INVENTED_LATER_URN not in report
    lowered = " ".join(report.casefold().split())
    assert "cannot be guessed" in lowered
    assert "diagnostic only" in lowered or "diagnostic notes" in lowered
    assert "source-sealed locator" in lowered or "not yet source-sealed" in lowered
    assert "s000000464" in lowered
    assert "epcs" in lowered
    assert ACT283_CRC_NONOCCURRENCE_URL in residual
    assert ACT283_DWS_CURRENT_FORM_URL in residual
    fetch_source = inspect.getsource(
        ArkansasScraper._fetch_verified_delegated_lexis_statutes
    )
    assert "require_exact_identity_frontier" in fetch_source
    assert INVENTED_AG_CERT_URL not in fetch_source
    blocked_source = inspect.getsource(ArkansasDelegatedCorpusBlockedError)
    assert "admissible body bytes" in blocked_source

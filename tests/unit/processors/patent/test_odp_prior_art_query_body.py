"""Unit tests for ODP prior-art search body construction and hit shaping."""

from __future__ import annotations

import json

from ipfs_datasets_py.processors.domains.patent.prior_art import QueryFamily
from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
    PublicSearchQuery,
    _build_odp_search_body,
    _odp_items_to_journal_hits,
)
from ipfs_datasets_py.processors.domains.patent.search_journal import SearchDatabase
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    ApiKeySecret,
    RecordedExchange,
    RecordedHttpTransport,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PatentFileWrapperClient,
)


def test_odp_body_uses_keyword_and() -> None:
    q = PublicSearchQuery(
        query_id="q1",
        query_text="tamper evident securing monitoring device individual",
        database=SearchDatabase.US_PATENTS,
        keywords=("tamper", "evident", "securing", "monitoring", "individual"),
        family=QueryFamily.CLAIM_LIMITATION,
    )
    body = _build_odp_search_body(q)
    assert "AND" in body["q"]
    assert "tamper" in body["q"]
    assert "offset" not in body
    assert "limit" not in body


def test_odp_body_classification_fielded() -> None:
    q = PublicSearchQuery(
        query_id="q-class",
        query_text="G06F16/00",
        database=SearchDatabase.US_PATENTS,
        family=QueryFamily.CLASSIFICATION_CPC,
        classification_codes=("G06F16/00",),
    )
    body = _build_odp_search_body(q)
    assert "cpc" in body["q"].lower() or "G06F16" in body["q"]


def test_odp_hits_enrich_title_and_identifiers() -> None:
    items = [
        {
            "applicationNumberText": "18654466",
            "applicationMetaData": {
                "inventionTitle": "SYSTEMS AND METHODS FOR TAMPER EVIDENT SECURING",
                "applicationStatusDescriptionText": "Patented Case",
                "filingDate": "2024-05-03",
                "firstInventorName": "Example",
                "earliestPublicationNumber": "US-2025-0259523-A1",
                "cpcClassificationBag": [{"cpcSymbolText": "A61B5/00"}],
            },
        }
    ]
    hits = _odp_items_to_journal_hits(items, rank_cutoff=5, receipt_id="receipt:test")
    assert len(hits) == 1
    hit = hits[0]
    assert "TAMPER" in (hit.passage_excerpt or "").upper()
    assert hit.identifiers.get("applicationNumberText") == "18654466"
    assert "google_patents_url" in hit.metadata
    assert "title" in hit.metadata


def test_search_client_sends_nested_pagination_only() -> None:
    """Live ODP rejects top-level offset/limit; body must nest under pagination."""
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="POST",
                path="/api/v1/patent/applications/search",
                status=200,
                body={
                    "count": 1,
                    "patentFileWrapperDataBag": [
                        {"applicationNumberText": "16000001"}
                    ],
                },
            )
        ]
    )
    client = PatentFileWrapperClient(
        transport=transport,
        api_key=ApiKeySecret("test-key-not-a-secret"),
        retry_policy=__import__(
            "ipfs_datasets_py.processors.domains.uspto.providers.base",
            fromlist=["RetryPolicy"],
        ).RetryPolicy(max_attempts=1, base_delay_seconds=0.0),
    )
    result = client.search("tamper evident", limit=5)
    assert result.ok
    assert transport.requests, "expected recorded outbound request"
    raw = transport.requests[0].body
    assert raw is not None
    body = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    assert "pagination" in body
    assert body["pagination"]["limit"] == 5
    assert body["pagination"]["offset"] == 0
    assert "offset" not in body
    assert "limit" not in body

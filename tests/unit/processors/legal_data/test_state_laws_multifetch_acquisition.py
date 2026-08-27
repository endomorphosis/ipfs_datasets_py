"""Prospective multi-fetch state-law acquisition evidence checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_data import (
    open_us_law_acquisition_coordinator,
    patent_authority_contracts_v2,
    state_laws_legacy_v2_adapter,
    state_laws_multifetch_acquisition,
    state_laws_source_provenance,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    closed_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    AUTHORIZES_LEGACY_CHECKPOINTS,
    AUTHORIZES_REMATERIALIZATION_RECEIPTS,
    StateLawMultiFetchAcquisitionError,
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
)

OFFICIAL_START = "https://docs.legis.wisconsin.gov/statutes/statutes/1"
OFFICIAL_ONE = "https://docs.legis.wisconsin.gov/document/statutes/1.01"
OFFICIAL_TWO = "https://docs.legis.wisconsin.gov/document/statutes/1.02"
RELEASE_POINT = hashlib.sha256(b"wi-multifetch-release").hexdigest()


def _direct_receipt(url: str, body: bytes) -> dict[str, object]:
    return {
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "official_url": url,
        "source_transport": "direct",
    }


def _cache_receipt(url: str, body: bytes) -> dict[str, object]:
    return {
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "official_url": url,
        "origin_transport_receipt": _direct_receipt(url, body),
        "source_transport": "fetch_cache",
    }


def _jsonld_bytes() -> bytes:
    rows = [
        {
            "@id": "urn:state:wi:statute:1.01",
            "@type": "Legislation",
            "sectionNumber": "1.01",
            "sourceUrl": OFFICIAL_ONE,
            "stateCode": "WI",
            "text": "A person shall comply with section one.",
        },
        {
            "@id": "urn:state:wi:statute:1.02",
            "@type": "Legislation",
            "sectionNumber": "1.02",
            "sourceUrl": OFFICIAL_TWO,
            "stateCode": "WI",
            "text": "A person shall comply with section two.",
        },
    ]
    return b"".join(
        (json.dumps(row, sort_keys=True) + "\n").encode("utf-8") for row in rows
    )


def _completion_receipt() -> dict[str, object]:
    return closed_jurisdiction_receipt(
        "WI",
        discovered=2,
        fetched=2,
        excluded=0,
        quarantined=0,
        failed_final=0,
        duplicates=0,
        source_domain="docs.legis.wisconsin.gov",
        canonical_keys=[
            "urn:state:wi:statute:1.01",
            "urn:state:wi:statute:1.02",
        ],
        derived_keys=[
            "urn:state:wi:statute:1.01",
            "urn:state:wi:statute:1.02",
        ],
        row_count=2,
    )


def test_each_parser_body_reuses_shared_contracts_and_is_retained(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    body_one = b"official response body one"
    body_two = b"official response body two"

    first = ledger.retain_parser_input(
        official_url=OFFICIAL_ONE,
        body=body_one,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body_one),
        retrieved_at="2026-08-24T01:02:03Z",
    )
    second = ledger.retain_parser_input(
        official_url=OFFICIAL_TWO,
        body=body_two,
        transport_receipt=_cache_receipt(OFFICIAL_TWO, body_two),
        retrieved_at="2026-08-24T01:02:04Z",
    )

    assert first.envelope.body == body_one
    assert first.body_path.read_bytes() == body_one
    assert first.receipt.content.sha256 == hashlib.sha256(body_one).hexdigest()
    assert second.envelope.acquisition.kind.value == "unchanged"
    assert second.receipt.cache_hit is True
    assert second.transport.transport_chain == ("fetch_cache", "direct")

    replayed = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    assert [item.receipt.receipt_sha256 for item in replayed.entries] == [
        item.receipt.receipt_sha256 for item in ledger.entries
    ]

    # Architecture guard: the seam composes, rather than cloning, the shared
    # acquisition, transport, byte/frontier, and source-normalization gates.
    assert (
        state_laws_multifetch_acquisition.AcquisitionReceipt
        is patent_authority_contracts_v2.AcquisitionReceipt
    )
    assert (
        state_laws_multifetch_acquisition.verify_receipt_bytes
        is open_us_law_acquisition_coordinator.verify_receipt_bytes
    )
    assert (
        state_laws_multifetch_acquisition.normalize_source_receipt
        is state_laws_legacy_v2_adapter.normalize_source_receipt
    )
    assert (
        state_laws_multifetch_acquisition.canonicalize_state_law_transport_receipt
        is state_laws_source_provenance.canonicalize_state_law_transport_receipt
    )


def test_cache_body_without_original_transport_receipt_is_rejected(
    tmp_path: Path,
) -> None:
    body = b"unbound historical page-cache body"
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="verified direct/archive/cache origin",
    ):
        ledger.retain_parser_input(
            official_url=OFFICIAL_ONE,
            body=body,
            transport_receipt={
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": OFFICIAL_ONE,
                "source_transport": "fetch_cache",
            },
        )


def test_closed_aggregate_binds_ledgers_and_canonical_jsonld_separately(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    body_one = b"official response body one"
    body_two = b"official response body two"
    ledger.retain_parser_input(
        official_url=OFFICIAL_ONE,
        body=body_one,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body_one),
        retrieved_at="2026-08-24T01:02:03Z",
    )
    ledger.retain_parser_input(
        official_url=OFFICIAL_TWO,
        body=body_two,
        transport_receipt=_direct_receipt(OFFICIAL_TWO, body_two),
        retrieved_at="2026-08-24T01:02:04Z",
    )
    canonical = tmp_path / "STATE-WI.jsonld"
    canonical.write_bytes(_jsonld_bytes())
    completion = _completion_receipt()
    replayed_frontier = dict(completion["frontier"])

    closed = ledger.close_jurisdiction_frontier(
        completion,
        replayed_frontier=replayed_frontier,
        canonical_jsonld_path=canonical,
        release_point=RELEASE_POINT,
        official_source_url=OFFICIAL_START,
        acquisition_path_ids=["wi-docs-statutes"],
        observation_time="2026-08-24T02:00:00Z",
        source_software_version="state-scraper/verified-multifetch",
    )

    canonical_digest = hashlib.sha256(canonical.read_bytes()).hexdigest()
    receipt = closed.receipt
    aggregate = receipt["frontier_aggregate"]
    assert closed.byte_verification.ok is True
    assert closed.byte_verification.raw_bytes_checked is True
    assert closed.frontier_verification.ok is True
    assert closed.normalized_source_receipt.admission_eligible is True
    assert receipt["hashes"]["admitted_body_sha256"] == canonical_digest
    assert aggregate["canonical_jsonld"] == {
        "row_count": 2,
        "sha256": canonical_digest,
    }
    assert aggregate["parser_input_count"] == 2
    assert aggregate["single_response_claims_entire_corpus"] is False
    assert canonical_digest not in {
        hashlib.sha256(body_one).hexdigest(),
        hashlib.sha256(body_two).hexdigest(),
    }
    assert closed.request_ledger_path.is_file()
    assert closed.response_ledger_path.is_file()
    response_ledger = json.loads(closed.response_ledger_path.read_text())
    assert len(response_ledger["responses"]) == 2
    assert all(item["body_relative_path"].startswith("objects/") for item in response_ledger["responses"])


def test_deferred_closure_writes_only_nondiscoverable_pending_receipt(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    body_one = b"official response body one"
    body_two = b"official response body two"
    ledger.retain_parser_input(
        official_url=OFFICIAL_ONE,
        body=body_one,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body_one),
        retrieved_at="2026-08-24T01:02:03Z",
    )
    ledger.retain_parser_input(
        official_url=OFFICIAL_TWO,
        body=body_two,
        transport_receipt=_direct_receipt(OFFICIAL_TWO, body_two),
        retrieved_at="2026-08-24T01:02:04Z",
    )
    canonical = tmp_path / "STATE-WI.jsonld"
    canonical.write_bytes(_jsonld_bytes())
    completion = _completion_receipt()

    closed = ledger.close_jurisdiction_frontier(
        completion,
        replayed_frontier=dict(completion["frontier"]),
        canonical_jsonld_path=canonical,
        release_point=RELEASE_POINT,
        official_source_url=OFFICIAL_START,
        acquisition_path_ids=["wi-docs-statutes"],
        observation_time="2026-08-24T02:00:00Z",
        source_software_version="state-scraper/verified-multifetch",
        defer_normalized_receipt=True,
    )

    assert closed.normalized_receipt_path.name.endswith(
        ".pending-normalized.json"
    )
    assert closed.normalized_receipt_path.is_file()
    assert list(ledger.frontiers_dir.glob("*.normalized.json")) == []


def test_large_file_parser_input_is_streamed_retained_and_replayable(
    tmp_path: Path,
) -> None:
    body = (b"official bulk archive member bytes\n" * 4096) + b"tail"
    source = tmp_path / "official-bundle.zip"
    source.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinBulkParser",
    )

    retained = ledger.retain_parser_input_file(
        official_url=OFFICIAL_ONE,
        source_path=source,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
        retrieved_at="2026-08-24T01:02:03Z",
        media_type="application/zip",
    )

    assert retained.body_path.read_bytes() == body
    assert retained.envelope.body is None
    assert retained.receipt.content is not None
    assert retained.receipt.content.sha256 == digest
    coverage = ledger.audit_parser_output_coverage(
        [
            {
                "source_url": OFFICIAL_TWO,
                "structured_data": {"content_sha256": digest},
            }
        ]
    )
    assert coverage["complete"] is True
    assert coverage["covered_by_content_digest"] == 1

    source.unlink()
    replayed = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinBulkParser",
    )
    assert len(replayed.entries) == 1
    assert replayed.entries[0].receipt.content.sha256 == digest


def test_file_backed_parser_input_replay_is_streaming_and_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (b"large official bundle\n" * 8192) + b"tail"
    source = tmp_path / "official-bundle.zip"
    source.write_bytes(body)
    request = {"method": "GET", "url": OFFICIAL_ONE}
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinBulkParser",
    )
    retained = ledger.retain_parser_input_file(
        official_url=OFFICIAL_ONE,
        source_path=source,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
        retrieved_at="2026-08-24T01:02:03Z",
        media_type="application/zip",
        sanitized_request=request,
    )

    def _read_bytes_must_not_run(_self):
        raise AssertionError("file-backed replay must remain bounded-memory")

    monkeypatch.setattr(Path, "read_bytes", _read_bytes_must_not_run)
    replayed = ledger.replay_retained_parser_input_file(
        official_url=OFFICIAL_ONE,
        sanitized_request=request,
    )
    assert replayed is retained
    assert replayed.envelope.body is None


def test_file_backed_parser_input_replay_rejects_tampered_object(
    tmp_path: Path,
) -> None:
    body = b"original official bundle bytes"
    source = tmp_path / "official-bundle.zip"
    source.write_bytes(body)
    request = {"method": "GET", "url": OFFICIAL_ONE}
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinBulkParser",
    )
    retained = ledger.retain_parser_input_file(
        official_url=OFFICIAL_ONE,
        source_path=source,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
        retrieved_at="2026-08-24T01:02:03Z",
        sanitized_request=request,
    )
    retained.body_path.write_bytes(b"tampered official bundle bytes")

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="failed fixity replay",
    ):
        ledger.replay_retained_parser_input_file(
            official_url=OFFICIAL_ONE,
            sanitized_request=request,
        )


def test_file_backed_parser_input_replay_request_mismatch_returns_none(
    tmp_path: Path,
) -> None:
    body = b"official bundle bytes"
    source = tmp_path / "official-bundle.zip"
    source.write_bytes(body)
    request = {"method": "GET", "url": OFFICIAL_ONE, "variant": "current"}
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinBulkParser",
    )
    ledger.retain_parser_input_file(
        official_url=OFFICIAL_ONE,
        source_path=source,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
        retrieved_at="2026-08-24T01:02:03Z",
        sanitized_request=request,
    )

    assert ledger.replay_retained_parser_input_file(
        official_url=OFFICIAL_ONE,
        sanitized_request={**request, "variant": "prior"},
    ) is None


def test_file_backed_parser_input_replay_rejects_ambiguous_responses(
    tmp_path: Path,
) -> None:
    request = {"method": "GET", "url": OFFICIAL_ONE}
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinBulkParser",
    )
    for index, body in enumerate((b"official bundle v1", b"official bundle v2")):
        source = tmp_path / f"official-bundle-{index}.zip"
        source.write_bytes(body)
        ledger.retain_parser_input_file(
            official_url=OFFICIAL_ONE,
            source_path=source,
            transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
            retrieved_at=f"2026-08-24T01:02:0{index + 3}Z",
            sanitized_request=request,
        )

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="ambiguous for this request",
    ):
        ledger.replay_retained_parser_input_file(
            official_url=OFFICIAL_ONE,
            sanitized_request=request,
        )


def test_frontier_replay_or_canonical_row_drift_fails_closed(
    tmp_path: Path,
) -> None:
    body = b"official response body"
    body_two = b"second official response body"
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    ledger.retain_parser_input(
        official_url=OFFICIAL_ONE,
        body=body,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
        retrieved_at="2026-08-24T01:02:03Z",
    )
    ledger.retain_parser_input(
        official_url=OFFICIAL_TWO,
        body=body_two,
        transport_receipt=_direct_receipt(OFFICIAL_TWO, body_two),
        retrieved_at="2026-08-24T01:02:04Z",
    )
    canonical = tmp_path / "STATE-WI.jsonld"
    canonical.write_bytes(_jsonld_bytes())
    completion = _completion_receipt()
    drifted = dict(completion["frontier"])
    drifted["visited_index_units"] = 1

    with pytest.raises(StateLawMultiFetchAcquisitionError, match="frontiers differ"):
        ledger.close_jurisdiction_frontier(
            completion,
            replayed_frontier=drifted,
            canonical_jsonld_path=canonical,
            release_point=RELEASE_POINT,
            official_source_url=OFFICIAL_START,
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T02:00:00Z",
            source_software_version="state-scraper/verified-multifetch",
        )

    completion["row_count"] = 1
    with pytest.raises(StateLawMultiFetchAcquisitionError, match="row count"):
        ledger.close_jurisdiction_frontier(
            completion,
            replayed_frontier=dict(completion["frontier"]),
            canonical_jsonld_path=canonical,
            release_point=RELEASE_POINT,
            official_source_url=OFFICIAL_START,
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T02:00:00Z",
            source_software_version="state-scraper/verified-multifetch",
        )


def test_unretained_bulk_or_custom_parser_rows_block_aggregate(tmp_path: Path) -> None:
    body = b"retained official index response"
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    ledger.retain_parser_input(
        official_url=OFFICIAL_ONE,
        body=body,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
        retrieved_at="2026-08-24T01:02:03Z",
    )
    canonical = tmp_path / "STATE-WI.jsonld"
    canonical.write_bytes(_jsonld_bytes())
    coverage = ledger.audit_canonical_jsonld_coverage(canonical)

    assert coverage["complete"] is False
    assert coverage["uncovered_unit_count"] == 1
    assert coverage["uncovered_units"][0]["source_url"] == OFFICIAL_TWO

    completion = _completion_receipt()
    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="bypassed the retained parser-input ledger",
    ):
        ledger.close_jurisdiction_frontier(
            completion,
            replayed_frontier=dict(completion["frontier"]),
            canonical_jsonld_path=canonical,
            release_point=RELEASE_POINT,
            official_source_url=OFFICIAL_START,
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T02:00:00Z",
            source_software_version="state-scraper/verified-multifetch",
        )


class _DummyWisconsinScraper(BaseStateScraper):
    def __init__(self) -> None:
        super().__init__("WI", "Wisconsin")

    def get_base_url(self) -> str:
        return OFFICIAL_START

    def get_code_list(self) -> list[dict[str, str]]:
        return []

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
    ) -> list[NormalizedStatute]:
        return []


class _ResponseHeaders(dict):
    def get_content_type(self) -> str:
        return str(self.get("Content-Type") or "application/octet-stream").split(
            ";", 1
        )[0]


class _DirectResponse:
    def __init__(self, body: bytes, *, media_type: str) -> None:
        self.status = 200
        self.headers = _ResponseHeaders({"Content-Type": media_type})
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_custom_post_adapter_retains_exact_bytes_before_returning_to_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    scraper = _DummyWisconsinScraper()
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    request_body = b'{"query":"{ statutes { id } }"}'
    response_body = b'{"data":{"statutes":[{"id":"1.01"}]}}'
    observed_request: dict[str, object] = {}

    async def _no_cache(_url: str) -> bytes:
        return b""

    async def _no_cache_write(**_kwargs) -> None:
        return None

    def _urlopen(request, **_kwargs):
        observed_request["method"] = request.get_method()
        observed_request["body"] = request.data
        return _DirectResponse(response_body, media_type="application/json")

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _no_cache)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache_write)
    monkeypatch.setattr("urllib.request.urlopen", _urlopen)

    parser_input = await scraper._fetch_parser_input_with_transport(
        OFFICIAL_ONE,
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": "must-not-enter-receipt",
            "Content-Type": "application/json",
        },
        request_body=request_body,
        timeout_seconds=2,
        allow_archival_fallback=False,
        media_type="application/json",
        provider="fixture_post",
    )

    assert parser_input == response_body
    assert observed_request == {"method": "POST", "body": request_body}
    assert len(ledger.entries) == 1
    retained = ledger.entries[0]
    assert retained.body_path.read_bytes() == response_body
    assert retained.envelope.body == response_body
    assert retained.transport.transport_chain == ("direct",)
    assert retained.receipt.sanitized_request == {
        "headers": {
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        "method": "POST",
        "request_body_length": len(request_body),
        "request_body_sha256": hashlib.sha256(request_body).hexdigest(),
        "url": OFFICIAL_ONE,
    }
    assert "must-not-enter-receipt" not in retained.evidence_path.read_text(
        encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_custom_post_adapter_replays_exact_retained_request_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _DummyWisconsinScraper()
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    request_body = b'{"query":"query($ids:[ID!]!){nodes(ids:$ids){id}}","variables":{"ids":["1.01"]}}'
    other_request_body = request_body.replace(b'1.01', b'1.02')
    response_body = b'{"data":{"nodes":[{"id":"1.01"}]}}'
    safe_request = {
        "headers": {
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        "method": "POST",
        "request_body_length": len(request_body),
        "request_body_sha256": hashlib.sha256(request_body).hexdigest(),
        "url": OFFICIAL_ONE,
    }
    retained = ledger.retain_parser_input(
        official_url=OFFICIAL_ONE,
        body=response_body,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, response_body),
        retrieved_at="2026-08-24T01:02:03Z",
        media_type="application/json",
        sanitized_request=safe_request,
    )
    scraper.attach_state_law_acquisition_ledger(ledger)

    async def _cache_must_not_run(_url: str) -> bytes:
        raise AssertionError("exact retained response must precede local cache lookup")

    def _network_must_not_run(*_args, **_kwargs):
        raise AssertionError("exact retained response must prevent another request")

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _cache_must_not_run)
    monkeypatch.setattr("urllib.request.urlopen", _network_must_not_run)

    observed = await scraper._fetch_parser_input_with_transport(
        OFFICIAL_ONE,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        request_body=request_body,
        allow_archival_fallback=False,
        media_type="application/json",
    )

    assert observed == response_body
    assert scraper._last_page_parser_input_envelope is retained.envelope
    assert scraper._last_parser_input_row_provenance() == {
        "content_sha256": hashlib.sha256(response_body).hexdigest(),
        "transport_receipt": _direct_receipt(OFFICIAL_ONE, response_body),
    }
    assert len(ledger.entries) == 1
    assert scraper.get_fetch_analytics_snapshot()["providers"][
        "retained_acquisition_replay"
    ] == 1
    assert ledger.replay_retained_parser_input(
        official_url=OFFICIAL_ONE,
        sanitized_request={
            **safe_request,
            "request_body_length": len(other_request_body),
            "request_body_sha256": hashlib.sha256(other_request_body).hexdigest(),
        },
    ) is None


def test_retained_request_replay_fails_closed_when_response_changed(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    request = {"method": "POST", "request_body_sha256": "a" * 64, "url": OFFICIAL_ONE}
    for timestamp, body in (
        ("2026-08-24T01:02:03Z", b'{"data":{"version":1}}'),
        ("2026-08-24T01:02:04Z", b'{"data":{"version":2}}'),
    ):
        ledger.retain_parser_input(
            official_url=OFFICIAL_ONE,
            body=body,
            transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
            retrieved_at=timestamp,
            sanitized_request=request,
        )

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="ambiguous for this request",
    ):
        ledger.replay_retained_parser_input(
            official_url=OFFICIAL_ONE,
            sanitized_request=request,
        )


def test_plural_retained_replay_is_ordered_exact_and_does_not_rescan_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    bodies = {
        OFFICIAL_ONE: b"official one",
        OFFICIAL_TWO: b"official two",
    }
    for url, body in bodies.items():
        ledger.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt=_direct_receipt(url, body),
            retrieved_at="2026-08-24T01:02:03Z",
            sanitized_request={"method": "GET", "url": url},
        )

    class _NoIterationDict(dict[str, object]):
        def __iter__(self):
            raise AssertionError("plural replay rescanned every retained entry")

    ledger._entries = _NoIterationDict(ledger._entries)  # type: ignore[assignment]

    def _network_must_not_run(*_args, **_kwargs):
        raise AssertionError("retained plural replay attempted network I/O")

    monkeypatch.setattr("urllib.request.urlopen", _network_must_not_run)
    replayed = ledger.replay_retained_parser_inputs(
        requests=[
            (OFFICIAL_TWO, {"method": "GET", "url": OFFICIAL_TWO}),
            (OFFICIAL_ONE, {"method": "GET", "url": OFFICIAL_ONE}),
        ]
    )

    assert [row.envelope.body for row in replayed] == [
        bodies[OFFICIAL_TWO],
        bodies[OFFICIAL_ONE],
    ]

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="missing request",
    ):
        ledger.replay_retained_parser_inputs(
            requests=[
                (
                    OFFICIAL_ONE,
                    {"headers": {"Accept": "text/html"}, "method": "GET", "url": OFFICIAL_ONE},
                )
            ]
        )


def test_plural_retained_replay_rejects_ambiguity_and_body_mutation(
    tmp_path: Path,
) -> None:
    ambiguous = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "ambiguous",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    request = {"method": "GET", "url": OFFICIAL_ONE}
    for timestamp, body in (
        ("2026-08-24T01:02:03Z", b"version one"),
        ("2026-08-24T01:02:04Z", b"version two"),
    ):
        ambiguous.retain_parser_input(
            official_url=OFFICIAL_ONE,
            body=body,
            transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
            retrieved_at=timestamp,
            sanitized_request=request,
        )
    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="ambiguous for this request",
    ):
        ambiguous.replay_retained_parser_inputs(
            requests=[(OFFICIAL_ONE, request)]
        )

    mutated = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "mutated",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    retained = mutated.retain_parser_input(
        official_url=OFFICIAL_ONE,
        body=b"immutable body",
        transport_receipt=_direct_receipt(OFFICIAL_ONE, b"immutable body"),
        retrieved_at="2026-08-24T01:02:03Z",
        sanitized_request=request,
    )
    retained.body_path.write_bytes(b"mutated body")
    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="failed fixity verification",
    ):
        mutated.replay_retained_parser_inputs(
            requests=[(OFFICIAL_ONE, request)]
        )


@pytest.mark.asyncio
async def test_stateful_form_adapter_preserves_session_and_hashes_post_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _DummyWisconsinScraper()
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    response_body = b"<html><body>stateful official response</body></html>"
    request_body = b"__VIEWSTATE=abc&__EVENTTARGET=title1"

    class _Session:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.closed = False

        def request(self, **kwargs):
            self.calls.append(dict(kwargs))
            return SimpleNamespace(
                content=response_body,
                headers={"Content-Type": "text/html; charset=utf-8"},
                status_code=200,
                url=OFFICIAL_ONE,
            )

        def close(self) -> None:
            self.closed = True

    raw_session = _Session()
    monkeypatch.setattr("requests.Session", lambda: raw_session)
    session = scraper._new_stateful_parser_input_session(verify_tls=True)

    observed = await scraper._fetch_parser_input_with_transport(
        OFFICIAL_ONE,
        method="POST",
        headers={
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": "must-not-enter-receipt",
        },
        request_body=request_body,
        timeout_seconds=2,
        allow_archival_fallback=False,
        stateful_session=session,
    )
    await scraper._close_stateful_parser_input_session(session)

    assert observed == response_body
    assert len(raw_session.calls) == 1
    assert raw_session.calls[0]["data"] == request_body
    assert raw_session.closed is True
    retained = ledger.entries[0]
    assert retained.transport.transport_chain == ("direct",)
    assert retained.receipt.sanitized_request == {
        "headers": {
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        "method": "POST",
        "request_body_length": len(request_body),
        "request_body_sha256": hashlib.sha256(request_body).hexdigest(),
        "url": OFFICIAL_ONE,
    }
    assert "must-not-enter-receipt" not in retained.evidence_path.read_text(
        encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_browser_render_adapter_admits_exact_dom_and_final_official_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _DummyWisconsinScraper()
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    rendered = "<html><body><a href='/statutes/1'>Chapter 1</a></body></html>"

    class _Page:
        url = OFFICIAL_START

        async def goto(self, url: str, **_kwargs):
            assert url == OFFICIAL_START
            return SimpleNamespace(status=200)

        async def wait_for_selector(self, selector: str, **_kwargs) -> None:
            assert selector == "a"

        async def content(self) -> str:
            return rendered

        async def close(self) -> None:
            return None

    class _Browser:
        async def new_page(self):
            return _Page()

        async def close(self) -> None:
            return None

    class _Chromium:
        async def launch(self, **_kwargs):
            return _Browser()

    class _Playwright:
        chromium = _Chromium()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

    class _Slot:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _Playwright())
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper.acquire_playwright_slot",
        lambda: _Slot(),
    )

    observed = await scraper._fetch_browser_parser_input_with_transport(
        OFFICIAL_START,
        allowed_final_hosts=("docs.legis.wisconsin.gov",),
        pagination={"kind": "rendered_catalog"},
    )

    assert observed == rendered.encode("utf-8")
    retained = ledger.entries[0]
    assert retained.transport.transport_chain == ("browser_rendered",)
    assert retained.receipt.sanitized_request == {
        "browser_final_url": OFFICIAL_START,
        "method": "GET",
        "rendered_by": "playwright",
        "url": OFFICIAL_START,
        "wait_until": "networkidle",
    }
    assert retained.receipt.pagination == {"kind": "rendered_catalog"}


@pytest.mark.asyncio
async def test_custom_adapter_replays_only_cache_with_verified_origin_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    scraper = _DummyWisconsinScraper()
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    body = b"verified synthetic-namespace cache bytes"
    cache_url = f"{OFFICIAL_ONE}?request_sha256={'a' * 64}"

    async def _cached(url: str) -> bytes:
        assert url == cache_url
        scraper._last_page_fetch_transport_evidence = {
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "official_url": cache_url,
            "origin_transport_receipt": _direct_receipt(OFFICIAL_ONE, body),
            "source_transport": "fetch_cache",
        }
        scraper._record_fetch_event(provider="fetch_cache", success=True)
        return body

    def _network_must_not_run(*_args, **_kwargs):
        raise AssertionError("verified cache must be admitted without a network call")

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _cached)
    monkeypatch.setattr("urllib.request.urlopen", _network_must_not_run)

    observed = await scraper._fetch_parser_input_with_transport(
        OFFICIAL_ONE,
        cache_url=cache_url,
        allow_archival_fallback=False,
    )

    assert observed == body
    assert len(ledger.entries) == 1
    assert ledger.entries[0].transport.transport_chain == ("fetch_cache", "direct")
    assert ledger.entries[0].receipt.endpoint == OFFICIAL_ONE


@pytest.mark.asyncio
async def test_custom_adapter_does_not_admit_cache_without_origin_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    scraper = _DummyWisconsinScraper()
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    body = b"legacy cache body with no origin evidence"

    async def _unbound_cache(_url: str) -> bytes:
        scraper._last_page_fetch_transport_evidence = {}
        scraper._record_fetch_event(provider="fetch_cache", success=True)
        return body

    def _offline(*_args, **_kwargs):
        raise OSError("offline fixture")

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _unbound_cache)
    monkeypatch.setattr("urllib.request.urlopen", _offline)

    observed = await scraper._fetch_parser_input_with_transport(
        OFFICIAL_ONE,
        timeout_seconds=1,
        allow_archival_fallback=False,
    )

    assert observed == b""
    assert ledger.entries == ()
    analytics = scraper.get_fetch_analytics_snapshot()
    assert analytics["providers"]["cache_provenance_rejected"] == 1


@pytest.mark.asyncio
async def test_custom_get_adapter_reuses_verified_shared_archive_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        state_archival_fetch,
    )
    from ipfs_datasets_py.processors.web_archiving.wayback_machine_engine import (
        _wayback_inventory_query_url,
    )

    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    monkeypatch.setenv("STATE_SCRAPER_DIRECT_FIRST", "0")
    monkeypatch.setenv("STATE_SCRAPER_UNIFIED_FETCH_ENABLED", "0")
    monkeypatch.setenv("STATE_SCRAPER_ARCHIVAL_FETCH_ENABLED", "1")
    scraper = _DummyWisconsinScraper()
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    body = b"official statute bytes recovered from an immutable snapshot"
    stamp = "20260824010203"
    cdx_query, _variant_count = _wayback_inventory_query_url(
        OFFICIAL_ONE,
        limit=100,
        exact_originals=[OFFICIAL_ONE],
    )

    async def _no_cache(_url: str) -> bytes:
        return b""

    async def _no_cache_write(**_kwargs) -> None:
        return None

    def _offline(*_args, **_kwargs):
        raise OSError("official endpoint unavailable")

    class _ArchiveClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def fetch_with_fallback(self, url: str):
            assert url == OFFICIAL_ONE
            return SimpleNamespace(
                archive_timestamp=stamp,
                archive_url=f"https://web.archive.org/web/{stamp}id_/{url}",
                content=body,
                fetched_at="2026-08-24T01:02:03Z",
                source="wayback",
                wayback_cdx_query_url=cdx_query,
                wayback_cdx_response_sha256="a" * 64,
                wayback_cdx_fetched_at="2026-08-24T01:02:02+00:00",
            )

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _no_cache)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache_write)
    monkeypatch.setattr("urllib.request.urlopen", _offline)
    monkeypatch.setattr(state_archival_fetch, "ArchivalFetchClient", _ArchiveClient)

    observed = await scraper._fetch_parser_input_with_transport(
        OFFICIAL_ONE,
        timeout_seconds=6,
        allow_archival_fallback=True,
    )

    assert observed == body
    assert len(ledger.entries) == 1
    retained = ledger.entries[0]
    assert retained.body_path.read_bytes() == body
    assert retained.transport.transport_chain == ("wayback",)
    assert retained.transport.archive_timestamp == stamp


@pytest.mark.asyncio
async def test_base_shared_fetch_hook_admits_valid_cache_before_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    monkeypatch.setenv("STATE_SCRAPER_DIRECT_FIRST", "0")
    monkeypatch.setenv("STATE_SCRAPER_UNIFIED_FETCH_ENABLED", "0")
    monkeypatch.setenv("STATE_SCRAPER_ARCHIVAL_FETCH_ENABLED", "0")
    scraper = _DummyWisconsinScraper()
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    body = b"verified cached official statute bytes"

    async def _cached(url: str) -> bytes:
        scraper._last_page_fetch_transport_evidence = _cache_receipt(url, body)
        scraper._record_fetch_event(provider="fetch_cache", success=True)
        return body

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _cached)
    observed = await scraper._fetch_page_content_with_archival_fallback(
        OFFICIAL_ONE,
        timeout_seconds=2,
    )

    assert observed == body
    assert len(ledger.entries) == 1
    assert scraper._last_page_parser_input_envelope is ledger.entries[0].envelope
    assert ledger.entries[0].transport.transport_chain == ("fetch_cache", "direct")


@pytest.mark.asyncio
async def test_single_page_fetch_replays_prospective_ledger_before_cache_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    body = b"retained official discovery page"
    first_ledger = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    retained = first_ledger.retain_parser_input(
        official_url=OFFICIAL_ONE,
        body=body,
        transport_receipt=_direct_receipt(OFFICIAL_ONE, body),
        sanitized_request={"method": "GET", "url": OFFICIAL_ONE},
    )

    scraper = _DummyWisconsinScraper()
    replay_ledger = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    scraper.attach_state_law_acquisition_ledger(replay_ledger)

    async def _unexpected_cache(_url: str) -> bytes:
        raise AssertionError("page cache must not run before exact ledger replay")

    async def _unexpected_unified(*_args, **_kwargs) -> bytes:
        raise AssertionError("network fallback must not run after exact ledger replay")

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _unexpected_cache)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_unified_api",
        _unexpected_unified,
    )
    observed = await scraper._fetch_page_content_with_archival_fallback(
        OFFICIAL_ONE,
        timeout_seconds=6,
        content_validator=lambda payload: payload == body,
    )

    assert observed == body
    assert len(replay_ledger.entries) == 1
    assert scraper._last_page_parser_input_envelope is replay_ledger.entries[0].envelope
    assert scraper._last_page_fetch_transport_evidence == dict(
        replay_ledger.entries[0].transport_receipt
    )
    assert replay_ledger.entries[0].receipt.receipt_sha256 == retained.receipt.receipt_sha256
    assert scraper.get_fetch_analytics_snapshot()["providers"] == {
        "retained_acquisition_replay": 1
    }


def test_old_checkpoint_and_rematerialization_claims_remain_nonauthorizing() -> None:
    assert AUTHORIZES_LEGACY_CHECKPOINTS is False
    assert AUTHORIZES_REMATERIALIZATION_RECEIPTS is False


def test_default_frontier_software_identity_is_a_shared_loaded_code_bundle() -> None:
    scraper = _DummyWisconsinScraper()
    qualified_name = f"{type(scraper).__module__}.{type(scraper).__qualname__}"
    identity = scraper._state_law_frontier_source_software_version()

    assert identity.startswith(f"{qualified_name}@sha256:")
    assert len(identity.rsplit("@sha256:", 1)[1]) == 64


def test_frontier_software_identity_binds_loaded_class_not_only_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _DummyWisconsinScraper()
    baseline = scraper._state_law_frontier_source_software_version()

    monkeypatch.setattr(
        type(scraper),
        "get_base_url",
        lambda self: "https://loaded-code-change.example.test",
    )

    assert scraper._state_law_frontier_source_software_version() != baseline


def test_base_exposes_fail_closed_frontier_projection_producer_api(
    tmp_path: Path,
) -> None:
    scraper = _DummyWisconsinScraper()
    completion = _completion_receipt()
    replayed = dict(completion["frontier"])

    with pytest.raises(RuntimeError, match="attached acquisition ledger"):
        scraper.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=replayed,
            release_point=RELEASE_POINT,
            official_source_url=OFFICIAL_START,
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T02:00:00Z",
            source_software_version="state-scraper/verified-multifetch",
        )

    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    closure_path = scraper.retain_state_law_frontier_closure_projection(
        completion,
        replayed_frontier=replayed,
        release_point=RELEASE_POINT,
        official_source_url=OFFICIAL_START,
        acquisition_path_ids=["wi-docs-statutes"],
        observation_time="2026-08-24T02:00:00Z",
        source_software_version="state-scraper/verified-multifetch",
    )

    assert closure_path.parent == ledger.closure_inputs_dir
    assert closure_path.name == (
        hashlib.sha256(closure_path.read_bytes()).hexdigest() + ".json"
    )
    assert not ledger.closure_input_path.exists()
    assert closure_path.is_file()
    retained = json.loads(closure_path.read_text(encoding="utf-8"))
    assert retained["completion_receipt"]["jurisdiction"] == "WI"
    assert retained["replayed_frontier"] == replayed

    drifted = dict(replayed)
    drifted["visited_index_units"] = 1
    with pytest.raises(StateLawMultiFetchAcquisitionError, match="frontiers differ"):
        scraper.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=drifted,
            release_point=RELEASE_POINT,
            official_source_url=OFFICIAL_START,
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T02:00:00Z",
            source_software_version="state-scraper/verified-multifetch",
        )


def test_frontier_projection_retains_one_key_list_plus_compact_output_binding(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    completion = _completion_receipt()
    rows = [
        {
            "state_code": "WI",
            "statute_id": "WI-1.01",
            "structured_data": {
                "jsonld": {"@id": "urn:state:wi:statute:1.01"}
            },
        },
        {
            "state_code": "WI",
            "statute_id": "WI-1.02",
            "structured_data": {
                "jsonld": {"@id": "urn:state:wi:statute:1.02"}
            },
        },
    ]
    output_projection = build_canonical_state_law_output_projection(
        rows,
        jurisdiction="WI",
    )

    closure_path = ledger.retain_frontier_closure_projection(
        completion,
        replayed_frontier=dict(completion["frontier"]),
        canonical_output_projection=output_projection,
        release_point=RELEASE_POINT,
        official_source_url=OFFICIAL_START,
        acquisition_path_ids=["wi-docs-statutes"],
        observation_time="2026-08-24T02:00:00Z",
        source_software_version="state-scraper/verified-multifetch",
    )

    retained = json.loads(closure_path.read_text(encoding="utf-8"))
    binding = retained["canonical_output_binding"]
    assert "canonical_keys" not in binding
    assert binding["canonical_row_count"] == 2
    assert binding["canonical_keys_sha256"] == output_projection[
        "canonical_keys_sha256"
    ]
    assert retained["completion_receipt"]["index_keys"]["canonical_keys"] == [
        "urn:state:wi:statute:1.01",
        "urn:state:wi:statute:1.02",
    ]
    assert ledger.verify_retained_frontier_closure_projection(
        output_projection,
        closure_input_path=closure_path,
    ) == binding


def test_closure_generations_are_idempotent_and_coexist(tmp_path: Path) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    completion = _completion_receipt()
    projection = build_canonical_state_law_output_projection(
        [
            {
                "state_code": "WI",
                "statute_id": "WI-1.01",
                "structured_data": {
                    "jsonld": {"@id": "urn:state:wi:statute:1.01"}
                },
            },
            {
                "state_code": "WI",
                "statute_id": "WI-1.02",
                "structured_data": {
                    "jsonld": {"@id": "urn:state:wi:statute:1.02"}
                },
            },
        ],
        jurisdiction="WI",
    )

    def _retain(version: str) -> Path:
        return ledger.retain_frontier_closure_projection(
            completion,
            replayed_frontier=dict(completion["frontier"]),
            canonical_output_projection=projection,
            release_point=RELEASE_POINT,
            official_source_url=OFFICIAL_START,
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T02:00:00Z",
            source_software_version=version,
        )

    first = _retain("state-scraper/generation-1")
    first_bytes = first.read_bytes()
    assert _retain("state-scraper/generation-1") == first
    assert first.read_bytes() == first_bytes

    second = _retain("state-scraper/generation-2")
    assert second != first
    assert first.is_file() and second.is_file()
    assert sorted(ledger.closure_inputs_dir.glob("*.json")) == sorted(
        [first, second]
    )
    for closure_path in (first, second):
        assert ledger.verify_retained_frontier_closure_projection(
            projection,
            closure_input_path=closure_path,
        )["canonical_row_count"] == 2


def test_closure_path_handoff_is_explicit_confined_and_hash_verified(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    completion = _completion_receipt()
    projection = build_canonical_state_law_output_projection(
        [
            {
                "state_code": "WI",
                "statute_id": "WI-1.01",
                "structured_data": {
                    "jsonld": {"@id": "urn:state:wi:statute:1.01"}
                },
            },
            {
                "state_code": "WI",
                "statute_id": "WI-1.02",
                "structured_data": {
                    "jsonld": {"@id": "urn:state:wi:statute:1.02"}
                },
            },
        ],
        jurisdiction="WI",
    )
    closure_path = ledger.retain_frontier_closure_projection(
        completion,
        replayed_frontier=dict(completion["frontier"]),
        canonical_output_projection=projection,
        release_point=RELEASE_POINT,
        official_source_url=OFFICIAL_START,
        acquisition_path_ids=["wi-docs-statutes"],
        observation_time="2026-08-24T02:00:00Z",
        source_software_version="state-scraper/verified-multifetch",
    )

    with pytest.raises(StateLawMultiFetchAcquisitionError, match="explicit"):
        ledger.verify_retained_frontier_closure_projection(projection)

    outside = tmp_path / closure_path.name
    outside.write_bytes(closure_path.read_bytes())
    with pytest.raises(StateLawMultiFetchAcquisitionError, match="escaped"):
        ledger.verify_retained_frontier_closure_projection(
            projection,
            closure_input_path=outside,
        )

    forged = ledger.closure_inputs_dir / ("0" * 64 + ".json")
    forged.write_bytes(closure_path.read_bytes())
    with pytest.raises(StateLawMultiFetchAcquisitionError, match="filename"):
        ledger.verify_retained_frontier_closure_projection(
            projection,
            closure_input_path=forged,
        )

    linked = ledger.closure_inputs_dir / ("1" * 64 + ".json")
    linked.symlink_to(closure_path.name)
    with pytest.raises(StateLawMultiFetchAcquisitionError, match="symlink"):
        ledger.verify_retained_frontier_closure_projection(
            projection,
            closure_input_path=linked,
        )

    linked_ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "linked-evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    outside_directory = tmp_path / "outside-closure-inputs"
    outside_directory.mkdir()
    linked_ledger.closure_inputs_dir.symlink_to(
        outside_directory,
        target_is_directory=True,
    )
    with pytest.raises(StateLawMultiFetchAcquisitionError, match="symlink"):
        linked_ledger.retain_frontier_closure_projection(
            completion,
            replayed_frontier=dict(completion["frontier"]),
            canonical_output_projection=projection,
            release_point=RELEASE_POINT,
            official_source_url=OFFICIAL_START,
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T02:00:00Z",
            source_software_version="state-scraper/verified-multifetch",
        )


def test_legacy_singleton_requires_explicit_opt_in(tmp_path: Path) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    completion = _completion_receipt()
    projection = build_canonical_state_law_output_projection(
        [
            {
                "state_code": "WI",
                "statute_id": "WI-1.01",
                "structured_data": {
                    "jsonld": {"@id": "urn:state:wi:statute:1.01"}
                },
            },
            {
                "state_code": "WI",
                "statute_id": "WI-1.02",
                "structured_data": {
                    "jsonld": {"@id": "urn:state:wi:statute:1.02"}
                },
            },
        ],
        jurisdiction="WI",
    )
    legacy = ledger.retain_frontier_closure_projection(
        completion,
        replayed_frontier=dict(completion["frontier"]),
        canonical_output_projection=projection,
        release_point=RELEASE_POINT,
        official_source_url=OFFICIAL_START,
        acquisition_path_ids=["wi-docs-statutes"],
        observation_time="2026-08-24T02:00:00Z",
        source_software_version="state-scraper/legacy",
        legacy_singleton=True,
    )
    assert legacy == ledger.closure_input_path

    with pytest.raises(StateLawMultiFetchAcquisitionError, match="opt-in"):
        ledger.verify_retained_frontier_closure_projection(
            projection,
            closure_input_path=legacy,
        )
    assert ledger.verify_retained_frontier_closure_projection(
        projection,
        closure_input_path=legacy,
        allow_legacy_singleton=True,
    )["canonical_row_count"] == 2


def test_materialized_jsonld_identity_drift_rejects_retained_output_binding(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinStatuteParser",
    )
    completion = _completion_receipt()
    output_projection = build_canonical_state_law_output_projection(
        [
            {
                "state_code": "WI",
                "statute_id": "WI-1.01",
                "structured_data": {
                    "jsonld": {"@id": "urn:state:wi:statute:1.01"}
                },
            },
            {
                "state_code": "WI",
                "statute_id": "WI-1.02",
                "structured_data": {
                    "jsonld": {"@id": "urn:state:wi:statute:1.02"}
                },
            },
        ],
        jurisdiction="WI",
    )
    closure_path = ledger.retain_frontier_closure_projection(
        completion,
        replayed_frontier=dict(completion["frontier"]),
        canonical_output_projection=output_projection,
        release_point=RELEASE_POINT,
        official_source_url=OFFICIAL_START,
        acquisition_path_ids=["wi-docs-statutes"],
        observation_time="2026-08-24T02:00:00Z",
        source_software_version="state-scraper/verified-multifetch",
    )
    drifted = _jsonld_bytes().replace(
        b"urn:state:wi:statute:1.02",
        b"urn:state:wi:statute:9.99",
    )
    canonical_path = tmp_path / "STATE-WI.jsonld"
    canonical_path.write_bytes(drifted)

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="identities differ",
    ):
        ledger.close_from_projection_file(
            closure_path,
            canonical_jsonld_path=canonical_path,
        )


@pytest.mark.asyncio
async def test_inherited_common_crawl_recovery_reuses_archive_bridge_and_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        state_archival_fetch,
    )
    from ipfs_datasets_py.processors.web_archiving import (
        common_crawl_integration,
    )

    source_url = "https://billstatus.ls.state.ms.us/code/section-1.html"
    terminal = "END-OF-EXACT-ARCHIVED-STATUTE"
    body = (
        "<html><body><main>Mississippi Code section 1. "
        + ("legal text " * 9000)
        + terminal
        + "</main></body></html>"
    ).encode("utf-8")
    record = {
        "collection": "CC-MAIN-2026-30",
        "domain": "billstatus.ls.state.ms.us",
        "mime": "text/html",
        "timestamp": "20260824000000",
        "url": source_url,
        "warc_filename": "crawl-data/CC-MAIN-2026-30/example.warc.gz",
        "warc_length": 1234,
        "warc_offset": 5678,
    }

    class _Engine:
        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr(
        common_crawl_integration,
        "CommonCrawlSearchEngine",
        _Engine,
    )

    def _shared_fetch(self, requests, *, engine, **_kwargs):
        assert isinstance(self, state_archival_fetch.ArchivalFetchClient)
        assert requests == [(source_url, record)]
        assert isinstance(engine, _Engine)
        return state_archival_fetch.CommonCrawlBatchFetchResult(
            results=[
                state_archival_fetch.FetchResult(
                    url=source_url,
                    content=body,
                    source="common_crawl",
                    fetched_at="2026-08-24T08:00:00+00:00",
                    status_code=200,
                    archive_url=(
                        "https://data.commoncrawl.org/"
                        "crawl-data/CC-MAIN-2026-30/example.warc.gz"
                    ),
                    archive_timestamp="20260824000000",
                    common_crawl_collection="CC-MAIN-2026-30",
                    common_crawl_indexed_url=source_url,
                    common_crawl_warc_filename=record["warc_filename"],
                    common_crawl_warc_length=1234,
                    common_crawl_warc_offset=5678,
                    content_sha256=hashlib.sha256(body).hexdigest(),
                )
            ],
            stats={"range_fetch_calls": 1, "warc_objects": 1},
        )

    monkeypatch.setattr(
        state_archival_fetch.ArchivalFetchClient,
        "fetch_common_crawl_records",
        _shared_fetch,
    )
    scraper = _DummyWisconsinScraper()

    async def _records(**_kwargs):
        return [record]

    monkeypatch.setattr(scraper, "_search_state_common_crawl_records", _records)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name=type(scraper).__name__,
    )
    scraper.attach_state_law_acquisition_ledger(ledger)

    candidates = await scraper._scrape_state_common_crawl_candidates(
        max_results=1,
    )

    assert len(candidates) == 1
    assert terminal in candidates[0]["text"]
    assert candidates[0]["content_sha256"] == hashlib.sha256(body).hexdigest()
    assert len(ledger.entries) == 1
    assert ledger.entries[0].receipt.endpoint == source_url
    assert ledger.entries[0].transport.leaf_transport == "common_crawl"
    assert scraper._last_common_crawl_batch_stats["range_fetch_calls"] == 1

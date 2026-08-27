from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    RetainedEvidenceSeedSource,
    StateLawsRetainedEvidenceSeedError,
    seed_retained_evidence_generation,
    seed_retained_evidence_union,
)
from ipfs_datasets_py.processors.web_archiving.wayback_machine_engine import (
    _wayback_inventory_query_url,
)

DIRECT_ONE = "https://law.example.gov/code/section-1"
ARCHIVED_TWO = "https://law.example.gov/code/section-2"
DIRECT_THREE = "https://law.example.gov/code/section-3"


def _direct_receipt(url: str, body: bytes) -> dict[str, str]:
    return {
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "official_url": url,
        "source_transport": "direct",
    }


def _wayback_receipt(url: str, body: bytes) -> dict[str, str]:
    timestamp = "20260102030405"
    query_url, _variant_count = _wayback_inventory_query_url(
        url,
        limit=100,
        exact_originals=[url],
    )
    return {
        "archive_timestamp": timestamp,
        "archive_url": (
            f"https://web.archive.org/web/{timestamp}id_/{url}"
        ),
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "official_url": url,
        "source_transport": "wayback",
        "wayback_cdx_fetched_at": "2026-08-26T00:59:59+00:00",
        "wayback_cdx_query_url": query_url,
        "wayback_cdx_response_sha256": "a" * 64,
    }


def _source_ledger(tmp_path: Path) -> StateLawMultiFetchAcquisitionLedger:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "source",
        jurisdiction="VA",
        parser_name="VirginiaScraper",
    )
    direct_body = b"current direct public-law body"
    ledger.retain_parser_input(
        official_url=DIRECT_ONE,
        body=direct_body,
        transport_receipt=_direct_receipt(DIRECT_ONE, direct_body),
        retrieved_at="2026-08-26T01:00:00Z",
    )
    # Same exact request/body observed twice: the fresh generation needs only
    # one byte-equivalent receipt.
    ledger.retain_parser_input(
        official_url=DIRECT_ONE,
        body=direct_body,
        transport_receipt=_direct_receipt(DIRECT_ONE, direct_body),
        retrieved_at="2026-08-26T01:00:01Z",
    )
    archive_body = b"older archive body excluded from the direct-current seed"
    ledger.retain_parser_input(
        official_url=ARCHIVED_TWO,
        body=archive_body,
        transport_receipt=_wayback_receipt(ARCHIVED_TWO, archive_body),
        retrieved_at="2026-08-26T01:00:02Z",
    )
    second_direct_body = b"another current direct public-law body"
    ledger.retain_parser_input(
        official_url=DIRECT_THREE,
        body=second_direct_body,
        transport_receipt=_direct_receipt(DIRECT_THREE, second_direct_body),
        retrieved_at="2026-08-26T01:00:03Z",
    )
    return ledger


def test_seed_direct_inputs_deduplicates_and_replays_without_copying_bytes(
    tmp_path: Path,
) -> None:
    source = _source_ledger(tmp_path)
    destination = tmp_path / "destination"

    report = seed_retained_evidence_generation(
        source_root=tmp_path / "source",
        destination_root=destination,
        jurisdiction="VA",
        parser_name="VirginiaScraper",
    )

    assert report.selected_parser_input_count == 2
    assert report.duplicate_request_observations_avoided == 1
    assert report.unique_content_object_count == 2
    assert report.hardlinked_file_count == 4
    assert report.copied_file_count == 0
    assert report.network_io_performed is False

    replay = StateLawMultiFetchAcquisitionLedger(
        destination,
        jurisdiction="VA",
        parser_name="VirginiaScraper",
    )
    assert len(replay.entries) == 2
    direct_one = next(
        entry for entry in replay.entries if entry.receipt.endpoint == DIRECT_ONE
    )
    assert all(
        entry.transport_receipt["source_transport"] == "direct"
        for entry in replay.entries
    )
    assert direct_one.body_path.stat().st_ino in {
        entry.body_path.stat().st_ino
        for entry in source.entries
        if entry.receipt.endpoint == DIRECT_ONE
    }

    migration_path = Path(report.migration_receipt_path)
    migration = json.loads(migration_path.read_text())
    assert migration["authorizes_parser_admission"] is False
    assert migration["network_io_performed"] is False
    assert migration["selected_projection_sha256"] == (
        report.selected_projection_sha256
    )
    assert not (destination / "VA" / "frontiers" / "receipt.json").exists()


def test_seed_can_require_an_exact_url_subset(tmp_path: Path) -> None:
    _source_ledger(tmp_path)

    report = seed_retained_evidence_generation(
        source_root=tmp_path / "source",
        destination_root=tmp_path / "destination",
        jurisdiction="VA",
        parser_name="VirginiaScraper",
        allowed_source_transports=("wayback",),
        include_urls=(ARCHIVED_TWO,),
    )

    assert report.requested_url_count == 1
    replay = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "destination",
        jurisdiction="VA",
        parser_name="VirginiaScraper",
    )
    assert [entry.receipt.endpoint for entry in replay.entries] == [ARCHIVED_TWO]


def test_seed_rejects_disagreeing_bodies_for_one_allowed_request(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "source",
        jurisdiction="VA",
        parser_name="VirginiaScraper",
    )
    for index, body in enumerate((b"first direct body", b"changed direct body")):
        ledger.retain_parser_input(
            official_url=DIRECT_ONE,
            body=body,
            transport_receipt=_direct_receipt(DIRECT_ONE, body),
            retrieved_at=f"2026-08-26T01:00:0{index}Z",
        )

    with pytest.raises(
        StateLawsRetainedEvidenceSeedError,
        match="disagree for one exact request",
    ):
        seed_retained_evidence_generation(
            source_root=tmp_path / "source",
            destination_root=tmp_path / "destination",
            jurisdiction="VA",
            parser_name="VirginiaScraper",
        )
    assert not (tmp_path / "destination" / "VA").exists()


def test_seed_requires_fresh_destination_and_complete_requested_urls(
    tmp_path: Path,
) -> None:
    _source_ledger(tmp_path)
    destination = tmp_path / "destination"

    with pytest.raises(
        StateLawsRetainedEvidenceSeedError,
        match="requested retained URLs are absent",
    ):
        seed_retained_evidence_generation(
            source_root=tmp_path / "source",
            destination_root=destination,
            jurisdiction="VA",
            parser_name="VirginiaScraper",
            include_urls=("https://law.example.gov/code/missing",),
        )

    (destination / "VA").mkdir(parents=True)
    with pytest.raises(
        StateLawsRetainedEvidenceSeedError,
        match="must be absent",
    ):
        seed_retained_evidence_generation(
            source_root=tmp_path / "source",
            destination_root=destination,
            jurisdiction="VA",
            parser_name="VirginiaScraper",
        )


def test_multi_source_seed_rebinds_exact_selected_proof_only(
    tmp_path: Path,
) -> None:
    primary = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "primary",
        jurisdiction="NY",
        parser_name="NewYorkScraper",
    )
    primary_urls = (
        "https://www.nysenate.gov/legislation/laws/CONSOLIDATED",
        "https://legislation.nysenate.gov/pdf/laws/AGM?full=true",
    )
    for index, url in enumerate(primary_urls):
        body = f"primary retained body {index}".encode()
        primary.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt=_direct_receipt(url, body),
            retrieved_at=f"2026-08-26T01:00:0{index}Z",
            sanitized_request={"method": "GET", "url": url},
        )

    proof_url = "https://agriculture.ny.gov/reports/exact-proof.pdf"
    unrelated_url = "https://agriculture.ny.gov/search/reports"
    proof = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "proof",
        jurisdiction="NY",
        parser_name="NewYorkAGM28LifecycleSelector",
    )
    for index, url in enumerate((proof_url, unrelated_url), start=2):
        body = f"archived proof body {index}".encode()
        proof.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt=_wayback_receipt(url, body),
            retrieved_at=f"2026-08-26T01:00:0{index}Z",
            sanitized_request={
                "headers": {"Accept": "application/pdf,*/*;q=0.8"},
                "method": "GET",
                "url": url,
            },
        )

    source_receipt_ids = {
        entry.receipt.endpoint: entry.receipt.receipt_sha256
        for ledger in (primary, proof)
        for entry in ledger.entries
    }
    destination = tmp_path / "union"
    report = seed_retained_evidence_union(
        sources=(
            RetainedEvidenceSeedSource(
                source_root=tmp_path / "primary",
                parser_name="NewYorkScraper",
                allowed_source_transports=("direct",),
            ),
            RetainedEvidenceSeedSource(
                source_root=tmp_path / "proof",
                parser_name="NewYorkAGM28LifecycleSelector",
                allowed_source_transports=("wayback",),
                include_urls=(proof_url,),
            ),
        ),
        destination_root=destination,
        jurisdiction="NY",
        parser_name="NewYorkScraper",
    )

    assert report.selected_parser_input_count == 3
    assert report.unique_content_object_count == 3
    assert report.hardlinked_file_count == 3
    assert report.copied_file_count == 0
    assert report.rebound_parser_input_count == 3
    assert report.network_io_performed is False
    replay = StateLawMultiFetchAcquisitionLedger(
        destination,
        jurisdiction="NY",
        parser_name="NewYorkScraper",
        retained_replay_only=True,
    )
    assert {entry.receipt.endpoint for entry in replay.entries} == {
        *primary_urls,
        proof_url,
    }
    assert unrelated_url not in {entry.receipt.endpoint for entry in replay.entries}
    assert all(
        entry.envelope.parser_name == "NewYorkScraper"
        for entry in replay.entries
    )
    assert {
        entry.receipt.endpoint: entry.receipt.receipt_sha256
        for entry in replay.entries
    } == {
        url: source_receipt_ids[url] for url in (*primary_urls, proof_url)
    }
    replayed = [
        replay.replay_retained_parser_input(
            official_url=entry.receipt.endpoint,
            sanitized_request=entry.receipt.sanitized_request,
        )
        for entry in replay.entries
    ]
    assert all(item is not None for item in replayed)
    assert all(item.envelope.body for item in replayed if item is not None)
    migration = json.loads(Path(report.migration_receipt_path).read_text())
    assert migration["network_io_performed"] is False
    assert [row["selected_parser_input_count"] for row in migration["sources"]] == [
        2,
        1,
    ]


def test_multi_source_seed_rejects_cross_source_request_conflict(
    tmp_path: Path,
) -> None:
    url = "https://law.example.gov/code/conflict"
    sources = []
    for index, body in enumerate((b"first body", b"conflicting body")):
        root = tmp_path / f"source-{index}"
        ledger = StateLawMultiFetchAcquisitionLedger(
            root,
            jurisdiction="NY",
            parser_name=f"ProofParser{index}",
        )
        ledger.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt=_direct_receipt(url, body),
            retrieved_at=f"2026-08-26T01:00:0{index}Z",
            sanitized_request={"method": "GET", "url": url},
        )
        sources.append(
            RetainedEvidenceSeedSource(
                source_root=root,
                parser_name=f"ProofParser{index}",
                allowed_source_transports=("direct",),
            )
        )

    with pytest.raises(
        StateLawsRetainedEvidenceSeedError,
        match="disagree for one exact request",
    ):
        seed_retained_evidence_union(
            sources=sources,
            destination_root=tmp_path / "union",
            jurisdiction="NY",
            parser_name="NewYorkScraper",
        )
    assert not (tmp_path / "union" / "NY").exists()

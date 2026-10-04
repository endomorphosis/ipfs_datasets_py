"""CRYPTOIR-G410 primary-source OFAC SDN ingestion evidence."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from ipfs_datasets_py.processors.compliance import (
    AppendOnlySnapshotJournal,
    OFACIngestionError,
    OFACSDNParser,
    PublishedHashEvidence,
    SanctionsSnapshotValidator,
    SignatureEvidence,
    SnapshotEvidenceStatus,
)
from ipfs_datasets_py.processors.compliance.sanctions import OFAC_SDN_XML_URL

NOW = "2026-07-29T12:00:00Z"
PUBLISHED = "2026-07-29T00:00:00Z"
ETH_ADDRESS = "0x1234567890abcdef1234567890ABCDEF12345678"
BTC_ADDRESS = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"


def _entry(
    uid: int,
    *,
    name: str | None = None,
    identifiers: tuple[tuple[str, str], ...] = (),
) -> str:
    ids = "".join(
        (
            f"<id><uid>{uid}{index}</uid>"
            f"<idType>Digital Currency Address - {symbol}</idType>"
            f"<idNumber>{address}</idNumber></id>"
        )
        for index, (symbol, address) in enumerate(identifiers, start=1)
    )
    return (
        f"<sdnEntry><uid>{uid}</uid><firstName>Fixture</firstName>"
        f"<lastName>{name or f'Party {uid}'}</lastName>"
        "<programList><program>SDGT</program></programList>"
        f"<idList>{ids}</idList>"
        "<akaList><aka><uid>9</uid><firstName>Alias</firstName>"
        f"<lastName>{uid}</lastName></aka></akaList></sdnEntry>"
    )


def _xml(
    *entries: str,
    declared_count: int | None = None,
    publish_date: str = "07/29/2026",
) -> bytes:
    count = len(entries) if declared_count is None else declared_count
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sdnList xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML">'
        f"<publshInformation><Publish_Date>{publish_date}</Publish_Date>"
        f"<Record_Count>{count}</Record_Count></publshInformation>"
        + "".join(entries)
        + "</sdnList>"
    ).encode()


def _parse(
    raw: bytes,
    *,
    published_at: str = PUBLISHED,
    effective_at: str = PUBLISHED,
    retrieved_at: str = "2026-07-29T00:05:00Z",
    previous=None,
):
    return OFACSDNParser().parse(
        raw,
        source_url=OFAC_SDN_XML_URL,
        retrieved_at=retrieved_at,
        published_at=published_at,
        effective_at=effective_at,
        previous=previous,
    )


def test_import_binds_untouched_bytes_metadata_hash_signature_parser_counts_and_cid():
    raw = _xml(
        _entry(1, identifiers=(("ETH", ETH_ADDRESS), ("XBT", BTC_ADDRESS))),
        _entry(2),
    )
    digest = hashlib.sha256(raw).hexdigest()
    signature = SignatureEvidence(
        scheme="fixture-detached",
        value=b"offline signature fixture",
        source="fixture/signature",
    )
    record = OFACSDNParser().parse(
        raw,
        source_url=OFAC_SDN_XML_URL,
        transport="offline_fixture",
        retrieved_at="2026-07-29T00:05:00Z",
        published_at=PUBLISHED,
        effective_at=PUBLISHED,
        transport_metadata={"fixture": "historical-2026-07-29"},
        published_hashes=(
            PublishedHashEvidence(
                algorithm="sha-256",
                value=digest,
                source="fixture/hash",
                verified=True,
            ),
        ),
        signatures=(signature,),
    )

    assert record.source.raw_bytes is raw
    assert record.source.content_sha256 == f"sha256:{digest}"
    assert record.source.cid.startswith("bafkrei")
    assert record.snapshot_cid == record.source.cid
    assert record.source.transport_metadata["fixture"] == "historical-2026-07-29"
    assert record.source.published_hashes[0].verified
    assert record.source.signatures == (signature,)
    assert record.parser_identity == "ipfs-datasets.ofac-sdn-xml"
    assert record.parser_version == "1.0.0"
    assert record.schema_identity.startswith("ofac:sdnList:")
    assert record.declared_entry_count == record.parsed_entry_count == 2
    assert record.digital_identifier_count == 2
    assert record.snapshot is not None
    assert record.snapshot.content_digest == record.source.content_sha256

    extracted = OFACSDNParser().parse(
        raw,
        source_url=OFAC_SDN_XML_URL,
        retrieved_at="2026-07-29T00:05:00Z",
    )
    assert extracted.source.published_at == PUBLISHED
    assert extracted.source.effective_at == PUBLISHED


def test_identifiers_are_chain_qualified_and_never_cross_network_coerced():
    record = _parse(
        _xml(
            _entry(
                1,
                identifiers=(("ETH", ETH_ADDRESS), ("BTC", BTC_ADDRESS)),
            )
        )
    )
    assert record.snapshot is not None
    eth, bitcoin = record.snapshot.designations[0].identifiers
    assert eth.comparison_key == (
        "eip155",
        "ethereum-mainnet",
        ETH_ADDRESS.lower(),
        "eth",
    )
    assert bitcoin.comparison_key == (
        "bip122",
        "bitcoin-mainnet",
        BTC_ADDRESS,
        "btc",
    )
    assert eth.comparison_key != bitcoin.comparison_key

    # An Ethereum-shaped value labeled BTC is invalid, not silently retyped.
    invalid = _parse(_xml(_entry(1, identifiers=(("BTC", ETH_ADDRESS),))))
    validation = SanctionsSnapshotValidator().validate(invalid, now=NOW)
    assert validation.status is SnapshotEvidenceStatus.UNKNOWN
    assert not validation.permits_allow
    assert "ofac.digital_identifier_invalid" in {
        finding.code for finding in validation.diagnostics
    }

    # Asset names that do not establish an unambiguous network also fail closed.
    ambiguous = _parse(_xml(_entry(1, identifiers=(("USDT", ETH_ADDRESS),))))
    validation = SanctionsSnapshotValidator().validate(ambiguous, now=NOW)
    assert validation.status is SnapshotEvidenceStatus.UNKNOWN
    assert "ofac.currency_network_unsupported" in {
        finding.code for finding in validation.diagnostics
    }


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"<notSdnList/>", "ofac.unknown_schema"),
        (b"<sdnList>", "ofac.malformed_xml"),
        (
            b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><sdnList/>',
            "ofac.unsafe_xml",
        ),
    ],
)
def test_malformed_or_unsafe_schema_is_unknown_and_never_allow(raw, reason):
    record = _parse(raw)
    validation = SanctionsSnapshotValidator().validate(record, now=NOW)
    assert validation.status is SnapshotEvidenceStatus.UNKNOWN
    assert not validation.permits_allow
    assert reason in {finding.code for finding in validation.diagnostics}
    assert record.source.raw_bytes == raw


def test_truncation_suspicious_drop_rollback_and_delisting_time_fail_closed():
    entries = tuple(_entry(uid) for uid in range(1, 11))
    previous = _parse(
        _xml(*entries, publish_date="07/28/2026"),
        published_at="2026-07-28T00:00:00Z",
        effective_at="2026-07-28T00:00:00Z",
    )

    truncated = _parse(
        _xml(_entry(1), declared_count=10),
        published_at=PUBLISHED,
        effective_at=PUBLISHED,
        previous=previous,
    )
    result = SanctionsSnapshotValidator().validate(
        truncated, previous=previous, now=NOW
    )
    assert result.status is SnapshotEvidenceStatus.UNKNOWN
    assert not result.permits_allow
    assert {"ofac.record_count_mismatch", "snapshot.suspicious_count_drop"} <= {
        finding.code for finding in result.diagnostics
    }

    rollback = _parse(
        _xml(*entries[:-1], publish_date="07/27/2026"),
        published_at="2026-07-27T00:00:00Z",
        effective_at="2026-07-28T00:00:00Z",
        previous=previous,
    )
    result = SanctionsSnapshotValidator().validate(
        rollback, previous=previous, now="2026-07-28T01:00:00Z"
    )
    assert result.status is SnapshotEvidenceStatus.UNKNOWN
    assert not result.permits_allow
    assert {
        "snapshot.publication_rollback",
        "snapshot.effective_time_rollback",
        "snapshot.delisting_time_error",
    } <= {finding.code for finding in result.diagnostics}


def test_delta_and_valid_delisting_bind_a_later_effective_epoch():
    previous = _parse(
        _xml(_entry(1), _entry(2), publish_date="07/28/2026"),
        published_at="2026-07-28T00:00:00Z",
        effective_at="2026-07-28T00:00:00Z",
    )
    current = _parse(
        _xml(_entry(2, name="Changed"), _entry(3)),
        previous=previous,
    )
    result = SanctionsSnapshotValidator().validate(
        current, previous=previous, now=NOW
    )
    assert result.status is SnapshotEvidenceStatus.CURRENT
    assert result.permits_allow
    assert result.delta is not None
    assert result.delta.added_designation_ids == ("designation:ofac-sdn:3",)
    assert result.delta.removed_designation_ids == ("designation:ofac-sdn:1",)
    assert result.delta.changed_designation_ids == ("designation:ofac-sdn:2",)


def test_expired_snapshot_is_stale_and_never_allow():
    record = _parse(
        _xml(_entry(1), publish_date="07/01/2026"),
        published_at="2026-07-01T00:00:00Z",
        effective_at="2026-07-01T00:00:00Z",
    )
    result = SanctionsSnapshotValidator(maximum_age=timedelta(days=1)).validate(
        record, now=NOW
    )
    assert result.status is SnapshotEvidenceStatus.STALE
    assert not result.permits_allow
    assert "snapshot.expired" in {finding.code for finding in result.diagnostics}


def test_publication_after_retrieval_is_unknown_instead_of_escaping_model_error():
    record = _parse(
        _xml(_entry(1), publish_date="07/30/2026"),
        published_at="2026-07-30T00:00:00Z",
        effective_at="2026-07-30T00:00:00Z",
        retrieved_at="2026-07-29T00:05:00Z",
    )
    result = SanctionsSnapshotValidator().validate(record, now=NOW)
    assert result.status is SnapshotEvidenceStatus.UNKNOWN
    assert not result.permits_allow
    assert "ofac.snapshot_model_invalid" in {
        finding.code for finding in result.diagnostics
    }


def test_injected_acquisition_rejects_unofficial_origin_and_enforces_bound():
    calls = []

    def fetcher(url: str, maximum_bytes: int) -> bytes:
        calls.append((url, maximum_bytes))
        return _xml(_entry(1))

    parser = OFACSDNParser(max_source_bytes=4096)
    record = parser.acquire(
        fetcher,
        source_url=OFAC_SDN_XML_URL,
        retrieved_at="2026-07-29T00:05:00Z",
        published_at=PUBLISHED,
        effective_at=PUBLISHED,
    )
    assert record.snapshot is not None
    assert calls == [(OFAC_SDN_XML_URL, 4096)]

    with pytest.raises(OFACIngestionError, match="official OFAC"):
        parser.acquire(
            fetcher,
            source_url="https://search.example/ofac-copy.xml",
            retrieved_at="2026-07-29T00:05:00Z",
        )

    def oversized(_url: str, maximum_bytes: int) -> bytes:
        return b"x" * (maximum_bytes + 1)

    with pytest.raises(OFACIngestionError, match="max_source_bytes"):
        parser.acquire(
            oversized,
            source_url=OFAC_SDN_XML_URL,
            retrieved_at="2026-07-29T00:05:00Z",
        )


def test_append_only_journal_preserves_historical_imports_and_rejects_rewrite():
    first = _parse(_xml(_entry(1)))
    second = _parse(
        _xml(_entry(1), _entry(2), publish_date="07/30/2026"),
        published_at="2026-07-30T00:00:00Z",
        effective_at="2026-07-30T00:00:00Z",
        retrieved_at="2026-07-30T00:05:00Z",
        previous=first,
    )
    journal = AppendOnlySnapshotJournal()
    journal.append(first)
    journal.append(second)
    assert journal.records == (first, second)
    with pytest.raises(ValueError, match="already recorded"):
        journal.append(first)

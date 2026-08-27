"""Focused tests for the production legacy state-law v2 adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    closed_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    ADAPTER_SCHEMA_VERSION,
    COLLISION_STRATEGY_VERSION,
    DEFAULT_MIN_TEXT_CHARS,
    AdaptationDisposition,
    AdapterCheckpoint,
    CheckpointMismatchError,
    LegacyInputError,
    LegacyStateLawsV2Adapter,
    file_sha256,
    legacy_input_row_count,
    normalize_source_receipt,
    resolve_refresh_state_input,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    AdmissionStatus,
    CorpusRecord,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
    canonical_json_dumps,
    content_sha256,
)

RELEASE_POINT = hashlib.sha256(b"state-laws-live-adapter-test-release").hexdigest()
OBSERVED_AT = "2026-08-24T00:00:00Z"


def _statutory_text(section: str = "1.01") -> str:
    return (
        f"Section {section}. A person licensed under this chapter shall maintain "
        "complete records of every regulated transaction. The department may "
        "inspect those records during ordinary business hours and must provide "
        "written notice of any violation. A licensee may not knowingly submit a "
        "false record, and each violation is subject to the remedies provided in "
        "this title. This subsection applies together with all related provisions."
    )


def _jsonld_row(
    *,
    state: str = "WI",
    section: str = "1.01",
    source_url: str = "https://docs.legis.wisconsin.gov/document/statutes/1.01",
    text: str | None = None,
) -> dict:
    return {
        "@context": "https://schema.org",
        "@id": f"urn:state:{state.lower()}:statute:{section}",
        "@type": "Legislation",
        "stateCode": state,
        "sectionNumber": section,
        "titleNumber": "1",
        "chapterNumber": "1",
        "name": "Recordkeeping requirements",
        "text": _statutory_text(section) if text is None else text,
        "sourceUrl": source_url,
    }


def _write_jsonld(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _verified_receipt(
    path: Path,
    *,
    state: str = "WI",
    official_source_url: str = "https://docs.legis.wisconsin.gov/statutes/statutes/1",
    acquisition_path_id: str = "wi-docs-statutes",
    verification_result: str = "verified",
    input_sha256: str | None = None,
) -> dict:
    digest = input_sha256 or file_sha256(path)
    row_count = legacy_input_row_count(path)
    host = official_source_url.split("/", 3)[2]
    receipt = closed_jurisdiction_receipt(
        state,
        discovered=row_count,
        fetched=row_count,
        excluded=0,
        quarantined=0,
        failed_final=0,
        source_domain=host,
        canonical_keys=[f"{state.lower()}:1.01"],
        derived_keys=[f"{state.lower()}:1.01"],
    )
    receipt.update(
        {
            "receipt_id": f"scrape-{state.lower()}-live-test",
            "official_source_url": official_source_url,
            "observation_time": OBSERVED_AT,
            "release_point": RELEASE_POINT,
            "source_checksum": digest,
            "adapter_input_sha256": digest,
            "verification_result": verification_result,
            "acquisition_path_ids": [acquisition_path_id],
            "content_hashes": [digest],
            "start_urls": [official_source_url],
            "source_software_version": "test-scraper/1",
        }
    )
    return receipt


def _wayback_transport_receipt(
    *,
    official_url: str,
    content_sha256: str,
    archive_timestamp: str = "20260102030405",
) -> dict:
    return {
        "archive_timestamp": archive_timestamp,
        "archive_url": (
            f"https://web.archive.org/web/{archive_timestamp}id_/{official_url}"
        ),
        "content_sha256": content_sha256,
        "official_url": official_url,
        "source_transport": "wayback",
    }


def test_jsonld_real_body_is_admitted_only_with_bound_verified_receipt(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row()])
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )

    events = list(adapter.iter_events())

    assert len(events) == 1
    event = events[0]
    assert event.disposition is AdaptationDisposition.ADMITTED
    assert isinstance(event.record, CorpusRecord)
    assert event.record.admission_status is AdmissionStatus.ADMITTED
    assert event.record.source_authority_class is SourceAuthorityClass.OFFICIAL
    assert event.record.verification_result is VerificationResult.VERIFIED
    assert event.record.legal_id == "state:WI:wisconsin-statutes:1:1:1.01"
    assert event.record.text == _statutory_text()
    assert event.record.acquisition_receipt_id == "scrape-wi-live-test"
    assert event.source_evidence_sha256 == event.record.source_checksum
    assert isinstance(adapter.source_receipt.record, SourceReceiptRecord)
    assert adapter.source_receipt.admission_eligible is True
    assert adapter.source_receipt.record.source_checksum == file_sha256(source)


def test_current_typed_source_receipt_round_trip_remains_admission_eligible(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row()])
    normalized = normalize_source_receipt(
        _verified_receipt(source),
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
    )
    typed = SourceReceiptRecord.from_mapping(normalized.record.to_dict())

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=typed,
    )
    event = next(adapter.iter_events())

    assert adapter.source_receipt.record is typed
    assert adapter.source_receipt.admission_eligible is True
    assert adapter.source_receipt.qualification_reasons == ()
    assert event.disposition is AdaptationDisposition.ADMITTED


@pytest.mark.parametrize(
    "upstream_checksum",
    [None, hashlib.sha256(b"distinct upstream source bundle").hexdigest()],
)
def test_current_typed_receipt_preserves_optional_distinct_source_checksum(
    tmp_path: Path,
    upstream_checksum: str | None,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row()])
    receipt = _verified_receipt(source)
    receipt["disposition"].update(discovered=2, fetched=1, quarantined=1)
    if upstream_checksum is None:
        receipt.pop("source_checksum")
    else:
        receipt["source_checksum"] = upstream_checksum

    first = normalize_source_receipt(
        receipt,
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
    )
    typed = SourceReceiptRecord.from_mapping(first.record.to_dict())
    second = normalize_source_receipt(
        typed,
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
    )

    assert first.admission_eligible is True
    assert second.admission_eligible is True
    assert second.qualification_reasons == ()
    assert second.record is typed
    assert second.record.source_checksum == (upstream_checksum or file_sha256(source))
    if upstream_checksum is None:
        tampered = replace(
            typed,
            source_checksum=hashlib.sha256(b"unrelated replacement checksum").hexdigest(),
        )
        rejected = normalize_source_receipt(
            tampered,
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
        )
        assert rejected.admission_eligible is False
        assert (
            "receipt_fallback_source_checksum_mismatch"
            in rejected.qualification_reasons
        )


def test_current_typed_source_receipt_rechecks_artifact_bytes_and_row_count(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row()])
    normalized = normalize_source_receipt(
        _verified_receipt(source),
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
    )
    typed = SourceReceiptRecord.from_mapping(normalized.record.to_dict())
    _write_jsonld(source, [_jsonld_row(), _jsonld_row(section="1.02")])

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=typed,
    )

    assert adapter.source_receipt.admission_eligible is False
    assert (
        "receipt_adapter_input_sha256_mismatch"
        in adapter.source_receipt.qualification_reasons
    )
    assert any(
        reason.startswith("receipt_canonical_row_count_mismatch:")
        for reason in adapter.source_receipt.qualification_reasons
    )
    assert all(
        event.disposition is AdaptationDisposition.QUARANTINED
        for event in adapter.iter_events()
    )


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("count", "receipt_canonical_row_count_mismatch:2!=1"),
        ("release", "receipt_release_point_mismatch"),
        ("policy", "receipt_source_policy:MissingAuthoritativePathError"),
        ("authority_claim", "receipt_reported_authority_not_official"),
        ("verification_claim", "receipt_reported_verification_not_verified"),
        ("schema", "receipt_normalized_release_schema_mismatch"),
        ("start_url", "receipt_official_source_url_missing_from_start_urls"),
    ],
)
def test_current_typed_source_receipt_tampering_fails_closed(
    tmp_path: Path,
    mutation: str,
    expected_reason: str,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row()])
    normalized = normalize_source_receipt(
        _verified_receipt(source),
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
    )
    typed = SourceReceiptRecord.from_mapping(normalized.record.to_dict())
    if mutation == "release":
        typed = replace(typed, release_point=hashlib.sha256(b"other release").hexdigest())
    elif mutation == "schema":
        typed = replace(typed, schema_version="invented-state-laws-schema-v999")
    elif mutation == "start_url":
        typed = replace(typed, start_urls=())
    else:
        payload = dict(typed.payload)
        if mutation == "count":
            payload["reported_canonical_row_count"] = 2
        elif mutation == "policy":
            payload["acquisition_path_ids"] = ["not-a-cataloged-path"]
        elif mutation == "authority_claim":
            payload["reported_source_authority_class"] = "secondary"
        else:
            payload["reported_verification_result"] = "unverified"
        typed = replace(typed, payload=payload)

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=typed,
    )
    event = next(adapter.iter_events())

    assert adapter.source_receipt.admission_eligible is False
    assert expected_reason in adapter.source_receipt.qualification_reasons
    assert event.disposition is AdaptationDisposition.QUARANTINED


def test_jsonld_explicit_relation_evidence_is_canonical_and_entry_bound(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    row = _jsonld_row()
    row.update(
        {
            "citations": {
                "public_laws": [
                    "Pub. L. 117-58",
                    "Pub. L. 117-58",
                    "Pub. L. 112-29",
                ],
                "cites": ["state:WI:wisconsin-statutes:1:1:1.02"],
            },
            "amends": ["state:WI:wisconsin-statutes:1:1:1.03"],
            "repeals": ["state:WI:wisconsin-statutes:1:1:1.04"],
            "structured_data": {
                "transfers": ["state:WI:wisconsin-statutes:1:1:1.05"],
                # Mirrored public-law evidence must not create a second edge.
                "public_laws": ["Pub. L. 117-58"],
            },
        }
    )
    _write_jsonld(source, [row])
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )

    event = next(adapter.iter_events())

    assert event.disposition is AdaptationDisposition.ADMITTED
    assert event.record is not None
    assert event.record.public_laws == (
        "Pub. L. 117-58",
        "Pub. L. 117-58",
        "Pub. L. 112-29",
    )
    assert event.record.cites == ("state:WI:wisconsin-statutes:1:1:1.02",)
    assert event.record.amends == ("state:WI:wisconsin-statutes:1:1:1.03",)
    assert event.record.repeals == ("state:WI:wisconsin-statutes:1:1:1.04",)
    assert event.record.transfers == ("state:WI:wisconsin-statutes:1:1:1.05",)

    without_relations = adapter.adapt_row(_jsonld_row(), source_index=0)
    assert without_relations.record is not None
    assert without_relations.record.entry_cid != event.record.entry_cid


def test_malformed_explicit_relation_is_rejected_without_silent_loss(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    row = _jsonld_row()
    row["amends"] = "state:WI:wisconsin-statutes:1:1:1.02"
    _write_jsonld(source, [row])
    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=_verified_receipt(source),
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.REJECTED
    assert event.record is None
    assert event.reasons[0].startswith("explicit_relation_invalid:")


def test_default_policy_preserves_valid_short_public_law(tmp_path: Path) -> None:
    text = "A licensee shall comply with this section today."
    assert len(text) == 48
    assert DEFAULT_MIN_TEXT_CHARS == 1
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row(text=text)])

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )
    event = next(adapter.iter_events())

    assert event.disposition is AdaptationDisposition.ADMITTED
    assert event.record is not None
    assert event.record.text == text


def test_explicit_source_units_at_same_citation_remain_distinct(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    first = _jsonld_row(section="1.01")
    first["provenance"] = {"source_record_id": "WI1.01.current"}
    second = _jsonld_row(section="1.01")
    second["provenance"] = {"source_record_id": "WI1.01.future version"}
    _write_jsonld(source, [first, second])

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )
    events = list(adapter.iter_events())

    assert [event.disposition for event in events] == [
        AdaptationDisposition.ADMITTED,
        AdaptationDisposition.ADMITTED,
    ]
    records = [event.record for event in events]
    assert all(record is not None for record in records)
    assert len({record.legal_id for record in records if record is not None}) == 2
    assert len({record.entry_cid for record in records if record is not None}) == 2
    assert all(
        ";granule=source-record:" in record.legal_id
        for record in records
        if record is not None
    )
    assert adapter.collision_group_count == 0
    assert adapter.collision_row_count == 0


def test_normalized_citation_collision_uses_canonical_source_identity_only_for_group(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    rows = [
        _jsonld_row(section="5/7-01"),
        _jsonld_row(section="5/7-1"),
        _jsonld_row(section="8/1"),
    ]
    _write_jsonld(source, rows)
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )

    events = list(adapter.iter_events())
    records = [event.record for event in events]

    assert all(event.disposition is AdaptationDisposition.ADMITTED for event in events)
    assert all(record is not None for record in records)
    assert adapter.collision_strategy_version == COLLISION_STRATEGY_VERSION
    assert adapter.collision_group_count == 1
    assert adapter.collision_row_count == 2
    assert len({record.legal_id for record in records if record is not None}) == 3
    assert len({record.entry_cid for record in records if record is not None}) == 3
    assert all(
        ";granule=source-record:urn%3a" in record.legal_id
        for record in records[:2]
        if record is not None
    )
    assert records[2] is not None
    assert records[2].legal_id == "state:WI:wisconsin-statutes:1:1:8/1"

    versioned_config = {
        "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
        "collision_plan_sha256": adapter.collision_plan_sha256,
        "collision_strategy_version": COLLISION_STRATEGY_VERSION,
        "input_sha256": adapter.source_receipt.input_sha256,
        "jurisdiction": adapter.jurisdiction,
        "min_text_chars": adapter.min_text_chars,
        "parser_version": adapter.parser_version,
        "release_point": adapter.release_point,
        "source_receipt": adapter.source_receipt.record.to_dict(),
    }
    old_config = dict(versioned_config)
    old_config.pop("collision_plan_sha256")
    old_config.pop("collision_strategy_version")
    assert adapter.configuration_sha256 == content_sha256(
        canonical_json_dumps(versioned_config)
    )
    old_configuration_sha256 = content_sha256(canonical_json_dumps(old_config))
    assert adapter.configuration_sha256 != old_configuration_sha256
    assert adapter.new_checkpoint().configuration_sha256 == adapter.configuration_sha256
    pre_strategy_checkpoint = replace(
        adapter.new_checkpoint(),
        configuration_sha256=old_configuration_sha256,
    )
    with pytest.raises(CheckpointMismatchError, match="configuration_sha256"):
        adapter.validate_checkpoint(pre_strategy_checkpoint)


def test_collision_plan_is_order_independent_and_byte_reproducible(
    tmp_path: Path,
) -> None:
    rows = [
        _jsonld_row(section="5/7-01"),
        _jsonld_row(section="5/7-1"),
        _jsonld_row(section="8/1"),
    ]
    forward_source = tmp_path / "forward" / "STATE-WI.jsonld"
    reverse_source = tmp_path / "reverse" / "STATE-WI.jsonld"
    _write_jsonld(forward_source, rows)
    _write_jsonld(reverse_source, list(reversed(rows)))

    def build(path: Path) -> LegacyStateLawsV2Adapter:
        return LegacyStateLawsV2Adapter(
            input_path=path,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=_verified_receipt(path),
        )

    first = build(forward_source)
    again = build(forward_source)
    reversed_adapter = build(reverse_source)
    first_events = list(first.iter_events())
    again_events = list(again.iter_events())
    reverse_events = list(reversed_adapter.iter_events())
    first_by_source = {
        row["@id"]: event.record.legal_id
        for row, event in zip(rows, first_events, strict=True)
        if event.record is not None
    }
    reverse_by_source = {
        row["@id"]: event.record.legal_id
        for row, event in zip(reversed(rows), reverse_events, strict=True)
        if event.record is not None
    }

    assert first.collision_plan_sha256 == reversed_adapter.collision_plan_sha256
    assert first_by_source == reverse_by_source
    assert first.configuration_sha256 == again.configuration_sha256
    assert [
        (event.record.legal_id, event.record.entry_cid, event.source_evidence_sha256)
        for event in first_events
        if event.record is not None
    ] == [
        (event.record.legal_id, event.record.entry_cid, event.source_evidence_sha256)
        for event in again_events
        if event.record is not None
    ]


def test_collision_plan_matches_jsonld_and_parquet_source_identity(
    tmp_path: Path,
) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    rows = [_jsonld_row(section="5/7-01"), _jsonld_row(section="5/7-1")]
    jsonld_source = tmp_path / "jsonld" / "STATE-WI.jsonld"
    parquet_source = tmp_path / "parquet" / "STATE-WI.parquet"
    _write_jsonld(jsonld_source, rows)
    parquet_source.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "WI",
                    "source_id": row["@id"],
                    "identifier": row["sectionNumber"],
                    "text": row["text"],
                    "source_url": row["sourceUrl"],
                    "jsonld": json.dumps(row, sort_keys=True),
                }
                for row in rows
            ]
        ),
        parquet_source,
    )

    def build(path: Path) -> LegacyStateLawsV2Adapter:
        return LegacyStateLawsV2Adapter(
            input_path=path,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=_verified_receipt(path),
        )

    jsonld_adapter = build(jsonld_source)
    parquet_adapter = build(parquet_source)
    jsonld_events = list(jsonld_adapter.iter_events())
    parquet_events = list(parquet_adapter.iter_events())

    assert jsonld_adapter.collision_plan_sha256 == parquet_adapter.collision_plan_sha256
    assert [event.record.legal_id for event in jsonld_events if event.record is not None] == [
        event.record.legal_id for event in parquet_events if event.record is not None
    ]
    assert [event.record.entry_cid for event in jsonld_events if event.record is not None] == [
        event.record.entry_cid for event in parquet_events if event.record is not None
    ]


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing", "missing_canonical_source_identity"),
        ("repeated", "repeated, non-global source identity"),
        ("conflicting", "conflicting_canonical_source_identities"),
        ("malformed", "malformed_canonical_source_identity"),
        ("explicit_legal_id", "explicit legal_id"),
        ("explicit_granule", "explicit source granule"),
        ("non_global", "repeated, non-global source identity"),
    ],
)
def test_ambiguous_collision_groups_fail_closed(
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    source = tmp_path / mutation / "STATE-WI.jsonld"
    first = _jsonld_row(section="5/7-01")
    second = _jsonld_row(section="5/7-1")
    rows = [first, second]
    if mutation == "missing":
        first.pop("@id")
        second.pop("@id")
    elif mutation == "repeated":
        second["@id"] = first["@id"]
    elif mutation == "conflicting":
        first["source_id"] = "urn:conflict:first"
        second["source_id"] = "urn:conflict:second"
    elif mutation == "malformed":
        first["source_id"] = 7
        second["source_id"] = 8
    elif mutation == "explicit_legal_id":
        legal_id = "state:WI:wisconsin-statutes:1:1:5/7-1"
        first["legal_id"] = legal_id
        second["legal_id"] = legal_id
    elif mutation == "explicit_granule":
        first["provenance"] = {"source_record_id": "shared-record"}
        second["provenance"] = {"source_record_id": "shared-record"}
    else:
        rows.append(_jsonld_row(section="8/1"))
        rows[-1]["@id"] = first["@id"]
    _write_jsonld(source, rows)

    with pytest.raises(LegacyInputError, match=error):
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=_verified_receipt(source),
        )


def test_malformed_colliding_row_keeps_existing_per_row_rejection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    valid = _jsonld_row(section="5/7-01")
    malformed = _jsonld_row(section="5/7-1", text="")
    malformed.pop("@id")
    _write_jsonld(source, [valid, malformed])

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )
    events = list(adapter.iter_events())

    assert adapter.collision_group_count == 0
    assert adapter.collision_row_count == 0
    assert events[0].disposition is AdaptationDisposition.ADMITTED
    assert events[0].record is not None
    assert events[0].record.legal_id == "state:WI:wisconsin-statutes:1:1:5/7-1"
    assert events[1].disposition is AdaptationDisposition.REJECTED
    assert "empty_statute_body" in events[1].reasons


def test_terms_of_service_inside_public_law_is_not_footer_chrome(
    tmp_path: Path,
) -> None:
    text = (
        "Disclosure of the contents of the deceased user's account to a fiduciary "
        "is subject to the same license, restrictions, terms of service, and "
        "legal obligations that applied to the deceased user."
    )
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row(text=text)])

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=_verified_receipt(source),
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.ADMITTED
    assert event.record is not None
    assert event.record.text == text


def test_statutory_form_insert_direction_is_not_a_placeholder(tmp_path: Path) -> None:
    text = (
        "Section 1.01. A licensee shall provide written notice to every affected "
        "person while the regulated facility is under construction. The notice "
        "must state, \"The effective date is [insert date],\" "
        "and must identify the applicable chapter, agency, and appeal period. A "
        "person may request review under this section, and the department shall "
        "retain the completed form as an official record."
    )
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row(text=text)])

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=_verified_receipt(source),
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.ADMITTED
    assert event.record is not None
    assert event.record.text == text


def test_insert_only_body_remains_a_rejected_placeholder(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row(text="[insert statute text]")])

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=_verified_receipt(source),
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.REJECTED
    assert event.record is None
    assert "text_quality:placeholder_text" in event.reasons


def test_parquet_preserves_legacy_cid_as_source_lineage(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    legacy_cid = "bafkreib6m4myvtr7zmwivx7y6o42b3x6rflmrmxztqskj5uvzqi7jmuqei"
    payload = _jsonld_row()
    parquet_row = {
        "ipfs_cid": legacy_cid,
        "state_code": "WI",
        "identifier": "1.01",
        "name": payload["name"],
        "text": payload["text"],
        "source_url": payload["sourceUrl"],
        "jsonld": json.dumps(payload, sort_keys=True),
    }
    source = tmp_path / "state_laws_parquet_cid" / "STATE-WI.parquet"
    source.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist([parquet_row]), source)
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )

    event = next(adapter.iter_events())

    assert event.disposition is AdaptationDisposition.ADMITTED
    assert event.record is not None
    assert event.record.source_cid == legacy_cid
    assert event.legacy_hashes["ipfs_cid"] == legacy_cid


def test_unverified_or_input_hash_mismatch_quarantines_every_real_row(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row()])
    wrong_digest = hashlib.sha256(b"different artifact").hexdigest()
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source, input_sha256=wrong_digest),
    )

    event = next(adapter.iter_events())

    assert event.disposition is AdaptationDisposition.QUARANTINED
    assert event.record is not None
    assert event.record.admission_status is AdmissionStatus.QUARANTINED
    assert event.record.verification_result is VerificationResult.CONFLICT
    assert "receipt_input_sha256_mismatch" in event.reasons
    assert adapter.source_receipt.admission_eligible is False


def test_archive_and_secondary_sources_remain_quarantined(tmp_path: Path) -> None:
    archived = tmp_path / "STATE-WI.jsonld"
    archive_url = (
        "https://web.archive.org/web/20260101000000/"
        "https://docs.legis.wisconsin.gov/document/statutes/1.01"
    )
    _write_jsonld(archived, [_jsonld_row(source_url=archive_url)])
    archive_adapter = LegacyStateLawsV2Adapter(
        input_path=archived,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(archived),
    )
    archive_event = next(archive_adapter.iter_events())
    assert archive_event.disposition is AdaptationDisposition.QUARANTINED
    assert any(reason.startswith("row_transport:archive_host") for reason in archive_event.reasons)

    secondary = tmp_path / "STATE-TN.jsonld"
    justia = "https://law.justia.com/codes/tennessee/title-1/chapter-1/section-1-1-101/"
    _write_jsonld(
        secondary,
        [_jsonld_row(state="TN", section="1-1-101", source_url=justia)],
    )
    tn_receipt = _verified_receipt(
        secondary,
        state="TN",
        official_source_url="https://www.capitol.tn.gov/",
        acquisition_path_id="tn-tga",
    )
    secondary_adapter = LegacyStateLawsV2Adapter(
        input_path=secondary,
        jurisdiction="TN",
        release_point=RELEASE_POINT,
        source_receipt=tn_receipt,
    )
    secondary_event = next(secondary_adapter.iter_events())
    assert secondary_event.disposition is AdaptationDisposition.QUARANTINED
    assert secondary_event.record is not None
    assert secondary_event.record.source_authority_class is SourceAuthorityClass.SECONDARY
    assert "secondary_source_host:law.justia.com" in secondary_event.reasons


def test_verified_manifest_artifact_transport_of_official_bytes_is_admitted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    row = _jsonld_row()
    body_sha256 = hashlib.sha256(b"retained official response bytes").hexdigest()
    transport = _wayback_transport_receipt(
        official_url=row["sourceUrl"],
        content_sha256=body_sha256,
    )
    row["structured_data"] = {
        "archive_timestamp": transport["archive_timestamp"],
        "archive_url": transport["archive_url"],
        "archive_source_url": transport["archive_url"],
        "body_sha256": body_sha256,
        "fetch_transport": "wayback",
        "source_authority_class": "official",
        "source_kind": "hash_bound_archived_official_state_law",
        "transport_receipt": transport,
    }
    _write_jsonld(source, [row])
    receipt = _verified_receipt(source)
    receipt["content_hashes"].append(body_sha256)
    receipt["transport"] = {"kind": "archived_https"}
    receipt["artifacts"] = [transport]

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=receipt,
    )
    event = next(adapter.iter_events())

    assert adapter.source_receipt.admission_eligible is True
    assert adapter.source_receipt.requires_verified_transport_binding is True
    assert len(adapter.source_receipt.verified_transport_receipts) == 1
    assert event.disposition is AdaptationDisposition.ADMITTED
    assert event.record is not None
    assert event.record.source_checksum == body_sha256
    assert not any(reason.startswith("row_transport:") for reason in event.reasons)


def test_verified_transport_binds_section_fragment_to_fetched_page(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    official_page = "https://docs.legis.wisconsin.gov/document/statutes/1.01"
    body_sha256 = hashlib.sha256(b"official chapter representation").hexdigest()
    transport = _wayback_transport_receipt(
        official_url=official_page,
        content_sha256=body_sha256,
    )
    row = _jsonld_row(source_url=f"{official_page}#section-1.01")
    row["structuredData"] = {
        "content_sha256": body_sha256,
        "source_authority_class": "official",
        "transport_receipt": transport,
    }
    _write_jsonld(source, [row])
    receipt = _verified_receipt(source)
    receipt["content_hashes"].append(body_sha256)
    receipt["transport_receipts"] = [transport]

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=receipt,
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.ADMITTED
    assert event.record is not None
    assert event.record.official_source_url == row["sourceUrl"]
    assert event.record.source_checksum == body_sha256


@pytest.mark.parametrize(
    "row_url",
    [
        "https://docs.legis.wisconsin.gov/document/statutes/1.02#section-1.01",
        "https://docs.legis.wisconsin.gov/document/statutes/1.01?edition=2#section-1.01",
        "https://legis.wisconsin.gov/document/statutes/1.01#section-1.01",
    ],
    ids=("path-drift", "query-drift", "host-drift"),
)
def test_verified_transport_fragment_rule_rejects_locator_drift(
    tmp_path: Path,
    row_url: str,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    official_page = "https://docs.legis.wisconsin.gov/document/statutes/1.01"
    body_sha256 = hashlib.sha256(b"official chapter representation").hexdigest()
    transport = _wayback_transport_receipt(
        official_url=official_page,
        content_sha256=body_sha256,
    )
    row = _jsonld_row(source_url=row_url)
    row["structuredData"] = {
        "content_sha256": body_sha256,
        "transport_receipt": transport,
    }
    _write_jsonld(source, [row])
    receipt = _verified_receipt(source)
    receipt["content_hashes"].append(body_sha256)
    receipt["transport_receipts"] = [transport]

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=receipt,
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.QUARANTINED
    assert "row_transport:missing_verified_official_byte_binding" in event.reasons


def test_verified_transport_fragment_rule_rejects_digest_drift(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    official_page = "https://docs.legis.wisconsin.gov/document/statutes/1.01"
    receipt_body_sha256 = hashlib.sha256(b"official representation").hexdigest()
    declared_body_sha256 = hashlib.sha256(b"different representation").hexdigest()
    transport = _wayback_transport_receipt(
        official_url=official_page,
        content_sha256=receipt_body_sha256,
    )
    row = _jsonld_row(source_url=f"{official_page}#section-1.01")
    row["structuredData"] = {
        "content_sha256": declared_body_sha256,
        "transport_receipt": transport,
    }
    _write_jsonld(source, [row])
    receipt = _verified_receipt(source)
    receipt["content_hashes"].append(receipt_body_sha256)
    receipt["transport_receipts"] = [transport]

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=receipt,
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.QUARANTINED
    assert "row_transport:missing_verified_official_byte_binding" in event.reasons


def test_verified_transport_fragment_rule_rejects_missing_row_digest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    official_page = "https://docs.legis.wisconsin.gov/document/statutes/1.01"
    receipt_body_sha256 = hashlib.sha256(b"official representation").hexdigest()
    transport = _wayback_transport_receipt(
        official_url=official_page,
        content_sha256=receipt_body_sha256,
    )
    row = _jsonld_row(source_url=f"{official_page}#section-1.01")
    row["structuredData"] = {"transport_receipt": transport}
    _write_jsonld(source, [row])
    receipt = _verified_receipt(source)
    receipt["content_hashes"].append(receipt_body_sha256)
    receipt["transport_receipts"] = [transport]

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=receipt,
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.QUARANTINED
    assert "row_transport:missing_verified_official_byte_binding" in event.reasons


def test_input_bound_row_can_carry_its_explicit_georgia_shaped_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    row = _jsonld_row()
    body_sha256 = hashlib.sha256(b"one retained official response").hexdigest()
    transport = _wayback_transport_receipt(
        official_url=row["sourceUrl"],
        content_sha256=body_sha256,
    )
    row.update(
        {
            "body_sha256": body_sha256,
            "fetch_transport": "wayback",
            "transport_receipt": transport,
        }
    )
    _write_jsonld(source, [row])
    receipt = _verified_receipt(source)
    receipt["content_hashes"].append(body_sha256)

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=receipt,
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.ADMITTED
    assert event.record is not None
    assert event.record.official_source_url == row["sourceUrl"]
    assert event.record.source_checksum == body_sha256


def test_row_transport_digest_must_be_bound_by_the_source_receipt(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    row = _jsonld_row()
    body_sha256 = hashlib.sha256(b"one retained official response").hexdigest()
    row.update(
        {
            "body_sha256": body_sha256,
            "fetch_transport": "wayback",
            "transport_receipt": _wayback_transport_receipt(
                official_url=row["sourceUrl"],
                content_sha256=body_sha256,
            ),
        }
    )
    _write_jsonld(source, [row])

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=_verified_receipt(source),
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.QUARANTINED
    assert (
        "row_transport:transport_receipt:content_sha256_not_in_source_receipt_hashes"
        in event.reasons
    )


def test_generic_archive_marker_without_byte_receipt_remains_quarantined(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row()])
    receipt = _verified_receipt(source)
    receipt["transport"] = {"kind": "archived_https"}

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=receipt,
    )
    event = next(adapter.iter_events())

    assert adapter.source_receipt.admission_eligible is False
    assert event.disposition is AdaptationDisposition.QUARANTINED
    assert "receipt_transport:kind:archived_https" in event.reasons


def test_archive_binding_must_match_each_rows_declared_body_hash(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    row = _jsonld_row()
    declared_body = hashlib.sha256(b"declared official response").hexdigest()
    unrelated_body = hashlib.sha256(b"different official response").hexdigest()
    transport = _wayback_transport_receipt(
        official_url=row["sourceUrl"],
        content_sha256=unrelated_body,
    )
    row.update(
        {
            "archive_url": transport["archive_url"],
            "body_sha256": declared_body,
            "fetch_transport": "wayback",
        }
    )
    _write_jsonld(source, [row])
    receipt = _verified_receipt(source)
    receipt["content_hashes"].append(unrelated_body)
    receipt["transport_receipts"] = [transport]

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=receipt,
    )
    event = next(adapter.iter_events())

    assert adapter.source_receipt.admission_eligible is True
    assert event.disposition is AdaptationDisposition.QUARANTINED
    assert "row_transport:missing_verified_official_byte_binding" in event.reasons


def test_verified_archive_receipt_does_not_cover_a_different_provider_marker(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    row = _jsonld_row()
    body_sha256 = hashlib.sha256(b"retained official response bytes").hexdigest()
    transport = _wayback_transport_receipt(
        official_url=row["sourceUrl"],
        content_sha256=body_sha256,
    )
    row.update(
        {
            "body_sha256": body_sha256,
            "fetch_transport": "common_crawl",
        }
    )
    _write_jsonld(source, [row])
    receipt = _verified_receipt(source)
    receipt["artifacts"] = [transport]
    receipt["content_hashes"].append(body_sha256)

    event = next(
        LegacyStateLawsV2Adapter(
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            source_receipt=receipt,
        ).iter_events()
    )

    assert event.disposition is AdaptationDisposition.QUARANTINED
    assert "row_transport:fetch_transport:common_crawl" in event.reasons


def test_tampered_wayback_original_locator_quarantines_receipt_and_row(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    row = _jsonld_row()
    body_sha256 = hashlib.sha256(b"retained official response bytes").hexdigest()
    transport = _wayback_transport_receipt(
        official_url=row["sourceUrl"],
        content_sha256=body_sha256,
    )
    transport["archive_url"] = (
        "https://web.archive.org/web/20260102030405id_/"
        "https://docs.legis.wisconsin.gov/document/statutes/9.99"
    )
    row.update(
        {
            "archive_url": transport["archive_url"],
            "body_sha256": body_sha256,
            "fetch_transport": "wayback",
        }
    )
    _write_jsonld(source, [row])
    receipt = _verified_receipt(source)
    receipt["content_hashes"].append(body_sha256)
    receipt["transport_receipts"] = [transport]

    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=receipt,
    )
    event = next(adapter.iter_events())

    assert adapter.source_receipt.admission_eligible is False
    assert event.disposition is AdaptationDisposition.QUARANTINED
    assert any(
        reason.endswith("wayback_official_url_mismatch") for reason in event.reasons
    )


@pytest.mark.parametrize(
    "row,expected_reason",
    [
        (_jsonld_row(text=""), "empty_statute_body"),
        (_jsonld_row(text="lorem ipsum placeholder text"), "fixture_placeholder_or_example_text"),
        (
            _jsonld_row(source_url="https://example.com/statutes/1.01"),
            "reserved_example_source_host:example.com",
        ),
        (
            {**_jsonld_row(), "fixture_only": True},
            "explicit_fixture_only_flag",
        ),
    ],
)
def test_empty_fixture_and_example_rows_are_rejected(
    tmp_path: Path,
    row: dict,
    expected_reason: str,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [row])
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
        min_text_chars=64,
    )

    event = next(adapter.iter_events())

    assert event.disposition is AdaptationDisposition.REJECTED
    assert event.record is None
    assert expected_reason in event.reasons


def test_checkpoint_resume_is_deterministic_and_config_bound(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row(), _jsonld_row(section="1.02")])
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )
    checkpoint = adapter.new_checkpoint()
    first = next(adapter.iter_events(checkpoint=checkpoint))
    checkpoint = checkpoint.advance(first)
    checkpoint_path = tmp_path / "adapter.checkpoint.json"
    checkpoint.save(checkpoint_path)
    loaded = AdapterCheckpoint.load(checkpoint_path)

    resumed = list(adapter.iter_events(checkpoint=loaded))

    assert [event.source_index for event in resumed] == [1]
    closed = adapter.finalize_checkpoint(loaded.advance(resumed[0]))
    assert closed.complete is True
    changed = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
        min_text_chars=301,
    )
    with pytest.raises(CheckpointMismatchError, match="configuration_sha256"):
        list(changed.iter_events(checkpoint=loaded))


def test_adapter_rejects_input_swap_before_iteration(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row()])
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )
    _write_jsonld(source, [_jsonld_row(section="9.99")])

    with pytest.raises(LegacyInputError, match="changed after adapter preflight"):
        list(adapter.iter_events())


def test_adapter_does_not_retain_canonical_input_bytes_after_preflight(
    tmp_path: Path,
) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row(), _jsonld_row(section="1.02")])
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )

    assert "_input_bytes" not in adapter.__dict__
    assert not any(isinstance(value, bytes) for value in adapter.__dict__.values())


def test_adapter_rejects_input_swap_at_checkpoint_finalization(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row()])
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )
    checkpoint = adapter.new_checkpoint()
    event = next(adapter.iter_events())
    checkpoint = checkpoint.advance(event)
    _write_jsonld(source, [_jsonld_row(section="9.99")])

    with pytest.raises(LegacyInputError, match="changed after adapter preflight"):
        adapter.finalize_checkpoint(checkpoint)


def test_eligible_receipt_cannot_finalize_with_rejected_candidate_row(tmp_path: Path) -> None:
    source = tmp_path / "STATE-WI.jsonld"
    _write_jsonld(source, [_jsonld_row(), _jsonld_row(text="")])
    adapter = LegacyStateLawsV2Adapter(
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        source_receipt=_verified_receipt(source),
    )
    checkpoint = adapter.new_checkpoint()
    for event in adapter.iter_events(checkpoint=checkpoint):
        checkpoint = checkpoint.advance(event)

    with pytest.raises(ValueError, match="does not reconcile"):
        adapter.finalize_checkpoint(checkpoint)


def test_resolve_refresh_input_prefers_per_state_parquet(tmp_path: Path) -> None:
    jsonld = tmp_path / "state_laws_jsonld" / "STATE-WI.jsonld"
    parquet = tmp_path / "state_laws_parquet_cid" / "STATE-WI.parquet"
    _write_jsonld(jsonld, [_jsonld_row()])
    parquet.parent.mkdir(parents=True)
    parquet.write_bytes(b"not opened by resolver")

    assert resolve_refresh_state_input(tmp_path, "WI") == parquet.resolve()
    assert resolve_refresh_state_input(tmp_path, "WI", prefer="jsonld") == jsonld.resolve()

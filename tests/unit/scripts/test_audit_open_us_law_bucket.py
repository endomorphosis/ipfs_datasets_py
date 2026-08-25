"""Unit tests for the OUL-001 live open-us-law bucket inventory freeze."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.ops.legal_data.audit_open_us_law_bucket import (
    ABSENT_REQUIRED_STATUTE_CODES,
    BUCKET_ID,
    CANONICAL_ALGORITHM_ID,
    EXPECTED_CONTROL_OBJECT_COUNT,
    EXPECTED_OBJECT_COUNT,
    EXPECTED_PARQUET_COUNT,
    EXPECTED_TOTAL_SIZE_BYTES,
    PROVISIONAL_INVENTORY_DIGEST,
    SCHEMA_VERSION,
    STALE_SHA256SUMS_DIGEST,
    AuditError,
    audit_bucket_snapshot,
    build_snapshot_payload,
    canonical_object_records,
    check_committed_snapshot,
    default_schema_path,
    default_snapshot_path,
    independent_reconciliation,
    inventory_digest_sha256,
    is_parquet_path,
    listing_digest_sha256,
    load_snapshot,
    main,
    normalize_listing_objects,
    parse_checksum_entries,
    reconcile_checksum_entries,
    sha256_snapshot_json,
    statute_code_from_path,
    validate_snapshot,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _xet(label: str) -> str:
    return hashlib_sha256(label.encode("utf-8"))


def hashlib_sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _object(
    path: str,
    *,
    size: int,
    uploaded_at: str = "2026-08-13T20:54:05.114000Z",
    xet_hash: str | None = None,
) -> dict[str, object]:
    return {
        "path": path,
        "size": size,
        "type": "file",
        "uploadedAt": uploaded_at,
        "xetHash": xet_hash or _xet(path),
    }


def _compact_objects() -> list[dict[str, object]]:
    return [
        _object(".gitattributes", size=32),
        _object("README.md", size=64),
        _object("SHA256SUMS.json", size=128),
        _object("us_ak_statutes.parquet", size=256),
        _object("us_dc_statutes.parquet", size=512),
        _object("us_federal_constitutions.parquet", size=31003),
        _object("walkthrough-thumb.png", size=16),
    ]


def _compact_checksums() -> list[dict[str, object]]:
    return [
        {
            "file": "us_ak_statutes.parquet",
            "sha256": _xet("ak-bytes"),
            "bytes": 256,
        },
        {
            "file": "us_dc_statutes.parquet",
            "sha256": _xet("dc-bytes"),
            "bytes": 512,
        },
        {
            "file": "us_federal_constitutions.parquet",
            "sha256": _xet("federal-const-bytes"),
            "bytes": 25208,
        },
        {
            "file": "us_ga_statutes.parquet",
            "sha256": _xet("ga-bytes"),
            "bytes": 18649994,
        },
        {
            "file": "us_nc_statutes.parquet",
            "sha256": _xet("nc-bytes"),
            "bytes": 17106762,
        },
    ]


def _reseal(payload: dict) -> dict:
    body = {key: value for key, value in payload.items() if key != "snapshot_digest_sha256"}
    payload["snapshot_digest_sha256"] = sha256_snapshot_json(body)
    return payload


def test_statute_paths_use_live_us_code_layout() -> None:
    assert statute_code_from_path("us_al_statutes.parquet") == "AL"
    assert statute_code_from_path("us_dc_statutes.parquet") == "DC"
    assert statute_code_from_path("us_ga_statutes.parquet") == "GA"
    assert statute_code_from_path("us_nc_statutes.parquet") == "NC"
    assert statute_code_from_path("us_ga_constitutions.parquet") is None
    assert statute_code_from_path("us_federal_statutes.parquet") is None
    assert statute_code_from_path("statutes/al.parquet") is None


def test_canonical_records_are_sorted_by_path_and_hashed() -> None:
    objects = normalize_listing_objects(list(reversed(_compact_objects())))
    records = canonical_object_records(objects)
    paths = [item["path"] for item in records]
    assert paths == sorted(paths)
    assert [item["type"] for item in records] == ["file"] * len(records)
    for record in records:
        assert set(record) == {"path", "size_bytes", "type", "uploaded_at", "xet_hash"}
    digest = inventory_digest_sha256(objects)
    assert len(digest) == 64
    assert digest != listing_digest_sha256(objects)


def test_directories_are_excluded_from_inventory() -> None:
    objects = normalize_listing_objects(
        _compact_objects()
        + [{"type": "directory", "path": "statutes", "uploadedAt": "2026-08-13T20:54:05.114Z"}]
    )
    assert all(item["type"] == "file" for item in objects)
    assert "statutes" not in {item["path"] for item in objects}


def test_checksum_reconciliation_flags_withdrawn_and_size_drift() -> None:
    objects = normalize_listing_objects(_compact_objects())
    entries = parse_checksum_entries(_compact_checksums())
    manifest = reconcile_checksum_entries(
        objects,
        entries,
        checksum_bytes_sha256=STALE_SHA256SUMS_DIGEST,
    )
    assert manifest["stale"] is True
    assert manifest["withdrawn_paths_still_listed"] == [
        "us_ga_statutes.parquet",
        "us_nc_statutes.parquet",
    ]
    assert "us_ga_statutes.parquet" in manifest["checksum_paths_missing_from_live"]
    assert "us_nc_statutes.parquet" in manifest["checksum_paths_missing_from_live"]
    mismatches = manifest["size_or_digest_mismatches"]
    assert mismatches
    assert mismatches[0]["path"] == "us_federal_constitutions.parquet"
    assert mismatches[0]["checksum_size_bytes"] == 25208
    assert mismatches[0]["live_size_bytes"] == 31003


def test_independent_reconciliation_does_not_trust_declared_counts() -> None:
    objects = normalize_listing_objects(_compact_objects())
    entries = parse_checksum_entries(_compact_checksums())
    manifest = reconcile_checksum_entries(
        objects,
        entries,
        checksum_bytes_sha256=STALE_SHA256SUMS_DIGEST,
    )
    report = independent_reconciliation(
        objects,
        checksum_manifest=manifest,
        observed_at="2026-08-14T00:51:06Z",
        expected_object_count=len(objects),
        expected_parquet_count=sum(1 for item in objects if is_parquet_path(item["path"])),
        expected_total_size_bytes=sum(item["size_bytes"] for item in objects),
    )
    assert report["object_count"]["independent"] == len(objects)
    assert report["parquet_count"]["independent"] == 3
    assert report["xet_hashes"]["present"] == len(objects)
    assert report["xet_hashes"]["missing"] == 0
    assert report["observation_time"]["match"] is True
    assert report["stale_checksum_entries"]["stale"] is True
    assert report["absent_required_statute_codes"]["independent"] == list(
        ABSENT_REQUIRED_STATUTE_CODES
    )


def test_compact_builder_can_skip_live_totals() -> None:
    payload = build_snapshot_payload(
        _compact_objects(),
        observed_at="2026-08-14T00:51:06Z",
        checksum_entries=parse_checksum_entries(_compact_checksums()),
        checksum_bytes_sha256=STALE_SHA256SUMS_DIGEST,
        expected_object_count=7,
        expected_parquet_count=3,
        expected_total_size_bytes=32011,
        require_expected_totals=False,
    )
    assert payload["revision_pin"] is False
    assert payload["grants_authority"] is False
    assert payload["bucket_is_mutable"] is True
    assert payload["provisional_digest_authorizes_downstream"] is False
    assert payload["canonical_algorithm"]["id"] == CANONICAL_ALGORITHM_ID
    assert payload["provisional_inventory_digest_sha256"] == PROVISIONAL_INVENTORY_DIGEST


def test_validate_snapshot_rejects_revision_pin() -> None:
    payload = build_snapshot_payload(
        _compact_objects(),
        observed_at="2026-08-14T00:51:06Z",
        checksum_entries=parse_checksum_entries(_compact_checksums()),
        checksum_bytes_sha256=STALE_SHA256SUMS_DIGEST,
        expected_object_count=7,
        expected_parquet_count=3,
        expected_total_size_bytes=32011,
        require_expected_totals=False,
    )
    payload["revision_pin"] = True
    _reseal(payload)
    with pytest.raises(AuditError, match="revision pin"):
        validate_snapshot(payload, require_live=False)


def test_validate_snapshot_rejects_authority_grant() -> None:
    payload = build_snapshot_payload(
        _compact_objects(),
        observed_at="2026-08-14T00:51:06Z",
        checksum_entries=parse_checksum_entries(_compact_checksums()),
        checksum_bytes_sha256=STALE_SHA256SUMS_DIGEST,
        expected_object_count=7,
        expected_parquet_count=3,
        expected_total_size_bytes=32011,
        require_expected_totals=False,
    )
    payload["grants_authority"] = True
    _reseal(payload)
    with pytest.raises(AuditError, match="authority"):
        validate_snapshot(payload, require_live=False)


def test_validate_snapshot_rejects_digest_tamper() -> None:
    payload = build_snapshot_payload(
        _compact_objects(),
        observed_at="2026-08-14T00:51:06Z",
        checksum_entries=parse_checksum_entries(_compact_checksums()),
        checksum_bytes_sha256=STALE_SHA256SUMS_DIGEST,
        expected_object_count=7,
        expected_parquet_count=3,
        expected_total_size_bytes=32011,
        require_expected_totals=False,
    )
    payload["inventory_digest_sha256"] = "0" * 64
    _reseal(payload)
    with pytest.raises(AuditError, match="inventory_digest_sha256"):
        validate_snapshot(payload, require_live=False)


def test_committed_snapshot_is_a_live_unpinned_inventory() -> None:
    report = check_committed_snapshot(require_live=True)
    assert report["status"] == "passed"
    assert report["require_live"] is True
    assert report["revision_pin"] is False
    assert report["authorizing_for_publication"] is False
    assert report["object_count"] == EXPECTED_OBJECT_COUNT == 107
    assert report["parquet_count"] == EXPECTED_PARQUET_COUNT == 103
    assert report["total_size_bytes"] == EXPECTED_TOTAL_SIZE_BYTES
    assert report["stale_checksum_entry_count"] >= 2


def test_committed_snapshot_reconciles_live_layout_and_stale_checksums() -> None:
    payload = load_snapshot()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["bucket_id"] == BUCKET_ID
    assert payload["listing_mode"] == "authenticated_recursive"
    assert payload["authenticated"] is True
    assert payload["recursive"] is True
    assert payload["bucket_is_mutable"] is True
    assert payload["revision_pin"] is False
    assert payload["descriptor_is_authoritative"] is False
    assert payload["provisional_inventory_digest_sha256"] == PROVISIONAL_INVENTORY_DIGEST
    assert payload["provisional_digest_authorizes_downstream"] is False
    assert payload["checksum_manifest"]["bytes_sha256"] == STALE_SHA256SUMS_DIGEST
    assert payload["checksum_manifest"]["stale"] is True
    assert payload["checksum_manifest"]["withdrawn_paths_still_listed"] == [
        "us_ga_statutes.parquet",
        "us_nc_statutes.parquet",
    ]
    mismatches = {
        item["path"]: item for item in payload["checksum_manifest"]["size_or_digest_mismatches"]
    }
    assert "us_federal_constitutions.parquet" in mismatches
    paths = {item["path"] for item in payload["objects"]}
    assert "us_ga_statutes.parquet" not in paths
    assert "us_nc_statutes.parquet" not in paths
    assert "us_dc_statutes.parquet" in paths
    assert "us_ga_constitutions.parquet" in paths
    assert "README.md" in paths
    assert "SHA256SUMS.json" in paths
    assert ".gitattributes" in paths
    assert "walkthrough-thumb.png" in paths
    parquet_paths = [path for path in paths if path.endswith(".parquet")]
    assert len(parquet_paths) == 103
    control = payload["reconciliation"]["control_object_paths"]
    assert len(control) == EXPECTED_CONTROL_OBJECT_COUNT
    assert payload["reconciliation"]["object_count"]["match"] is True
    assert payload["reconciliation"]["parquet_count"]["match"] is True
    assert payload["reconciliation"]["total_size_bytes"]["match"] is True
    assert payload["reconciliation"]["xet_hashes"]["match"] is True
    assert payload["reconciliation"]["observation_time"]["match"] is True
    assert payload["inventory_digest_sha256"] != payload["listing_sha256"]


def test_schema_file_names_the_live_unpinned_contract() -> None:
    schema = json.loads(default_schema_path().read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    assert schema["properties"]["revision_pin"]["const"] is False
    assert schema["properties"]["bucket_is_mutable"]["const"] is True
    assert schema["properties"]["objects"]["minItems"] == 107
    assert schema["properties"]["objects"]["maxItems"] == 107
    expected = schema["$defs"]["expectedCounts"]["properties"]
    assert expected["object_count"]["const"] == 107
    assert expected["parquet_count"]["const"] == 103
    assert expected["total_size_bytes"]["const"] == 1_134_269_198
    assert (
        expected["stale_checksum_bytes_sha256"]["const"] == STALE_SHA256SUMS_DIGEST
    )


def test_cli_require_live_check_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--require-live", "--check"]) == 0
    captured = capsys.readouterr()
    assert "PASSED" in captured.out
    assert "objects=107" in captured.out
    assert "parquets=103" in captured.out
    assert "revision_pin=False" in captured.out


def test_cli_json_report_is_non_authorizing() -> None:
    report = audit_bucket_snapshot(load_snapshot(), require_live=True)
    assert report["status"] == "passed"
    assert report["authorizing_for_publication"] is False
    assert report["revision_pin"] is False
    assert report["require_live"] is True


def test_cli_missing_flags_fails() -> None:
    assert main([]) == 2
    assert main(["--check"]) == 2
    assert main(["--require-live"]) == 2


def test_repository_outputs_exist() -> None:
    root = _repo_root()
    assert (root / "data/legal/open_us_law/bucket_snapshot.schema.json").is_file()
    assert (root / "docs/reports/open_us_law_reindex/bucket_snapshot.json").is_file()
    assert (root / "scripts/ops/legal_data/audit_open_us_law_bucket.py").is_file()
    assert default_snapshot_path().is_file()


def test_committed_snapshot_bytes_round_trip() -> None:
    payload = load_snapshot()
    rebuilt = copy.deepcopy(payload)
    _reseal(rebuilt)
    assert rebuilt["snapshot_digest_sha256"] == payload["snapshot_digest_sha256"]

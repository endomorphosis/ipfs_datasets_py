#!/usr/bin/env python3
"""Freeze and reconcile the live open-us-law bucket inventory (OUL-001).

A Hugging Face Bucket is mutable object storage. This audit records one live
authenticated recursive listing, sorts it, and hashes the canonical
path/type/size/Xet/upload-time records. Counts, stale checksum entries, sizes,
Xet hashes, and observation time are recomputed independently. The inventory
digest is an observation, never a revision pin.

Validation gate (no network)::

    python scripts/ops/legal_data/audit_open_us_law_bucket.py --require-live --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "OUL-001"
GOAL_ID = "OUL-G010"
PROGRAM_ID = "open-us-law-reindex-v1"
PRODUCER = "audit_open_us_law_bucket.py@1"
SCHEMA_VERSION = "open-us-law-bucket-snapshot-v1"
REPORT_SCHEMA = "ipfs_datasets_py/open-us-law-bucket-snapshot-audit@1"
CODE_VERSION = "1"
CANONICAL_ALGORITHM_ID = "open-us-law-bucket-object-list-v1"
CANONICAL_ENCODING = "ir-canonical-json-v1"
LISTING_MODE_AUTHENTICATED_RECURSIVE = "authenticated_recursive"

BUCKET_ID = "justicedao/open-us-law-bucket"
SNAPSHOT_LABEL = "v2026.07"
SOURCES_OBSERVED_ON = "2026-07-21"
WITHDRAWN_ON = "2026-08-12"

SNAPSHOT_RELPATH = Path("docs/reports/open_us_law_reindex/bucket_snapshot.json")
SCHEMA_RELPATH = Path("data/legal/open_us_law/bucket_snapshot.schema.json")

EXPECTED_OBJECT_COUNT = 107
EXPECTED_PARQUET_COUNT = 103
EXPECTED_CONTROL_OBJECT_COUNT = 4
EXPECTED_TOTAL_SIZE_BYTES = 1_134_269_198
STALE_SHA256SUMS_DIGEST = (
    "20c7f327d38810da9168e53dd90babcae25fb634114e3cebbbe201c4726306b0"
)
PROVISIONAL_INVENTORY_DIGEST = (
    "ef84263ab604460297fadfefa4268aee974b1ba1ed914188cc591df62e6ff65b"
)
ABSENT_REQUIRED_STATUTE_CODES: tuple[str, ...] = ("GA", "NC")
CHECKSUM_MANIFEST_PATH = "SHA256SUMS.json"

REQUIRED_JURISDICTION_CODES: tuple[str, ...] = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
)

CANONICAL_RECORD_FIELDS: tuple[str, ...] = (
    "path",
    "size_bytes",
    "type",
    "uploaded_at",
    "xet_hash",
)
HF_TOKEN_ENV_VARS: tuple[str, ...] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
_STATUTE_PATH_RE = re.compile(r"^us_([a-z]{2})_statutes\.parquet$", re.IGNORECASE)
_WITHDRAWN_STATUTE_PATHS: tuple[str, ...] = (
    "us_ga_statutes.parquet",
    "us_nc_statutes.parquet",
)

SNAPSHOT_DESCRIPTION = (
    "Live authenticated recursive inventory of justicedao/open-us-law-bucket. "
    "The listing is canonically sorted and hashed over path, type, size, Xet "
    "identity, and upload time. Object counts, live Parquet counts, stale "
    "checksum entries, sizes, Xet hashes, and observation time are recomputed "
    "independently. The bucket is mutable and is not a revision pin."
)

CURRENTNESS_DISCLAIMER = (
    "This snapshot records one observation of a mutable, non-versioned Hugging "
    "Face Bucket. The inventory digest identifies that observation only. It is "
    "not a 40-hex Dataset revision, not a content-addressed release pin, and "
    "not proof of completeness or freshness."
)


class AuditError(RuntimeError):
    """Fail-closed bucket-inventory audit failure."""


def default_snapshot_path() -> Path:
    return REPOSITORY_ROOT / SNAPSHOT_RELPATH


def default_schema_path() -> Path:
    return REPOSITORY_ROOT / SCHEMA_RELPATH


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def snapshot_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_snapshot_json(value: Any) -> str:
    return sha256_bytes(snapshot_json_bytes(value))


_CANONICAL_JSON = None


def _canonical_json_impl():
    global _CANONICAL_JSON
    if _CANONICAL_JSON is None:
        import importlib.util

        module_path = (
            REPOSITORY_ROOT / "ipfs_datasets_py" / "logic" / "ir_core" / "canonical.py"
        )
        spec = importlib.util.spec_from_file_location("oul001_ir_canonical", module_path)
        if spec is None or spec.loader is None:
            raise AuditError("unable to load ir-canonical-json-v1")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _CANONICAL_JSON = module.canonical_json_bytes
    return _CANONICAL_JSON


def canonical_inventory_bytes(value: Any) -> bytes:
    return _canonical_json_impl()(value)


def sha256_canonical(value: Any) -> str:
    return sha256_bytes(canonical_inventory_bytes(value))


def _strict_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or isinstance(value, (str, bytes, bytearray)):
        raise AuditError(f"{label} must be an object")
    return value


def _strict_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise AuditError(f"{label} must be a non-empty string without surrounding whitespace")
    if "\x00" in value:
        raise AuditError(f"{label} must not contain NUL")
    return value


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AuditError(f"{label} must be a non-negative integer")
    return value


def _sha256_hex(value: Any, label: str) -> str:
    text = _strict_string(value, label).casefold()
    if _SHA256_RE.fullmatch(text) is None:
        raise AuditError(f"{label} must be a 64-character lowercase hexadecimal digest")
    return text


def _utc_timestamp(value: Any, label: str) -> str:
    text = _strict_string(value, label)
    if not _UTC_RE.fullmatch(text):
        raise AuditError(f"{label} must be a UTC timestamp")
    return text


def _posix_path(value: Any, label: str = "path") -> str:
    from pathlib import PurePosixPath

    text = _strict_string(value, label)
    if "\\" in text:
        raise AuditError(f"{label} must use POSIX separators")
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or parsed.as_posix() != text or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise AuditError(f"{label} must be a normalized root-relative POSIX path")
    return text


def _source_field(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    else:
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
    return default


def normalize_timestamp(value: Any, *, label: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = _strict_string(value, label)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AuditError(f"{label} must be an ISO-8601 timestamp") from exc
    else:
        raise AuditError(f"{label} must be an ISO-8601 timestamp or null")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuditError(f"{label} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def is_parquet_path(path: str) -> bool:
    return path.rsplit(".", 1)[-1].casefold() == "parquet"


def statute_code_from_path(path: str) -> str | None:
    match = _STATUTE_PATH_RE.fullmatch(path)
    if match is None:
        return None
    return match.group(1).upper()


def guess_media_type(path: str) -> str:
    lowered = path.casefold()
    if lowered.endswith(".parquet"):
        return "application/vnd.apache.parquet"
    if lowered.endswith(".json"):
        return "application/json"
    if lowered.endswith(".md"):
        return "text/markdown"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".svg"):
        return "image/svg+xml"
    if lowered.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"


def discover_hf_token() -> str | None:
    for name in HF_TOKEN_ENV_VARS:
        value = os.environ.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    try:
        from huggingface_hub.utils import get_token

        value = get_token()
    except Exception:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def normalize_listing_object(value: Any) -> dict[str, Any]:
    mapping = value if isinstance(value, Mapping) else None
    object_type = _source_field(value, "type", "kind", default="file")
    if isinstance(object_type, str) and object_type.casefold() in {"directory", "folder"}:
        raise AuditError("directory entries are excluded from the object inventory")
    path = _posix_path(_source_field(value, "path", "key", "name"), "path")
    size = _source_field(value, "size_bytes", "size")
    size_bytes = _non_negative_int(size, f"{path}.size_bytes")
    xet_hash = _sha256_hex(
        _source_field(value, "xet_hash", "xetHash", "xet_identity"),
        f"{path}.xet_hash",
    )
    guessed = guess_media_type(path)
    media_type = _source_field(
        value, "media_type", "content_type", "contentType", "mime_type"
    )
    if guessed != "application/octet-stream":
        media_type = guessed
    elif media_type is None:
        media_type = guessed
    media_type = _strict_string(media_type, f"{path}.media_type").casefold()
    uploaded_at = normalize_timestamp(
        _source_field(value, "uploaded_at", "uploadedAt", "upload_time"),
        label=f"{path}.uploaded_at",
    )
    mtime = normalize_timestamp(_source_field(value, "mtime"), label=f"{path}.mtime")
    return {
        "media_type": media_type,
        "mtime": mtime,
        "path": path,
        "size_bytes": size_bytes,
        "type": "file",
        "uploaded_at": uploaded_at,
        "xet_hash": xet_hash,
    }


def normalize_listing_objects(values: Sequence[Any]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for index, item in enumerate(values):
        object_type = _source_field(item, "type", "kind", default="file")
        if isinstance(object_type, str) and object_type.casefold() in {
            "directory",
            "folder",
        }:
            continue
        try:
            objects.append(normalize_listing_object(item))
        except AuditError as exc:
            raise AuditError(f"objects[{index}]: {exc}") from exc
    paths = [item["path"] for item in objects]
    if len(paths) != len(set(paths)):
        raise AuditError("bucket listing paths must be unique")
    objects.sort(key=lambda item: item["path"])
    return objects


def canonical_object_record(item: Mapping[str, Any]) -> dict[str, Any]:
    uploaded_at = item.get("uploaded_at")
    return {
        "path": _posix_path(item.get("path"), "path"),
        "size_bytes": _non_negative_int(item.get("size_bytes"), "size_bytes"),
        "type": "file",
        "uploaded_at": uploaded_at if uploaded_at is not None else "",
        "xet_hash": _sha256_hex(item.get("xet_hash"), "xet_hash"),
    }


def canonical_object_records(objects: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = [canonical_object_record(item) for item in objects]
    records.sort(key=lambda item: item["path"])
    return records


def inventory_digest_sha256(objects: Sequence[Mapping[str, Any]]) -> str:
    return sha256_canonical(canonical_object_records(objects))


def listing_digest_sha256(objects: Sequence[Mapping[str, Any]], *, bucket_id: str = BUCKET_ID) -> str:
    listing = {
        "bucket_id": bucket_id,
        "objects": [
            {
                "media_type": item["media_type"],
                "mtime": item.get("mtime"),
                "path": item["path"],
                "size_bytes": item["size_bytes"],
                "uploaded_at": item.get("uploaded_at"),
                "xet_hash": item["xet_hash"],
            }
            for item in sorted(objects, key=lambda item: item["path"])
        ],
        "prefix": "",
        "schema_version": "huggingface-bucket-listing/v1",
    }
    return sha256_canonical(listing)


def parse_checksum_entries(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, (bytes, bytearray)):
        text = bytes(payload).decode("utf-8")
        try:
            payload = json.loads(text)
        except ValueError:
            payload = text
    if isinstance(payload, str):
        entries: list[dict[str, Any]] = []
        for line_number, raw_line in enumerate(payload.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                raise AuditError(f"SHA256SUMS.json line {line_number} is malformed")
            digest = parts[0].casefold()
            path = parts[-1].lstrip("*")
            entries.append(
                {
                    "path": _posix_path(path, f"checksum[{line_number}].path"),
                    "sha256": _sha256_hex(digest, f"checksum[{line_number}].sha256"),
                    "size_bytes": None,
                }
            )
        return sorted(entries, key=lambda item: item["path"])
    if isinstance(payload, list):
        raw_entries = payload
    else:
        mapping = _strict_mapping(payload, "SHA256SUMS.json")
        raw_entries = mapping.get("files", mapping.get("objects", mapping.get("entries")))
        if raw_entries is None and all(
            isinstance(key, str) and key not in {"schema", "schema_version", "generated_at"}
            for key in mapping
        ):
            raw_entries = mapping
    if isinstance(raw_entries, Mapping):
        entries = []
        for path, spec in raw_entries.items():
            if isinstance(spec, Mapping):
                digest = _source_field(spec, "sha256", "digest", "checksum")
                size = _source_field(spec, "size_bytes", "size", "bytes")
            else:
                digest = spec
                size = None
            entries.append(
                {
                    "path": _posix_path(path, "checksum.path"),
                    "sha256": _sha256_hex(digest, f"{path}.sha256"),
                    "size_bytes": None
                    if size is None
                    else _non_negative_int(size, f"{path}.size_bytes"),
                }
            )
        return sorted(entries, key=lambda item: item["path"])
    if isinstance(raw_entries, list):
        entries = []
        for index, item in enumerate(raw_entries):
            row = _strict_mapping(item, f"checksum[{index}]")
            path = _posix_path(
                _source_field(row, "path", "file", "name"), f"checksum[{index}].path"
            )
            digest = _sha256_hex(
                _source_field(row, "sha256", "digest", "checksum"),
                f"checksum[{index}].sha256",
            )
            size = _source_field(row, "size_bytes", "size", "bytes")
            entries.append(
                {
                    "path": path,
                    "sha256": digest,
                    "size_bytes": None
                    if size is None
                    else _non_negative_int(size, f"checksum[{index}].size_bytes"),
                }
            )
        return sorted(entries, key=lambda item: item["path"])
    raise AuditError("SHA256SUMS.json must be a mapping, list, or text checksum file")


def reconcile_checksum_entries(
    objects: Sequence[Mapping[str, Any]],
    checksum_entries: Sequence[Mapping[str, Any]],
    *,
    checksum_bytes_sha256: str | None,
) -> dict[str, Any]:
    live = {item["path"]: item for item in objects}
    listed = {item["path"]: item for item in checksum_entries}
    withdrawn_still_listed = [
        path for path in _WITHDRAWN_STATUTE_PATHS if path in listed and path not in live
    ]
    missing_from_live = sorted(path for path in listed if path not in live)
    live_missing_from_manifest = sorted(
        path for path in live if is_parquet_path(path) and path not in listed
    )
    mismatches: list[dict[str, Any]] = []
    for path, entry in listed.items():
        live_item = live.get(path)
        if live_item is None:
            continue
        expected_size = entry.get("size_bytes")
        if expected_size is not None and expected_size != live_item["size_bytes"]:
            mismatches.append(
                {
                    "path": path,
                    "kind": "size",
                    "checksum_size_bytes": expected_size,
                    "live_size_bytes": live_item["size_bytes"],
                }
            )
    stale = bool(
        withdrawn_still_listed
        or mismatches
        or (
            checksum_bytes_sha256 is not None
            and checksum_bytes_sha256 == STALE_SHA256SUMS_DIGEST
        )
    )
    return {
        "path": CHECKSUM_MANIFEST_PATH,
        "bytes_sha256": checksum_bytes_sha256,
        "expected_stale_bytes_sha256": STALE_SHA256SUMS_DIGEST,
        "stale": stale,
        "entry_count": len(checksum_entries),
        "entries": [dict(item) for item in checksum_entries],
        "withdrawn_paths_still_listed": withdrawn_still_listed,
        "checksum_paths_missing_from_live": missing_from_live,
        "live_parquet_paths_missing_from_checksum": live_missing_from_manifest,
        "size_or_digest_mismatches": mismatches,
        "stale_entry_count": len(missing_from_live) + len(mismatches),
    }


def independent_reconciliation(
    objects: Sequence[Mapping[str, Any]],
    *,
    checksum_manifest: Mapping[str, Any],
    observed_at: str,
    expected_object_count: int = EXPECTED_OBJECT_COUNT,
    expected_parquet_count: int = EXPECTED_PARQUET_COUNT,
    expected_total_size_bytes: int = EXPECTED_TOTAL_SIZE_BYTES,
) -> dict[str, Any]:
    listed_count = len(objects)
    parquet_paths = [item["path"] for item in objects if is_parquet_path(item["path"])]
    control_paths = [item["path"] for item in objects if not is_parquet_path(item["path"])]
    total_size = sum(int(item["size_bytes"]) for item in objects)
    xet_hashes = [item["xet_hash"] for item in objects]
    missing_xet = [item["path"] for item in objects if not _SHA256_RE.fullmatch(str(item["xet_hash"]))]
    statute_codes = []
    for item in objects:
        code = statute_code_from_path(item["path"])
        if code is not None:
            statute_codes.append(code)
    present = set(statute_codes)
    if any(code not in REQUIRED_JURISDICTION_CODES for code in ABSENT_REQUIRED_STATUTE_CODES):
        raise AuditError("absent required statute codes must be members of the exact-51 set")
    absent = [code for code in ABSENT_REQUIRED_STATUTE_CODES if code not in present]
    stale_entries = int(checksum_manifest.get("stale_entry_count") or 0)
    return {
        "object_count": {
            "independent": listed_count,
            "expected": expected_object_count,
            "match": listed_count == expected_object_count,
        },
        "parquet_count": {
            "independent": len(parquet_paths),
            "expected": expected_parquet_count,
            "match": len(parquet_paths) == expected_parquet_count,
        },
        "control_object_count": {
            "independent": len(control_paths),
            "expected": EXPECTED_CONTROL_OBJECT_COUNT,
            "match": len(control_paths) == EXPECTED_CONTROL_OBJECT_COUNT,
        },
        "total_size_bytes": {
            "independent": total_size,
            "expected": expected_total_size_bytes,
            "match": total_size == expected_total_size_bytes,
        },
        "xet_hashes": {
            "present": len(xet_hashes) - len(missing_xet),
            "missing": len(missing_xet),
            "unique": len(set(xet_hashes)) == len(xet_hashes),
            "match": not missing_xet and len(xet_hashes) == listed_count,
        },
        "observation_time": {
            "recorded": bool(observed_at),
            "value": observed_at,
            "match": bool(_UTC_RE.fullmatch(observed_at or "")),
        },
        "stale_checksum_entries": {
            "independent": stale_entries,
            "withdrawn_paths_still_listed": list(
                checksum_manifest.get("withdrawn_paths_still_listed") or []
            ),
            "stale": checksum_manifest.get("stale") is True,
            "match": checksum_manifest.get("stale") is True and stale_entries >= 2,
        },
        "absent_required_statute_codes": {
            "independent": absent,
            "expected": list(ABSENT_REQUIRED_STATUTE_CODES),
            "match": absent == list(ABSENT_REQUIRED_STATUTE_CODES),
        },
        "live_statute_codes": statute_codes,
        "live_parquet_paths": parquet_paths,
        "control_object_paths": control_paths,
    }


def _count_match(block: Mapping[str, Any], label: str) -> None:
    if block.get("match") is not True:
        raise AuditError(f"{label} failed independent reconciliation: {dict(block)}")


def assert_reconciliation_matches(reconciliation: Mapping[str, Any], *, require_live: bool) -> None:
    _count_match(_strict_mapping(reconciliation.get("object_count"), "object_count"), "object_count")
    _count_match(_strict_mapping(reconciliation.get("parquet_count"), "parquet_count"), "parquet_count")
    _count_match(
        _strict_mapping(reconciliation.get("total_size_bytes"), "total_size_bytes"),
        "total_size_bytes",
    )
    _count_match(_strict_mapping(reconciliation.get("xet_hashes"), "xet_hashes"), "xet_hashes")
    _count_match(
        _strict_mapping(reconciliation.get("observation_time"), "observation_time"),
        "observation_time",
    )
    stale = _strict_mapping(
        reconciliation.get("stale_checksum_entries"), "stale_checksum_entries"
    )
    _count_match(stale, "stale_checksum_entries")
    absent = _strict_mapping(
        reconciliation.get("absent_required_statute_codes"),
        "absent_required_statute_codes",
    )
    _count_match(absent, "absent_required_statute_codes")
    if require_live:
        control = _strict_mapping(
            reconciliation.get("control_object_count"), "control_object_count"
        )
        _count_match(control, "control_object_count")


def build_snapshot_payload(
    objects: Sequence[Mapping[str, Any]],
    *,
    observed_at: str,
    checksum_entries: Sequence[Mapping[str, Any]] | None = None,
    checksum_bytes_sha256: str | None = None,
    token_presented: bool = False,
    listing_mode: str = LISTING_MODE_AUTHENTICATED_RECURSIVE,
    expected_object_count: int = EXPECTED_OBJECT_COUNT,
    expected_parquet_count: int = EXPECTED_PARQUET_COUNT,
    expected_total_size_bytes: int = EXPECTED_TOTAL_SIZE_BYTES,
    require_expected_totals: bool = True,
) -> dict[str, Any]:
    normalized = normalize_listing_objects(objects)
    observed = _utc_timestamp(observed_at, "observed_at")
    checksum_manifest = reconcile_checksum_entries(
        normalized,
        list(checksum_entries or []),
        checksum_bytes_sha256=checksum_bytes_sha256,
    )
    reconciliation = independent_reconciliation(
        normalized,
        checksum_manifest=checksum_manifest,
        observed_at=observed,
        expected_object_count=expected_object_count,
        expected_parquet_count=expected_parquet_count,
        expected_total_size_bytes=expected_total_size_bytes,
    )
    if require_expected_totals:
        assert_reconciliation_matches(reconciliation, require_live=True)
    records = canonical_object_records(normalized)
    inventory_digest = sha256_canonical(records)
    listing_digest = listing_digest_sha256(normalized)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "bucket_id": BUCKET_ID,
        "snapshot_label": SNAPSHOT_LABEL,
        "sources_observed_on": SOURCES_OBSERVED_ON,
        "withdrawn_on": WITHDRAWN_ON,
        "observed_at": observed,
        "listing_mode": listing_mode,
        "authenticated": True,
        "recursive": True,
        "token_presented": bool(token_presented),
        "bucket_is_mutable": True,
        "revision_pin": False,
        "grants_authority": False,
        "authorizing_for_publication": False,
        "descriptor_is_authoritative": False,
        "provisional_digest_authorizes_downstream": False,
        "description": SNAPSHOT_DESCRIPTION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "canonical_algorithm": {
            "id": CANONICAL_ALGORITHM_ID,
            "fields": list(CANONICAL_RECORD_FIELDS),
            "sort": "path_lexicographic",
            "encoding": CANONICAL_ENCODING,
            "hash": "sha256",
        },
        "expected": {
            "object_count": expected_object_count,
            "parquet_count": expected_parquet_count,
            "control_object_count": EXPECTED_CONTROL_OBJECT_COUNT,
            "total_size_bytes": expected_total_size_bytes,
            "absent_required_statute_codes": list(ABSENT_REQUIRED_STATUTE_CODES),
            "stale_checksum_bytes_sha256": STALE_SHA256SUMS_DIGEST,
        },
        "objects": normalized,
        "canonical_records": records,
        "inventory_digest_sha256": inventory_digest,
        "listing_sha256": listing_digest,
        "provisional_inventory_digest_sha256": PROVISIONAL_INVENTORY_DIGEST,
        "checksum_manifest": checksum_manifest,
        "reconciliation": reconciliation,
    }
    payload["snapshot_digest_sha256"] = sha256_snapshot_json(
        {key: value for key, value in payload.items() if key != "snapshot_digest_sha256"}
    )
    return payload


def encode_snapshot(payload: Mapping[str, Any]) -> bytes:
    return snapshot_json_bytes(payload)


def load_snapshot(path: Path | None = None) -> dict[str, Any]:
    target = path or default_snapshot_path()
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise AuditError(f"unable to read bucket snapshot: {exc}") from exc


def load_schema(path: Path | None = None) -> dict[str, Any]:
    target = path or default_schema_path()
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise AuditError(f"unable to read bucket snapshot schema: {exc}") from exc


def _validate_schema_with_jsonschema(payload: Mapping[str, Any]) -> None:
    schema = load_schema()
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        _validate_schema_structurally(payload)
        return
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise AuditError(f"schema validation failed at {location}: {first.message}")


def _validate_schema_structurally(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "producer",
        "program_id",
        "task_id",
        "goal_id",
        "bucket_id",
        "observed_at",
        "listing_mode",
        "authenticated",
        "recursive",
        "bucket_is_mutable",
        "revision_pin",
        "grants_authority",
        "authorizing_for_publication",
        "objects",
        "canonical_records",
        "inventory_digest_sha256",
        "checksum_manifest",
        "reconciliation",
        "snapshot_digest_sha256",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise AuditError("snapshot is missing required fields: " + ",".join(missing))


def validate_snapshot(payload: Mapping[str, Any], *, require_live: bool = True) -> dict[str, Any]:
    mapping = _strict_mapping(payload, "bucket_snapshot")
    if mapping.get("schema_version") != SCHEMA_VERSION:
        raise AuditError("schema_version must be open-us-law-bucket-snapshot-v1")
    if mapping.get("producer") != PRODUCER:
        raise AuditError(f"producer must be {PRODUCER}")
    if mapping.get("program_id") != PROGRAM_ID:
        raise AuditError(f"program_id must be {PROGRAM_ID}")
    if mapping.get("task_id") != TASK_ID:
        raise AuditError(f"task_id must be {TASK_ID}")
    if mapping.get("goal_id") != GOAL_ID:
        raise AuditError(f"goal_id must be {GOAL_ID}")
    if mapping.get("bucket_id") != BUCKET_ID:
        raise AuditError(f"bucket_id must be {BUCKET_ID}")
    observed_at = _utc_timestamp(mapping.get("observed_at"), "observed_at")
    if mapping.get("revision_pin") is not False:
        raise AuditError("mutable bucket snapshot must not be a revision pin")
    if mapping.get("grants_authority") is not False:
        raise AuditError("bucket snapshot must not grant authority")
    if mapping.get("authorizing_for_publication") is not False:
        raise AuditError("bucket snapshot cannot authorize publication")
    if mapping.get("bucket_is_mutable") is not True:
        raise AuditError("bucket_is_mutable must be true")
    if mapping.get("descriptor_is_authoritative") is not False:
        raise AuditError("descriptor_is_authoritative must be false")
    if mapping.get("provisional_digest_authorizes_downstream") is not False:
        raise AuditError("provisional inventory digest cannot authorize downstream work")
    if mapping.get("provisional_inventory_digest_sha256") != PROVISIONAL_INVENTORY_DIGEST:
        raise AuditError("provisional_inventory_digest_sha256 does not match the plan note")
    algorithm = _strict_mapping(mapping.get("canonical_algorithm"), "canonical_algorithm")
    if algorithm.get("id") != CANONICAL_ALGORITHM_ID:
        raise AuditError("canonical_algorithm.id is not the sealed object-list algorithm")
    if algorithm.get("fields") != list(CANONICAL_RECORD_FIELDS):
        raise AuditError("canonical_algorithm.fields must be path/type/size/Xet/upload-time")
    if algorithm.get("sort") != "path_lexicographic":
        raise AuditError("canonical records must be path-lexicographically sorted")
    if algorithm.get("encoding") != CANONICAL_ENCODING:
        raise AuditError("canonical_algorithm.encoding must be ir-canonical-json-v1")
    if algorithm.get("hash") != "sha256":
        raise AuditError("canonical_algorithm.hash must be sha256")

    objects = normalize_listing_objects(mapping.get("objects") or [])
    declared_records = mapping.get("canonical_records")
    if not isinstance(declared_records, list):
        raise AuditError("canonical_records must be a list")
    expected_records = canonical_object_records(objects)
    if declared_records != expected_records:
        raise AuditError("canonical_records do not match the independently sorted object list")
    inventory_digest = _sha256_hex(
        mapping.get("inventory_digest_sha256"), "inventory_digest_sha256"
    )
    if inventory_digest != sha256_canonical(expected_records):
        raise AuditError("inventory_digest_sha256 does not match the canonical object list")
    listing_digest = _sha256_hex(mapping.get("listing_sha256"), "listing_sha256")
    if listing_digest != listing_digest_sha256(objects):
        raise AuditError("listing_sha256 does not match the independently hashed listing")
    if inventory_digest == listing_digest:
        raise AuditError("inventory and listing digests must be independently derived")

    checksum_manifest = _strict_mapping(mapping.get("checksum_manifest"), "checksum_manifest")
    checksum_bytes = checksum_manifest.get("bytes_sha256")
    checksum_digest = (
        _sha256_hex(checksum_bytes, "checksum_manifest.bytes_sha256")
        if checksum_bytes is not None
        else None
    )
    recomputed_checksum = reconcile_checksum_entries(
        objects,
        checksum_manifest.get("entries") or [],
        checksum_bytes_sha256=checksum_digest,
    )
    for key in (
        "stale",
        "withdrawn_paths_still_listed",
        "checksum_paths_missing_from_live",
        "stale_entry_count",
    ):
        if checksum_manifest.get(key) != recomputed_checksum.get(key):
            raise AuditError(f"checksum_manifest.{key} failed independent reconciliation")
    if checksum_digest != STALE_SHA256SUMS_DIGEST:
        raise AuditError("checksum bytes digest is not the sealed stale SHA256SUMS.json digest")
    if recomputed_checksum.get("stale") is not True:
        raise AuditError("checksum manifest must be independently classified as stale")
    withdrawn = list(recomputed_checksum.get("withdrawn_paths_still_listed") or [])
    if withdrawn != list(_WITHDRAWN_STATUTE_PATHS):
        raise AuditError("stale checksum entries must still list withdrawn GA and NC statutes")

    reconciliation = independent_reconciliation(
        objects,
        checksum_manifest=recomputed_checksum,
        observed_at=observed_at,
    )
    declared_reconciliation = _strict_mapping(mapping.get("reconciliation"), "reconciliation")
    for key in (
        "object_count",
        "parquet_count",
        "total_size_bytes",
        "xet_hashes",
        "observation_time",
        "stale_checksum_entries",
        "absent_required_statute_codes",
    ):
        if declared_reconciliation.get(key) != reconciliation.get(key):
            raise AuditError(f"reconciliation.{key} failed independent recomputation")
    assert_reconciliation_matches(reconciliation, require_live=require_live)

    if require_live:
        if mapping.get("listing_mode") != LISTING_MODE_AUTHENTICATED_RECURSIVE:
            raise AuditError("require-live needs an authenticated recursive listing")
        if mapping.get("authenticated") is not True:
            raise AuditError("require-live needs authenticated=true")
        if mapping.get("recursive") is not True:
            raise AuditError("require-live needs recursive=true")
        if mapping.get("snapshot_label") != SNAPSHOT_LABEL:
            raise AuditError("snapshot_label must be v2026.07")

    body = {key: value for key, value in mapping.items() if key != "snapshot_digest_sha256"}
    expected_digest = sha256_snapshot_json(body)
    digest = _sha256_hex(mapping.get("snapshot_digest_sha256"), "snapshot_digest_sha256")
    if digest != expected_digest:
        raise AuditError("snapshot_digest_sha256 does not match the canonical snapshot bytes")

    _validate_schema_with_jsonschema(mapping)
    return {
        "object_count": reconciliation["object_count"]["independent"],
        "parquet_count": reconciliation["parquet_count"]["independent"],
        "total_size_bytes": reconciliation["total_size_bytes"]["independent"],
        "stale_checksum_entry_count": reconciliation["stale_checksum_entries"]["independent"],
        "inventory_digest_sha256": inventory_digest,
        "listing_sha256": listing_digest,
        "observed_at": observed_at,
        "revision_pin": False,
        "snapshot_digest_sha256": digest,
    }


def audit_bucket_snapshot(
    payload: Mapping[str, Any] | None = None, *, require_live: bool = True
) -> dict[str, Any]:
    snapshot = payload if payload is not None else load_snapshot()
    projection = validate_snapshot(snapshot, require_live=require_live)
    report = {
        "report_schema": REPORT_SCHEMA,
        "code_version": CODE_VERSION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "status": "passed",
        "require_live": require_live,
        "authorizing_for_publication": False,
        "revision_pin": False,
        "bucket_is_mutable": True,
        "grants_authority": False,
        **projection,
    }
    report["report_digest_sha256"] = sha256_snapshot_json(report)
    return report


def check_committed_snapshot(*, require_live: bool = True) -> dict[str, Any]:
    return audit_bucket_snapshot(load_snapshot(), require_live=require_live)


def observe_live_bucket(
    *,
    client: Any | None = None,
    token: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    from ipfs_datasets_py.huggingface.bucket import (
        HuggingFaceBucketHttpClient,
        HuggingFaceBucketStore,
    )

    presented = token if token is not None else discover_hf_token()
    http_client = client or HuggingFaceBucketHttpClient(
        token=presented, timeout_seconds=120.0
    )
    store = HuggingFaceBucketStore(BUCKET_ID, client=http_client)
    listing = store.discover()
    objects = [item.to_dict() | {"type": "file"} for item in listing.objects]
    checksum_entries: list[dict[str, Any]] = []
    checksum_digest: str | None = None
    checksum_item = next(
        (item for item in listing.objects if item.path == CHECKSUM_MANIFEST_PATH),
        None,
    )
    if checksum_item is not None:
        download = getattr(http_client, "download_bucket_file", None)
        if not callable(download):
            raise AuditError("bucket client cannot download SHA256SUMS.json")
        import tempfile

        handle, tmp_name = tempfile.mkstemp(prefix="oul-001-sha256sums-", suffix=".json")
        os.close(handle)
        tmp_path = Path(tmp_name)
        try:
            download(
                bucket_id=BUCKET_ID,
                path=CHECKSUM_MANIFEST_PATH,
                destination=tmp_path,
                expected_xet_hash=checksum_item.xet_hash,
                expected_size_bytes=checksum_item.size_bytes,
            )
            raw = tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)
        checksum_digest = sha256_bytes(raw)
        checksum_entries = parse_checksum_entries(raw)
    return build_snapshot_payload(
        objects,
        observed_at=observed_at or utc_now(),
        checksum_entries=checksum_entries,
        checksum_bytes_sha256=checksum_digest,
        token_presented=presented is not None,
        listing_mode=LISTING_MODE_AUTHENTICATED_RECURSIVE,
    )


def write_snapshot(payload: Mapping[str, Any], path: Path | None = None) -> Path:
    target = path or default_snapshot_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode_snapshot(payload))
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the live open-us-law bucket inventory snapshot"
    )
    parser.add_argument(
        "--require-live",
        dest="require_live",
        action="store_true",
        help=(
            "Require the committed snapshot to be a live authenticated recursive "
            "listing with independently reconciled 107/103/stale-checksum facts."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the committed snapshot without contacting the mutable bucket.",
    )
    parser.add_argument(
        "--observe",
        action="store_true",
        help="Perform a live authenticated recursive listing and write the snapshot.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the audit report as JSON.")
    return parser


def _print_json(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.observe:
        try:
            payload = observe_live_bucket()
            write_snapshot(payload)
            report = audit_bucket_snapshot(payload, require_live=True)
        except (AuditError, Exception) as exc:
            message = str(exc)
            if args.json:
                _print_json(
                    {
                        "status": "failed",
                        "producer": PRODUCER,
                        "program_id": PROGRAM_ID,
                        "task_id": TASK_ID,
                        "authorizing_for_publication": False,
                        "revision_pin": False,
                        "error": message,
                    }
                )
            else:
                sys.stderr.write(f"audit_open_us_law_bucket: FAILED: {message}\n")
            return 1
        if args.json:
            _print_json(report)
        else:
            sys.stdout.write(
                "audit_open_us_law_bucket: OBSERVED "
                f"(objects={report['object_count']} "
                f"parquets={report['parquet_count']} "
                f"digest={report['inventory_digest_sha256']})\n"
            )
        return 0
    if not args.check:
        sys.stderr.write("audit_open_us_law_bucket: FAILED: --check is required\n")
        return 2
    if not args.require_live:
        sys.stderr.write("audit_open_us_law_bucket: FAILED: --require-live is required\n")
        return 2
    try:
        report = check_committed_snapshot(require_live=True)
    except AuditError as exc:
        if args.json:
            _print_json(
                {
                    "status": "failed",
                    "producer": PRODUCER,
                    "program_id": PROGRAM_ID,
                    "task_id": TASK_ID,
                    "authorizing_for_publication": False,
                    "revision_pin": False,
                    "error": str(exc),
                }
            )
        else:
            sys.stderr.write(f"audit_open_us_law_bucket: FAILED: {exc}\n")
        return 1
    if args.json:
        _print_json(report)
    else:
        sys.stdout.write(
            "audit_open_us_law_bucket: PASSED "
            f"(objects={report['object_count']} "
            f"parquets={report['parquet_count']} "
            f"bytes={report['total_size_bytes']} "
            f"revision_pin={report['revision_pin']})\n"
            f"  observed_at={report['observed_at']}\n"
            f"  inventory_digest={report['inventory_digest_sha256']}\n"
            f"  stale_checksum_entries={report['stale_checksum_entry_count']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

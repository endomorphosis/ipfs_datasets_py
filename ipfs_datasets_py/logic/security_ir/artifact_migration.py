"""Deterministic, reversible migration records for legacy Security artifacts.

The migration described by this module is a map, not a file-moving operation.
Legacy files remain byte-for-byte in place.  Each inventory record receives a
content binding, a stable v1 path, and one of the five migration classes:
``source``, ``golden``, ``run``, ``promoted``, or ``archive``.

Ambiguous, transient, and unknown files are retained in ``archive`` and carry
explicit flags.  In particular, filename variants never select authority.

Manifest identity covers the ``deterministic`` section only.  Producer guesses,
operator recommendations, environment details, and other observations remain
available in the ``observational`` section without changing ``migration_id``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from types import MappingProxyType
from typing import Any, Final


SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION: Final = (
    "SecurityArtifactMigration@1"
)
DEFAULT_INVENTORY_PATH: Final = (
    "docs/security_verification/security_ir_artifact_inventory.json"
)
DEFAULT_MANIFEST_PATH: Final = "security_ir_artifacts/migrations/manifest.json"
LEGACY_ARTIFACT_ROOT: Final = "security_ir_artifacts"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ArtifactMigrationError(ValueError):
    """Raised when a migration manifest or source inventory is invalid."""


class ArtifactMigrationIntegrityError(ArtifactMigrationError):
    """Raised when legacy bytes no longer agree with their migration records."""

    def __init__(self, receipt: "MigrationIntegrityReceipt") -> None:
        self.receipt = receipt
        super().__init__("; ".join(receipt.issues) or "migration integrity failed")


class ArtifactClass(str, Enum):
    """The complete set of Security artifact migration destinations."""

    SOURCE = "source"
    GOLDEN = "golden"
    RUN = "run"
    PROMOTED = "promoted"
    ARCHIVE = "archive"


class MigrationFlag(str, Enum):
    """Conditions that prevent silent use as authoritative evidence."""

    AMBIGUOUS = "ambiguous"
    MUTABLE_ALIAS = "mutable_alias"
    OBSERVATIONAL_CONTENT = "observational_content"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


_INVENTORY_CLASS_MAP: Final[Mapping[str, ArtifactClass]] = MappingProxyType(
    {
        "source": ArtifactClass.SOURCE,
        "golden": ArtifactClass.GOLDEN,
        "run output": ArtifactClass.RUN,
        "environment record": ArtifactClass.RUN,
        "promoted evidence": ArtifactClass.PROMOTED,
        "transient compiler output": ArtifactClass.ARCHIVE,
        "ambiguous": ArtifactClass.ARCHIVE,
        "unknown": ArtifactClass.ARCHIVE,
    }
)

_CLASS_PREFIX: Final[Mapping[ArtifactClass, str]] = MappingProxyType(
    {
        ArtifactClass.SOURCE: "inputs",
        ArtifactClass.GOLDEN: "golden",
        ArtifactClass.RUN: "runs/legacy",
        ArtifactClass.PROMOTED: "promoted",
        ArtifactClass.ARCHIVE: "archive",
    }
)

_DETERMINISTIC_RECORD_FIELDS: Final = (
    "artifact_class",
    "flags",
    "legacy_ids",
    "legacy_path",
    "legacy_sha256",
    "record_id",
    "size_bytes",
    "source_classification",
    "source_format",
    "v1_artifact_id",
    "v1_content_sha256",
    "v1_path",
)
_OBSERVATIONAL_RECORD_FIELDS: Final = (
    "ambiguity_reasons",
    "authority_selected",
    "likely_producers",
    "recommendations",
    "variant_kinds",
    "variant_of",
)
_DETERMINISTIC_MANIFEST_FIELDS: Final = frozenset(
    {
        "classification_policy",
        "field_partition",
        "legacy_artifact_count",
        "legacy_total_size_bytes",
        "record_counts_by_class",
        "record_counts_by_flag",
        "records",
        "source_inventory",
    }
)
_OBSERVATIONAL_MANIFEST_FIELDS: Final = frozenset(
    {
        "authority_decisions_made",
        "inventory_scope",
        "legacy_classification_counts",
        "legacy_format_counts",
        "legacy_id_extraction",
        "notes",
        "records",
        "variant_groups",
    }
)


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactMigrationError(
            "migration data must contain only finite JSON values"
        ) from exc


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactMigrationError(f"{label} must be a mapping")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ArtifactMigrationError(f"{label} must be a sequence")
    return value


def _normalized_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ArtifactMigrationError(f"{label} must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ArtifactMigrationError(
            f"{label} must be a normalized repository-relative POSIX path"
        )
    return value


def _sha256(value: Any, label: str, *, qualified: bool = False) -> str:
    expression = _DIGEST_RE if qualified else _SHA256_RE
    if not isinstance(value, str) or not expression.fullmatch(value):
        qualifier = "sha256:" if qualified else ""
        raise ArtifactMigrationError(
            f"{label} must be {qualifier} followed by 64 lowercase hexadecimal "
            "characters"
        )
    return value


def _legacy_relative_path(legacy_path: str) -> str:
    normalized = _normalized_path(legacy_path, "legacy_path")
    prefix = f"{LEGACY_ARTIFACT_ROOT}/"
    if not normalized.startswith(prefix):
        raise ArtifactMigrationError(
            f"legacy_path must be below {LEGACY_ARTIFACT_ROOT!r}"
        )
    relative = normalized.removeprefix(prefix)
    if relative.startswith("migrations/"):
        raise ArtifactMigrationError(
            "migration manifests are v1 metadata, not legacy artifacts"
        )
    return relative


def _target_path(legacy_path: str, artifact_class: ArtifactClass) -> str:
    relative = _legacy_relative_path(legacy_path)
    return (
        f"{LEGACY_ARTIFACT_ROOT}/{_CLASS_PREFIX[artifact_class]}/{relative}"
    )


def _legacy_ids(value: Any) -> list[dict[str, str]]:
    ids: list[dict[str, str]] = []
    for index, item in enumerate(_sequence(value, "legacy_ids")):
        entry = _mapping(item, f"legacy_ids[{index}]")
        if set(entry) != {"field", "value"}:
            raise ArtifactMigrationError(
                "each legacy ID must contain exactly 'field' and 'value'"
            )
        field = entry["field"]
        legacy_value = entry["value"]
        if not isinstance(field, str) or not field:
            raise ArtifactMigrationError("legacy ID field must be a non-empty string")
        if not isinstance(legacy_value, str) or not legacy_value:
            raise ArtifactMigrationError("legacy ID value must be a non-empty string")
        ids.append({"field": field, "value": legacy_value})
    expected = sorted(ids, key=lambda item: (item["field"], item["value"]))
    if ids != expected or len({(item["field"], item["value"]) for item in ids}) != len(
        ids
    ):
        raise ArtifactMigrationError("legacy_ids must be sorted and unique")
    return ids


def _flags(record: Mapping[str, Any]) -> list[str]:
    classification = str(record.get("classification") or "")
    flags: set[MigrationFlag] = set()
    if classification == "ambiguous" or record.get("is_new_variant"):
        flags.add(MigrationFlag.AMBIGUOUS)
    if classification == "transient compiler output" or record.get("is_temporary"):
        flags.add(MigrationFlag.TRANSIENT)
    if classification == "unknown":
        flags.add(MigrationFlag.UNKNOWN)
    if classification == "environment record":
        flags.add(MigrationFlag.OBSERVATIONAL_CONTENT)
    if record.get("is_mutable_alias"):
        flags.add(MigrationFlag.MUTABLE_ALIAS)
        flags.add(MigrationFlag.AMBIGUOUS)
    return sorted(flag.value for flag in flags)


def _build_record(
    record: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    classification = record.get("classification")
    try:
        artifact_class = _INVENTORY_CLASS_MAP[str(classification)]
    except KeyError as exc:
        raise ArtifactMigrationError(
            f"unsupported inventory classification: {classification!r}"
        ) from exc

    legacy_path = _normalized_path(record.get("path"), "inventory artifact path")
    legacy_sha256 = _sha256(
        record.get("sha256"), f"{legacy_path}.sha256"
    )
    size = record.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ArtifactMigrationError(
            f"{legacy_path}.size_bytes must be a non-negative integer"
        )
    source_format = record.get("detected_format")
    if not isinstance(source_format, str) or not source_format:
        raise ArtifactMigrationError(
            f"{legacy_path}.detected_format must be a non-empty string"
        )

    ids = _legacy_ids(record.get("legacy_ids", ()))
    v1_path = _target_path(legacy_path, artifact_class)
    record_preimage = {
        "artifact_class": artifact_class.value,
        "legacy_path": legacy_path,
        "legacy_sha256": legacy_sha256,
        "v1_path": v1_path,
    }
    deterministic = {
        "artifact_class": artifact_class.value,
        "flags": _flags(record),
        "legacy_ids": ids,
        "legacy_path": legacy_path,
        "legacy_sha256": legacy_sha256,
        "record_id": _digest(record_preimage),
        "size_bytes": size,
        "source_classification": classification,
        "source_format": source_format,
        "v1_artifact_id": f"sha256:{legacy_sha256}",
        "v1_content_sha256": legacy_sha256,
        "v1_path": v1_path,
    }
    observational = {
        "record_id": deterministic["record_id"],
        "ambiguity_reasons": list(record.get("ambiguity_reasons", ())),
        "authority_selected": bool(record.get("authority_selected", False)),
        "likely_producers": list(record.get("likely_producers", ())),
        "recommendations": list(record.get("recommendations", ())),
        "variant_kinds": list(record.get("variant_kinds", ())),
        "variant_of": record.get("variant_of"),
    }
    return deterministic, observational


def _deterministic_preimage(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": manifest.get("schema_version"),
        "deterministic": manifest.get("deterministic"),
    }


def build_migration_manifest(inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Build a complete migration manifest from a v1 read-only inventory.

    Input order has no effect.  The source inventory is not mutated.
    """

    inventory = _mapping(inventory, "inventory")
    if inventory.get("schema_version") != "SecurityArtifactInventory@1":
        raise ArtifactMigrationError(
            "inventory schema_version must be SecurityArtifactInventory@1"
        )
    inventory_sha256 = _sha256(
        inventory.get("inventory_sha256"), "inventory_sha256"
    )
    record_pairs = [
        _build_record(_mapping(record, "inventory artifact"))
        for record in _sequence(inventory.get("artifacts"), "inventory artifacts")
    ]
    record_pairs.sort(key=lambda item: item[0]["legacy_path"].encode("utf-8"))
    records = [item[0] for item in record_pairs]
    record_observations = [item[1] for item in record_pairs]

    if len(records) != inventory.get("artifact_count"):
        raise ArtifactMigrationError(
            "inventory artifact_count does not match its artifact records"
        )
    classes = Counter(record["artifact_class"] for record in records)
    flags = Counter(flag for record in records for flag in record["flags"])
    deterministic = {
        "classification_policy": {
            "inventory_to_v1": {
                key: value.value for key, value in _INVENTORY_CLASS_MAP.items()
            },
            "unreviewed_authority_policy": (
                "ambiguous, transient, and unknown artifacts remain archived"
            ),
        },
        "field_partition": {
            "deterministic_record_fields": list(_DETERMINISTIC_RECORD_FIELDS),
            "observational_record_fields": list(_OBSERVATIONAL_RECORD_FIELDS),
        },
        "legacy_artifact_count": len(records),
        "legacy_total_size_bytes": sum(
            record["size_bytes"] for record in records
        ),
        "record_counts_by_class": {
            value.value: classes.get(value.value, 0) for value in ArtifactClass
        },
        "record_counts_by_flag": {
            value.value: flags.get(value.value, 0) for value in MigrationFlag
        },
        "records": records,
        "source_inventory": {
            "artifact_root": inventory.get("artifact_root"),
            "inventory_sha256": inventory_sha256,
            "schema_version": inventory.get("schema_version"),
        },
    }
    observational = {
        "authority_decisions_made": inventory.get("authority_decisions_made", 0),
        "inventory_scope": inventory.get("scope", ""),
        "legacy_classification_counts": dict(
            inventory.get("classification_counts", {})
        ),
        "legacy_format_counts": dict(inventory.get("format_counts", {})),
        "legacy_id_extraction": inventory.get("legacy_id_extraction", ""),
        "notes": [
            "This manifest records a reversible path map; it does not move or "
            "rewrite legacy files.",
            "Observational fields are excluded from migration identity.",
        ],
        "records": record_observations,
        "variant_groups": list(inventory.get("variant_groups", ())),
    }
    manifest: dict[str, Any] = {
        "schema_version": SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION,
        "migration_id": "",
        "deterministic": deterministic,
        "observational": observational,
    }
    manifest["migration_id"] = _digest(_deterministic_preimage(manifest))
    validate_migration_manifest(manifest)
    return manifest


def _validate_record(
    deterministic: Mapping[str, Any],
    observational: Mapping[str, Any],
    *,
    seen_legacy: set[str],
    seen_v1: set[str],
    seen_records: set[str],
) -> None:
    if set(deterministic) != set(_DETERMINISTIC_RECORD_FIELDS):
        raise ArtifactMigrationError(
            "record deterministic fields do not match the v1 field partition"
        )
    if set(observational) != set(_OBSERVATIONAL_RECORD_FIELDS) | {"record_id"}:
        raise ArtifactMigrationError(
            "record observational fields do not match the v1 field partition"
        )

    try:
        artifact_class = ArtifactClass(deterministic["artifact_class"])
    except (TypeError, ValueError) as exc:
        raise ArtifactMigrationError("unsupported artifact_class") from exc
    legacy_path = _normalized_path(deterministic["legacy_path"], "legacy_path")
    _legacy_relative_path(legacy_path)
    v1_path = _normalized_path(deterministic["v1_path"], "v1_path")
    if v1_path != _target_path(legacy_path, artifact_class):
        raise ArtifactMigrationError(
            f"v1_path is not reversible for legacy path {legacy_path!r}"
        )
    legacy_sha = _sha256(deterministic["legacy_sha256"], "legacy_sha256")
    if deterministic["v1_content_sha256"] != legacy_sha:
        raise ArtifactMigrationError(
            f"v1 content hash does not preserve legacy hash for {legacy_path}"
        )
    if deterministic["v1_artifact_id"] != f"sha256:{legacy_sha}":
        raise ArtifactMigrationError(
            f"v1 artifact ID does not preserve legacy hash for {legacy_path}"
        )
    size = deterministic["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ArtifactMigrationError("size_bytes must be a non-negative integer")
    _legacy_ids(deterministic["legacy_ids"])
    if (
        not isinstance(deterministic["source_format"], str)
        or not deterministic["source_format"]
    ):
        raise ArtifactMigrationError("source_format must be a non-empty string")

    flags = deterministic["flags"]
    if (
        not isinstance(flags, list)
        or flags != sorted(set(flags))
        or any(flag not in {value.value for value in MigrationFlag} for flag in flags)
    ):
        raise ArtifactMigrationError("record flags must be sorted, unique, and known")
    source_class = deterministic["source_classification"]
    expected_class = _INVENTORY_CLASS_MAP.get(source_class)
    if expected_class is not artifact_class:
        raise ArtifactMigrationError(
            "source classification does not match artifact_class"
        )
    required_flag = {
        "ambiguous": MigrationFlag.AMBIGUOUS.value,
        "transient compiler output": MigrationFlag.TRANSIENT.value,
        "unknown": MigrationFlag.UNKNOWN.value,
    }.get(source_class)
    if required_flag and required_flag not in flags:
        raise ArtifactMigrationError(
            f"{source_class} record is missing required flag {required_flag!r}"
        )
    if required_flag and artifact_class is not ArtifactClass.ARCHIVE:
        raise ArtifactMigrationError(
            f"{source_class} record must remain in the archive class"
        )
    if required_flag and observational.get("authority_selected") is not False:
        raise ArtifactMigrationError(
            "flagged records cannot select authority without reviewed migration data"
        )

    record_preimage = {
        "artifact_class": artifact_class.value,
        "legacy_path": legacy_path,
        "legacy_sha256": legacy_sha,
        "v1_path": v1_path,
    }
    record_id = _sha256(deterministic["record_id"], "record_id", qualified=True)
    if record_id != _digest(record_preimage):
        raise ArtifactMigrationError(f"record_id does not match {legacy_path}")
    if observational["record_id"] != record_id:
        raise ArtifactMigrationError(
            f"observational record is not bound to {legacy_path}"
        )

    for value, seen, label in (
        (legacy_path, seen_legacy, "legacy_path"),
        (v1_path, seen_v1, "v1_path"),
        (record_id, seen_records, "record_id"),
    ):
        if value in seen:
            raise ArtifactMigrationError(f"duplicate {label}: {value}")
        seen.add(value)


def validate_migration_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate schema, completeness invariants, and deterministic identity."""

    manifest = _mapping(manifest, "manifest")
    if set(manifest) != {
        "schema_version",
        "migration_id",
        "deterministic",
        "observational",
    }:
        raise ArtifactMigrationError("manifest contains missing or unknown fields")
    if (
        manifest.get("schema_version")
        != SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION
    ):
        raise ArtifactMigrationError(
            f"unsupported schema_version: {manifest.get('schema_version')!r}"
        )
    deterministic = _mapping(manifest["deterministic"], "manifest.deterministic")
    observational = _mapping(manifest["observational"], "manifest.observational")
    if set(deterministic) != _DETERMINISTIC_MANIFEST_FIELDS:
        raise ArtifactMigrationError(
            "deterministic manifest fields do not match the v1 schema"
        )
    if set(observational) != _OBSERVATIONAL_MANIFEST_FIELDS:
        raise ArtifactMigrationError(
            "observational manifest fields do not match the v1 schema"
        )
    if deterministic["classification_policy"] != {
        "inventory_to_v1": {
            key: value.value for key, value in _INVENTORY_CLASS_MAP.items()
        },
        "unreviewed_authority_policy": (
            "ambiguous, transient, and unknown artifacts remain archived"
        ),
    }:
        raise ArtifactMigrationError("classification_policy is not the v1 policy")
    if deterministic["field_partition"] != {
        "deterministic_record_fields": list(_DETERMINISTIC_RECORD_FIELDS),
        "observational_record_fields": list(_OBSERVATIONAL_RECORD_FIELDS),
    }:
        raise ArtifactMigrationError("field_partition is not the v1 partition")
    source_inventory = _mapping(
        deterministic["source_inventory"], "deterministic.source_inventory"
    )
    if set(source_inventory) != {
        "artifact_root",
        "inventory_sha256",
        "schema_version",
    }:
        raise ArtifactMigrationError("source_inventory fields do not match v1")
    if source_inventory["artifact_root"] != LEGACY_ARTIFACT_ROOT:
        raise ArtifactMigrationError("source_inventory artifact_root is unsupported")
    if source_inventory["schema_version"] != "SecurityArtifactInventory@1":
        raise ArtifactMigrationError("source inventory schema is unsupported")
    _sha256(source_inventory["inventory_sha256"], "source inventory digest")
    expected_id = _digest(_deterministic_preimage(manifest))
    supplied_id = _sha256(manifest["migration_id"], "migration_id", qualified=True)

    records = _sequence(deterministic.get("records"), "deterministic.records")
    record_observations = _sequence(
        observational.get("records"), "observational.records"
    )
    if len(record_observations) != len(records):
        raise ArtifactMigrationError(
            "observational records must correspond one-to-one with "
            "deterministic records"
        )
    seen_legacy: set[str] = set()
    seen_v1: set[str] = set()
    seen_records: set[str] = set()
    ordered_paths: list[str] = []
    for item, observed_item in zip(records, record_observations, strict=True):
        record = _mapping(item, "deterministic migration record")
        observation = _mapping(observed_item, "observational migration record")
        _validate_record(
            record,
            observation,
            seen_legacy=seen_legacy,
            seen_v1=seen_v1,
            seen_records=seen_records,
        )
        ordered_paths.append(record["legacy_path"])
    if ordered_paths != sorted(ordered_paths, key=lambda value: value.encode("utf-8")):
        raise ArtifactMigrationError("migration records must be bytewise path sorted")
    if deterministic.get("legacy_artifact_count") != len(records):
        raise ArtifactMigrationError("legacy_artifact_count does not match records")
    if deterministic.get("legacy_total_size_bytes") != sum(
        item["size_bytes"] for item in records
    ):
        raise ArtifactMigrationError("legacy_total_size_bytes does not match records")

    expected_classes = Counter(item["artifact_class"] for item in records)
    if deterministic.get("record_counts_by_class") != {
        value.value: expected_classes.get(value.value, 0) for value in ArtifactClass
    }:
        raise ArtifactMigrationError("record_counts_by_class does not match records")
    expected_flags = Counter(flag for item in records for flag in item["flags"])
    if deterministic.get("record_counts_by_flag") != {
        value.value: expected_flags.get(value.value, 0) for value in MigrationFlag
    }:
        raise ArtifactMigrationError("record_counts_by_flag does not match records")
    if supplied_id != expected_id:
        raise ArtifactMigrationError(
            "migration_id does not match deterministic manifest content"
        )


def render_migration_manifest(manifest: Mapping[str, Any]) -> str:
    """Return stable, review-friendly JSON after validating the manifest."""

    validate_migration_manifest(manifest)
    return json.dumps(
        manifest, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True
    ) + "\n"


def load_migration_manifest(path: str | Path) -> dict[str, Any]:
    """Load and validate a migration manifest from disk."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactMigrationError(
            f"unable to load migration manifest: {exc}"
        ) from exc
    validate_migration_manifest(payload)
    return payload


def write_migration_manifest(
    manifest: Mapping[str, Any],
    path: str | Path,
    *,
    repo_root: str | Path,
) -> bool:
    """Atomically create/update only the designated v1 migration manifest.

    Returns ``False`` when the exact content is already present, making repeated
    generation idempotent.  No legacy artifact path is accepted as a target.
    """

    root = Path(repo_root).resolve()
    requested = Path(path)
    if not requested.is_absolute():
        requested = root / requested
    destination = Path(os.path.abspath(requested))
    expected = root.joinpath(*PurePosixPath(DEFAULT_MANIFEST_PATH).parts)
    if destination != expected:
        raise ArtifactMigrationError(
            f"migration output must be exactly {DEFAULT_MANIFEST_PATH}"
        )
    if destination.is_symlink():
        raise ArtifactMigrationError("migration output must not be a symbolic link")
    rendered = render_migration_manifest(manifest)
    if destination.exists() and destination.read_text(encoding="utf-8") == rendered:
        return False
    if not destination.parent.resolve().is_relative_to(root):
        raise ArtifactMigrationError("migration output directory escapes repo_root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".manifest.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return True


def _path_maps(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    validate_migration_manifest(manifest)
    forward = {
        item["legacy_path"]: item["v1_path"]
        for item in manifest["deterministic"]["records"]
    }
    return forward, {value: key for key, value in forward.items()}


def migrate_artifact_path(manifest: Mapping[str, Any], path: str) -> str:
    """Map a legacy path to v1; return an already-migrated path unchanged."""

    normalized = _normalized_path(path, "path")
    forward, reverse = _path_maps(manifest)
    if normalized in forward:
        return forward[normalized]
    if normalized in reverse:
        return normalized
    raise KeyError(normalized)


def reverse_artifact_path(manifest: Mapping[str, Any], path: str) -> str:
    """Map a v1 path back to its exact legacy path."""

    normalized = _normalized_path(path, "path")
    forward, reverse = _path_maps(manifest)
    if normalized in reverse:
        return reverse[normalized]
    if normalized in forward:
        return normalized
    raise KeyError(normalized)


@dataclass(frozen=True, slots=True)
class MigrationIntegrityReceipt:
    """Deterministically ordered evidence that all legacy bytes still match."""

    migration_id: str
    checked_artifact_count: int
    checked_legacy_sha256: tuple[str, ...]
    issues: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_artifact_count": self.checked_artifact_count,
            "checked_legacy_sha256": list(self.checked_legacy_sha256),
            "issues": list(self.issues),
            "migration_id": self.migration_id,
            "valid": self.valid,
        }


def audit_migration_integrity(
    manifest: Mapping[str, Any], repo_root: str | Path
) -> MigrationIntegrityReceipt:
    """Check every legacy path, size, and digest without modifying any file."""

    validate_migration_manifest(manifest)
    root = Path(repo_root).resolve()
    issues: list[str] = []
    checked_hashes: list[str] = []
    for item in manifest["deterministic"]["records"]:
        record = item
        relative = PurePosixPath(record["legacy_path"])
        path = root.joinpath(*relative.parts)
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            issues.append(f"missing:{record['legacy_path']}")
            continue
        if not resolved.is_relative_to(root) or not resolved.is_file():
            issues.append(f"invalid:{record['legacy_path']}")
            continue
        data = resolved.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        checked_hashes.append(actual)
        if len(data) != record["size_bytes"]:
            issues.append(
                f"size_changed:{record['legacy_path']}:{len(data)}"
            )
        if actual != record["legacy_sha256"]:
            issues.append(
                f"digest_changed:{record['legacy_path']}:{actual}"
            )
    return MigrationIntegrityReceipt(
        migration_id=manifest["migration_id"],
        checked_artifact_count=len(checked_hashes),
        checked_legacy_sha256=tuple(checked_hashes),
        issues=tuple(sorted(issues)),
    )


def verify_migration_integrity(
    manifest: Mapping[str, Any], repo_root: str | Path
) -> MigrationIntegrityReceipt:
    """Return an integrity receipt or raise on any missing/changed legacy file."""

    receipt = audit_migration_integrity(manifest, repo_root)
    if not receipt.valid:
        raise ArtifactMigrationIntegrityError(receipt)
    return receipt


@dataclass(frozen=True, slots=True)
class SecurityArtifactMigration:
    """Small typed facade over the JSON-compatible migration contract."""

    manifest: Mapping[str, Any]

    def __post_init__(self) -> None:
        validate_migration_manifest(self.manifest)
        # A JSON round trip gives the frozen facade its own defensive copy.
        copied = json.loads(json.dumps(self.manifest))
        object.__setattr__(self, "manifest", MappingProxyType(copied))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityArtifactMigration":
        return cls(value)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(dict(self.manifest)))

    @property
    def migration_id(self) -> str:
        return str(self.manifest["migration_id"])

    def migrate_path(self, path: str) -> str:
        return migrate_artifact_path(self.manifest, path)

    def reverse_path(self, path: str) -> str:
        return reverse_artifact_path(self.manifest, path)


__all__ = [
    "ArtifactClass",
    "ArtifactMigrationError",
    "ArtifactMigrationIntegrityError",
    "DEFAULT_INVENTORY_PATH",
    "DEFAULT_MANIFEST_PATH",
    "MigrationFlag",
    "MigrationIntegrityReceipt",
    "SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION",
    "SecurityArtifactMigration",
    "audit_migration_integrity",
    "build_migration_manifest",
    "load_migration_manifest",
    "migrate_artifact_path",
    "render_migration_manifest",
    "reverse_artifact_path",
    "validate_migration_manifest",
    "verify_migration_integrity",
    "write_migration_manifest",
]

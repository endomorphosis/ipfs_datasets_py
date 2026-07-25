"""Deterministic, reversible migration records for legacy Security artifacts.

The migration is deliberately non-destructive: it maps an existing path and
content digest to a versioned record without moving, rewriting, or deleting
the legacy file.  Ambiguous, transient, and unknown artifacts are retained as
``archive`` records and never acquire evidentiary authority from migration.

The manifest separates identity-bearing ``deterministic_fields`` from
``observational_fields`` copied from the read-only inventory.  Producer
inferences and recommendations are useful audit context, but changing them
cannot perturb a migrated record ID or the manifest digest.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Final

from ..ir_core.canonical import canonical_json_bytes


SECURITY_ARTIFACT_MIGRATION_VERSION: Final = "SecurityArtifactMigration@1"
SECURITY_ARTIFACT_RECORD_VERSION: Final = "SecurityArtifactRecord@1"
SECURITY_ARTIFACT_MIGRATION_RECEIPT_VERSION: Final = (
    "SecurityArtifactMigrationIntegrityReceipt@1"
)

DEFAULT_INVENTORY_PATH: Final = (
    "docs/security_verification/security_ir_artifact_inventory.json"
)
DEFAULT_MANIFEST_PATH: Final = "security_ir_artifacts/migrations/manifest.json"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OBSERVATIONAL_INVENTORY_FIELDS: Final = frozenset(
    {"ambiguity_reasons", "likely_producers", "recommendations"}
)
_REQUIRED_INVENTORY_FIELDS: Final = frozenset(
    {
        "ambiguity_reasons",
        "authority_selected",
        "classification",
        "detected_format",
        "file_type",
        "is_mutable_alias",
        "is_new_variant",
        "is_temporary",
        "legacy_ids",
        "likely_producers",
        "path",
        "recommendations",
        "sha256",
        "size_bytes",
        "variant_kinds",
        "variant_of",
    }
)


class ArtifactMigrationError(ValueError):
    """Base error for malformed or unsafe Security artifact migrations."""


class ArtifactMigrationIntegrityError(ArtifactMigrationError):
    """Raised when a manifest or a bound legacy artifact fails integrity checks."""

    def __init__(self, receipt: "MigrationIntegrityReceipt") -> None:
        self.receipt = receipt
        super().__init__("; ".join(receipt.issues) or "artifact migration is invalid")


class ArtifactClass(str, Enum):
    """The five v1 storage/lineage classes used by the migration."""

    SOURCE = "source"
    GOLDEN = "golden"
    RUN = "run"
    PROMOTED = "promoted"
    ARCHIVE = "archive"


# Inventory classifications intentionally map to storage/lineage classes, not
# authority.  In particular, ambiguous files are archived pending review.
_CLASS_MAP: Final = {
    "source": ArtifactClass.SOURCE,
    "golden": ArtifactClass.GOLDEN,
    "run output": ArtifactClass.RUN,
    "environment record": ArtifactClass.RUN,
    "promoted evidence": ArtifactClass.PROMOTED,
    "transient compiler output": ArtifactClass.ARCHIVE,
    "ambiguous": ArtifactClass.ARCHIVE,
    "unknown": ArtifactClass.ARCHIVE,
}


def _canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _inventory_digest(records: Sequence[Mapping[str, Any]]) -> str:
    """Reproduce the v1 inventory's documented record digest."""

    encoded = json.dumps(
        list(records),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactMigrationError(f"{label} must be a mapping")
    return value


def _require_sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ArtifactMigrationError(f"{label} must be a sequence")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ArtifactMigrationError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ArtifactMigrationError(
                f"migration manifest contains duplicate JSON key {key!r}"
            )
        value[key] = item
    return value


def _normalise_path(value: Any, *, artifact_root: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ArtifactMigrationError("legacy artifact path must be normalized POSIX text")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ArtifactMigrationError("legacy artifact path must be repository-relative")
    root = PurePosixPath(artifact_root)
    if path.parts[: len(root.parts)] != root.parts:
        raise ArtifactMigrationError(
            f"legacy artifact path must be below {artifact_root!r}"
        )
    return value


def _normalise_legacy_ids(value: Any) -> list[dict[str, str]]:
    identities: list[dict[str, str]] = []
    for index, item in enumerate(_require_sequence(value, "legacy_ids")):
        identity = _require_mapping(item, f"legacy_ids[{index}]")
        if set(identity) != {"field", "value"}:
            raise ArtifactMigrationError(
                "legacy identifier entries must contain exactly field and value"
            )
        field = identity["field"]
        legacy_value = identity["value"]
        if not isinstance(field, str) or not field:
            raise ArtifactMigrationError("legacy identifier field must not be empty")
        if not isinstance(legacy_value, str) or not legacy_value:
            raise ArtifactMigrationError("legacy identifier value must not be empty")
        identities.append({"field": field, "value": legacy_value})
    ordered = sorted(identities, key=lambda item: (item["field"], item["value"]))
    if ordered != identities or len({(x["field"], x["value"]) for x in ordered}) != len(
        ordered
    ):
        raise ArtifactMigrationError(
            "legacy identifiers must be unique and canonically ordered"
        )
    return identities


def _record_id(path: str, content_sha256: str) -> str:
    preimage = {
        "legacy_content_sha256": content_sha256,
        "legacy_path": path,
        "schema_version": SECURITY_ARTIFACT_RECORD_VERSION,
    }
    return f"security-artifact:sha256:{_canonical_digest(preimage)}"


def _flags(record: Mapping[str, Any]) -> dict[str, bool]:
    classification = str(record["classification"])
    return {
        "ambiguous": classification == "ambiguous"
        or bool(record["is_new_variant"])
        or bool(record["is_mutable_alias"]),
        "transient": classification == "transient compiler output"
        or bool(record["is_temporary"]),
        "unknown": classification == "unknown",
    }


def _artifact_class(record: Mapping[str, Any]) -> ArtifactClass:
    flags = _flags(record)
    if flags["ambiguous"] or flags["transient"] or flags["unknown"]:
        return ArtifactClass.ARCHIVE
    return _CLASS_MAP[str(record["classification"])]


def _target_disposition(record: Mapping[str, Any]) -> str:
    flags = _flags(record)
    if flags["ambiguous"]:
        return "retain_pending_review"
    if flags["unknown"]:
        return "retain_pending_classification"
    if flags["transient"]:
        return "retain_regenerable_output"
    return "mapped"


def _build_record(
    inventory_record: Mapping[str, Any],
    *,
    artifact_root: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    missing = sorted(_REQUIRED_INVENTORY_FIELDS - set(inventory_record))
    if missing:
        raise ArtifactMigrationError(
            f"inventory record is missing required fields: {', '.join(missing)}"
        )
    path = _normalise_path(inventory_record["path"], artifact_root=artifact_root)
    content_sha256 = _require_sha256(
        inventory_record["sha256"], f"{path}.sha256"
    )
    classification = inventory_record["classification"]
    if classification not in _CLASS_MAP:
        raise ArtifactMigrationError(
            f"{path} has unsupported inventory classification {classification!r}"
        )
    size = inventory_record["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ArtifactMigrationError(f"{path}.size_bytes must be non-negative")
    legacy_ids = _normalise_legacy_ids(inventory_record["legacy_ids"])
    record_id = _record_id(path, content_sha256)
    flags = _flags(inventory_record)
    deterministic_inventory = {
        key: deepcopy(value)
        for key, value in inventory_record.items()
        if key not in _OBSERVATIONAL_INVENTORY_FIELDS
    }
    deterministic_inventory["legacy_ids"] = legacy_ids

    deterministic = {
        "flags": flags,
        "legacy": deterministic_inventory,
        "record_id": record_id,
        "target": {
            "artifact_class": _artifact_class(inventory_record).value,
            "authority_selected": False,
            "content_sha256": content_sha256,
            "disposition": _target_disposition(inventory_record),
            "path": path,
            "schema_version": SECURITY_ARTIFACT_RECORD_VERSION,
            "size_bytes": size,
        },
    }
    observational = {
        "ambiguity_reasons": deepcopy(inventory_record["ambiguity_reasons"]),
        "likely_producers": deepcopy(inventory_record["likely_producers"]),
        "recommendations": deepcopy(inventory_record["recommendations"]),
        "record_id": record_id,
    }
    return deterministic, observational


def build_migration_manifest(inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic migration manifest from an inventory payload.

    The input is never mutated.  Rebuilding from the same inventory produces
    byte-identical output and record IDs.
    """

    inventory = _require_mapping(inventory, "inventory")
    if inventory.get("schema_version") != "SecurityArtifactInventory@1":
        raise ArtifactMigrationError("unsupported Security artifact inventory version")
    artifact_root = inventory.get("artifact_root")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise ArtifactMigrationError("inventory artifact_root must not be empty")
    records = list(_require_sequence(inventory.get("artifacts"), "inventory.artifacts"))
    if inventory.get("artifact_count") != len(records):
        raise ArtifactMigrationError("inventory artifact_count does not match artifacts")
    expected_inventory_digest = _require_sha256(
        inventory.get("inventory_sha256"), "inventory.inventory_sha256"
    )
    if _inventory_digest(records) != expected_inventory_digest:
        raise ArtifactMigrationError("inventory_sha256 does not match inventory records")

    deterministic_records: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for item in records:
        deterministic, observational = _build_record(
            _require_mapping(item, "inventory artifact"),
            artifact_root=artifact_root,
        )
        deterministic_records.append(deterministic)
        observations.append(observational)
    deterministic_records.sort(key=lambda item: item["legacy"]["path"].encode("utf-8"))
    observations.sort(key=lambda item: item["record_id"].encode("utf-8"))

    paths = [item["legacy"]["path"] for item in deterministic_records]
    record_ids = [item["record_id"] for item in deterministic_records]
    if len(set(paths)) != len(paths):
        raise ArtifactMigrationError("inventory contains duplicate artifact paths")
    if len(set(record_ids)) != len(record_ids):
        raise ArtifactMigrationError("migration contains duplicate record IDs")

    class_counts = Counter(
        item["target"]["artifact_class"] for item in deterministic_records
    )
    deterministic_fields = {
        "artifact_count": len(deterministic_records),
        "artifact_root": artifact_root,
        "authority_decisions_made": 0,
        "class_counts": {
            item.value: class_counts.get(item.value, 0) for item in ArtifactClass
        },
        "legacy_id_count": sum(
            len(item["legacy"]["legacy_ids"]) for item in deterministic_records
        ),
        "records": deterministic_records,
        "source_inventory": {
            "artifact_count": len(deterministic_records),
            "inventory_sha256": expected_inventory_digest,
            "path": DEFAULT_INVENTORY_PATH,
            "schema_version": "SecurityArtifactInventory@1",
            "scope": inventory.get("scope"),
        },
    }
    digest = _canonical_digest(deterministic_fields)
    return {
        "deterministic_fields": deterministic_fields,
        "manifest_id": f"security-artifact-migration:sha256:{digest}",
        "manifest_sha256": digest,
        "observational_fields": {
            "inventory_annotations": observations,
            "note": (
                "Producer attributions, ambiguity explanations, and recommendations "
                "are inventory observations excluded from migration identity."
            ),
        },
        "schema_version": SECURITY_ARTIFACT_MIGRATION_VERSION,
    }


def render_migration_manifest(manifest: Mapping[str, Any]) -> str:
    """Render validated, stable checked-in JSON."""

    validate_migration_manifest(manifest)
    return json.dumps(
        manifest, ensure_ascii=True, indent=2, sort_keys=True
    ) + "\n"


def load_migration_manifest(path: str | Path) -> dict[str, Any]:
    """Load and validate a migration manifest from disk."""

    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactMigrationError(f"unable to read migration manifest: {exc}") from exc
    validate_migration_manifest(value)
    return value


def validate_migration_manifest(manifest: Mapping[str, Any]) -> None:
    """Fail closed on malformed IDs, unsafe mappings, or digest drift."""

    manifest = _require_mapping(manifest, "manifest")
    if manifest.get("schema_version") != SECURITY_ARTIFACT_MIGRATION_VERSION:
        raise ArtifactMigrationError("unsupported artifact migration version")
    deterministic = _require_mapping(
        manifest.get("deterministic_fields"), "deterministic_fields"
    )
    digest = _canonical_digest(deterministic)
    if manifest.get("manifest_sha256") != digest:
        raise ArtifactMigrationError("manifest_sha256 does not match deterministic_fields")
    expected_id = f"security-artifact-migration:sha256:{digest}"
    if manifest.get("manifest_id") != expected_id:
        raise ArtifactMigrationError("manifest_id does not match deterministic_fields")

    artifact_root = deterministic.get("artifact_root")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise ArtifactMigrationError("deterministic artifact_root must not be empty")
    records = list(
        _require_sequence(deterministic.get("records"), "deterministic_fields.records")
    )
    if deterministic.get("artifact_count") != len(records):
        raise ArtifactMigrationError("manifest artifact_count does not match records")
    if deterministic.get("authority_decisions_made") != 0:
        raise ArtifactMigrationError(
            "migration must not make artifact authority decisions"
        )
    source_inventory = _require_mapping(
        deterministic.get("source_inventory"), "source_inventory"
    )
    if source_inventory.get("schema_version") != "SecurityArtifactInventory@1":
        raise ArtifactMigrationError("source_inventory has an unsupported schema")
    if source_inventory.get("path") != DEFAULT_INVENTORY_PATH:
        raise ArtifactMigrationError("source_inventory path is not the frozen inventory")
    _require_sha256(
        source_inventory.get("inventory_sha256"),
        "source_inventory.inventory_sha256",
    )
    if source_inventory.get("artifact_count") != len(records):
        raise ArtifactMigrationError(
            "source_inventory artifact_count does not match records"
        )

    paths: list[str] = []
    record_ids: list[str] = []
    class_counts: Counter[str] = Counter()
    legacy_id_count = 0
    for index, item in enumerate(records):
        record = _require_mapping(item, f"records[{index}]")
        legacy = _require_mapping(record.get("legacy"), f"records[{index}].legacy")
        target = _require_mapping(record.get("target"), f"records[{index}].target")
        flags = _require_mapping(record.get("flags"), f"records[{index}].flags")
        missing = sorted(
            (_REQUIRED_INVENTORY_FIELDS - _OBSERVATIONAL_INVENTORY_FIELDS)
            - set(legacy)
        )
        if missing:
            raise ArtifactMigrationError(
                f"records[{index}].legacy is missing fields: {', '.join(missing)}"
            )
        path = _normalise_path(legacy.get("path"), artifact_root=artifact_root)
        digest_value = _require_sha256(
            legacy.get("sha256"), f"records[{index}].legacy.sha256"
        )
        ids = _normalise_legacy_ids(legacy.get("legacy_ids"))
        legacy_id_count += len(ids)
        size = legacy.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ArtifactMigrationError(f"{path} has an invalid legacy size")
        if legacy.get("authority_selected") is not False:
            raise ArtifactMigrationError(
                f"{path} legacy inventory must not select authority"
            )
        record_id = _record_id(path, digest_value)
        if record.get("record_id") != record_id:
            raise ArtifactMigrationError(f"{path} has an invalid record_id")
        classification = legacy.get("classification")
        if classification not in _CLASS_MAP:
            raise ArtifactMigrationError(
                f"{path} has unsupported legacy classification {classification!r}"
            )
        expected_class = _artifact_class(legacy).value
        if target.get("schema_version") != SECURITY_ARTIFACT_RECORD_VERSION:
            raise ArtifactMigrationError(f"{path} has an unsupported target schema")
        if target.get("path") != path or target.get("content_sha256") != digest_value:
            raise ArtifactMigrationError(
                f"{path} target does not preserve legacy path and digest"
            )
        if target.get("size_bytes") != size:
            raise ArtifactMigrationError(f"{path} target does not preserve legacy size")
        if target.get("artifact_class") != expected_class:
            raise ArtifactMigrationError(f"{path} has an invalid target class")
        if target.get("authority_selected") is not False:
            raise ArtifactMigrationError(f"{path} must not select authority")
        if dict(flags) != _flags(legacy):
            raise ArtifactMigrationError(f"{path} has inconsistent safety flags")
        if target.get("disposition") != _target_disposition(legacy):
            raise ArtifactMigrationError(f"{path} has an unsafe target disposition")
        paths.append(path)
        record_ids.append(record_id)
        class_counts[expected_class] += 1

    if paths != sorted(paths, key=lambda value: value.encode("utf-8")):
        raise ArtifactMigrationError("migration records must be bytewise path ordered")
    if len(paths) != len(set(paths)) or len(record_ids) != len(set(record_ids)):
        raise ArtifactMigrationError("migration paths and record IDs must be unique")
    expected_counts = {
        item.value: class_counts.get(item.value, 0) for item in ArtifactClass
    }
    if deterministic.get("class_counts") != expected_counts:
        raise ArtifactMigrationError("class_counts does not match migration records")
    if deterministic.get("legacy_id_count") != legacy_id_count:
        raise ArtifactMigrationError("legacy_id_count does not match migration records")

    observational = _require_mapping(
        manifest.get("observational_fields"), "observational_fields"
    )
    annotations = _require_sequence(
        observational.get("inventory_annotations"),
        "observational_fields.inventory_annotations",
    )
    annotation_ids: list[str] = []
    for item in annotations:
        annotation = _require_mapping(item, "inventory annotation")
        if set(annotation) != _OBSERVATIONAL_INVENTORY_FIELDS | {"record_id"}:
            raise ArtifactMigrationError(
                "inventory annotations must contain exactly record_id and "
                "the declared observational fields"
            )
        record_id = annotation["record_id"]
        if not isinstance(record_id, str) or not record_id:
            raise ArtifactMigrationError(
                "inventory annotation record_id must not be empty"
            )
        for field_name in _OBSERVATIONAL_INVENTORY_FIELDS:
            _require_sequence(
                annotation[field_name],
                f"inventory annotation {field_name}",
            )
        annotation_ids.append(record_id)
    if sorted(annotation_ids) != sorted(record_ids):
        raise ArtifactMigrationError(
            "observational inventory annotations must cover every record exactly once"
        )


def restore_inventory_records(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Reverse the migration into the exact per-artifact inventory records."""

    validate_migration_manifest(manifest)
    deterministic = manifest["deterministic_fields"]
    annotations = {
        item["record_id"]: item
        for item in manifest["observational_fields"]["inventory_annotations"]
    }
    restored: list[dict[str, Any]] = []
    for record in deterministic["records"]:
        item = deepcopy(record["legacy"])
        annotation = annotations[record["record_id"]]
        for key in _OBSERVATIONAL_INVENTORY_FIELDS:
            item[key] = deepcopy(annotation[key])
        restored.append(item)
    return restored


def migrate_legacy_reference(
    manifest: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Map one legacy reference to its v1 record, idempotently.

    A legacy reference must supply ``path`` and may additionally pin ``sha256``.
    Passing a previously returned v1 record returns the same canonical record.
    """

    validate_migration_manifest(manifest)
    reference = _require_mapping(reference, "reference")
    records = manifest["deterministic_fields"]["records"]
    if reference.get("schema_version") == SECURITY_ARTIFACT_RECORD_VERSION:
        record_id = reference.get("record_id")
        match = next(
            (item["target"] | {"record_id": item["record_id"]} for item in records
             if item["record_id"] == record_id),
            None,
        )
        if match is None or dict(reference) != match:
            raise ArtifactMigrationError("v1 artifact reference is not bound by manifest")
        return deepcopy(match)

    path = reference.get("path")
    if not isinstance(path, str) or not path:
        raise ArtifactMigrationError("legacy reference requires path")
    matches = [item for item in records if item["legacy"]["path"] == path]
    if not matches:
        raise ArtifactMigrationError(f"legacy path is not bound by manifest: {path}")
    record = matches[0]
    pinned = reference.get("sha256")
    if pinned is not None and pinned != record["legacy"]["sha256"]:
        raise ArtifactMigrationIntegrityError(
            MigrationIntegrityReceipt(
                valid=False,
                manifest_id=manifest["manifest_id"],
                checked_artifact_count=1,
                legacy_id_count=len(record["legacy"]["legacy_ids"]),
                issues=(f"{path}: supplied SHA-256 does not match manifest",),
            )
        )
    return deepcopy(record["target"] | {"record_id": record["record_id"]})


def reverse_migration(
    manifest: Mapping[str, Any],
    migrated_reference: Mapping[str, Any] | str,
) -> dict[str, Any]:
    """Return the preserved legacy path, digest, and IDs for a v1 record."""

    validate_migration_manifest(manifest)
    if isinstance(migrated_reference, str):
        record_id = migrated_reference
    else:
        record_id = migrate_legacy_reference(
            manifest, migrated_reference
        )["record_id"]
    for record in manifest["deterministic_fields"]["records"]:
        if record["record_id"] == record_id:
            legacy = record["legacy"]
            return {
                "legacy_ids": deepcopy(legacy["legacy_ids"]),
                "path": legacy["path"],
                "sha256": legacy["sha256"],
            }
    raise ArtifactMigrationError(f"v1 record is not bound by manifest: {record_id!r}")


@dataclass(frozen=True, slots=True)
class MigrationIntegrityReceipt:
    """Deterministic result of checking manifest coverage and legacy bytes."""

    valid: bool
    manifest_id: str
    checked_artifact_count: int
    legacy_id_count: int
    issues: tuple[str, ...] = ()
    schema_version: str = SECURITY_ARTIFACT_MIGRATION_RECEIPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_artifact_count": self.checked_artifact_count,
            "issues": list(self.issues),
            "legacy_id_count": self.legacy_id_count,
            "manifest_id": self.manifest_id,
            "schema_version": self.schema_version,
            "valid": self.valid,
        }


def _read_legacy_bytes(path: Path) -> bytes:
    """Read artifact bytes without following a legacy symbolic link."""

    metadata = path.lstat()
    if path.is_symlink():
        return os.readlink(path).encode("utf-8", errors="surrogateescape")
    if not path.is_file():
        raise OSError("path is not a regular file or symbolic link")
    data = path.read_bytes()
    if len(data) != metadata.st_size:
        raise OSError("artifact changed while it was read")
    return data


def audit_migration_integrity(
    manifest: Mapping[str, Any],
    repo_root: str | Path,
    *,
    inventory: Mapping[str, Any] | None = None,
) -> MigrationIntegrityReceipt:
    """Check exact bytes and, when supplied, complete inventory reversibility."""

    try:
        validate_migration_manifest(manifest)
    except ArtifactMigrationError as exc:
        return MigrationIntegrityReceipt(
            valid=False,
            manifest_id=str(manifest.get("manifest_id") or ""),
            checked_artifact_count=0,
            legacy_id_count=0,
            issues=(str(exc),),
        )
    root = Path(repo_root).resolve()
    records = manifest["deterministic_fields"]["records"]
    issues: list[str] = []
    for record in records:
        legacy = record["legacy"]
        path = root.joinpath(*PurePosixPath(legacy["path"]).parts)
        try:
            data = _read_legacy_bytes(path)
        except OSError as exc:
            issues.append(f"{legacy['path']}: missing or unreadable ({exc})")
            continue
        actual = hashlib.sha256(data).hexdigest()
        if actual != legacy["sha256"]:
            issues.append(
                f"{legacy['path']}: SHA-256 changed "
                f"(expected {legacy['sha256']}, got {actual})"
            )
        if len(data) != legacy["size_bytes"]:
            issues.append(
                f"{legacy['path']}: size changed "
                f"(expected {legacy['size_bytes']}, got {len(data)})"
            )

    if inventory is not None:
        try:
            inventory_records = list(
                _require_sequence(inventory.get("artifacts"), "inventory.artifacts")
            )
            if restore_inventory_records(manifest) != inventory_records:
                issues.append(
                    "reversed migration records do not exactly match source inventory"
                )
            source = manifest["deterministic_fields"]["source_inventory"]
            if inventory.get("inventory_sha256") != source["inventory_sha256"]:
                issues.append("source inventory digest does not match manifest binding")
            if len(inventory_records) != len(records):
                issues.append("source inventory coverage does not match manifest")
        except ArtifactMigrationError as exc:
            issues.append(str(exc))

    return MigrationIntegrityReceipt(
        valid=not issues,
        manifest_id=manifest["manifest_id"],
        checked_artifact_count=len(records),
        legacy_id_count=manifest["deterministic_fields"]["legacy_id_count"],
        issues=tuple(issues),
    )


def verify_migration_integrity(
    manifest: Mapping[str, Any],
    repo_root: str | Path,
    *,
    inventory: Mapping[str, Any] | None = None,
) -> MigrationIntegrityReceipt:
    """Return a valid receipt or raise with the complete integrity report."""

    receipt = audit_migration_integrity(manifest, repo_root, inventory=inventory)
    if not receipt.valid:
        raise ArtifactMigrationIntegrityError(receipt)
    return receipt


# Concise compatibility spellings for callers that use artifact-oriented names.
build_artifact_migration_manifest = build_migration_manifest
validate_artifact_migration_manifest = validate_migration_manifest


__all__ = [
    "ArtifactClass",
    "ArtifactMigrationError",
    "ArtifactMigrationIntegrityError",
    "DEFAULT_INVENTORY_PATH",
    "DEFAULT_MANIFEST_PATH",
    "MigrationIntegrityReceipt",
    "SECURITY_ARTIFACT_MIGRATION_RECEIPT_VERSION",
    "SECURITY_ARTIFACT_MIGRATION_VERSION",
    "SECURITY_ARTIFACT_RECORD_VERSION",
    "audit_migration_integrity",
    "build_artifact_migration_manifest",
    "build_migration_manifest",
    "load_migration_manifest",
    "migrate_legacy_reference",
    "render_migration_manifest",
    "restore_inventory_records",
    "reverse_migration",
    "validate_artifact_migration_manifest",
    "validate_migration_manifest",
    "verify_migration_integrity",
]

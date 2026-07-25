"""Domain-neutral schema compatibility and deterministic migration registry.

The registry deliberately treats schema identifiers as opaque, exact values.
It does not interpret semantic-version ranges or guess compatibility from
similar-looking identifiers.  Readers either declare an exact source schema as
compatible or use an explicit, audited migration path.

Migration receipts contain no clock, host, or runtime data.  They are therefore
reproducible and bind the canonical source and destination payload digests.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final


IR_SCHEMA_REGISTRY_PROTOCOL_ID: Final = "IRSchemaRegistry@1"
IR_MIGRATION_RECEIPT_SCHEMA_ID: Final = "IRMigrationReceipt@1"
_EXACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,254}$")


class SchemaRegistryError(ValueError):
    """Base class for registry construction and execution failures."""


class UnknownSchemaError(SchemaRegistryError):
    """Raised when an exact schema identifier is not registered."""


class IncompatibleSchemaError(SchemaRegistryError):
    """Raised when no declared compatibility or migration path exists."""


class MigrationCycleError(SchemaRegistryError):
    """Raised when explicit migration edges contain a directed cycle."""


class MigrationExecutionError(SchemaRegistryError):
    """Raised when a migration violates its declared schema contract."""


class ReceiptVerificationError(SchemaRegistryError):
    """Raised when a receipt does not bind the supplied payloads and path."""


class CompatibilityKind(str, Enum):
    """Result of negotiating an artifact schema with a reader schema."""

    EXACT = "exact"
    DECLARED = "declared"
    MIGRATION_REQUIRED = "migration_required"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class CompatibilityDeclaration:
    """Declare that one reader accepts one exact source schema unchanged."""

    source_schema_id: str

    def __post_init__(self) -> None:
        _validate_exact_id("source_schema_id", self.source_schema_id)

    def to_dict(self) -> dict[str, str]:
        return {"source_schema_id": self.source_schema_id}


@dataclass(frozen=True, slots=True)
class SchemaDeclaration:
    """Registration for one exact schema and its direct-read compatibility."""

    schema_id: str
    compatibility: tuple[CompatibilityDeclaration, ...] = ()
    schema_id_field: str = "schema_id"
    description: str = ""

    def __post_init__(self) -> None:
        _validate_exact_id("schema_id", self.schema_id)
        _validate_field_name(self.schema_id_field)
        declarations = tuple(self.compatibility)
        object.__setattr__(self, "compatibility", declarations)
        if any(
            not isinstance(item, CompatibilityDeclaration)
            for item in declarations
        ):
            raise SchemaRegistryError(
                f"schema {self.schema_id!r} compatibility entries must be "
                "CompatibilityDeclaration values"
            )
        source_ids = [item.source_schema_id for item in declarations]
        if len(source_ids) != len(set(source_ids)):
            raise SchemaRegistryError(
                f"schema {self.schema_id!r} has duplicate compatibility declarations"
            )
        if self.schema_id in source_ids:
            raise SchemaRegistryError(
                f"schema {self.schema_id!r} must not declare itself compatible; "
                "exact compatibility is automatic"
            )

    @property
    def compatible_source_schema_ids(self) -> tuple[str, ...]:
        return tuple(item.source_schema_id for item in self.compatibility)

    def accepts(self, source_schema_id: str) -> bool:
        return source_schema_id == self.schema_id or source_schema_id in (
            self.compatible_source_schema_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatibility": [
                item.to_dict()
                for item in sorted(
                    self.compatibility, key=lambda item: item.source_schema_id
                )
            ],
            "description": self.description,
            "schema_id": self.schema_id,
            "schema_id_field": self.schema_id_field,
        }


@dataclass(frozen=True, slots=True)
class LossEntry:
    """One intentional piece of information discarded by a migration."""

    code: str
    message: str
    field_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_exact_id("loss code", self.code)
        if not str(self.message or "").strip():
            raise SchemaRegistryError("loss message must not be empty")
        paths = tuple(str(path) for path in self.field_paths)
        if not paths or any(not path.strip() for path in paths):
            raise SchemaRegistryError(
                f"loss entry {self.code!r} requires non-empty field_paths"
            )
        if len(paths) != len(set(paths)):
            raise SchemaRegistryError(
                f"loss entry {self.code!r} has duplicate field paths"
            )
        object.__setattr__(self, "field_paths", paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field_paths": list(self.field_paths),
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class LossReport:
    """Explicit loss declaration for one migration edge."""

    entries: tuple[LossEntry, ...] = ()

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        object.__setattr__(self, "entries", entries)
        if any(not isinstance(entry, LossEntry) for entry in entries):
            raise SchemaRegistryError(
                "loss report entries must be LossEntry values"
            )
        codes = [entry.code for entry in entries]
        if len(codes) != len(set(codes)):
            raise SchemaRegistryError("loss report entry codes must be unique")

    @classmethod
    def lossless(cls) -> "LossReport":
        """Return an explicit report stating that no information is lost."""

        return cls()

    @property
    def is_lossless(self) -> bool:
        return not self.entries

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "is_lossless": self.is_lossless,
        }


MigrationTransform = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class Migration:
    """One explicit deterministic edge in the schema migration graph."""

    migration_id: str
    source_schema_id: str
    destination_schema_id: str
    transform: MigrationTransform = field(repr=False, compare=False)
    loss_report: LossReport
    description: str = ""

    def __post_init__(self) -> None:
        _validate_exact_id("migration_id", self.migration_id)
        _validate_exact_id("source_schema_id", self.source_schema_id)
        _validate_exact_id("destination_schema_id", self.destination_schema_id)
        if self.source_schema_id == self.destination_schema_id:
            raise MigrationCycleError(
                f"migration {self.migration_id!r} is a self-cycle"
            )
        if not callable(self.transform):
            raise SchemaRegistryError(
                f"migration {self.migration_id!r} transform must be callable"
            )
        if not isinstance(self.loss_report, LossReport):
            raise SchemaRegistryError(
                f"migration {self.migration_id!r} requires an explicit LossReport"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "loss_report": self.loss_report.to_dict(),
            "migration_id": self.migration_id,
            "source_schema_id": self.source_schema_id,
            "destination_schema_id": self.destination_schema_id,
        }


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    """Deterministic compatibility decision for two exact schema IDs."""

    source_schema_id: str
    reader_schema_id: str
    kind: CompatibilityKind
    migration_ids: tuple[str, ...] = ()
    schema_path: tuple[str, ...] = ()

    @property
    def compatible(self) -> bool:
        return self.kind is not CompatibilityKind.INCOMPATIBLE

    @property
    def requires_migration(self) -> bool:
        return self.kind is CompatibilityKind.MIGRATION_REQUIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "kind": self.kind.value,
            "migration_ids": list(self.migration_ids),
            "reader_schema_id": self.reader_schema_id,
            "requires_migration": self.requires_migration,
            "schema_path": list(self.schema_path),
            "source_schema_id": self.source_schema_id,
        }


@dataclass(frozen=True, slots=True)
class MigrationStepReceipt:
    """Digest and loss binding for one applied migration edge."""

    migration_id: str
    source_schema_id: str
    destination_schema_id: str
    source_digest: str
    destination_digest: str
    loss_report: LossReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination_digest": self.destination_digest,
            "destination_schema_id": self.destination_schema_id,
            "loss_report": self.loss_report.to_dict(),
            "migration_id": self.migration_id,
            "source_digest": self.source_digest,
            "source_schema_id": self.source_schema_id,
        }


@dataclass(frozen=True, slots=True)
class MigrationReceipt:
    """Deterministic receipt binding a complete migration execution."""

    source_schema_id: str
    destination_schema_id: str
    source_digest: str
    destination_digest: str
    steps: tuple[MigrationStepReceipt, ...]
    schema_id: str = IR_MIGRATION_RECEIPT_SCHEMA_ID
    registry_protocol_id: str = IR_SCHEMA_REGISTRY_PROTOCOL_ID

    @property
    def is_lossless(self) -> bool:
        return all(step.loss_report.is_lossless for step in self.steps)

    @property
    def migration_ids(self) -> tuple[str, ...]:
        return tuple(step.migration_id for step in self.steps)

    @property
    def receipt_digest(self) -> str:
        return canonical_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination_digest": self.destination_digest,
            "destination_schema_id": self.destination_schema_id,
            "is_lossless": self.is_lossless,
            "registry_protocol_id": self.registry_protocol_id,
            "schema_id": self.schema_id,
            "source_digest": self.source_digest,
            "source_schema_id": self.source_schema_id,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Migrated canonical payload plus its deterministic receipt."""

    payload: Mapping[str, Any]
    receipt: MigrationReceipt

    def __post_init__(self) -> None:
        canonical = _canonical_copy(self.payload)
        object.__setattr__(self, "payload", _freeze_json(canonical))

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload": _canonical_copy(self.payload),
            "receipt": self.receipt.to_dict(),
        }


class IRSchemaRegistry(Mapping[str, SchemaDeclaration]):
    """Immutable registry of exact schemas and explicit migration edges."""

    protocol_id: Final = IR_SCHEMA_REGISTRY_PROTOCOL_ID

    def __init__(
        self,
        schemas: Sequence[SchemaDeclaration],
        migrations: Sequence[Migration] = (),
    ) -> None:
        schema_items = tuple(schemas)
        migration_items = tuple(migrations)
        if any(not isinstance(item, SchemaDeclaration) for item in schema_items):
            raise SchemaRegistryError(
                "schemas must contain only SchemaDeclaration values"
            )
        if any(not isinstance(item, Migration) for item in migration_items):
            raise SchemaRegistryError(
                "migrations must contain only Migration values"
            )
        by_schema = {item.schema_id: item for item in schema_items}
        if len(by_schema) != len(schema_items):
            raise SchemaRegistryError("schema IDs must be unique")
        by_migration_id = {item.migration_id: item for item in migration_items}
        if len(by_migration_id) != len(migration_items):
            raise SchemaRegistryError("migration IDs must be unique")
        by_edge = {
            (item.source_schema_id, item.destination_schema_id): item
            for item in migration_items
        }
        if len(by_edge) != len(migration_items):
            raise SchemaRegistryError(
                "only one migration may be declared for an exact source/destination pair"
            )

        for schema in schema_items:
            for source_id in schema.compatible_source_schema_ids:
                if source_id not in by_schema:
                    raise UnknownSchemaError(
                        f"schema {schema.schema_id!r} declares unknown compatible "
                        f"source schema {source_id!r}"
                    )
        for migration in migration_items:
            for role, schema_id in (
                ("source", migration.source_schema_id),
                ("destination", migration.destination_schema_id),
            ):
                if schema_id not in by_schema:
                    raise UnknownSchemaError(
                        f"migration {migration.migration_id!r} has unknown "
                        f"{role} schema {schema_id!r}"
                    )

        adjacency: dict[str, list[Migration]] = {
            schema_id: [] for schema_id in by_schema
        }
        for migration in migration_items:
            adjacency[migration.source_schema_id].append(migration)
        frozen_adjacency = {
            schema_id: tuple(
                sorted(
                    edges,
                    key=lambda item: (
                        item.destination_schema_id,
                        item.migration_id,
                    ),
                )
            )
            for schema_id, edges in adjacency.items()
        }
        _reject_cycles(frozen_adjacency)

        self._schemas = MappingProxyType(dict(sorted(by_schema.items())))
        self._migrations = MappingProxyType(dict(sorted(by_migration_id.items())))
        self._edges = MappingProxyType(by_edge)
        self._adjacency = MappingProxyType(frozen_adjacency)

    def __getitem__(self, schema_id: str) -> SchemaDeclaration:
        try:
            return self._schemas[schema_id]
        except KeyError as exc:
            raise UnknownSchemaError(
                f"unknown schema ID {schema_id!r}; exact registration is required"
            ) from exc

    def __iter__(self) -> Iterable[str]:
        return iter(self._schemas)

    def __len__(self) -> int:
        return len(self._schemas)

    @property
    def migrations(self) -> Mapping[str, Migration]:
        return self._migrations

    def require_schema(self, schema_id: str) -> SchemaDeclaration:
        """Resolve an exact schema ID or reject the unknown version."""

        return self[schema_id]

    def migration_path(
        self, source_schema_id: str, destination_schema_id: str
    ) -> tuple[Migration, ...]:
        """Return the deterministic shortest path, breaking ties lexically."""

        self.require_schema(source_schema_id)
        self.require_schema(destination_schema_id)
        if source_schema_id == destination_schema_id:
            return ()

        queue: deque[tuple[str, tuple[Migration, ...]]] = deque(
            [(source_schema_id, ())]
        )
        visited = {source_schema_id}
        while queue:
            current, path = queue.popleft()
            for migration in self._adjacency[current]:
                next_id = migration.destination_schema_id
                next_path = (*path, migration)
                if next_id == destination_schema_id:
                    return next_path
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, next_path))
        raise IncompatibleSchemaError(
            f"no migration path from {source_schema_id!r} "
            f"to {destination_schema_id!r}"
        )

    def negotiate(
        self, source_schema_id: str, reader_schema_id: str
    ) -> CompatibilityResult:
        """Negotiate only exact IDs and explicit compatibility declarations."""

        source = self.require_schema(source_schema_id)
        reader = self.require_schema(reader_schema_id)
        if source.schema_id == reader.schema_id:
            return CompatibilityResult(
                source_schema_id, reader_schema_id, CompatibilityKind.EXACT
            )
        if reader.accepts(source.schema_id):
            return CompatibilityResult(
                source_schema_id, reader_schema_id, CompatibilityKind.DECLARED
            )
        try:
            path = self.migration_path(source.schema_id, reader.schema_id)
        except IncompatibleSchemaError:
            return CompatibilityResult(
                source_schema_id, reader_schema_id, CompatibilityKind.INCOMPATIBLE
            )
        return CompatibilityResult(
            source_schema_id=source_schema_id,
            reader_schema_id=reader_schema_id,
            kind=CompatibilityKind.MIGRATION_REQUIRED,
            migration_ids=tuple(item.migration_id for item in path),
            schema_path=(
                source_schema_id,
                *(item.destination_schema_id for item in path),
            ),
        )

    def migrate(
        self,
        payload: Mapping[str, Any],
        source_schema_id: str,
        destination_schema_id: str,
    ) -> MigrationResult:
        """Execute an explicit path and return a digest-bound receipt."""

        source = self.require_schema(source_schema_id)
        destination = self.require_schema(destination_schema_id)
        current = _canonical_copy(payload)
        _require_payload_schema(current, source)
        source_digest = canonical_digest(current)

        if source_schema_id == destination_schema_id:
            receipt = MigrationReceipt(
                source_schema_id=source_schema_id,
                destination_schema_id=destination_schema_id,
                source_digest=source_digest,
                destination_digest=source_digest,
                steps=(),
            )
            return MigrationResult(current, receipt)

        path = self.migration_path(source_schema_id, destination_schema_id)
        step_receipts: list[MigrationStepReceipt] = []
        for migration in path:
            step_source = self.require_schema(migration.source_schema_id)
            step_destination = self.require_schema(migration.destination_schema_id)
            _require_payload_schema(current, step_source)
            step_source_digest = canonical_digest(current)
            transform_input = _freeze_json(_canonical_copy(current))
            try:
                transformed = migration.transform(transform_input)
            except Exception as exc:
                raise MigrationExecutionError(
                    f"migration {migration.migration_id!r} failed"
                ) from exc
            if not isinstance(transformed, Mapping):
                raise MigrationExecutionError(
                    f"migration {migration.migration_id!r} must return a mapping"
                )
            current = _canonical_copy(transformed)
            _require_payload_schema(current, step_destination)
            step_destination_digest = canonical_digest(current)
            step_receipts.append(
                MigrationStepReceipt(
                    migration_id=migration.migration_id,
                    source_schema_id=migration.source_schema_id,
                    destination_schema_id=migration.destination_schema_id,
                    source_digest=step_source_digest,
                    destination_digest=step_destination_digest,
                    loss_report=migration.loss_report,
                )
            )

        destination_digest = canonical_digest(current)
        receipt = MigrationReceipt(
            source_schema_id=source_schema_id,
            destination_schema_id=destination_schema_id,
            source_digest=source_digest,
            destination_digest=destination_digest,
            steps=tuple(step_receipts),
        )
        return MigrationResult(current, receipt)

    def verify_receipt(
        self,
        receipt: MigrationReceipt,
        source_payload: Mapping[str, Any],
        destination_payload: Mapping[str, Any],
    ) -> None:
        """Verify payload digests, the registered path, and the step chain."""

        if receipt.schema_id != IR_MIGRATION_RECEIPT_SCHEMA_ID:
            raise ReceiptVerificationError("unknown migration receipt schema ID")
        if receipt.registry_protocol_id != self.protocol_id:
            raise ReceiptVerificationError("migration receipt registry protocol mismatch")
        if canonical_digest(source_payload) != receipt.source_digest:
            raise ReceiptVerificationError("migration receipt source digest mismatch")
        if canonical_digest(destination_payload) != receipt.destination_digest:
            raise ReceiptVerificationError(
                "migration receipt destination digest mismatch"
            )
        try:
            expected_path = self.migration_path(
                receipt.source_schema_id, receipt.destination_schema_id
            )
        except SchemaRegistryError as exc:
            raise ReceiptVerificationError(
                "migration receipt references an unavailable path"
            ) from exc
        if receipt.migration_ids != tuple(item.migration_id for item in expected_path):
            raise ReceiptVerificationError("migration receipt path mismatch")
        if len(receipt.steps) != len(expected_path):
            raise ReceiptVerificationError("migration receipt step count mismatch")

        previous_digest = receipt.source_digest
        previous_schema = receipt.source_schema_id
        for step, migration in zip(receipt.steps, expected_path):
            if (
                step.migration_id != migration.migration_id
                or step.source_schema_id != previous_schema
                or step.destination_schema_id != migration.destination_schema_id
                or step.source_digest != previous_digest
                or step.loss_report != migration.loss_report
            ):
                raise ReceiptVerificationError(
                    f"migration receipt step {step.migration_id!r} is inconsistent"
                )
            previous_digest = step.destination_digest
            previous_schema = step.destination_schema_id
        if (
            previous_digest != receipt.destination_digest
            or previous_schema != receipt.destination_schema_id
        ):
            raise ReceiptVerificationError("migration receipt chain is incomplete")

        # A structurally plausible chain is not sufficient: re-execution binds
        # every intermediate digest to the registered deterministic transforms.
        try:
            expected = self.migrate(
                source_payload,
                receipt.source_schema_id,
                receipt.destination_schema_id,
            )
        except SchemaRegistryError as exc:
            raise ReceiptVerificationError(
                "registered migration path could not reproduce the receipt"
            ) from exc
        if canonical_digest(expected.payload) != receipt.destination_digest:
            raise ReceiptVerificationError(
                "destination payload is not the registered migration result"
            )
        if expected.receipt.to_dict() != receipt.to_dict():
            raise ReceiptVerificationError(
                "migration receipt does not match deterministic re-execution"
            )

    def manifest(self) -> dict[str, Any]:
        """Return a deterministic, transform-free registry manifest."""

        return {
            "migrations": [
                migration.to_dict() for migration in self._migrations.values()
            ],
            "protocol_id": self.protocol_id,
            "schemas": [schema.to_dict() for schema in self._schemas.values()],
        }


def canonical_digest(payload: Mapping[str, Any]) -> str:
    """Return the SHA-256 digest of strict, canonical UTF-8 JSON."""

    encoded = _canonical_json(payload)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_exact_id(label: str, value: str) -> None:
    if not isinstance(value, str) or not _EXACT_ID_RE.fullmatch(value):
        raise SchemaRegistryError(
            f"{label} must be an exact identifier without wildcards or ranges"
        )


def _validate_field_name(value: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise SchemaRegistryError("schema_id_field must be a non-empty exact key")
    if any(ord(character) < 32 for character in value):
        raise SchemaRegistryError("schema_id_field contains a control character")


def _canonical_json(value: Any) -> bytes:
    normalized = _json_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value).decode("utf-8"))


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MigrationExecutionError(
                "payload contains a non-finite number and cannot be canonicalized"
            )
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise MigrationExecutionError(
                    "payload mapping keys must be strings for canonical JSON"
                )
            normalized[key] = _json_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise MigrationExecutionError(
        f"payload contains unsupported canonical JSON value {type(value).__name__}"
    )


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _require_payload_schema(
    payload: Mapping[str, Any], declaration: SchemaDeclaration
) -> None:
    actual = payload.get(declaration.schema_id_field)
    if actual != declaration.schema_id:
        raise MigrationExecutionError(
            f"payload field {declaration.schema_id_field!r} must equal exact "
            f"schema ID {declaration.schema_id!r}, got {actual!r}"
        )


def _reject_cycles(adjacency: Mapping[str, tuple[Migration, ...]]) -> None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(schema_id: str) -> None:
        state[schema_id] = 1
        stack.append(schema_id)
        for migration in adjacency[schema_id]:
            destination = migration.destination_schema_id
            if state.get(destination, 0) == 0:
                visit(destination)
            elif state.get(destination) == 1:
                start = stack.index(destination)
                cycle = (*stack[start:], destination)
                raise MigrationCycleError(
                    "migration cycle detected: " + " -> ".join(cycle)
                )
        stack.pop()
        state[schema_id] = 2

    for schema_id in sorted(adjacency):
        if state.get(schema_id, 0) == 0:
            visit(schema_id)


__all__ = [
    "IR_MIGRATION_RECEIPT_SCHEMA_ID",
    "IR_SCHEMA_REGISTRY_PROTOCOL_ID",
    "CompatibilityDeclaration",
    "CompatibilityKind",
    "CompatibilityResult",
    "IRSchemaRegistry",
    "IncompatibleSchemaError",
    "LossEntry",
    "LossReport",
    "Migration",
    "MigrationCycleError",
    "MigrationExecutionError",
    "MigrationReceipt",
    "MigrationResult",
    "MigrationStepReceipt",
    "ReceiptVerificationError",
    "SchemaDeclaration",
    "SchemaRegistryError",
    "UnknownSchemaError",
    "canonical_digest",
]

"""Exact schema negotiation and deterministic migrations for IR documents.

Schema identifiers are opaque strings in this module.  In particular, the
registry never infers compatibility from a version-like suffix: a reader can
consume another schema only when that relationship, or a migration path, has
been registered explicitly.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from types import MappingProxyType
from typing import Any, Final


IR_SCHEMA_REGISTRY_PROTOCOL_ID: Final = "IRSchemaRegistry@1"
MIGRATION_RECEIPT_SCHEMA_ID: Final = "ir-core/migration-receipt@1"
DEFAULT_SCHEMA_ID_FIELD: Final = "schema_id"

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,254}$")


class SchemaRegistryError(ValueError):
    """Base class for schema-registry contract violations."""


class UnknownSchemaError(SchemaRegistryError):
    """Raised when an exact schema identifier is not registered."""


class DuplicateSchemaError(SchemaRegistryError):
    """Raised when an exact schema identifier is registered twice."""


class SchemaValidationError(SchemaRegistryError):
    """Raised when a payload does not satisfy its registered schema."""


class DuplicateMigrationError(SchemaRegistryError):
    """Raised when a migration identifier or edge is registered twice."""


class MigrationCycleError(SchemaRegistryError):
    """Raised when a migration would make the migration graph cyclic."""


class MigrationPathError(SchemaRegistryError):
    """Raised when no explicit migration path exists."""


class MigrationExecutionError(SchemaRegistryError):
    """Raised when a migration transform violates its execution contract."""


class ReceiptVerificationError(SchemaRegistryError):
    """Raised when a migration receipt does not bind the supplied artifacts."""


class CompatibilityKind(str, Enum):
    """The exact relationship between a writer and reader schema."""

    EXACT = "exact"
    DECLARED = "declared"
    MIGRATION_REQUIRED = "migration_required"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class MigrationLoss:
    """One stable, machine-readable semantic loss caused by a migration."""

    code: str
    message: str
    field_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.code, "loss code")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("migration loss message must be a non-empty string")
        object.__setattr__(self, "field_paths", tuple(self.field_paths))
        if any(not isinstance(path, str) or not path for path in self.field_paths):
            raise ValueError("migration loss field paths must be non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field_paths": list(self.field_paths),
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class LossReport:
    """Complete loss declaration for one migration or migration path."""

    losses: tuple[MigrationLoss, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "losses", _dedupe_losses(self.losses))

    @property
    def lossy(self) -> bool:
        return bool(self.losses)

    def to_dict(self) -> dict[str, Any]:
        return {
            "losses": [loss.to_dict() for loss in self.losses],
            "lossy": self.lossy,
        }


SchemaValidator = Callable[[Mapping[str, Any]], bool | None]


@dataclass(frozen=True, slots=True)
class SchemaRegistration:
    """One exact schema known to the registry."""

    schema_id: str
    description: str = ""
    validator: SchemaValidator | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _require_identifier(self.schema_id, "schema_id")
        if not isinstance(self.description, str):
            raise TypeError("schema description must be a string")
        if self.validator is not None and not callable(self.validator):
            raise TypeError("schema validator must be callable")

    def to_dict(self) -> dict[str, str]:
        return {"description": self.description, "schema_id": self.schema_id}


@dataclass(frozen=True, slots=True)
class CompatibilityDeclaration:
    """An explicit declaration that a destination reader accepts a source."""

    source_schema_id: str
    destination_schema_id: str
    rationale: str = ""

    def __post_init__(self) -> None:
        _require_identifier(self.source_schema_id, "source_schema_id")
        _require_identifier(self.destination_schema_id, "destination_schema_id")
        if self.source_schema_id == self.destination_schema_id:
            raise ValueError("exact compatibility is implicit and must not be declared")
        if not isinstance(self.rationale, str):
            raise TypeError("compatibility rationale must be a string")

    def to_dict(self) -> dict[str, str]:
        return {
            "destination_schema_id": self.destination_schema_id,
            "rationale": self.rationale,
            "source_schema_id": self.source_schema_id,
        }


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Payload and runtime-discovered losses returned by a transform."""

    payload: Mapping[str, Any]
    losses: tuple[MigrationLoss, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("migration result payload must be a mapping")
        object.__setattr__(self, "payload", _freeze_json(_clone_payload(self.payload)))
        object.__setattr__(self, "losses", _dedupe_losses(self.losses))


MigrationTransform = Callable[
    [Mapping[str, Any]], Mapping[str, Any] | MigrationResult
]


@dataclass(frozen=True, slots=True)
class SchemaMigration:
    """One directed, deterministic migration edge."""

    migration_id: str
    source_schema_id: str
    destination_schema_id: str
    transform: MigrationTransform = field(repr=False, compare=False)
    declared_losses: tuple[MigrationLoss, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        _require_identifier(self.migration_id, "migration_id")
        _require_identifier(self.source_schema_id, "source_schema_id")
        _require_identifier(self.destination_schema_id, "destination_schema_id")
        if self.source_schema_id == self.destination_schema_id:
            raise MigrationCycleError("self migrations are cycles")
        if not callable(self.transform):
            raise TypeError("migration transform must be callable")
        object.__setattr__(
            self, "declared_losses", _dedupe_losses(self.declared_losses)
        )
        if not isinstance(self.description, str):
            raise TypeError("migration description must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_loss_report": LossReport(self.declared_losses).to_dict(),
            "description": self.description,
            "destination_schema_id": self.destination_schema_id,
            "migration_id": self.migration_id,
            "source_schema_id": self.source_schema_id,
        }


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    """Persistable compatibility decision for two exact schema IDs."""

    source_schema_id: str
    destination_schema_id: str
    kind: CompatibilityKind
    migration_path: tuple[str, ...] = ()

    @property
    def compatible(self) -> bool:
        return self.kind is not CompatibilityKind.INCOMPATIBLE

    @property
    def requires_migration(self) -> bool:
        return self.kind is CompatibilityKind.MIGRATION_REQUIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "destination_schema_id": self.destination_schema_id,
            "kind": self.kind.value,
            "migration_path": list(self.migration_path),
            "requires_migration": self.requires_migration,
            "source_schema_id": self.source_schema_id,
        }


@dataclass(frozen=True, slots=True)
class MigrationStepReceipt:
    """Digest and loss binding for one executed migration edge."""

    migration_id: str
    source_schema_id: str
    destination_schema_id: str
    source_digest: str
    destination_digest: str
    loss_report: LossReport

    def __post_init__(self) -> None:
        _require_identifier(self.migration_id, "migration_id")
        _require_identifier(self.source_schema_id, "source_schema_id")
        _require_identifier(self.destination_schema_id, "destination_schema_id")
        _require_digest(self.source_digest, "source_digest")
        _require_digest(self.destination_digest, "destination_digest")
        if not isinstance(self.loss_report, LossReport):
            raise TypeError("migration step loss_report must be a LossReport")

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
    """Tamper-evident receipt binding both ends of an executed path."""

    receipt_id: str
    registry_digest: str
    source_schema_id: str
    destination_schema_id: str
    source_digest: str
    destination_digest: str
    schema_path: tuple[str, ...]
    steps: tuple[MigrationStepReceipt, ...]
    loss_report: LossReport
    schema_id: str = MIGRATION_RECEIPT_SCHEMA_ID
    protocol_id: str = IR_SCHEMA_REGISTRY_PROTOCOL_ID

    def __post_init__(self) -> None:
        for name in (
            "receipt_id",
            "registry_digest",
            "source_digest",
            "destination_digest",
        ):
            _require_digest(getattr(self, name), name)
        _require_identifier(self.source_schema_id, "source_schema_id")
        _require_identifier(self.destination_schema_id, "destination_schema_id")
        if self.schema_id != MIGRATION_RECEIPT_SCHEMA_ID:
            raise ReceiptVerificationError("unknown migration receipt schema_id")
        if self.protocol_id != IR_SCHEMA_REGISTRY_PROTOCOL_ID:
            raise ReceiptVerificationError("migration receipt protocol_id mismatch")
        if not isinstance(self.loss_report, LossReport):
            raise TypeError("migration receipt loss_report must be a LossReport")
        object.__setattr__(self, "schema_path", tuple(self.schema_path))
        object.__setattr__(self, "steps", tuple(self.steps))
        self._verify_structure()

    def to_dict(self, *, include_receipt_id: bool = True) -> dict[str, Any]:
        value = {
            "destination_digest": self.destination_digest,
            "destination_schema_id": self.destination_schema_id,
            "loss_report": self.loss_report.to_dict(),
            "protocol_id": self.protocol_id,
            "registry_digest": self.registry_digest,
            "schema_id": self.schema_id,
            "schema_path": list(self.schema_path),
            "source_digest": self.source_digest,
            "source_schema_id": self.source_schema_id,
            "steps": [step.to_dict() for step in self.steps],
        }
        if include_receipt_id:
            value["receipt_id"] = self.receipt_id
        return value

    def verify(
        self,
        source_payload: Mapping[str, Any],
        destination_payload: Mapping[str, Any],
    ) -> bool:
        """Raise on a broken binding and otherwise return ``True``."""

        self._verify_structure()
        if canonical_payload_digest(source_payload) != self.source_digest:
            raise ReceiptVerificationError("migration receipt source digest mismatch")
        if canonical_payload_digest(destination_payload) != self.destination_digest:
            raise ReceiptVerificationError(
                "migration receipt destination digest mismatch"
            )
        expected_id = canonical_payload_digest(
            self.to_dict(include_receipt_id=False)
        )
        if expected_id != self.receipt_id:
            raise ReceiptVerificationError("migration receipt identity mismatch")
        return True

    def _verify_structure(self) -> None:
        if self.source_schema_id == self.destination_schema_id and self.steps:
            raise ReceiptVerificationError(
                "an exact-schema receipt must not contain migration steps"
            )
        expected_schema = self.source_schema_id
        expected_digest = self.source_digest
        expected_path = [expected_schema]
        losses: list[MigrationLoss] = []
        for step in self.steps:
            if not isinstance(step, MigrationStepReceipt):
                raise TypeError(
                    "migration receipt steps must be MigrationStepReceipt values"
                )
            if (
                step.source_schema_id != expected_schema
                or step.source_digest != expected_digest
            ):
                raise ReceiptVerificationError(
                    "migration receipt step chain is discontinuous"
                )
            expected_schema = step.destination_schema_id
            expected_digest = step.destination_digest
            expected_path.append(expected_schema)
            losses.extend(step.loss_report.losses)
        if tuple(expected_path) != self.schema_path:
            raise ReceiptVerificationError(
                "receipt schema_path does not match its migration steps"
            )
        if (
            expected_schema != self.destination_schema_id
            or expected_digest != self.destination_digest
        ):
            raise ReceiptVerificationError(
                "migration receipt steps do not bind the destination"
            )
        if LossReport(tuple(losses)) != self.loss_report:
            raise ReceiptVerificationError(
                "migration receipt aggregate loss report mismatch"
            )


@dataclass(frozen=True, slots=True)
class MigrationOutcome:
    """The migrated payload and its audit receipt."""

    payload: Mapping[str, Any]
    receipt: MigrationReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("migration outcome payload must be a mapping")
        if not isinstance(self.receipt, MigrationReceipt):
            raise TypeError("migration outcome receipt must be a MigrationReceipt")
        object.__setattr__(self, "payload", _freeze_json(_clone_payload(self.payload)))

    def __iter__(self) -> Iterator[Any]:
        yield self.payload
        yield self.receipt


class IRSchemaRegistry(Mapping[str, SchemaRegistration]):
    """Thread-safe registry of exact schemas and an acyclic migration graph."""

    protocol_id: Final = IR_SCHEMA_REGISTRY_PROTOCOL_ID

    def __init__(
        self,
        schemas: Iterable[SchemaRegistration | str] = (),
        migrations: Iterable[SchemaMigration] = (),
        compatibilities: Iterable[CompatibilityDeclaration] = (),
        *,
        schema_id_field: str = DEFAULT_SCHEMA_ID_FIELD,
        verify_determinism: bool = True,
    ) -> None:
        _require_identifier(schema_id_field, "schema_id_field")
        self._schema_id_field = schema_id_field
        self._verify_determinism = bool(verify_determinism)
        self._schemas: dict[str, SchemaRegistration] = {}
        self._migrations: dict[tuple[str, str], SchemaMigration] = {}
        self._migration_ids: set[str] = set()
        self._compatibilities: dict[
            tuple[str, str], CompatibilityDeclaration
        ] = {}
        self._lock = RLock()
        for schema in schemas:
            self.register_schema(schema)
        for declaration in compatibilities:
            self.declare_compatibility(declaration)
        for migration in migrations:
            self.register_migration(migration)

    def __getitem__(self, schema_id: str) -> SchemaRegistration:
        try:
            return self._schemas[schema_id]
        except KeyError as exc:
            raise UnknownSchemaError(f"unknown schema_id {schema_id!r}") from exc

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(tuple(sorted(self._schemas)))

    def __len__(self) -> int:
        return len(self._schemas)

    @property
    def schema_id_field(self) -> str:
        return self._schema_id_field

    @property
    def schemas(self) -> Mapping[str, SchemaRegistration]:
        return MappingProxyType(self._schemas)

    @property
    def migrations(self) -> Mapping[tuple[str, str], SchemaMigration]:
        return MappingProxyType(self._migrations)

    @property
    def compatibilities(
        self,
    ) -> Mapping[tuple[str, str], CompatibilityDeclaration]:
        return MappingProxyType(self._compatibilities)

    def register_schema(
        self,
        schema: SchemaRegistration | str,
        *,
        description: str = "",
        validator: SchemaValidator | None = None,
    ) -> SchemaRegistration:
        registration = (
            schema
            if isinstance(schema, SchemaRegistration)
            else SchemaRegistration(schema, description, validator)
        )
        with self._lock:
            if registration.schema_id in self._schemas:
                raise DuplicateSchemaError(
                    f"schema_id {registration.schema_id!r} is already registered"
                )
            self._schemas[registration.schema_id] = registration
        return registration

    def require_schema(self, schema_id: str) -> SchemaRegistration:
        return self[schema_id]

    def declare_compatibility(
        self,
        declaration: CompatibilityDeclaration | None = None,
        *,
        source_schema_id: str = "",
        destination_schema_id: str = "",
        rationale: str = "",
    ) -> CompatibilityDeclaration:
        item = declaration or CompatibilityDeclaration(
            source_schema_id, destination_schema_id, rationale
        )
        with self._lock:
            self._require_known(item.source_schema_id)
            self._require_known(item.destination_schema_id)
            key = (item.source_schema_id, item.destination_schema_id)
            if key in self._compatibilities:
                raise SchemaRegistryError(
                    f"compatibility {key!r} is already declared"
                )
            self._compatibilities[key] = item
        return item

    register_compatibility = declare_compatibility

    def register_migration(
        self,
        migration: SchemaMigration | None = None,
        *,
        migration_id: str = "",
        source_schema_id: str = "",
        destination_schema_id: str = "",
        transform: MigrationTransform | None = None,
        declared_losses: Sequence[MigrationLoss] = (),
        description: str = "",
    ) -> SchemaMigration:
        if migration is None:
            if transform is None:
                raise TypeError("migration transform must be supplied")
            migration = SchemaMigration(
                migration_id=migration_id,
                source_schema_id=source_schema_id,
                destination_schema_id=destination_schema_id,
                transform=transform,
                declared_losses=tuple(declared_losses),
                description=description,
            )
        with self._lock:
            self._require_known(migration.source_schema_id)
            self._require_known(migration.destination_schema_id)
            edge = (
                migration.source_schema_id,
                migration.destination_schema_id,
            )
            if edge in self._migrations or migration.migration_id in self._migration_ids:
                raise DuplicateMigrationError(
                    f"migration edge or ID is already registered: {migration.migration_id!r}"
                )
            if self._reachable(
                migration.destination_schema_id, migration.source_schema_id
            ):
                raise MigrationCycleError(
                    "migration would create a cycle: "
                    f"{migration.source_schema_id!r} -> "
                    f"{migration.destination_schema_id!r}"
                )
            self._migrations[edge] = migration
            self._migration_ids.add(migration.migration_id)
        return migration

    def compatibility(
        self, source_schema_id: str, destination_schema_id: str
    ) -> CompatibilityResult:
        with self._lock:
            self._require_known(source_schema_id)
            self._require_known(destination_schema_id)
            if source_schema_id == destination_schema_id:
                return CompatibilityResult(
                    source_schema_id,
                    destination_schema_id,
                    CompatibilityKind.EXACT,
                )
            if (source_schema_id, destination_schema_id) in self._compatibilities:
                return CompatibilityResult(
                    source_schema_id,
                    destination_schema_id,
                    CompatibilityKind.DECLARED,
                )
            path = self._find_path(source_schema_id, destination_schema_id)
            if path:
                return CompatibilityResult(
                    source_schema_id,
                    destination_schema_id,
                    CompatibilityKind.MIGRATION_REQUIRED,
                    tuple(step.migration_id for step in path),
                )
            return CompatibilityResult(
                source_schema_id,
                destination_schema_id,
                CompatibilityKind.INCOMPATIBLE,
            )

    check_compatibility = compatibility
    negotiate = compatibility

    def find_migration_path(
        self, source_schema_id: str, destination_schema_id: str
    ) -> tuple[SchemaMigration, ...]:
        with self._lock:
            self._require_known(source_schema_id)
            self._require_known(destination_schema_id)
            if source_schema_id == destination_schema_id:
                return ()
            path = self._find_path(source_schema_id, destination_schema_id)
            if not path:
                raise MigrationPathError(
                    "no explicit migration path from "
                    f"{source_schema_id!r} to {destination_schema_id!r}"
                )
            return path

    migration_path = find_migration_path

    def migrate(
        self,
        payload: Mapping[str, Any],
        destination_schema_id: str,
        *,
        source_schema_id: str | None = None,
    ) -> MigrationOutcome:
        """Execute the deterministic path and return its bound receipt."""

        original = _clone_payload(payload)
        embedded_source = self._payload_schema_id(original)
        if source_schema_id is not None and source_schema_id != embedded_source:
            raise SchemaValidationError(
                "supplied source_schema_id does not exactly match payload "
                f"{self._schema_id_field!r}"
            )
        source_schema_id = embedded_source
        with self._lock:
            self._require_known(source_schema_id)
            self._require_known(destination_schema_id)
            path = self.find_migration_path(
                source_schema_id, destination_schema_id
            )
            registry_digest = self.registry_digest()

        self._validate(source_schema_id, original)
        source_digest = canonical_payload_digest(original)
        current: Mapping[str, Any] = original
        step_receipts: list[MigrationStepReceipt] = []
        all_losses: list[MigrationLoss] = []

        for migration in path:
            step_source_digest = canonical_payload_digest(current)
            migrated, losses = self._execute(migration, current)
            self._validate(migration.destination_schema_id, migrated)
            step_destination_digest = canonical_payload_digest(migrated)
            loss_report = LossReport(losses)
            step_receipts.append(
                MigrationStepReceipt(
                    migration_id=migration.migration_id,
                    source_schema_id=migration.source_schema_id,
                    destination_schema_id=migration.destination_schema_id,
                    source_digest=step_source_digest,
                    destination_digest=step_destination_digest,
                    loss_report=loss_report,
                )
            )
            all_losses.extend(loss_report.losses)
            current = migrated

        destination_digest = canonical_payload_digest(current)
        schema_path = (
            source_schema_id,
            *(step.destination_schema_id for step in step_receipts),
        )
        loss_report = LossReport(tuple(all_losses))
        receipt_without_id = {
            "destination_digest": destination_digest,
            "destination_schema_id": destination_schema_id,
            "loss_report": loss_report.to_dict(),
            "protocol_id": IR_SCHEMA_REGISTRY_PROTOCOL_ID,
            "registry_digest": registry_digest,
            "schema_id": MIGRATION_RECEIPT_SCHEMA_ID,
            "schema_path": list(schema_path),
            "source_digest": source_digest,
            "source_schema_id": source_schema_id,
            "steps": [step.to_dict() for step in step_receipts],
        }
        receipt = MigrationReceipt(
            receipt_id=canonical_payload_digest(receipt_without_id),
            registry_digest=registry_digest,
            source_schema_id=source_schema_id,
            destination_schema_id=destination_schema_id,
            source_digest=source_digest,
            destination_digest=destination_digest,
            schema_path=schema_path,
            steps=tuple(step_receipts),
            loss_report=loss_report,
        )
        immutable_payload = _freeze_json(_clone_payload(current))
        receipt.verify(original, immutable_payload)
        return MigrationOutcome(immutable_payload, receipt)

    def verify_receipt(
        self,
        receipt: MigrationReceipt,
        source_payload: Mapping[str, Any],
        destination_payload: Mapping[str, Any],
        *,
        reexecute: bool = True,
    ) -> bool:
        """Verify payload, registry, path, and optionally transform bindings."""

        if not isinstance(receipt, MigrationReceipt):
            raise TypeError("receipt must be a MigrationReceipt")
        receipt.verify(source_payload, destination_payload)
        if receipt.registry_digest != self.registry_digest():
            raise ReceiptVerificationError(
                "migration receipt registry digest mismatch"
            )
        try:
            path = self.find_migration_path(
                receipt.source_schema_id, receipt.destination_schema_id
            )
        except SchemaRegistryError as exc:
            raise ReceiptVerificationError(
                "migration receipt references an unavailable migration path"
            ) from exc
        if tuple(step.migration_id for step in path) != tuple(
            step.migration_id for step in receipt.steps
        ):
            raise ReceiptVerificationError("migration receipt path mismatch")
        if reexecute:
            try:
                expected = self.migrate(
                    source_payload, receipt.destination_schema_id
                )
            except SchemaRegistryError as exc:
                raise ReceiptVerificationError(
                    "registered migration path could not reproduce the receipt"
                ) from exc
            if expected.receipt != receipt:
                raise ReceiptVerificationError(
                    "migration receipt does not match deterministic re-execution"
                )
        return True

    def manifest(self) -> dict[str, Any]:
        with self._lock:
            return {
                "compatibilities": [
                    item.to_dict()
                    for item in sorted(
                        self._compatibilities.values(),
                        key=lambda value: (
                            value.source_schema_id,
                            value.destination_schema_id,
                        ),
                    )
                ],
                "migrations": [
                    item.to_dict()
                    for item in sorted(
                        self._migrations.values(),
                        key=lambda value: (
                            value.source_schema_id,
                            value.destination_schema_id,
                            value.migration_id,
                        ),
                    )
                ],
                "protocol_id": IR_SCHEMA_REGISTRY_PROTOCOL_ID,
                "schema_id_field": self._schema_id_field,
                "schemas": [
                    self._schemas[key].to_dict() for key in sorted(self._schemas)
                ],
            }

    def registry_digest(self) -> str:
        return canonical_payload_digest(self.manifest())

    def _payload_schema_id(self, payload: Mapping[str, Any]) -> str:
        value = payload.get(self._schema_id_field)
        if not isinstance(value, str) or not value:
            raise SchemaValidationError(
                f"payload must contain a non-empty exact "
                f"{self._schema_id_field!r}"
            )
        return value

    def _validate(self, schema_id: str, payload: Mapping[str, Any]) -> None:
        if self._payload_schema_id(payload) != schema_id:
            raise SchemaValidationError(
                f"payload schema does not exactly match {schema_id!r}"
            )
        registration = self.require_schema(schema_id)
        if registration.validator is None:
            return
        try:
            valid = registration.validator(_clone_payload(payload))
        except Exception as exc:
            raise SchemaValidationError(
                f"validator for schema {schema_id!r} raised an exception"
            ) from exc
        if valid is False:
            raise SchemaValidationError(
                f"payload failed validator for schema {schema_id!r}"
            )

    def _execute(
        self, migration: SchemaMigration, payload: Mapping[str, Any]
    ) -> tuple[dict[str, Any], tuple[MigrationLoss, ...]]:
        first = self._run_transform(migration, payload)
        if self._verify_determinism:
            second = self._run_transform(migration, payload)
            if (
                canonical_payload_digest(first[0])
                != canonical_payload_digest(second[0])
                or first[1] != second[1]
            ):
                raise MigrationExecutionError(
                    f"migration {migration.migration_id!r} is nondeterministic"
                )
        return first

    def _run_transform(
        self, migration: SchemaMigration, payload: Mapping[str, Any]
    ) -> tuple[dict[str, Any], tuple[MigrationLoss, ...]]:
        try:
            raw = migration.transform(_freeze_json(_clone_payload(payload)))
        except Exception as exc:
            raise MigrationExecutionError(
                f"migration {migration.migration_id!r} failed"
            ) from exc
        if isinstance(raw, MigrationResult):
            migrated = _clone_payload(raw.payload)
            runtime_losses = raw.losses
        elif isinstance(raw, Mapping):
            migrated = _clone_payload(raw)
            runtime_losses = ()
        else:
            raise MigrationExecutionError(
                f"migration {migration.migration_id!r} returned "
                f"{type(raw).__name__}, expected a mapping or MigrationResult"
            )
        migrated[self._schema_id_field] = migration.destination_schema_id
        losses = _dedupe_losses(
            (*migration.declared_losses, *runtime_losses)
        )
        return migrated, losses

    def _require_known(self, schema_id: str) -> None:
        if schema_id not in self._schemas:
            raise UnknownSchemaError(f"unknown schema_id {schema_id!r}")

    def _reachable(self, source: str, destination: str) -> bool:
        if source == destination:
            return True
        return bool(self._find_path(source, destination))

    def _find_path(
        self, source: str, destination: str
    ) -> tuple[SchemaMigration, ...]:
        outgoing: dict[str, list[SchemaMigration]] = {}
        for migration in self._migrations.values():
            outgoing.setdefault(migration.source_schema_id, []).append(migration)
        for migrations in outgoing.values():
            migrations.sort(
                key=lambda value: (
                    value.destination_schema_id,
                    value.migration_id,
                )
            )
        queue: deque[tuple[str, tuple[SchemaMigration, ...]]] = deque(
            [(source, ())]
        )
        visited = {source}
        while queue:
            node, path = queue.popleft()
            for migration in outgoing.get(node, ()):
                next_node = migration.destination_schema_id
                next_path = (*path, migration)
                if next_node == destination:
                    return next_path
                if next_node not in visited:
                    visited.add(next_node)
                    queue.append((next_node, next_path))
        return ()


def canonical_payload_digest(payload: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 digest for a JSON-compatible mapping."""

    if not isinstance(payload, Mapping):
        raise TypeError("digest payload must be a mapping")
    encoded = json.dumps(
        _canonical_json_value(payload),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def verify_migration_receipt(
    receipt: MigrationReceipt,
    source_payload: Mapping[str, Any],
    destination_payload: Mapping[str, Any],
    *,
    registry: IRSchemaRegistry | None = None,
    reexecute: bool = True,
) -> bool:
    """Verify a receipt, including registry/path bindings when supplied."""

    if registry is not None:
        return registry.verify_receipt(
            receipt,
            source_payload,
            destination_payload,
            reexecute=reexecute,
        )
    return receipt.verify(source_payload, destination_payload)


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical payload mapping keys must be strings")
            normalized[key] = _canonical_json_value(child)
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(child) for child in value]
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical payload numbers must be finite")
        return value
    raise TypeError(
        f"canonical payload contains unsupported {type(value).__name__}"
    )


def _clone_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("IR payload must be a mapping")
    normalized = _canonical_json_value(payload)
    assert isinstance(normalized, dict)
    return normalized


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_json(child) for key, child in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    if isinstance(value, tuple):
        return tuple(_freeze_json(child) for child in value)
    return value


def _dedupe_losses(losses: Iterable[MigrationLoss]) -> tuple[MigrationLoss, ...]:
    unique: dict[tuple[str, str, tuple[str, ...]], MigrationLoss] = {}
    for loss in losses:
        if not isinstance(loss, MigrationLoss):
            raise TypeError("loss reports must contain MigrationLoss values")
        key = (loss.code, loss.message, tuple(loss.field_paths))
        unique.setdefault(key, loss)
    return tuple(
        unique[key]
        for key in sorted(unique, key=lambda item: (item[0], item[2], item[1]))
    )


def _require_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"{name} must be an exact identifier without wildcards or ranges"
        )


def _require_digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{name} must be a canonical sha256 digest")


# Concise aliases for callers that use the protocol vocabulary.
SchemaDefinition = SchemaRegistration
Migration = SchemaMigration
Loss = MigrationLoss
SchemaCompatibility = CompatibilityKind
IR_MIGRATION_RECEIPT_SCHEMA_ID = MIGRATION_RECEIPT_SCHEMA_ID
canonical_digest = canonical_payload_digest


__all__ = [
    "CompatibilityDeclaration",
    "CompatibilityKind",
    "CompatibilityResult",
    "DEFAULT_SCHEMA_ID_FIELD",
    "DuplicateMigrationError",
    "DuplicateSchemaError",
    "IR_SCHEMA_REGISTRY_PROTOCOL_ID",
    "IR_MIGRATION_RECEIPT_SCHEMA_ID",
    "IRSchemaRegistry",
    "Loss",
    "LossReport",
    "MIGRATION_RECEIPT_SCHEMA_ID",
    "Migration",
    "MigrationCycleError",
    "MigrationExecutionError",
    "MigrationLoss",
    "MigrationOutcome",
    "MigrationPathError",
    "MigrationReceipt",
    "MigrationResult",
    "MigrationStepReceipt",
    "ReceiptVerificationError",
    "SchemaCompatibility",
    "SchemaDefinition",
    "SchemaMigration",
    "SchemaRegistration",
    "SchemaRegistryError",
    "SchemaValidationError",
    "UnknownSchemaError",
    "canonical_payload_digest",
    "canonical_digest",
    "verify_migration_receipt",
]

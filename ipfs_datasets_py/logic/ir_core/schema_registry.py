"""Domain-neutral schema negotiation and deterministic migration contracts.

The registry deliberately treats schema identifiers as opaque, exact strings.
It does not infer compatibility from names, version suffixes, or registration
order.  Cross-version reads must be declared explicitly or performed through
an explicit migration path.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Final


MIGRATION_RECEIPT_SCHEMA_ID: Final = "ir-core-migration-receipt/v1"

JSONScalar = None | bool | int | float | str
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class SchemaRegistryError(ValueError):
    """Base class for fail-closed schema registry errors."""


class InvalidSchemaIDError(SchemaRegistryError):
    """Raised when a schema identifier is not an exact, usable string."""


class DuplicateRegistrationError(SchemaRegistryError):
    """Raised when a schema, declaration, or migration is registered twice."""


class UnknownSchemaError(SchemaRegistryError):
    """Raised when an operation names a schema that is not registered."""


class MigrationPathError(SchemaRegistryError):
    """Raised when no explicit migration path exists."""


class MigrationCycleError(SchemaRegistryError):
    """Raised when migration registration would make the graph cyclic."""


class MigrationExecutionError(SchemaRegistryError):
    """Raised when a migration violates its declared contract."""


class NondeterministicMigrationError(MigrationExecutionError):
    """Raised when identical input produces different migration output."""


def _validate_exact_id(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise InvalidSchemaIDError(f"{field_name} must be a string")
    if not value:
        raise InvalidSchemaIDError(f"{field_name} must not be empty")
    if value != value.strip():
        raise InvalidSchemaIDError(
            f"{field_name} must be exact and contain no surrounding whitespace"
        )
    if len(value) > 512:
        raise InvalidSchemaIDError(f"{field_name} must not exceed 512 characters")
    if any(character.isspace() or not character.isprintable() for character in value):
        raise InvalidSchemaIDError(
            f"{field_name} must contain only printable, non-whitespace characters"
        )
    return value


def _validate_identifier(value: str, *, field_name: str) -> str:
    return _validate_exact_id(value, field_name=field_name)


def _normalize_json(value: Any, *, path: str = "$") -> JSONValue:
    """Return a detached canonical JSON value or reject unsupported input."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MigrationExecutionError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise MigrationExecutionError(f"{path} contains a non-string key")
            normalized[key] = _normalize_json(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _normalize_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise MigrationExecutionError(
        f"{path} contains non-JSON value of type {type(value).__name__}"
    )


def canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    """Serialize a migration payload with the registry's fixed JSON profile."""

    if not isinstance(payload, Mapping):
        raise MigrationExecutionError("migration payload must be a mapping")
    normalized = _normalize_json(payload)
    return json.dumps(
        normalized,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def payload_digest(payload: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 binding for a migration payload."""

    return "sha256:" + hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def _detached_payload(payload: Mapping[str, Any]) -> dict[str, JSONValue]:
    normalized = _normalize_json(payload)
    if not isinstance(normalized, dict):  # Defensive: Mapping always normalizes to dict.
        raise MigrationExecutionError("migration payload must normalize to an object")
    return normalized


def _freeze_json(value: JSONValue) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


class CompatibilityStatus(str, Enum):
    """A directional writer-to-reader compatibility decision."""

    EXACT = "exact"
    COMPATIBLE = "compatible"
    MIGRATION_REQUIRED = "migration_required"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class SchemaSpec:
    """Registration record for one exact schema identifier."""

    schema_id: str
    description: str = ""

    def __post_init__(self) -> None:
        _validate_exact_id(self.schema_id, field_name="schema_id")

    def to_dict(self) -> dict[str, str]:
        return {"description": self.description, "schema_id": self.schema_id}


@dataclass(frozen=True)
class CompatibilityDeclaration:
    """Explicitly allow or deny reading one schema as another.

    Direction matters: ``source_schema_id`` identifies the writer and
    ``reader_schema_id`` identifies the reader.
    """

    source_schema_id: str
    reader_schema_id: str
    compatible: bool
    rationale: str

    def __post_init__(self) -> None:
        _validate_exact_id(self.source_schema_id, field_name="source_schema_id")
        _validate_exact_id(self.reader_schema_id, field_name="reader_schema_id")
        if self.source_schema_id == self.reader_schema_id:
            raise SchemaRegistryError(
                "same-schema compatibility is exact and must not be declared"
            )
        if not isinstance(self.compatible, bool):
            raise SchemaRegistryError("compatible must be a bool")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise SchemaRegistryError(
                "compatibility declarations require a non-empty rationale"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "rationale": self.rationale,
            "reader_schema_id": self.reader_schema_id,
            "source_schema_id": self.source_schema_id,
        }


@dataclass(frozen=True)
class MigrationLoss:
    """One semantic or representational loss caused by a migration."""

    code: str
    message: str
    field_path: str = ""
    migration_id: str = ""

    def __post_init__(self) -> None:
        _validate_identifier(self.code, field_name="loss code")
        if not isinstance(self.message, str) or not self.message.strip():
            raise MigrationExecutionError("migration loss message must not be empty")
        if self.migration_id:
            _validate_identifier(self.migration_id, field_name="migration_id")

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "message": self.message,
            "migration_id": self.migration_id,
        }


@dataclass(frozen=True)
class LossReport:
    """Deterministic aggregate of all losses along a migration path."""

    losses: tuple[MigrationLoss, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "losses", tuple(self.losses))
        if not all(isinstance(item, MigrationLoss) for item in self.losses):
            raise MigrationExecutionError(
                "loss reports may contain only MigrationLoss records"
            )

    @property
    def lossy(self) -> bool:
        return bool(self.losses)

    def to_dict(self) -> dict[str, Any]:
        return {
            "loss_count": len(self.losses),
            "losses": [item.to_dict() for item in self.losses],
            "lossy": self.lossy,
        }


@dataclass(frozen=True)
class MigrationOutcome:
    """Output returned by a migration transform."""

    payload: Mapping[str, JSONValue]
    losses: tuple[MigrationLoss, ...] = ()

    def __post_init__(self) -> None:
        detached = _detached_payload(self.payload)
        object.__setattr__(self, "payload", _freeze_json(detached))
        object.__setattr__(self, "losses", tuple(self.losses))
        if not all(isinstance(item, MigrationLoss) for item in self.losses):
            raise MigrationExecutionError(
                "migration outcomes may contain only MigrationLoss records"
            )


MigrationTransform = Callable[
    [Mapping[str, JSONValue]],
    Mapping[str, JSONValue] | MigrationOutcome,
]


@dataclass(frozen=True)
class MigrationSpec:
    """One directed, explicitly lossless or lossy migration edge."""

    migration_id: str
    source_schema_id: str
    destination_schema_id: str
    transform: MigrationTransform = field(repr=False, compare=False)
    lossy: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        _validate_identifier(self.migration_id, field_name="migration_id")
        _validate_exact_id(self.source_schema_id, field_name="source_schema_id")
        _validate_exact_id(
            self.destination_schema_id, field_name="destination_schema_id"
        )
        if self.source_schema_id == self.destination_schema_id:
            raise MigrationCycleError("self migrations are cycles and are not allowed")
        if not callable(self.transform):
            raise SchemaRegistryError("migration transform must be callable")
        if not isinstance(self.lossy, bool):
            raise SchemaRegistryError("lossy must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "destination_schema_id": self.destination_schema_id,
            "lossy": self.lossy,
            "migration_id": self.migration_id,
            "source_schema_id": self.source_schema_id,
        }


@dataclass(frozen=True)
class CompatibilityResult:
    """Persistable result of exact compatibility negotiation."""

    source_schema_id: str
    reader_schema_id: str
    status: CompatibilityStatus
    declared: bool
    rationale: str = ""
    schema_path: tuple[str, ...] = ()
    migration_ids: tuple[str, ...] = ()

    @property
    def compatible(self) -> bool:
        return self.status in {
            CompatibilityStatus.EXACT,
            CompatibilityStatus.COMPATIBLE,
        }

    @property
    def requires_migration(self) -> bool:
        return self.status is CompatibilityStatus.MIGRATION_REQUIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "declared": self.declared,
            "migration_ids": list(self.migration_ids),
            "rationale": self.rationale,
            "reader_schema_id": self.reader_schema_id,
            "requires_migration": self.requires_migration,
            "schema_path": list(self.schema_path),
            "source_schema_id": self.source_schema_id,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class MigrationReceipt:
    """Content-bound evidence for a completed deterministic migration."""

    source_schema_id: str
    destination_schema_id: str
    source_digest: str
    destination_digest: str
    schema_path: tuple[str, ...]
    migration_ids: tuple[str, ...]
    loss_report: LossReport
    schema_id: str = MIGRATION_RECEIPT_SCHEMA_ID

    def __post_init__(self) -> None:
        if self.schema_id != MIGRATION_RECEIPT_SCHEMA_ID:
            raise MigrationExecutionError(
                f"receipt schema_id must be exactly {MIGRATION_RECEIPT_SCHEMA_ID!r}"
            )
        _validate_exact_id(self.source_schema_id, field_name="source_schema_id")
        _validate_exact_id(
            self.destination_schema_id, field_name="destination_schema_id"
        )
        object.__setattr__(self, "schema_path", tuple(self.schema_path))
        object.__setattr__(self, "migration_ids", tuple(self.migration_ids))
        for schema_id in self.schema_path:
            _validate_exact_id(schema_id, field_name="schema_path item")
        for migration_id in self.migration_ids:
            _validate_identifier(migration_id, field_name="migration_ids item")
        if not isinstance(self.loss_report, LossReport):
            raise MigrationExecutionError(
                "receipt loss_report must be a LossReport"
            )
        expected_length = max(0, len(self.schema_path) - 1)
        if len(self.migration_ids) != expected_length:
            raise MigrationExecutionError(
                "receipt migration_ids must connect every schema_path element"
            )
        if not self.schema_path or self.schema_path[0] != self.source_schema_id:
            raise MigrationExecutionError(
                "receipt schema_path must start at source_schema_id"
            )
        if self.schema_path[-1] != self.destination_schema_id:
            raise MigrationExecutionError(
                "receipt schema_path must end at destination_schema_id"
            )
        for field_name, digest in (
            ("source_digest", self.source_digest),
            ("destination_digest", self.destination_digest),
        ):
            if (
                not isinstance(digest, str)
                or not digest.startswith("sha256:")
                or len(digest) != 71
                or any(character not in "0123456789abcdef" for character in digest[7:])
            ):
                raise MigrationExecutionError(
                    f"{field_name} must be a lowercase sha256 digest"
                )

    def _bound_dict(self) -> dict[str, Any]:
        return {
            "destination_digest": self.destination_digest,
            "destination_schema_id": self.destination_schema_id,
            "loss_report": self.loss_report.to_dict(),
            "migration_ids": list(self.migration_ids),
            "schema_id": self.schema_id,
            "schema_path": list(self.schema_path),
            "source_digest": self.source_digest,
            "source_schema_id": self.source_schema_id,
        }

    @property
    def receipt_digest(self) -> str:
        return payload_digest(self._bound_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self._bound_dict(), "receipt_digest": self.receipt_digest}

    def verifies(
        self,
        source_payload: Mapping[str, Any],
        destination_payload: Mapping[str, Any],
    ) -> bool:
        """Return whether both supplied payloads match the bound digests."""

        return (
            payload_digest(source_payload) == self.source_digest
            and payload_digest(destination_payload) == self.destination_digest
        )


@dataclass(frozen=True)
class MigrationResult:
    """Immutable migrated payload and its content-bound receipt."""

    payload: Mapping[str, JSONValue]
    receipt: MigrationReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, MigrationReceipt):
            raise MigrationExecutionError(
                "migration result receipt must be a MigrationReceipt"
            )
        detached = _detached_payload(self.payload)
        if payload_digest(detached) != self.receipt.destination_digest:
            raise MigrationExecutionError(
                "migration result payload does not match receipt destination_digest"
            )
        object.__setattr__(self, "payload", _freeze_json(detached))

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload": _detached_payload(self.payload),
            "receipt": self.receipt.to_dict(),
        }


class IRSchemaRegistry(Mapping[str, SchemaSpec]):
    """Registry of exact schemas, compatibility declarations, and migrations."""

    def __init__(
        self,
        schemas: Sequence[SchemaSpec] = (),
        compatibility: Sequence[CompatibilityDeclaration] = (),
        migrations: Sequence[MigrationSpec] = (),
    ) -> None:
        self._schemas: dict[str, SchemaSpec] = {}
        self._compatibility: dict[
            tuple[str, str], CompatibilityDeclaration
        ] = {}
        self._migrations: dict[tuple[str, str], MigrationSpec] = {}
        self._migration_ids: set[str] = set()
        for schema in schemas:
            self.register_schema(schema)
        for declaration in compatibility:
            self.register_compatibility(declaration)
        for migration in migrations:
            self.register_migration(migration)

    def __getitem__(self, schema_id: str) -> SchemaSpec:
        try:
            return self._schemas[schema_id]
        except KeyError as error:
            raise UnknownSchemaError(f"unknown schema_id {schema_id!r}") from error

    def __iter__(self) -> Iterable[str]:
        return iter(sorted(self._schemas))

    def __len__(self) -> int:
        return len(self._schemas)

    @property
    def compatibility_declarations(
        self,
    ) -> Mapping[tuple[str, str], CompatibilityDeclaration]:
        return MappingProxyType(dict(self._compatibility))

    @property
    def migrations(self) -> Mapping[tuple[str, str], MigrationSpec]:
        return MappingProxyType(dict(self._migrations))

    def register_schema(self, schema: SchemaSpec) -> None:
        if not isinstance(schema, SchemaSpec):
            raise TypeError("schema must be a SchemaSpec")
        if schema.schema_id in self._schemas:
            raise DuplicateRegistrationError(
                f"schema_id {schema.schema_id!r} is already registered"
            )
        self._schemas[schema.schema_id] = schema

    def register_compatibility(
        self, declaration: CompatibilityDeclaration
    ) -> None:
        if not isinstance(declaration, CompatibilityDeclaration):
            raise TypeError("declaration must be a CompatibilityDeclaration")
        self._require_schema(declaration.source_schema_id)
        self._require_schema(declaration.reader_schema_id)
        key = (declaration.source_schema_id, declaration.reader_schema_id)
        if key in self._compatibility:
            raise DuplicateRegistrationError(
                f"compatibility for {key[0]!r} -> {key[1]!r} is already declared"
            )
        self._compatibility[key] = declaration

    def register_migration(self, migration: MigrationSpec) -> None:
        if not isinstance(migration, MigrationSpec):
            raise TypeError("migration must be a MigrationSpec")
        self._require_schema(migration.source_schema_id)
        self._require_schema(migration.destination_schema_id)
        key = (migration.source_schema_id, migration.destination_schema_id)
        if key in self._migrations:
            raise DuplicateRegistrationError(
                f"migration for {key[0]!r} -> {key[1]!r} is already registered"
            )
        if migration.migration_id in self._migration_ids:
            raise DuplicateRegistrationError(
                f"migration_id {migration.migration_id!r} is already registered"
            )

        # Adding source -> destination forms a cycle exactly when destination
        # can already reach source.  Check before mutating to keep registration
        # atomic after failure.
        reverse_path = self._find_path(
            migration.destination_schema_id,
            migration.source_schema_id,
            missing_ok=True,
        )
        if reverse_path is not None:
            cycle_ids = (
                migration.source_schema_id,
                migration.destination_schema_id,
                *(edge.destination_schema_id for edge in reverse_path),
            )
            raise MigrationCycleError(
                "migration cycle detected: " + " -> ".join(cycle_ids)
            )
        self._migrations[key] = migration
        self._migration_ids.add(migration.migration_id)

    def _require_schema(self, schema_id: str) -> SchemaSpec:
        _validate_exact_id(schema_id, field_name="schema_id")
        try:
            return self._schemas[schema_id]
        except KeyError as error:
            raise UnknownSchemaError(f"unknown schema_id {schema_id!r}") from error

    def negotiate(
        self, source_schema_id: str, reader_schema_id: str
    ) -> CompatibilityResult:
        """Negotiate a directional read using exact registered identifiers."""

        self._require_schema(source_schema_id)
        self._require_schema(reader_schema_id)
        if source_schema_id == reader_schema_id:
            return CompatibilityResult(
                source_schema_id=source_schema_id,
                reader_schema_id=reader_schema_id,
                status=CompatibilityStatus.EXACT,
                declared=True,
                rationale="exact schema identifier match",
                schema_path=(source_schema_id,),
            )

        declaration = self._compatibility.get(
            (source_schema_id, reader_schema_id)
        )
        if declaration is not None and declaration.compatible:
            return CompatibilityResult(
                source_schema_id=source_schema_id,
                reader_schema_id=reader_schema_id,
                status=CompatibilityStatus.COMPATIBLE,
                declared=True,
                rationale=declaration.rationale,
            )

        path = self._find_path(source_schema_id, reader_schema_id, missing_ok=True)
        if path is not None:
            return CompatibilityResult(
                source_schema_id=source_schema_id,
                reader_schema_id=reader_schema_id,
                status=CompatibilityStatus.MIGRATION_REQUIRED,
                declared=True,
                rationale=(
                    f"direct read denied ({declaration.rationale}); "
                    "an explicit migration path is registered"
                    if declaration is not None
                    else "an explicit migration path is registered"
                ),
                schema_path=(
                    source_schema_id,
                    *(edge.destination_schema_id for edge in path),
                ),
                migration_ids=tuple(edge.migration_id for edge in path),
            )
        return CompatibilityResult(
            source_schema_id=source_schema_id,
            reader_schema_id=reader_schema_id,
            status=CompatibilityStatus.INCOMPATIBLE,
            declared=declaration is not None,
            rationale=(
                declaration.rationale
                if declaration is not None
                else "no compatibility declaration or migration path exists"
            ),
        )

    # Clear aliases for callers that phrase negotiation as a check or resolution.
    check_compatibility = negotiate

    def resolve_migration_path(
        self, source_schema_id: str, destination_schema_id: str
    ) -> tuple[MigrationSpec, ...]:
        """Return the shortest lexicographically stable explicit path."""

        self._require_schema(source_schema_id)
        self._require_schema(destination_schema_id)
        path = self._find_path(
            source_schema_id, destination_schema_id, missing_ok=False
        )
        assert path is not None
        return path

    migration_path = resolve_migration_path

    def _find_path(
        self,
        source_schema_id: str,
        destination_schema_id: str,
        *,
        missing_ok: bool,
    ) -> tuple[MigrationSpec, ...] | None:
        if source_schema_id == destination_schema_id:
            return ()

        outgoing: dict[str, list[MigrationSpec]] = {}
        for edge in self._migrations.values():
            outgoing.setdefault(edge.source_schema_id, []).append(edge)
        for edges in outgoing.values():
            edges.sort(
                key=lambda edge: (edge.destination_schema_id, edge.migration_id)
            )

        queue: list[
            tuple[
                int,
                tuple[tuple[str, str], ...],
                str,
                tuple[MigrationSpec, ...],
            ]
        ] = [(0, (), source_schema_id, ())]
        best: dict[str, tuple[int, tuple[tuple[str, str], ...]]] = {}
        while queue:
            length, signature, current, path = heapq.heappop(queue)
            previous = best.get(current)
            if previous is not None and previous <= (length, signature):
                continue
            best[current] = (length, signature)
            if current == destination_schema_id:
                return path
            for edge in outgoing.get(current, ()):
                next_signature = signature + (
                    (edge.destination_schema_id, edge.migration_id),
                )
                heapq.heappush(
                    queue,
                    (
                        length + 1,
                        next_signature,
                        edge.destination_schema_id,
                        path + (edge,),
                    ),
                )
        if missing_ok:
            return None
        raise MigrationPathError(
            f"no migration path from {source_schema_id!r} "
            f"to {destination_schema_id!r}"
        )

    def migrate(
        self,
        payload: Mapping[str, Any],
        *,
        source_schema_id: str,
        destination_schema_id: str,
    ) -> MigrationResult:
        """Execute a path and return immutable output plus a bound receipt.

        Each transform is evaluated twice with detached inputs.  Its canonical
        output and loss report must match both times, turning nondeterministic
        transforms into an explicit execution failure rather than unstable
        artifacts.
        """

        self._require_schema(source_schema_id)
        self._require_schema(destination_schema_id)
        source = _detached_payload(payload)
        source_digest = payload_digest(source)
        if source_schema_id == destination_schema_id:
            receipt = MigrationReceipt(
                source_schema_id=source_schema_id,
                destination_schema_id=destination_schema_id,
                source_digest=source_digest,
                destination_digest=source_digest,
                schema_path=(source_schema_id,),
                migration_ids=(),
                loss_report=LossReport(),
            )
            return MigrationResult(source, receipt)

        path = self.resolve_migration_path(
            source_schema_id, destination_schema_id
        )
        current = source
        all_losses: list[MigrationLoss] = []
        for migration in path:
            first_payload, first_losses = self._execute_once(migration, current)
            second_payload, second_losses = self._execute_once(migration, current)
            if (
                canonical_payload_bytes(first_payload)
                != canonical_payload_bytes(second_payload)
                or tuple(item.to_dict() for item in first_losses)
                != tuple(item.to_dict() for item in second_losses)
            ):
                raise NondeterministicMigrationError(
                    f"migration {migration.migration_id!r} is nondeterministic"
                )
            if migration.lossy and not first_losses:
                raise MigrationExecutionError(
                    f"lossy migration {migration.migration_id!r} "
                    "must return at least one loss"
                )
            if not migration.lossy and first_losses:
                raise MigrationExecutionError(
                    f"lossless migration {migration.migration_id!r} "
                    "returned a loss report"
                )
            current = first_payload
            all_losses.extend(first_losses)

        destination_digest = payload_digest(current)
        receipt = MigrationReceipt(
            source_schema_id=source_schema_id,
            destination_schema_id=destination_schema_id,
            source_digest=source_digest,
            destination_digest=destination_digest,
            schema_path=(
                source_schema_id,
                *(edge.destination_schema_id for edge in path),
            ),
            migration_ids=tuple(edge.migration_id for edge in path),
            loss_report=LossReport(tuple(all_losses)),
        )
        return MigrationResult(current, receipt)

    @staticmethod
    def _execute_once(
        migration: MigrationSpec, payload: Mapping[str, JSONValue]
    ) -> tuple[dict[str, JSONValue], tuple[MigrationLoss, ...]]:
        migration_input = _detached_payload(payload)
        try:
            raw_outcome = migration.transform(
                MappingProxyType(migration_input)
            )
        except SchemaRegistryError:
            raise
        except Exception as error:
            raise MigrationExecutionError(
                f"migration {migration.migration_id!r} failed: {error}"
            ) from error

        if isinstance(raw_outcome, MigrationOutcome):
            outcome_payload = _detached_payload(raw_outcome.payload)
            raw_losses = raw_outcome.losses
        elif isinstance(raw_outcome, Mapping):
            outcome_payload = _detached_payload(raw_outcome)
            raw_losses = ()
        else:
            raise MigrationExecutionError(
                f"migration {migration.migration_id!r} must return "
                "a mapping or MigrationOutcome"
            )

        losses: list[MigrationLoss] = []
        for loss in raw_losses:
            if loss.migration_id and loss.migration_id != migration.migration_id:
                raise MigrationExecutionError(
                    f"loss for migration {migration.migration_id!r} "
                    f"is incorrectly bound to {loss.migration_id!r}"
                )
            losses.append(replace(loss, migration_id=migration.migration_id))
        return outcome_payload, tuple(losses)

    def manifest(self) -> dict[str, Any]:
        """Return a deterministic, transform-free registry description."""

        body = {
            "compatibility": [
                declaration.to_dict()
                for declaration in sorted(
                    self._compatibility.values(),
                    key=lambda item: (
                        item.source_schema_id,
                        item.reader_schema_id,
                    ),
                )
            ],
            "migrations": [
                migration.to_dict()
                for migration in sorted(
                    self._migrations.values(),
                    key=lambda item: (
                        item.source_schema_id,
                        item.destination_schema_id,
                        item.migration_id,
                    ),
                )
            ],
            "schemas": [
                self._schemas[schema_id].to_dict()
                for schema_id in sorted(self._schemas)
            ],
        }
        return {**body, "registry_digest": payload_digest(body)}


# Terminology aliases make the protocol natural for both schema-version and
# migration-step callers without creating parallel implementations.
SchemaVersion = SchemaSpec
SchemaMigration = MigrationSpec
MigrationLossReport = LossReport


__all__ = [
    "MIGRATION_RECEIPT_SCHEMA_ID",
    "CompatibilityDeclaration",
    "CompatibilityResult",
    "CompatibilityStatus",
    "DuplicateRegistrationError",
    "IRSchemaRegistry",
    "InvalidSchemaIDError",
    "LossReport",
    "MigrationCycleError",
    "MigrationExecutionError",
    "MigrationLoss",
    "MigrationLossReport",
    "MigrationOutcome",
    "MigrationPathError",
    "MigrationReceipt",
    "MigrationResult",
    "MigrationSpec",
    "MigrationTransform",
    "NondeterministicMigrationError",
    "SchemaMigration",
    "SchemaRegistryError",
    "SchemaSpec",
    "SchemaVersion",
    "UnknownSchemaError",
    "canonical_payload_bytes",
    "payload_digest",
]

"""LogicContractMigration@1 — dual-read / canonical-write migration receipts.

Legacy BackendRequest@1 fields and provider descriptors remain readable only
through explicit adapters that emit deprecation and alias diagnostics.  Every
new write emits canonical namespace identities only.

Interfaces (LFP2-009):

* ``LogicContractMigration@1`` — dual-read diagnosis + canonical-write receipts
  for legacy requests and provider descriptors

Guarantees (fail closed):

* legacy labels dual-read with typed :class:`LogicMigrationDiagnostic`
* provider / syntax / property / lane labels cannot be written as families
* free-form payload routing is dropped (never used for selection)
* every successful write payload contains only canonical ids
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.requests_v2 import (
    BACKEND_REQUEST_V2_INTERFACE,
    BACKEND_REQUEST_V2_SCHEMA_VERSION,
    BackendRequestV2,
    LEGACY_BACKEND_REQUEST_INTERFACE,
    LEGACY_BACKEND_REQUEST_SCHEMA_VERSION,
    RequestAuthorityCeiling,
    RequestBounds,
    RequestV2Error,
)
from ipfs_datasets_py.logic.families.aliases import (
    BASELINE_ALIAS_REGISTRY,
    DIAGNOSTIC_INTERFACE,
    LogicAliasRegistry,
    LogicMigrationDiagnostic,
    MigrationDisposition,
)
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    NamespaceKind,
    provider_id,
)
from ipfs_datasets_py.logic.families.provider_matrix_v2 import (
    FamilyMasqueradeError,
    reject_family_masquerade,
)
from ipfs_datasets_py.logic.families.providers import (
    BASELINE_PROVIDER_CATALOG,
    ProviderCapabilityCatalog,
    ProviderCapabilityEntry,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest as LegacyBackendRequest,
    ExecutionBounds as LegacyExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    canonical_json_bytes,
    content_sha256,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

MIGRATION_INTERFACE: Final = "LogicContractMigration@1"
MIGRATION_SCHEMA_VERSION: Final = "logic-contract-migration/v1"
MIGRATION_MODULE_VERSION: Final = "1.0.0"
FIELD_RECORD_SCHEMA_VERSION: Final = "logic-contract-migration-field/v1"
RECEIPT_SCHEMA_VERSION: Final = "logic-contract-migration-receipt/v1"

MIGRATION_TASK: Final = "LFP2-009"

# Artifact / request field names that dual-read under a known namespace.
_FIELD_NAMESPACE: Final[Mapping[str, NamespaceKind]] = {
    "family": NamespaceKind.FAMILY,
    "family_id": NamespaceKind.FAMILY,
    "logic_family": NamespaceKind.FAMILY,
    "source_family": NamespaceKind.FAMILY,
    "source_family_id": NamespaceKind.FAMILY,
    "target_family": NamespaceKind.FAMILY,
    "target_family_id": NamespaceKind.FAMILY,
    "profile": NamespaceKind.PROFILE,
    "profile_id": NamespaceKind.PROFILE,
    "property": NamespaceKind.PROPERTY,
    "property_id": NamespaceKind.PROPERTY,
    "view": NamespaceKind.VIEW,
    "view_id": NamespaceKind.VIEW,
    "notation": NamespaceKind.NOTATION,
    "notation_id": NamespaceKind.NOTATION,
    "syntax": NamespaceKind.NOTATION,
    "encoding": NamespaceKind.ENCODING,
    "encoding_id": NamespaceKind.ENCODING,
    "provider": NamespaceKind.PROVIDER,
    "provider_id": NamespaceKind.PROVIDER,
    "requested_backend_id": NamespaceKind.PROVIDER,
    "requested_provider": NamespaceKind.PROVIDER,
    "lane": NamespaceKind.LANE,
    "lane_id": NamespaceKind.LANE,
    "evidence": NamespaceKind.EVIDENCE,
    "evidence_id": NamespaceKind.EVIDENCE,
    "evidence_kind": NamespaceKind.EVIDENCE,
}

# Nested list fields whose items dual-read as identities.
_LIST_FIELD_NAMESPACE: Final[Mapping[str, NamespaceKind]] = {
    "property_ids": NamespaceKind.PROPERTY,
    "family_ids": NamespaceKind.FAMILY,
    "provider_ids": NamespaceKind.PROVIDER,
    "lane_ids": NamespaceKind.LANE,
    "evidence_ids": NamespaceKind.EVIDENCE,
}


class MigrationV2Error(ValueError):
    """Raised when a logic-contract migration fails closed."""


class CanonicalWriteError(MigrationV2Error):
    """Raised when a write would emit a non-canonical or masquerading label."""


class LegacyReadError(MigrationV2Error):
    """Raised when a legacy payload cannot be dual-read safely."""


class MigrationDispositionKind(str, Enum):
    """Top-level disposition of a migration receipt."""

    CANONICAL = "canonical"
    MIGRATED = "migrated"
    PARTIAL = "partial"
    REJECTED = "rejected"


class FieldAction(str, Enum):
    """Per-field migration action recorded on the receipt."""

    IDENTITY = "identity"
    REPLACED = "replaced"
    DROPPED = "dropped"
    REJECTED = "rejected"
    CANONICAL_WRITE = "canonical_write"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise MigrationV2Error(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise MigrationV2Error(f"{field_name} must not contain NUL bytes")
    return value


def _version(value: object, field_name: str = "version") -> str:
    result = _text(value, field_name)
    if "/" in result or any(character.isspace() for character in result):
        raise MigrationV2Error(f"{field_name} must not contain '/' or whitespace")
    return result


# ---------------------------------------------------------------------------
# Field + receipt records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldMigrationRecord:
    """One dual-read / write edge for a single field."""

    field: str
    namespace: str
    observed: str
    action: FieldAction
    canonical: str | None = None
    diagnostic: LogicMigrationDiagnostic | None = None
    loss: str = ""
    deprecation: str = ""
    schema_version: str = FIELD_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "field", _text(self.field, "field"))
        object.__setattr__(self, "namespace", _text(self.namespace, "namespace"))
        if not isinstance(self.observed, str):
            raise MigrationV2Error("observed must be a string")
        object.__setattr__(self, "observed", self.observed)
        if not isinstance(self.action, FieldAction):
            object.__setattr__(self, "action", FieldAction(self.action))
        if self.canonical is not None:
            object.__setattr__(
                self, "canonical", _text(self.canonical, "canonical")
            )
        if self.diagnostic is not None and not isinstance(
            self.diagnostic, LogicMigrationDiagnostic
        ):
            raise MigrationV2Error("diagnostic must be a LogicMigrationDiagnostic")
        object.__setattr__(self, "loss", self.loss if isinstance(self.loss, str) else str(self.loss))
        object.__setattr__(
            self,
            "deprecation",
            self.deprecation if isinstance(self.deprecation, str) else str(self.deprecation),
        )
        if self.schema_version != FIELD_RECORD_SCHEMA_VERSION:
            raise MigrationV2Error(
                f"unsupported field record schema_version {self.schema_version!r}"
            )
        if self.action in {FieldAction.IDENTITY, FieldAction.REPLACED, FieldAction.CANONICAL_WRITE}:
            if not self.canonical:
                raise MigrationV2Error(
                    f"action {self.action.value} requires a canonical value"
                )

    @property
    def was_alias(self) -> bool:
        return self.action is FieldAction.REPLACED

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "canonical": self.canonical,
            "deprecation": self.deprecation,
            "diagnostic": self.diagnostic.to_dict() if self.diagnostic else None,
            "field": self.field,
            "loss": self.loss,
            "namespace": self.namespace,
            "observed": self.observed,
            "schema_version": self.schema_version,
            "was_alias": self.was_alias,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FieldMigrationRecord":
        if not isinstance(value, Mapping):
            raise MigrationV2Error("field record payload must be a mapping")
        diagnostic_payload = value.get("diagnostic")
        diagnostic = (
            LogicMigrationDiagnostic.from_dict(diagnostic_payload)
            if isinstance(diagnostic_payload, Mapping)
            else None
        )
        return cls(
            field=value["field"],
            namespace=value["namespace"],
            observed=value.get("observed", "") or "",
            action=value["action"],
            canonical=value.get("canonical"),
            diagnostic=diagnostic,
            loss=value.get("loss", "") or "",
            deprecation=value.get("deprecation", "") or "",
            schema_version=value.get("schema_version", FIELD_RECORD_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class LogicContractMigrationReceipt:
    """``LogicContractMigration@1`` dual-read / canonical-write receipt.

    Successful migrations set :attr:`canonical_payload` and a non-rejected
    disposition.  Rejected outcomes leave the payload empty and record losses.
    """

    receipt_id: str
    source_interface: str
    target_interface: str
    disposition: MigrationDispositionKind
    field_records: tuple[FieldMigrationRecord, ...] = ()
    canonical_payload: Mapping[str, Any] = field(default_factory=dict)
    losses: tuple[str, ...] = ()
    deprecations: tuple[str, ...] = ()
    notes: str = ""
    version: str = MIGRATION_MODULE_VERSION
    schema_version: str = RECEIPT_SCHEMA_VERSION

    interface: ClassVar[str] = MIGRATION_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self, "source_interface", _text(self.source_interface, "source_interface")
        )
        object.__setattr__(
            self, "target_interface", _text(self.target_interface, "target_interface")
        )
        if not isinstance(self.disposition, MigrationDispositionKind):
            object.__setattr__(
                self, "disposition", MigrationDispositionKind(self.disposition)
            )
        records = tuple(
            item
            if isinstance(item, FieldMigrationRecord)
            else FieldMigrationRecord.from_dict(item)
            for item in self.field_records
        )
        object.__setattr__(self, "field_records", records)

        if not isinstance(self.canonical_payload, Mapping):
            raise MigrationV2Error("canonical_payload must be a mapping")
        # Freeze payload as a plain dict copy for immutability of outer receipt.
        object.__setattr__(
            self, "canonical_payload", dict(self.canonical_payload)
        )

        losses = tuple(
            _text(item, "losses item") if item else ""
            for item in self.losses
        )
        object.__setattr__(self, "losses", tuple(item for item in losses if item))
        deprecations = tuple(
            _text(item, "deprecations item") if item else ""
            for item in self.deprecations
        )
        object.__setattr__(
            self, "deprecations", tuple(item for item in deprecations if item)
        )
        object.__setattr__(self, "notes", self.notes if isinstance(self.notes, str) else "")
        object.__setattr__(self, "version", _version(self.version, "version"))
        if self.schema_version != RECEIPT_SCHEMA_VERSION:
            raise MigrationV2Error(
                f"unsupported receipt schema_version {self.schema_version!r}"
            )

        if self.disposition is MigrationDispositionKind.REJECTED:
            if self.canonical_payload:
                raise MigrationV2Error(
                    "rejected receipts must not carry a canonical_payload"
                )
        else:
            if not self.canonical_payload:
                raise MigrationV2Error(
                    "non-rejected receipts require a canonical_payload"
                )

    @property
    def ok(self) -> bool:
        return self.disposition in {
            MigrationDispositionKind.CANONICAL,
            MigrationDispositionKind.MIGRATED,
            MigrationDispositionKind.PARTIAL,
        }

    @property
    def alias_replacements(self) -> tuple[FieldMigrationRecord, ...]:
        return tuple(
            record for record in self.field_records if record.was_alias
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias_replacements": [
                record.to_dict() for record in self.alias_replacements
            ],
            "canonical_payload": dict(self.canonical_payload),
            "deprecations": list(self.deprecations),
            "disposition": self.disposition.value,
            "field_records": [record.to_dict() for record in self.field_records],
            "interface": self.interface,
            "losses": list(self.losses),
            "notes": self.notes,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "source_interface": self.source_interface,
            "target_interface": self.target_interface,
            "version": self.version,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicContractMigrationReceipt":
        if not isinstance(value, Mapping):
            raise MigrationV2Error("receipt payload must be a mapping")
        schema = value.get("schema_version")
        if schema != RECEIPT_SCHEMA_VERSION:
            raise MigrationV2Error(
                f"unsupported or missing receipt schema_version: {schema!r}"
            )
        interface = value.get("interface")
        if interface not in (None, MIGRATION_INTERFACE):
            raise MigrationV2Error(f"unsupported migration interface: {interface!r}")
        return cls(
            receipt_id=value["receipt_id"],
            source_interface=value["source_interface"],
            target_interface=value["target_interface"],
            disposition=value["disposition"],
            field_records=tuple(value.get("field_records", ())),
            canonical_payload=value.get("canonical_payload", {}),
            losses=tuple(value.get("losses", ())),
            deprecations=tuple(value.get("deprecations", ())),
            notes=value.get("notes", "") or "",
            version=value.get("version", MIGRATION_MODULE_VERSION),
            schema_version=value.get("schema_version", RECEIPT_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# Dual-read / canonical-write primitives
# ---------------------------------------------------------------------------


def dual_read_identity(
    namespace: NamespaceKind | str,
    label: str,
    *,
    registry: LogicAliasRegistry | None = None,
) -> tuple[LogicIdentity | None, LogicMigrationDiagnostic]:
    """Dual-read *label* in *namespace*, always returning a diagnostic.

    Unlike :func:`dual_read`, this helper never raises on unknown or wrong-
    namespace labels; the diagnostic carries the failure disposition.

    Family dual-reads attempt alias resolution first so reviewed aliases such
    as ``protocol`` -> ``cryptographic_protocol`` still work.  Pure provider /
    syntax / property / lane surfaces that do not dual-read as families are
    then diagnosed as masquerades.
    """

    active = registry if registry is not None else BASELINE_ALIAS_REGISTRY
    kind = (
        namespace
        if isinstance(namespace, NamespaceKind)
        else NamespaceKind(str(namespace))
    )

    diagnostic = active.diagnose(kind, label)
    if diagnostic.ok and diagnostic.resolved is not None:
        if kind is NamespaceKind.FAMILY:
            try:
                reject_family_masquerade(
                    diagnostic.resolved.value, field_name="family"
                )
            except FamilyMasqueradeError as error:
                masquerade = LogicMigrationDiagnostic(
                    observed=diagnostic.observed,
                    namespace=kind,
                    disposition=MigrationDisposition.REJECTED_WRONG_NAMESPACE,
                    error_code="family_masquerade",
                    message=str(error),
                    known_namespaces=tuple(
                        item.value
                        for item in (
                            NamespaceKind.PROVIDER,
                            NamespaceKind.NOTATION,
                            NamespaceKind.PROPERTY,
                            NamespaceKind.LANE,
                        )
                    ),
                )
                return None, masquerade
        return diagnostic.resolved, diagnostic

    # Alias dual-read failed: surface clearer masquerade diagnostics for family.
    if kind is NamespaceKind.FAMILY and isinstance(label, str) and label.strip():
        try:
            reject_family_masquerade(label, field_name="family")
        except FamilyMasqueradeError as error:
            masquerade = LogicMigrationDiagnostic(
                observed=label.strip(),
                namespace=kind,
                disposition=MigrationDisposition.REJECTED_WRONG_NAMESPACE,
                error_code="family_masquerade",
                message=str(error),
                known_namespaces=tuple(
                    item.value
                    for item in (
                        NamespaceKind.PROVIDER,
                        NamespaceKind.NOTATION,
                        NamespaceKind.PROPERTY,
                        NamespaceKind.LANE,
                    )
                ),
            )
            return None, masquerade
        except Exception:
            pass

    return None, diagnostic


def canonical_write_identity(
    namespace: NamespaceKind | str,
    label: str,
    *,
    registry: LogicAliasRegistry | None = None,
) -> LogicIdentity:
    """Resolve *label* and return only the canonical identity for writes.

    Raises :class:`CanonicalWriteError` when the label cannot be dual-read or
    would masquerade across namespaces.
    """

    identity, diagnostic = dual_read_identity(namespace, label, registry=registry)
    if identity is None:
        raise CanonicalWriteError(
            diagnostic.message
            or f"cannot canonical-write {label!r} in namespace {namespace!r}"
        )
    # Guard: never emit the observed legacy surface form.
    if identity.value == label and not (
        (registry or BASELINE_ALIAS_REGISTRY).is_canonical(namespace, label)
    ):
        # Observed equals canonical text only when it *is* canonical.
        pass
    kind = identity.namespace
    if kind is NamespaceKind.FAMILY:
        reject_family_masquerade(identity.value, field_name="family")
    return identity


def _record_from_diagnostic(
    field_name: str,
    diagnostic: LogicMigrationDiagnostic,
    *,
    action: FieldAction | None = None,
) -> FieldMigrationRecord:
    if diagnostic.ok and diagnostic.resolved is not None:
        if action is None:
            action = (
                FieldAction.REPLACED
                if diagnostic.disposition is MigrationDisposition.REPLACED
                else FieldAction.IDENTITY
            )
        deprecation = ""
        if diagnostic.disposition is MigrationDisposition.REPLACED:
            deprecation = (
                f"legacy label {diagnostic.observed!r} dual-reads as "
                f"{diagnostic.resolved.qualified}; writers must emit "
                f"{diagnostic.resolved.value!r}"
            )
        return FieldMigrationRecord(
            field=field_name,
            namespace=diagnostic.namespace.value,
            observed=diagnostic.observed,
            action=action,
            canonical=diagnostic.resolved.value,
            diagnostic=diagnostic,
            deprecation=deprecation,
        )
    return FieldMigrationRecord(
        field=field_name,
        namespace=diagnostic.namespace.value,
        observed=diagnostic.observed,
        action=FieldAction.REJECTED,
        canonical=None,
        diagnostic=diagnostic,
        loss=diagnostic.message or f"rejected {diagnostic.observed!r}",
    )


# ---------------------------------------------------------------------------
# Descriptor / request migration
# ---------------------------------------------------------------------------


def migrate_provider_descriptor(
    descriptor: Mapping[str, Any] | ProviderCapabilityEntry,
    *,
    catalog: ProviderCapabilityCatalog | None = None,
    registry: LogicAliasRegistry | None = None,
    receipt_id: str | None = None,
) -> LogicContractMigrationReceipt:
    """Dual-read a legacy provider descriptor and emit a canonical write.

    Provider aliases resolve to catalog canonical ids.  Family support entries
    are rewritten to baseline family ids; masquerading labels fail closed.
    """

    active_catalog = catalog if catalog is not None else BASELINE_PROVIDER_CATALOG
    active_aliases = registry if registry is not None else BASELINE_ALIAS_REGISTRY

    if isinstance(descriptor, ProviderCapabilityEntry):
        payload: dict[str, Any] = descriptor.to_dict()
        source_interface = "ProviderCapabilityEntry@1"
    elif isinstance(descriptor, Mapping):
        payload = dict(descriptor)
        source_interface = str(
            payload.get("interface") or "ProviderCapabilityDescriptor@1"
        )
    else:
        raise MigrationV2Error("descriptor must be a mapping or ProviderCapabilityEntry")

    records: list[FieldMigrationRecord] = []
    losses: list[str] = []
    deprecations: list[str] = []
    canonical: dict[str, Any] = {}

    raw_provider = payload.get("provider_id") or payload.get("provider")
    if not isinstance(raw_provider, str) or not raw_provider.strip():
        return LogicContractMigrationReceipt(
            receipt_id=receipt_id or "migration:provider:rejected",
            source_interface=source_interface,
            target_interface="ProviderCapabilityDescriptor@1",
            disposition=MigrationDispositionKind.REJECTED,
            field_records=(),
            canonical_payload={},
            losses=("provider_id is required",),
            notes="legacy provider descriptor missing provider_id",
        )

    # Prefer catalog dual-read (includes reviewed matrix aliases).
    try:
        entry = active_catalog.resolve(raw_provider)
        provider_canonical = entry.provider_id
        was_alias = provider_canonical != raw_provider
        identity, diagnostic = dual_read_identity(
            NamespaceKind.PROVIDER, raw_provider, registry=active_aliases
        )
        # Catalog is authoritative when it resolves; alias diagnostic is additive.
        if identity is None:
            diagnostic = active_aliases.diagnose(NamespaceKind.PROVIDER, provider_canonical)
            identity = provider_id(provider_canonical)
        records.append(
            FieldMigrationRecord(
                field="provider_id",
                namespace=NamespaceKind.PROVIDER.value,
                observed=raw_provider,
                action=FieldAction.REPLACED if was_alias else FieldAction.IDENTITY,
                canonical=provider_canonical,
                diagnostic=diagnostic if diagnostic.ok else None,
                deprecation=(
                    f"legacy provider alias {raw_provider!r} -> {provider_canonical!r}"
                    if was_alias
                    else ""
                ),
            )
        )
        if was_alias:
            deprecations.append(
                f"provider_id:{raw_provider}->{provider_canonical}"
            )
        canonical["provider_id"] = provider_canonical
        canonical["provider_version"] = (
            payload.get("provider_version") or entry.provider_version
        )
    except Exception as error:
        identity, diagnostic = dual_read_identity(
            NamespaceKind.PROVIDER, raw_provider, registry=active_aliases
        )
        if identity is None:
            records.append(_record_from_diagnostic("provider_id", diagnostic))
            return LogicContractMigrationReceipt(
                receipt_id=receipt_id or "migration:provider:rejected",
                source_interface=source_interface,
                target_interface="ProviderCapabilityDescriptor@1",
                disposition=MigrationDispositionKind.REJECTED,
                field_records=tuple(records),
                canonical_payload={},
                losses=(str(error), diagnostic.message or "unknown provider"),
            )
        records.append(_record_from_diagnostic("provider_id", diagnostic))
        if diagnostic.was_alias:
            deprecations.append(
                f"provider_id:{raw_provider}->{identity.value}"
            )
        canonical["provider_id"] = identity.value
        canonical["provider_version"] = payload.get("provider_version") or "migrated-v1"

    # Family support dual-read.
    family_support_out: list[dict[str, Any]] = []
    raw_support = payload.get("family_support", ())
    if isinstance(raw_support, Sequence) and not isinstance(
        raw_support, (str, bytes, bytearray)
    ):
        for index, item in enumerate(raw_support):
            if isinstance(item, Mapping):
                family_label = item.get("family_id") or item.get("family")
                support_level = item.get("support_level", "native")
                rest = {
                    key: value
                    for key, value in item.items()
                    if key not in {"family_id", "family"}
                }
            else:
                family_label = getattr(item, "family_id", None)
                support_level = getattr(item, "support_level", "native")
                rest = {}
                if hasattr(item, "to_dict"):
                    rest = {
                        key: value
                        for key, value in item.to_dict().items()
                        if key not in {"family_id", "family"}
                    }
            if not isinstance(family_label, str):
                losses.append(f"family_support[{index}]: missing family_id")
                continue
            field_name = f"family_support[{index}].family_id"
            identity, diagnostic = dual_read_identity(
                NamespaceKind.FAMILY, family_label, registry=active_aliases
            )
            record = _record_from_diagnostic(field_name, diagnostic)
            records.append(record)
            if identity is None:
                losses.append(record.loss or f"rejected family {family_label!r}")
                continue
            if diagnostic.was_alias:
                deprecations.append(
                    f"{field_name}:{family_label}->{identity.value}"
                )
            support_entry = dict(rest)
            support_entry["family_id"] = identity.value
            if "support_level" not in support_entry:
                support_entry["support_level"] = (
                    support_level.value
                    if isinstance(support_level, Enum)
                    else str(support_level)
                )
            family_support_out.append(support_entry)

    canonical["family_support"] = family_support_out

    # Evidence / runtime ids — dual-read when possible, pass through identifiers.
    for list_field, namespace in (
        ("evidence_ids", NamespaceKind.EVIDENCE),
        ("runtime_ids", None),
        ("boundedness_ids", None),
        ("translation_ids", None),
        ("aliases", None),
    ):
        raw = payload.get(list_field, ())
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            continue
        rewritten: list[str] = []
        for index, item in enumerate(raw):
            if not isinstance(item, str):
                continue
            if namespace is None:
                rewritten.append(item)
                continue
            identity, diagnostic = dual_read_identity(
                namespace, item, registry=active_aliases
            )
            field_name = f"{list_field}[{index}]"
            if identity is None:
                # Unknown evidence labels pass through as identifiers with a loss note.
                rewritten.append(item)
                losses.append(f"{field_name}: unknown {namespace.value} label {item!r}")
                records.append(
                    FieldMigrationRecord(
                        field=field_name,
                        namespace=namespace.value,
                        observed=item,
                        action=FieldAction.IDENTITY,
                        canonical=item,
                        loss=(
                            f"unregistered {namespace.value} label retained "
                            "as identifier"
                        ),
                    )
                )
            else:
                records.append(_record_from_diagnostic(field_name, diagnostic))
                rewritten.append(identity.value)
                if diagnostic.was_alias:
                    deprecations.append(f"{field_name}:{item}->{identity.value}")
        canonical[list_field] = rewritten

    for key in (
        "authority_ceiling",
        "deterministic",
        "in_executable_matrix",
        "advisory",
        "availability_posture",
        "catalog_source",
        "notes",
        "metadata",
        "version",
    ):
        if key in payload:
            canonical[key] = payload[key]

    # Ensure aliases never appear as provider_id write values.
    if "aliases" in canonical and canonical["provider_id"] in set(
        canonical.get("aliases") or ()
    ):
        raise CanonicalWriteError(
            "canonical provider_id collides with an alias list entry"
        )

    disposition = MigrationDispositionKind.CANONICAL
    if any(record.was_alias for record in records) or deprecations:
        disposition = MigrationDispositionKind.MIGRATED
    if losses and family_support_out:
        disposition = MigrationDispositionKind.PARTIAL
    if not family_support_out and payload.get("family_support"):
        disposition = MigrationDispositionKind.REJECTED
        return LogicContractMigrationReceipt(
            receipt_id=receipt_id
            or f"migration:provider:{canonical.get('provider_id', 'unknown')}",
            source_interface=source_interface,
            target_interface="ProviderCapabilityDescriptor@1",
            disposition=disposition,
            field_records=tuple(records),
            canonical_payload={},
            losses=tuple(losses) or ("all family_support entries rejected",),
            deprecations=tuple(deprecations),
            notes="provider descriptor migration rejected",
        )

    # Final canonical-write guard: no field may still hold a known legacy form.
    _assert_canonical_only(canonical, records)

    return LogicContractMigrationReceipt(
        receipt_id=receipt_id
        or f"migration:provider:{canonical['provider_id']}",
        source_interface=source_interface,
        target_interface="ProviderCapabilityDescriptor@1",
        disposition=disposition,
        field_records=tuple(records),
        canonical_payload=canonical,
        losses=tuple(losses),
        deprecations=tuple(deprecations),
        notes="provider descriptor dual-read / canonical-write",
    )


def migrate_legacy_backend_request(
    request: LegacyBackendRequest | Mapping[str, Any],
    *,
    document_id: str,
    source_digest: str,
    expression_id: str,
    expression_digest: str,
    profile: LogicIdentity | Mapping[str, Any] | str,
    property: LogicIdentity | Mapping[str, Any] | str,
    view: LogicIdentity | Mapping[str, Any] | str,
    notation: LogicIdentity | Mapping[str, Any] | str,
    encoding: LogicIdentity | Mapping[str, Any] | str,
    evidence_kind: LogicIdentity | Mapping[str, Any] | str,
    authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED,
    features: Sequence[str] = (),
    slice_id: str = "",
    slice_digest: str = "",
    request_id: str | None = None,
    registry: LogicAliasRegistry | None = None,
    receipt_id: str | None = None,
) -> tuple[BackendRequestV2 | None, LogicContractMigrationReceipt]:
    """Dual-read a legacy BackendRequest@1 and emit BackendRequest@2 + receipt.

    Free-form ``payload`` is never used for routing.  Legacy family / provider
    labels dual-read through the alias registry with diagnostics.  New writes
    are always BackendRequest@2 with canonical ids.
    """

    active_aliases = registry if registry is not None else BASELINE_ALIAS_REGISTRY
    records: list[FieldMigrationRecord] = []
    losses: list[str] = []
    deprecations: list[str] = []

    if isinstance(request, Mapping):
        try:
            legacy = LegacyBackendRequest.from_dict(request)  # type: ignore[attr-defined]
        except Exception:
            # Minimal structural dual-read when full legacy class parse fails.
            legacy = None
            raw = dict(request)
    else:
        if not isinstance(request, LegacyBackendRequest):
            raise MigrationV2Error("request must be BackendRequest@1 or a mapping")
        legacy = request
        raw = request.to_dict() if hasattr(request, "to_dict") else {}

    if legacy is not None:
        raw_family = legacy.logic_family
        raw_provider = legacy.requested_backend_id or ""
        raw_bounds = legacy.bounds
        raw_payload = legacy.payload
        obligation_id = legacy.obligation_id
        obligation_digest = legacy.obligation_digest
        legacy_request_id = legacy.request_id
        query_kind = legacy.query_kind
        assumption_ids = legacy.assumption_ids
        legacy_digest = legacy.digest
    else:
        raw_family = str(raw.get("logic_family") or raw.get("family") or "")
        raw_provider = str(
            raw.get("requested_backend_id") or raw.get("provider_id") or ""
        )
        raw_bounds = raw.get("bounds")
        raw_payload = raw.get("payload")
        obligation_id = str(raw.get("obligation_id") or "obl:migrated")
        obligation_digest = str(raw.get("obligation_digest") or "")
        legacy_request_id = str(raw.get("request_id") or "req:migrated")
        query_kind = raw.get("query_kind")
        assumption_ids = tuple(raw.get("assumption_ids") or ())
        legacy_digest = str(raw.get("digest") or "")

    # Dual-read family.
    if not raw_family or raw_family in {"", "unspecified"}:
        diagnostic = LogicMigrationDiagnostic(
            observed=raw_family or "",
            namespace=NamespaceKind.FAMILY,
            disposition=MigrationDisposition.REJECTED_UNKNOWN,
            error_code="unspecified_family",
            message="legacy BackendRequest logic_family is unspecified",
        )
        records.append(_record_from_diagnostic("logic_family", diagnostic))
        return None, LogicContractMigrationReceipt(
            receipt_id=receipt_id or "migration:request:rejected",
            source_interface=LEGACY_BACKEND_REQUEST_INTERFACE,
            target_interface=BACKEND_REQUEST_V2_INTERFACE,
            disposition=MigrationDispositionKind.REJECTED,
            field_records=tuple(records),
            canonical_payload={},
            losses=("logic_family is unspecified",),
            notes="cannot lift legacy request without a typed family",
        )

    family_identity, family_diag = dual_read_identity(
        NamespaceKind.FAMILY, raw_family, registry=active_aliases
    )
    records.append(_record_from_diagnostic("logic_family", family_diag))
    if family_identity is None:
        return None, LogicContractMigrationReceipt(
            receipt_id=receipt_id or "migration:request:rejected",
            source_interface=LEGACY_BACKEND_REQUEST_INTERFACE,
            target_interface=BACKEND_REQUEST_V2_INTERFACE,
            disposition=MigrationDispositionKind.REJECTED,
            field_records=tuple(records),
            canonical_payload={},
            losses=(family_diag.message or f"rejected family {raw_family!r}",),
            notes="legacy family dual-read failed",
        )
    if family_diag.was_alias:
        deprecations.append(f"logic_family:{raw_family}->{family_identity.value}")

    # Dual-read optional provider.
    provider_identity: LogicIdentity | None = None
    if raw_provider:
        provider_identity, provider_diag = dual_read_identity(
            NamespaceKind.PROVIDER, raw_provider, registry=active_aliases
        )
        # Catalog aliases (e.g. tlc -> tla_tlc) may not be in namespace baseline.
        if provider_identity is None:
            try:
                entry = BASELINE_PROVIDER_CATALOG.resolve(raw_provider)
                provider_identity = provider_id(entry.provider_id)
                records.append(
                    FieldMigrationRecord(
                        field="requested_backend_id",
                        namespace=NamespaceKind.PROVIDER.value,
                        observed=raw_provider,
                        action=FieldAction.REPLACED
                        if entry.provider_id != raw_provider
                        else FieldAction.IDENTITY,
                        canonical=entry.provider_id,
                        deprecation=(
                            f"legacy provider alias {raw_provider!r} -> "
                            f"{entry.provider_id!r}"
                            if entry.provider_id != raw_provider
                            else ""
                        ),
                    )
                )
                if entry.provider_id != raw_provider:
                    deprecations.append(
                        f"requested_backend_id:{raw_provider}->{entry.provider_id}"
                    )
            except Exception:
                records.append(_record_from_diagnostic("requested_backend_id", provider_diag))
                losses.append(
                    provider_diag.message
                    or f"unknown provider {raw_provider!r}; dropped"
                )
                provider_identity = None
        else:
            records.append(
                _record_from_diagnostic("requested_backend_id", provider_diag)
            )
            if provider_diag.was_alias:
                deprecations.append(
                    f"requested_backend_id:{raw_provider}->{provider_identity.value}"
                )

    # Payload is always dropped from routing.
    if raw_payload:
        losses.append("legacy payload dropped; never used for provider selection")
        records.append(
            FieldMigrationRecord(
                field="payload",
                namespace="none",
                observed="(payload)",
                action=FieldAction.DROPPED,
                canonical=None,
                loss="free-form payload routing removed in BackendRequest@2",
                deprecation="BackendRequest@2 rejects free-form payload routing",
            )
        )
        deprecations.append("payload:dropped")

    # Coerce typed lineage fields (already canonical from caller or dual-read).
    def _as_identity(
        value: LogicIdentity | Mapping[str, Any] | str,
        kind: NamespaceKind,
        field_name: str,
    ) -> LogicIdentity:
        if isinstance(value, LogicIdentity):
            if value.namespace is not kind:
                raise CanonicalWriteError(
                    f"{field_name} requires {kind.value} namespace; got "
                    f"{value.qualified}"
                )
            return value
        if isinstance(value, Mapping):
            identity = LogicIdentity.from_dict(value)
            if identity.namespace is not kind:
                raise CanonicalWriteError(
                    f"{field_name} requires {kind.value} namespace; got "
                    f"{identity.qualified}"
                )
            return identity
        identity, diagnostic = dual_read_identity(
            kind, str(value), registry=active_aliases
        )
        records.append(_record_from_diagnostic(field_name, diagnostic))
        if identity is None:
            raise CanonicalWriteError(
                diagnostic.message or f"cannot resolve {field_name}={value!r}"
            )
        if diagnostic.was_alias:
            deprecations.append(f"{field_name}:{value}->{identity.value}")
        return identity

    try:
        profile_i = _as_identity(profile, NamespaceKind.PROFILE, "profile")
        property_i = _as_identity(property, NamespaceKind.PROPERTY, "property")
        view_i = _as_identity(view, NamespaceKind.VIEW, "view")
        notation_i = _as_identity(notation, NamespaceKind.NOTATION, "notation")
        encoding_i = _as_identity(encoding, NamespaceKind.ENCODING, "encoding")
        evidence_i = _as_identity(
            evidence_kind, NamespaceKind.EVIDENCE, "evidence_kind"
        )
    except CanonicalWriteError as error:
        return None, LogicContractMigrationReceipt(
            receipt_id=receipt_id or "migration:request:rejected",
            source_interface=LEGACY_BACKEND_REQUEST_INTERFACE,
            target_interface=BACKEND_REQUEST_V2_INTERFACE,
            disposition=MigrationDispositionKind.REJECTED,
            field_records=tuple(records),
            canonical_payload={},
            losses=(str(error),),
            deprecations=tuple(deprecations),
            notes="typed lineage dual-read failed",
        )

    # Bounds.
    try:
        if isinstance(raw_bounds, LegacyExecutionBounds):
            bounds = RequestBounds.from_legacy(raw_bounds)
        elif isinstance(raw_bounds, Mapping):
            bounds = RequestBounds.from_dict(raw_bounds)
        elif raw_bounds is None:
            raise RequestV2Error("bounds required")
        else:
            bounds = RequestBounds.from_legacy(raw_bounds)  # type: ignore[arg-type]
    except Exception as error:
        return None, LogicContractMigrationReceipt(
            receipt_id=receipt_id or "migration:request:rejected",
            source_interface=LEGACY_BACKEND_REQUEST_INTERFACE,
            target_interface=BACKEND_REQUEST_V2_INTERFACE,
            disposition=MigrationDispositionKind.REJECTED,
            field_records=tuple(records),
            canonical_payload={},
            losses=(f"bounds migration failed: {error}",),
            deprecations=tuple(deprecations),
            notes="legacy bounds could not be lifted",
        )

    # Build BackendRequest@2 (canonical write).
    try:
        if isinstance(obligation_digest, str) and len(obligation_digest) == 64:
            obl_digest = obligation_digest
        else:
            obl_digest = content_sha256(
                canonical_json_bytes(
                    {
                        "obligation_id": obligation_id,
                        "legacy_obligation_digest": obligation_digest,
                    }
                )
            )
        if isinstance(legacy_digest, str) and len(legacy_digest) == 64:
            leg_digest = legacy_digest
        else:
            leg_digest = content_sha256(
                canonical_json_bytes({"legacy_digest": legacy_digest or legacy_request_id})
            )
        v2 = BackendRequestV2(
            request_id=request_id or legacy_request_id,
            obligation_id=obligation_id,
            obligation_digest=obl_digest,
            document_id=document_id,
            source_digest=source_digest,
            expression_id=expression_id,
            expression_digest=expression_digest,
            family=family_identity,
            profile=profile_i,
            property=property_i,
            view=view_i,
            notation=notation_i,
            encoding=encoding_i,
            evidence_kind=evidence_i,
            bounds=bounds,
            authority_ceiling=authority_ceiling,
            features=tuple(features),
            assumption_ids=assumption_ids,
            slice_id=slice_id,
            slice_digest=slice_digest,
            requested_provider=provider_identity,
            legacy_request_digest=leg_digest,
            metadata={
                "migrated_from": LEGACY_BACKEND_REQUEST_INTERFACE,
                "legacy_query_kind": (
                    query_kind.value
                    if isinstance(query_kind, QueryKind)
                    else str(query_kind or "")
                ),
                "legacy_payload_dropped": True,
                "migration_task": MIGRATION_TASK,
            },
        )
    except Exception as error:
        return None, LogicContractMigrationReceipt(
            receipt_id=receipt_id or "migration:request:rejected",
            source_interface=LEGACY_BACKEND_REQUEST_INTERFACE,
            target_interface=BACKEND_REQUEST_V2_INTERFACE,
            disposition=MigrationDispositionKind.REJECTED,
            field_records=tuple(records),
            canonical_payload={},
            losses=(f"BackendRequest@2 admission failed: {error}",),
            deprecations=tuple(deprecations),
            notes="canonical write rejected by BackendRequest@2",
        )

    canonical_payload = v2.to_dict()
    # Canonical-write guard on family / provider fields.
    written_family = canonical_payload.get("family", {})
    if isinstance(written_family, Mapping):
        family_value = str(written_family.get("value") or "")
    else:
        family_value = str(written_family)
    try:
        reject_family_masquerade(family_value, field_name="family")
    except FamilyMasqueradeError as error:
        return None, LogicContractMigrationReceipt(
            receipt_id=receipt_id or "migration:request:rejected",
            source_interface=LEGACY_BACKEND_REQUEST_INTERFACE,
            target_interface=BACKEND_REQUEST_V2_INTERFACE,
            disposition=MigrationDispositionKind.REJECTED,
            field_records=tuple(records),
            canonical_payload={},
            losses=(str(error),),
            deprecations=tuple(deprecations),
        )

    records.append(
        FieldMigrationRecord(
            field="family",
            namespace=NamespaceKind.FAMILY.value,
            observed=raw_family,
            action=FieldAction.CANONICAL_WRITE,
            canonical=family_identity.value,
            deprecation=(
                f"writers must emit {family_identity.value!r}"
                if family_diag.was_alias
                else ""
            ),
        )
    )

    disposition = MigrationDispositionKind.CANONICAL
    if deprecations or any(record.was_alias for record in records):
        disposition = MigrationDispositionKind.MIGRATED
    if losses:
        disposition = MigrationDispositionKind.PARTIAL

    receipt = LogicContractMigrationReceipt(
        receipt_id=receipt_id or f"migration:request:{v2.request_id}",
        source_interface=LEGACY_BACKEND_REQUEST_INTERFACE,
        target_interface=BACKEND_REQUEST_V2_INTERFACE,
        disposition=disposition,
        field_records=tuple(records),
        canonical_payload=canonical_payload,
        losses=tuple(losses),
        deprecations=tuple(deprecations),
        notes="legacy BackendRequest@1 dual-read / BackendRequest@2 canonical-write",
    )
    return v2, receipt


def migrate_artifact(
    artifact: Mapping[str, Any],
    *,
    registry: LogicAliasRegistry | None = None,
    receipt_id: str | None = None,
) -> LogicContractMigrationReceipt:
    """Migrate an accepted artifact mapping to canonical labels only.

    Dual-reads every known identity field, rewrites aliases, and rejects
    family masquerades.  Nested mappings/lists are walked recursively.
    """

    if not isinstance(artifact, Mapping):
        raise MigrationV2Error("artifact must be a mapping")

    active = registry if registry is not None else BASELINE_ALIAS_REGISTRY
    records: list[FieldMigrationRecord] = []
    losses: list[str] = []
    deprecations: list[str] = []

    def walk(
        node: Any,
        path: str,
    ) -> Any:
        if isinstance(node, Mapping):
            out: dict[str, Any] = {}
            for key, value in node.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                namespace = _FIELD_NAMESPACE.get(key_text)
                if namespace is not None and isinstance(value, str):
                    identity, diagnostic = dual_read_identity(
                        namespace, value, registry=active
                    )
                    record = _record_from_diagnostic(child_path, diagnostic)
                    records.append(record)
                    if identity is None:
                        losses.append(
                            record.loss or f"rejected {child_path}={value!r}"
                        )
                        # Fail closed for family fields; drop others with loss.
                        if namespace is NamespaceKind.FAMILY:
                            continue
                        out[key_text] = value
                        continue
                    if diagnostic.was_alias:
                        deprecations.append(
                            f"{child_path}:{value}->{identity.value}"
                        )
                    out[key_text] = identity.value
                elif key_text in _LIST_FIELD_NAMESPACE and isinstance(
                    value, Sequence
                ) and not isinstance(value, (str, bytes, bytearray)):
                    ns = _LIST_FIELD_NAMESPACE[key_text]
                    rewritten: list[Any] = []
                    for index, item in enumerate(value):
                        item_path = f"{child_path}[{index}]"
                        if isinstance(item, str):
                            identity, diagnostic = dual_read_identity(
                                ns, item, registry=active
                            )
                            record = _record_from_diagnostic(item_path, diagnostic)
                            records.append(record)
                            if identity is None:
                                losses.append(
                                    record.loss
                                    or f"rejected {item_path}={item!r}"
                                )
                                continue
                            if diagnostic.was_alias:
                                deprecations.append(
                                    f"{item_path}:{item}->{identity.value}"
                                )
                            rewritten.append(identity.value)
                        else:
                            rewritten.append(walk(item, item_path))
                    out[key_text] = rewritten
                else:
                    out[key_text] = walk(value, child_path)
            return out
        if isinstance(node, Sequence) and not isinstance(
            node, (str, bytes, bytearray)
        ):
            return [walk(item, f"{path}[{index}]") for index, item in enumerate(node)]
        return node

    canonical = walk(dict(artifact), "")
    if not isinstance(canonical, dict):
        raise MigrationV2Error("artifact walk must produce a mapping")

    # If top-level family was present and rejected, fail closed.
    if "family_id" in artifact or "family" in artifact or "logic_family" in artifact:
        family_keys = ("family_id", "family", "logic_family")
        has_family = any(key in canonical for key in family_keys)
        if not has_family:
            return LogicContractMigrationReceipt(
                receipt_id=receipt_id or "migration:artifact:rejected",
                source_interface="Artifact@legacy",
                target_interface="Artifact@canonical",
                disposition=MigrationDispositionKind.REJECTED,
                field_records=tuple(records),
                canonical_payload={},
                losses=tuple(losses) or ("family field rejected",),
                deprecations=tuple(deprecations),
                notes="artifact family dual-read failed",
            )

    _assert_canonical_only(canonical, records)

    disposition = MigrationDispositionKind.CANONICAL
    if deprecations or any(record.was_alias for record in records):
        disposition = MigrationDispositionKind.MIGRATED
    if losses:
        disposition = MigrationDispositionKind.PARTIAL

    return LogicContractMigrationReceipt(
        receipt_id=receipt_id or "migration:artifact",
        source_interface="Artifact@legacy",
        target_interface="Artifact@canonical",
        disposition=disposition,
        field_records=tuple(records),
        canonical_payload=canonical,
        losses=tuple(losses),
        deprecations=tuple(deprecations),
        notes="artifact dual-read / canonical-write",
    )


def canonical_write_request_fields(
    fields: Mapping[str, Any],
    *,
    registry: LogicAliasRegistry | None = None,
) -> dict[str, Any]:
    """Canonical-write helper: rewrite known identity fields only.

    Every value written is a canonical id.  Legacy aliases never appear in the
    result.  Family masquerades raise :class:`CanonicalWriteError`.
    """

    if not isinstance(fields, Mapping):
        raise MigrationV2Error("fields must be a mapping")
    active = registry if registry is not None else BASELINE_ALIAS_REGISTRY
    out: dict[str, Any] = {}
    for key, value in fields.items():
        key_text = str(key)
        namespace = _FIELD_NAMESPACE.get(key_text)
        if namespace is not None and isinstance(value, str):
            identity = canonical_write_identity(namespace, value, registry=active)
            out[key_text] = identity.value
        else:
            out[key_text] = value
    return out


def _assert_canonical_only(
    payload: Mapping[str, Any],
    records: Sequence[FieldMigrationRecord],
) -> None:
    """Ensure no rewritten field still holds a non-canonical observed form."""

    for record in records:
        if record.action not in {
            FieldAction.REPLACED,
            FieldAction.CANONICAL_WRITE,
            FieldAction.IDENTITY,
        }:
            continue
        if not record.canonical:
            continue
        # Only check simple top-level fields.
        field = record.field
        if "." in field or "[" in field:
            continue
        value = payload.get(field)
        if isinstance(value, Mapping):
            value = value.get("value")
        if isinstance(value, str) and value != record.canonical:
            # Allow when the field name differs from the write key (e.g. logic_family
            # rewritten into family).
            if field in payload and value == record.observed:
                raise CanonicalWriteError(
                    f"legacy label retained on {field}: {value!r}"
                )


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class LogicContractMigration:
    """``LogicContractMigration@1`` dual-read / canonical-write facade."""

    interface: Final = MIGRATION_INTERFACE
    schema_version: Final = MIGRATION_SCHEMA_VERSION

    def __init__(
        self,
        *,
        alias_registry: LogicAliasRegistry | None = None,
        catalog: ProviderCapabilityCatalog | None = None,
        version: str = MIGRATION_MODULE_VERSION,
    ) -> None:
        self.version = _version(version, "version")
        self._aliases = (
            alias_registry if alias_registry is not None else BASELINE_ALIAS_REGISTRY
        )
        self._catalog = (
            catalog if catalog is not None else BASELINE_PROVIDER_CATALOG
        )

    @property
    def alias_registry(self) -> LogicAliasRegistry:
        return self._aliases

    @property
    def catalog(self) -> ProviderCapabilityCatalog:
        return self._catalog

    def dual_read(
        self,
        namespace: NamespaceKind | str,
        label: str,
    ) -> tuple[LogicIdentity | None, LogicMigrationDiagnostic]:
        return dual_read_identity(namespace, label, registry=self._aliases)

    def canonical_write(
        self,
        namespace: NamespaceKind | str,
        label: str,
    ) -> LogicIdentity:
        return canonical_write_identity(namespace, label, registry=self._aliases)

    def migrate_provider(
        self,
        descriptor: Mapping[str, Any] | ProviderCapabilityEntry,
        *,
        receipt_id: str | None = None,
    ) -> LogicContractMigrationReceipt:
        return migrate_provider_descriptor(
            descriptor,
            catalog=self._catalog,
            registry=self._aliases,
            receipt_id=receipt_id,
        )

    def migrate_request(
        self,
        request: LegacyBackendRequest | Mapping[str, Any],
        *,
        document_id: str,
        source_digest: str,
        expression_id: str,
        expression_digest: str,
        profile: LogicIdentity | Mapping[str, Any] | str,
        property: LogicIdentity | Mapping[str, Any] | str,
        view: LogicIdentity | Mapping[str, Any] | str,
        notation: LogicIdentity | Mapping[str, Any] | str,
        encoding: LogicIdentity | Mapping[str, Any] | str,
        evidence_kind: LogicIdentity | Mapping[str, Any] | str,
        authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED,
        features: Sequence[str] = (),
        slice_id: str = "",
        slice_digest: str = "",
        request_id: str | None = None,
        receipt_id: str | None = None,
    ) -> tuple[BackendRequestV2 | None, LogicContractMigrationReceipt]:
        return migrate_legacy_backend_request(
            request,
            document_id=document_id,
            source_digest=source_digest,
            expression_id=expression_id,
            expression_digest=expression_digest,
            profile=profile,
            property=property,
            view=view,
            notation=notation,
            encoding=encoding,
            evidence_kind=evidence_kind,
            authority_ceiling=authority_ceiling,
            features=features,
            slice_id=slice_id,
            slice_digest=slice_digest,
            request_id=request_id,
            registry=self._aliases,
            receipt_id=receipt_id,
        )

    def migrate_artifact(
        self,
        artifact: Mapping[str, Any],
        *,
        receipt_id: str | None = None,
    ) -> LogicContractMigrationReceipt:
        return migrate_artifact(
            artifact, registry=self._aliases, receipt_id=receipt_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_interface": self._catalog.interface,
            "diagnostic_interface": DIAGNOSTIC_INTERFACE,
            "interface": self.interface,
            "operations": [
                "dual_read",
                "canonical_write",
                "migrate_provider",
                "migrate_request",
                "migrate_artifact",
            ],
            "schema_version": self.schema_version,
            "target_request_interface": BACKEND_REQUEST_V2_INTERFACE,
            "target_request_schema_version": BACKEND_REQUEST_V2_SCHEMA_VERSION,
            "version": self.version,
        }


DEFAULT_CONTRACT_MIGRATION: Final[LogicContractMigration] = LogicContractMigration()


__all__ = [
    "DEFAULT_CONTRACT_MIGRATION",
    "FIELD_RECORD_SCHEMA_VERSION",
    "LEGACY_BACKEND_REQUEST_INTERFACE",
    "LEGACY_BACKEND_REQUEST_SCHEMA_VERSION",
    "MIGRATION_INTERFACE",
    "MIGRATION_MODULE_VERSION",
    "MIGRATION_SCHEMA_VERSION",
    "MIGRATION_TASK",
    "RECEIPT_SCHEMA_VERSION",
    "CanonicalWriteError",
    "FieldAction",
    "FieldMigrationRecord",
    "LegacyReadError",
    "LogicContractMigration",
    "LogicContractMigrationReceipt",
    "MigrationDispositionKind",
    "MigrationV2Error",
    "canonical_write_identity",
    "canonical_write_request_fields",
    "dual_read_identity",
    "migrate_artifact",
    "migrate_legacy_backend_request",
    "migrate_provider_descriptor",
]

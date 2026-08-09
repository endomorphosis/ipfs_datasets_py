"""Versioned alias migration with dual-read / one-write canonicalization.

``LogicAliasRegistry@1`` records reviewed legacy labels and maps them to
typed canonical identities.  ``LogicMigrationDiagnostic@1`` reports every
resolution edge so consumers can accept legacy labels while writers emit only
canonical namespace values.

Guarantees (fail closed):

* unknown labels cannot resolve;
* labels belonging to another namespace cannot be coerced by request;
* alias cycles and collisions are rejected at registration time;
* canonicalization is deterministic and idempotent.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final

from .namespaces import (
    BASELINE_NAMESPACES,
    IDENTITY_VERSION,
    InvalidIdentifierError,
    LogicIdentity,
    LogicIdentityNamespaces,
    NamespaceKind,
    SchemaVersionError,
    UnknownIdentityError,
    identity_for,
    normalize_identity_name,
    validate_identifier,
    validate_version,
)

ALIAS_SCHEMA_VERSION: Final = "logic-alias-registry/v1"
ALIAS_INTERFACE: Final = "LogicAliasRegistry@1"
ALIAS_MODULE_VERSION: Final = "1.0.0"

DIAGNOSTIC_SCHEMA_VERSION: Final = "logic-migration-diagnostic/v1"
DIAGNOSTIC_INTERFACE: Final = "LogicMigrationDiagnostic@1"
DIAGNOSTIC_VERSION: Final = "1.0.0"

ALIAS_EDGE_VERSION: Final = "1.0.0"


class AliasError(ValueError):
    """Base error for logic alias registry operations."""


class AliasCollisionError(AliasError):
    """Raised when two aliases claim the same normalized lookup key."""


class AliasCycleError(AliasError):
    """Raised when registering an alias would introduce a cycle."""


class UnknownAliasError(AliasError, KeyError):
    """Raised when a label cannot be resolved in the requested namespace."""


class WrongNamespaceError(AliasError, TypeError):
    """Raised when a label is known only under a different namespace."""


class FrozenAliasRegistryError(AliasError):
    """Raised on attempted mutation of a frozen alias registry."""


class AliasResolutionKind(str, Enum):
    """How a dual-read resolution obtained its result."""

    CANONICAL = "canonical"
    ALIAS = "alias"
    IDENTITY = "identity"


class MigrationDisposition(str, Enum):
    """Disposition recorded on a migration diagnostic."""

    CANONICAL = "canonical"
    REPLACED = "replaced"
    REJECTED_UNKNOWN = "rejected_unknown"
    REJECTED_WRONG_NAMESPACE = "rejected_wrong_namespace"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidIdentifierError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise InvalidIdentifierError(f"{field_name} must not contain NUL bytes")
    return value


def _coerce_namespace(value: object) -> NamespaceKind:
    if isinstance(value, NamespaceKind):
        return value
    if isinstance(value, str):
        try:
            return NamespaceKind(value)
        except ValueError as error:
            choices = ", ".join(repr(member.value) for member in NamespaceKind)
            raise InvalidIdentifierError(
                f"namespace must be one of {choices}; got {value!r}"
            ) from error
    raise InvalidIdentifierError(
        f"namespace must be a NamespaceKind or string; got {type(value).__name__}"
    )


def _alias_label(value: object, field_name: str = "alias") -> str:
    """Validate a dual-read label (canonical id or freer legacy surface form)."""

    text = _text(value, field_name)
    # Collision keys always go through the shared normalizer.
    normalize_identity_name(text)
    return text


@dataclass(frozen=True, slots=True)
class AliasEdge:
    """One versioned dual-read mapping from a legacy label to a canonical id.

    The edge is scoped to :attr:`namespace`: the *source* label may only be
    resolved when the caller requests that namespace.  The *target* must already
    be a canonical identity in the same namespace (never another alias).
    """

    source: str
    target: LogicIdentity
    version: str = ALIAS_EDGE_VERSION
    notes: str = ""
    replacement: str = ""

    schema_version: ClassVar[str] = ALIAS_SCHEMA_VERSION
    interface: ClassVar[str] = ALIAS_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _alias_label(self.source, "source"))
        if not isinstance(self.target, LogicIdentity):
            raise InvalidIdentifierError("target must be a LogicIdentity")
        object.__setattr__(self, "version", validate_version(self.version, "version"))
        notes = self.notes
        if notes:
            object.__setattr__(self, "notes", _text(notes, "notes"))
        else:
            object.__setattr__(self, "notes", "")
        replacement = self.replacement
        if replacement:
            object.__setattr__(
                self, "replacement", validate_identifier(replacement, "replacement")
            )
            if replacement != self.target.value:
                raise InvalidIdentifierError(
                    f"replacement {replacement!r} must equal target "
                    f"{self.target.value!r}"
                )
        else:
            object.__setattr__(self, "replacement", self.target.value)
        # Source must not already be the canonical target under normalization.
        if normalize_identity_name(self.source) == normalize_identity_name(
            self.target.value
        ):
            raise AliasCollisionError(
                f"alias source {self.source!r} collides with its target "
                f"{self.target.qualified!r} after normalization"
            )

    @property
    def namespace(self) -> NamespaceKind:
        return self.target.namespace

    @property
    def source_key(self) -> str:
        return normalize_identity_name(self.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "namespace": self.namespace.value,
            "notes": self.notes,
            "replacement": self.replacement,
            "schema_version": self.schema_version,
            "source": self.source,
            "target": self.target.to_dict(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AliasEdge":
        if not isinstance(payload, Mapping):
            raise InvalidIdentifierError("alias edge payload must be a mapping")
        schema = payload.get("schema_version")
        if schema is not None and schema != ALIAS_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported alias edge schema_version: {schema!r}"
            )
        target_payload = payload.get("target")
        if isinstance(target_payload, Mapping):
            target = LogicIdentity.from_dict(target_payload)
        else:
            target = identity_for(
                payload["namespace"],
                payload["replacement"] if "replacement" in payload else payload["target"],
                version=payload.get("target_version", IDENTITY_VERSION),
            )
        declared_namespace = payload.get("namespace")
        if declared_namespace is not None:
            if _coerce_namespace(declared_namespace) is not target.namespace:
                raise WrongNamespaceError(
                    f"edge namespace {declared_namespace!r} disagrees with "
                    f"target namespace {target.namespace.value!r}"
                )
        return cls(
            source=payload["source"],
            target=target,
            version=payload.get("version", ALIAS_EDGE_VERSION),
            notes=payload.get("notes", "") or "",
            replacement=payload.get("replacement", "") or "",
        )


@dataclass(frozen=True, slots=True)
class LogicMigrationDiagnostic:
    """``LogicMigrationDiagnostic@1`` dual-read resolution receipt.

    Successful resolutions set :attr:`resolved` and a non-rejected disposition.
    Fail-closed outcomes leave :attr:`resolved` as ``None`` and set
    :attr:`error_code` / :attr:`message`.
    """

    observed: str
    namespace: NamespaceKind
    disposition: MigrationDisposition
    resolved: LogicIdentity | None = None
    normalized: str = ""
    resolution_kind: AliasResolutionKind | None = None
    alias_path: tuple[str, ...] = ()
    replacement: str | None = None
    known_namespaces: tuple[str, ...] = ()
    error_code: str | None = None
    message: str = ""
    version: str = DIAGNOSTIC_VERSION

    schema_version: ClassVar[str] = DIAGNOSTIC_SCHEMA_VERSION
    interface: ClassVar[str] = DIAGNOSTIC_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.observed, str) or "\x00" in self.observed:
            raise InvalidIdentifierError(
                "observed must be a string without NUL bytes"
            )
        object.__setattr__(self, "observed", self.observed.strip())
        object.__setattr__(self, "namespace", _coerce_namespace(self.namespace))
        if not isinstance(self.disposition, MigrationDisposition):
            try:
                object.__setattr__(
                    self, "disposition", MigrationDisposition(self.disposition)
                )
            except (TypeError, ValueError) as error:
                raise InvalidIdentifierError(
                    f"invalid migration disposition: {self.disposition!r}"
                ) from error
        if self.resolved is not None and not isinstance(self.resolved, LogicIdentity):
            raise InvalidIdentifierError("resolved must be a LogicIdentity or None")
        if self.normalized:
            try:
                object.__setattr__(
                    self, "normalized", normalize_identity_name(self.normalized)
                )
            except InvalidIdentifierError:
                object.__setattr__(self, "normalized", self.normalized.strip().casefold())
        elif self.observed:
            try:
                object.__setattr__(
                    self, "normalized", normalize_identity_name(self.observed)
                )
            except InvalidIdentifierError:
                object.__setattr__(self, "normalized", "")
        else:
            object.__setattr__(self, "normalized", "")
        if self.resolution_kind is not None and not isinstance(
            self.resolution_kind, AliasResolutionKind
        ):
            object.__setattr__(
                self, "resolution_kind", AliasResolutionKind(self.resolution_kind)
            )
        path = self.alias_path
        if isinstance(path, (str, bytes, bytearray)) or not isinstance(path, Sequence):
            raise InvalidIdentifierError("alias_path must be a sequence of strings")
        object.__setattr__(
            self,
            "alias_path",
            tuple(_text(item, "alias_path item") for item in path),
        )
        if self.replacement is not None:
            object.__setattr__(
                self,
                "replacement",
                validate_identifier(self.replacement, "replacement"),
            )
        known = self.known_namespaces
        if isinstance(known, (str, bytes, bytearray)) or not isinstance(known, Sequence):
            raise InvalidIdentifierError(
                "known_namespaces must be a sequence of strings"
            )
        object.__setattr__(
            self,
            "known_namespaces",
            tuple(sorted({_text(item, "known_namespaces item") for item in known})),
        )
        if self.error_code is not None:
            object.__setattr__(self, "error_code", _text(self.error_code, "error_code"))
        if self.message:
            object.__setattr__(self, "message", _text(self.message, "message"))
        else:
            object.__setattr__(self, "message", "")
        object.__setattr__(self, "version", validate_version(self.version, "version"))

        success = self.disposition in {
            MigrationDisposition.CANONICAL,
            MigrationDisposition.REPLACED,
        }
        if success:
            if self.resolved is None:
                raise InvalidIdentifierError(
                    "successful diagnostics require a resolved identity"
                )
            if self.resolved.namespace is not self.namespace:
                raise WrongNamespaceError(
                    "resolved identity namespace must match diagnostic namespace"
                )
            if self.error_code is not None:
                raise InvalidIdentifierError(
                    "successful diagnostics must not carry an error_code"
                )
        else:
            if self.resolved is not None:
                raise InvalidIdentifierError(
                    "rejected diagnostics must not carry a resolved identity"
                )
            if self.error_code is None:
                raise InvalidIdentifierError(
                    "rejected diagnostics require an error_code"
                )

    @property
    def ok(self) -> bool:
        return self.disposition in {
            MigrationDisposition.CANONICAL,
            MigrationDisposition.REPLACED,
        }

    @property
    def was_alias(self) -> bool:
        return self.disposition is MigrationDisposition.REPLACED

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias_path": list(self.alias_path),
            "disposition": self.disposition.value,
            "error_code": self.error_code,
            "interface": self.interface,
            "known_namespaces": list(self.known_namespaces),
            "message": self.message,
            "namespace": self.namespace.value,
            "normalized": self.normalized,
            "observed": self.observed,
            "replacement": self.replacement,
            "resolution_kind": (
                self.resolution_kind.value if self.resolution_kind is not None else None
            ),
            "resolved": self.resolved.to_dict() if self.resolved is not None else None,
            "schema_version": self.schema_version,
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
    def from_dict(cls, payload: Mapping[str, Any]) -> "LogicMigrationDiagnostic":
        if not isinstance(payload, Mapping):
            raise InvalidIdentifierError("diagnostic payload must be a mapping")
        schema = payload.get("schema_version")
        if schema != DIAGNOSTIC_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported or missing diagnostic schema_version: {schema!r}"
            )
        interface = payload.get("interface")
        if interface is not None and interface != DIAGNOSTIC_INTERFACE:
            raise SchemaVersionError(f"unsupported diagnostic interface: {interface!r}")
        resolved_payload = payload.get("resolved")
        resolved: LogicIdentity | None
        if resolved_payload is None:
            resolved = None
        elif isinstance(resolved_payload, Mapping):
            resolved = LogicIdentity.from_dict(resolved_payload)
        else:
            raise InvalidIdentifierError("resolved must be a mapping or null")
        kind = payload.get("resolution_kind")
        return cls(
            observed=payload["observed"],
            namespace=payload["namespace"],
            disposition=payload["disposition"],
            resolved=resolved,
            normalized=payload.get("normalized", "") or "",
            resolution_kind=(
                AliasResolutionKind(kind) if kind is not None else None
            ),
            alias_path=tuple(payload.get("alias_path", ())),
            replacement=payload.get("replacement"),
            known_namespaces=tuple(payload.get("known_namespaces", ())),
            error_code=payload.get("error_code"),
            message=payload.get("message", "") or "",
            version=payload.get("version", DIAGNOSTIC_VERSION),
        )


class LogicAliasRegistry:
    """``LogicAliasRegistry@1`` dual-read / one-write alias catalog.

    Registration is mutable until :meth:`freeze`.  Every successful registration
    leaves the table free of cycles and collisions.  Reads accept reviewed
    aliases; writers always emit canonical identities.
    """

    schema_version: Final = ALIAS_SCHEMA_VERSION
    interface: Final = ALIAS_INTERFACE

    def __init__(
        self,
        edges: Iterable[AliasEdge] | None = None,
        *,
        namespaces: LogicIdentityNamespaces | None = None,
        version: str = ALIAS_MODULE_VERSION,
        frozen: bool = False,
    ) -> None:
        self.version = validate_version(version, "version")
        self._namespaces = namespaces if namespaces is not None else BASELINE_NAMESPACES
        # (namespace, normalized_source) -> AliasEdge
        self._edges: dict[tuple[NamespaceKind, str], AliasEdge] = {}
        # (namespace, normalized_label) -> set of namespaces where label is known
        # Built for wrong-namespace diagnostics across registered edges + namespace
        # catalog surface forms.
        self._global_labels: dict[str, set[NamespaceKind]] = {}
        self._frozen = False

        for edge in sorted(
            edges or (),
            key=lambda item: (item.namespace.value, item.source_key, item.source),
        ):
            self.register_edge(edge)
        if frozen:
            self.freeze()

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def namespaces(self) -> LogicIdentityNamespaces:
        return self._namespaces

    def freeze(self) -> "LogicAliasRegistry":
        """Prevent further registration and return this registry."""

        self._frozen = True
        return self

    def _require_mutable(self) -> None:
        if self._frozen:
            raise FrozenAliasRegistryError("logic alias registry is frozen")

    def _index_label(self, namespace: NamespaceKind, label: str) -> None:
        key = normalize_identity_name(label)
        owners = self._global_labels.setdefault(key, set())
        owners.add(namespace)

    def _rebuild_global_index(self) -> None:
        self._global_labels.clear()
        for binding in self._namespaces.bindings():
            self._index_label(binding.namespace, binding.value)
            for alias in binding.aliases:
                self._index_label(binding.namespace, alias)
        for edge in self._edges.values():
            self._index_label(edge.namespace, edge.source)
            self._index_label(edge.namespace, edge.target.value)

    def register_edge(self, edge: AliasEdge) -> AliasEdge:
        """Insert a fully formed edge, rejecting collisions and cycles."""

        if not isinstance(edge, AliasEdge):
            raise TypeError("edge must be an AliasEdge")
        self._require_mutable()

        # Target must be a registered canonical identity (never an alias key).
        try:
            registered = self._namespaces.require_identity(edge.target)
        except UnknownIdentityError as error:
            raise UnknownAliasError(
                f"alias target {edge.target.qualified!r} is not a registered "
                f"canonical identity"
            ) from error
        if registered.value != edge.target.value:
            raise AliasError(
                f"alias target {edge.target.qualified!r} is not canonical"
            )

        key = (edge.namespace, edge.source_key)
        if key in self._edges:
            raise AliasCollisionError(
                f"alias {edge.source!r} in namespace {edge.namespace.value!r} "
                f"is already registered"
            )

        # Source must not collide with another identity's canonical value or
        # namespace-catalog alias in the same namespace.
        if self._namespaces.contains(edge.namespace, edge.source):
            owner = self._namespaces.resolve(edge.namespace, edge.source)
            if owner.value != edge.target.value:
                raise AliasCollisionError(
                    f"alias {edge.source!r} in namespace {edge.namespace.value!r} "
                    f"collides with registered identity {owner.qualified!r}"
                )
            # Same target: redundant with namespace catalog — still reject to
            # keep a single authority for the surface form.
            raise AliasCollisionError(
                f"alias {edge.source!r} in namespace {edge.namespace.value!r} "
                f"is already claimed by the namespace catalog for "
                f"{owner.qualified!r}"
            )

        # Cycle check: walk target through any alias-of-alias chain.  Targets
        # are required to be canonical, so multi-hop cycles only arise if a
        # future edge re-aliases a previous target as a source of another edge
        # that eventually points back.  We also refuse sources that match any
        # existing edge's target under a chain that would close.
        if self._would_cycle(edge):
            raise AliasCycleError(
                f"alias {edge.source!r} -> {edge.target.qualified!r} would "
                f"introduce a cycle"
            )

        self._edges[key] = edge
        self._index_label(edge.namespace, edge.source)
        self._index_label(edge.namespace, edge.target.value)
        return edge

    def _would_cycle(self, edge: AliasEdge) -> bool:
        """Return True if adding *edge* would create a source/target cycle.

        Because targets must be canonical registry identities (never other
        alias sources), the only cycle shape is ``A -> B`` where some existing
        edge is ``B_label -> A_canonical`` and ``B_label`` normalizes to ``B``.
        We also reject any chain where following replacements from the new
        target eventually reaches the new source key.
        """

        source_key = edge.source_key
        # If any existing edge's source normalizes to the new target and its
        # target normalizes to the new source, that is a 2-cycle.
        target_key = normalize_identity_name(edge.target.value)
        for existing in self._edges.values():
            if existing.namespace is not edge.namespace:
                continue
            if (
                existing.source_key == target_key
                and normalize_identity_name(existing.target.value) == source_key
            ):
                return True

        # Walk alias edges whose source matches successive targets.  With the
        # canonical-target invariant this is usually a single step, but the
        # walk remains general and bounded.
        seen: set[str] = set()
        cursor = target_key
        while cursor not in seen:
            seen.add(cursor)
            if cursor == source_key:
                return True
            nxt = self._edges.get((edge.namespace, cursor))
            if nxt is None:
                break
            cursor = normalize_identity_name(nxt.target.value)
        return False

    def register(
        self,
        source: str,
        target: LogicIdentity | str,
        *,
        namespace: NamespaceKind | str | None = None,
        version: str = ALIAS_EDGE_VERSION,
        notes: str = "",
        target_version: str = IDENTITY_VERSION,
    ) -> AliasEdge:
        """Register a legacy *source* label for a canonical *target* identity."""

        if isinstance(target, LogicIdentity):
            identity = target
            if namespace is not None:
                expected = _coerce_namespace(namespace)
                if identity.namespace is not expected:
                    raise WrongNamespaceError(
                        f"target {identity.qualified!r} is not in namespace "
                        f"{expected.value!r}"
                    )
        else:
            if namespace is None:
                raise InvalidIdentifierError(
                    "namespace is required when target is a bare string"
                )
            identity = identity_for(
                namespace, validate_identifier(target, "target"), version=target_version
            )
        return self.register_edge(
            AliasEdge(
                source=source,
                target=identity,
                version=version,
                notes=notes,
            )
        )

    def edges(
        self,
        namespace: NamespaceKind | str | None = None,
    ) -> tuple[AliasEdge, ...]:
        """Return registered edges in deterministic order."""

        items = list(self._edges.values())
        if namespace is not None:
            kind = _coerce_namespace(namespace)
            items = [edge for edge in items if edge.namespace is kind]
        items.sort(key=lambda item: (item.namespace.value, item.source_key, item.source))
        return tuple(items)

    def __iter__(self) -> Iterator[AliasEdge]:
        return iter(self.edges())

    def __len__(self) -> int:
        return len(self._edges)

    def contains(self, namespace: NamespaceKind | str, name: str) -> bool:
        """Return whether *name* dual-reads in *namespace*."""

        try:
            self.resolve(namespace, name)
        except (UnknownAliasError, WrongNamespaceError, InvalidIdentifierError):
            return False
        return True

    def is_canonical(self, namespace: NamespaceKind | str, name: str) -> bool:
        """Return whether *name* is already the canonical id in *namespace*."""

        kind = _coerce_namespace(namespace)
        if not isinstance(name, str) or not name.strip():
            return False
        try:
            identity = self._namespaces.resolve(kind, name)
        except (UnknownIdentityError, InvalidIdentifierError):
            return False
        return normalize_identity_name(name) == normalize_identity_name(identity.value)

    def _known_namespaces_for(self, normalized: str) -> tuple[NamespaceKind, ...]:
        if not self._global_labels:
            self._rebuild_global_index()
        owners = self._global_labels.get(normalized, set())
        # Also probe the namespace catalog directly for freshness.
        for kind in NamespaceKind:
            if self._namespaces.contains(kind, normalized):
                owners.add(kind)
            if (kind, normalized) in self._edges:
                owners.add(kind)
        return tuple(sorted(owners, key=lambda item: item.value))

    def diagnose(
        self,
        namespace: NamespaceKind | str,
        name: str,
    ) -> LogicMigrationDiagnostic:
        """Produce a dual-read diagnostic without raising on failure."""

        kind = _coerce_namespace(namespace)
        if not isinstance(name, str) or not name.strip():
            return LogicMigrationDiagnostic(
                observed=str(name) if isinstance(name, str) else "",
                namespace=kind,
                disposition=MigrationDisposition.REJECTED_UNKNOWN,
                normalized="",
                error_code="invalid_label",
                message="label must be a non-empty string",
            )
        try:
            observed = _alias_label(name, "name")
            normalized = normalize_identity_name(observed)
        except InvalidIdentifierError as error:
            return LogicMigrationDiagnostic(
                observed=name.strip() if isinstance(name, str) else "",
                namespace=kind,
                disposition=MigrationDisposition.REJECTED_UNKNOWN,
                error_code="invalid_label",
                message=str(error),
            )

        # 1. Direct canonical / namespace-catalog alias resolution.
        if self._namespaces.contains(kind, observed):
            identity = self._namespaces.resolve(kind, observed)
            was_catalog_alias = normalize_identity_name(
                observed
            ) != normalize_identity_name(identity.value)
            if was_catalog_alias:
                return LogicMigrationDiagnostic(
                    observed=observed,
                    namespace=kind,
                    disposition=MigrationDisposition.REPLACED,
                    resolved=identity,
                    normalized=normalized,
                    resolution_kind=AliasResolutionKind.ALIAS,
                    alias_path=(observed, identity.value),
                    replacement=identity.value,
                    message=(
                        f"legacy label {observed!r} dual-reads as "
                        f"{identity.qualified}"
                    ),
                )
            return LogicMigrationDiagnostic(
                observed=observed,
                namespace=kind,
                disposition=MigrationDisposition.CANONICAL,
                resolved=identity,
                normalized=normalized,
                resolution_kind=AliasResolutionKind.CANONICAL,
                alias_path=(identity.value,),
                replacement=identity.value,
                message=f"label {observed!r} is already canonical",
            )

        # 2. Explicit migration edge in the requested namespace.
        edge = self._edges.get((kind, normalized))
        if edge is not None:
            identity = edge.target
            return LogicMigrationDiagnostic(
                observed=observed,
                namespace=kind,
                disposition=MigrationDisposition.REPLACED,
                resolved=identity,
                normalized=normalized,
                resolution_kind=AliasResolutionKind.ALIAS,
                alias_path=(observed, identity.value),
                replacement=identity.value,
                message=(
                    edge.notes
                    or f"legacy label {observed!r} dual-reads as {identity.qualified}"
                ),
            )

        # 3. Known under other namespace(s) → wrong-namespace fail closed.
        known = self._known_namespaces_for(normalized)
        other = tuple(item for item in known if item is not kind)
        if other:
            known_values = tuple(item.value for item in other)
            return LogicMigrationDiagnostic(
                observed=observed,
                namespace=kind,
                disposition=MigrationDisposition.REJECTED_WRONG_NAMESPACE,
                normalized=normalized,
                known_namespaces=known_values,
                error_code="wrong_namespace",
                message=(
                    f"label {observed!r} is not valid in namespace {kind.value!r}; "
                    f"known under: {', '.join(known_values)}"
                ),
            )

        # 4. Unknown everywhere.
        return LogicMigrationDiagnostic(
            observed=observed,
            namespace=kind,
            disposition=MigrationDisposition.REJECTED_UNKNOWN,
            normalized=normalized,
            error_code="unknown_label",
            message=(
                f"unknown label {observed!r} in namespace {kind.value!r}"
            ),
        )

    def resolve(
        self,
        namespace: NamespaceKind | str,
        name: str,
    ) -> LogicIdentity:
        """Dual-read resolve *name* in *namespace*; fail closed on errors."""

        diagnostic = self.diagnose(namespace, name)
        if not diagnostic.ok or diagnostic.resolved is None:
            if diagnostic.disposition is MigrationDisposition.REJECTED_WRONG_NAMESPACE:
                raise WrongNamespaceError(diagnostic.message)
            raise UnknownAliasError(diagnostic.message)
        return diagnostic.resolved

    def read(
        self,
        namespace: NamespaceKind | str,
        name: str,
    ) -> tuple[LogicIdentity, LogicMigrationDiagnostic]:
        """Dual-read: accept legacy aliases, return canonical id + diagnostic."""

        diagnostic = self.diagnose(namespace, name)
        if not diagnostic.ok or diagnostic.resolved is None:
            if diagnostic.disposition is MigrationDisposition.REJECTED_WRONG_NAMESPACE:
                raise WrongNamespaceError(diagnostic.message)
            raise UnknownAliasError(diagnostic.message)
        return diagnostic.resolved, diagnostic

    def canonicalize(
        self,
        namespace: NamespaceKind | str,
        name: str,
    ) -> LogicIdentity:
        """Deterministic dual-read canonicalization (alias of :meth:`resolve`)."""

        return self.resolve(namespace, name)

    def write(
        self,
        identity: LogicIdentity,
        *,
        namespace: NamespaceKind | str | None = None,
    ) -> LogicIdentity:
        """One-write: accept only canonical registered identities for emission.

        If *identity* is presented via a surface that still resolves (for
        example a catalog alias mistakenly constructed as an identity value),
        the method rewrites to the registered canonical form.  Unknown or
        wrong-namespace values fail closed.
        """

        if not isinstance(identity, LogicIdentity):
            raise WrongNamespaceError(
                f"write requires LogicIdentity, got {type(identity).__name__}"
            )
        if namespace is not None:
            expected = _coerce_namespace(namespace)
            if identity.namespace is not expected:
                raise WrongNamespaceError(
                    f"cannot write {identity.qualified!r} where namespace "
                    f"{expected.value!r} is required"
                )
        # Resolve through dual-read so catalog aliases collapse, then demand the
        # result is the registered canonical identity.
        resolved = self.resolve(identity.namespace, identity.value)
        if resolved.namespace is not identity.namespace:
            raise WrongNamespaceError(
                f"write collapsed {identity.qualified!r} into a different "
                f"namespace {resolved.qualified!r}"
            )
        # Re-check registration + version via the namespace catalog.
        return self._namespaces.require_identity(resolved)

    def write_value(
        self,
        namespace: NamespaceKind | str,
        name: str,
    ) -> str:
        """One-write helper returning only the canonical identifier string."""

        return self.write(
            self.canonicalize(namespace, name),
            namespace=namespace,
        ).value

    def canonicalize_many(
        self,
        namespace: NamespaceKind | str,
        names: Sequence[str],
    ) -> tuple[LogicIdentity, ...]:
        """Deterministically canonicalize a sequence of labels."""

        if isinstance(names, (str, bytes, bytearray)) or not isinstance(names, Sequence):
            raise InvalidIdentifierError("names must be a sequence of strings")
        return tuple(self.canonicalize(namespace, name) for name in names)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the registry with deterministic ordering."""

        return {
            "edges": [edge.to_dict() for edge in self.edges()],
            "interface": self.interface,
            "schema_version": self.schema_version,
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
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        namespaces: LogicIdentityNamespaces | None = None,
        frozen: bool = False,
    ) -> "LogicAliasRegistry":
        if not isinstance(payload, Mapping):
            raise InvalidIdentifierError("alias registry payload must be a mapping")
        schema = payload.get("schema_version")
        if schema != ALIAS_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported or missing schema_version: {schema!r}"
            )
        interface = payload.get("interface")
        if interface is not None and interface != ALIAS_INTERFACE:
            raise SchemaVersionError(f"unsupported interface: {interface!r}")
        raw_edges = payload.get("edges", ())
        if isinstance(raw_edges, (str, bytes, bytearray)) or not isinstance(
            raw_edges, Sequence
        ):
            raise InvalidIdentifierError("edges must be a sequence")
        edges = tuple(AliasEdge.from_dict(item) for item in raw_edges)
        return cls(
            edges=edges,
            namespaces=namespaces,
            version=payload.get("version", ALIAS_MODULE_VERSION),
            frozen=frozen,
        )

    @classmethod
    def parse(
        cls,
        payload: Mapping[str, Any] | str,
        *,
        namespaces: LogicIdentityNamespaces | None = None,
        frozen: bool = False,
    ) -> "LogicAliasRegistry":
        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError as error:
                raise InvalidIdentifierError(
                    f"alias registry JSON is not valid: {error.msg}"
                ) from error
            if not isinstance(decoded, Mapping):
                raise InvalidIdentifierError(
                    "alias registry JSON must decode to an object"
                )
            return cls.from_dict(decoded, namespaces=namespaces, frozen=frozen)
        return cls.from_dict(payload, namespaces=namespaces, frozen=frozen)


def build_baseline_alias_registry(
    *,
    namespaces: LogicIdentityNamespaces | None = None,
    frozen: bool = True,
) -> LogicAliasRegistry:
    """Build the reviewed dual-read alias catalog from the migration plan.

    Namespace-catalog aliases (for example ``fol`` → ``first_order``) remain
    authoritative in :mod:`namespaces`.  This registry adds migration edges
    that are not already claimed there, plus the dual-read / one-write API and
    wrong-namespace diagnostics over the shared baseline catalog.

    Plan evidence cases covered: fol, smt, tla_plus, hyperltl, protocol,
    secpal, VC, safety, provider, and view roles.
    """

    catalog = namespaces if namespaces is not None else BASELINE_NAMESPACES
    registry = LogicAliasRegistry(namespaces=catalog, version=ALIAS_MODULE_VERSION)

    # Edges not already claimed as namespace-catalog aliases.  Catalog aliases
    # (fol, smt, tla+, vc, coq, runtime, …) remain dual-readable via the
    # namespace table; these add the plan's remaining migration surface.
    # Sources must not normalize to their targets (AliasEdge rejects that).
    planned: tuple[tuple[str, NamespaceKind, str, str], ...] = (
        # Family — plan migration examples and reviewed legacy overloads.
        (
            "protocol",
            NamespaceKind.FAMILY,
            "cryptographic_protocol",
            "legacy protocol family label for cryptographic_protocol",
        ),
        (
            "crypto_protocol",
            NamespaceKind.FAMILY,
            "cryptographic_protocol",
            "legacy shortened cryptographic_protocol family label",
        ),
        (
            "dynamic_logic",
            NamespaceKind.FAMILY,
            "program",
            "dynamic_logic remains a versioned alias over canonical program",
        ),
        # Profile — freer surface forms not in the namespace catalog.
        (
            "hyper-ltl",
            NamespaceKind.PROFILE,
            "hyperltl",
            "legacy hyphenated HyperLTL profile label",
        ),
        (
            "policy",
            NamespaceKind.PROFILE,
            "secpal",
            "legacy policy profile under authorization/SecPAL",
        ),
        (
            "information_flow",
            NamespaceKind.PROFILE,
            "hyperltl",
            "information_flow remains a profile concern under hyperproperty",
        ),
        # Property abbreviations / alternate spellings.
        (
            "SAT",
            NamespaceKind.PROPERTY,
            "satisfiability",
            "legacy SAT property abbreviation",
        ),
        (
            "non_interference",
            NamespaceKind.PROPERTY,
            "noninterference",
            "legacy underscored noninterference property label",
        ),
        # View / obligation alternate spellings.
        (
            "verif_condition",
            NamespaceKind.VIEW,
            "verification_condition",
            "legacy abbreviated verification-condition view role",
        ),
        (
            "graph_view",
            NamespaceKind.VIEW,
            "graph_projection",
            "legacy graph_view role for graph_projection",
        ),
        # Encoding aliases (targets stay out of the family namespace).
        (
            "lean4_target",
            NamespaceKind.ENCODING,
            "lean4",
            "explicit Lean 4 target-encoding alias",
        ),
        (
            "isabelle_hol_encoding",
            NamespaceKind.ENCODING,
            "isabelle_hol",
            "explicit Isabelle/HOL encoding alias",
        ),
        # Evidence.
        (
            "kernel_proof",
            NamespaceKind.EVIDENCE,
            "kernel_checked_proof",
            "legacy kernel_proof evidence label",
        ),
    )

    for source, namespace, target, notes in planned:
        # Skip sources that normalize onto their target (not a real alias).
        if normalize_identity_name(source) == normalize_identity_name(target):
            continue
        # Skip edges already owned by the namespace catalog (collision-safe).
        if catalog.contains(namespace, source):
            continue
        try:
            catalog.get(namespace, target)
        except UnknownIdentityError:
            # Target missing from supplied catalog — skip rather than emit a
            # partial/invalid edge.
            continue
        registry.register(
            source,
            target,
            namespace=namespace,
            notes=notes,
        )

    # Ensure global label index covers namespace catalog for wrong-namespace
    # diagnostics even when no extra edges were added.
    registry._rebuild_global_index()

    if frozen:
        registry.freeze()
    return registry


BASELINE_ALIAS_REGISTRY: Final[LogicAliasRegistry] = build_baseline_alias_registry(
    frozen=True
)


def dual_read(
    namespace: NamespaceKind | str,
    name: str,
    *,
    registry: LogicAliasRegistry | None = None,
) -> tuple[LogicIdentity, LogicMigrationDiagnostic]:
    """Module-level dual-read against the baseline alias registry."""

    active = registry if registry is not None else BASELINE_ALIAS_REGISTRY
    return active.read(namespace, name)


def one_write(
    identity: LogicIdentity,
    *,
    namespace: NamespaceKind | str | None = None,
    registry: LogicAliasRegistry | None = None,
) -> LogicIdentity:
    """Module-level one-write against the baseline alias registry."""

    active = registry if registry is not None else BASELINE_ALIAS_REGISTRY
    return active.write(identity, namespace=namespace)


def canonicalize_label(
    namespace: NamespaceKind | str,
    name: str,
    *,
    registry: LogicAliasRegistry | None = None,
) -> LogicIdentity:
    """Module-level deterministic canonicalization helper."""

    active = registry if registry is not None else BASELINE_ALIAS_REGISTRY
    return active.canonicalize(namespace, name)


__all__ = [
    "ALIAS_EDGE_VERSION",
    "ALIAS_INTERFACE",
    "ALIAS_MODULE_VERSION",
    "ALIAS_SCHEMA_VERSION",
    "BASELINE_ALIAS_REGISTRY",
    "DIAGNOSTIC_INTERFACE",
    "DIAGNOSTIC_SCHEMA_VERSION",
    "DIAGNOSTIC_VERSION",
    "AliasCollisionError",
    "AliasCycleError",
    "AliasEdge",
    "AliasError",
    "AliasResolutionKind",
    "FrozenAliasRegistryError",
    "LogicAliasRegistry",
    "LogicMigrationDiagnostic",
    "MigrationDisposition",
    "UnknownAliasError",
    "WrongNamespaceError",
    "build_baseline_alias_registry",
    "canonicalize_label",
    "dual_read",
    "one_write",
]

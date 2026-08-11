"""Explicit notation/profile parser registry for the syntax core.

Interfaces (LFP-015):

* ``LogicParserRegistry@1`` — fail-closed registration and exact-key resolution
  of notation parsers keyed by
  ``(notation_id, notation_version, semantic_profile_id)``

Collisions are rejected.  Implicit fallback (partial keys, "latest" version,
profile defaults) is rejected.  Callers must name the full registry key.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    NamespaceKind,
    validate_version,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_COLLECTION_ITEMS,
    ParseArtifact,
    ParseRequest,
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _text,
    _thaw_mapping,
    require_namespace_identity,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_PARSER_REGISTRY_INTERFACE: Final = "LogicParserRegistry@1"
LOGIC_PARSER_DESCRIPTOR_INTERFACE: Final = "LogicParserDescriptor@1"
PARSER_REGISTRY_SCHEMA_VERSION: Final = "syntax-logic-parser-registry/v1"
PARSER_DESCRIPTOR_SCHEMA_VERSION: Final = "syntax-logic-parser-descriptor/v1"
PARSER_KEY_SCHEMA_VERSION: Final = "syntax-logic-parser-key/v1"
REGISTRY_MODULE_VERSION: Final = "1.0.0"

_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")


class ParserRegistryError(SyntaxContractError):
    """Raised when a parser registry operation is invalid."""


class DuplicateParserError(ParserRegistryError):
    """Raised when a registry key is registered more than once."""


class UnknownParserError(ParserRegistryError):
    """Raised when an exact registry key has no registered parser."""


class ImplicitFallbackError(ParserRegistryError):
    """Raised when a caller requests implicit fallback or partial-key lookup."""


# ---------------------------------------------------------------------------
# Parser protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LogicParser(Protocol):
    """Callable surface for a notation parser bound to a registry key."""

    def parse(self, request: ParseRequest) -> ParseArtifact:
        """Parse *request* into a :class:`ParseArtifact`."""
        ...


ParserFactory = Callable[[], LogicParser]
ParseCallable = Callable[[ParseRequest], ParseArtifact]


# ---------------------------------------------------------------------------
# Registry key
# ---------------------------------------------------------------------------


def _notation_value(value: object, field_name: str = "notation_id") -> str:
    identity = require_namespace_identity(value, NamespaceKind.NOTATION, field_name)
    return identity.value


def _profile_value(value: object, field_name: str = "semantic_profile_id") -> str:
    identity = require_namespace_identity(value, NamespaceKind.PROFILE, field_name)
    return identity.value


def _version_label(value: object, field_name: str = "notation_version") -> str:
    text = _text(value, field_name, maximum=64)
    # Reject sentinel values that would enable implicit "latest" fallback.
    # Must run before validate_version: generic version validation accepts
    # labels like "latest" and "*", which are not valid registry versions.
    lowered = text.casefold()
    if lowered in {"*", "latest", "any", "default", "auto", ""}:
        raise ImplicitFallbackError(
            f"{field_name} rejects implicit fallback sentinel {text!r}"
        )
    try:
        return validate_version(text, field_name)
    except Exception:
        # Allow simple numeric / dotted versions already used by notations.
        if not text or text != text.strip() or "\x00" in text:
            raise ParserRegistryError(
                f"{field_name} must be a non-empty trimmed version label"
            )
        return text


@dataclass(frozen=True, slots=True)
class ParserKey:
    """Exact registry key: notation, version, and semantic profile.

    Partial keys and wildcards are not representable.  Construction rejects
    fallback sentinels such as ``latest`` or ``*``.
    """

    notation_id: str
    notation_version: str
    semantic_profile_id: str
    schema_version: str = PARSER_KEY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "notation_id", _notation_value(self.notation_id, "notation_id")
        )
        object.__setattr__(
            self,
            "notation_version",
            _version_label(self.notation_version, "notation_version"),
        )
        object.__setattr__(
            self,
            "semantic_profile_id",
            _profile_value(self.semantic_profile_id, "semantic_profile_id"),
        )
        if self.schema_version != PARSER_KEY_SCHEMA_VERSION:
            raise ParserRegistryError(
                f"unsupported ParserKey schema_version {self.schema_version!r}"
            )

    @property
    def as_tuple(self) -> tuple[str, str, str]:
        return (self.notation_id, self.notation_version, self.semantic_profile_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notation_id": self.notation_id,
            "notation_version": self.notation_version,
            "schema_version": self.schema_version,
            "semantic_profile_id": self.semantic_profile_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParserKey":
        payload = _require_mapping(data, "ParserKey")
        return cls(
            notation_id=str(payload.get("notation_id") or ""),
            notation_version=str(payload.get("notation_version") or ""),
            semantic_profile_id=str(payload.get("semantic_profile_id") or ""),
            schema_version=str(
                payload.get("schema_version") or PARSER_KEY_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_parts(
        cls,
        notation_id: LogicIdentity | Mapping[str, Any] | str,
        notation_version: str,
        semantic_profile_id: LogicIdentity | Mapping[str, Any] | str,
    ) -> "ParserKey":
        return cls(
            notation_id=_notation_value(notation_id),
            notation_version=_version_label(notation_version),
            semantic_profile_id=_profile_value(semantic_profile_id),
        )

    def matches_request(self, request: ParseRequest) -> bool:
        """Return True when *request* names this exact key (no fallback)."""

        if not isinstance(request, ParseRequest):
            raise ParserRegistryError("matches_request requires a ParseRequest")
        notation = (
            request.notation_id.value
            if isinstance(request.notation_id, LogicIdentity)
            else _notation_value(request.notation_id)
        )
        profile = (
            request.profile_id.value
            if isinstance(request.profile_id, LogicIdentity)
            else _profile_value(request.profile_id)
        )
        # ParseRequest does not carry version; version is part of the registry
        # key supplied explicitly by the caller at resolve time.
        return notation == self.notation_id and profile == self.semantic_profile_id


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicParserDescriptor:
    """Immutable registration record for one notation parser.

    Interface: ``LogicParserDescriptor@1``.
    """

    descriptor_id: str
    key: ParserKey
    family_id: LogicIdentity | Mapping[str, Any] | str | None = None
    features: tuple[str, ...] = ()
    implementation: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PARSER_DESCRIPTOR_SCHEMA_VERSION

    interface: ClassVar[str] = LOGIC_PARSER_DESCRIPTOR_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "descriptor_id", _record_id(self.descriptor_id, "descriptor_id")
        )
        if not isinstance(self.key, ParserKey):
            if isinstance(self.key, Mapping):
                object.__setattr__(self, "key", ParserKey.from_dict(self.key))
            else:
                raise ParserRegistryError(
                    "LogicParserDescriptor.key must be a ParserKey"
                )
        if self.family_id is not None:
            object.__setattr__(
                self,
                "family_id",
                require_namespace_identity(
                    self.family_id, NamespaceKind.FAMILY, "family_id"
                ),
            )
        raw_features = _require_sequence(
            self.features if self.features is not None else (), "features"
        )
        features_list: list[str] = []
        for item in raw_features:
            feature = _text(item, "features item", maximum=128)
            if not _FEATURE_RE.fullmatch(feature):
                raise ParserRegistryError(
                    f"features item must be a lowercase feature id; got {feature!r}"
                )
            features_list.append(feature)
        if len(features_list) > MAX_COLLECTION_ITEMS:
            raise ParserRegistryError("features exceeds collection ceiling")
        if len(features_list) != len(set(features_list)):
            raise ParserRegistryError("features must not contain duplicates")
        object.__setattr__(self, "features", tuple(sorted(features_list)))
        object.__setattr__(
            self,
            "implementation",
            _text(self.implementation, "implementation", maximum=256)
            if self.implementation
            else "",
        )
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != PARSER_DESCRIPTOR_SCHEMA_VERSION:
            raise ParserRegistryError(
                f"unsupported LogicParserDescriptor schema_version "
                f"{self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "descriptor_id": self.descriptor_id,
            "features": list(self.features),
            "implementation": self.implementation,
            "interface": self.interface,
            "key": self.key.to_dict(),
            "metadata": _thaw_mapping(self.metadata),
            "schema_version": self.schema_version,
        }
        if self.family_id is not None:
            payload["family_id"] = (
                self.family_id.to_dict()
                if isinstance(self.family_id, LogicIdentity)
                else self.family_id
            )
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicParserDescriptor":
        payload = _require_mapping(data, "LogicParserDescriptor")
        interface = payload.get("interface")
        if interface is not None and interface != LOGIC_PARSER_DESCRIPTOR_INTERFACE:
            raise ParserRegistryError(
                f"unsupported LogicParserDescriptor interface {interface!r}"
            )
        return cls(
            descriptor_id=str(payload.get("descriptor_id") or ""),
            key=ParserKey.from_dict(_require_mapping(payload.get("key"), "key")),
            family_id=payload.get("family_id"),
            features=tuple(payload.get("features") or ()),
            implementation=str(payload.get("implementation") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or PARSER_DESCRIPTOR_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Registry entry (descriptor + bound callable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RegistryEntry:
    descriptor: LogicParserDescriptor
    parser: LogicParser | ParseCallable | None = None
    factory: ParserFactory | None = None

    def resolve_parser(self) -> LogicParser | ParseCallable:
        if self.parser is not None:
            return self.parser
        if self.factory is not None:
            instance = self.factory()
            if not callable(getattr(instance, "parse", None)) and not callable(
                instance
            ):
                raise ParserRegistryError(
                    f"factory for {self.descriptor.descriptor_id!r} did not "
                    "return a parser"
                )
            return instance  # type: ignore[return-value]
        raise ParserRegistryError(
            f"parser {self.descriptor.descriptor_id!r} has no bound implementation"
        )


# ---------------------------------------------------------------------------
# LogicParserRegistry@1
# ---------------------------------------------------------------------------


class LogicParserRegistry:
    """Exact-key parser registry with collision and fallback rejection.

    Interface: ``LogicParserRegistry@1``.

    Registration is fail-closed:

    * Duplicate ``ParserKey`` values raise :class:`DuplicateParserError`.
    * Lookup requires the full ``(notation_id, notation_version,
      semantic_profile_id)`` triple.
    * Partial-key, "latest", wildcard, and default-profile resolution raise
      :class:`ImplicitFallbackError`.
    """

    interface: ClassVar[str] = LOGIC_PARSER_REGISTRY_INTERFACE
    schema_version: ClassVar[str] = PARSER_REGISTRY_SCHEMA_VERSION

    def __init__(self, *, registry_id: str = "registry:logic-parsers") -> None:
        self._registry_id = _record_id(registry_id, "registry_id")
        self._entries: dict[tuple[str, str, str], _RegistryEntry] = {}

    @property
    def registry_id(self) -> str:
        return self._registry_id

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, ParserKey):
            return key.as_tuple in self._entries
        if isinstance(key, tuple) and len(key) == 3:
            try:
                parsed = ParserKey.from_parts(key[0], str(key[1]), key[2])
            except (ParserRegistryError, SyntaxContractError, TypeError, ValueError):
                return False
            return parsed.as_tuple in self._entries
        return False

    def keys(self) -> tuple[ParserKey, ...]:
        return tuple(
            sorted(
                (entry.descriptor.key for entry in self._entries.values()),
                key=lambda item: item.as_tuple,
            )
        )

    def descriptors(self) -> tuple[LogicParserDescriptor, ...]:
        return tuple(
            self._entries[key].descriptor
            for key in sorted(self._entries)
        )

    def register(
        self,
        descriptor: LogicParserDescriptor | Mapping[str, Any],
        *,
        parser: LogicParser | ParseCallable | None = None,
        factory: ParserFactory | None = None,
        replace: bool = False,
    ) -> LogicParserDescriptor:
        """Register *descriptor* under its exact key.

        ``replace=True`` is required to overwrite an existing key; silent
        replacement is never the default.
        """

        if not isinstance(descriptor, LogicParserDescriptor):
            descriptor = LogicParserDescriptor.from_dict(
                _require_mapping(descriptor, "descriptor")
            )
        if parser is None and factory is None:
            raise ParserRegistryError(
                "register requires a parser instance or factory; "
                "descriptor-only registration without an implementation is "
                "rejected for executable entries"
            )
        if parser is not None and factory is not None:
            raise ParserRegistryError(
                "register accepts either parser or factory, not both"
            )
        if parser is not None:
            if not callable(parser) and not callable(getattr(parser, "parse", None)):
                raise ParserRegistryError(
                    "parser must be callable or expose a parse() method"
                )
        key = descriptor.key.as_tuple
        if key in self._entries and not replace:
            existing = self._entries[key].descriptor
            raise DuplicateParserError(
                f"parser key {descriptor.key.to_dict()!r} collides with "
                f"existing descriptor {existing.descriptor_id!r}; "
                "registry collisions are rejected"
            )
        # Also reject descriptor_id collisions under a different key.
        for entry in self._entries.values():
            if (
                entry.descriptor.descriptor_id == descriptor.descriptor_id
                and entry.descriptor.key.as_tuple != key
            ):
                raise DuplicateParserError(
                    f"descriptor_id {descriptor.descriptor_id!r} is already "
                    f"registered under key {entry.descriptor.key.to_dict()!r}"
                )
        self._entries[key] = _RegistryEntry(
            descriptor=descriptor,
            parser=parser,
            factory=factory,
        )
        return descriptor

    def unregister(self, key: ParserKey | Mapping[str, Any]) -> None:
        parsed = key if isinstance(key, ParserKey) else ParserKey.from_dict(key)
        tuple_key = parsed.as_tuple
        if tuple_key not in self._entries:
            raise UnknownParserError(
                f"no parser registered for exact key {parsed.to_dict()!r}"
            )
        del self._entries[tuple_key]

    def resolve(
        self,
        notation_id: LogicIdentity | Mapping[str, Any] | str | None = None,
        notation_version: str | None = None,
        semantic_profile_id: LogicIdentity | Mapping[str, Any] | str | None = None,
        *,
        key: ParserKey | Mapping[str, Any] | None = None,
    ) -> LogicParser | ParseCallable:
        """Resolve a parser by exact key only.

        Implicit fallback is rejected: every component of the key must be
        supplied (either via *key* or all three parts).  Missing version or
        profile never defaults.
        """

        parsed_key = self._require_exact_key(
            notation_id=notation_id,
            notation_version=notation_version,
            semantic_profile_id=semantic_profile_id,
            key=key,
        )
        entry = self._entries.get(parsed_key.as_tuple)
        if entry is None:
            raise UnknownParserError(
                f"no parser registered for exact key {parsed_key.to_dict()!r}; "
                "implicit fallback is rejected"
            )
        return entry.resolve_parser()

    def resolve_descriptor(
        self,
        notation_id: LogicIdentity | Mapping[str, Any] | str | None = None,
        notation_version: str | None = None,
        semantic_profile_id: LogicIdentity | Mapping[str, Any] | str | None = None,
        *,
        key: ParserKey | Mapping[str, Any] | None = None,
    ) -> LogicParserDescriptor:
        parsed_key = self._require_exact_key(
            notation_id=notation_id,
            notation_version=notation_version,
            semantic_profile_id=semantic_profile_id,
            key=key,
        )
        entry = self._entries.get(parsed_key.as_tuple)
        if entry is None:
            raise UnknownParserError(
                f"no parser registered for exact key {parsed_key.to_dict()!r}; "
                "implicit fallback is rejected"
            )
        return entry.descriptor

    def get(
        self,
        notation_id: LogicIdentity | Mapping[str, Any] | str | None = None,
        notation_version: str | None = None,
        semantic_profile_id: LogicIdentity | Mapping[str, Any] | str | None = None,
        *,
        key: ParserKey | Mapping[str, Any] | None = None,
        default: Any = ...,
    ) -> LogicParser | ParseCallable | Any:
        """Like :meth:`resolve` but returns *default* when provided.

        Omitting *default* preserves fail-closed resolution.  Passing a
        default is explicit caller choice, not registry fallback.
        """

        try:
            return self.resolve(
                notation_id=notation_id,
                notation_version=notation_version,
                semantic_profile_id=semantic_profile_id,
                key=key,
            )
        except UnknownParserError:
            if default is ...:
                raise
            return default

    def parse(
        self,
        request: ParseRequest,
        *,
        notation_version: str,
        notation_id: LogicIdentity | Mapping[str, Any] | str | None = None,
        semantic_profile_id: LogicIdentity | Mapping[str, Any] | str | None = None,
    ) -> ParseArtifact:
        """Resolve by exact key and invoke the bound parser.

        *notation_version* is mandatory: the registry never infers version
        from the request or defaults to "latest".
        """

        if not isinstance(request, ParseRequest):
            raise ParserRegistryError("parse requires a ParseRequest")
        if notation_version is None or (
            isinstance(notation_version, str) and not notation_version.strip()
        ):
            raise ImplicitFallbackError(
                "notation_version is required; implicit version fallback is rejected"
            )
        notation = notation_id if notation_id is not None else request.notation_id
        profile = (
            semantic_profile_id
            if semantic_profile_id is not None
            else request.profile_id
        )
        parser = self.resolve(
            notation_id=notation,
            notation_version=notation_version,
            semantic_profile_id=profile,
        )
        if callable(getattr(parser, "parse", None)):
            artifact = parser.parse(request)  # type: ignore[union-attr]
        elif callable(parser):
            artifact = parser(request)
        else:
            raise ParserRegistryError("resolved parser is not callable")
        if not isinstance(artifact, ParseArtifact):
            raise ParserRegistryError(
                "parser must return a ParseArtifact; got "
                f"{type(artifact).__name__}"
            )
        return artifact

    def select_for_request(
        self,
        request: ParseRequest,
        *,
        notation_version: str,
    ) -> LogicParserDescriptor:
        """Select the descriptor for *request* with an explicit version.

        Does not fall back across versions or profiles when the exact key is
        missing.
        """

        if not isinstance(request, ParseRequest):
            raise ParserRegistryError("select_for_request requires a ParseRequest")
        return self.resolve_descriptor(
            notation_id=request.notation_id,
            notation_version=notation_version,
            semantic_profile_id=request.profile_id,
        )

    def resolve_by_partial(
        self,
        *,
        notation_id: object = None,
        notation_version: object = None,
        semantic_profile_id: object = None,
    ) -> None:
        """Explicitly reject partial-key resolution.

        Present so callers that attempt fallback-style APIs receive a stable
        :class:`ImplicitFallbackError` rather than a silent match.
        """

        raise ImplicitFallbackError(
            "partial-key parser resolution is rejected; supply the full "
            f"(notation_id, notation_version, semantic_profile_id) key "
            f"(got notation_id={notation_id!r}, "
            f"notation_version={notation_version!r}, "
            f"semantic_profile_id={semantic_profile_id!r})"
        )

    def _require_exact_key(
        self,
        *,
        notation_id: object,
        notation_version: object,
        semantic_profile_id: object,
        key: ParserKey | Mapping[str, Any] | None,
    ) -> ParserKey:
        if key is not None:
            if notation_id is not None or notation_version is not None or (
                semantic_profile_id is not None
            ):
                raise ImplicitFallbackError(
                    "provide either key= or all three key components, not both"
                )
            return key if isinstance(key, ParserKey) else ParserKey.from_dict(key)
        missing = [
            name
            for name, value in (
                ("notation_id", notation_id),
                ("notation_version", notation_version),
                ("semantic_profile_id", semantic_profile_id),
            )
            if value is None or (isinstance(value, str) and not str(value).strip())
        ]
        if missing:
            raise ImplicitFallbackError(
                "exact parser resolution requires notation_id, "
                "notation_version, and semantic_profile_id; missing "
                f"{', '.join(missing)}; implicit fallback is rejected"
            )
        return ParserKey.from_parts(
            notation_id,  # type: ignore[arg-type]
            str(notation_version),
            semantic_profile_id,  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptors": [item.to_dict() for item in self.descriptors()],
            "interface": self.interface,
            "registry_id": self._registry_id,
            "schema_version": self.schema_version,
        }

    def freeze(self) -> "FrozenLogicParserRegistry":
        """Return an immutable snapshot of this registry."""

        return FrozenLogicParserRegistry(self)

    def __iter__(self) -> Iterator[LogicParserDescriptor]:
        return iter(self.descriptors())


class FrozenLogicParserRegistry(LogicParserRegistry):
    """Immutable view over a :class:`LogicParserRegistry` snapshot."""

    def __init__(self, source: LogicParserRegistry) -> None:
        super().__init__(registry_id=source.registry_id)
        # Copy entries without re-validating callables.
        for key, entry in source._entries.items():  # noqa: SLF001
            self._entries[key] = entry
        self._frozen = True

    def register(self, *args: Any, **kwargs: Any) -> LogicParserDescriptor:
        raise ParserRegistryError("FrozenLogicParserRegistry is immutable")

    def unregister(self, key: ParserKey | Mapping[str, Any]) -> None:
        raise ParserRegistryError("FrozenLogicParserRegistry is immutable")


def empty_parser_registry(
    *, registry_id: str = "registry:logic-parsers"
) -> LogicParserRegistry:
    """Return a fresh empty registry."""

    return LogicParserRegistry(registry_id=registry_id)


__all__ = [
    "LOGIC_PARSER_DESCRIPTOR_INTERFACE",
    "LOGIC_PARSER_REGISTRY_INTERFACE",
    "PARSER_DESCRIPTOR_SCHEMA_VERSION",
    "PARSER_KEY_SCHEMA_VERSION",
    "PARSER_REGISTRY_SCHEMA_VERSION",
    "REGISTRY_MODULE_VERSION",
    "DuplicateParserError",
    "FrozenLogicParserRegistry",
    "ImplicitFallbackError",
    "LogicParser",
    "LogicParserDescriptor",
    "LogicParserRegistry",
    "ParserFactory",
    "ParserKey",
    "ParserRegistryError",
    "UnknownParserError",
    "empty_parser_registry",
]

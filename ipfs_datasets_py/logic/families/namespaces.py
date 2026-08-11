"""Typed, non-interchangeable logic identity namespaces.

``LogicIdentityNamespaces@1`` binds every identity string to exactly one of
the canonical roles required by the logic-family parser plan:

* semantic family
* fragment / profile
* property / obligation kind
* view role
* notation / source syntax
* target encoding
* provider
* execution lane
* evidence kind

Values from different namespaces are never interchangeable.  Cross-namespace
coercion fails closed, aliases cannot collide within a namespace after
normalization, and serialization is deterministic with an explicit schema
and module version.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final


NAMESPACE_SCHEMA_VERSION: Final = "logic-identity-namespaces/v1"
NAMESPACE_INTERFACE: Final = "LogicIdentityNamespaces@1"
NAMESPACE_MODULE_VERSION: Final = "1.0.0"
IDENTITY_VERSION: Final = "1.0.0"

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")
_ALIAS_SEPARATORS = re.compile(r"[^a-z0-9]+")


class NamespaceError(ValueError):
    """Base error for logic identity namespace operations."""


class InvalidIdentifierError(NamespaceError):
    """Raised when an identity or alias string is malformed."""


class AliasCollisionError(NamespaceError):
    """Raised when two identities claim the same normalized alias."""


class CrossNamespaceCoercionError(NamespaceError, TypeError):
    """Raised when an identity is forced into the wrong namespace."""


class UnknownIdentityError(NamespaceError, KeyError):
    """Raised when a name cannot be resolved in the requested namespace."""


class SchemaVersionError(NamespaceError):
    """Raised when a payload carries an unsupported schema or interface."""


class FrozenNamespaceError(NamespaceError):
    """Raised on attempted mutation of a frozen namespace table."""


class NamespaceKind(str, Enum):
    """Canonical roles that identity strings may occupy.

    Members are deliberately non-interchangeable: a provider id is never a
    family id, even when the surface strings coincide.
    """

    FAMILY = "family"
    PROFILE = "profile"
    PROPERTY = "property"
    VIEW = "view"
    NOTATION = "notation"
    ENCODING = "encoding"
    PROVIDER = "provider"
    LANE = "lane"
    EVIDENCE = "evidence"


CANONICAL_NAMESPACE_KINDS: Final[tuple[NamespaceKind, ...]] = tuple(NamespaceKind)


def normalize_identity_name(value: str) -> str:
    """Normalize an identity or alias for collision-safe lookup."""

    if not isinstance(value, str) or not value.strip():
        raise InvalidIdentifierError("identity name must be a non-empty string")
    normalized = _ALIAS_SEPARATORS.sub("_", value.strip().casefold()).strip("_")
    if not normalized:
        raise InvalidIdentifierError(
            "identity name must contain at least one alphanumeric character"
        )
    return normalized


def validate_identifier(value: object, field_name: str = "value") -> str:
    """Validate a lowercase canonical identifier string."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidIdentifierError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise InvalidIdentifierError(f"{field_name} must not contain NUL bytes")
    if not _IDENTIFIER_RE.fullmatch(value):
        raise InvalidIdentifierError(
            f"{field_name} must be a lowercase canonical identifier; got {value!r}"
        )
    return value


def validate_version(value: object, field_name: str = "version") -> str:
    """Validate a version label that may appear on the wire."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidIdentifierError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "/" in value or any(character.isspace() for character in value):
        raise InvalidIdentifierError(
            f"{field_name} must not contain '/' or whitespace"
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


def _alias_text(value: object, field_name: str = "alias") -> str:
    """Validate a human alias (freer form than a canonical identifier)."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidIdentifierError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise InvalidIdentifierError(f"{field_name} must not contain NUL bytes")
    # Ensure the alias still normalizes to a collision key.
    normalize_identity_name(value)
    return value


def _aliases(value: Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InvalidIdentifierError("aliases must be a sequence of strings")
    result = tuple(_alias_text(item, "aliases item") for item in value)
    if len(set(result)) != len(result):
        raise AliasCollisionError("aliases must not contain duplicates")
    # Deterministic order by normalized key, then surface form.
    return tuple(sorted(result, key=lambda item: (normalize_identity_name(item), item)))


@dataclass(frozen=True, slots=True)
class LogicIdentity:
    """A single typed identity value bound to exactly one namespace.

    Equality, hashing, and serialization always include the namespace, so
    ``family:first_order`` is never equal to ``provider:first_order``.
    """

    namespace: NamespaceKind
    value: str
    version: str = IDENTITY_VERSION

    schema_version: ClassVar[str] = NAMESPACE_SCHEMA_VERSION
    interface: ClassVar[str] = NAMESPACE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _coerce_namespace(self.namespace))
        object.__setattr__(self, "value", validate_identifier(self.value, "value"))
        object.__setattr__(self, "version", validate_version(self.version, "version"))

    @property
    def kind(self) -> NamespaceKind:
        """Alias for :attr:`namespace` used by role-oriented call sites."""

        return self.namespace

    @property
    def qualified(self) -> str:
        """Return the stable ``namespace:value`` display form."""

        return f"{self.namespace.value}:{self.value}"

    def require(self, namespace: NamespaceKind | str) -> "LogicIdentity":
        """Return *self* when it occupies *namespace*; otherwise fail closed."""

        expected = _coerce_namespace(namespace)
        if self.namespace is not expected:
            raise CrossNamespaceCoercionError(
                f"cannot use {self.qualified!r} where "
                f"namespace {expected.value!r} is required"
            )
        return self

    def coerce(self, namespace: NamespaceKind | str) -> "LogicIdentity":
        """Coerce this identity into *namespace*.

        Same-namespace coercion is a no-op.  Cross-namespace coercion always
        fails closed; identities are never rewritten into another role.
        """

        return self.require(namespace)

    def as_namespace(self, namespace: NamespaceKind | str) -> "LogicIdentity":
        """Fail-closed cast synonym for :meth:`coerce`."""

        return self.coerce(namespace)

    def to_dict(self) -> dict[str, str]:
        """Serialize this identity with stable key ordering semantics."""

        return {
            "interface": self.interface,
            "namespace": self.namespace.value,
            "schema_version": self.schema_version,
            "value": self.value,
            "version": self.version,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        """Deterministic JSON for this identity."""

        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LogicIdentity":
        """Parse a wire identity, rejecting wrong schema/interface/namespace."""

        if not isinstance(payload, Mapping):
            raise InvalidIdentifierError("identity payload must be a mapping")
        schema = payload.get("schema_version")
        if schema != NAMESPACE_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported or missing schema_version: {schema!r}"
            )
        interface = payload.get("interface")
        if interface is not None and interface != NAMESPACE_INTERFACE:
            raise SchemaVersionError(
                f"unsupported interface: {interface!r}"
            )
        return cls(
            namespace=payload["namespace"],
            value=payload["value"],
            version=payload.get("version", IDENTITY_VERSION),
        )

    @classmethod
    def parse(cls, payload: Mapping[str, Any] | str) -> "LogicIdentity":
        """Parse a mapping or JSON string into a typed identity."""

        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError as error:
                raise InvalidIdentifierError(
                    f"identity JSON is not valid: {error.msg}"
                ) from error
            if not isinstance(decoded, Mapping):
                raise InvalidIdentifierError(
                    "identity JSON must decode to an object"
                )
            return cls.from_dict(decoded)
        return cls.from_dict(payload)


def family_id(value: str, *, version: str = IDENTITY_VERSION) -> LogicIdentity:
    """Construct a semantic-family identity."""

    return LogicIdentity(NamespaceKind.FAMILY, value, version=version)


def profile_id(value: str, *, version: str = IDENTITY_VERSION) -> LogicIdentity:
    """Construct a fragment/profile identity."""

    return LogicIdentity(NamespaceKind.PROFILE, value, version=version)


def property_id(value: str, *, version: str = IDENTITY_VERSION) -> LogicIdentity:
    """Construct a property/obligation identity."""

    return LogicIdentity(NamespaceKind.PROPERTY, value, version=version)


def view_id(value: str, *, version: str = IDENTITY_VERSION) -> LogicIdentity:
    """Construct a view-role identity."""

    return LogicIdentity(NamespaceKind.VIEW, value, version=version)


def notation_id(value: str, *, version: str = IDENTITY_VERSION) -> LogicIdentity:
    """Construct a notation/source-syntax identity."""

    return LogicIdentity(NamespaceKind.NOTATION, value, version=version)


def encoding_id(value: str, *, version: str = IDENTITY_VERSION) -> LogicIdentity:
    """Construct a target-encoding identity."""

    return LogicIdentity(NamespaceKind.ENCODING, value, version=version)


def provider_id(value: str, *, version: str = IDENTITY_VERSION) -> LogicIdentity:
    """Construct a provider identity."""

    return LogicIdentity(NamespaceKind.PROVIDER, value, version=version)


def lane_id(value: str, *, version: str = IDENTITY_VERSION) -> LogicIdentity:
    """Construct an execution-lane identity."""

    return LogicIdentity(NamespaceKind.LANE, value, version=version)


def evidence_id(value: str, *, version: str = IDENTITY_VERSION) -> LogicIdentity:
    """Construct an evidence-kind identity."""

    return LogicIdentity(NamespaceKind.EVIDENCE, value, version=version)


def identity_for(
    namespace: NamespaceKind | str,
    value: str,
    *,
    version: str = IDENTITY_VERSION,
) -> LogicIdentity:
    """Construct an identity for an arbitrary namespace kind."""

    return LogicIdentity(_coerce_namespace(namespace), value, version=version)


def coerce_identity(
    identity: LogicIdentity,
    namespace: NamespaceKind | str,
) -> LogicIdentity:
    """Fail-closed cross-namespace coercion helper."""

    if not isinstance(identity, LogicIdentity):
        raise CrossNamespaceCoercionError(
            f"expected LogicIdentity, got {type(identity).__name__}"
        )
    return identity.coerce(namespace)


@dataclass(frozen=True, slots=True)
class NamespaceBinding:
    """A registered canonical identity plus its non-colliding aliases."""

    identity: LogicIdentity
    aliases: tuple[str, ...] = ()
    name: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LogicIdentity):
            raise InvalidIdentifierError("binding identity must be a LogicIdentity")
        object.__setattr__(self, "aliases", _aliases(self.aliases))
        name = self.name
        if name:
            if not isinstance(name, str) or name != name.strip() or "\x00" in name:
                raise InvalidIdentifierError(
                    "name must be a non-empty trimmed string without NUL"
                )
        else:
            name = ""
        object.__setattr__(self, "name", name)
        description = self.description
        if description:
            if (
                not isinstance(description, str)
                or description != description.strip()
                or "\x00" in description
            ):
                raise InvalidIdentifierError(
                    "description must be a non-empty trimmed string without NUL"
                )
        else:
            description = ""
        object.__setattr__(self, "description", description)

        claimed = (self.identity.value, *self.aliases)
        normalized: set[str] = set()
        for claim in claimed:
            key = normalize_identity_name(claim)
            if key in normalized:
                raise AliasCollisionError(
                    f"binding {self.identity.qualified!r} contains colliding "
                    f"aliases after normalization: {claim!r}"
                )
            normalized.add(key)

    @property
    def namespace(self) -> NamespaceKind:
        return self.identity.namespace

    @property
    def value(self) -> str:
        return self.identity.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "description": self.description,
            "identity": self.identity.to_dict(),
            "name": self.name,
            "namespace": self.namespace.value,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NamespaceBinding":
        if not isinstance(payload, Mapping):
            raise InvalidIdentifierError("binding payload must be a mapping")
        identity_payload = payload.get("identity")
        if isinstance(identity_payload, Mapping):
            identity = LogicIdentity.from_dict(identity_payload)
        else:
            identity = LogicIdentity(
                namespace=payload["namespace"],
                value=payload["value"],
                version=payload.get("version", IDENTITY_VERSION),
            )
        declared_namespace = payload.get("namespace")
        if declared_namespace is not None:
            if _coerce_namespace(declared_namespace) is not identity.namespace:
                raise CrossNamespaceCoercionError(
                    f"binding namespace {declared_namespace!r} disagrees with "
                    f"identity namespace {identity.namespace.value!r}"
                )
        declared_value = payload.get("value")
        if declared_value is not None and declared_value != identity.value:
            raise InvalidIdentifierError(
                f"binding value {declared_value!r} disagrees with "
                f"identity value {identity.value!r}"
            )
        return cls(
            identity=identity,
            aliases=tuple(payload.get("aliases", ())),
            name=payload.get("name", "") or "",
            description=payload.get("description", "") or "",
        )


class LogicIdentityNamespaces:
    """Validated catalog of typed identity bindings across all namespaces.

    Bindings are mutable while the catalog is assembled and may then be
    frozen.  Registration validates alias collisions immediately so a
    successful call never leaves a partially valid table behind.
    """

    schema_version: Final = NAMESPACE_SCHEMA_VERSION
    interface: Final = NAMESPACE_INTERFACE

    def __init__(
        self,
        bindings: Iterable[NamespaceBinding] | None = None,
        *,
        version: str = NAMESPACE_MODULE_VERSION,
        frozen: bool = False,
    ) -> None:
        self.version = validate_version(version, "version")
        self._bindings: dict[tuple[NamespaceKind, str], NamespaceBinding] = {}
        # (namespace, normalized_name) -> canonical value
        self._names: dict[tuple[NamespaceKind, str], str] = {}
        self._frozen = False

        for binding in sorted(
            bindings or (),
            key=lambda item: (item.namespace.value, item.value),
        ):
            self.register_binding(binding)
        if frozen:
            self.freeze()

    @property
    def frozen(self) -> bool:
        return self._frozen

    def freeze(self) -> "LogicIdentityNamespaces":
        """Prevent further registration and return this catalog."""

        self._frozen = True
        return self

    def _require_mutable(self) -> None:
        if self._frozen:
            raise FrozenNamespaceError("logic identity namespaces are frozen")

    def register(
        self,
        namespace: NamespaceKind | str,
        value: str,
        *,
        aliases: Sequence[str] | None = None,
        version: str = IDENTITY_VERSION,
        name: str = "",
        description: str = "",
    ) -> NamespaceBinding:
        """Register a canonical identity and optional aliases."""

        binding = NamespaceBinding(
            identity=identity_for(namespace, value, version=version),
            aliases=tuple(aliases or ()),
            name=name,
            description=description,
        )
        return self.register_binding(binding)

    def register_binding(self, binding: NamespaceBinding) -> NamespaceBinding:
        """Insert a fully formed binding, rejecting alias collisions."""

        if not isinstance(binding, NamespaceBinding):
            raise TypeError("binding must be a NamespaceBinding")
        self._require_mutable()
        key = (binding.namespace, binding.value)
        if key in self._bindings:
            raise AliasCollisionError(
                f"{binding.identity.qualified!r} is already registered"
            )

        claimed = (binding.value, *binding.aliases)
        pending: list[tuple[tuple[NamespaceKind, str], str]] = []
        pending_keys: set[tuple[NamespaceKind, str]] = set()
        for claim in claimed:
            normalized = normalize_identity_name(claim)
            owner_key = (binding.namespace, normalized)
            owner = self._names.get(owner_key)
            if owner is not None or owner_key in pending_keys:
                raise AliasCollisionError(
                    f"name {claim!r} in namespace {binding.namespace.value!r} "
                    f"collides with registered identity "
                    f"{owner if owner is not None else binding.value!r}"
                )
            pending_keys.add(owner_key)
            pending.append((owner_key, binding.value))

        self._bindings[key] = binding
        for owner_key, canonical in pending:
            self._names[owner_key] = canonical
        return binding

    def get(
        self,
        namespace: NamespaceKind | str,
        value: str,
    ) -> NamespaceBinding:
        """Return the binding for a canonical value (not an alias)."""

        kind = _coerce_namespace(namespace)
        try:
            return self._bindings[(kind, validate_identifier(value, "value"))]
        except KeyError as error:
            raise UnknownIdentityError(
                f"unknown identity {kind.value}:{value}"
            ) from error

    def resolve(
        self,
        namespace: NamespaceKind | str,
        name: str,
    ) -> LogicIdentity:
        """Resolve a canonical id or alias within *namespace* only."""

        kind = _coerce_namespace(namespace)
        if not isinstance(name, str) or not name.strip():
            raise InvalidIdentifierError("resolve name must be a non-empty string")
        normalized = normalize_identity_name(name)
        canonical = self._names.get((kind, normalized))
        if canonical is None:
            raise UnknownIdentityError(
                f"unknown identity {kind.value}:{name}"
            )
        return self._bindings[(kind, canonical)].identity

    def contains(
        self,
        namespace: NamespaceKind | str,
        name: str,
    ) -> bool:
        """Return whether *name* resolves in *namespace*."""

        try:
            self.resolve(namespace, name)
        except (UnknownIdentityError, InvalidIdentifierError):
            return False
        return True

    def identities(
        self,
        namespace: NamespaceKind | str | None = None,
    ) -> tuple[LogicIdentity, ...]:
        """Return registered identities, optionally filtered by namespace."""

        if namespace is None:
            items = sorted(
                self._bindings.values(),
                key=lambda item: (item.namespace.value, item.value),
            )
            return tuple(item.identity for item in items)
        kind = _coerce_namespace(namespace)
        items = sorted(
            (
                binding
                for binding in self._bindings.values()
                if binding.namespace is kind
            ),
            key=lambda item: item.value,
        )
        return tuple(item.identity for item in items)

    def bindings(
        self,
        namespace: NamespaceKind | str | None = None,
    ) -> tuple[NamespaceBinding, ...]:
        """Return registered bindings in deterministic order."""

        if namespace is None:
            items = sorted(
                self._bindings.values(),
                key=lambda item: (item.namespace.value, item.value),
            )
            return tuple(items)
        kind = _coerce_namespace(namespace)
        items = sorted(
            (
                binding
                for binding in self._bindings.values()
                if binding.namespace is kind
            ),
            key=lambda item: item.value,
        )
        return tuple(items)

    def __iter__(self) -> Iterator[NamespaceBinding]:
        return iter(self.bindings())

    def __len__(self) -> int:
        return len(self._bindings)

    def __contains__(self, item: object) -> bool:
        if isinstance(item, LogicIdentity):
            return (item.namespace, item.value) in self._bindings
        if isinstance(item, NamespaceBinding):
            existing = self._bindings.get((item.namespace, item.value))
            return existing == item
        return False

    def require_identity(
        self,
        identity: LogicIdentity,
        namespace: NamespaceKind | str | None = None,
    ) -> LogicIdentity:
        """Validate *identity* is registered and occupies the expected role."""

        if not isinstance(identity, LogicIdentity):
            raise CrossNamespaceCoercionError(
                f"expected LogicIdentity, got {type(identity).__name__}"
            )
        if namespace is not None:
            identity = identity.require(namespace)
        if (identity.namespace, identity.value) not in self._bindings:
            raise UnknownIdentityError(
                f"unknown identity {identity.qualified}"
            )
        registered = self._bindings[(identity.namespace, identity.value)].identity
        if registered.version != identity.version:
            raise SchemaVersionError(
                f"identity version mismatch for {identity.qualified}: "
                f"registered {registered.version!r}, got {identity.version!r}"
            )
        return registered

    def coerce(
        self,
        identity: LogicIdentity,
        namespace: NamespaceKind | str,
    ) -> LogicIdentity:
        """Fail-closed coercion that also requires registration."""

        coerced = coerce_identity(identity, namespace)
        return self.require_identity(coerced, namespace)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full catalog with deterministic ordering."""

        return {
            "bindings": [binding.to_dict() for binding in self.bindings()],
            "interface": self.interface,
            "schema_version": self.schema_version,
            "version": self.version,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        """Deterministic JSON for the full catalog."""

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
        frozen: bool = False,
    ) -> "LogicIdentityNamespaces":
        """Parse a catalog payload, preserving schema and version."""

        if not isinstance(payload, Mapping):
            raise InvalidIdentifierError("namespace catalog must be a mapping")
        schema = payload.get("schema_version")
        if schema != NAMESPACE_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported or missing schema_version: {schema!r}"
            )
        interface = payload.get("interface")
        if interface is not None and interface != NAMESPACE_INTERFACE:
            raise SchemaVersionError(f"unsupported interface: {interface!r}")
        raw_bindings = payload.get("bindings", ())
        if isinstance(raw_bindings, (str, bytes, bytearray)) or not isinstance(
            raw_bindings, Sequence
        ):
            raise InvalidIdentifierError("bindings must be a sequence")
        bindings = tuple(
            NamespaceBinding.from_dict(item) for item in raw_bindings
        )
        return cls(
            bindings=bindings,
            version=payload.get("version", NAMESPACE_MODULE_VERSION),
            frozen=frozen,
        )

    @classmethod
    def parse(
        cls,
        payload: Mapping[str, Any] | str,
        *,
        frozen: bool = False,
    ) -> "LogicIdentityNamespaces":
        """Parse a mapping or JSON string into a catalog."""

        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError as error:
                raise InvalidIdentifierError(
                    f"namespace catalog JSON is not valid: {error.msg}"
                ) from error
            if not isinstance(decoded, Mapping):
                raise InvalidIdentifierError(
                    "namespace catalog JSON must decode to an object"
                )
            return cls.from_dict(decoded, frozen=frozen)
        return cls.from_dict(payload, frozen=frozen)


def build_baseline_namespaces(*, frozen: bool = True) -> LogicIdentityNamespaces:
    """Build the reviewed baseline identity bindings for taxonomy work.

    This catalog records the plan-level separation of roles.  It does not
    replace the family registry; join tasks attach descriptors later.
    """

    catalog = LogicIdentityNamespaces(version=NAMESPACE_MODULE_VERSION)

    # Semantic families (canonical baseline from the plan).
    families = (
        ("authorization", ("secpal_family",), "Authorization"),
        ("concurrency", (), "Concurrency"),
        ("cryptographic_protocol", ("protocol_family",), "Cryptographic protocol"),
        ("datalog", (), "Datalog"),
        ("dcec", (), "DCEC"),
        ("deontic", (), "Deontic"),
        ("event_calculus", (), "Event calculus"),
        ("first_order", ("fol", "predicate_logic"), "First-order"),
        ("frame_logic", (), "Frame logic"),
        ("higher_order", (), "Higher-order"),
        ("horn_chc", ("chc", "horn"), "Horn/CHC"),
        ("hyperproperty", (), "Hyperproperty"),
        ("modal", (), "Modal"),
        ("mu_calculus", (), "Mu-calculus"),
        ("program", (), "Program"),
        ("propositional", (), "Propositional"),
        ("refinement", (), "Refinement"),
        ("separation_logic", (), "Separation logic"),
        ("tdfol", (), "Temporal deontic FOL"),
        ("temporal", (), "Temporal"),
        ("transition_system", ("state_transition",), "Transition system"),
    )
    for value, aliases, name in families:
        catalog.register(
            NamespaceKind.FAMILY,
            value,
            aliases=aliases,
            name=name,
        )

    # Profiles / fragments (not families).
    profiles = (
        ("hyperltl", ("hyper_ltl",), "HyperLTL"),
        ("qf_bv", (), "QF_BV"),
        ("s4", (), "S4"),
        ("s5", (), "S5"),
        ("secpal", ("secpal_style",), "SecPAL"),
        ("tla_plus", ("tla+",), "TLA+"),
        ("temporal_first_order", ("first_order_temporal",), "Temporal first-order"),
    )
    for value, aliases, name in profiles:
        catalog.register(NamespaceKind.PROFILE, value, aliases=aliases, name=name)

    # Property / obligation kinds.
    properties = (
        ("liveness", (), "Liveness"),
        ("noninterference", (), "Noninterference"),
        ("reachability", (), "Reachability"),
        ("safety", (), "Safety"),
        ("satisfiability", (), "Satisfiability"),
        ("secrecy", (), "Secrecy"),
        ("termination", (), "Termination"),
        ("validity", (), "Validity"),
    )
    for value, aliases, name in properties:
        catalog.register(NamespaceKind.PROPERTY, value, aliases=aliases, name=name)

    # View roles.
    views = (
        ("graph_projection", (), "Graph projection"),
        ("normalized", (), "Normalized"),
        ("proof_translation", (), "Proof translation"),
        ("source", (), "Source"),
        ("verification_condition", ("vc",), "Verification condition"),
    )
    for value, aliases, name in views:
        catalog.register(NamespaceKind.VIEW, value, aliases=aliases, name=name)

    # Notation / source syntax.
    notations = (
        ("canonical_text", (), "Canonical text"),
        ("smt_lib2", ("smt", "smtlib2", "smt_lib"), "SMT-LIB2"),
        ("tamarin_spthy", ("spthy",), "Tamarin spthy"),
        ("tla_plus_source", ("tla",), "TLA+ source"),
        ("tptp_fof", ("tptp",), "TPTP FOF"),
        ("proverif_pv", ("pv",), "ProVerif pv"),
    )
    for value, aliases, name in notations:
        catalog.register(NamespaceKind.NOTATION, value, aliases=aliases, name=name)

    # Target encodings (separate from source notation).
    encodings = (
        ("isabelle_hol", (), "Isabelle/HOL"),
        ("lean4", (), "Lean 4"),
        ("rocq", (), "Rocq"),
        ("smt_lib2", (), "SMT-LIB2 target"),
        ("tptp_tff", (), "TPTP TFF"),
    )
    for value, aliases, name in encodings:
        catalog.register(NamespaceKind.ENCODING, value, aliases=aliases, name=name)

    # Providers (tools, never families).
    providers = (
        ("cvc5", (), "cvc5"),
        ("isabelle", (), "Isabelle"),
        ("lean", ("lean4_provider",), "Lean"),
        ("proverif", (), "ProVerif"),
        ("rocq", ("coq", "coqc"), "Rocq"),
        ("tamarin", (), "Tamarin"),
        ("tla_tlc", ("tlc",), "TLA TLC"),
        ("z3", (), "Z3"),
    )
    for value, aliases, name in providers:
        catalog.register(NamespaceKind.PROVIDER, value, aliases=aliases, name=name)

    # Execution lanes.
    lanes = (
        ("advisor", (), "Advisor"),
        ("atp", (), "ATP"),
        ("itp_kernel", ("kernel",), "ITP kernel"),
        ("runtime_monitor", ("runtime",), "Runtime monitor"),
        ("smt", ("smt_lane",), "SMT"),
        ("state_model", (), "State model"),
    )
    for value, aliases, name in lanes:
        catalog.register(NamespaceKind.LANE, value, aliases=aliases, name=name)

    # Evidence kinds.
    evidence = (
        ("attestation", (), "Attestation"),
        ("candidate", (), "Candidate"),
        ("checked_proof", (), "Checked proof"),
        ("counterexample", (), "Counterexample"),
        ("kernel_checked_proof", (), "Kernel-checked proof"),
        ("model", (), "Model"),
        ("monitor_verdict", (), "Monitor verdict"),
        ("trace", (), "Trace"),
    )
    for value, aliases, name in evidence:
        catalog.register(NamespaceKind.EVIDENCE, value, aliases=aliases, name=name)

    if frozen:
        catalog.freeze()
    return catalog


BASELINE_NAMESPACES: Final[LogicIdentityNamespaces] = build_baseline_namespaces(
    frozen=True
)


__all__ = [
    "BASELINE_NAMESPACES",
    "CANONICAL_NAMESPACE_KINDS",
    "IDENTITY_VERSION",
    "AliasCollisionError",
    "CrossNamespaceCoercionError",
    "FrozenNamespaceError",
    "InvalidIdentifierError",
    "LogicIdentity",
    "LogicIdentityNamespaces",
    "NAMESPACE_INTERFACE",
    "NAMESPACE_MODULE_VERSION",
    "NAMESPACE_SCHEMA_VERSION",
    "NamespaceBinding",
    "NamespaceError",
    "NamespaceKind",
    "SchemaVersionError",
    "UnknownIdentityError",
    "build_baseline_namespaces",
    "coerce_identity",
    "encoding_id",
    "evidence_id",
    "family_id",
    "identity_for",
    "lane_id",
    "normalize_identity_name",
    "notation_id",
    "profile_id",
    "property_id",
    "provider_id",
    "validate_identifier",
    "validate_version",
    "view_id",
]

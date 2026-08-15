"""Deterministic mutation operator registry and dispatch (AAE-014).

Interface: ``MutationOperatorRegistry@1``

The registry is the sole admission surface for operator declarations used by
mutation generation. Assembly is fail-closed:

* duplicate ``(operator_id, operator_version)`` or ``operator_cid`` rejected;
* versionless declarations rejected;
* unbounded / non-deterministic / sandbox-unsafe operators rejected;
* declarations are canonicalized before storage;
* dispatch returns only operators that support the given target;
* rollback records are content-addressed and deterministic for identical inputs.

The registry never mutates production worktrees, never grants assurance
authority, and does not open a network store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MAX_OPERATORS,
    MutationContractError,
    MutationOperatorDefinition,
    MutationTarget,
    OperatorClass,
    assert_operator_supports_target,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.base import (
    DeclarationBackedOperator,
    MutationOperator,
    OperatorBaseError,
    OperatorBoundError,
    OperatorDeclarationError,
    OperatorRollbackRecord,
    RegisteredOperator,
    assert_operator_bounded,
    canonicalize_operator_declaration,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

MUTATION_OPERATOR_REGISTRY_INTERFACE: Final[str] = "MutationOperatorRegistry@1"
MUTATION_OPERATOR_REGISTRY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-operator-registry@1"
)
MUTATION_OPERATOR_REGISTRY_VERSION: Final[str] = "1"
MUTATION_OPERATOR_REGISTRY_PRODUCER: Final[str] = (
    "adversarial-assurance.mutation-operator-registry@1"
)

MAX_REGISTRY_OPERATORS: Final[int] = MAX_OPERATORS


class OperatorRegistryError(AssuranceBaseError):
    """Raised when registry assembly, lookup, or dispatch fails closed."""


class DuplicateOperatorError(OperatorRegistryError):
    """Raised when a duplicate operator id/version or CID is registered."""


class UnknownOperatorError(OperatorRegistryError):
    """Raised when a requested operator is not present in the registry."""


class UnsupportedTargetError(OperatorRegistryError):
    """Raised when no registered operator supports the requested target."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise OperatorRegistryError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise OperatorRegistryError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return dict(data)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise OperatorRegistryError(f"{name} must be a nonempty string")
    if value != value.strip():
        raise OperatorRegistryError(f"{name} must be trimmed text")
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_structured(item) for item in value]
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise OperatorRegistryError(f"{name} must be a mapping")
    payload = _thaw_structured(dict(value))
    try:
        cid_for_structured(payload)
    except Exception as exc:  # noqa: BLE001
        raise OperatorRegistryError(f"{name} must be DAG-JSON structured data") from exc
    try:
        reject_private_model_authority_and_host_fallbacks(payload, path=name)
    except AssuranceBaseError as exc:
        raise OperatorRegistryError(str(exc)) from exc
    return MappingProxyType(dict(payload))


def _operator_sort_key(operator: MutationOperatorDefinition) -> tuple[str, str, str]:
    return (operator.operator_id, operator.operator_version, operator.operator_cid)


def _normalize_operator_class(
    value: OperatorClass | str | None,
) -> str | None:
    if value is None:
        return None
    if isinstance(value, OperatorClass):
        return value.value
    if type(value) is not str or not value:
        raise OperatorRegistryError("operator_class must be a nonempty string")
    try:
        return OperatorClass(value).value
    except ValueError as exc:
        raise OperatorRegistryError(
            f"unsupported operator_class: {value!r}"
        ) from exc


def _definition_from_input(
    declaration: MutationOperatorDefinition
    | MutationOperator
    | Mapping[str, Any]
    | RegisteredOperator,
) -> MutationOperatorDefinition:
    if isinstance(declaration, RegisteredOperator):
        return declaration.definition
    if isinstance(declaration, MutationOperator):
        return declaration.sealed_definition()
    try:
        return canonicalize_operator_declaration(declaration)
    except (OperatorDeclarationError, OperatorBoundError, OperatorBaseError) as exc:
        raise OperatorRegistryError(str(exc)) from exc
    except MutationContractError as exc:
        raise OperatorRegistryError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Builder (mutable assembly surface)
# ---------------------------------------------------------------------------


class MutationOperatorRegistryBuilder:
    """Mutable fail-closed assembly surface for ``MutationOperatorRegistry@1``.

    Call :meth:`register` zero or more times, then :meth:`build` to obtain the
    immutable catalogue. The builder never mutates an already-built registry.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], MutationOperatorDefinition] = {}
        self._by_cid: dict[str, MutationOperatorDefinition] = {}
        self._order: list[tuple[str, str]] = []

    def __len__(self) -> int:
        return len(self._order)

    def register(
        self,
        declaration: MutationOperatorDefinition
        | MutationOperator
        | Mapping[str, Any]
        | RegisteredOperator,
    ) -> MutationOperatorDefinition:
        """Canonicalize and admit one operator declaration.

        Rejects duplicates, versionless, and unbounded operators. Returns the
        sealed canonical definition that will appear in the built registry.
        """

        if len(self._order) >= MAX_REGISTRY_OPERATORS:
            raise OperatorRegistryError(
                f"registry exceeds maximum operator count ({MAX_REGISTRY_OPERATORS})"
            )

        sealed = _definition_from_input(declaration)
        # Explicit versionless / unbounded gates (defense in depth).
        if not sealed.operator_version or not str(sealed.operator_version).strip():
            raise OperatorRegistryError(
                "registry rejects versionless operators; operator_version required"
            )
        try:
            assert_operator_bounded(sealed)
        except OperatorBoundError as exc:
            raise OperatorRegistryError(str(exc)) from exc

        key = (sealed.operator_id, sealed.operator_version)
        if key in self._by_key:
            raise DuplicateOperatorError(
                "duplicate operator registration for "
                f"{sealed.operator_id}@{sealed.operator_version}"
            )
        if sealed.operator_cid in self._by_cid:
            existing = self._by_cid[sealed.operator_cid]
            raise DuplicateOperatorError(
                "duplicate operator_cid registration: "
                f"{sealed.operator_cid} already bound to "
                f"{existing.operator_id}@{existing.operator_version}"
            )

        self._by_key[key] = sealed
        self._by_cid[sealed.operator_cid] = sealed
        self._order.append(key)
        return sealed

    def register_many(
        self,
        declarations: Iterable[
            MutationOperatorDefinition
            | MutationOperator
            | Mapping[str, Any]
            | RegisteredOperator
        ],
    ) -> tuple[MutationOperatorDefinition, ...]:
        """Register multiple declarations in iteration order."""

        sealed: list[MutationOperatorDefinition] = []
        for item in declarations:
            sealed.append(self.register(item))
        return tuple(sealed)

    def build(
        self,
        *,
        producer_id: str = MUTATION_OPERATOR_REGISTRY_PRODUCER,
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "MutationOperatorRegistry":
        """Freeze the admitted operators into an immutable registry."""

        # Deterministic catalogue order: id, version, cid — not insertion order.
        operators = tuple(
            sorted(self._by_key.values(), key=_operator_sort_key)
        )
        return MutationOperatorRegistry(
            operators=operators,
            producer_id=producer_id,
            notes=notes,
            metadata=metadata or {},
        )


# ---------------------------------------------------------------------------
# Immutable registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationOperatorRegistry:
    """Immutable catalogue of sealed, bounded mutation operators.

    Interface: ``MutationOperatorRegistry@1``
    """

    operators: Sequence[MutationOperatorDefinition]
    producer_id: str = MUTATION_OPERATOR_REGISTRY_PRODUCER
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    registry_id: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "registry_version",
            "operators",
            "producer_id",
            "notes",
            "metadata",
            "registry_id",
            "operator_cids",
            "operator_count",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.operators, Sequence) or isinstance(
            self.operators, (str, bytes)
        ):
            raise OperatorRegistryError("operators must be a sequence of definitions")
        raw = list(self.operators)
        if len(raw) > MAX_REGISTRY_OPERATORS:
            raise OperatorRegistryError(
                f"registry exceeds maximum operator count ({MAX_REGISTRY_OPERATORS})"
            )

        sealed: list[MutationOperatorDefinition] = []
        seen_keys: set[tuple[str, str]] = set()
        seen_cids: set[str] = set()
        for item in raw:
            if not isinstance(item, MutationOperatorDefinition):
                try:
                    definition = canonicalize_operator_declaration(item)
                except (OperatorDeclarationError, OperatorBoundError, OperatorBaseError) as exc:
                    raise OperatorRegistryError(str(exc)) from exc
            else:
                try:
                    definition = canonicalize_operator_declaration(item)
                except (OperatorDeclarationError, OperatorBoundError, OperatorBaseError) as exc:
                    raise OperatorRegistryError(str(exc)) from exc

            if not definition.operator_version or not str(
                definition.operator_version
            ).strip():
                raise OperatorRegistryError(
                    "registry rejects versionless operators; operator_version required"
                )
            try:
                assert_operator_bounded(definition)
            except OperatorBoundError as exc:
                raise OperatorRegistryError(str(exc)) from exc

            key = (definition.operator_id, definition.operator_version)
            if key in seen_keys:
                raise DuplicateOperatorError(
                    "duplicate operator registration for "
                    f"{definition.operator_id}@{definition.operator_version}"
                )
            if definition.operator_cid in seen_cids:
                raise DuplicateOperatorError(
                    f"duplicate operator_cid registration: {definition.operator_cid}"
                )
            seen_keys.add(key)
            seen_cids.add(definition.operator_cid)
            sealed.append(definition)

        ordered = tuple(sorted(sealed, key=_operator_sort_key))
        object.__setattr__(self, "operators", ordered)
        object.__setattr__(
            self, "producer_id", _text(self.producer_id, "producer_id")
        )
        if self.notes is not None:
            object.__setattr__(self, "notes", _text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        computed = cid_for_structured(self._identity_payload_without_registry_id())
        if self.registry_id is None:
            object.__setattr__(self, "registry_id", computed)
        else:
            claimed = _text(self.registry_id, "registry_id")
            if claimed != computed:
                raise OperatorRegistryError(
                    "registry_id identity mismatch with recomputed catalogue identity"
                )
            object.__setattr__(self, "registry_id", claimed)

    # -- identity ------------------------------------------------------------

    def _identity_payload_without_registry_id(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_OPERATOR_REGISTRY_SCHEMA,
            "interface_id": MUTATION_OPERATOR_REGISTRY_INTERFACE,
            "registry_version": MUTATION_OPERATOR_REGISTRY_VERSION,
            "operators": [item.identity_payload() for item in self.operators],
            "producer_id": self.producer_id,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "operator_cids": [item.operator_cid for item in self.operators],
            "operator_count": len(self.operators),
        }

    def identity_payload(self) -> dict[str, Any]:
        payload = self._identity_payload_without_registry_id()
        payload["registry_id"] = self.registry_id
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_OPERATOR_REGISTRY_SCHEMA,
            "interface_id": MUTATION_OPERATOR_REGISTRY_INTERFACE,
            "registry_version": MUTATION_OPERATOR_REGISTRY_VERSION,
            "operators": [item.to_dict() for item in self.operators],
            "producer_id": self.producer_id,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "operator_cids": [item.operator_cid for item in self.operators],
            "operator_count": len(self.operators),
            "registry_id": self.registry_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationOperatorRegistry":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != MUTATION_OPERATOR_REGISTRY_SCHEMA:
            raise OperatorRegistryError(
                "unsupported MutationOperatorRegistry schema version"
            )
        if payload.pop("interface_id") != MUTATION_OPERATOR_REGISTRY_INTERFACE:
            raise OperatorRegistryError(
                "unsupported MutationOperatorRegistry interface_id"
            )
        version = payload.pop("registry_version", MUTATION_OPERATOR_REGISTRY_VERSION)
        if version != MUTATION_OPERATOR_REGISTRY_VERSION:
            raise OperatorRegistryError(
                "unsupported MutationOperatorRegistry registry_version"
            )
        payload.pop("operator_cids", None)
        payload.pop("operator_count", None)
        operators_raw = payload["operators"]
        if not isinstance(operators_raw, list):
            raise OperatorRegistryError("operators must be a list")
        operators: list[MutationOperatorDefinition] = []
        for item in operators_raw:
            if isinstance(item, MutationOperatorDefinition):
                operators.append(item)
            elif isinstance(item, Mapping):
                operators.append(MutationOperatorDefinition.from_dict(item))
            else:
                raise OperatorRegistryError(
                    "operators entries must be MutationOperatorDefinition or mapping"
                )
        return cls(
            operators=operators,
            producer_id=payload.get(
                "producer_id", MUTATION_OPERATOR_REGISTRY_PRODUCER
            ),
            notes=payload.get("notes"),
            metadata=payload.get("metadata") or {},
            registry_id=payload.get("registry_id"),
        )

    @classmethod
    def from_operators(
        cls,
        declarations: Iterable[
            MutationOperatorDefinition
            | MutationOperator
            | Mapping[str, Any]
            | RegisteredOperator
        ],
        *,
        producer_id: str = MUTATION_OPERATOR_REGISTRY_PRODUCER,
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "MutationOperatorRegistry":
        """Build a registry from an iterable of declarations (fail-closed)."""

        builder = MutationOperatorRegistryBuilder()
        builder.register_many(declarations)
        return builder.build(
            producer_id=producer_id,
            notes=notes,
            metadata=metadata,
        )

    @classmethod
    def empty(
        cls,
        *,
        producer_id: str = MUTATION_OPERATOR_REGISTRY_PRODUCER,
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "MutationOperatorRegistry":
        """Return an empty sealed registry catalogue."""

        return cls(
            operators=(),
            producer_id=producer_id,
            notes=notes,
            metadata=metadata or {},
        )

    # -- catalogue views -----------------------------------------------------

    def __len__(self) -> int:
        return len(self.operators)

    def __iter__(self):
        return iter(self.operators)

    def __contains__(self, item: object) -> bool:
        if isinstance(item, MutationOperatorDefinition):
            return item.operator_cid in self.operator_cids()
        if type(item) is str:
            return item in self.operator_cids() or any(
                op.operator_id == item for op in self.operators
            )
        return False

    def operator_cids(self) -> tuple[str, ...]:
        return tuple(item.operator_cid for item in self.operators)

    def operator_ids(self) -> tuple[str, ...]:
        return tuple(item.operator_id for item in self.operators)

    def list_operators(self) -> tuple[MutationOperatorDefinition, ...]:
        """Return the sealed catalogue in deterministic order."""

        return tuple(self.operators)

    def registered_operators(self) -> tuple[RegisteredOperator, ...]:
        """Return registration bindings with stable registration indices."""

        return tuple(
            RegisteredOperator(
                operator_id=item.operator_id,
                operator_version=item.operator_version,
                operator_class=item.operator_class,
                operator_cid=item.operator_cid,
                definition=item,
                registration_index=index,
            )
            for index, item in enumerate(self.operators)
        )

    def as_mutation_operators(self) -> tuple[DeclarationBackedOperator, ...]:
        """Return declaration-backed operator handles for each catalogue entry."""

        return tuple(
            DeclarationBackedOperator(_definition=item) for item in self.operators
        )

    # -- lookup --------------------------------------------------------------

    def get(
        self,
        operator_id: str,
        operator_version: str | None = None,
    ) -> MutationOperatorDefinition:
        """Return the sealed operator for an id (and optional version).

        When ``operator_version`` is omitted and multiple versions are
        registered for the same id, fails closed.
        """

        operator_id = _text(operator_id, "operator_id")
        matches = [
            item for item in self.operators if item.operator_id == operator_id
        ]
        if not matches:
            raise UnknownOperatorError(
                f"unknown operator_id: {operator_id}"
            )
        if operator_version is None:
            if len(matches) != 1:
                versions = ", ".join(
                    sorted({item.operator_version for item in matches})
                )
                raise OperatorRegistryError(
                    f"operator_id {operator_id} is ambiguous across versions "
                    f"({versions}); provide operator_version"
                )
            return matches[0]
        operator_version = _text(operator_version, "operator_version")
        for item in matches:
            if item.operator_version == operator_version:
                return item
        raise UnknownOperatorError(
            f"unknown operator: {operator_id}@{operator_version}"
        )

    def get_by_cid(self, operator_cid: str) -> MutationOperatorDefinition:
        """Return the sealed operator for a content identity."""

        operator_cid = _text(operator_cid, "operator_cid")
        for item in self.operators:
            if item.operator_cid == operator_cid:
                return item
        raise UnknownOperatorError(f"unknown operator_cid: {operator_cid}")

    def get_versions(self, operator_id: str) -> tuple[MutationOperatorDefinition, ...]:
        """Return every registered version of an operator id (sorted)."""

        operator_id = _text(operator_id, "operator_id")
        matches = tuple(
            item for item in self.operators if item.operator_id == operator_id
        )
        if not matches:
            raise UnknownOperatorError(f"unknown operator_id: {operator_id}")
        return matches

    # -- dispatch ------------------------------------------------------------

    def operators_for_target(
        self,
        target: MutationTarget,
        *,
        operator_class: OperatorClass | str | None = None,
        operator_id: str | None = None,
        operator_version: str | None = None,
    ) -> tuple[MutationOperatorDefinition, ...]:
        """Return operators that support ``target`` under optional filters.

        Never returns unsupported operators. Empty support set is a normal
        result (use :meth:`dispatch` to fail closed when none match).
        """

        if not isinstance(target, MutationTarget):
            raise OperatorRegistryError("target must be a MutationTarget")
        class_filter = _normalize_operator_class(operator_class)
        id_filter = None if operator_id is None else _text(operator_id, "operator_id")
        version_filter = (
            None
            if operator_version is None
            else _text(operator_version, "operator_version")
        )

        selected: list[MutationOperatorDefinition] = []
        for item in self.operators:
            if id_filter is not None and item.operator_id != id_filter:
                continue
            if version_filter is not None and item.operator_version != version_filter:
                continue
            if class_filter is not None and item.operator_class != class_filter:
                continue
            if item.supports_target(target):
                selected.append(item)
        return tuple(selected)

    def dispatch(
        self,
        target: MutationTarget,
        *,
        operator_class: OperatorClass | str | None = None,
        operator_id: str | None = None,
        operator_version: str | None = None,
        require_nonempty: bool = True,
    ) -> tuple[MutationOperatorDefinition, ...]:
        """Dispatch only operators that support the target (fail-closed).

        When ``require_nonempty`` is true (default), raises
        :class:`UnsupportedTargetError` if the filtered support set is empty.
        Explicit ``operator_id``/``operator_version`` that does not support the
        target also fails closed.
        """

        if not isinstance(target, MutationTarget):
            raise OperatorRegistryError("target must be a MutationTarget")

        # Explicit lookup first so unsupported-but-registered operators fail
        # with a clear contract error rather than silent omission.
        if operator_id is not None:
            operator = self.get(operator_id, operator_version)
            class_filter = _normalize_operator_class(operator_class)
            if class_filter is not None and operator.operator_class != class_filter:
                raise OperatorRegistryError(
                    f"operator {operator.operator_id}@{operator.operator_version} "
                    f"class {operator.operator_class} does not match requested "
                    f"operator_class {class_filter}"
                )
            try:
                assert_operator_supports_target(operator, target)
            except MutationContractError as exc:
                raise UnsupportedTargetError(str(exc)) from exc
            return (operator,)

        matches = self.operators_for_target(
            target,
            operator_class=operator_class,
            operator_version=operator_version,
        )
        if require_nonempty and not matches:
            raise UnsupportedTargetError(
                "no registered operator supports the requested target under "
                "the given filters"
            )
        return matches

    def dispatch_one(
        self,
        target: MutationTarget,
        *,
        operator_class: OperatorClass | str | None = None,
        operator_id: str | None = None,
        operator_version: str | None = None,
    ) -> MutationOperatorDefinition:
        """Dispatch exactly one supporting operator; fail on zero or many."""

        matches = self.dispatch(
            target,
            operator_class=operator_class,
            operator_id=operator_id,
            operator_version=operator_version,
            require_nonempty=True,
        )
        if len(matches) != 1:
            ids = ", ".join(
                f"{item.operator_id}@{item.operator_version}" for item in matches
            )
            raise OperatorRegistryError(
                f"dispatch_one requires exactly one supporting operator; "
                f"matched: {ids or '(none)'}"
            )
        return matches[0]

    # -- rollback records ----------------------------------------------------

    def rollback_record(
        self,
        operator_id: str,
        *,
        pre_mutation_state_cid: str,
        operator_version: str | None = None,
        target: MutationTarget | None = None,
        source_root_cid: str | None = None,
        scope_paths: Sequence[str] = (),
        scope_symbol_ids: Sequence[str] = (),
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> OperatorRollbackRecord:
        """Produce a deterministic rollback record for a registered operator.

        When ``target`` is supplied, the operator must support it (fail-closed).
        """

        operator = self.get(operator_id, operator_version)
        if target is not None:
            try:
                assert_operator_supports_target(operator, target)
            except MutationContractError as exc:
                raise UnsupportedTargetError(str(exc)) from exc
        try:
            return OperatorRollbackRecord.from_operator(
                operator,
                pre_mutation_state_cid=pre_mutation_state_cid,
                target=target,
                source_root_cid=source_root_cid,
                scope_paths=scope_paths,
                scope_symbol_ids=scope_symbol_ids,
                notes=notes,
                metadata=metadata,
            )
        except OperatorBaseError as exc:
            raise OperatorRegistryError(str(exc)) from exc

    def rollback_record_for_definition(
        self,
        operator: MutationOperatorDefinition,
        *,
        pre_mutation_state_cid: str,
        target: MutationTarget | None = None,
        source_root_cid: str | None = None,
        scope_paths: Sequence[str] = (),
        scope_symbol_ids: Sequence[str] = (),
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> OperatorRollbackRecord:
        """Produce a rollback record after verifying the definition is registered."""

        if not isinstance(operator, MutationOperatorDefinition):
            raise OperatorRegistryError(
                "operator must be a sealed MutationOperatorDefinition"
            )
        registered = self.get_by_cid(operator.operator_cid)
        if registered.operator_cid != operator.operator_cid:
            raise UnknownOperatorError(
                "operator is not admitted by this registry"
            )
        return self.rollback_record(
            registered.operator_id,
            operator_version=registered.operator_version,
            pre_mutation_state_cid=pre_mutation_state_cid,
            target=target,
            source_root_cid=source_root_cid,
            scope_paths=scope_paths,
            scope_symbol_ids=scope_symbol_ids,
            notes=notes,
            metadata=metadata,
        )


def build_mutation_operator_registry(
    declarations: Iterable[
        MutationOperatorDefinition
        | MutationOperator
        | Mapping[str, Any]
        | RegisteredOperator
    ] = (),
    *,
    producer_id: str = MUTATION_OPERATOR_REGISTRY_PRODUCER,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MutationOperatorRegistry:
    """Convenience constructor for a sealed ``MutationOperatorRegistry@1``."""

    return MutationOperatorRegistry.from_operators(
        declarations,
        producer_id=producer_id,
        notes=notes,
        metadata=metadata,
    )


__all__ = [
    "MAX_REGISTRY_OPERATORS",
    "MUTATION_OPERATOR_REGISTRY_INTERFACE",
    "MUTATION_OPERATOR_REGISTRY_PRODUCER",
    "MUTATION_OPERATOR_REGISTRY_SCHEMA",
    "MUTATION_OPERATOR_REGISTRY_VERSION",
    "DuplicateOperatorError",
    "MutationOperatorRegistry",
    "MutationOperatorRegistryBuilder",
    "OperatorRegistryError",
    "UnknownOperatorError",
    "UnsupportedTargetError",
    "build_mutation_operator_registry",
]

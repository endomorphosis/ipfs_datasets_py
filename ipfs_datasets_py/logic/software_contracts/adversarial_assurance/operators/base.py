"""Base types for deterministic mutation operators and rollback records (AAE-014).

Defines the closed runtime contracts that every registered operator must
satisfy before admission into ``MutationOperatorRegistry@1``:

* Canonical declarations bind a sealed ``MutationOperatorDefinition@1``.
* Operators are bounded, deterministic, sandbox-isolated, and rollback-safe.
* Rollback records are content-addressed and byte-for-byte deterministic for
  identical inputs (operator, target, pre-mutation state, strategy).

This module does not open a store, mutate production worktrees, or grant
assurance-authority. Generation callables live in later operator-class tasks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MAX_MUTANTS_PER_TARGET,
    MAX_OPERATORS,
    MUTATION_OPERATOR_DEFINITION_INTERFACE,
    MUTATION_OPERATOR_DEFINITION_SCHEMA,
    MutationContractError,
    MutationOperatorDefinition,
    MutationTarget,
    RollbackDeclaration,
    RollbackStrategy,
    ScopeLimits,
    assert_operator_supports_target,
    verify_operator_identity,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

OPERATOR_BASE_INTERFACE: Final[str] = "MutationOperatorBase@1"
ROLLBACK_RECORD_INTERFACE: Final[str] = "OperatorRollbackRecord@1"
ROLLBACK_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-operator-rollback-record@1"
)
REGISTERED_OPERATOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-registered-operator@1"
)
REGISTERED_OPERATOR_INTERFACE: Final[str] = "RegisteredOperator@1"

MAX_TEXT_CHARS: Final[int] = 16_384


class OperatorBaseError(AssuranceBaseError):
    """Raised when an operator base contract is malformed or unsafe."""


class OperatorBoundError(OperatorBaseError):
    """Raised when an operator declaration is unbounded or non-deterministic."""


class OperatorDeclarationError(OperatorBaseError):
    """Raised when an operator declaration cannot be canonicalized."""


# ---------------------------------------------------------------------------
# Validation helpers (closed, fail-closed)
# ---------------------------------------------------------------------------


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise OperatorBaseError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise OperatorBaseError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return dict(data)


def _cid(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise OperatorBaseError(f"{name} must be a nonempty CID string")
    try:
        return validate_cid(value)
    except Exception as exc:  # noqa: BLE001 — re-bind content identity errors
        raise OperatorBaseError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise OperatorBaseError(f"{name} must be a nonempty string")
    if value != value.strip() or len(value) > MAX_TEXT_CHARS:
        raise OperatorBaseError(f"{name} must be trimmed NFC-safe text")
    if any(not char.isprintable() for char in value):
        raise OperatorBaseError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise OperatorBaseError(f"{name} must be a boolean")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    # Reuse the mutation-contract token shape via a sealed definition field check.
    if not text or text != text.strip():
        raise OperatorBaseError(f"{name} must be a nonempty token")
    return text


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
        raise OperatorBaseError(f"{name} must be a mapping")
    try:
        validate_payload = _thaw_structured(dict(value))
        # Identity profile admits only reviewed structured types.
        cid_for_structured(validate_payload)
    except Exception as exc:  # noqa: BLE001
        raise OperatorBaseError(f"{name} must be DAG-JSON structured data") from exc
    reject_private_model_authority_and_host_fallbacks(validate_payload, path=name)
    return MappingProxyType(dict(validate_payload))


# ---------------------------------------------------------------------------
# Boundedness / canonicalization
# ---------------------------------------------------------------------------


def assert_operator_bounded(operator: MutationOperatorDefinition) -> None:
    """Fail closed when an operator is versionless, non-deterministic, or unbounded.

    Bounds enforced here are the registry admission surface on top of the
    already-sealed ``MutationOperatorDefinition`` invariants:

    * nonempty version token;
    * ``deterministic is True``;
    * positive ``max_mutants_per_target`` within ``MAX_MUTANTS_PER_TARGET``;
    * positive finite scope limits and no verifier mutation;
    * production-preserving rollback with a clean worktree;
    * disposable, network-disabled sandbox without production credentials.
    """

    if not isinstance(operator, MutationOperatorDefinition):
        raise OperatorBoundError(
            "operator must be a sealed MutationOperatorDefinition"
        )

    version = operator.operator_version
    if type(version) is not str or not version.strip():
        raise OperatorBoundError("operator is versionless; operator_version required")

    if operator.deterministic is not True:
        raise OperatorBoundError(
            "operator is non-deterministic; generation must be byte-for-byte "
            "deterministic given seed and config"
        )

    max_mutants = operator.max_mutants_per_target
    if type(max_mutants) is not int or isinstance(max_mutants, bool):
        raise OperatorBoundError("max_mutants_per_target must be a positive integer")
    if max_mutants < 1:
        raise OperatorBoundError(
            "operator is unbounded: max_mutants_per_target must be >= 1"
        )
    if max_mutants > MAX_MUTANTS_PER_TARGET:
        raise OperatorBoundError(
            "operator is unbounded: max_mutants_per_target exceeds "
            f"MAX_MUTANTS_PER_TARGET ({MAX_MUTANTS_PER_TARGET})"
        )

    scope = operator.scope_limits
    if not isinstance(scope, ScopeLimits):
        raise OperatorBoundError("scope_limits must be a sealed ScopeLimits")
    for field_name, value in (
        ("max_files", scope.max_files),
        ("max_symbols", scope.max_symbols),
        ("max_span_lines", scope.max_span_lines),
    ):
        if type(value) is not int or isinstance(value, bool) or value < 1:
            raise OperatorBoundError(
                f"operator is unbounded: scope_limits.{field_name} must be >= 1"
            )
    if scope.allow_verifier_mutation:
        raise OperatorBoundError(
            "operator is unbounded: scope_limits.allow_verifier_mutation must be false"
        )

    rollback = operator.rollback
    if not isinstance(rollback, RollbackDeclaration):
        raise OperatorBoundError("rollback must be a sealed RollbackDeclaration")
    if rollback.preserves_production is not True:
        raise OperatorBoundError(
            "operator lacks production-preserving rollback"
        )
    if rollback.requires_clean_worktree is not True:
        raise OperatorBoundError(
            "operator rollback requires_clean_worktree must be true"
        )

    sandbox = operator.required_sandbox
    if sandbox.network_disabled is not True:
        raise OperatorBoundError("operator sandbox must disable network")
    if sandbox.production_credentials_forbidden is not True:
        raise OperatorBoundError(
            "operator sandbox must forbid production credentials"
        )
    if sandbox.disposable_worktree_required is not True:
        raise OperatorBoundError(
            "operator sandbox must require a disposable worktree"
        )

    if not operator.supported_languages:
        raise OperatorBoundError("operator supported_languages must not be empty")
    if not operator.supported_artifact_types:
        raise OperatorBoundError(
            "operator supported_artifact_types must not be empty"
        )
    if not operator.expected_violated_property_classes:
        raise OperatorBoundError(
            "operator expected_violated_property_classes must not be empty"
        )


def canonicalize_operator_declaration(
    declaration: MutationOperatorDefinition | Mapping[str, Any],
) -> MutationOperatorDefinition:
    """Return a sealed, identity-verified ``MutationOperatorDefinition``.

    Accepts either an already-constructed definition or a closed mapping.
    Re-seals through ``from_dict`` / constructor so list order, enums, and
    nested CIDs are canonical, then re-verifies content identity and bounds.
    """

    if isinstance(declaration, MutationOperatorDefinition):
        # Round-trip through identity payload so nested declarations are sealed
        # in canonical form even if the caller constructed the object ad hoc.
        sealed = MutationOperatorDefinition.from_dict(declaration.to_dict())
    elif isinstance(declaration, Mapping):
        payload = dict(declaration)
        try:
            if "operator_cid" in payload and "schema" in payload:
                sealed = MutationOperatorDefinition.from_dict(payload)
            else:
                # Permit partial construction maps used by operator authors.
                sealed = MutationOperatorDefinition(**payload)  # type: ignore[arg-type]
                sealed = MutationOperatorDefinition.from_dict(sealed.to_dict())
        except MutationContractError as exc:
            raise OperatorDeclarationError(str(exc)) from exc
        except TypeError as exc:
            raise OperatorDeclarationError(
                f"operator declaration is incomplete or malformed: {exc}"
            ) from exc
    else:
        raise OperatorDeclarationError(
            "declaration must be MutationOperatorDefinition or mapping"
        )

    try:
        verify_operator_identity(sealed)
    except MutationContractError as exc:
        raise OperatorDeclarationError(str(exc)) from exc

    try:
        assert_operator_bounded(sealed)
    except OperatorBoundError:
        raise
    except OperatorBaseError as exc:
        raise OperatorBoundError(str(exc)) from exc

    return sealed


# ---------------------------------------------------------------------------
# Registered operator binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegisteredOperator:
    """Canonical registration binding for one sealed operator declaration.

    Interface: ``RegisteredOperator@1``
    """

    operator_id: str
    operator_version: str
    operator_class: str
    operator_cid: str
    definition: MutationOperatorDefinition
    registration_index: int
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "operator_id",
            "operator_version",
            "operator_class",
            "operator_cid",
            "definition",
            "registration_index",
            "notes",
            "metadata",
            "registration_cid",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.definition, MutationOperatorDefinition):
            raise OperatorBaseError(
                "definition must be a sealed MutationOperatorDefinition"
            )
        assert_operator_bounded(self.definition)
        object.__setattr__(self, "operator_id", _token(self.operator_id, "operator_id"))
        object.__setattr__(
            self, "operator_version", _text(self.operator_version, "operator_version")
        )
        object.__setattr__(
            self, "operator_class", _text(self.operator_class, "operator_class")
        )
        claimed_cid = _cid(self.operator_cid, "operator_cid")
        if claimed_cid != self.definition.operator_cid:
            raise OperatorBaseError(
                "operator_cid does not match definition.operator_cid"
            )
        if self.operator_id != self.definition.operator_id:
            raise OperatorBaseError("operator_id does not match definition")
        if self.operator_version != self.definition.operator_version:
            raise OperatorBaseError("operator_version does not match definition")
        if self.operator_class != self.definition.operator_class:
            raise OperatorBaseError("operator_class does not match definition")
        if (
            type(self.registration_index) is not int
            or isinstance(self.registration_index, bool)
            or self.registration_index < 0
            or self.registration_index >= MAX_OPERATORS
        ):
            raise OperatorBaseError(
                "registration_index must be a nonnegative integer within bounds"
            )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        object.__setattr__(self, "operator_cid", claimed_cid)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": REGISTERED_OPERATOR_SCHEMA,
            "interface_id": REGISTERED_OPERATOR_INTERFACE,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_class": self.operator_class,
            "operator_cid": self.operator_cid,
            "definition": self.definition.identity_payload(),
            "registration_index": self.registration_index,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def registration_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REGISTERED_OPERATOR_SCHEMA,
            "interface_id": REGISTERED_OPERATOR_INTERFACE,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_class": self.operator_class,
            "operator_cid": self.operator_cid,
            "definition": self.definition.to_dict(),
            "registration_index": self.registration_index,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "registration_cid": self.registration_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RegisteredOperator":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("registration_cid")
        if payload.pop("schema") != REGISTERED_OPERATOR_SCHEMA:
            raise OperatorBaseError("unsupported RegisteredOperator schema version")
        if payload.pop("interface_id") != REGISTERED_OPERATOR_INTERFACE:
            raise OperatorBaseError("unsupported RegisteredOperator interface_id")
        definition = payload["definition"]
        if isinstance(definition, Mapping):
            definition = MutationOperatorDefinition.from_dict(definition)
        result = cls(
            operator_id=payload["operator_id"],
            operator_version=payload["operator_version"],
            operator_class=payload["operator_class"],
            operator_cid=payload["operator_cid"],
            definition=definition,
            registration_index=payload["registration_index"],
            notes=payload.get("notes"),
            metadata=payload.get("metadata") or {},
        )
        if claimed != result.registration_cid:
            raise OperatorBaseError(
                "RegisteredOperator registration_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Deterministic rollback record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperatorRollbackRecord:
    """Deterministic, content-addressed rollback record for one operator apply.

    Interface: ``OperatorRollbackRecord@1``

    Given identical operator, target, pre-mutation state, strategy, and
    scope bindings, ``record_cid`` is byte-for-byte stable. Production
    preservation is mandatory.
    """

    operator_id: str
    operator_version: str
    operator_cid: str
    strategy: RollbackStrategy | str
    rollback_declaration_cid: str
    pre_mutation_state_cid: str
    target_id: str | None = None
    target_cid: str | None = None
    source_root_cid: str | None = None
    scope_paths: Sequence[str] = ()
    scope_symbol_ids: Sequence[str] = ()
    requires_clean_worktree: bool = True
    preserves_production: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "operator_id",
            "operator_version",
            "operator_cid",
            "strategy",
            "rollback_declaration_cid",
            "pre_mutation_state_cid",
            "target_id",
            "target_cid",
            "source_root_cid",
            "scope_paths",
            "scope_symbol_ids",
            "requires_clean_worktree",
            "preserves_production",
            "notes",
            "metadata",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator_id", _token(self.operator_id, "operator_id"))
        object.__setattr__(
            self, "operator_version", _text(self.operator_version, "operator_version")
        )
        object.__setattr__(self, "operator_cid", _cid(self.operator_cid, "operator_cid"))
        strategy = self.strategy
        if isinstance(strategy, RollbackStrategy):
            strategy_value = strategy.value
        elif type(strategy) is str:
            try:
                strategy_value = RollbackStrategy(strategy).value
            except ValueError as exc:
                raise OperatorBaseError(
                    f"unsupported rollback strategy: {strategy!r}"
                ) from exc
        else:
            raise OperatorBaseError("strategy must be a RollbackStrategy or string")
        object.__setattr__(self, "strategy", strategy_value)
        object.__setattr__(
            self,
            "rollback_declaration_cid",
            _cid(self.rollback_declaration_cid, "rollback_declaration_cid"),
        )
        object.__setattr__(
            self,
            "pre_mutation_state_cid",
            _cid(self.pre_mutation_state_cid, "pre_mutation_state_cid"),
        )
        object.__setattr__(
            self, "target_id", _optional_text(self.target_id, "target_id")
        )
        object.__setattr__(
            self, "target_cid", _optional_cid(self.target_cid, "target_cid")
        )
        object.__setattr__(
            self,
            "source_root_cid",
            _optional_cid(self.source_root_cid, "source_root_cid"),
        )
        paths = tuple(
            _text(item, "scope_paths[]") for item in list(self.scope_paths or ())
        )
        if len(paths) != len(set(paths)):
            raise OperatorBaseError("scope_paths must not contain duplicates")
        object.__setattr__(self, "scope_paths", tuple(sorted(paths)))
        symbols = tuple(
            _text(item, "scope_symbol_ids[]")
            for item in list(self.scope_symbol_ids or ())
        )
        if len(symbols) != len(set(symbols)):
            raise OperatorBaseError("scope_symbol_ids must not contain duplicates")
        object.__setattr__(self, "scope_symbol_ids", tuple(sorted(symbols)))
        requires_clean = _bool(
            self.requires_clean_worktree, "requires_clean_worktree"
        )
        if not requires_clean:
            raise OperatorBaseError(
                "rollback record requires_clean_worktree must be true"
            )
        object.__setattr__(self, "requires_clean_worktree", requires_clean)
        preserves = _bool(self.preserves_production, "preserves_production")
        if not preserves:
            raise OperatorBaseError(
                "rollback record must preserve production; production "
                "worktrees/branches cannot be mutation targets"
            )
        object.__setattr__(self, "preserves_production", preserves)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ROLLBACK_RECORD_SCHEMA,
            "interface_id": ROLLBACK_RECORD_INTERFACE,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_cid": self.operator_cid,
            "strategy": self.strategy,
            "rollback_declaration_cid": self.rollback_declaration_cid,
            "pre_mutation_state_cid": self.pre_mutation_state_cid,
            "target_id": self.target_id,
            "target_cid": self.target_cid,
            "source_root_cid": self.source_root_cid,
            "scope_paths": list(self.scope_paths),
            "scope_symbol_ids": list(self.scope_symbol_ids),
            "requires_clean_worktree": self.requires_clean_worktree,
            "preserves_production": self.preserves_production,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["record_cid"] = self.record_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OperatorRollbackRecord":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != ROLLBACK_RECORD_SCHEMA:
            raise OperatorBaseError(
                "unsupported OperatorRollbackRecord schema version"
            )
        if payload.pop("interface_id") != ROLLBACK_RECORD_INTERFACE:
            raise OperatorBaseError(
                "unsupported OperatorRollbackRecord interface_id"
            )
        result = cls(
            operator_id=payload["operator_id"],
            operator_version=payload["operator_version"],
            operator_cid=payload["operator_cid"],
            strategy=payload["strategy"],
            rollback_declaration_cid=payload["rollback_declaration_cid"],
            pre_mutation_state_cid=payload["pre_mutation_state_cid"],
            target_id=payload.get("target_id"),
            target_cid=payload.get("target_cid"),
            source_root_cid=payload.get("source_root_cid"),
            scope_paths=payload.get("scope_paths") or (),
            scope_symbol_ids=payload.get("scope_symbol_ids") or (),
            requires_clean_worktree=payload["requires_clean_worktree"],
            preserves_production=payload["preserves_production"],
            notes=payload.get("notes"),
            metadata=payload.get("metadata") or {},
        )
        if claimed != result.record_cid:
            raise OperatorBaseError(
                "OperatorRollbackRecord record_cid identity mismatch"
            )
        return result

    @classmethod
    def from_operator(
        cls,
        operator: MutationOperatorDefinition,
        *,
        pre_mutation_state_cid: str,
        target: MutationTarget | None = None,
        source_root_cid: str | None = None,
        scope_paths: Sequence[str] = (),
        scope_symbol_ids: Sequence[str] = (),
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "OperatorRollbackRecord":
        """Build a deterministic rollback record from a sealed operator."""

        if not isinstance(operator, MutationOperatorDefinition):
            raise OperatorBaseError(
                "operator must be a sealed MutationOperatorDefinition"
            )
        assert_operator_bounded(operator)
        if target is not None and not isinstance(target, MutationTarget):
            raise OperatorBaseError("target must be MutationTarget or None")
        paths = list(scope_paths)
        symbols = list(scope_symbol_ids)
        if target is not None:
            if not paths and target.source_path is not None:
                paths = [target.source_path]
            if not symbols:
                symbols = list(target.symbol_ids)
        return cls(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            operator_cid=operator.operator_cid,
            strategy=operator.rollback.strategy,
            rollback_declaration_cid=operator.rollback.rollback_cid,
            pre_mutation_state_cid=pre_mutation_state_cid,
            target_id=None if target is None else target.target_id,
            target_cid=None if target is None else target.target_cid,
            source_root_cid=source_root_cid,
            scope_paths=paths,
            scope_symbol_ids=symbols,
            requires_clean_worktree=operator.rollback.requires_clean_worktree,
            preserves_production=operator.rollback.preserves_production,
            notes=notes,
            metadata=metadata or {},
        )


# ---------------------------------------------------------------------------
# Abstract operator base
# ---------------------------------------------------------------------------


class MutationOperator(ABC):
    """Abstract base for deterministic, bounded mutation operator implementations.

    Concrete operator classes (control-flow, data/schema, …) bind a sealed
    ``MutationOperatorDefinition`` and inherit target/rollback helpers. The
    registry admits definitions; callables that generate mutants are supplied
    by later operator-class tasks.
    """

    interface_id: ClassVar[str] = OPERATOR_BASE_INTERFACE

    @property
    @abstractmethod
    def definition(self) -> MutationOperatorDefinition:
        """Return the sealed operator declaration for this implementation."""

    @property
    def operator_id(self) -> str:
        return self.definition.operator_id

    @property
    def operator_version(self) -> str:
        return self.definition.operator_version

    @property
    def operator_class(self) -> str:
        return self.definition.operator_class

    @property
    def operator_cid(self) -> str:
        return self.definition.operator_cid

    def supports_target(self, target: MutationTarget) -> bool:
        """Return True when language, artifact type, and prerequisites match."""

        return self.definition.supports_target(target)

    def assert_supports_target(self, target: MutationTarget) -> None:
        """Fail closed when the target is outside this operator's support set."""

        try:
            assert_operator_supports_target(self.definition, target)
        except MutationContractError as exc:
            raise OperatorBaseError(str(exc)) from exc

    def rollback_declaration(self) -> RollbackDeclaration:
        """Return the sealed rollback contract bound into the definition."""

        return self.definition.rollback

    def build_rollback_record(
        self,
        *,
        pre_mutation_state_cid: str,
        target: MutationTarget | None = None,
        source_root_cid: str | None = None,
        scope_paths: Sequence[str] = (),
        scope_symbol_ids: Sequence[str] = (),
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> OperatorRollbackRecord:
        """Produce a deterministic rollback record for a prospective apply."""

        if target is not None:
            self.assert_supports_target(target)
        return OperatorRollbackRecord.from_operator(
            self.definition,
            pre_mutation_state_cid=pre_mutation_state_cid,
            target=target,
            source_root_cid=source_root_cid,
            scope_paths=scope_paths,
            scope_symbol_ids=scope_symbol_ids,
            notes=notes,
            metadata=metadata,
        )

    def sealed_definition(self) -> MutationOperatorDefinition:
        """Return the canonicalized, bound-checked declaration."""

        return canonicalize_operator_declaration(self.definition)


@dataclass(frozen=True, slots=True)
class DeclarationBackedOperator(MutationOperator):
    """Concrete operator that binds only a sealed declaration (no generator).

    Useful for registry admission tests and declaration-only catalogues before
    class-specific generators land.
    """

    _definition: MutationOperatorDefinition

    def __post_init__(self) -> None:
        sealed = canonicalize_operator_declaration(self._definition)
        object.__setattr__(self, "_definition", sealed)

    @property
    def definition(self) -> MutationOperatorDefinition:
        return self._definition


__all__ = [
    "OPERATOR_BASE_INTERFACE",
    "REGISTERED_OPERATOR_INTERFACE",
    "REGISTERED_OPERATOR_SCHEMA",
    "ROLLBACK_RECORD_INTERFACE",
    "ROLLBACK_RECORD_SCHEMA",
    "DeclarationBackedOperator",
    "MAX_MUTANTS_PER_TARGET",
    "MAX_OPERATORS",
    "MUTATION_OPERATOR_DEFINITION_INTERFACE",
    "MUTATION_OPERATOR_DEFINITION_SCHEMA",
    "MutationOperator",
    "OperatorBaseError",
    "OperatorBoundError",
    "OperatorDeclarationError",
    "OperatorRollbackRecord",
    "RegisteredOperator",
    "assert_operator_bounded",
    "canonicalize_operator_declaration",
]

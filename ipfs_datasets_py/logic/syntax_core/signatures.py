"""Many-sorted signatures for the typed logic syntax kernel.

Interfaces (LFP-012):

* ``LogicSignature@1`` — immutable sort/symbol table with arity and domain
  invariants enforced at construction

A signature is the closed vocabulary against which terms and formulas are
elaborated.  Sort and symbol names are unique, arities are finite and
non-negative, predicate domains are non-empty or explicitly nullary, and
function symbols always declare a range sort.  Built-in ``Bool`` is always
present and cannot be redeclared with a conflicting shape.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterator

from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    NamespaceKind,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_COLLECTION_ITEMS,
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

LOGIC_SIGNATURE_INTERFACE: Final = "LogicSignature@1"
LOGIC_SIGNATURE_SCHEMA_VERSION: Final = "syntax-logic-signature/v1"
LOGIC_SORT_SCHEMA_VERSION: Final = "syntax-logic-sort/v1"
SYMBOL_DECLARATION_SCHEMA_VERSION: Final = "syntax-symbol-declaration/v1"
SIGNATURES_MODULE_VERSION: Final = "1.0.0"

BOOL_SORT_NAME: Final = "Bool"
INDIVIDUAL_SORT_NAME: Final = "Individual"

_SYMBOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']{0,255}$")
_SORT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']{0,255}$")
_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")


class SignatureError(SyntaxContractError):
    """Raised when a signature, sort, or symbol declaration is invalid."""


class SymbolKind(str, Enum):
    """Closed vocabulary of symbol roles in a many-sorted signature."""

    CONSTANT = "constant"
    FUNCTION = "function"
    PREDICATE = "predicate"
    TYPE_VARIABLE = "type_variable"


class SortKind(str, Enum):
    """Shape of a sort expression."""

    ATOMIC = "atomic"
    BOOL = "bool"
    PARAMETRIC = "parametric"


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _symbol_name(value: object, field_name: str = "name") -> str:
    result = _text(value, field_name, maximum=256)
    if not _SYMBOL_NAME_RE.fullmatch(result):
        raise SignatureError(
            f"{field_name} must be a stable symbol identifier; got {result!r}"
        )
    return result


def _sort_name(value: object, field_name: str = "name") -> str:
    result = _text(value, field_name, maximum=256)
    if not _SORT_NAME_RE.fullmatch(result):
        raise SignatureError(
            f"{field_name} must be a stable sort identifier; got {result!r}"
        )
    return result


def _feature_id(value: object, field_name: str = "feature") -> str:
    result = _text(value, field_name, maximum=128)
    if not _FEATURE_RE.fullmatch(result):
        raise SignatureError(
            f"{field_name} must be a lowercase feature id; got {result!r}"
        )
    return result


def _features(value: object, field_name: str = "features") -> tuple[str, ...]:
    items = tuple(
        _feature_id(item, f"{field_name} item")
        for item in _require_sequence(value if value is not None else (), field_name)
    )
    if len(items) > MAX_COLLECTION_ITEMS:
        raise SignatureError(f"{field_name} exceeds collection ceiling")
    if len(items) != len(set(items)):
        raise SignatureError(f"{field_name} must not contain duplicates")
    return tuple(sorted(items))


# ---------------------------------------------------------------------------
# Sorts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicSort:
    """One immutable sort expression.

    Atomic sorts carry only a name.  Parametric sorts (for example
    ``Array(Index, Elem)``) nest argument sorts.  The built-in Boolean sort is
    available as :data:`BOOL_SORT`.
    """

    name: str
    kind: SortKind | str = SortKind.ATOMIC
    arguments: tuple["LogicSort", ...] = ()
    schema_version: str = LOGIC_SORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _sort_name(self.name, "LogicSort.name"))
        if isinstance(self.kind, SortKind):
            kind = self.kind
        else:
            try:
                kind = SortKind(_text(self.kind, "LogicSort.kind", maximum=32))
            except ValueError as error:
                raise SignatureError(
                    f"LogicSort.kind must be a SortKind value; got {self.kind!r}"
                ) from error
        object.__setattr__(self, "kind", kind)

        arguments = tuple(
            item
            if isinstance(item, LogicSort)
            else LogicSort.from_dict(_require_mapping(item, "LogicSort.arguments item"))
            for item in _require_sequence(self.arguments, "LogicSort.arguments")
        )
        if len(arguments) > MAX_COLLECTION_ITEMS:
            raise SignatureError("LogicSort.arguments exceeds collection ceiling")
        object.__setattr__(self, "arguments", arguments)

        if kind is SortKind.BOOL:
            if self.name != BOOL_SORT_NAME:
                raise SignatureError(
                    f"bool sort must be named {BOOL_SORT_NAME!r}; got {self.name!r}"
                )
            if arguments:
                raise SignatureError("bool sort must be nullary")
        elif kind is SortKind.ATOMIC:
            if arguments:
                raise SignatureError(
                    f"atomic sort {self.name!r} must not carry arguments"
                )
            if self.name == BOOL_SORT_NAME:
                # Normalize Bool-named atomic sorts to the bool kind.
                object.__setattr__(self, "kind", SortKind.BOOL)
        elif kind is SortKind.PARAMETRIC:
            if not arguments:
                raise SignatureError(
                    f"parametric sort {self.name!r} requires at least one argument"
                )

        if self.schema_version != LOGIC_SORT_SCHEMA_VERSION:
            raise SignatureError(
                f"unsupported LogicSort schema_version {self.schema_version!r}"
            )

    @property
    def is_bool(self) -> bool:
        return self.kind is SortKind.BOOL or self.name == BOOL_SORT_NAME

    @property
    def arity(self) -> int:
        return len(self.arguments)

    def is_subtype_of(self, other: "LogicSort") -> bool:
        """Structural equality only; no subtyping lattice in the core kernel."""

        return self == other

    def to_dict(self) -> dict[str, Any]:
        return {
            "arguments": [item.to_dict() for item in self.arguments],
            "kind": self.kind.value if isinstance(self.kind, SortKind) else self.kind,
            "name": self.name,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicSort":
        payload = _require_mapping(data, "LogicSort")
        return cls(
            name=str(payload.get("name") or ""),
            kind=str(payload.get("kind") or SortKind.ATOMIC.value),
            arguments=tuple(
                LogicSort.from_dict(_require_mapping(item, "arguments item"))
                for item in _require_sequence(
                    payload.get("arguments") or (), "arguments"
                )
            ),
            schema_version=str(
                payload.get("schema_version") or LOGIC_SORT_SCHEMA_VERSION
            ),
        )

    def __str__(self) -> str:
        if not self.arguments:
            return self.name
        args = ", ".join(str(item) for item in self.arguments)
        return f"{self.name}({args})"


BOOL_SORT: Final = LogicSort(name=BOOL_SORT_NAME, kind=SortKind.BOOL)
INDIVIDUAL_SORT: Final = LogicSort(name=INDIVIDUAL_SORT_NAME, kind=SortKind.ATOMIC)


def atomic_sort(name: str) -> LogicSort:
    """Construct an atomic sort, mapping ``Bool`` to the built-in Boolean sort."""

    if name == BOOL_SORT_NAME:
        return BOOL_SORT
    return LogicSort(name=name, kind=SortKind.ATOMIC)


def parametric_sort(name: str, *arguments: LogicSort) -> LogicSort:
    """Construct a parametric sort with the given argument sorts."""

    return LogicSort(name=name, kind=SortKind.PARAMETRIC, arguments=tuple(arguments))


# ---------------------------------------------------------------------------
# Symbol declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SymbolDeclaration:
    """One typed symbol with an explicit domain and optional range.

    * Constants are nullary functions (empty domain, non-bool range).
    * Functions have a non-empty domain and a non-bool range.
    * Predicates have a (possibly empty) domain and an implicit Boolean range.
    * Type variables are nullary and carry no domain/range payload beyond name.
    """

    name: str
    kind: SymbolKind | str
    domain: tuple[LogicSort, ...] = ()
    range: LogicSort | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SYMBOL_DECLARATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _symbol_name(self.name, "SymbolDeclaration.name"))
        if isinstance(self.kind, SymbolKind):
            kind = self.kind
        else:
            try:
                kind = SymbolKind(
                    _text(self.kind, "SymbolDeclaration.kind", maximum=32)
                )
            except ValueError as error:
                raise SignatureError(
                    f"SymbolDeclaration.kind must be a SymbolKind value; "
                    f"got {self.kind!r}"
                ) from error
        object.__setattr__(self, "kind", kind)

        domain = tuple(
            item
            if isinstance(item, LogicSort)
            else LogicSort.from_dict(
                _require_mapping(item, "SymbolDeclaration.domain item")
            )
            for item in _require_sequence(self.domain, "SymbolDeclaration.domain")
        )
        if len(domain) > MAX_COLLECTION_ITEMS:
            raise SignatureError("SymbolDeclaration.domain exceeds collection ceiling")
        object.__setattr__(self, "domain", domain)

        range_sort = self.range
        if range_sort is not None and not isinstance(range_sort, LogicSort):
            range_sort = LogicSort.from_dict(
                _require_mapping(range_sort, "SymbolDeclaration.range")
            )
        object.__setattr__(self, "range", range_sort)
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "SymbolDeclaration.metadata")
        )

        if kind is SymbolKind.CONSTANT:
            if domain:
                raise SignatureError(
                    f"constant {self.name!r} must be nullary; got arity {len(domain)}"
                )
            if range_sort is None:
                raise SignatureError(f"constant {self.name!r} requires a range sort")
            if range_sort.is_bool:
                raise SignatureError(
                    f"constant {self.name!r} range must not be Bool "
                    "(use a nullary predicate for propositions)"
                )
        elif kind is SymbolKind.FUNCTION:
            if not domain:
                raise SignatureError(
                    f"function {self.name!r} requires a non-empty domain "
                    "(use constant for nullary symbols)"
                )
            if range_sort is None:
                raise SignatureError(f"function {self.name!r} requires a range sort")
            if range_sort.is_bool:
                raise SignatureError(
                    f"function {self.name!r} range must not be Bool "
                    "(use a predicate for Boolean-valued symbols)"
                )
        elif kind is SymbolKind.PREDICATE:
            if range_sort is not None and not range_sort.is_bool:
                raise SignatureError(
                    f"predicate {self.name!r} range must be Bool when present"
                )
            # Normalize predicate range to Bool.
            object.__setattr__(self, "range", BOOL_SORT)
        elif kind is SymbolKind.TYPE_VARIABLE:
            if domain:
                raise SignatureError(
                    f"type variable {self.name!r} must not carry a domain"
                )
            if range_sort is not None:
                raise SignatureError(
                    f"type variable {self.name!r} must not carry a range"
                )

        if self.schema_version != SYMBOL_DECLARATION_SCHEMA_VERSION:
            raise SignatureError(
                f"unsupported SymbolDeclaration schema_version "
                f"{self.schema_version!r}"
            )

    @property
    def arity(self) -> int:
        return len(self.domain)

    @property
    def is_nullary(self) -> bool:
        return self.arity == 0

    @property
    def result_sort(self) -> LogicSort:
        if self.kind is SymbolKind.PREDICATE:
            return BOOL_SORT
        if self.range is None:
            raise SignatureError(
                f"symbol {self.name!r} has no result sort"
            )
        return self.range

    def accepts(self, argument_sorts: Sequence[LogicSort]) -> bool:
        """Return True when *argument_sorts* match this symbol's domain exactly."""

        if len(argument_sorts) != self.arity:
            return False
        return all(
            expected == actual
            for expected, actual in zip(self.domain, argument_sorts, strict=True)
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "domain": [item.to_dict() for item in self.domain],
            "kind": self.kind.value if isinstance(self.kind, SymbolKind) else self.kind,
            "metadata": _thaw_mapping(self.metadata),
            "name": self.name,
            "schema_version": self.schema_version,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SymbolDeclaration":
        payload = _require_mapping(data, "SymbolDeclaration")
        range_payload = payload.get("range")
        return cls(
            name=str(payload.get("name") or ""),
            kind=str(payload.get("kind") or ""),
            domain=tuple(
                LogicSort.from_dict(_require_mapping(item, "domain item"))
                for item in _require_sequence(payload.get("domain") or (), "domain")
            ),
            range=(
                LogicSort.from_dict(_require_mapping(range_payload, "range"))
                if range_payload is not None
                else None
            ),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or SYMBOL_DECLARATION_SCHEMA_VERSION
            ),
        )


def declare_constant(name: str, sort: LogicSort) -> SymbolDeclaration:
    """Declare a typed constant (nullary function symbol)."""

    return SymbolDeclaration(
        name=name, kind=SymbolKind.CONSTANT, domain=(), range=sort
    )


def declare_function(
    name: str,
    domain: Sequence[LogicSort],
    range: LogicSort,
) -> SymbolDeclaration:
    """Declare a function symbol with the given domain and range."""

    return SymbolDeclaration(
        name=name,
        kind=SymbolKind.FUNCTION,
        domain=tuple(domain),
        range=range,
    )


def declare_predicate(
    name: str,
    domain: Sequence[LogicSort] = (),
) -> SymbolDeclaration:
    """Declare a predicate symbol (Boolean-valued)."""

    return SymbolDeclaration(
        name=name,
        kind=SymbolKind.PREDICATE,
        domain=tuple(domain),
        range=BOOL_SORT,
    )


# ---------------------------------------------------------------------------
# LogicSignature@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicSignature:
    """Immutable many-sorted signature.

    Interface: ``LogicSignature@1``.

    Construction fails closed on:

    * duplicate sort or symbol names
    * symbols that reference undeclared sorts
    * arity/domain/range shape violations (delegated to
      :class:`SymbolDeclaration`)
    * wrong family/profile namespaces
    * missing or conflicting built-in ``Bool``
    """

    signature_id: str
    family: LogicIdentity | Mapping[str, Any] | str
    profile: LogicIdentity | Mapping[str, Any] | str
    sorts: tuple[LogicSort, ...] = ()
    symbols: tuple[SymbolDeclaration, ...] = ()
    features: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOGIC_SIGNATURE_SCHEMA_VERSION

    interface: ClassVar[str] = LOGIC_SIGNATURE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "signature_id", _record_id(self.signature_id, "signature_id")
        )
        object.__setattr__(
            self,
            "family",
            require_namespace_identity(self.family, NamespaceKind.FAMILY, "family"),
        )
        object.__setattr__(
            self,
            "profile",
            require_namespace_identity(self.profile, NamespaceKind.PROFILE, "profile"),
        )
        object.__setattr__(self, "features", _features(self.features, "features"))
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )

        sorts = tuple(
            item
            if isinstance(item, LogicSort)
            else LogicSort.from_dict(_require_mapping(item, "sorts item"))
            for item in _require_sequence(self.sorts, "sorts")
        )
        if len(sorts) > MAX_COLLECTION_ITEMS:
            raise SignatureError("LogicSignature.sorts exceeds collection ceiling")

        # Ensure Bool is present exactly once as the built-in Boolean sort.
        bool_entries = [item for item in sorts if item.name == BOOL_SORT_NAME]
        if not bool_entries:
            sorts = (BOOL_SORT, *sorts)
        else:
            for item in bool_entries:
                if not item.is_bool:
                    raise SignatureError(
                        "Bool sort must use the built-in bool kind"
                    )
            # Deduplicate Bool if the caller also supplied it.
            if len(bool_entries) > 1:
                raise SignatureError("Bool sort must not be declared more than once")
            # Keep Bool first for deterministic ordering of the built-in.
            others = tuple(item for item in sorts if item.name != BOOL_SORT_NAME)
            sorts = (BOOL_SORT, *others)

        sort_names = [item.name for item in sorts]
        if len(sort_names) != len(set(sort_names)):
            raise SignatureError("LogicSignature.sorts must have unique names")
        object.__setattr__(self, "sorts", sorts)
        sort_index = {item.name: item for item in sorts}

        symbols = tuple(
            item
            if isinstance(item, SymbolDeclaration)
            else SymbolDeclaration.from_dict(
                _require_mapping(item, "symbols item")
            )
            for item in _require_sequence(self.symbols, "symbols")
        )
        if len(symbols) > MAX_COLLECTION_ITEMS:
            raise SignatureError("LogicSignature.symbols exceeds collection ceiling")
        symbol_names = [item.name for item in symbols]
        if len(symbol_names) != len(set(symbol_names)):
            raise SignatureError("LogicSignature.symbols must have unique names")
        # Symbol names must not collide with sort names.
        collisions = set(symbol_names) & set(sort_names)
        if collisions:
            raise SignatureError(
                f"symbol names collide with sort names: {sorted(collisions)}"
            )

        for symbol in symbols:
            for domain_sort in symbol.domain:
                self._require_sort_declared(domain_sort, sort_index, symbol.name)
            if symbol.range is not None:
                self._require_sort_declared(symbol.range, sort_index, symbol.name)
        object.__setattr__(self, "symbols", symbols)

        if self.schema_version != LOGIC_SIGNATURE_SCHEMA_VERSION:
            raise SignatureError(
                f"unsupported LogicSignature schema_version "
                f"{self.schema_version!r}"
            )

    @staticmethod
    def _require_sort_declared(
        sort: LogicSort,
        sort_index: Mapping[str, LogicSort],
        owner: str,
    ) -> None:
        declared = sort_index.get(sort.name)
        if declared is None:
            raise SignatureError(
                f"symbol {owner!r} references undeclared sort {sort.name!r}"
            )
        if declared != sort:
            # Allow structural match on name+kind+args even if object identity differs.
            if (
                declared.name != sort.name
                or declared.kind != sort.kind
                or declared.arguments != sort.arguments
            ):
                raise SignatureError(
                    f"symbol {owner!r} references sort {sort!s} that does not "
                    f"match the declared sort {declared!s}"
                )
        for argument in sort.arguments:
            LogicSignature._require_sort_declared(argument, sort_index, owner)

    def sort_map(self) -> Mapping[str, LogicSort]:
        return MappingProxyType({item.name: item for item in self.sorts})

    def symbol_map(self) -> Mapping[str, SymbolDeclaration]:
        return MappingProxyType({item.name: item for item in self.symbols})

    def get_sort(self, name: str) -> LogicSort:
        try:
            return self.sort_map()[name]
        except KeyError as error:
            raise SignatureError(f"unknown sort {name!r}") from error

    def get_symbol(self, name: str) -> SymbolDeclaration:
        try:
            return self.symbol_map()[name]
        except KeyError as error:
            raise SignatureError(f"unknown symbol {name!r}") from error

    def has_sort(self, name: str) -> bool:
        return name in self.sort_map()

    def has_symbol(self, name: str) -> bool:
        return name in self.symbol_map()

    def require_symbol(
        self,
        name: str,
        *,
        kind: SymbolKind | None = None,
        arity: int | None = None,
    ) -> SymbolDeclaration:
        """Lookup a symbol and optionally enforce kind/arity invariants."""

        symbol = self.get_symbol(name)
        if kind is not None and symbol.kind is not kind:
            raise SignatureError(
                f"symbol {name!r} has kind {symbol.kind.value!r}; "
                f"expected {kind.value!r}"
            )
        if arity is not None and symbol.arity != arity:
            raise SignatureError(
                f"symbol {name!r} has arity {symbol.arity}; expected {arity}"
            )
        return symbol

    def check_application(
        self,
        name: str,
        argument_sorts: Sequence[LogicSort],
        *,
        expected_kind: SymbolKind | None = None,
    ) -> LogicSort:
        """Validate an application against this signature; return result sort.

        Fails closed on unknown symbols, kind mismatches, arity mismatches, and
        domain sort mismatches.
        """

        symbol = self.get_symbol(name)
        if expected_kind is not None and symbol.kind is not expected_kind:
            raise SignatureError(
                f"symbol {name!r} has kind {symbol.kind.value!r}; "
                f"expected {expected_kind.value!r}"
            )
        if symbol.kind is SymbolKind.TYPE_VARIABLE:
            raise SignatureError(
                f"type variable {name!r} cannot be applied"
            )
        if len(argument_sorts) != symbol.arity:
            raise SignatureError(
                f"symbol {name!r} expects arity {symbol.arity}; "
                f"got {len(argument_sorts)}"
            )
        for index, (expected, actual) in enumerate(
            zip(symbol.domain, argument_sorts, strict=True)
        ):
            if expected != actual:
                raise SignatureError(
                    f"symbol {name!r} argument {index} expects sort "
                    f"{expected!s}; got {actual!s}"
                )
        return symbol.result_sort

    def extend(
        self,
        *,
        signature_id: str | None = None,
        sorts: Sequence[LogicSort] = (),
        symbols: Sequence[SymbolDeclaration] = (),
        features: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> "LogicSignature":
        """Return a new signature with additional sorts/symbols/features."""

        merged_features = tuple(
            sorted(set(self.features) | set(_features(tuple(features), "features")))
        )
        merged_metadata = dict(_thaw_mapping(self.metadata))
        if metadata:
            merged_metadata.update(dict(metadata))
        # Drop Bool from self.sorts when re-constructing; constructor re-injects it.
        base_sorts = tuple(
            item for item in self.sorts if item.name != BOOL_SORT_NAME
        )
        return LogicSignature(
            signature_id=signature_id or self.signature_id,
            family=self.family,
            profile=self.profile,
            sorts=base_sorts + tuple(sorts),
            symbols=self.symbols + tuple(symbols),
            features=merged_features,
            metadata=merged_metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family.to_dict()
            if isinstance(self.family, LogicIdentity)
            else self.family,
            "features": list(self.features),
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "profile": self.profile.to_dict()
            if isinstance(self.profile, LogicIdentity)
            else self.profile,
            "schema_version": self.schema_version,
            "signature_id": self.signature_id,
            "sorts": [item.to_dict() for item in self.sorts],
            "symbols": [item.to_dict() for item in self.symbols],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicSignature":
        payload = _require_mapping(data, "LogicSignature")
        interface = payload.get("interface")
        if interface is not None and interface != LOGIC_SIGNATURE_INTERFACE:
            raise SignatureError(
                f"unsupported LogicSignature interface {interface!r}"
            )
        return cls(
            signature_id=str(payload.get("signature_id") or ""),
            family=payload.get("family") or "",
            profile=payload.get("profile") or "",
            sorts=tuple(
                LogicSort.from_dict(_require_mapping(item, "sorts item"))
                for item in _require_sequence(payload.get("sorts") or (), "sorts")
            ),
            symbols=tuple(
                SymbolDeclaration.from_dict(
                    _require_mapping(item, "symbols item")
                )
                for item in _require_sequence(
                    payload.get("symbols") or (), "symbols"
                )
            ),
            features=tuple(payload.get("features") or ()),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or LOGIC_SIGNATURE_SCHEMA_VERSION
            ),
        )

    def __iter__(self) -> Iterator[SymbolDeclaration]:
        return iter(self.symbols)

    def __len__(self) -> int:
        return len(self.symbols)


def propositional_signature(
    signature_id: str,
    propositions: Sequence[str],
    *,
    family: str = "propositional",
    profile: str = "classical",
) -> LogicSignature:
    """Build a pure-propositional signature of nullary predicates."""

    symbols = tuple(declare_predicate(name) for name in propositions)
    return LogicSignature(
        signature_id=signature_id,
        family=family,
        profile=profile,
        sorts=(),
        symbols=symbols,
        features=("propositional",),
    )


def many_sorted_fol_signature(
    signature_id: str,
    *,
    sorts: Sequence[LogicSort] = (),
    constants: Sequence[tuple[str, LogicSort]] = (),
    functions: Sequence[tuple[str, Sequence[LogicSort], LogicSort]] = (),
    predicates: Sequence[tuple[str, Sequence[LogicSort]]] = (),
    family: str = "first_order",
    profile: str = "many_sorted",
    features: Sequence[str] = ("first_order", "many_sorted"),
) -> LogicSignature:
    """Build a many-sorted first-order signature from compact declarations."""

    symbols: list[SymbolDeclaration] = []
    for name, sort in constants:
        symbols.append(declare_constant(name, sort))
    for name, domain, range_sort in functions:
        symbols.append(declare_function(name, domain, range_sort))
    for name, domain in predicates:
        symbols.append(declare_predicate(name, domain))
    return LogicSignature(
        signature_id=signature_id,
        family=family,
        profile=profile,
        sorts=tuple(sorts),
        symbols=tuple(symbols),
        features=tuple(features),
    )


__all__ = [
    "BOOL_SORT",
    "BOOL_SORT_NAME",
    "INDIVIDUAL_SORT",
    "INDIVIDUAL_SORT_NAME",
    "LOGIC_SIGNATURE_INTERFACE",
    "LOGIC_SIGNATURE_SCHEMA_VERSION",
    "LOGIC_SORT_SCHEMA_VERSION",
    "SIGNATURES_MODULE_VERSION",
    "SYMBOL_DECLARATION_SCHEMA_VERSION",
    "LogicSignature",
    "LogicSort",
    "SignatureError",
    "SortKind",
    "SymbolDeclaration",
    "SymbolKind",
    "atomic_sort",
    "declare_constant",
    "declare_function",
    "declare_predicate",
    "many_sorted_fol_signature",
    "parametric_sort",
    "propositional_signature",
]

"""Typed core terms, formulas, binders, and family extension nodes.

Interfaces (LFP-012):

* ``TypedExpression@1`` — signature-bound, content-identified expression root
* ``LogicExtensionNode@1`` — versioned family extension with explicit
  family/profile/features (never an opaque unversioned payload)

Construction is fail-closed for shape invariants (connective arity, binder
presence, formula-vs-term categories).  Full sort/arity/signature checking is
performed by :func:`elaborate` / :class:`TypedExpression` construction against
a :class:`~ipfs_datasets_py.logic.syntax_core.signatures.LogicSignature`.
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
    SourceRange,
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
    require_namespace_identity,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    LogicSort,
    SignatureError,
    SymbolKind,
    _symbol_name,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

TYPED_EXPRESSION_INTERFACE: Final = "TypedExpression@1"
LOGIC_EXTENSION_NODE_INTERFACE: Final = "LogicExtensionNode@1"

TYPED_EXPRESSION_SCHEMA_VERSION: Final = "syntax-typed-expression/v1"
LOGIC_NODE_SCHEMA_VERSION: Final = "syntax-logic-node/v1"
LOGIC_EXTENSION_NODE_SCHEMA_VERSION: Final = "syntax-logic-extension-node/v1"
BINDER_SCHEMA_VERSION: Final = "syntax-binder/v1"
AST_MODULE_VERSION: Final = "1.0.0"

# Payload schema must be versioned: ``family.construct/vN`` or similar.
_PAYLOAD_SCHEMA_RE = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+/v[0-9]+(?:\.[0-9]+)*$"
)
_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")
_NODE_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class AstError(SyntaxContractError):
    """Raised when a core AST node or typed expression is malformed."""


class ExprCategory(str, Enum):
    """Whether a node denotes a term or a formula."""

    TERM = "term"
    FORMULA = "formula"


class NodeKind(str, Enum):
    """Closed core node vocabulary for classical many-sorted FOL."""

    # Terms
    CONSTANT = "constant"
    VARIABLE = "variable"
    APPLICATION = "application"
    # Atomic formulas
    TRUE = "true"
    FALSE = "false"
    PREDICATE = "predicate"
    EQUALITY = "equality"
    # Connectives
    NOT = "not"
    AND = "and"
    OR = "or"
    IMPLIES = "implies"
    IFF = "iff"
    # Binders
    FORALL = "forall"
    EXISTS = "exists"
    LET = "let"
    # Family extensions
    EXTENSION = "extension"


_TERM_KINDS: Final[frozenset[NodeKind]] = frozenset(
    {
        NodeKind.CONSTANT,
        NodeKind.VARIABLE,
        NodeKind.APPLICATION,
    }
)
_FORMULA_KINDS: Final[frozenset[NodeKind]] = frozenset(
    {
        NodeKind.TRUE,
        NodeKind.FALSE,
        NodeKind.PREDICATE,
        NodeKind.EQUALITY,
        NodeKind.NOT,
        NodeKind.AND,
        NodeKind.OR,
        NodeKind.IMPLIES,
        NodeKind.IFF,
        NodeKind.FORALL,
        NodeKind.EXISTS,
        NodeKind.EXTENSION,
    }
)
# ``let`` is polymorphic: formula when the body is a formula, else term.
_NULLARY_FORMULAS: Final[frozenset[NodeKind]] = frozenset(
    {NodeKind.TRUE, NodeKind.FALSE}
)
_UNARY_CONNECTIVES: Final[frozenset[NodeKind]] = frozenset({NodeKind.NOT})
_BINARY_CONNECTIVES: Final[frozenset[NodeKind]] = frozenset(
    {NodeKind.IMPLIES, NodeKind.IFF}
)
_NARY_CONNECTIVES: Final[frozenset[NodeKind]] = frozenset(
    {NodeKind.AND, NodeKind.OR}
)
_QUANTIFIERS: Final[frozenset[NodeKind]] = frozenset(
    {NodeKind.FORALL, NodeKind.EXISTS}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_kind(value: object, field_name: str = "kind") -> NodeKind | str:
    if isinstance(value, NodeKind):
        return value
    text = _text(value, field_name, maximum=128)
    try:
        return NodeKind(text)
    except ValueError:
        if not _NODE_KIND_RE.fullmatch(text):
            raise AstError(
                f"{field_name} must be a NodeKind or lowercase node kind id"
            )
        # Open kind reserved for decoded extension wrappers only.
        return text


def _feature_id(value: object, field_name: str = "feature") -> str:
    result = _text(value, field_name, maximum=128)
    if not _FEATURE_RE.fullmatch(result):
        raise AstError(f"{field_name} must be a lowercase feature id; got {result!r}")
    return result


def _features(value: object, field_name: str = "features") -> tuple[str, ...]:
    items = tuple(
        _feature_id(item, f"{field_name} item")
        for item in _require_sequence(value if value is not None else (), field_name)
    )
    if len(items) > MAX_COLLECTION_ITEMS:
        raise AstError(f"{field_name} exceeds collection ceiling")
    if len(items) != len(set(items)):
        raise AstError(f"{field_name} must not contain duplicates")
    return tuple(sorted(items))


def _payload_schema(value: object, field_name: str = "payload_schema") -> str:
    result = _text(value, field_name, maximum=256)
    if not _PAYLOAD_SCHEMA_RE.fullmatch(result):
        raise AstError(
            f"{field_name} must be a versioned schema id matching "
            f"'family.construct/vN' (got {result!r}); opaque unversioned "
            "payloads are rejected"
        )
    return result


def _optional_range(value: object, field_name: str = "range") -> SourceRange | None:
    if value is None:
        return None
    if isinstance(value, SourceRange):
        return value
    return SourceRange.from_dict(_require_mapping(value, field_name))


def _optional_sort(value: object, field_name: str = "sort") -> LogicSort | None:
    if value is None:
        return None
    if isinstance(value, LogicSort):
        return value
    return LogicSort.from_dict(_require_mapping(value, field_name))


def _require_sort(value: object, field_name: str = "sort") -> LogicSort:
    sort = _optional_sort(value, field_name)
    if sort is None:
        raise AstError(f"{field_name} is required")
    return sort


# ---------------------------------------------------------------------------
# Binder
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Binder:
    """Typed binder ``(name : sort)`` for quantifiers and let-bindings."""

    name: str
    sort: LogicSort
    schema_version: str = BINDER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _symbol_name(self.name, "Binder.name"))
        sort = self.sort
        if not isinstance(sort, LogicSort):
            sort = LogicSort.from_dict(_require_mapping(sort, "Binder.sort"))
        if sort.is_bool:
            raise AstError(
                f"binder {self.name!r} must not bind a Boolean sort "
                "(use propositional structure instead)"
            )
        object.__setattr__(self, "sort", sort)
        if self.schema_version != BINDER_SCHEMA_VERSION:
            raise AstError(
                f"unsupported Binder schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema_version": self.schema_version,
            "sort": self.sort.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Binder":
        payload = _require_mapping(data, "Binder")
        return cls(
            name=str(payload.get("name") or ""),
            sort=LogicSort.from_dict(_require_mapping(payload.get("sort"), "sort")),
            schema_version=str(payload.get("schema_version") or BINDER_SCHEMA_VERSION),
        )

    def __str__(self) -> str:
        return f"{self.name}:{self.sort}"


# ---------------------------------------------------------------------------
# LogicExtensionNode@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicExtensionNode:
    """Versioned family-specific extension payload.

    Interface: ``LogicExtensionNode@1``.

    Every extension **must** declare:

    * ``family`` — semantic family identity
    * ``profile`` — fragment/profile identity
    * ``features`` — non-empty feature set enabled by this node
    * ``payload_schema`` — versioned schema id (``family.construct/vN``)
    * ``payload`` — structured JSON matching that schema (never raw text alone)

    Opaque unversioned payloads (missing schema, bare blobs, free-form strings
    as the sole payload) are rejected at construction.
    """

    node_id: str
    family: LogicIdentity | Mapping[str, Any] | str
    profile: LogicIdentity | Mapping[str, Any] | str
    features: tuple[str, ...]
    payload_schema: str
    payload: Mapping[str, Any]
    children: tuple["LogicNode", ...] = ()
    range: SourceRange | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOGIC_EXTENSION_NODE_SCHEMA_VERSION

    interface: ClassVar[str] = LOGIC_EXTENSION_NODE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _record_id(self.node_id, "node_id"))
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
        features = _features(self.features, "features")
        if not features:
            raise AstError(
                "LogicExtensionNode.features must be non-empty; "
                "undeclared feature sets are rejected"
            )
        object.__setattr__(self, "features", features)
        object.__setattr__(
            self, "payload_schema", _payload_schema(self.payload_schema)
        )

        # Reject opaque unversioned payloads.
        if self.payload is None:
            raise AstError("LogicExtensionNode.payload must not be None")
        if isinstance(self.payload, (str, bytes, bytearray)):
            raise AstError(
                "LogicExtensionNode.payload must be a structured mapping; "
                "opaque string/bytes payloads are rejected"
            )
        payload = _freeze_mapping(self.payload, "payload")
        if not payload:
            raise AstError(
                "LogicExtensionNode.payload must not be empty; "
                "opaque unversioned payloads are rejected"
            )
        # Disallow smuggling an unversioned blob under generic keys alone.
        opaque_only = set(payload) <= {"data", "blob", "raw", "bytes", "opaque", "value"}
        if opaque_only and "schema_version" not in payload and "kind" not in payload:
            raise AstError(
                "LogicExtensionNode.payload looks opaque/unversioned; "
                "provide a versioned structured payload (include kind or "
                "schema_version inside the payload)"
            )
        object.__setattr__(self, "payload", payload)

        children = tuple(
            item
            if isinstance(item, LogicNode)
            else LogicNode.from_dict(_require_mapping(item, "children item"))
            for item in _require_sequence(self.children, "children")
        )
        if len(children) > MAX_COLLECTION_ITEMS:
            raise AstError("LogicExtensionNode.children exceeds collection ceiling")
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "range", _optional_range(self.range, "range"))
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != LOGIC_EXTENSION_NODE_SCHEMA_VERSION:
            raise AstError(
                f"unsupported LogicExtensionNode schema_version "
                f"{self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "children": [child.to_dict() for child in self.children],
            "family": self.family.to_dict()
            if isinstance(self.family, LogicIdentity)
            else self.family,
            "features": list(self.features),
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "node_id": self.node_id,
            "payload": _thaw_mapping(self.payload),
            "payload_schema": self.payload_schema,
            "profile": self.profile.to_dict()
            if isinstance(self.profile, LogicIdentity)
            else self.profile,
            "schema_version": self.schema_version,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicExtensionNode":
        payload = _require_mapping(data, "LogicExtensionNode")
        interface = payload.get("interface")
        if interface is not None and interface != LOGIC_EXTENSION_NODE_INTERFACE:
            raise AstError(
                f"unsupported LogicExtensionNode interface {interface!r}"
            )
        return cls(
            node_id=str(payload.get("node_id") or ""),
            family=payload.get("family") or "",
            profile=payload.get("profile") or "",
            features=tuple(payload.get("features") or ()),
            payload_schema=str(payload.get("payload_schema") or ""),
            payload=_require_mapping(payload.get("payload") or {}, "payload"),
            children=tuple(
                LogicNode.from_dict(_require_mapping(item, "children item"))
                for item in _require_sequence(
                    payload.get("children") or (), "children"
                )
            ),
            range=payload.get("range"),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or LOGIC_EXTENSION_NODE_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# LogicNode (core term / formula)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicNode:
    """One immutable core term or formula node.

    Shape invariants are enforced at construction.  Signature-relative sort and
    arity checks are performed by :meth:`elaborate` / :func:`elaborate`.
    """

    node_id: str
    kind: NodeKind | str
    sort: LogicSort | None = None
    symbol: str = ""
    arguments: tuple["LogicNode", ...] = ()
    binders: tuple[Binder, ...] = ()
    extension: LogicExtensionNode | None = None
    range: SourceRange | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOGIC_NODE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _record_id(self.node_id, "node_id"))
        kind = _node_kind(self.kind)
        object.__setattr__(self, "kind", kind)

        sort = _optional_sort(self.sort, "sort")
        object.__setattr__(self, "sort", sort)

        symbol = self.symbol
        if symbol:
            symbol = _symbol_name(symbol, "symbol")
        else:
            symbol = ""
        object.__setattr__(self, "symbol", symbol)

        arguments = tuple(
            item
            if isinstance(item, LogicNode)
            else LogicNode.from_dict(_require_mapping(item, "arguments item"))
            for item in _require_sequence(self.arguments, "arguments")
        )
        if len(arguments) > MAX_COLLECTION_ITEMS:
            raise AstError("LogicNode.arguments exceeds collection ceiling")
        object.__setattr__(self, "arguments", arguments)

        binders = tuple(
            item
            if isinstance(item, Binder)
            else Binder.from_dict(_require_mapping(item, "binders item"))
            for item in _require_sequence(self.binders, "binders")
        )
        if len(binders) > MAX_COLLECTION_ITEMS:
            raise AstError("LogicNode.binders exceeds collection ceiling")
        binder_names = [item.name for item in binders]
        if len(binder_names) != len(set(binder_names)):
            raise AstError("LogicNode.binders must have unique names within a binder list")
        object.__setattr__(self, "binders", binders)

        extension = self.extension
        if extension is not None and not isinstance(extension, LogicExtensionNode):
            extension = LogicExtensionNode.from_dict(
                _require_mapping(extension, "extension")
            )
        object.__setattr__(self, "extension", extension)
        object.__setattr__(self, "range", _optional_range(self.range, "range"))
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != LOGIC_NODE_SCHEMA_VERSION:
            raise AstError(
                f"unsupported LogicNode schema_version {self.schema_version!r}"
            )

        self._validate_shape()

    # -- category / classification -----------------------------------------

    @property
    def category(self) -> ExprCategory:
        kind = self.kind
        if kind is NodeKind.LET or kind == NodeKind.LET.value:
            # Polymorphic: follow the body category when available.
            if self.arguments and len(self.arguments) == 2:
                return self.arguments[1].category
            if self.sort is not None and self.sort.is_bool:
                return ExprCategory.FORMULA
            return ExprCategory.TERM
        if isinstance(kind, NodeKind):
            if kind in _TERM_KINDS:
                return ExprCategory.TERM
            if kind in _FORMULA_KINDS:
                return ExprCategory.FORMULA
        if kind == NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return ExprCategory.FORMULA
        raise AstError(f"unknown node kind category for {kind!r}")

    @property
    def is_term(self) -> bool:
        return self.category is ExprCategory.TERM

    @property
    def is_formula(self) -> bool:
        return self.category is ExprCategory.FORMULA

    @property
    def result_sort(self) -> LogicSort:
        if self.kind is NodeKind.LET or self.kind == NodeKind.LET.value:
            if self.sort is not None:
                return self.sort
            if self.arguments and len(self.arguments) == 2:
                return self.arguments[1].result_sort
            raise AstError(
                f"let node {self.node_id} has no sort; elaborate against a signature"
            )
        if self.is_formula:
            return BOOL_SORT
        if self.sort is None:
            raise AstError(
                f"term node {self.node_id} has no sort; elaborate against a signature"
            )
        return self.sort

    # -- shape validation --------------------------------------------------

    def _validate_shape(self) -> None:
        kind = self.kind
        if not isinstance(kind, NodeKind):
            # Open kinds only allowed when extension payload is attached.
            if self.extension is None:
                raise AstError(
                    f"open node kind {kind!r} requires an extension payload"
                )
            return

        if kind in _TERM_KINDS:
            self._validate_term_shape(kind)
        elif kind in _NULLARY_FORMULAS:
            if self.symbol or self.arguments or self.binders or self.extension:
                raise AstError(f"{kind.value} takes no symbol, arguments, or binders")
            object.__setattr__(self, "sort", BOOL_SORT)
        elif kind is NodeKind.PREDICATE:
            if not self.symbol:
                raise AstError("predicate requires a symbol")
            if self.binders or self.extension:
                raise AstError("predicate takes no binders or extension")
            object.__setattr__(self, "sort", BOOL_SORT)
        elif kind is NodeKind.EQUALITY:
            if len(self.arguments) != 2:
                raise AstError("equality requires exactly two arguments")
            if self.symbol or self.binders or self.extension:
                raise AstError("equality takes no symbol, binders, or extension")
            left, right = self.arguments
            if not left.is_term or not right.is_term:
                raise AstError("equality arguments must be terms")
            object.__setattr__(self, "sort", BOOL_SORT)
        elif kind in _UNARY_CONNECTIVES:
            if len(self.arguments) != 1:
                raise AstError(f"{kind.value} requires exactly one argument")
            if self.symbol or self.binders or self.extension:
                raise AstError(f"{kind.value} takes no symbol, binders, or extension")
            if not self.arguments[0].is_formula:
                raise AstError(f"{kind.value} argument must be a formula")
            object.__setattr__(self, "sort", BOOL_SORT)
        elif kind in _BINARY_CONNECTIVES:
            if len(self.arguments) != 2:
                raise AstError(f"{kind.value} requires exactly two arguments")
            if self.symbol or self.binders or self.extension:
                raise AstError(f"{kind.value} takes no symbol, binders, or extension")
            if not all(arg.is_formula for arg in self.arguments):
                raise AstError(f"{kind.value} arguments must be formulas")
            object.__setattr__(self, "sort", BOOL_SORT)
        elif kind in _NARY_CONNECTIVES:
            if len(self.arguments) < 2:
                raise AstError(f"{kind.value} requires at least two arguments")
            if self.symbol or self.binders or self.extension:
                raise AstError(f"{kind.value} takes no symbol, binders, or extension")
            if not all(arg.is_formula for arg in self.arguments):
                raise AstError(f"{kind.value} arguments must be formulas")
            object.__setattr__(self, "sort", BOOL_SORT)
        elif kind in _QUANTIFIERS:
            if not self.binders:
                raise AstError(f"{kind.value} requires at least one binder")
            if len(self.arguments) != 1:
                raise AstError(f"{kind.value} requires exactly one body formula")
            if self.symbol or self.extension:
                raise AstError(f"{kind.value} takes no symbol or extension")
            if not self.arguments[0].is_formula:
                raise AstError(f"{kind.value} body must be a formula")
            object.__setattr__(self, "sort", BOOL_SORT)
        elif kind is NodeKind.LET:
            if len(self.binders) != 1:
                raise AstError("let requires exactly one binder")
            if len(self.arguments) != 2:
                raise AstError("let requires a bound value and a body")
            if self.symbol or self.extension:
                raise AstError("let takes no symbol or extension")
            value, body = self.arguments
            if not value.is_term:
                raise AstError("let bound value must be a term")
            if value.sort is not None and value.sort != self.binders[0].sort:
                raise AstError(
                    f"let binder sort {self.binders[0].sort!s} does not match "
                    f"bound value sort {value.sort!s}"
                )
            # Body may be term or formula; result sort follows body.
            if body.is_formula:
                object.__setattr__(self, "sort", BOOL_SORT)
            elif body.sort is not None:
                object.__setattr__(self, "sort", body.sort)
        elif kind is NodeKind.EXTENSION:
            if self.extension is None:
                raise AstError("extension node requires an extension payload")
            if self.symbol:
                raise AstError("extension node takes no symbol")
            # Binders are admitted when a schema-governed extension declares
            # binder positions (validated by ExtensionSchemaRegistry@1).
            # Children live on the extension payload; arguments optional sugar.
            if self.sort is None:
                object.__setattr__(self, "sort", BOOL_SORT)
            elif self.sort.is_bool is False and self.sort is not None:
                # Non-Bool result sorts are reserved for term-category extensions.
                pass
        else:
            raise AstError(f"unhandled node kind {kind!r}")

    def _validate_term_shape(self, kind: NodeKind) -> None:
        if kind is NodeKind.CONSTANT:
            if not self.symbol:
                raise AstError("constant requires a symbol")
            if self.arguments or self.binders or self.extension:
                raise AstError("constant takes no arguments, binders, or extension")
            if self.sort is not None and self.sort.is_bool:
                raise AstError("constant sort must not be Bool")
        elif kind is NodeKind.VARIABLE:
            if not self.symbol:
                raise AstError("variable requires a symbol")
            if self.arguments or self.binders or self.extension:
                raise AstError("variable takes no arguments, binders, or extension")
            if self.sort is not None and self.sort.is_bool:
                raise AstError("variable sort must not be Bool")
        elif kind is NodeKind.APPLICATION:
            if not self.symbol:
                raise AstError("application requires a function symbol")
            if not self.arguments:
                raise AstError(
                    "application requires at least one argument "
                    "(use constant for nullary symbols)"
                )
            if self.binders or self.extension:
                raise AstError("application takes no binders or extension")
            if not all(arg.is_term for arg in self.arguments):
                raise AstError("application arguments must be terms")
            if self.sort is not None and self.sort.is_bool:
                raise AstError(
                    "application result sort must not be Bool "
                    "(use predicate for Boolean applications)"
                )

    # -- traversal ---------------------------------------------------------

    def children(self) -> tuple["LogicNode", ...]:
        if self.extension is not None:
            return (*self.arguments, *self.extension.children)
        return self.arguments

    def walk(self) -> Iterator["LogicNode"]:
        yield self
        for child in self.children():
            yield from child.walk()

    def free_variable_names(self) -> frozenset[str]:
        """Syntactic free variable names (no signature required)."""

        return frozenset(self._free_vars(bound=frozenset()))

    def _free_vars(self, *, bound: frozenset[str]) -> set[str]:
        kind = self.kind
        if kind is NodeKind.VARIABLE:
            return set() if self.symbol in bound else {self.symbol}
        if kind is NodeKind.CONSTANT:
            return set()
        if kind in _QUANTIFIERS:
            new_bound = bound | {binder.name for binder in self.binders}
            free: set[str] = set()
            for child in self.arguments:
                free |= child._free_vars(bound=new_bound)
            return free
        if kind is NodeKind.LET:
            binder = self.binders[0]
            value_free = self.arguments[0]._free_vars(bound=bound)
            body_free = self.arguments[1]._free_vars(bound=bound | {binder.name})
            return value_free | body_free
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            # Schema-governed binders scope over extension children.
            child_bound = bound | {binder.name for binder in self.binders}
            free: set[str] = set()
            for child in self.children():
                free |= child._free_vars(bound=child_bound)
            return free
        free = set()
        for child in self.children():
            free |= child._free_vars(bound=bound)
        return free

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "arguments": [item.to_dict() for item in self.arguments],
            "binders": [item.to_dict() for item in self.binders],
            "kind": self.kind.value if isinstance(self.kind, NodeKind) else self.kind,
            "metadata": _thaw_mapping(self.metadata),
            "node_id": self.node_id,
            "schema_version": self.schema_version,
            "symbol": self.symbol,
        }
        if self.sort is not None:
            payload["sort"] = self.sort.to_dict()
        if self.extension is not None:
            payload["extension"] = self.extension.to_dict()
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicNode":
        payload = _require_mapping(data, "LogicNode")
        extension_payload = payload.get("extension")
        return cls(
            node_id=str(payload.get("node_id") or ""),
            kind=str(payload.get("kind") or ""),
            sort=payload.get("sort"),
            symbol=str(payload.get("symbol") or ""),
            arguments=tuple(
                LogicNode.from_dict(_require_mapping(item, "arguments item"))
                for item in _require_sequence(
                    payload.get("arguments") or (), "arguments"
                )
            ),
            binders=tuple(
                Binder.from_dict(_require_mapping(item, "binders item"))
                for item in _require_sequence(payload.get("binders") or (), "binders")
            ),
            extension=(
                LogicExtensionNode.from_dict(
                    _require_mapping(extension_payload, "extension")
                )
                if extension_payload is not None
                else None
            ),
            range=payload.get("range"),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or LOGIC_NODE_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------


def mk_constant(
    node_id: str,
    symbol: str,
    sort: LogicSort,
    *,
    range: SourceRange | None = None,
) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.CONSTANT,
        symbol=symbol,
        sort=sort,
        range=range,
    )


def mk_variable(
    node_id: str,
    symbol: str,
    sort: LogicSort,
    *,
    range: SourceRange | None = None,
) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.VARIABLE,
        symbol=symbol,
        sort=sort,
        range=range,
    )


def mk_application(
    node_id: str,
    symbol: str,
    arguments: Sequence[LogicNode],
    *,
    sort: LogicSort | None = None,
    range: SourceRange | None = None,
) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.APPLICATION,
        symbol=symbol,
        arguments=tuple(arguments),
        sort=sort,
        range=range,
    )


def mk_true(node_id: str = "node:true") -> LogicNode:
    return LogicNode(node_id=node_id, kind=NodeKind.TRUE, sort=BOOL_SORT)


def mk_false(node_id: str = "node:false") -> LogicNode:
    return LogicNode(node_id=node_id, kind=NodeKind.FALSE, sort=BOOL_SORT)


def mk_predicate(
    node_id: str,
    symbol: str,
    arguments: Sequence[LogicNode] = (),
    *,
    range: SourceRange | None = None,
) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.PREDICATE,
        symbol=symbol,
        arguments=tuple(arguments),
        sort=BOOL_SORT,
        range=range,
    )


def mk_equality(
    node_id: str,
    left: LogicNode,
    right: LogicNode,
    *,
    range: SourceRange | None = None,
) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.EQUALITY,
        arguments=(left, right),
        sort=BOOL_SORT,
        range=range,
    )


def mk_not(node_id: str, formula: LogicNode) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.NOT,
        arguments=(formula,),
        sort=BOOL_SORT,
    )


def mk_and(node_id: str, *formulas: LogicNode) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.AND,
        arguments=tuple(formulas),
        sort=BOOL_SORT,
    )


def mk_or(node_id: str, *formulas: LogicNode) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.OR,
        arguments=tuple(formulas),
        sort=BOOL_SORT,
    )


def mk_implies(node_id: str, antecedent: LogicNode, consequent: LogicNode) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.IMPLIES,
        arguments=(antecedent, consequent),
        sort=BOOL_SORT,
    )


def mk_iff(node_id: str, left: LogicNode, right: LogicNode) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.IFF,
        arguments=(left, right),
        sort=BOOL_SORT,
    )


def mk_forall(
    node_id: str,
    binders: Sequence[Binder],
    body: LogicNode,
) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.FORALL,
        binders=tuple(binders),
        arguments=(body,),
        sort=BOOL_SORT,
    )


def mk_exists(
    node_id: str,
    binders: Sequence[Binder],
    body: LogicNode,
) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.EXISTS,
        binders=tuple(binders),
        arguments=(body,),
        sort=BOOL_SORT,
    )


def mk_let(
    node_id: str,
    binder: Binder,
    value: LogicNode,
    body: LogicNode,
) -> LogicNode:
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.LET,
        binders=(binder,),
        arguments=(value, body),
    )


def mk_extension(
    node_id: str,
    *,
    family: LogicIdentity | Mapping[str, Any] | str,
    profile: LogicIdentity | Mapping[str, Any] | str,
    features: Sequence[str],
    payload_schema: str,
    payload: Mapping[str, Any],
    children: Sequence[LogicNode] = (),
    binders: Sequence[Binder] = (),
    sort: LogicSort | None = None,
    range: SourceRange | None = None,
) -> LogicNode:
    """Build an extension node.

    *binders* and non-Bool *sort* are reserved for schema-governed extension
    kinds registered with ``ExtensionSchemaRegistry@1``.
    """

    extension = LogicExtensionNode(
        node_id=f"{node_id}:ext",
        family=family,
        profile=profile,
        features=tuple(features),
        payload_schema=payload_schema,
        payload=payload,
        children=tuple(children),
        range=range,
    )
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.EXTENSION,
        extension=extension,
        binders=tuple(binders),
        sort=BOOL_SORT if sort is None else sort,
        range=range,
    )


# ---------------------------------------------------------------------------
# Elaboration against a signature
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ElaborationContext:
    """Local binder environment layered over a signature.

    Optional ``extension_registry`` enables schema-governed validation of
    ``LogicExtensionNode`` payloads during elaboration (LFP2-006).
    """

    signature: LogicSignature
    locals: Mapping[str, LogicSort] = field(default_factory=dict)
    extension_registry: Any | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.signature, LogicSignature):
            raise AstError("ElaborationContext.signature must be a LogicSignature")
        frozen: dict[str, LogicSort] = {}
        for name, sort in dict(self.locals).items():
            key = _symbol_name(name, "locals key")
            if not isinstance(sort, LogicSort):
                sort = LogicSort.from_dict(_require_mapping(sort, "locals value"))
            frozen[key] = sort
        object.__setattr__(self, "locals", MappingProxyType(frozen))

    def extend(self, binders: Sequence[Binder]) -> "ElaborationContext":
        merged = dict(self.locals)
        for binder in binders:
            if binder.name in merged:
                # Shadowing is allowed; innermost wins.
                pass
            merged[binder.name] = binder.sort
        return ElaborationContext(
            signature=self.signature,
            locals=merged,
            extension_registry=self.extension_registry,
        )

    def lookup_var(self, name: str) -> LogicSort | None:
        return self.locals.get(name)


def elaborate_node(
    node: LogicNode,
    context: ElaborationContext,
) -> LogicNode:
    """Elaborate *node* under *context*, returning a sort-annotated copy.

    Sort, arity, and signature invariants fail here when not already rejected
    at construction.
    """

    if not isinstance(node, LogicNode):
        raise AstError("elaborate_node requires a LogicNode")
    kind = node.kind
    signature = context.signature

    if kind is NodeKind.CONSTANT:
        decl = signature.require_symbol(
            node.symbol, kind=SymbolKind.CONSTANT, arity=0
        )
        result_sort = decl.result_sort
        if node.sort is not None and node.sort != result_sort:
            raise AstError(
                f"constant {node.symbol!r} annotated with sort {node.sort!s} "
                f"but signature declares {result_sort!s}"
            )
        return LogicNode(
            node_id=node.node_id,
            kind=NodeKind.CONSTANT,
            symbol=node.symbol,
            sort=result_sort,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    if kind is NodeKind.VARIABLE:
        local = context.lookup_var(node.symbol)
        if local is not None:
            result_sort = local
        else:
            # Free variables may be declared as constants in the signature.
            if signature.has_symbol(node.symbol):
                decl = signature.get_symbol(node.symbol)
                if decl.kind is SymbolKind.CONSTANT:
                    result_sort = decl.result_sort
                else:
                    raise AstError(
                        f"variable {node.symbol!r} resolves to non-constant "
                        f"symbol of kind {decl.kind.value!r}"
                    )
            else:
                if node.sort is None:
                    raise AstError(
                        f"free variable {node.symbol!r} is not bound and has no sort"
                    )
                result_sort = node.sort
        if node.sort is not None and node.sort != result_sort:
            raise AstError(
                f"variable {node.symbol!r} annotated with sort {node.sort!s} "
                f"but environment has {result_sort!s}"
            )
        return LogicNode(
            node_id=node.node_id,
            kind=NodeKind.VARIABLE,
            symbol=node.symbol,
            sort=result_sort,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    if kind is NodeKind.APPLICATION:
        elaborated_args = tuple(
            elaborate_node(arg, context) for arg in node.arguments
        )
        arg_sorts = tuple(arg.result_sort for arg in elaborated_args)
        try:
            result_sort = signature.check_application(
                node.symbol,
                arg_sorts,
                expected_kind=SymbolKind.FUNCTION,
            )
        except SignatureError as error:
            raise AstError(str(error)) from error
        if node.sort is not None and node.sort != result_sort:
            raise AstError(
                f"application {node.symbol!r} annotated with sort {node.sort!s} "
                f"but signature declares {result_sort!s}"
            )
        return LogicNode(
            node_id=node.node_id,
            kind=NodeKind.APPLICATION,
            symbol=node.symbol,
            arguments=elaborated_args,
            sort=result_sort,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    if kind in _NULLARY_FORMULAS:
        return LogicNode(
            node_id=node.node_id,
            kind=kind,
            sort=BOOL_SORT,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    if kind is NodeKind.PREDICATE:
        elaborated_args = tuple(
            elaborate_node(arg, context) for arg in node.arguments
        )
        arg_sorts = tuple(arg.result_sort for arg in elaborated_args)
        try:
            signature.check_application(
                node.symbol,
                arg_sorts,
                expected_kind=SymbolKind.PREDICATE,
            )
        except SignatureError as error:
            raise AstError(str(error)) from error
        return LogicNode(
            node_id=node.node_id,
            kind=NodeKind.PREDICATE,
            symbol=node.symbol,
            arguments=elaborated_args,
            sort=BOOL_SORT,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    if kind is NodeKind.EQUALITY:
        left = elaborate_node(node.arguments[0], context)
        right = elaborate_node(node.arguments[1], context)
        if left.result_sort != right.result_sort:
            raise AstError(
                f"equality sort mismatch: {left.result_sort!s} vs "
                f"{right.result_sort!s}"
            )
        return LogicNode(
            node_id=node.node_id,
            kind=NodeKind.EQUALITY,
            arguments=(left, right),
            sort=BOOL_SORT,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    if kind in _UNARY_CONNECTIVES | _BINARY_CONNECTIVES | _NARY_CONNECTIVES:
        elaborated_args = tuple(
            elaborate_node(arg, context) for arg in node.arguments
        )
        for arg in elaborated_args:
            if not arg.is_formula:
                raise AstError(f"{kind.value} argument must elaborate to a formula")
        return LogicNode(
            node_id=node.node_id,
            kind=kind,
            arguments=elaborated_args,
            sort=BOOL_SORT,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    if kind in _QUANTIFIERS:
        # Binders must reference sorts present in the signature.
        for binder in node.binders:
            if not signature.has_sort(binder.sort.name):
                # Allow structural sorts that match declared ones by rebuild.
                try:
                    declared = signature.get_sort(binder.sort.name)
                except SignatureError as error:
                    raise AstError(
                        f"quantifier binder {binder.name!r} uses undeclared "
                        f"sort {binder.sort.name!r}"
                    ) from error
                if declared != binder.sort:
                    raise AstError(
                        f"quantifier binder {binder.name!r} sort does not match "
                        f"signature"
                    )
            else:
                declared = signature.get_sort(binder.sort.name)
                if (
                    declared.kind != binder.sort.kind
                    or declared.arguments != binder.sort.arguments
                ):
                    raise AstError(
                        f"quantifier binder {binder.name!r} sort does not match "
                        f"signature"
                    )
        inner = context.extend(node.binders)
        body = elaborate_node(node.arguments[0], inner)
        if not body.is_formula:
            raise AstError(f"{kind.value} body must elaborate to a formula")
        return LogicNode(
            node_id=node.node_id,
            kind=kind,
            binders=node.binders,
            arguments=(body,),
            sort=BOOL_SORT,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    if kind is NodeKind.LET:
        binder = node.binders[0]
        if not signature.has_sort(binder.sort.name):
            raise AstError(
                f"let binder {binder.name!r} uses undeclared sort "
                f"{binder.sort.name!r}"
            )
        value = elaborate_node(node.arguments[0], context)
        if value.result_sort != binder.sort:
            raise AstError(
                f"let binder sort {binder.sort!s} does not match bound value "
                f"sort {value.result_sort!s}"
            )
        body = elaborate_node(node.arguments[1], context.extend((binder,)))
        result_sort = BOOL_SORT if body.is_formula else body.result_sort
        return LogicNode(
            node_id=node.node_id,
            kind=NodeKind.LET,
            binders=(binder,),
            arguments=(value, body),
            sort=result_sort,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    if kind is NodeKind.EXTENSION:
        if node.extension is None:
            raise AstError("extension node missing payload during elaboration")
        # Extension binders extend the local environment for children.
        child_context = (
            context.extend(node.binders) if node.binders else context
        )
        elaborated_children = tuple(
            elaborate_node(child, child_context)
            for child in node.extension.children
        )
        # Schema-governed path: validate payload/children/binders and apply
        # registered sort + payload codec when a registry is bound.
        registry = context.extension_registry
        if registry is not None:
            elaborate_extension = getattr(registry, "elaborate_extension", None)
            if elaborate_extension is None:
                raise AstError(
                    "extension_registry must provide elaborate_extension"
                )
            try:
                return elaborate_extension(
                    node, elaborated_children=elaborated_children
                )
            except Exception as error:
                # Preserve AstError identity for callers; wrap others.
                if isinstance(error, AstError):
                    raise
                raise AstError(str(error)) from error

        extension = LogicExtensionNode(
            node_id=node.extension.node_id,
            family=node.extension.family,
            profile=node.extension.profile,
            features=node.extension.features,
            payload_schema=node.extension.payload_schema,
            payload=_thaw_mapping(node.extension.payload),
            children=elaborated_children,
            range=node.extension.range,
            metadata=_thaw_mapping(node.extension.metadata),
        )
        result_sort = node.sort if node.sort is not None else BOOL_SORT
        return LogicNode(
            node_id=node.node_id,
            kind=NodeKind.EXTENSION,
            extension=extension,
            binders=node.binders,
            sort=result_sort,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    raise AstError(f"cannot elaborate node kind {kind!r}")


def elaborate(
    node: LogicNode,
    signature: LogicSignature,
    *,
    locals: Mapping[str, LogicSort] | None = None,
    extension_registry: Any | None = None,
) -> LogicNode:
    """Elaborate *node* against *signature*; fail closed on sort/arity errors.

    When *extension_registry* is provided, extension nodes are validated and
    sort-annotated through ``ExtensionSchemaRegistry@1``.
    """

    context = ElaborationContext(
        signature=signature,
        locals=dict(locals or {}),
        extension_registry=extension_registry,
    )
    return elaborate_node(node, context)


# ---------------------------------------------------------------------------
# TypedExpression@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedExpression:
    """Signature-bound, content-identified typed expression.

    Interface: ``TypedExpression@1``.

    Construction elaborates the root against the signature so that sort/arity
    invariants fail at the TypedExpression boundary when not already rejected
    by node construction.
    """

    expression_id: str
    root: LogicNode
    signature: LogicSignature
    family: LogicIdentity | Mapping[str, Any] | str | None = None
    profile: LogicIdentity | Mapping[str, Any] | str | None = None
    content_digest: str = ""
    range: SourceRange | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = TYPED_EXPRESSION_SCHEMA_VERSION
    elaborate_on_init: bool = True

    interface: ClassVar[str] = TYPED_EXPRESSION_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "expression_id", _record_id(self.expression_id, "expression_id")
        )
        if not isinstance(self.signature, LogicSignature):
            if isinstance(self.signature, Mapping):
                object.__setattr__(
                    self, "signature", LogicSignature.from_dict(self.signature)
                )
            else:
                raise AstError("TypedExpression.signature must be a LogicSignature")

        family = self.family
        if family is None:
            family = self.signature.family
        object.__setattr__(
            self,
            "family",
            require_namespace_identity(family, NamespaceKind.FAMILY, "family"),
        )
        profile = self.profile
        if profile is None:
            profile = self.signature.profile
        object.__setattr__(
            self,
            "profile",
            require_namespace_identity(profile, NamespaceKind.PROFILE, "profile"),
        )

        # Family/profile on the expression must agree with the signature.
        if (
            isinstance(self.family, LogicIdentity)
            and isinstance(self.signature.family, LogicIdentity)
            and self.family.value != self.signature.family.value
        ):
            raise AstError(
                f"TypedExpression.family {self.family.qualified!r} does not "
                f"match signature family {self.signature.family.qualified!r}"
            )
        if (
            isinstance(self.profile, LogicIdentity)
            and isinstance(self.signature.profile, LogicIdentity)
            and self.profile.value != self.signature.profile.value
        ):
            raise AstError(
                f"TypedExpression.profile {self.profile.qualified!r} does not "
                f"match signature profile {self.signature.profile.qualified!r}"
            )

        root = self.root
        if not isinstance(root, LogicNode):
            root = LogicNode.from_dict(_require_mapping(root, "root"))
        if self.elaborate_on_init:
            root = elaborate(root, self.signature)
        if not root.is_formula and root.sort is None:
            raise AstError("TypedExpression root term must have a sort after elaboration")
        object.__setattr__(self, "root", root)
        # elaborate_on_init is a construction flag, not part of identity.
        object.__setattr__(self, "elaborate_on_init", True)

        object.__setattr__(self, "range", _optional_range(self.range, "range"))
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )

        digest = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _text(self.content_digest, "content_digest", maximum=64)
            if not re.fullmatch(r"^[0-9a-f]{64}$", provided):
                raise AstError(
                    "content_digest must be a lowercase 64-hex sha256 digest"
                )
            if provided != digest:
                raise AstError("content_digest does not match TypedExpression content")
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", digest)

        if self.schema_version != TYPED_EXPRESSION_SCHEMA_VERSION:
            raise AstError(
                f"unsupported TypedExpression schema_version "
                f"{self.schema_version!r}"
            )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "expression_id": self.expression_id,
            "family": self.family.to_dict()
            if isinstance(self.family, LogicIdentity)
            else self.family,
            "interface": self.interface,
            "profile": self.profile.to_dict()
            if isinstance(self.profile, LogicIdentity)
            else self.profile,
            "root": self.root.to_dict(),
            "schema_version": self.schema_version,
            "signature": self.signature.to_dict(),
        }

    @property
    def is_formula(self) -> bool:
        return self.root.is_formula

    @property
    def is_term(self) -> bool:
        return self.root.is_term

    @property
    def result_sort(self) -> LogicSort:
        return self.root.result_sort

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "content_digest": self.content_digest,
            "expression_id": self.expression_id,
            "family": self.family.to_dict()
            if isinstance(self.family, LogicIdentity)
            else self.family,
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "profile": self.profile.to_dict()
            if isinstance(self.profile, LogicIdentity)
            else self.profile,
            "root": self.root.to_dict(),
            "schema_version": self.schema_version,
            "signature": self.signature.to_dict(),
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TypedExpression":
        payload = _require_mapping(data, "TypedExpression")
        interface = payload.get("interface")
        if interface is not None and interface != TYPED_EXPRESSION_INTERFACE:
            raise AstError(
                f"unsupported TypedExpression interface {interface!r}"
            )
        return cls(
            expression_id=str(payload.get("expression_id") or ""),
            root=LogicNode.from_dict(_require_mapping(payload.get("root"), "root")),
            signature=LogicSignature.from_dict(
                _require_mapping(payload.get("signature"), "signature")
            ),
            family=payload.get("family"),
            profile=payload.get("profile"),
            content_digest=str(payload.get("content_digest") or ""),
            range=payload.get("range"),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or TYPED_EXPRESSION_SCHEMA_VERSION
            ),
        )


__all__ = [
    "AST_MODULE_VERSION",
    "BINDER_SCHEMA_VERSION",
    "LOGIC_EXTENSION_NODE_INTERFACE",
    "LOGIC_EXTENSION_NODE_SCHEMA_VERSION",
    "LOGIC_NODE_SCHEMA_VERSION",
    "TYPED_EXPRESSION_INTERFACE",
    "TYPED_EXPRESSION_SCHEMA_VERSION",
    "AstError",
    "Binder",
    "ElaborationContext",
    "ExprCategory",
    "LogicExtensionNode",
    "LogicNode",
    "NodeKind",
    "TypedExpression",
    "elaborate",
    "elaborate_node",
    "mk_and",
    "mk_application",
    "mk_constant",
    "mk_equality",
    "mk_exists",
    "mk_extension",
    "mk_false",
    "mk_forall",
    "mk_iff",
    "mk_implies",
    "mk_let",
    "mk_not",
    "mk_or",
    "mk_predicate",
    "mk_true",
    "mk_variable",
]

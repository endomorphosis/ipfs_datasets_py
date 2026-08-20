"""Capture-avoiding substitution, alpha-equivalence, and free/bound analysis.

Interfaces (LFP-013):

* ``LogicExpressionAlgebra@1`` — shared safe binding operations for core AST
  nodes: free/bound variables, alpha-equivalence, semantic identity, and
  capture-avoiding substitution under explicit traversal bounds.

All operations are side-effect free and fail closed when resource limits are
exceeded.  Substitution never captures free variables of the replacement term.
Alpha-equivalent expressions share the same semantic identity digest.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.ast import (
    Binder,
    LogicExtensionNode,
    LogicNode,
    NodeKind,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_COLLECTION_ITEMS,
    MAX_CST_NODES,
    MAX_PARSE_DEPTH,
    SyntaxContractError,
    _freeze_mapping,
    _positive_int,
    _require_mapping,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)
from ipfs_datasets_py.logic.syntax_core.signatures import _symbol_name

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_EXPRESSION_ALGEBRA_INTERFACE: Final = "LogicExpressionAlgebra@1"
ALGEBRA_MODULE_VERSION: Final = "1.0.0"
ALGEBRA_LIMITS_SCHEMA_VERSION: Final = "syntax-algebra-limits/v1"

# Hard ceilings (callers may only tighten).
MAX_ALGEBRA_NODES: Final = MAX_CST_NODES
MAX_ALGEBRA_DEPTH: Final = MAX_PARSE_DEPTH
MAX_FRESH_ATTEMPTS: Final = 65_536

_QUANTIFIERS: Final[frozenset[NodeKind]] = frozenset(
    {NodeKind.FORALL, NodeKind.EXISTS}
)
_FRESH_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']{0,255}$")


class AlgebraError(SyntaxContractError):
    """Raised when an algebra operation is malformed or exceeds bounds."""


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlgebraLimits:
    """Finite resource bounds for algebra traversal and rewriting."""

    max_nodes: int = MAX_ALGEBRA_NODES
    max_depth: int = MAX_ALGEBRA_DEPTH
    schema_version: str = ALGEBRA_LIMITS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            max_nodes = _positive_int(
                self.max_nodes, "max_nodes", maximum=MAX_ALGEBRA_NODES
            )
            max_depth = _positive_int(
                self.max_depth, "max_depth", maximum=MAX_ALGEBRA_DEPTH
            )
        except SyntaxContractError as error:
            raise AlgebraError(str(error)) from error
        object.__setattr__(self, "max_nodes", max_nodes)
        object.__setattr__(self, "max_depth", max_depth)
        if self.schema_version != ALGEBRA_LIMITS_SCHEMA_VERSION:
            raise AlgebraError(
                f"unsupported AlgebraLimits schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AlgebraLimits":
        payload = _require_mapping(data, "AlgebraLimits")
        return cls(
            max_nodes=int(payload.get("max_nodes") or MAX_ALGEBRA_NODES),
            max_depth=int(payload.get("max_depth") or MAX_ALGEBRA_DEPTH),
            schema_version=str(
                payload.get("schema_version") or ALGEBRA_LIMITS_SCHEMA_VERSION
            ),
        )


DEFAULT_ALGEBRA_LIMITS: Final = AlgebraLimits()


# ---------------------------------------------------------------------------
# Internal counters / helpers
# ---------------------------------------------------------------------------


class _Budget:
    """Mutable visit counter enforcing node and depth ceilings."""

    __slots__ = ("limits", "nodes", "max_seen_depth")

    def __init__(self, limits: AlgebraLimits) -> None:
        self.limits = limits
        self.nodes = 0
        self.max_seen_depth = 0

    def enter(self, depth: int) -> None:
        if depth > self.limits.max_depth:
            raise AlgebraError(
                f"algebra traversal depth {depth} exceeds limit "
                f"{self.limits.max_depth}"
            )
        self.nodes += 1
        if self.nodes > self.limits.max_nodes:
            raise AlgebraError(
                f"algebra traversal node count {self.nodes} exceeds limit "
                f"{self.limits.max_nodes}"
            )
        if depth > self.max_seen_depth:
            self.max_seen_depth = depth


def _kind_of(node: LogicNode) -> NodeKind | str:
    return node.kind


def _is_quantifier(kind: NodeKind | str) -> bool:
    return kind in _QUANTIFIERS or kind in {NodeKind.FORALL.value, NodeKind.EXISTS.value}


def _is_let(kind: NodeKind | str) -> bool:
    return kind is NodeKind.LET or kind == NodeKind.LET.value


def _is_variable(kind: NodeKind | str) -> bool:
    return kind is NodeKind.VARIABLE or kind == NodeKind.VARIABLE.value


def _is_extension(kind: NodeKind | str) -> bool:
    return kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value


def _binder_names(binders: Sequence[Binder]) -> frozenset[str]:
    return frozenset(item.name for item in binders)


def _collect_names(node: LogicNode, budget: _Budget, depth: int = 0) -> set[str]:
    """Collect every variable/binder/symbol name that might collide with fresh ids."""

    budget.enter(depth)
    names: set[str] = set()
    kind = _kind_of(node)
    if _is_variable(kind) or kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
        if node.symbol:
            names.add(node.symbol)
    for binder in node.binders:
        names.add(binder.name)
    if node.symbol and not _is_variable(kind):
        # Function/predicate symbols are not variables, but avoid clashing anyway.
        names.add(node.symbol)
    for child in node.children():
        names |= _collect_names(child, budget, depth + 1)
    return names


def _fresh_name(base: str, used: set[str]) -> str:
    """Return a symbol name derived from *base* that is not in *used*."""

    candidate_base = base if _FRESH_NAME_RE.fullmatch(base) else f"_{base}"
    if not _FRESH_NAME_RE.fullmatch(candidate_base):
        candidate_base = "_v"
    # Always suffix so renamed binders never reuse a captured free name.
    for index in range(MAX_FRESH_ATTEMPTS):
        candidate = f"{candidate_base}_{index}"
        if len(candidate) > 256:
            candidate = f"_v{index}"
        if candidate not in used and _FRESH_NAME_RE.fullmatch(candidate):
            used.add(candidate)
            return candidate
    raise AlgebraError("exhausted fresh variable name space")


def _with_args(
    node: LogicNode,
    arguments: tuple[LogicNode, ...],
    *,
    binders: tuple[Binder, ...] | None = None,
    extension: LogicExtensionNode | None = None,
    node_id: str | None = None,
) -> LogicNode:
    return LogicNode(
        node_id=node_id if node_id is not None else node.node_id,
        kind=node.kind,
        sort=node.sort,
        symbol=node.symbol,
        arguments=arguments,
        binders=binders if binders is not None else node.binders,
        extension=extension if extension is not None else node.extension,
        range=None,
        metadata={},
    )


def _rename_free_in_body(
    node: LogicNode,
    old: str,
    new: str,
    *,
    bound: frozenset[str],
    budget: _Budget,
    depth: int,
    id_factory: list[int],
) -> LogicNode:
    """Rename free occurrences of *old* to *new* (not under a binder for *old*)."""

    budget.enter(depth)
    kind = _kind_of(node)

    if _is_variable(kind):
        if node.symbol == old and old not in bound:
            return LogicNode(
                node_id=_next_id(id_factory, node.node_id, "rn"),
                kind=NodeKind.VARIABLE,
                symbol=new,
                sort=node.sort,
            )
        return node

    if _is_quantifier(kind):
        binder_set = _binder_names(node.binders)
        if old in binder_set:
            return node
        new_bound = bound | binder_set
        body = _rename_free_in_body(
            node.arguments[0],
            old,
            new,
            bound=new_bound,
            budget=budget,
            depth=depth + 1,
            id_factory=id_factory,
        )
        if body is node.arguments[0]:
            return node
        return _with_args(node, (body,), node_id=_next_id(id_factory, node.node_id, "rn"))

    if _is_let(kind):
        binder = node.binders[0]
        value = _rename_free_in_body(
            node.arguments[0],
            old,
            new,
            bound=bound,
            budget=budget,
            depth=depth + 1,
            id_factory=id_factory,
        )
        if old == binder.name:
            body = node.arguments[1]
        else:
            body = _rename_free_in_body(
                node.arguments[1],
                old,
                new,
                bound=bound | {binder.name},
                budget=budget,
                depth=depth + 1,
                id_factory=id_factory,
            )
        if value is node.arguments[0] and body is node.arguments[1]:
            return node
        return _with_args(
            node,
            (value, body),
            node_id=_next_id(id_factory, node.node_id, "rn"),
        )

    if _is_extension(kind) and node.extension is not None:
        children = tuple(
            _rename_free_in_body(
                child,
                old,
                new,
                bound=bound,
                budget=budget,
                depth=depth + 1,
                id_factory=id_factory,
            )
            for child in node.extension.children
        )
        args = tuple(
            _rename_free_in_body(
                arg,
                old,
                new,
                bound=bound,
                budget=budget,
                depth=depth + 1,
                id_factory=id_factory,
            )
            for arg in node.arguments
        )
        if children == node.extension.children and args == node.arguments:
            return node
        extension = LogicExtensionNode(
            node_id=_next_id(id_factory, node.extension.node_id, "rn"),
            family=node.extension.family,
            profile=node.extension.profile,
            features=node.extension.features,
            payload_schema=node.extension.payload_schema,
            payload=_thaw_mapping(node.extension.payload),
            children=children,
        )
        return LogicNode(
            node_id=_next_id(id_factory, node.node_id, "rn"),
            kind=NodeKind.EXTENSION,
            arguments=args,
            extension=extension,
            sort=node.sort,
        )

    new_args = tuple(
        _rename_free_in_body(
            arg,
            old,
            new,
            bound=bound,
            budget=budget,
            depth=depth + 1,
            id_factory=id_factory,
        )
        for arg in node.arguments
    )
    if new_args == node.arguments:
        return node
    return _with_args(node, new_args, node_id=_next_id(id_factory, node.node_id, "rn"))


def _next_id(factory: list[int], base: str, tag: str) -> str:
    factory[0] += 1
    # Keep stable, unique record ids within the algebra rewrite.
    candidate = f"{base}:{tag}{factory[0]}"
    if len(candidate) > 256:
        candidate = f"alg:{tag}{factory[0]}"
    return candidate


# ---------------------------------------------------------------------------
# Free / bound analysis
# ---------------------------------------------------------------------------


def _free_vars(
    node: LogicNode,
    *,
    bound: frozenset[str],
    budget: _Budget,
    depth: int,
) -> set[str]:
    budget.enter(depth)
    kind = _kind_of(node)

    if _is_variable(kind):
        return set() if node.symbol in bound else {node.symbol}

    if kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
        return set()

    if kind is NodeKind.TRUE or kind is NodeKind.FALSE:
        return set()
    if kind in {NodeKind.TRUE.value, NodeKind.FALSE.value}:
        return set()

    if _is_quantifier(kind):
        new_bound = bound | _binder_names(node.binders)
        free: set[str] = set()
        for child in node.arguments:
            free |= _free_vars(child, bound=new_bound, budget=budget, depth=depth + 1)
        return free

    if _is_let(kind):
        binder = node.binders[0]
        value_free = _free_vars(
            node.arguments[0], bound=bound, budget=budget, depth=depth + 1
        )
        body_free = _free_vars(
            node.arguments[1],
            bound=bound | {binder.name},
            budget=budget,
            depth=depth + 1,
        )
        return value_free | body_free

    free = set()
    for child in node.children():
        free |= _free_vars(child, bound=bound, budget=budget, depth=depth + 1)
    return free


def _bound_vars(
    node: LogicNode,
    *,
    budget: _Budget,
    depth: int,
) -> set[str]:
    """Names introduced by binders in *node* (including shadowed binders)."""

    budget.enter(depth)
    names: set[str] = set()
    for binder in node.binders:
        names.add(binder.name)
    for child in node.children():
        names |= _bound_vars(child, budget=budget, depth=depth + 1)
    return names


# ---------------------------------------------------------------------------
# Alpha-canonical form / equivalence / semantic identity
# ---------------------------------------------------------------------------


def _alpha_canonical(
    node: LogicNode,
    *,
    env: Mapping[str, int],
    next_index: int,
    budget: _Budget,
    depth: int,
) -> Any:
    """Return a JSON-ready alpha-canonical structure (de Bruijn for bound vars).

    Free variables keep their names.  Bound variables become non-negative
    indices assigned at binder introduction (shared across a multi-binder
    quantifier list in left-to-right order).  Node ids, ranges, and metadata
    are omitted so alpha-variants share identity.
    """

    budget.enter(depth)
    kind = _kind_of(node)
    kind_key = kind.value if isinstance(kind, NodeKind) else str(kind)

    if _is_variable(kind):
        if node.symbol in env:
            return {"k": "variable", "b": env[node.symbol]}
        return {"k": "variable", "f": node.symbol}

    if kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
        payload: dict[str, Any] = {"k": "constant", "s": node.symbol}
        if node.sort is not None:
            payload["sort"] = node.sort.to_dict()
        return payload

    if kind is NodeKind.TRUE or kind == NodeKind.TRUE.value:
        return {"k": "true"}
    if kind is NodeKind.FALSE or kind == NodeKind.FALSE.value:
        return {"k": "false"}

    if _is_quantifier(kind):
        local = dict(env)
        index = next_index
        binder_sorts: list[Any] = []
        for binder in node.binders:
            local[binder.name] = index
            binder_sorts.append(binder.sort.to_dict())
            index += 1
        return {
            "k": kind_key,
            "binders": binder_sorts,
            "body": _alpha_canonical(
                node.arguments[0],
                env=local,
                next_index=index,
                budget=budget,
                depth=depth + 1,
            ),
        }

    if _is_let(kind):
        binder = node.binders[0]
        value = _alpha_canonical(
            node.arguments[0],
            env=env,
            next_index=next_index,
            budget=budget,
            depth=depth + 1,
        )
        local = dict(env)
        local[binder.name] = next_index
        body = _alpha_canonical(
            node.arguments[1],
            env=local,
            next_index=next_index + 1,
            budget=budget,
            depth=depth + 1,
        )
        return {
            "k": "let",
            "binder_sort": binder.sort.to_dict(),
            "value": value,
            "body": body,
        }

    if _is_extension(kind) and node.extension is not None:
        ext = node.extension
        family = (
            ext.family.to_dict()
            if hasattr(ext.family, "to_dict")
            else ext.family
        )
        profile = (
            ext.profile.to_dict()
            if hasattr(ext.profile, "to_dict")
            else ext.profile
        )
        return {
            "k": "extension",
            "family": family,
            "profile": profile,
            "features": list(ext.features),
            "payload_schema": ext.payload_schema,
            "payload": _thaw_mapping(ext.payload),
            "children": [
                _alpha_canonical(
                    child,
                    env=env,
                    next_index=next_index,
                    budget=budget,
                    depth=depth + 1,
                )
                for child in ext.children
            ],
            "arguments": [
                _alpha_canonical(
                    arg,
                    env=env,
                    next_index=next_index,
                    budget=budget,
                    depth=depth + 1,
                )
                for arg in node.arguments
            ],
        }

    # Applications, predicates, equality, connectives.
    result: dict[str, Any] = {"k": kind_key}
    if node.symbol:
        result["s"] = node.symbol
    if node.sort is not None and kind_key in {"application", "constant", "variable"}:
        result["sort"] = node.sort.to_dict()
    result["args"] = [
        _alpha_canonical(
            arg,
            env=env,
            next_index=next_index,
            budget=budget,
            depth=depth + 1,
        )
        for arg in node.arguments
    ]
    return result


def _alpha_equivalent(
    left: LogicNode,
    right: LogicNode,
    *,
    env_left: Mapping[str, int],
    env_right: Mapping[str, int],
    next_index: int,
    budget: _Budget,
    depth: int,
) -> bool:
    budget.enter(depth)
    lk = _kind_of(left)
    rk = _kind_of(right)

    left_key = lk.value if isinstance(lk, NodeKind) else str(lk)
    right_key = rk.value if isinstance(rk, NodeKind) else str(rk)
    if left_key != right_key:
        return False

    if _is_variable(lk):
        left_bound = left.symbol in env_left
        right_bound = right.symbol in env_right
        if left_bound != right_bound:
            return False
        if left_bound:
            return env_left[left.symbol] == env_right[right.symbol]
        return left.symbol == right.symbol

    if lk is NodeKind.CONSTANT or lk == NodeKind.CONSTANT.value:
        if left.symbol != right.symbol:
            return False
        return left.sort == right.sort

    if lk in {NodeKind.TRUE, NodeKind.FALSE} or left_key in {"true", "false"}:
        return True

    if _is_quantifier(lk):
        if len(left.binders) != len(right.binders):
            return False
        for lb, rb in zip(left.binders, right.binders):
            if lb.sort != rb.sort:
                return False
        local_l = dict(env_left)
        local_r = dict(env_right)
        index = next_index
        for lb, rb in zip(left.binders, right.binders):
            local_l[lb.name] = index
            local_r[rb.name] = index
            index += 1
        return _alpha_equivalent(
            left.arguments[0],
            right.arguments[0],
            env_left=local_l,
            env_right=local_r,
            next_index=index,
            budget=budget,
            depth=depth + 1,
        )

    if _is_let(lk):
        if left.binders[0].sort != right.binders[0].sort:
            return False
        if not _alpha_equivalent(
            left.arguments[0],
            right.arguments[0],
            env_left=env_left,
            env_right=env_right,
            next_index=next_index,
            budget=budget,
            depth=depth + 1,
        ):
            return False
        local_l = dict(env_left)
        local_r = dict(env_right)
        local_l[left.binders[0].name] = next_index
        local_r[right.binders[0].name] = next_index
        return _alpha_equivalent(
            left.arguments[1],
            right.arguments[1],
            env_left=local_l,
            env_right=local_r,
            next_index=next_index + 1,
            budget=budget,
            depth=depth + 1,
        )

    if _is_extension(lk):
        le = left.extension
        rext = right.extension
        if le is None or rext is None:
            return le is rext
        if (
            le.payload_schema != rext.payload_schema
            or list(le.features) != list(rext.features)
            or _thaw_mapping(le.payload) != _thaw_mapping(rext.payload)
        ):
            return False
        left_family = (
            le.family.to_dict() if hasattr(le.family, "to_dict") else le.family
        )
        right_family = (
            rext.family.to_dict() if hasattr(rext.family, "to_dict") else rext.family
        )
        left_profile = (
            le.profile.to_dict() if hasattr(le.profile, "to_dict") else le.profile
        )
        right_profile = (
            rext.profile.to_dict() if hasattr(rext.profile, "to_dict") else rext.profile
        )
        if left_family != right_family or left_profile != right_profile:
            return False
        if len(le.children) != len(rext.children):
            return False
        if len(left.arguments) != len(right.arguments):
            return False
        for lc, rc in zip(le.children, rext.children):
            if not _alpha_equivalent(
                lc,
                rc,
                env_left=env_left,
                env_right=env_right,
                next_index=next_index,
                budget=budget,
                depth=depth + 1,
            ):
                return False
        for la, ra in zip(left.arguments, right.arguments):
            if not _alpha_equivalent(
                la,
                ra,
                env_left=env_left,
                env_right=env_right,
                next_index=next_index,
                budget=budget,
                depth=depth + 1,
            ):
                return False
        return True

    if left.symbol != right.symbol:
        return False
    if len(left.arguments) != len(right.arguments):
        return False
    # Application result sorts participate in structure when present.
    if left_key == "application" and left.sort != right.sort:
        return False
    for la, ra in zip(left.arguments, right.arguments):
        if not _alpha_equivalent(
            la,
            ra,
            env_left=env_left,
            env_right=env_right,
            next_index=next_index,
            budget=budget,
            depth=depth + 1,
        ):
            return False
    return True


# ---------------------------------------------------------------------------
# Capture-avoiding substitution
# ---------------------------------------------------------------------------


def _substitute(
    node: LogicNode,
    var: str,
    replacement: LogicNode,
    *,
    free_of_replacement: frozenset[str],
    used_names: set[str],
    budget: _Budget,
    depth: int,
    id_factory: list[int],
) -> LogicNode:
    """Capture-avoiding substitution of free *var* by *replacement* in *node*."""

    budget.enter(depth)
    kind = _kind_of(node)

    if _is_variable(kind):
        if node.symbol == var:
            return replacement
        return node

    if kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
        return node
    if kind is NodeKind.TRUE or kind is NodeKind.FALSE:
        return node
    if kind in {NodeKind.TRUE.value, NodeKind.FALSE.value}:
        return node

    if _is_quantifier(kind):
        binder_set = _binder_names(node.binders)
        if var in binder_set:
            # Variable is shadowed; body is untouched.
            return node

        binders = list(node.binders)
        body = node.arguments[0]
        # Alpha-rename any binder that would capture a free var of replacement.
        for index, binder in enumerate(list(binders)):
            if binder.name in free_of_replacement:
                fresh = _fresh_name(binder.name, used_names)
                body = _rename_free_in_body(
                    body,
                    binder.name,
                    fresh,
                    bound=frozenset(),
                    budget=budget,
                    depth=depth + 1,
                    id_factory=id_factory,
                )
                binders[index] = Binder(name=fresh, sort=binder.sort)

        new_body = _substitute(
            body,
            var,
            replacement,
            free_of_replacement=free_of_replacement,
            used_names=used_names,
            budget=budget,
            depth=depth + 1,
            id_factory=id_factory,
        )
        if new_body is node.arguments[0] and tuple(binders) == node.binders:
            return node
        return _with_args(
            node,
            (new_body,),
            binders=tuple(binders),
            node_id=_next_id(id_factory, node.node_id, "sub"),
        )

    if _is_let(kind):
        binder = node.binders[0]
        # Value is outside the binder scope.
        new_value = _substitute(
            node.arguments[0],
            var,
            replacement,
            free_of_replacement=free_of_replacement,
            used_names=used_names,
            budget=budget,
            depth=depth + 1,
            id_factory=id_factory,
        )
        if var == binder.name:
            # Shadowed in body.
            if new_value is node.arguments[0]:
                return node
            return _with_args(
                node,
                (new_value, node.arguments[1]),
                node_id=_next_id(id_factory, node.node_id, "sub"),
            )

        body = node.arguments[1]
        binders = node.binders
        if binder.name in free_of_replacement:
            fresh = _fresh_name(binder.name, used_names)
            body = _rename_free_in_body(
                body,
                binder.name,
                fresh,
                bound=frozenset(),
                budget=budget,
                depth=depth + 1,
                id_factory=id_factory,
            )
            binders = (Binder(name=fresh, sort=binder.sort),)

        new_body = _substitute(
            body,
            var,
            replacement,
            free_of_replacement=free_of_replacement,
            used_names=used_names,
            budget=budget,
            depth=depth + 1,
            id_factory=id_factory,
        )
        if (
            new_value is node.arguments[0]
            and new_body is node.arguments[1]
            and binders == node.binders
        ):
            return node
        return _with_args(
            node,
            (new_value, new_body),
            binders=binders,
            node_id=_next_id(id_factory, node.node_id, "sub"),
        )

    if _is_extension(kind) and node.extension is not None:
        children = tuple(
            _substitute(
                child,
                var,
                replacement,
                free_of_replacement=free_of_replacement,
                used_names=used_names,
                budget=budget,
                depth=depth + 1,
                id_factory=id_factory,
            )
            for child in node.extension.children
        )
        args = tuple(
            _substitute(
                arg,
                var,
                replacement,
                free_of_replacement=free_of_replacement,
                used_names=used_names,
                budget=budget,
                depth=depth + 1,
                id_factory=id_factory,
            )
            for arg in node.arguments
        )
        if children == node.extension.children and args == node.arguments:
            return node
        extension = LogicExtensionNode(
            node_id=_next_id(id_factory, node.extension.node_id, "sub"),
            family=node.extension.family,
            profile=node.extension.profile,
            features=node.extension.features,
            payload_schema=node.extension.payload_schema,
            payload=_thaw_mapping(node.extension.payload),
            children=children,
        )
        return LogicNode(
            node_id=_next_id(id_factory, node.node_id, "sub"),
            kind=NodeKind.EXTENSION,
            arguments=args,
            extension=extension,
            sort=node.sort,
        )

    new_args = tuple(
        _substitute(
            arg,
            var,
            replacement,
            free_of_replacement=free_of_replacement,
            used_names=used_names,
            budget=budget,
            depth=depth + 1,
            id_factory=id_factory,
        )
        for arg in node.arguments
    )
    if new_args == node.arguments:
        return node
    return _with_args(
        node,
        new_args,
        node_id=_next_id(id_factory, node.node_id, "sub"),
    )


def _walk_bounded(
    node: LogicNode,
    *,
    budget: _Budget,
    depth: int = 0,
) -> Iterator[LogicNode]:
    budget.enter(depth)
    yield node
    for child in node.children():
        yield from _walk_bounded(child, budget=budget, depth=depth + 1)


def _size(node: LogicNode, *, budget: _Budget, depth: int = 0) -> int:
    budget.enter(depth)
    total = 1
    for child in node.children():
        total += _size(child, budget=budget, depth=depth + 1)
    return total


def _depth_of(node: LogicNode, *, budget: _Budget, depth: int = 0) -> int:
    budget.enter(depth)
    children = node.children()
    if not children:
        return 1
    return 1 + max(
        _depth_of(child, budget=budget, depth=depth + 1) for child in children
    )


# ---------------------------------------------------------------------------
# LogicExpressionAlgebra@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicExpressionAlgebra:
    """Shared capture-safe binding algebra for core logic expressions.

    Interface: ``LogicExpressionAlgebra@1``.
    """

    limits: AlgebraLimits = field(default_factory=AlgebraLimits)
    algebra_id: str = "algebra:default"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "syntax-logic-expression-algebra/v1"

    interface: ClassVar[str] = LOGIC_EXPRESSION_ALGEBRA_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.limits, AlgebraLimits):
            if isinstance(self.limits, Mapping):
                object.__setattr__(
                    self, "limits", AlgebraLimits.from_dict(self.limits)
                )
            else:
                raise AlgebraError("limits must be AlgebraLimits")
        object.__setattr__(
            self,
            "algebra_id",
            _text(self.algebra_id, "algebra_id", maximum=256),
        )
        # algebra_id uses record-id style when possible; allow simple tokens.
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != "syntax-logic-expression-algebra/v1":
            raise AlgebraError(
                f"unsupported LogicExpressionAlgebra schema_version "
                f"{self.schema_version!r}"
            )

    def _budget(self) -> _Budget:
        return _Budget(self.limits)

    def _require_node(self, node: object, field_name: str = "node") -> LogicNode:
        if not isinstance(node, LogicNode):
            raise AlgebraError(f"{field_name} must be a LogicNode")
        return node

    # -- analysis ----------------------------------------------------------

    def free_variables(self, node: LogicNode) -> frozenset[str]:
        """Return free variable names in *node* under the configured limits."""

        node = self._require_node(node)
        return frozenset(
            _free_vars(node, bound=frozenset(), budget=self._budget(), depth=0)
        )

    def bound_variables(self, node: LogicNode) -> frozenset[str]:
        """Return names introduced by binders anywhere under *node*."""

        node = self._require_node(node)
        return frozenset(_bound_vars(node, budget=self._budget(), depth=0))

    def size(self, node: LogicNode) -> int:
        """Number of nodes in the tree (bounded)."""

        node = self._require_node(node)
        return _size(node, budget=self._budget(), depth=0)

    def depth(self, node: LogicNode) -> int:
        """Maximum depth of the tree (bounded); leaves have depth 1."""

        node = self._require_node(node)
        return _depth_of(node, budget=self._budget(), depth=0)

    def walk(self, node: LogicNode) -> Iterator[LogicNode]:
        """Yield nodes in pre-order under the configured limits."""

        node = self._require_node(node)
        return _walk_bounded(node, budget=self._budget(), depth=0)

    # -- alpha / identity --------------------------------------------------

    def alpha_canonical(self, node: LogicNode) -> Any:
        """Alpha-canonical JSON structure for *node* (de Bruijn bound vars)."""

        node = self._require_node(node)
        return _alpha_canonical(
            node,
            env={},
            next_index=0,
            budget=self._budget(),
            depth=0,
        )

    def semantic_identity(self, node: LogicNode) -> str:
        """SHA-256 digest of the alpha-canonical form of *node*.

        Alpha-equivalent expressions share this digest.  Node ids, source
        ranges, and metadata do not participate.
        """

        canonical = self.alpha_canonical(node)
        # Wrap as mapping for canonical_json_bytes.
        payload = {"alpha": canonical, "v": 1}
        return content_sha256(canonical_json_bytes(payload))

    def alpha_equivalent(self, left: LogicNode, right: LogicNode) -> bool:
        """Return whether *left* and *right* are alpha-equivalent."""

        left = self._require_node(left, "left")
        right = self._require_node(right, "right")
        # Single shared budget for the comparison walk.
        return _alpha_equivalent(
            left,
            right,
            env_left={},
            env_right={},
            next_index=0,
            budget=self._budget(),
            depth=0,
        )

    # -- rewriting ---------------------------------------------------------

    def alpha_rename_binder(
        self,
        node: LogicNode,
        old_name: str,
        new_name: str,
    ) -> LogicNode:
        """Rename binder *old_name* to *new_name* at the root quantifier/let.

        Only the outermost binders of *node* are considered.  Free occurrences
        of *old_name* in the body become free occurrences of *new_name*.
        """

        node = self._require_node(node)
        old = _symbol_name(old_name, "old_name")
        new = _symbol_name(new_name, "new_name")
        if old == new:
            return node
        kind = _kind_of(node)
        budget = self._budget()
        budget.enter(0)
        id_factory = [0]

        # Side condition: the new binder name must not be free in the whole
        # term (classic α-rename).  Body rewrite uses capture-avoiding
        # substitution so nested binders that would capture *new* are renamed.
        whole_free = _free_vars(
            node, bound=frozenset(), budget=self._budget(), depth=0
        )
        if new in whole_free:
            raise AlgebraError(
                f"renaming binder {old!r} to {new!r} would capture "
                f"free variable {new!r}"
            )

        if _is_quantifier(kind):
            names = [b.name for b in node.binders]
            if old not in names:
                raise AlgebraError(
                    f"binder {old!r} is not among root binders of quantifier"
                )
            if new in names:
                raise AlgebraError(f"binder name {new!r} already present")
            binder_sort = next(b.sort for b in node.binders if b.name == old)
            binders = tuple(
                Binder(name=new if b.name == old else b.name, sort=b.sort)
                for b in node.binders
            )
            # Capture-avoiding: old ↦ new inside the body (as a free rewrite
            # relative to the binder being removed).
            fresh_var = LogicNode(
                node_id=_next_id(id_factory, node.node_id, "arv"),
                kind=NodeKind.VARIABLE,
                symbol=new,
                sort=binder_sort,
            )
            body = _substitute(
                node.arguments[0],
                old,
                fresh_var,
                free_of_replacement=frozenset({new}),
                used_names=_collect_names(node, self._budget(), 0) | {new},
                budget=budget,
                depth=1,
                id_factory=id_factory,
            )
            return _with_args(
                node,
                (body,),
                binders=binders,
                node_id=_next_id(id_factory, node.node_id, "ar"),
            )

        if _is_let(kind):
            binder = node.binders[0]
            if binder.name != old:
                raise AlgebraError(f"let binder is {binder.name!r}, not {old!r}")
            fresh_var = LogicNode(
                node_id=_next_id(id_factory, node.node_id, "arv"),
                kind=NodeKind.VARIABLE,
                symbol=new,
                sort=binder.sort,
            )
            body = _substitute(
                node.arguments[1],
                old,
                fresh_var,
                free_of_replacement=frozenset({new}),
                used_names=_collect_names(node, self._budget(), 0) | {new},
                budget=budget,
                depth=1,
                id_factory=id_factory,
            )
            return _with_args(
                node,
                (node.arguments[0], body),
                binders=(Binder(name=new, sort=binder.sort),),
                node_id=_next_id(id_factory, node.node_id, "ar"),
            )

        raise AlgebraError("alpha_rename_binder requires a quantifier or let root")

    def substitute(
        self,
        node: LogicNode,
        var: str,
        replacement: LogicNode,
    ) -> LogicNode:
        """Capture-avoiding substitution of free *var* by *replacement*.

        Guarantees the free-variable property::

            if var ∉ FV(node):
                FV(result) == FV(node)
            else:
                FV(result) == (FV(node) - {var}) ∪ FV(replacement)

        Binders that would capture free variables of *replacement* are
        alpha-renamed automatically.
        """

        node = self._require_node(node)
        replacement = self._require_node(replacement, "replacement")
        var_name = _symbol_name(var, "var")
        if not replacement.is_term:
            raise AlgebraError("substitution replacement must be a term")

        budget = self._budget()
        free_repl = frozenset(
            _free_vars(replacement, bound=frozenset(), budget=self._budget(), depth=0)
        )
        used = _collect_names(node, self._budget(), 0)
        used |= _collect_names(replacement, self._budget(), 0)
        id_factory = [0]
        return _substitute(
            node,
            var_name,
            replacement,
            free_of_replacement=free_repl,
            used_names=used,
            budget=budget,
            depth=0,
            id_factory=id_factory,
        )

    def substitute_many(
        self,
        node: LogicNode,
        mapping: Mapping[str, LogicNode],
    ) -> LogicNode:
        """Simultaneous capture-avoiding substitution.

        Implemented via fresh intermediates so that replacements do not
        interfere: ``x↦t, y↦u`` will not substitute into ``t`` or ``u``.
        """

        node = self._require_node(node)
        if not isinstance(mapping, Mapping):
            raise AlgebraError("mapping must be a mapping of var -> term")
        if len(mapping) > MAX_COLLECTION_ITEMS:
            raise AlgebraError("substitute_many mapping exceeds collection ceiling")
        if not mapping:
            return node

        # Validate and stage through fresh names to achieve simultaneous subst.
        pairs: list[tuple[str, LogicNode]] = []
        for key, value in mapping.items():
            name = _symbol_name(key, "mapping key")
            term = self._require_node(value, f"mapping[{name!r}]")
            if not term.is_term:
                raise AlgebraError(
                    f"mapping[{name!r}] replacement must be a term"
                )
            pairs.append((name, term))

        used = _collect_names(node, self._budget(), 0)
        for _, term in pairs:
            used |= _collect_names(term, self._budget(), 0)

        # Stage: each var -> fresh, then fresh -> replacement.
        staged: list[tuple[str, str, LogicNode]] = []
        for name, term in pairs:
            fresh = _fresh_name(f"__s_{name}", used)
            staged.append((name, fresh, term))

        result = node
        # First wave: var -> temporary variable (same sort as original free var if known).
        for name, fresh, term in staged:
            # Build a temporary variable node carrying replacement sort when available.
            sort = term.sort
            temp = LogicNode(
                node_id=f"alg:tmp:{fresh}",
                kind=NodeKind.VARIABLE,
                symbol=fresh,
                sort=sort,
            )
            result = self.substitute(result, name, temp)
        for name, fresh, term in staged:
            result = self.substitute(result, fresh, term)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "algebra_id": self.algebra_id,
            "interface": self.interface,
            "limits": self.limits.to_dict(),
            "metadata": _thaw_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicExpressionAlgebra":
        payload = _require_mapping(data, "LogicExpressionAlgebra")
        interface = payload.get("interface")
        if interface is not None and interface != LOGIC_EXPRESSION_ALGEBRA_INTERFACE:
            raise AlgebraError(
                f"unsupported LogicExpressionAlgebra interface {interface!r}"
            )
        return cls(
            algebra_id=str(payload.get("algebra_id") or "algebra:default"),
            limits=AlgebraLimits.from_dict(
                _require_mapping(payload.get("limits") or {}, "limits")
            )
            if payload.get("limits") is not None
            else AlgebraLimits(),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or "syntax-logic-expression-algebra/v1"
            ),
        )


# Module-level default algebra and free functions.
DEFAULT_ALGEBRA: Final = LogicExpressionAlgebra()


def free_variables(
    node: LogicNode,
    *,
    limits: AlgebraLimits | None = None,
) -> frozenset[str]:
    algebra = (
        DEFAULT_ALGEBRA
        if limits is None
        else LogicExpressionAlgebra(limits=limits)
    )
    return algebra.free_variables(node)


def bound_variables(
    node: LogicNode,
    *,
    limits: AlgebraLimits | None = None,
) -> frozenset[str]:
    algebra = (
        DEFAULT_ALGEBRA
        if limits is None
        else LogicExpressionAlgebra(limits=limits)
    )
    return algebra.bound_variables(node)


def alpha_equivalent(
    left: LogicNode,
    right: LogicNode,
    *,
    limits: AlgebraLimits | None = None,
) -> bool:
    algebra = (
        DEFAULT_ALGEBRA
        if limits is None
        else LogicExpressionAlgebra(limits=limits)
    )
    return algebra.alpha_equivalent(left, right)


def semantic_identity(
    node: LogicNode,
    *,
    limits: AlgebraLimits | None = None,
) -> str:
    algebra = (
        DEFAULT_ALGEBRA
        if limits is None
        else LogicExpressionAlgebra(limits=limits)
    )
    return algebra.semantic_identity(node)


def substitute(
    node: LogicNode,
    var: str,
    replacement: LogicNode,
    *,
    limits: AlgebraLimits | None = None,
) -> LogicNode:
    algebra = (
        DEFAULT_ALGEBRA
        if limits is None
        else LogicExpressionAlgebra(limits=limits)
    )
    return algebra.substitute(node, var, replacement)


def walk_bounded(
    node: LogicNode,
    *,
    limits: AlgebraLimits | None = None,
) -> Iterator[LogicNode]:
    algebra = (
        DEFAULT_ALGEBRA
        if limits is None
        else LogicExpressionAlgebra(limits=limits)
    )
    return algebra.walk(node)


__all__ = [
    "ALGEBRA_MODULE_VERSION",
    "DEFAULT_ALGEBRA",
    "DEFAULT_ALGEBRA_LIMITS",
    "LOGIC_EXPRESSION_ALGEBRA_INTERFACE",
    "MAX_ALGEBRA_DEPTH",
    "MAX_ALGEBRA_NODES",
    "AlgebraError",
    "AlgebraLimits",
    "LogicExpressionAlgebra",
    "alpha_equivalent",
    "bound_variables",
    "free_variables",
    "semantic_identity",
    "substitute",
    "walk_bounded",
]

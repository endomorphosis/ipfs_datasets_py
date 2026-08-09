"""Elaborator, typechecker, overload resolution, and normalizer.

Interfaces (LFP-015):

* ``LogicElaborator@1`` — signature-bound elaboration producing typed
  expressions, symbol tables, diagnostics, and backend-readiness gates

Unresolved overloads, unknown signatures/symbols, and sort errors never
produce a backend-ready artifact.  Normalization is deterministic and
idempotent.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.algebra import (
    DEFAULT_ALGEBRA,
    AlgebraLimits,
    LogicExpressionAlgebra,
    semantic_identity,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    AstError,
    Binder,
    ElaborationContext,
    LogicExtensionNode,
    LogicNode,
    NodeKind,
    TypedExpression,
    elaborate,
    elaborate_node,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_COLLECTION_ITEMS,
    MAX_DIAGNOSTICS,
    DiagnosticSeverity,
    SourceRange,
    SyntaxContractError,
    SyntaxDiagnostic,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    LogicSort,
    SignatureError,
    SymbolDeclaration,
    SymbolKind,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_ELABORATOR_INTERFACE: Final = "LogicElaborator@1"
ELABORATION_RESULT_SCHEMA_VERSION: Final = "syntax-elaboration-result/v1"
ELABORATOR_SCHEMA_VERSION: Final = "syntax-logic-elaborator/v1"
OVERLOAD_SET_SCHEMA_VERSION: Final = "syntax-overload-set/v1"
ELABORATION_MODULE_VERSION: Final = "1.0.0"

# Stable diagnostic codes (namespaced).
CODE_UNKNOWN_SYMBOL: Final = "elaboration.unknown_symbol"
CODE_UNKNOWN_SIGNATURE: Final = "elaboration.unknown_signature"
CODE_UNRESOLVED_OVERLOAD: Final = "elaboration.unresolved_overload"
CODE_AMBIGUOUS_OVERLOAD: Final = "elaboration.ambiguous_overload"
CODE_SORT_MISMATCH: Final = "elaboration.sort_mismatch"
CODE_ARITY_MISMATCH: Final = "elaboration.arity_mismatch"
CODE_KIND_MISMATCH: Final = "elaboration.kind_mismatch"
CODE_TYPECHECK_FAILED: Final = "elaboration.typecheck_failed"
CODE_NOT_BACKEND_READY: Final = "elaboration.not_backend_ready"
CODE_EXTENSION_FAILED: Final = "elaboration.extension_failed"

_NARY_CONNECTIVES: Final[frozenset[NodeKind]] = frozenset(
    {NodeKind.AND, NodeKind.OR}
)
_COMMUTATIVE_BINARY: Final[frozenset[NodeKind]] = frozenset(
    {NodeKind.IFF, NodeKind.EQUALITY}
)


class ElaborationError(SyntaxContractError):
    """Raised when elaboration, typechecking, or normalization fails hard."""


class UnresolvedOverloadError(ElaborationError):
    """Raised when overload resolution yields zero or multiple matches."""


class UnknownSignatureError(ElaborationError):
    """Raised when a required signature or symbol cannot be resolved."""


class ElaborationStatus(str, Enum):
    """Outcome of an elaboration attempt."""

    OK = "ok"
    FAILED = "failed"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Overload resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OverloadCandidate:
    """One typed candidate in an overload set."""

    declaration: SymbolDeclaration
    candidate_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.declaration, SymbolDeclaration):
            if isinstance(self.declaration, Mapping):
                object.__setattr__(
                    self,
                    "declaration",
                    SymbolDeclaration.from_dict(self.declaration),
                )
            else:
                raise ElaborationError(
                    "OverloadCandidate.declaration must be a SymbolDeclaration"
                )
        candidate_id = self.candidate_id or (
            f"cand:{self.declaration.name}:{self.declaration.kind.value}:"
            f"{self.declaration.arity}"
        )
        object.__setattr__(
            self, "candidate_id", _record_id(candidate_id, "candidate_id")
        )

    def accepts(self, argument_sorts: Sequence[LogicSort]) -> bool:
        return self.declaration.accepts(argument_sorts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "declaration": self.declaration.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OverloadCandidate":
        payload = _require_mapping(data, "OverloadCandidate")
        return cls(
            declaration=SymbolDeclaration.from_dict(
                _require_mapping(payload.get("declaration"), "declaration")
            ),
            candidate_id=str(payload.get("candidate_id") or ""),
        )


@dataclass(frozen=True, slots=True)
class OverloadSet:
    """Named set of overload candidates for one surface symbol.

    Construction rejects empty sets.  Resolution is fail-closed: zero matches
    or more than one match raise :class:`UnresolvedOverloadError`.
    """

    name: str
    candidates: tuple[OverloadCandidate, ...]
    schema_version: str = OVERLOAD_SET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        name = _text(self.name, "OverloadSet.name", maximum=256)
        object.__setattr__(self, "name", name)
        candidates = tuple(
            item
            if isinstance(item, OverloadCandidate)
            else OverloadCandidate.from_dict(
                _require_mapping(item, "candidates item")
            )
            for item in _require_sequence(self.candidates, "candidates")
        )
        if not candidates:
            raise ElaborationError(
                f"OverloadSet {name!r} must contain at least one candidate"
            )
        if len(candidates) > MAX_COLLECTION_ITEMS:
            raise ElaborationError("OverloadSet.candidates exceeds collection ceiling")
        # All candidates must share the surface name.
        for candidate in candidates:
            if candidate.declaration.name != name:
                raise ElaborationError(
                    f"overload candidate {candidate.candidate_id!r} name "
                    f"{candidate.declaration.name!r} does not match set name "
                    f"{name!r}"
                )
        object.__setattr__(self, "candidates", candidates)
        if self.schema_version != OVERLOAD_SET_SCHEMA_VERSION:
            raise ElaborationError(
                f"unsupported OverloadSet schema_version {self.schema_version!r}"
            )

    def resolve(
        self,
        argument_sorts: Sequence[LogicSort],
        *,
        expected_kind: SymbolKind | None = None,
    ) -> OverloadCandidate:
        """Return the unique candidate matching *argument_sorts*.

        Zero matches or multiple matches are unresolved overloads and must not
        reach backends.
        """

        matches: list[OverloadCandidate] = []
        for candidate in self.candidates:
            decl = candidate.declaration
            if expected_kind is not None and decl.kind is not expected_kind:
                continue
            if candidate.accepts(argument_sorts):
                matches.append(candidate)
        if not matches:
            raise UnresolvedOverloadError(
                f"unresolved overload for {self.name!r}: no candidate accepts "
                f"argument sorts {[str(s) for s in argument_sorts]}"
            )
        if len(matches) > 1:
            ids = [item.candidate_id for item in matches]
            raise UnresolvedOverloadError(
                f"ambiguous overload for {self.name!r}: candidates {ids} all "
                f"accept argument sorts {[str(s) for s in argument_sorts]}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [item.to_dict() for item in self.candidates],
            "name": self.name,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OverloadSet":
        payload = _require_mapping(data, "OverloadSet")
        return cls(
            name=str(payload.get("name") or ""),
            candidates=tuple(
                OverloadCandidate.from_dict(_require_mapping(item, "candidates item"))
                for item in _require_sequence(
                    payload.get("candidates") or (), "candidates"
                )
            ),
            schema_version=str(
                payload.get("schema_version") or OVERLOAD_SET_SCHEMA_VERSION
            ),
        )


def resolve_overload(
    overload_set: OverloadSet,
    argument_sorts: Sequence[LogicSort],
    *,
    expected_kind: SymbolKind | None = None,
) -> OverloadCandidate:
    """Module-level overload resolution entry point."""

    if not isinstance(overload_set, OverloadSet):
        raise ElaborationError("resolve_overload requires an OverloadSet")
    return overload_set.resolve(argument_sorts, expected_kind=expected_kind)


# ---------------------------------------------------------------------------
# Diagnostics helpers
# ---------------------------------------------------------------------------


def _diagnostic(
    diagnostic_id: str,
    code: str,
    message: str,
    *,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    range: SourceRange | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=diagnostic_id,
        code=code,
        message=message,
        severity=severity,
        range=range,
    )


# ---------------------------------------------------------------------------
# Typechecker
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypecheckReport:
    """Result of a pure typecheck pass (no rewrite)."""

    ok: bool
    root: LogicNode | None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    unknown_symbols: tuple[str, ...] = ()
    unresolved_overloads: tuple[str, ...] = ()

    @property
    def backend_ready(self) -> bool:
        """Typecheck alone is never a backend authority grant.

        Backend readiness requires a successful elaboration result with no
        unresolved overloads or unknown symbols (see :class:`ElaborationResult`).
        """

        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "ok": self.ok,
            "root": None if self.root is None else self.root.to_dict(),
            "unknown_symbols": list(self.unknown_symbols),
            "unresolved_overloads": list(self.unresolved_overloads),
        }


class LogicTypechecker:
    """Signature-relative sort and arity checker."""

    def __init__(
        self,
        signature: LogicSignature | None = None,
        *,
        overloads: Mapping[str, OverloadSet] | Sequence[OverloadSet] = (),
    ) -> None:
        self._signature = signature
        self._overloads = self._index_overloads(overloads)

    @staticmethod
    def _index_overloads(
        overloads: Mapping[str, OverloadSet] | Sequence[OverloadSet],
    ) -> Mapping[str, OverloadSet]:
        if isinstance(overloads, Mapping):
            items = {
                _text(name, "overload name", maximum=256): (
                    value
                    if isinstance(value, OverloadSet)
                    else OverloadSet.from_dict(_require_mapping(value, "overload"))
                )
                for name, value in overloads.items()
            }
        else:
            items = {}
            for item in _require_sequence(overloads, "overloads"):
                overload = (
                    item
                    if isinstance(item, OverloadSet)
                    else OverloadSet.from_dict(_require_mapping(item, "overload"))
                )
                if overload.name in items:
                    raise ElaborationError(
                        f"duplicate overload set for {overload.name!r}"
                    )
                items[overload.name] = overload
        return MappingProxyType(items)

    @property
    def signature(self) -> LogicSignature | None:
        return self._signature

    @property
    def overloads(self) -> Mapping[str, OverloadSet]:
        return self._overloads

    def typecheck(
        self,
        node: LogicNode,
        *,
        signature: LogicSignature | None = None,
        locals: Mapping[str, LogicSort] | None = None,
    ) -> TypecheckReport:
        """Elaborate *node* for typing; collect diagnostics instead of raising.

        Unknown signatures and unresolved overloads are recorded and leave the
        report non-ok so they never become backend-ready.
        """

        if not isinstance(node, LogicNode):
            raise ElaborationError("typecheck requires a LogicNode")
        sig = signature if signature is not None else self._signature
        diagnostics: list[SyntaxDiagnostic] = []
        unknown: list[str] = []
        unresolved: list[str] = []
        seq = [0]
        resolved: dict[str, SymbolDeclaration] = {}

        if sig is None:
            diagnostics.append(
                _diagnostic(
                    "diag:elab:unknown-signature:1",
                    CODE_UNKNOWN_SIGNATURE,
                    "typecheck requires a LogicSignature; unknown signature "
                    "cannot reach backends",
                )
            )
            return TypecheckReport(
                ok=False,
                root=None,
                diagnostics=tuple(diagnostics),
                unknown_symbols=(),
                unresolved_overloads=(),
            )

        # Pre-scan for overload symbols and unknown surface names.
        try:
            self._check_overloads_in_tree(
                node,
                sig,
                diagnostics=diagnostics,
                unknown=unknown,
                unresolved=unresolved,
                seq=seq,
                resolved=resolved,
            )
        except ElaborationError as error:
            diagnostics.append(
                _diagnostic(
                    f"diag:elab:typecheck:{seq[0] + 1}",
                    CODE_TYPECHECK_FAILED,
                    str(error),
                )
            )
            return TypecheckReport(
                ok=False,
                root=None,
                diagnostics=tuple(diagnostics),
                unknown_symbols=tuple(sorted(set(unknown))),
                unresolved_overloads=tuple(sorted(set(unresolved))),
            )

        if unresolved or unknown:
            return TypecheckReport(
                ok=False,
                root=None,
                diagnostics=tuple(diagnostics),
                unknown_symbols=tuple(sorted(set(unknown))),
                unresolved_overloads=tuple(sorted(set(unresolved))),
            )

        work_node = node
        work_sig = sig
        if resolved:
            # Rewrite overload surface names to unique mangled symbols and
            # extend the signature so standard elaboration can proceed.
            work_node, work_sig = self._apply_resolved_overloads(
                node, sig, resolved
            )

        try:
            typed = elaborate(work_node, work_sig, locals=locals)
        except (AstError, SignatureError) as error:
            message = str(error)
            code = CODE_TYPECHECK_FAILED
            lowered = message.casefold()
            if "unknown symbol" in lowered:
                code = CODE_UNKNOWN_SYMBOL
            elif "arity" in lowered:
                code = CODE_ARITY_MISMATCH
            elif "sort" in lowered:
                code = CODE_SORT_MISMATCH
            elif "kind" in lowered:
                code = CODE_KIND_MISMATCH
            diagnostics.append(
                _diagnostic(
                    "diag:elab:typecheck:fail",
                    code,
                    message,
                )
            )
            if code is CODE_UNKNOWN_SYMBOL or "unknown symbol" in lowered:
                match = re.search(r"unknown symbol '([^']+)'", message)
                if match:
                    unknown.append(match.group(1))
            return TypecheckReport(
                ok=False,
                root=None,
                diagnostics=tuple(diagnostics),
                unknown_symbols=tuple(sorted(set(unknown))),
                unresolved_overloads=tuple(sorted(set(unresolved))),
            )

        return TypecheckReport(
            ok=True,
            root=typed,
            diagnostics=tuple(diagnostics),
            unknown_symbols=(),
            unresolved_overloads=(),
        )

    @staticmethod
    def _mangle_overload_name(
        name: str, declaration: SymbolDeclaration
    ) -> str:
        domain_key = "_".join(sort.name for sort in declaration.domain) or "nullary"
        kind_key = (
            declaration.kind.value
            if isinstance(declaration.kind, SymbolKind)
            else str(declaration.kind)
        )
        mangled = f"{name}_ov_{kind_key}_{domain_key}"
        if len(mangled) > 256:
            mangled = f"{name}_ov_{content_sha256(mangled.encode('utf-8'))[:16]}"
        return mangled

    def _apply_resolved_overloads(
        self,
        node: LogicNode,
        signature: LogicSignature,
        resolved: Mapping[str, SymbolDeclaration],
    ) -> tuple[LogicNode, LogicSignature]:
        """Rewrite overload surface symbols to unique mangled declarations."""

        rename: dict[str, str] = {}
        extra: list[SymbolDeclaration] = []
        for surface, decl in resolved.items():
            mangled = self._mangle_overload_name(surface, decl)
            rename[surface] = mangled
            extra.append(
                SymbolDeclaration(
                    name=mangled,
                    kind=decl.kind,
                    domain=decl.domain,
                    range=decl.range,
                    metadata=_thaw_mapping(decl.metadata),
                )
            )
        extended = signature.extend(
            signature_id=f"{signature.signature_id}:ov",
            symbols=extra,
        )
        rewritten = self._rename_symbols(node, rename)
        return rewritten, extended

    def _rename_symbols(
        self, node: LogicNode, rename: Mapping[str, str]
    ) -> LogicNode:
        kind = node.kind
        new_symbol = rename.get(node.symbol, node.symbol) if node.symbol else ""
        new_args = tuple(self._rename_symbols(arg, rename) for arg in node.arguments)
        new_extension = node.extension
        if node.extension is not None:
            children = tuple(
                self._rename_symbols(child, rename)
                for child in node.extension.children
            )
            new_extension = LogicExtensionNode(
                node_id=node.extension.node_id,
                family=node.extension.family,
                profile=node.extension.profile,
                features=node.extension.features,
                payload_schema=node.extension.payload_schema,
                payload=_thaw_mapping(node.extension.payload),
                children=children,
                range=node.extension.range,
                metadata=_thaw_mapping(node.extension.metadata),
            )
        if (
            new_symbol == node.symbol
            and new_args == node.arguments
            and new_extension is node.extension
        ):
            return node
        return LogicNode(
            node_id=node.node_id,
            kind=kind,
            sort=node.sort,
            symbol=new_symbol,
            arguments=new_args,
            binders=node.binders,
            extension=new_extension,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    def _check_overloads_in_tree(
        self,
        node: LogicNode,
        signature: LogicSignature,
        *,
        diagnostics: list[SyntaxDiagnostic],
        unknown: list[str],
        unresolved: list[str],
        seq: list[int],
        resolved: dict[str, SymbolDeclaration],
        locals: Mapping[str, LogicSort] | None = None,
    ) -> None:
        """Walk the tree and resolve overload-only symbols fail-closed."""

        local_env = dict(locals or {})
        kind = node.kind

        if kind in {NodeKind.FORALL, NodeKind.EXISTS} or kind in {
            NodeKind.FORALL.value,
            NodeKind.EXISTS.value,
        }:
            for binder in node.binders:
                local_env[binder.name] = binder.sort
            for child in node.arguments:
                self._check_overloads_in_tree(
                    child,
                    signature,
                    diagnostics=diagnostics,
                    unknown=unknown,
                    unresolved=unresolved,
                    seq=seq,
                    resolved=resolved,
                    locals=local_env,
                )
            return

        if kind is NodeKind.LET or kind == NodeKind.LET.value:
            if node.arguments:
                self._check_overloads_in_tree(
                    node.arguments[0],
                    signature,
                    diagnostics=diagnostics,
                    unknown=unknown,
                    unresolved=unresolved,
                    seq=seq,
                    resolved=resolved,
                    locals=local_env,
                )
            if node.binders:
                local_env[node.binders[0].name] = node.binders[0].sort
            if len(node.arguments) > 1:
                self._check_overloads_in_tree(
                    node.arguments[1],
                    signature,
                    diagnostics=diagnostics,
                    unknown=unknown,
                    unresolved=unresolved,
                    seq=seq,
                    resolved=resolved,
                    locals=local_env,
                )
            return

        # Applications / predicates may be overload-bound.
        if kind in {
            NodeKind.APPLICATION,
            NodeKind.PREDICATE,
            NodeKind.CONSTANT,
        } or kind in {
            NodeKind.APPLICATION.value,
            NodeKind.PREDICATE.value,
            NodeKind.CONSTANT.value,
        }:
            symbol = node.symbol
            # Overload tables apply only when the surface name is not already
            # a unique signature symbol (signature wins on unique names).
            if (
                symbol
                and symbol in self._overloads
                and not signature.has_symbol(symbol)
            ):
                arg_sorts: list[LogicSort] = []
                args_ok = True
                for arg in node.arguments:
                    self._check_overloads_in_tree(
                        arg,
                        signature,
                        diagnostics=diagnostics,
                        unknown=unknown,
                        unresolved=unresolved,
                        seq=seq,
                        resolved=resolved,
                        locals=local_env,
                    )
                    try:
                        typed_arg = elaborate_node(
                            arg,
                            ElaborationContext(
                                signature=signature, locals=local_env
                            ),
                        )
                        arg_sorts.append(typed_arg.result_sort)
                    except Exception:
                        args_ok = False
                        break
                if args_ok and (arg_sorts or not node.arguments):
                    expected_kind = None
                    if (
                        kind is NodeKind.APPLICATION
                        or kind == NodeKind.APPLICATION.value
                    ):
                        expected_kind = SymbolKind.FUNCTION
                    elif (
                        kind is NodeKind.PREDICATE
                        or kind == NodeKind.PREDICATE.value
                    ):
                        expected_kind = SymbolKind.PREDICATE
                    elif (
                        kind is NodeKind.CONSTANT
                        or kind == NodeKind.CONSTANT.value
                    ):
                        expected_kind = SymbolKind.CONSTANT
                    try:
                        winner = self._overloads[symbol].resolve(
                            arg_sorts, expected_kind=expected_kind
                        )
                        existing = resolved.get(symbol)
                        if (
                            existing is not None
                            and existing.to_dict() != winner.declaration.to_dict()
                        ):
                            seq[0] += 1
                            unresolved.append(symbol)
                            diagnostics.append(
                                _diagnostic(
                                    f"diag:elab:overload:{seq[0]}",
                                    CODE_AMBIGUOUS_OVERLOAD,
                                    f"overload {symbol!r} resolved to "
                                    "conflicting candidates in one term",
                                    range=node.range,
                                )
                            )
                        else:
                            resolved[symbol] = winner.declaration
                    except UnresolvedOverloadError as error:
                        seq[0] += 1
                        unresolved.append(symbol)
                        diagnostics.append(
                            _diagnostic(
                                f"diag:elab:overload:{seq[0]}",
                                CODE_UNRESOLVED_OVERLOAD
                                if "ambiguous" not in str(error).casefold()
                                else CODE_AMBIGUOUS_OVERLOAD,
                                str(error),
                                range=node.range,
                            )
                        )
                return

            if symbol and not signature.has_symbol(symbol):
                if kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
                    seq[0] += 1
                    unknown.append(symbol)
                    diagnostics.append(
                        _diagnostic(
                            f"diag:elab:unknown:{seq[0]}",
                            CODE_UNKNOWN_SYMBOL,
                            f"unknown symbol {symbol!r}; unknown signatures must "
                            "not reach backends",
                            range=node.range,
                        )
                    )
                elif kind in {
                    NodeKind.APPLICATION,
                    NodeKind.PREDICATE,
                } or kind in {
                    NodeKind.APPLICATION.value,
                    NodeKind.PREDICATE.value,
                }:
                    seq[0] += 1
                    unknown.append(symbol)
                    diagnostics.append(
                        _diagnostic(
                            f"diag:elab:unknown:{seq[0]}",
                            CODE_UNKNOWN_SYMBOL,
                            f"unknown symbol {symbol!r}; unknown signatures must "
                            "not reach backends",
                            range=node.range,
                        )
                    )

        for child in node.children():
            self._check_overloads_in_tree(
                child,
                signature,
                diagnostics=diagnostics,
                unknown=unknown,
                unresolved=unresolved,
                seq=seq,
                resolved=resolved,
                locals=local_env,
            )


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


class LogicNormalizer:
    """Deterministic, idempotent structural normalizer for core expressions.

    Normalization:

    * strips source ranges and metadata
    * flattens nested commutative n-ary connectives (``and`` / ``or``)
    * sorts commutative operator arguments by semantic identity
    * assigns stable content-derived node ids

    The result is a fixed point: ``normalize(normalize(x))`` is structurally
    equal to ``normalize(x)`` (modulo object identity).
    """

    def __init__(
        self,
        *,
        algebra: LogicExpressionAlgebra | None = None,
        limits: AlgebraLimits | None = None,
    ) -> None:
        if algebra is not None:
            self._algebra = algebra
        elif limits is not None:
            self._algebra = LogicExpressionAlgebra(limits=limits)
        else:
            self._algebra = DEFAULT_ALGEBRA

    def normalize(self, node: LogicNode) -> LogicNode:
        if not isinstance(node, LogicNode):
            raise ElaborationError("normalize requires a LogicNode")
        return self._normalize(node)

    def is_normalized(self, node: LogicNode) -> bool:
        return self._structurally_equal(node, self.normalize(node))

    def _normalize(self, node: LogicNode) -> LogicNode:
        kind = node.kind
        kind_enum = kind if isinstance(kind, NodeKind) else None

        # Recurse first.
        if kind_enum is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            if node.extension is None:
                raise ElaborationError("extension node missing payload")
            children = tuple(
                self._normalize(child) for child in node.extension.children
            )
            args = tuple(self._normalize(arg) for arg in node.arguments)
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
            ext_payload = {
                "family": family,
                "features": list(ext.features),
                "payload": _thaw_mapping(ext.payload),
                "payload_schema": ext.payload_schema,
                "profile": profile,
                "children": [self._identity_key(child) for child in children],
            }
            extension = LogicExtensionNode(
                node_id=self._stable_id("ext", ext_payload),
                family=ext.family,
                profile=ext.profile,
                features=ext.features,
                payload_schema=ext.payload_schema,
                payload=_thaw_mapping(ext.payload),
                children=children,
            )
            return LogicNode(
                node_id=self._stable_id(
                    "extension",
                    {
                        "args": [self._identity_key(a) for a in args],
                        "ext": ext_payload,
                    },
                ),
                kind=NodeKind.EXTENSION,
                arguments=args,
                extension=extension,
                sort=BOOL_SORT,
            )

        args = tuple(self._normalize(arg) for arg in node.arguments)

        if kind_enum in _NARY_CONNECTIVES or kind in {
            NodeKind.AND.value,
            NodeKind.OR.value,
        }:
            flat = self._flatten_nary(kind_enum or NodeKind(str(kind)), args)
            ordered = self._sort_by_identity(flat)
            # Collapse to true/false only when a single unique arg remains after
            # structural equality? Keep at least two for well-formedness; if
            # flattening produced one arg, wrap is invalid — rebuild only when ≥2.
            if len(ordered) < 2:
                # Should not happen for well-formed input; return first child.
                return ordered[0] if ordered else node
            payload = {
                "k": (kind_enum or NodeKind(str(kind))).value,
                "args": [self._identity_key(a) for a in ordered],
            }
            return LogicNode(
                node_id=self._stable_id("conn", payload),
                kind=kind_enum or kind,
                arguments=ordered,
                sort=BOOL_SORT,
            )

        if kind_enum in _COMMUTATIVE_BINARY or kind in {
            NodeKind.IFF.value,
            NodeKind.EQUALITY.value,
        }:
            ordered = self._sort_by_identity(args)
            payload = {
                "k": (kind_enum or NodeKind(str(kind))).value,
                "args": [self._identity_key(a) for a in ordered],
            }
            return LogicNode(
                node_id=self._stable_id("bin", payload),
                kind=kind_enum or kind,
                arguments=ordered,
                sort=BOOL_SORT,
            )

        if kind_enum in {NodeKind.FORALL, NodeKind.EXISTS} or kind in {
            NodeKind.FORALL.value,
            NodeKind.EXISTS.value,
        }:
            # Preserve binder order (binding structure is significant); only
            # normalize the body and strip ranges.
            body = args[0] if args else node.arguments[0]
            binders = tuple(
                Binder(name=b.name, sort=b.sort) for b in node.binders
            )
            payload = {
                "k": (kind_enum or NodeKind(str(kind))).value,
                "binders": [b.to_dict() for b in binders],
                "body": self._identity_key(body),
            }
            return LogicNode(
                node_id=self._stable_id("quant", payload),
                kind=kind_enum or kind,
                binders=binders,
                arguments=(body,),
                sort=BOOL_SORT,
            )

        if kind_enum is NodeKind.LET or kind == NodeKind.LET.value:
            binders = tuple(Binder(name=b.name, sort=b.sort) for b in node.binders)
            payload = {
                "k": "let",
                "binders": [b.to_dict() for b in binders],
                "args": [self._identity_key(a) for a in args],
            }
            result_sort = BOOL_SORT if args[1].is_formula else args[1].sort
            return LogicNode(
                node_id=self._stable_id("let", payload),
                kind=NodeKind.LET,
                binders=binders,
                arguments=args,
                sort=result_sort,
            )

        # Leaves and non-commutative operators.
        symbol = node.symbol
        sort = node.sort
        payload = {
            "k": kind_enum.value if kind_enum is not None else str(kind),
            "s": symbol,
            "sort": None if sort is None else sort.to_dict(),
            "args": [self._identity_key(a) for a in args],
            "binders": [b.to_dict() for b in node.binders],
        }
        return LogicNode(
            node_id=self._stable_id("node", payload),
            kind=kind_enum or kind,
            symbol=symbol,
            sort=sort,
            arguments=args,
            binders=tuple(Binder(name=b.name, sort=b.sort) for b in node.binders),
        )

    def _flatten_nary(
        self, kind: NodeKind, args: Sequence[LogicNode]
    ) -> tuple[LogicNode, ...]:
        flat: list[LogicNode] = []
        for arg in args:
            if arg.kind is kind or arg.kind == kind.value:
                flat.extend(self._flatten_nary(kind, arg.arguments))
            else:
                flat.append(arg)
        # Deduplicate by semantic identity while preserving first occurrence
        # order among identity-sorted later.
        seen: set[str] = set()
        unique: list[LogicNode] = []
        for item in flat:
            key = self._identity_key(item)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return tuple(unique)

    def _sort_by_identity(
        self, args: Sequence[LogicNode]
    ) -> tuple[LogicNode, ...]:
        return tuple(sorted(args, key=self._identity_key))

    def _identity_key(self, node: LogicNode) -> str:
        return self._algebra.semantic_identity(node)

    def _stable_id(self, tag: str, payload: Mapping[str, Any]) -> str:
        digest = content_sha256(canonical_json_bytes(dict(payload)))[:24]
        return f"n:{tag}:{digest}"

    def _structurally_equal(self, left: LogicNode, right: LogicNode) -> bool:
        return left.to_dict() == right.to_dict()


DEFAULT_NORMALIZER: Final = LogicNormalizer()


def normalize(
    node: LogicNode,
    *,
    algebra: LogicExpressionAlgebra | None = None,
    limits: AlgebraLimits | None = None,
) -> LogicNode:
    """Normalize *node* to a deterministic fixed-point form."""

    if algebra is None and limits is None:
        return DEFAULT_NORMALIZER.normalize(node)
    return LogicNormalizer(algebra=algebra, limits=limits).normalize(node)


# ---------------------------------------------------------------------------
# Elaboration result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ElaborationResult:
    """Typed elaboration envelope with backend-readiness gate.

    Interface payload for ``LogicElaborator@1`` results.

    ``backend_ready`` is True only when status is OK, a typed expression is
    present, and there are no unresolved overloads, unknown symbols, or
    error/fatal diagnostics.  Unresolved work never reaches backends.
    """

    result_id: str
    status: ElaborationStatus | str
    typed_expression: TypedExpression | None = None
    root: LogicNode | None = None
    normalized_root: LogicNode | None = None
    signature: LogicSignature | None = None
    symbol_table: Mapping[str, SymbolDeclaration] = field(default_factory=dict)
    unresolved_overloads: tuple[str, ...] = ()
    unknown_symbols: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    content_digest: str = ""
    semantic_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ELABORATION_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "result_id", _record_id(self.result_id, "result_id")
        )
        if isinstance(self.status, ElaborationStatus):
            status = self.status
        else:
            try:
                status = ElaborationStatus(
                    _text(self.status, "status", maximum=32)
                )
            except ValueError as error:
                raise ElaborationError(
                    f"status must be an ElaborationStatus; got {self.status!r}"
                ) from error
        object.__setattr__(self, "status", status)

        if self.typed_expression is not None and not isinstance(
            self.typed_expression, TypedExpression
        ):
            object.__setattr__(
                self,
                "typed_expression",
                TypedExpression.from_dict(
                    _require_mapping(self.typed_expression, "typed_expression")
                ),
            )
        if self.root is not None and not isinstance(self.root, LogicNode):
            object.__setattr__(
                self,
                "root",
                LogicNode.from_dict(_require_mapping(self.root, "root")),
            )
        if self.normalized_root is not None and not isinstance(
            self.normalized_root, LogicNode
        ):
            object.__setattr__(
                self,
                "normalized_root",
                LogicNode.from_dict(
                    _require_mapping(self.normalized_root, "normalized_root")
                ),
            )
        if self.signature is not None and not isinstance(
            self.signature, LogicSignature
        ):
            object.__setattr__(
                self,
                "signature",
                LogicSignature.from_dict(
                    _require_mapping(self.signature, "signature")
                ),
            )

        table: dict[str, SymbolDeclaration] = {}
        for name, decl in dict(self.symbol_table).items():
            key = _text(name, "symbol_table key", maximum=256)
            if not isinstance(decl, SymbolDeclaration):
                decl = SymbolDeclaration.from_dict(
                    _require_mapping(decl, "symbol_table value")
                )
            table[key] = decl
        object.__setattr__(self, "symbol_table", MappingProxyType(table))

        object.__setattr__(
            self,
            "unresolved_overloads",
            tuple(
                _text(item, "unresolved_overloads item", maximum=256)
                for item in _require_sequence(
                    self.unresolved_overloads, "unresolved_overloads"
                )
            ),
        )
        object.__setattr__(
            self,
            "unknown_symbols",
            tuple(
                _text(item, "unknown_symbols item", maximum=256)
                for item in _require_sequence(
                    self.unknown_symbols, "unknown_symbols"
                )
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            tuple(
                _text(item, "assumptions item", maximum=1024)
                for item in _require_sequence(self.assumptions, "assumptions")
            ),
        )

        diagnostics = tuple(
            item
            if isinstance(item, SyntaxDiagnostic)
            else SyntaxDiagnostic.from_dict(
                _require_mapping(item, "diagnostics item")
            )
            for item in _require_sequence(self.diagnostics, "diagnostics")
        )
        if len(diagnostics) > MAX_DIAGNOSTICS:
            raise ElaborationError("diagnostics exceeds collection ceiling")
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )

        if self.schema_version != ELABORATION_RESULT_SCHEMA_VERSION:
            raise ElaborationError(
                f"unsupported ElaborationResult schema_version "
                f"{self.schema_version!r}"
            )

        # Content identity over the deterministic payload (excluding digests).
        digest = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _text(self.content_digest, "content_digest", maximum=64)
            if provided != digest:
                raise ElaborationError(
                    "content_digest does not match ElaborationResult content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", digest)

        if not self.semantic_digest and self.normalized_root is not None:
            object.__setattr__(
                self,
                "semantic_digest",
                semantic_identity(self.normalized_root),
            )
        elif not self.semantic_digest and self.root is not None:
            object.__setattr__(
                self, "semantic_digest", semantic_identity(self.root)
            )
        elif self.semantic_digest:
            object.__setattr__(
                self,
                "semantic_digest",
                _text(self.semantic_digest, "semantic_digest", maximum=64),
            )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "normalized_root": None
            if self.normalized_root is None
            else self.normalized_root.to_dict(),
            "result_id": self.result_id,
            "root": None if self.root is None else self.root.to_dict(),
            "schema_version": self.schema_version,
            "signature": None
            if self.signature is None
            else self.signature.to_dict(),
            "status": self.status.value
            if isinstance(self.status, ElaborationStatus)
            else self.status,
            "symbol_table": {
                name: decl.to_dict() for name, decl in sorted(self.symbol_table.items())
            },
            "typed_expression": None
            if self.typed_expression is None
            else self.typed_expression.to_dict(),
            "unknown_symbols": list(self.unknown_symbols),
            "unresolved_overloads": list(self.unresolved_overloads),
        }

    @property
    def backend_ready(self) -> bool:
        """Whether this result may be handed to a backend lowering.

        Fail-closed: unresolved overloads, unknown symbols, missing typed
        expression, non-OK status, or error/fatal diagnostics block readiness.
        """

        if self.status is not ElaborationStatus.OK:
            return False
        if self.typed_expression is None:
            return False
        if self.unresolved_overloads:
            return False
        if self.unknown_symbols:
            return False
        for diagnostic in self.diagnostics:
            severity = diagnostic.severity
            if isinstance(severity, DiagnosticSeverity):
                if severity.rank >= DiagnosticSeverity.ERROR.rank:
                    return False
            else:
                if str(severity) in {
                    DiagnosticSeverity.ERROR.value,
                    DiagnosticSeverity.FATAL.value,
                }:
                    return False
        return True

    def require_backend_ready(self) -> TypedExpression:
        """Return the typed expression or raise if not backend-ready."""

        if not self.backend_ready or self.typed_expression is None:
            raise ElaborationError(
                "elaboration result is not backend-ready: unresolved "
                "overloads, unknown signatures, or type errors must not "
                "reach backends"
            )
        return self.typed_expression

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["backend_ready"] = self.backend_ready
        payload["content_digest"] = self.content_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        payload["semantic_digest"] = self.semantic_digest
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ElaborationResult":
        payload = _require_mapping(data, "ElaborationResult")
        typed_payload = payload.get("typed_expression")
        root_payload = payload.get("root")
        norm_payload = payload.get("normalized_root")
        sig_payload = payload.get("signature")
        return cls(
            result_id=str(payload.get("result_id") or ""),
            status=str(payload.get("status") or ElaborationStatus.FAILED.value),
            typed_expression=(
                None
                if typed_payload is None
                else TypedExpression.from_dict(
                    _require_mapping(typed_payload, "typed_expression")
                )
            ),
            root=(
                None
                if root_payload is None
                else LogicNode.from_dict(_require_mapping(root_payload, "root"))
            ),
            normalized_root=(
                None
                if norm_payload is None
                else LogicNode.from_dict(
                    _require_mapping(norm_payload, "normalized_root")
                )
            ),
            signature=(
                None
                if sig_payload is None
                else LogicSignature.from_dict(
                    _require_mapping(sig_payload, "signature")
                )
            ),
            symbol_table=_require_mapping(
                payload.get("symbol_table") or {}, "symbol_table"
            ),
            unresolved_overloads=tuple(payload.get("unresolved_overloads") or ()),
            unknown_symbols=tuple(payload.get("unknown_symbols") or ()),
            assumptions=tuple(payload.get("assumptions") or ()),
            diagnostics=tuple(
                SyntaxDiagnostic.from_dict(
                    _require_mapping(item, "diagnostics item")
                )
                for item in _require_sequence(
                    payload.get("diagnostics") or (), "diagnostics"
                )
            ),
            content_digest=str(payload.get("content_digest") or ""),
            semantic_digest=str(payload.get("semantic_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or ELABORATION_RESULT_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# LogicElaborator@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicElaborator:
    """Signature-bound elaborator with typecheck, overload, and normalize.

    Interface: ``LogicElaborator@1``.

    Optional ``extension_registry`` (``ExtensionSchemaRegistry@1``) validates
    schema-governed extension nodes during elaboration.
    """

    signature: LogicSignature | None = None
    overloads: tuple[OverloadSet, ...] = ()
    normalizer: LogicNormalizer | None = None
    algebra: LogicExpressionAlgebra | None = None
    extension_registry: Any | None = None
    elaborator_id: str = "elaborator:default"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ELABORATOR_SCHEMA_VERSION

    interface: ClassVar[str] = LOGIC_ELABORATOR_INTERFACE

    def __post_init__(self) -> None:
        if self.signature is not None and not isinstance(
            self.signature, LogicSignature
        ):
            object.__setattr__(
                self,
                "signature",
                LogicSignature.from_dict(
                    _require_mapping(self.signature, "signature")
                ),
            )
        overloads = tuple(
            item
            if isinstance(item, OverloadSet)
            else OverloadSet.from_dict(_require_mapping(item, "overloads item"))
            for item in _require_sequence(self.overloads, "overloads")
        )
        object.__setattr__(self, "overloads", overloads)
        object.__setattr__(
            self,
            "elaborator_id",
            _record_id(self.elaborator_id, "elaborator_id"),
        )
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != ELABORATOR_SCHEMA_VERSION:
            raise ElaborationError(
                f"unsupported LogicElaborator schema_version "
                f"{self.schema_version!r}"
            )

    def _normalizer(self) -> LogicNormalizer:
        if self.normalizer is not None:
            return self.normalizer
        return LogicNormalizer(algebra=self.algebra)

    def _typechecker(
        self, signature: LogicSignature | None
    ) -> LogicTypechecker:
        return LogicTypechecker(signature, overloads=self.overloads)

    def typecheck(
        self,
        node: LogicNode,
        *,
        signature: LogicSignature | None = None,
        locals: Mapping[str, LogicSort] | None = None,
    ) -> TypecheckReport:
        sig = signature if signature is not None else self.signature
        return self._typechecker(sig).typecheck(
            node, signature=sig, locals=locals
        )

    def normalize_expression(self, node: LogicNode) -> LogicNode:
        return self._normalizer().normalize(node)

    def _collect_extension_diagnostics(
        self, node: LogicNode
    ) -> tuple[SyntaxDiagnostic, ...]:
        """Validate extension nodes against the bound schema registry."""

        registry = self.extension_registry
        if registry is None:
            return ()
        validate = getattr(registry, "validate_extension", None)
        if validate is None:
            return ()
        diagnostics: list[SyntaxDiagnostic] = []
        for item in node.walk():
            if item.kind is NodeKind.EXTENSION or item.kind == NodeKind.EXTENSION.value:
                report = validate(item)
                if not report.ok:
                    diagnostics.extend(report.diagnostics)
        if len(diagnostics) > MAX_DIAGNOSTICS:
            return tuple(diagnostics[:MAX_DIAGNOSTICS])
        return tuple(diagnostics)

    def elaborate(
        self,
        node: LogicNode,
        *,
        signature: LogicSignature | None = None,
        expression_id: str = "expr:elaborated",
        locals: Mapping[str, LogicSort] | None = None,
        assumptions: Sequence[str] = (),
        normalize_result: bool = True,
    ) -> ElaborationResult:
        """Elaborate *node* into a gated :class:`ElaborationResult`.

        Unresolved overloads and unknown symbols yield a non-backend-ready
        result rather than a silent success.  When an extension registry is
        bound, unknown or malformed extension payloads produce stable
        diagnostics and never become backend-ready.
        """

        if not isinstance(node, LogicNode):
            raise ElaborationError("elaborate requires a LogicNode")
        sig = signature if signature is not None else self.signature
        result_id = f"elab:{expression_id}"

        if sig is None:
            diagnostic = _diagnostic(
                "diag:elab:unknown-signature",
                CODE_UNKNOWN_SIGNATURE,
                "elaboration requires a LogicSignature; unknown signature "
                "must not reach backends",
            )
            return ElaborationResult(
                result_id=result_id,
                status=ElaborationStatus.REJECTED,
                diagnostics=(diagnostic,),
                assumptions=tuple(assumptions),
            )

        extension_diagnostics = self._collect_extension_diagnostics(node)
        if extension_diagnostics:
            return ElaborationResult(
                result_id=result_id,
                status=ElaborationStatus.FAILED,
                root=None,
                signature=sig,
                symbol_table=sig.symbol_map(),
                assumptions=tuple(assumptions),
                diagnostics=extension_diagnostics,
            )

        report = self.typecheck(node, signature=sig, locals=locals)
        if not report.ok or report.root is None:
            status = (
                ElaborationStatus.UNRESOLVED
                if report.unresolved_overloads or report.unknown_symbols
                else ElaborationStatus.FAILED
            )
            return ElaborationResult(
                result_id=result_id,
                status=status,
                root=None,
                signature=sig,
                symbol_table=sig.symbol_map(),
                unresolved_overloads=report.unresolved_overloads,
                unknown_symbols=report.unknown_symbols,
                assumptions=tuple(assumptions),
                diagnostics=report.diagnostics,
            )

        # Re-elaborate through the registry so payload codecs and result sorts
        # from ExtensionSchemaRegistry@1 are applied.  Use report.root so any
        # overload rewrites from typecheck are preserved.
        typed_root = report.root
        if self.extension_registry is not None:
            try:
                typed_root = elaborate(
                    report.root,
                    sig,
                    locals=locals,
                    extension_registry=self.extension_registry,
                )
            except (AstError, SignatureError) as error:
                diagnostic = _diagnostic(
                    "diag:elab:extension",
                    CODE_EXTENSION_FAILED,
                    str(error),
                )
                return ElaborationResult(
                    result_id=result_id,
                    status=ElaborationStatus.FAILED,
                    root=None,
                    signature=sig,
                    symbol_table=sig.symbol_map(),
                    assumptions=tuple(assumptions),
                    diagnostics=(*report.diagnostics, diagnostic),
                )

        normalized = (
            self.normalize_expression(typed_root) if normalize_result else typed_root
        )

        try:
            typed_expression = TypedExpression(
                expression_id=expression_id,
                root=typed_root,
                signature=sig,
                elaborate_on_init=False,
            )
        except AstError as error:
            diagnostic = _diagnostic(
                "diag:elab:typed-expression",
                CODE_TYPECHECK_FAILED,
                str(error),
            )
            return ElaborationResult(
                result_id=result_id,
                status=ElaborationStatus.FAILED,
                root=typed_root,
                normalized_root=normalized,
                signature=sig,
                symbol_table=sig.symbol_map(),
                assumptions=tuple(assumptions),
                diagnostics=(*report.diagnostics, diagnostic),
            )

        return ElaborationResult(
            result_id=result_id,
            status=ElaborationStatus.OK,
            typed_expression=typed_expression,
            root=typed_root,
            normalized_root=normalized,
            signature=sig,
            symbol_table=sig.symbol_map(),
            unresolved_overloads=(),
            unknown_symbols=(),
            assumptions=tuple(assumptions),
            diagnostics=report.diagnostics,
        )

    def elaborate_artifact(
        self,
        node: LogicNode,
        *,
        parse_artifact: Any,
        artifact_id: str = "elab-art:1",
        signature: LogicSignature | None = None,
        expression_id: str = "expr:elaborated",
        locals: Mapping[str, LogicSort] | None = None,
        assumptions: Sequence[str] = (),
        normalize_result: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """Elaborate *node* into an ``ElaborationArtifact@2`` with parse lineage.

        Imports :mod:`artifacts_v2` lazily so the elaborator remains usable
        without the v2 artifact module in constrained contexts.
        """

        from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
            ElaborationArtifactV2,
            ParseArtifactV2,
        )

        if not isinstance(parse_artifact, ParseArtifactV2):
            raise ElaborationError(
                "elaborate_artifact requires a ParseArtifactV2 for lineage"
            )
        result = self.elaborate(
            node,
            signature=signature,
            expression_id=expression_id,
            locals=locals,
            assumptions=assumptions,
            normalize_result=normalize_result,
        )
        return ElaborationArtifactV2.from_elaboration_result(
            result,
            artifact_id=artifact_id,
            parse_artifact=parse_artifact,
            metadata=metadata,
        )

    def elaborate_to_backend(
        self,
        node: LogicNode,
        **kwargs: Any,
    ) -> TypedExpression:
        """Elaborate and require backend readiness (fail-closed)."""

        result = self.elaborate(node, **kwargs)
        return result.require_backend_ready()

    def to_dict(self) -> dict[str, Any]:
        return {
            "elaborator_id": self.elaborator_id,
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "overloads": [item.to_dict() for item in self.overloads],
            "schema_version": self.schema_version,
            "signature": None
            if self.signature is None
            else self.signature.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicElaborator":
        payload = _require_mapping(data, "LogicElaborator")
        interface = payload.get("interface")
        if interface is not None and interface != LOGIC_ELABORATOR_INTERFACE:
            raise ElaborationError(
                f"unsupported LogicElaborator interface {interface!r}"
            )
        sig_payload = payload.get("signature")
        return cls(
            signature=(
                None
                if sig_payload is None
                else LogicSignature.from_dict(
                    _require_mapping(sig_payload, "signature")
                )
            ),
            overloads=tuple(
                OverloadSet.from_dict(_require_mapping(item, "overloads item"))
                for item in _require_sequence(
                    payload.get("overloads") or (), "overloads"
                )
            ),
            elaborator_id=str(payload.get("elaborator_id") or "elaborator:default"),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or ELABORATOR_SCHEMA_VERSION
            ),
        )


DEFAULT_ELABORATOR: Final = LogicElaborator()


def elaborate_expression(
    node: LogicNode,
    signature: LogicSignature,
    **kwargs: Any,
) -> ElaborationResult:
    """Module-level elaboration helper."""

    return LogicElaborator(signature=signature).elaborate(node, **kwargs)


__all__ = [
    "CODE_AMBIGUOUS_OVERLOAD",
    "CODE_ARITY_MISMATCH",
    "CODE_EXTENSION_FAILED",
    "CODE_KIND_MISMATCH",
    "CODE_NOT_BACKEND_READY",
    "CODE_SORT_MISMATCH",
    "CODE_TYPECHECK_FAILED",
    "CODE_UNKNOWN_SIGNATURE",
    "CODE_UNKNOWN_SYMBOL",
    "CODE_UNRESOLVED_OVERLOAD",
    "DEFAULT_ELABORATOR",
    "DEFAULT_NORMALIZER",
    "ELABORATION_MODULE_VERSION",
    "ELABORATION_RESULT_SCHEMA_VERSION",
    "ELABORATOR_SCHEMA_VERSION",
    "LOGIC_ELABORATOR_INTERFACE",
    "OVERLOAD_SET_SCHEMA_VERSION",
    "ElaborationError",
    "ElaborationResult",
    "ElaborationStatus",
    "LogicElaborator",
    "LogicNormalizer",
    "LogicTypechecker",
    "OverloadCandidate",
    "OverloadSet",
    "TypecheckReport",
    "UnknownSignatureError",
    "UnresolvedOverloadError",
    "elaborate_expression",
    "normalize",
    "resolve_overload",
]

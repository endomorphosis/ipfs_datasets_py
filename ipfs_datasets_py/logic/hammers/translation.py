"""Typed translation of hammer goals/premises to TPTP and SMT-LIB (HAMMER-007).

This module implements the ``## HAMMER-007`` entry of
``docs/logic/itp_hammer_taskboard.todo.md``: *"Lower only supported fragments
through explicit monomorphization, lambda lifting or elimination, and type
encodings. Persist a translation map and obligations for each transformed
construct. Round-trip tests and negative fixtures must prove that unsupported
dependent, higher-order, or opaque constructs fail closed."*

Typed intermediate representation
----------------------------------
Native ITP goal/hypothesis text (Lean/Coq/Isabelle) is not translated
directly — that would require a full elaborator for each ITP. Instead this
module operates on a small, explicit, ITP-agnostic *typed term
representation* (:class:`TypeRef`/:class:`Term` and their subclasses) that a
caller (an elaboration step, a test, or a future HAMMER-006 extension)
constructs once per goal/premise. Every construct in that representation is
either lowered faithfully, lowered with recorded *obligations*, or rejected
outright with an explicit reason — never silently dropped.

Pipeline stages (see :func:`TranslationContext.translate`)
------------------------------------------------------------
1. **Dependent-type rejection.** Any :class:`DependentTypeRef` — a type that
   depends on a term-level value — anywhere in the construct fails closed
   immediately; no encoding of dependent types into the (non-dependent) TPTP
   or SMT-LIB target fragments is attempted.
2. **Opaque-construct rejection.** Any :class:`Opaque` node (a placeholder
   for something the caller could not resolve into a known shape, e.g. a
   tactic block, metavariable, or incomplete proof marker) fails closed
   immediately.
3. **Explicit monomorphization.** Every :class:`TypeVarRef` occurrence is
   substituted per a caller-supplied instance mapping (type-variable name ->
   concrete :class:`SortRef`). Every substitution actually applied is
   recorded as an obligation. Any type variable left unresolved after
   substitution fails closed.
4. **Lambda elimination.** Every ``App(Lambda(...), args)`` redex (a lambda
   immediately, fully applied to matching arguments) is beta-reduced away.
5. **Lambda lifting.** If, after elimination, the *entire* construct is
   itself a bare :class:`Lambda` (i.e. the construct defines a named
   function/predicate), it is lifted into a fresh top-level function symbol
   plus a universally quantified defining equation, recorded as an
   obligation. Any :class:`Lambda` that still remains anywhere else in the
   term afterwards is a genuine escaping first-class function value, which
   plain first-order TPTP/SMT-LIB cannot represent, and fails closed.
6. **Higher-order rejection.** Quantification over a function-typed or
   propositional variable, and passing a function-typed term as an
   argument, both fail closed — the supported fragment is first-order logic
   with explicit, monomorphic, many-sorted type encodings only.
7. **Rendering.** The fully lowered term is rendered to the requested target
   (:mod:`.tptp` or :mod:`.smtlib`); each declared sort/symbol/lifted
   function is recorded in the persisted :class:`TranslationMap`.

Every step failure produces a
:class:`~ipfs_datasets_py.logic.hammers.models.TranslationRecord` with
``status=TranslationStatus.UNSUPPORTED`` and a populated
``unsupported_reason`` — never a partially translated, silently-erased
result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, Union

from .corpus import compute_content_digest
from .models import (
    SCHEMA_VERSION,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
    _require_nonempty_str,
    _require_schema_version,
)

__all__ = [
    "SCHEMA_VERSION",
    # Errors
    "TranslationError",
    "MalformedTermError",
    "UnsupportedConstructError",
    # Types
    "SortRef",
    "TypeVarRef",
    "FunctionTypeRef",
    "DependentTypeRef",
    "TypeRef",
    "PROP_SORT",
    "is_function_type",
    # Terms
    "LambdaParam",
    "Var",
    "Const",
    "App",
    "Lambda",
    "Forall",
    "Exists",
    "Not",
    "And",
    "Or",
    "Implies",
    "Iff",
    "Eq",
    "BoolLit",
    "Opaque",
    "Term",
    "infer_type",
    "free_term_vars",
    "walk_term_types",
    "substitute_term",
    "substitute_type_vars",
    "substitute_type_vars_in_term",
    # Pipeline building blocks
    "LambdaLiftedDefinition",
    "TranslationMapEntry",
    "TranslationMap",
    "NormalizedConstruct",
    "beta_reduce",
    "normalize_construct",
    "find_dependent_type_issue",
    "find_opaque_issue",
    "find_type_var_issue",
    "find_structural_issue",
    "sanitize_identifier",
    # Orchestration
    "TranslationContext",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TranslationError(ValueError):
    """Base class for all translation errors raised by this module."""


class MalformedTermError(TranslationError):
    """Raised when a :class:`Term` tree is not well-typed (e.g. an
    application whose argument count does not match its function's arity).

    This signals a construction bug in the caller-supplied term, distinct
    from :class:`UnsupportedConstructError`, which signals a well-formed but
    unsupported *fragment* (dependent types, opaque constructs, escaping
    lambdas, higher-order quantification/application)."""


class UnsupportedConstructError(TranslationError):
    """Raised internally to short-circuit the pipeline when a construct
    cannot be lowered. Always carries a human-readable ``reason`` that
    becomes :attr:`~ipfs_datasets_py.logic.hammers.models.TranslationRecord.unsupported_reason`."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SortRef:
    """A concrete, monomorphic domain sort (e.g. ``nat``, ``bool``, a custom
    inductive type name)."""

    name: str

    def __post_init__(self) -> None:
        _require_nonempty_str(self.name, field_name="name", owner="SortRef")


@dataclass(frozen=True)
class TypeVarRef:
    """A polymorphic type variable that must be resolved by an explicit
    monomorphization instance before translation can proceed."""

    name: str

    def __post_init__(self) -> None:
        _require_nonempty_str(self.name, field_name="name", owner="TypeVarRef")


@dataclass(frozen=True)
class FunctionTypeRef:
    """An n-ary function/predicate type ``(params...) -> result``."""

    params: Tuple["TypeRef", ...]
    result: "TypeRef"

    def __post_init__(self) -> None:
        if not isinstance(self.params, tuple):
            object.__setattr__(self, "params", tuple(self.params))


@dataclass(frozen=True)
class DependentTypeRef:
    """A type that depends on a term-level value (e.g. ``Vec n``, ``Fin k``,
    a ``Pi``/``forall`` type family). Always fails closed — dependent types
    have no encoding in the plain first-order TPTP/SMT-LIB fragments this
    module targets."""

    description: str

    def __post_init__(self) -> None:
        _require_nonempty_str(
            self.description, field_name="description", owner="DependentTypeRef"
        )


TypeRef = Union[SortRef, TypeVarRef, FunctionTypeRef, DependentTypeRef]

#: Reserved sort marking a term as a proposition/boolean. Never renderable as
#: a domain sort; used only to detect propositional (higher-order)
#: quantification and to check that a fully lowered goal is a proposition.
PROP_SORT = SortRef("$prop")

#: Reserved sort used as the default type of an :class:`Opaque` placeholder.
OPAQUE_SORT = SortRef("$opaque")


def is_function_type(type_ref: TypeRef) -> bool:
    """Return whether ``type_ref`` is a :class:`FunctionTypeRef`."""

    return isinstance(type_ref, FunctionTypeRef)


def _contains_type_var(type_ref: TypeRef) -> bool:
    """Return whether ``type_ref`` mentions an unresolved :class:`TypeVarRef`
    anywhere (including nested inside a :class:`FunctionTypeRef`)."""

    if isinstance(type_ref, TypeVarRef):
        return True
    if isinstance(type_ref, FunctionTypeRef):
        return any(_contains_type_var(p) for p in type_ref.params) or _contains_type_var(
            type_ref.result
        )
    return False


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LambdaParam:
    """One binder ``name : type`` of a :class:`Lambda`."""

    name: str
    type: TypeRef

    def __post_init__(self) -> None:
        _require_nonempty_str(self.name, field_name="name", owner="LambdaParam")


@dataclass(frozen=True)
class Var:
    """A bound (or free) variable reference."""

    name: str
    type: TypeRef

    def __post_init__(self) -> None:
        _require_nonempty_str(self.name, field_name="name", owner="Var")


@dataclass(frozen=True)
class Const:
    """A named function/predicate/constant symbol.

    Attributes:
        name: The symbol's stable source-level name.
        type: The symbol's (possibly n-ary function) type.
        opaque: Whether this symbol is itself an opaque placeholder (e.g. an
            axiom or elaboration failure the caller could not resolve to a
            known definition). ``opaque=True`` always fails closed via
            :func:`find_opaque_issue`, distinct from an ordinary
            uninterpreted function symbol (``opaque=False``), which is a
            perfectly normal, supported first-order construct.
        opaque_reason: Human-readable reason, required when ``opaque`` is
            ``True``.
    """

    name: str
    type: TypeRef
    opaque: bool = False
    opaque_reason: Optional[str] = None

    def __post_init__(self) -> None:
        _require_nonempty_str(self.name, field_name="name", owner="Const")
        if self.opaque and not (
            isinstance(self.opaque_reason, str) and self.opaque_reason.strip()
        ):
            raise ValueError("Const.opaque_reason must be set when opaque=True")


@dataclass(frozen=True)
class App:
    """An n-ary application ``fn(args...)``."""

    fn: "Term"
    args: Tuple["Term", ...]

    def __post_init__(self) -> None:
        if not isinstance(self.args, tuple):
            object.__setattr__(self, "args", tuple(self.args))


@dataclass(frozen=True)
class Lambda:
    """An anonymous, possibly multi-argument function ``fun params => body``.

    Only survives the pipeline in two ways: eliminated via beta-reduction
    (see :func:`beta_reduce`) or lifted into a top-level defining equation
    when it is the *entire* construct being translated (see
    :func:`normalize_construct`). Any other occurrence is a genuine
    higher-order escape and fails closed.
    """

    params: Tuple[LambdaParam, ...]
    body: "Term"

    def __post_init__(self) -> None:
        if not isinstance(self.params, tuple):
            object.__setattr__(self, "params", tuple(self.params))
        if not self.params:
            raise ValueError("Lambda.params must be non-empty")


@dataclass(frozen=True)
class Forall:
    """Universal quantification ``forall var : var_type, body``."""

    var: str
    var_type: TypeRef
    body: "Term"

    def __post_init__(self) -> None:
        _require_nonempty_str(self.var, field_name="var", owner="Forall")


@dataclass(frozen=True)
class Exists:
    """Existential quantification ``exists var : var_type, body``."""

    var: str
    var_type: TypeRef
    body: "Term"

    def __post_init__(self) -> None:
        _require_nonempty_str(self.var, field_name="var", owner="Exists")


@dataclass(frozen=True)
class Not:
    term: "Term"


@dataclass(frozen=True)
class And:
    left: "Term"
    right: "Term"


@dataclass(frozen=True)
class Or:
    left: "Term"
    right: "Term"


@dataclass(frozen=True)
class Implies:
    left: "Term"
    right: "Term"


@dataclass(frozen=True)
class Iff:
    left: "Term"
    right: "Term"


@dataclass(frozen=True)
class Eq:
    left: "Term"
    right: "Term"


@dataclass(frozen=True)
class BoolLit:
    value: bool


@dataclass(frozen=True)
class Opaque:
    """A placeholder for a construct that could not be resolved into a known
    shape (an incomplete proof marker, a metavariable, an un-elaborated
    tactic block, ...). Always fails closed via :func:`find_opaque_issue`.
    """

    reason: str
    type: TypeRef = OPAQUE_SORT

    def __post_init__(self) -> None:
        _require_nonempty_str(self.reason, field_name="reason", owner="Opaque")


Term = Union[
    Var,
    Const,
    App,
    Lambda,
    Forall,
    Exists,
    Not,
    And,
    Or,
    Implies,
    Iff,
    Eq,
    BoolLit,
    Opaque,
]

_BIN_CONNECTIVES = (And, Or, Implies, Iff)


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------


def infer_type(term: Term) -> TypeRef:
    """Infer the type of ``term``.

    Raises:
        MalformedTermError: If ``term`` is not well-typed (e.g. an
            application whose function is not of function type, or whose
            argument count does not match the function's arity).
    """

    if isinstance(term, (Var, Const)):
        return term.type
    if isinstance(term, App):
        fn_type = infer_type(term.fn)
        if not isinstance(fn_type, FunctionTypeRef):
            raise MalformedTermError(
                f"App.fn has non-function type {fn_type!r}; cannot apply {len(term.args)} argument(s)"
            )
        if len(fn_type.params) != len(term.args):
            raise MalformedTermError(
                f"App arity mismatch: function expects {len(fn_type.params)} argument(s), "
                f"got {len(term.args)}"
            )
        for expected, arg in zip(fn_type.params, term.args):
            actual = infer_type(arg)
            if (
                not _contains_type_var(expected)
                and not _contains_type_var(actual)
                and actual != expected
            ):
                raise MalformedTermError(
                    f"App argument type mismatch: expected {expected!r}, got {actual!r}"
                )
        return fn_type.result
    if isinstance(term, Lambda):
        return FunctionTypeRef(
            params=tuple(p.type for p in term.params), result=infer_type(term.body)
        )
    if isinstance(term, (Forall, Exists, Not, Eq, BoolLit)) or isinstance(
        term, _BIN_CONNECTIVES
    ):
        return PROP_SORT
    if isinstance(term, Opaque):
        return term.type
    raise MalformedTermError(f"cannot infer type of unrecognized term node {term!r}")


# ---------------------------------------------------------------------------
# Free variables / substitution
# ---------------------------------------------------------------------------


def free_term_vars(term: Term, *, bound: FrozenSet[str] = frozenset()) -> FrozenSet[str]:
    """Return the set of free variable names occurring in ``term``, given an
    already-``bound`` set of names shadowed by enclosing binders."""

    if isinstance(term, Var):
        return frozenset() if term.name in bound else frozenset({term.name})
    if isinstance(term, Const):
        return frozenset()
    if isinstance(term, App):
        result: FrozenSet[str] = free_term_vars(term.fn, bound=bound)
        for arg in term.args:
            result = result | free_term_vars(arg, bound=bound)
        return result
    if isinstance(term, Lambda):
        inner_bound = bound | {p.name for p in term.params}
        return free_term_vars(term.body, bound=inner_bound)
    if isinstance(term, (Forall, Exists)):
        return free_term_vars(term.body, bound=bound | {term.var})
    if isinstance(term, Not):
        return free_term_vars(term.term, bound=bound)
    if isinstance(term, _BIN_CONNECTIVES) or isinstance(term, Eq):
        return free_term_vars(term.left, bound=bound) | free_term_vars(
            term.right, bound=bound
        )
    if isinstance(term, (BoolLit, Opaque)):
        return frozenset()
    raise MalformedTermError(f"cannot compute free variables of {term!r}")


def _free_var_types(term: Term, *, bound: FrozenSet[str]) -> Dict[str, TypeRef]:
    """Like :func:`free_term_vars` but returns a name -> type mapping (first
    occurrence wins; well-typed input is assumed consistent)."""

    out: Dict[str, TypeRef] = {}

    def visit(node: Term, bound_here: FrozenSet[str]) -> None:
        if isinstance(node, Var):
            if node.name not in bound_here and node.name not in out:
                out[node.name] = node.type
        elif isinstance(node, Const):
            pass
        elif isinstance(node, App):
            visit(node.fn, bound_here)
            for arg in node.args:
                visit(arg, bound_here)
        elif isinstance(node, Lambda):
            visit(node.body, bound_here | {p.name for p in node.params})
        elif isinstance(node, (Forall, Exists)):
            visit(node.body, bound_here | {node.var})
        elif isinstance(node, Not):
            visit(node.term, bound_here)
        elif isinstance(node, _BIN_CONNECTIVES) or isinstance(node, Eq):
            visit(node.left, bound_here)
            visit(node.right, bound_here)
        elif isinstance(node, (BoolLit, Opaque)):
            pass
        else:
            raise MalformedTermError(f"cannot compute free variable types of {node!r}")

    visit(term, bound)
    return out


def _fresh_name(base: str, avoid: FrozenSet[str]) -> str:
    if base not in avoid:
        return base
    counter = 0
    candidate = f"{base}_{counter}"
    while candidate in avoid:
        counter += 1
        candidate = f"{base}_{counter}"
    return candidate


def substitute_term(term: Term, name: str, replacement: Term) -> Term:
    """Capture-avoiding substitution of ``replacement`` for free occurrences
    of variable ``name`` in ``term``."""

    if isinstance(term, Var):
        return replacement if term.name == name else term
    if isinstance(term, Const):
        return term
    if isinstance(term, App):
        return App(
            fn=substitute_term(term.fn, name, replacement),
            args=tuple(substitute_term(a, name, replacement) for a in term.args),
        )
    if isinstance(term, Lambda):
        if any(p.name == name for p in term.params):
            return term  # shadowed; nothing to substitute inside
        repl_free = free_term_vars(replacement)
        params = term.params
        body = term.body
        for p in term.params:
            if p.name in repl_free:
                avoid = repl_free | free_term_vars(body) | {name}
                fresh = _fresh_name(p.name, avoid)
                body = substitute_term(body, p.name, Var(fresh, p.type))
                params = tuple(
                    LambdaParam(fresh, pp.type) if pp.name == p.name else pp
                    for pp in params
                )
        return Lambda(params=params, body=substitute_term(body, name, replacement))
    if isinstance(term, (Forall, Exists)):
        if term.var == name:
            return term
        repl_free = free_term_vars(replacement)
        if term.var in repl_free:
            avoid = repl_free | free_term_vars(term.body) | {name}
            fresh = _fresh_name(term.var, avoid)
            new_body = substitute_term(term.body, term.var, Var(fresh, term.var_type))
            new_body = substitute_term(new_body, name, replacement)
            return type(term)(var=fresh, var_type=term.var_type, body=new_body)
        return type(term)(
            var=term.var,
            var_type=term.var_type,
            body=substitute_term(term.body, name, replacement),
        )
    if isinstance(term, Not):
        return Not(substitute_term(term.term, name, replacement))
    if isinstance(term, _BIN_CONNECTIVES):
        return type(term)(
            left=substitute_term(term.left, name, replacement),
            right=substitute_term(term.right, name, replacement),
        )
    if isinstance(term, Eq):
        return Eq(
            left=substitute_term(term.left, name, replacement),
            right=substitute_term(term.right, name, replacement),
        )
    if isinstance(term, (BoolLit, Opaque)):
        return term
    raise MalformedTermError(f"cannot substitute into {term!r}")


# ---------------------------------------------------------------------------
# Type substitution (monomorphization)
# ---------------------------------------------------------------------------


def substitute_type_vars(type_ref: TypeRef, mapping: Dict[str, SortRef]) -> TypeRef:
    """Substitute every :class:`TypeVarRef` in ``type_ref`` per ``mapping``
    (type-variable name -> concrete :class:`SortRef`). Unmapped type
    variables are left untouched (detected later by
    :func:`find_type_var_issue`)."""

    if isinstance(type_ref, TypeVarRef):
        return mapping.get(type_ref.name, type_ref)
    if isinstance(type_ref, SortRef):
        return type_ref
    if isinstance(type_ref, FunctionTypeRef):
        return FunctionTypeRef(
            params=tuple(substitute_type_vars(p, mapping) for p in type_ref.params),
            result=substitute_type_vars(type_ref.result, mapping),
        )
    if isinstance(type_ref, DependentTypeRef):
        return type_ref
    raise MalformedTermError(f"cannot substitute type variables in {type_ref!r}")


def substitute_type_vars_in_term(term: Term, mapping: Dict[str, SortRef]) -> Term:
    """Apply :func:`substitute_type_vars` to every type annotation occurring
    anywhere in ``term``."""

    def st(t: TypeRef) -> TypeRef:
        return substitute_type_vars(t, mapping)

    if isinstance(term, Var):
        return Var(name=term.name, type=st(term.type))
    if isinstance(term, Const):
        return Const(
            name=term.name,
            type=st(term.type),
            opaque=term.opaque,
            opaque_reason=term.opaque_reason,
        )
    if isinstance(term, App):
        return App(
            fn=substitute_type_vars_in_term(term.fn, mapping),
            args=tuple(substitute_type_vars_in_term(a, mapping) for a in term.args),
        )
    if isinstance(term, Lambda):
        return Lambda(
            params=tuple(
                LambdaParam(p.name, st(p.type)) for p in term.params
            ),
            body=substitute_type_vars_in_term(term.body, mapping),
        )
    if isinstance(term, (Forall, Exists)):
        return type(term)(
            var=term.var,
            var_type=st(term.var_type),
            body=substitute_type_vars_in_term(term.body, mapping),
        )
    if isinstance(term, Not):
        return Not(substitute_type_vars_in_term(term.term, mapping))
    if isinstance(term, _BIN_CONNECTIVES):
        return type(term)(
            left=substitute_type_vars_in_term(term.left, mapping),
            right=substitute_type_vars_in_term(term.right, mapping),
        )
    if isinstance(term, Eq):
        return Eq(
            left=substitute_type_vars_in_term(term.left, mapping),
            right=substitute_type_vars_in_term(term.right, mapping),
        )
    if isinstance(term, BoolLit):
        return term
    if isinstance(term, Opaque):
        return Opaque(reason=term.reason, type=st(term.type))
    raise MalformedTermError(f"cannot substitute type variables into {term!r}")


def walk_term_types(term: Term) -> List[TypeRef]:
    """Return every :class:`TypeRef` attached anywhere in ``term`` (on
    variables, constants, lambda parameters, and quantifier binders), in a
    deterministic depth-first order."""

    out: List[TypeRef] = []

    def visit(node: Term) -> None:
        if isinstance(node, (Var, Const)):
            out.append(node.type)
        elif isinstance(node, App):
            visit(node.fn)
            for a in node.args:
                visit(a)
        elif isinstance(node, Lambda):
            for p in node.params:
                out.append(p.type)
            visit(node.body)
        elif isinstance(node, (Forall, Exists)):
            out.append(node.var_type)
            visit(node.body)
        elif isinstance(node, Not):
            visit(node.term)
        elif isinstance(node, _BIN_CONNECTIVES) or isinstance(node, Eq):
            visit(node.left)
            visit(node.right)
        elif isinstance(node, BoolLit):
            pass
        elif isinstance(node, Opaque):
            out.append(node.type)
        else:
            raise MalformedTermError(f"cannot walk types of {node!r}")

    visit(term)
    return out


def _walk_type_tree(type_ref: TypeRef) -> List[TypeRef]:
    """Return ``type_ref`` and every type nested inside it (function
    parameters/result), depth-first."""

    out = [type_ref]
    if isinstance(type_ref, FunctionTypeRef):
        for p in type_ref.params:
            out.extend(_walk_type_tree(p))
        out.extend(_walk_type_tree(type_ref.result))
    return out


# ---------------------------------------------------------------------------
# Fail-closed detection
# ---------------------------------------------------------------------------


def find_dependent_type_issue(term: Term) -> Optional[str]:
    """Return a human-readable reason if ``term`` contains a
    :class:`DependentTypeRef` anywhere, else ``None``."""

    for type_ref in walk_term_types(term):
        for nested in _walk_type_tree(type_ref):
            if isinstance(nested, DependentTypeRef):
                return f"dependent type is not supported: {nested.description}"
    return None


def find_opaque_issue(term: Term) -> Optional[str]:
    """Return a human-readable reason if ``term`` contains an
    :class:`Opaque` node, or an opaque :class:`Const`, anywhere, else
    ``None``."""

    found: List[str] = []

    def visit(node: Term) -> None:
        if found:
            return
        if isinstance(node, Opaque):
            found.append(f"opaque construct: {node.reason}")
        elif isinstance(node, Const):
            if node.opaque:
                found.append(
                    f"opaque construct: symbol '{node.name}' is opaque: {node.opaque_reason}"
                )
        elif isinstance(node, Var):
            pass
        elif isinstance(node, App):
            visit(node.fn)
            for a in node.args:
                visit(a)
        elif isinstance(node, Lambda):
            visit(node.body)
        elif isinstance(node, (Forall, Exists)):
            visit(node.body)
        elif isinstance(node, Not):
            visit(node.term)
        elif isinstance(node, _BIN_CONNECTIVES) or isinstance(node, Eq):
            visit(node.left)
            visit(node.right)
        elif isinstance(node, BoolLit):
            pass
        else:
            raise MalformedTermError(f"cannot scan for opaque constructs in {node!r}")

    visit(term)
    return found[0] if found else None


def find_type_var_issue(term: Term) -> Optional[str]:
    """Return a human-readable reason if ``term`` still contains an
    unresolved :class:`TypeVarRef` anywhere, else ``None``. Call this only
    *after* attempting monomorphization."""

    for type_ref in walk_term_types(term):
        for nested in _walk_type_tree(type_ref):
            if isinstance(nested, TypeVarRef):
                return (
                    f"unresolved type variable '{nested.name}': no monomorphization "
                    "instance was provided for it"
                )
    return None


def _display_fn_name(fn: Term) -> str:
    if isinstance(fn, Const):
        return fn.name
    if isinstance(fn, Var):
        return fn.name
    return "<anonymous>"


def find_structural_issue(term: Term) -> Optional[str]:
    """Return a human-readable reason if ``term`` still contains a
    higher-order construct after normalization: an escaping :class:`Lambda`,
    quantification over a function-typed or propositional variable, or a
    function-typed term passed as an argument. Returns ``None`` when the
    fully lowered term is a supported, first-order fragment."""

    if isinstance(term, Lambda):
        return (
            "higher-order: lambda used as a first-class value; it could not be "
            "eliminated by beta-reduction or lambda-lifted as a top-level definition"
        )
    if isinstance(term, (Forall, Exists)):
        kind = "Forall" if isinstance(term, Forall) else "Exists"
        if is_function_type(term.var_type):
            return (
                f"higher-order quantification: {kind} binds '{term.var}' of function "
                "type, which first-order TPTP/SMT-LIB cannot quantify over"
            )
        if term.var_type == PROP_SORT:
            return (
                f"higher-order quantification: {kind} binds '{term.var}' of "
                "propositional type (second-order/propositional quantification)"
            )
        return find_structural_issue(term.body)
    if isinstance(term, App):
        for arg in term.args:
            arg_type = infer_type(arg)
            if is_function_type(arg_type):
                return (
                    "higher-order: function-typed term passed as an argument to "
                    f"'{_display_fn_name(term.fn)}'"
                )
            if arg_type == PROP_SORT:
                return (
                    "higher-order: boolean/propositional-typed term passed as an "
                    f"argument to '{_display_fn_name(term.fn)}' (only individual-sorted "
                    "arguments are supported by the first-order fragment this module "
                    "targets)"
                )
            issue = find_structural_issue(arg)
            if issue:
                return issue
        return find_structural_issue(term.fn) if isinstance(term.fn, Lambda) else None
    if isinstance(term, Not):
        return find_structural_issue(term.term)
    if isinstance(term, _BIN_CONNECTIVES) or isinstance(term, Eq):
        return find_structural_issue(term.left) or find_structural_issue(term.right)
    if isinstance(term, (Const, Var, BoolLit)):
        return None
    if isinstance(term, Opaque):
        return f"opaque construct: {term.reason}"
    raise MalformedTermError(f"cannot scan for higher-order constructs in {term!r}")


# ---------------------------------------------------------------------------
# Beta reduction (lambda elimination)
# ---------------------------------------------------------------------------


def beta_reduce(term: Term) -> Tuple[Term, int]:
    """Eliminate every ``App(Lambda(...), args)`` redex in ``term`` by
    repeated beta-reduction to a fixpoint.

    Returns:
        A ``(normalized_term, reduction_count)`` pair; ``reduction_count`` is
        the number of beta-reductions actually performed (used to decide
        whether an "eliminated lambda" obligation should be recorded).
    """

    count = 0

    def go(node: Term) -> Term:
        nonlocal count
        if isinstance(node, (Var, Const, BoolLit)):
            return node
        if isinstance(node, App):
            fn = go(node.fn)
            args = tuple(go(a) for a in node.args)
            if isinstance(fn, Lambda) and len(fn.params) == len(args):
                body = fn.body
                for p, a in zip(fn.params, args):
                    body = substitute_term(body, p.name, a)
                count += 1
                return go(body)
            return App(fn=fn, args=args)
        if isinstance(node, Lambda):
            return Lambda(params=node.params, body=go(node.body))
        if isinstance(node, (Forall, Exists)):
            return type(node)(var=node.var, var_type=node.var_type, body=go(node.body))
        if isinstance(node, Not):
            return Not(go(node.term))
        if isinstance(node, _BIN_CONNECTIVES):
            return type(node)(left=go(node.left), right=go(node.right))
        if isinstance(node, Eq):
            return Eq(left=go(node.left), right=go(node.right))
        if isinstance(node, Opaque):
            return node
        raise MalformedTermError(f"cannot beta-reduce {node!r}")

    reduced = go(term)
    return reduced, count


# ---------------------------------------------------------------------------
# Lambda lifting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LambdaLiftedDefinition:
    """A fresh top-level function/predicate symbol introduced by lifting a
    bare top-level :class:`Lambda` out of a construct.

    Attributes:
        name: The fresh symbol's name.
        params: The lifted function's full parameter list (captured free
            variables, in deterministic sorted order, followed by the
            original lambda's own parameters).
        body: The (already normalized) lambda body, in terms of ``params``.
        source_construct: The construct identifier this definition was
            lifted from.
    """

    name: str
    params: Tuple[LambdaParam, ...]
    body: Term
    source_construct: str


def _lift_top_level_lambda(
    lam: Lambda, *, lifted_name: str, source_construct: str
) -> Tuple[Term, str, LambdaLiftedDefinition]:
    """Lift a bare top-level :class:`Lambda` into a fresh named function
    symbol plus a universally quantified defining equation.

    Returns:
        A ``(definition_formula, obligation, lifted_definition)`` triple.
    """

    bound = frozenset(p.name for p in lam.params)
    free_types = _free_var_types(lam.body, bound=bound)
    free_pairs = sorted(free_types.items())
    free_params = tuple(LambdaParam(name=n, type=t) for n, t in free_pairs)
    all_params = free_params + lam.params

    lifted_type = FunctionTypeRef(
        params=tuple(p.type for p in all_params), result=infer_type(lam.body)
    )
    lifted_const = Const(name=lifted_name, type=lifted_type)
    lhs = App(fn=lifted_const, args=tuple(Var(p.name, p.type) for p in all_params))
    equation: Term = Eq(left=lhs, right=lam.body)
    for p in reversed(all_params):
        equation = Forall(var=p.name, var_type=p.type, body=equation)

    obligation = (
        f"lambda-lifted definition of '{source_construct}' to fresh function symbol "
        f"'{lifted_name}' with captured free variable(s) {[n for n, _ in free_pairs]!r}"
    )
    lifted_def = LambdaLiftedDefinition(
        name=lifted_name, params=all_params, body=lam.body, source_construct=source_construct
    )
    return equation, obligation, lifted_def


@dataclass(frozen=True)
class NormalizedConstruct:
    """The result of :func:`normalize_construct`: a fully beta-reduced and
    (if applicable) lambda-lifted term, plus the obligations and lifted
    definitions produced along the way."""

    term: Term
    obligations: Tuple[str, ...]
    lifted_definitions: Tuple[LambdaLiftedDefinition, ...]


def normalize_construct(
    term: Term, *, source_construct: str, lifted_name: str
) -> NormalizedConstruct:
    """Perform lambda elimination (beta-reduction) followed by top-level
    lambda lifting.

    Args:
        term: The (already monomorphized) term to normalize.
        source_construct: Identifier of the construct being translated, used
            to name any lifted function and in obligation text.
        lifted_name: The fresh symbol name to use if the entire construct
            turns out to be a bare top-level lambda.
    """

    reduced, reduction_count = beta_reduce(term)
    obligations: List[str] = []
    if reduction_count:
        obligations.append(
            f"beta-eliminated {reduction_count} lambda application(s) in '{source_construct}'"
        )
    lifted_definitions: List[LambdaLiftedDefinition] = []
    if isinstance(reduced, Lambda):
        reduced, obligation, lifted_def = _lift_top_level_lambda(
            reduced, lifted_name=lifted_name, source_construct=source_construct
        )
        obligations.append(obligation)
        lifted_definitions.append(lifted_def)
    return NormalizedConstruct(
        term=reduced,
        obligations=tuple(obligations),
        lifted_definitions=tuple(lifted_definitions),
    )


# ---------------------------------------------------------------------------
# Identifier sanitization (shared by .tptp / .smtlib name registries)
# ---------------------------------------------------------------------------


def sanitize_identifier(name: str, *, fallback_prefix: str = "sym") -> str:
    """Return a deterministic, ASCII-alphanumeric-plus-underscore identifier
    derived from ``name``, suitable as a base for either TPTP or SMT-LIB
    naming. Never empty."""

    out_chars = []
    for ch in name:
        if ch.isalnum() and ch.isascii():
            out_chars.append(ch)
        else:
            out_chars.append("_")
    candidate = "".join(out_chars).strip("_")
    if not candidate:
        candidate = fallback_prefix
    if candidate[0].isdigit():
        candidate = f"{fallback_prefix}_{candidate}"
    return candidate


# ---------------------------------------------------------------------------
# Translation map
# ---------------------------------------------------------------------------


@dataclass
class TranslationMapEntry:
    """One entry of the persisted translation map: how a single source-level
    name was rendered into a translation target.

    Attributes:
        source_name: The original (pre-translation) name.
        target_name: The name actually emitted in the rendered text.
        target: Which translation target this mapping applies to.
        kind: What kind of symbol this is (``"sort"``, ``"function"``,
            ``"variable"``, or ``"lifted_function"``).
        origin: How this name came to exist (``"original"``,
            ``"monomorphized"``, or ``"lambda-lifted"``).
    """

    source_name: str
    target_name: str
    target: TranslationTarget
    kind: str
    origin: str = "original"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_name": self.source_name,
            "target_name": self.target_name,
            "target": self.target.value,
            "kind": self.kind,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranslationMapEntry":
        data = dict(data)
        if isinstance(data.get("target"), str):
            data["target"] = TranslationTarget(data["target"])
        return cls(**data)


@dataclass
class TranslationMap:
    """The persisted mapping of every source-level name to its rendered
    target-format name, accumulated across every construct translated within
    one :class:`TranslationContext`.

    This is the "translation map" required by the HAMMER-007 acceptance
    criterion: it lets a reconstruction step (or a human auditor) trace every
    symbol appearing in emitted TPTP/SMT-LIB text back to the original
    source construct it came from, including symbols introduced by
    monomorphization or lambda lifting.
    """

    entries: List[TranslationMapEntry] = field(default_factory=list)

    def add(
        self,
        *,
        source_name: str,
        target_name: str,
        target: TranslationTarget,
        kind: str,
        origin: str = "original",
    ) -> None:
        self.entries.append(
            TranslationMapEntry(
                source_name=source_name,
                target_name=target_name,
                target=target,
                kind=kind,
                origin=origin,
            )
        )

    def lookup(
        self, source_name: str, *, target: TranslationTarget
    ) -> Optional[TranslationMapEntry]:
        for entry in self.entries:
            if entry.source_name == source_name and entry.target is target:
                return entry
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {"entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranslationMap":
        return cls(
            entries=[TranslationMapEntry.from_dict(e) for e in data.get("entries", [])]
        )

    def content_digest(self) -> str:
        return compute_content_digest(self.to_dict())


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class TranslationContext:
    """Orchestrates the full HAMMER-007 pipeline for one
    :class:`~ipfs_datasets_py.logic.hammers.models.HammerRequest` and
    persists the accumulated :class:`TranslationMap` and every produced
    :class:`~ipfs_datasets_py.logic.hammers.models.TranslationRecord`.
    """

    request_id: str
    translation_map: TranslationMap = field(default_factory=TranslationMap)
    records: List[TranslationRecord] = field(default_factory=list)
    _lift_counter: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        _require_nonempty_str(self.request_id, field_name="request_id", owner="TranslationContext")

    def _next_lifted_name(self, source_construct: str) -> str:
        self._lift_counter += 1
        base = sanitize_identifier(source_construct, fallback_prefix="lifted")
        return f"{base}__lifted_{self._lift_counter}"

    def translate(
        self,
        *,
        source_construct: str,
        term: Term,
        target: TranslationTarget,
        monomorphization: Optional[Dict[str, SortRef]] = None,
    ) -> TranslationRecord:
        """Translate ``term`` (identified by ``source_construct``) to
        ``target``, returning a :class:`TranslationRecord`.

        Every call — successful or not — appends its record to
        :attr:`records`; a successful (``SUPPORTED``/``PARTIAL``) call also
        appends every declared sort/symbol/lifted-function name to
        :attr:`translation_map`.
        """

        _require_nonempty_str(
            source_construct, field_name="source_construct", owner="TranslationContext.translate"
        )
        if not isinstance(target, TranslationTarget):
            raise ValueError("TranslationContext.translate target must be a TranslationTarget")

        translation_id = f"{self.request_id}:{source_construct}:{target.value}:{len(self.records)}"

        try:
            record = self._translate_inner(
                translation_id=translation_id,
                source_construct=source_construct,
                term=term,
                target=target,
                monomorphization=monomorphization or {},
            )
        except UnsupportedConstructError as exc:
            record = TranslationRecord(
                translation_id=translation_id,
                request_id=self.request_id,
                target=target,
                status=TranslationStatus.UNSUPPORTED,
                source_construct=source_construct,
                translated_text=None,
                obligations=[],
                unsupported_reason=exc.reason,
            )
        except MalformedTermError as exc:
            record = TranslationRecord(
                translation_id=translation_id,
                request_id=self.request_id,
                target=target,
                status=TranslationStatus.UNSUPPORTED,
                source_construct=source_construct,
                translated_text=None,
                obligations=[],
                unsupported_reason=f"malformed term: {exc}",
            )

        record.validate()
        self.records.append(record)
        return record

    def _translate_inner(
        self,
        *,
        translation_id: str,
        source_construct: str,
        term: Term,
        target: TranslationTarget,
        monomorphization: Dict[str, SortRef],
    ) -> TranslationRecord:
        # Stage 0: well-formedness (raises MalformedTermError on failure).
        infer_type(term)

        # Stage 1: dependent types fail closed unconditionally.
        issue = find_dependent_type_issue(term)
        if issue:
            raise UnsupportedConstructError(issue)

        # Stage 2: opaque constructs fail closed unconditionally.
        issue = find_opaque_issue(term)
        if issue:
            raise UnsupportedConstructError(issue)

        # Stage 3: explicit monomorphization.
        obligations: List[str] = []
        applied_vars = sorted(
            {
                t.name
                for type_ref in walk_term_types(term)
                for t in _walk_type_tree(type_ref)
                if isinstance(t, TypeVarRef) and t.name in monomorphization
            }
        )
        monomorphized = substitute_type_vars_in_term(term, monomorphization)
        for var_name in applied_vars:
            sort = monomorphization[var_name]
            obligations.append(
                f"monomorphized type variable '{var_name}' -> '{sort.name}' in '{source_construct}'"
            )

        issue = find_type_var_issue(monomorphized)
        if issue:
            raise UnsupportedConstructError(issue)

        # Stage 4 + 5: beta-elimination and top-level lambda lifting.
        lifted_name = self._next_lifted_name(source_construct)
        normalized = normalize_construct(
            monomorphized, source_construct=source_construct, lifted_name=lifted_name
        )
        obligations.extend(normalized.obligations)

        # Stage 6: any remaining higher-order construct fails closed.
        issue = find_structural_issue(normalized.term)
        if issue:
            raise UnsupportedConstructError(issue)

        top_type = infer_type(normalized.term)
        if top_type != PROP_SORT:
            raise UnsupportedConstructError(
                f"'{source_construct}' does not denote a proposition after normalization "
                f"(top-level type is {top_type!r})"
            )

        # Stage 7: render.
        text, name_map = self._render(normalized.term, target=target)
        monomorphized_sort_names = {sort.name for sort in monomorphization.values()}
        for source_name, (target_name, kind) in name_map.items():
            origin = "original"
            if any(ld.name == source_name for ld in normalized.lifted_definitions):
                origin = "lambda-lifted"
            elif kind == "sort" and source_name in monomorphized_sort_names:
                origin = "monomorphized"
            self.translation_map.add(
                source_name=source_name,
                target_name=target_name,
                target=target,
                kind=kind,
                origin=origin,
            )

        status = TranslationStatus.PARTIAL if obligations else TranslationStatus.SUPPORTED
        content_digest = compute_content_digest({"target": target.value, "text": text})

        return TranslationRecord(
            translation_id=translation_id,
            request_id=self.request_id,
            target=target,
            status=status,
            source_construct=source_construct,
            translated_text=text,
            obligations=obligations,
            unsupported_reason=None,
            content_digest=content_digest,
        )

    @staticmethod
    def _render(
        term: Term, *, target: TranslationTarget
    ) -> Tuple[str, Dict[str, Tuple[str, str]]]:
        if target is TranslationTarget.TPTP:
            from . import tptp as tptp_module

            result = tptp_module.render_tff(term)
        elif target is TranslationTarget.SMTLIB:
            from . import smtlib as smtlib_module

            result = smtlib_module.render_smtlib(term)
        else:  # pragma: no cover - defensive, TranslationTarget is exhaustive
            raise UnsupportedConstructError(f"unknown translation target {target!r}")
        return result.text, dict(result.name_map)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": self.request_id,
            "translation_map": self.translation_map.to_dict(),
            "records": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranslationContext":
        data = dict(data)
        _require_schema_version(
            data.get("schema_version", SCHEMA_VERSION), owner="TranslationContext"
        )
        ctx = cls(request_id=data["request_id"])
        ctx.translation_map = TranslationMap.from_dict(data.get("translation_map", {}))
        ctx.records = [
            TranslationRecord.from_dict(r) for r in data.get("records", [])
        ]
        return ctx

    def save(self, path: str) -> None:
        import json

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)

    @classmethod
    def load(cls, path: str) -> "TranslationContext":
        import json

        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

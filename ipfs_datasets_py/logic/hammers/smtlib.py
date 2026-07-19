"""SMT-LIB2 rendering and parsing for the ITP hammer translation pipeline
(HAMMER-007).

This module renders the fully lowered, first-order
:class:`~ipfs_datasets_py.logic.hammers.translation.Term` produced by
:mod:`.translation` into SMT-LIB2 syntax (sort/function declarations plus an
``assert``), and parses that same emitted subset back into a
:class:`~ipfs_datasets_py.logic.hammers.translation.Term` so the round-trip
property ``render(parse(render(t))) == render(t)`` can be verified in tests.

Emitted grammar (standard SMT-LIB2 core + quantifiers)::

    (declare-sort <sort> 0)
    (declare-fun <name> (<arg1> <arg2> ...) <result>)
    (assert <FORMULA>)

    FORMULA := <atom>
             | "true" | "false"
             | (not FORMULA) | (and FORMULA FORMULA) | (or FORMULA FORMULA)
             | (=> FORMULA FORMULA) | (= TERM TERM)
             | (forall ((VAR SORT)) FORMULA) | (exists ((VAR SORT)) FORMULA)
    TERM := VAR | <name> | (<name> TERM ...)

Only :class:`~ipfs_datasets_py.logic.hammers.translation.SortRef` domain
sorts and the reserved boolean sort (``Bool``) are supported; any other type
reaching this module is a pipeline bug (the HAMMER-007 pipeline in
:mod:`.translation` must have already rejected it) and raises
:class:`SMTLIBRenderError`/:class:`SMTLIBParseError` rather than emitting
malformed or silently-wrong SMT-LIB text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple, Union

from .translation import (
    PROP_SORT,
    And,
    App,
    BoolLit,
    Const,
    Eq,
    Exists,
    Forall,
    FunctionTypeRef,
    Iff,
    Implies,
    MalformedTermError,
    Not,
    Or,
    SortRef,
    Term,
    TranslationError,
    Var,
    sanitize_identifier,
)

__all__ = [
    "SMTLIBError",
    "SMTLIBRenderError",
    "SMTLIBParseError",
    "SMTLIBRenderResult",
    "render_smtlib",
    "parse_smtlib",
]


class SMTLIBError(TranslationError):
    """Base class for all SMT-LIB rendering/parsing errors."""


class SMTLIBRenderError(SMTLIBError):
    """Raised when a term cannot be rendered into the supported SMT-LIB
    fragment (this indicates a pipeline bug — :mod:`.translation` should
    already have rejected any such term as ``unsupported``)."""


class SMTLIBParseError(SMTLIBError):
    """Raised when SMT-LIB text does not match the subset this module
    emits."""


# ---------------------------------------------------------------------------
# Name registry
# ---------------------------------------------------------------------------


class _NameRegistry:
    """Deterministic, collision-free SMT-LIB identifier assignment, with a
    separate namespace per symbol kind (sort/function/variable)."""

    def __init__(self) -> None:
        self._namespaces: Dict[str, Dict[str, str]] = {"sort": {}, "function": {}, "variable": {}}
        self._taken: Dict[str, set] = {"sort": set(), "function": set(), "variable": set()}

    def name(self, source_name: str, *, kind: str) -> str:
        used = self._namespaces[kind]
        if source_name in used:
            return used[source_name]
        base = sanitize_identifier(source_name, fallback_prefix=kind)
        taken = self._taken[kind]
        candidate = base
        n = 0
        while candidate in taken:
            n += 1
            candidate = f"{base}_{n}"
        used[source_name] = candidate
        taken.add(candidate)
        return candidate


# ---------------------------------------------------------------------------
# Collection (deterministic first-occurrence order)
# ---------------------------------------------------------------------------


def _collect(term: Term) -> Tuple[List[SortRef], List[Const], List[str]]:
    sorts: List[SortRef] = []
    consts: List[Const] = []
    var_names: List[str] = []

    def add_sort(s: SortRef) -> None:
        if s != PROP_SORT and s not in sorts:
            sorts.append(s)

    def visit_type(t) -> None:
        if isinstance(t, SortRef):
            add_sort(t)
        elif isinstance(t, FunctionTypeRef):
            for p in t.params:
                visit_type(p)
            visit_type(t.result)
        else:
            raise SMTLIBRenderError(f"unsupported type reached SMT-LIB renderer: {t!r}")

    def visit(node: Term) -> None:
        if isinstance(node, Var):
            visit_type(node.type)
            if node.name not in var_names:
                var_names.append(node.name)
        elif isinstance(node, Const):
            visit_type(node.type)
            if not any(c.name == node.name for c in consts):
                consts.append(node)
        elif isinstance(node, App):
            visit(node.fn)
            for a in node.args:
                visit(a)
        elif isinstance(node, (Forall, Exists)):
            visit_type(node.var_type)
            if node.var not in var_names:
                var_names.append(node.var)
            visit(node.body)
        elif isinstance(node, Not):
            visit(node.term)
        elif isinstance(node, (And, Or, Implies, Iff, Eq)):
            visit(node.left)
            visit(node.right)
        elif isinstance(node, BoolLit):
            pass
        else:
            raise SMTLIBRenderError(f"unsupported construct reached SMT-LIB renderer: {node!r}")

    visit(term)
    return sorts, consts, var_names


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _type_token(t, registry: _NameRegistry) -> str:
    if t == PROP_SORT:
        return "Bool"
    if isinstance(t, SortRef):
        return registry.name(t.name, kind="sort")
    raise SMTLIBRenderError(f"unsupported type in SMT-LIB signature position: {t!r}")


def _render_term(node: Term, registry: _NameRegistry) -> str:
    if isinstance(node, Var):
        return registry.name(node.name, kind="variable")
    if isinstance(node, Const):
        return registry.name(node.name, kind="function")
    if isinstance(node, App):
        name = _render_term(node.fn, registry)
        if not node.args:
            return name
        args = " ".join(_render_term(a, registry) for a in node.args)
        return f"({name} {args})"
    if isinstance(node, BoolLit):
        return "true" if node.value else "false"
    raise SMTLIBRenderError(f"cannot render {node!r} as an SMT-LIB term")


def _render_formula(node: Term, registry: _NameRegistry) -> str:
    if isinstance(node, BoolLit):
        return "true" if node.value else "false"
    if isinstance(node, Not):
        return f"(not {_render_formula(node.term, registry)})"
    if isinstance(node, And):
        return f"(and {_render_formula(node.left, registry)} {_render_formula(node.right, registry)})"
    if isinstance(node, Or):
        return f"(or {_render_formula(node.left, registry)} {_render_formula(node.right, registry)})"
    if isinstance(node, Implies):
        return f"(=> {_render_formula(node.left, registry)} {_render_formula(node.right, registry)})"
    if isinstance(node, Iff):
        return f"(= {_render_formula(node.left, registry)} {_render_formula(node.right, registry)})"
    if isinstance(node, Eq):
        return f"(= {_render_term(node.left, registry)} {_render_term(node.right, registry)})"
    if isinstance(node, (Forall, Exists)):
        keyword = "forall" if isinstance(node, Forall) else "exists"
        var = registry.name(node.var, kind="variable")
        sort = _type_token(node.var_type, registry)
        body = _render_formula(node.body, registry)
        return f"({keyword} (({var} {sort})) {body})"
    return _render_term(node, registry)


@dataclass
class SMTLIBRenderResult:
    """The output of :func:`render_smtlib`.

    Attributes:
        text: The full SMT-LIB2 text (sort/function declarations followed by
            one ``assert`` command).
        name_map: Mapping of source-level name -> ``(smtlib_name, kind)`` for
            every declared sort (``kind="sort"``), function/predicate symbol
            (``kind="function"``), and variable (``kind="variable"``).
    """

    text: str
    name_map: Dict[str, Tuple[str, str]]


def render_smtlib(term: Term) -> SMTLIBRenderResult:
    """Render ``term`` (already lowered by :mod:`.translation`) as SMT-LIB2
    text.

    Raises:
        SMTLIBRenderError: If ``term`` still contains a construct outside
            the supported first-order fragment (a pipeline bug —
            :mod:`.translation` is expected to have already rejected such
            terms as ``unsupported``).
    """

    try:
        sorts, consts, var_names = _collect(term)
    except MalformedTermError as exc:  # pragma: no cover - defensive
        raise SMTLIBRenderError(str(exc)) from exc

    registry = _NameRegistry()
    lines: List[str] = []
    name_map: Dict[str, Tuple[str, str]] = {}

    for sort in sorts:
        smt_name = registry.name(sort.name, kind="sort")
        lines.append(f"(declare-sort {smt_name} 0)")
        name_map[sort.name] = (smt_name, "sort")

    for const in consts:
        smt_name = registry.name(const.name, kind="function")
        if isinstance(const.type, FunctionTypeRef):
            arg_part = " ".join(_type_token(p, registry) for p in const.type.params)
            result = _type_token(const.type.result, registry)
        else:
            arg_part = ""
            result = _type_token(const.type, registry)
        lines.append(f"(declare-fun {smt_name} ({arg_part}) {result})")
        name_map[const.name] = (smt_name, "function")

    for name in var_names:
        smt_name = registry.name(name, kind="variable")
        name_map.setdefault(name, (smt_name, "variable"))

    formula = _render_formula(term, registry)
    lines.append(f"(assert {formula})")

    return SMTLIBRenderResult(text="\n".join(lines), name_map=name_map)


# ---------------------------------------------------------------------------
# Parsing (round-trip only — the subset this module itself emits)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\(|\)|[^\s()]+")

SExpr = Union[str, List["SExpr"]]


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text)


def _read_sexpr(tokens: List[str], i: int) -> Tuple[SExpr, int]:
    if i >= len(tokens):
        raise SMTLIBParseError("unexpected end of SMT-LIB input")
    if tokens[i] == "(":
        items: List[SExpr] = []
        j = i + 1
        while j < len(tokens) and tokens[j] != ")":
            item, j = _read_sexpr(tokens, j)
            items.append(item)
        if j >= len(tokens):
            raise SMTLIBParseError("unbalanced parentheses in SMT-LIB input")
        return items, j + 1
    if tokens[i] == ")":
        raise SMTLIBParseError("unexpected ')' in SMT-LIB input")
    return tokens[i], i + 1


def _read_top_level(text: str) -> List[SExpr]:
    tokens = _tokenize(text)
    forms: List[SExpr] = []
    i = 0
    while i < len(tokens):
        form, i = _read_sexpr(tokens, i)
        forms.append(form)
    return forms


class _Parser:
    def __init__(self) -> None:
        self.sorts: Dict[str, SortRef] = {}
        self.consts: Dict[str, Const] = {}
        self.var_types: Dict[str, object] = {}

    def resolve_sort_token(self, token: str):
        if token == "Bool":
            return PROP_SORT
        if token in self.sorts:
            return self.sorts[token]
        sort = SortRef(token)
        self.sorts[token] = sort
        return sort

    def declare_sort(self, form: List[SExpr]) -> None:
        # (declare-sort <name> 0)
        name = form[1]
        if not isinstance(name, str):
            raise SMTLIBParseError(f"malformed declare-sort: {form!r}")
        self.sorts[name] = SortRef(name)

    def declare_fun(self, form: List[SExpr]) -> None:
        # (declare-fun <name> (<arg>...) <result>)
        name = form[1]
        arg_forms = form[2]
        result_tok = form[3]
        if not isinstance(name, str) or not isinstance(arg_forms, list) or not isinstance(
            result_tok, str
        ):
            raise SMTLIBParseError(f"malformed declare-fun: {form!r}")
        params = [self.resolve_sort_token(a) for a in arg_forms if isinstance(a, str)]
        result = self.resolve_sort_token(result_tok)
        if params:
            self.consts[name] = Const(name, FunctionTypeRef(tuple(params), result))
        else:
            self.consts[name] = Const(name, result)

    def parse_formula(self, node: SExpr) -> Term:
        if isinstance(node, str):
            return self._resolve_atom(node)
        if not node:
            raise SMTLIBParseError("empty SMT-LIB s-expression")
        head = node[0]
        if head == "not":
            return Not(self.parse_formula(node[1]))
        if head == "and":
            return And(self.parse_formula(node[1]), self.parse_formula(node[2]))
        if head == "or":
            return Or(self.parse_formula(node[1]), self.parse_formula(node[2]))
        if head == "=>":
            return Implies(self.parse_formula(node[1]), self.parse_formula(node[2]))
        if head == "=":
            return Eq(self.parse_formula(node[1]), self.parse_formula(node[2]))
        if head in ("forall", "exists"):
            binder_list = node[1]
            if not isinstance(binder_list, list) or len(binder_list) != 1:
                raise SMTLIBParseError(f"only single-variable binders are supported: {node!r}")
            var_name, sort_tok = binder_list[0]
            var_type = self.resolve_sort_token(sort_tok)
            self.var_types[var_name] = var_type
            body = self.parse_formula(node[2])
            cls = Forall if head == "forall" else Exists
            return cls(var=var_name, var_type=var_type, body=body)
        # Application: (<name> arg...)
        if not isinstance(head, str):
            raise SMTLIBParseError(f"malformed SMT-LIB application head: {head!r}")
        fn = self._resolve_const(head)
        args = tuple(self.parse_formula(a) for a in node[1:])
        return App(fn=fn, args=args)

    def _resolve_atom(self, token: str) -> Term:
        if token == "true":
            return BoolLit(True)
        if token == "false":
            return BoolLit(False)
        if token in self.var_types:
            return Var(token, self.var_types[token])
        if token in self.consts:
            return self.consts[token]
        raise SMTLIBParseError(f"undeclared SMT-LIB identifier {token!r}")

    def _resolve_const(self, name: str) -> Const:
        if name not in self.consts:
            raise SMTLIBParseError(f"undeclared SMT-LIB symbol {name!r}")
        return self.consts[name]


def parse_smtlib(text: str) -> Term:
    """Parse SMT-LIB2 ``text`` produced by :func:`render_smtlib` back into a
    :class:`~ipfs_datasets_py.logic.hammers.translation.Term`.

    Only the exact subset emitted by :func:`render_smtlib` is supported; this
    function exists to support round-trip testing, not as a general SMT-LIB
    parser.
    """

    parser = _Parser()
    assert_form = None
    for form in _read_top_level(text):
        if not isinstance(form, list) or not form:
            raise SMTLIBParseError(f"malformed SMT-LIB top-level form: {form!r}")
        head = form[0]
        if head == "declare-sort":
            parser.declare_sort(form)
        elif head == "declare-fun":
            parser.declare_fun(form)
        elif head == "assert":
            assert_form = form[1]
        else:
            raise SMTLIBParseError(f"unsupported SMT-LIB command {head!r}")

    if assert_form is None:
        raise SMTLIBParseError("no 'assert' command found in SMT-LIB text")
    return parser.parse_formula(assert_form)

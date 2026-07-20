"""TPTP (TFF — Typed First-order Form) rendering and parsing for the ITP
hammer translation pipeline (HAMMER-007).

This module renders the fully lowered, first-order
:class:`~ipfs_datasets_py.logic.hammers.translation.Term` produced by
:mod:`.translation` into TPTP's typed first-order syntax (many-sorted
declarations plus a formula), and parses that same emitted subset back into
a :class:`~ipfs_datasets_py.logic.hammers.translation.Term` so the round-trip
property ``render(parse(render(t))) == render(t)`` can be verified in tests.

Emitted grammar
-----------------
Every clause is fully parenthesized so parsing never needs operator
precedence rules::

    tff(sort_<n>, type, <sort>: $tType).
    tff(sym_<n>, type, <name>: <arg1> > <result>).
    tff(sym_<n>, type, <name>: (<arg1> * <arg2> * ...) > <result>).
    tff(sym_<n>, type, <name>: <result>).            % nullary constant
    tff(goal, conjecture, <FORMULA>).

    FORMULA := <atom>
             | "$true" | "$false"
             | "(" "~" FORMULA ")"
             | "(" FORMULA ("&"|"|"|"=>"|"<=>") FORMULA ")"
             | "(" TERM "=" TERM ")"
             | "(" ("!"|"?") "[" VAR ":" SORT "]" ":" FORMULA ")"
    TERM := VAR | <name> | <name> "(" TERM ("," TERM)* ")"

Only :class:`~ipfs_datasets_py.logic.hammers.translation.SortRef` domain
sorts and the reserved boolean sort (``$o``) are supported; any other type
(``FunctionTypeRef`` outside a declaration signature, ``TypeVarRef``,
``DependentTypeRef``) reaching this module is a pipeline bug (the HAMMER-007
pipeline in :mod:`.translation` must have already rejected it) and raises
:class:`TPTPRenderError`/:class:`TPTPParseError` rather than emitting
malformed or silently-wrong TPTP text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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
    "TPTPError",
    "TPTPRenderError",
    "TPTPParseError",
    "TPTPRenderResult",
    "render_tff",
    "parse_tff",
]


class TPTPError(TranslationError):
    """Base class for all TPTP rendering/parsing errors."""


class TPTPRenderError(TPTPError):
    """Raised when a term cannot be rendered into the supported TPTP TFF
    fragment (this indicates a pipeline bug — :mod:`.translation` should
    already have rejected any such term as ``unsupported``)."""


class TPTPParseError(TPTPError):
    """Raised when TPTP text does not match the subset this module emits."""


# ---------------------------------------------------------------------------
# Name registry
# ---------------------------------------------------------------------------


class _NameRegistry:
    """Deterministic, collision-free TPTP identifier assignment.

    TPTP requires function/predicate/sort identifiers to start with a
    lowercase letter and variables to start with an uppercase letter; this
    registry assigns each distinct source name a fresh, valid, deduplicated
    target name the first time it is seen and reuses it thereafter.
    """

    def __init__(self) -> None:
        self._lower_used: Dict[str, str] = {}
        self._lower_taken: set = set()
        self._upper_used: Dict[str, str] = {}
        self._upper_taken: set = set()

    def lower(self, source_name: str) -> str:
        if source_name in self._lower_used:
            return self._lower_used[source_name]
        base = sanitize_identifier(source_name, fallback_prefix="sym").lower()
        if not base[0].isalpha():
            base = f"s_{base}"
        candidate = base
        n = 0
        while candidate in self._lower_taken:
            n += 1
            candidate = f"{base}_{n}"
        self._lower_used[source_name] = candidate
        self._lower_taken.add(candidate)
        return candidate

    def upper(self, source_name: str) -> str:
        if source_name in self._upper_used:
            return self._upper_used[source_name]
        base = sanitize_identifier(source_name, fallback_prefix="V").upper()
        if not base[0].isalpha():
            base = f"V_{base}"
        candidate = base
        n = 0
        while candidate in self._upper_taken:
            n += 1
            candidate = f"{base}_{n}"
        self._upper_used[source_name] = candidate
        self._upper_taken.add(candidate)
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
            raise TPTPRenderError(f"unsupported type reached TPTP renderer: {t!r}")

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
            raise TPTPRenderError(f"unsupported construct reached TPTP renderer: {node!r}")

    visit(term)
    return sorts, consts, var_names


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _type_token(t, registry: _NameRegistry) -> str:
    if t == PROP_SORT:
        return "$o"
    if isinstance(t, SortRef):
        return registry.lower(t.name)
    raise TPTPRenderError(f"unsupported type in TPTP signature position: {t!r}")


def _signature_token(func_type: FunctionTypeRef, registry: _NameRegistry) -> str:
    result = _type_token(func_type.result, registry)
    if not func_type.params:
        return result
    if len(func_type.params) == 1:
        arg_part = _type_token(func_type.params[0], registry)
    else:
        arg_part = "(" + " * ".join(_type_token(p, registry) for p in func_type.params) + ")"
    return f"{arg_part} > {result}"


def _render_term(node: Term, registry: _NameRegistry) -> str:
    if isinstance(node, Var):
        return registry.upper(node.name)
    if isinstance(node, Const):
        return registry.lower(node.name)
    if isinstance(node, App):  # App
        name = _render_term(node.fn, registry)
        if not node.args:
            return name
        args = ", ".join(_render_term(a, registry) for a in node.args)
        return f"{name}({args})"
    if isinstance(node, BoolLit):
        return "$true" if node.value else "$false"
    raise TPTPRenderError(f"cannot render {node!r} as a TPTP term")


def _render_formula(node: Term, registry: _NameRegistry) -> str:
    if isinstance(node, BoolLit):
        return "$true" if node.value else "$false"
    if isinstance(node, Not):
        return f"(~ {_render_formula(node.term, registry)})"
    if isinstance(node, And):
        return f"({_render_formula(node.left, registry)} & {_render_formula(node.right, registry)})"
    if isinstance(node, Or):
        return f"({_render_formula(node.left, registry)} | {_render_formula(node.right, registry)})"
    if isinstance(node, Implies):
        return f"({_render_formula(node.left, registry)} => {_render_formula(node.right, registry)})"
    if isinstance(node, Iff):
        return f"({_render_formula(node.left, registry)} <=> {_render_formula(node.right, registry)})"
    if isinstance(node, Eq):
        return f"({_render_term(node.left, registry)} = {_render_term(node.right, registry)})"
    if isinstance(node, (Forall, Exists)):
        quant = "!" if isinstance(node, Forall) else "?"
        var = registry.upper(node.var)
        sort = _type_token(node.var_type, registry)
        body = _render_formula(node.body, registry)
        return f"({quant} [{var}: {sort}] : {body})"
    # Atomic formula: an application/const/var used directly as a proposition.
    return _render_term(node, registry)


@dataclass
class TPTPRenderResult:
    """The output of :func:`render_tff`.

    Attributes:
        text: The full TPTP TFF text (type declarations followed by one
            ``conjecture`` clause).
        name_map: Mapping of source-level name -> ``(tptp_name, kind)`` for
            every declared sort (``kind="sort"``), function/predicate
            symbol (``kind="function"``), and variable (``kind="variable"``).
    """

    text: str
    name_map: Dict[str, Tuple[str, str]]


def render_tff(term: Term) -> TPTPRenderResult:
    """Render ``term`` (already lowered by :mod:`.translation`) as TPTP TFF
    text.

    Raises:
        TPTPRenderError: If ``term`` still contains a construct outside the
            supported first-order, many-sorted fragment (a pipeline bug —
            :mod:`.translation` is expected to have already rejected such
            terms as ``unsupported``).
    """

    try:
        sorts, consts, var_names = _collect(term)
    except MalformedTermError as exc:  # pragma: no cover - defensive
        raise TPTPRenderError(str(exc)) from exc

    registry = _NameRegistry()
    lines: List[str] = []
    name_map: Dict[str, Tuple[str, str]] = {}

    for i, sort in enumerate(sorts):
        tptp_name = registry.lower(sort.name)
        lines.append(f"tff(sort_{i}, type, {tptp_name}: $tType).")
        name_map[sort.name] = (tptp_name, "sort")

    for i, const in enumerate(consts):
        tptp_name = registry.lower(const.name)
        if isinstance(const.type, FunctionTypeRef):
            signature = _signature_token(const.type, registry)
        else:
            signature = _type_token(const.type, registry)
        lines.append(f"tff(sym_{i}, type, {tptp_name}: {signature}).")
        name_map[const.name] = (tptp_name, "function")

    for name in var_names:
        tptp_name = registry.upper(name)
        name_map.setdefault(name, (tptp_name, "variable"))

    formula = _render_formula(term, registry)
    lines.append(f"tff(goal, conjecture, {formula}).")

    return TPTPRenderResult(text="\n".join(lines), name_map=name_map)


# ---------------------------------------------------------------------------
# Parsing (round-trip only — the subset this module itself emits)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    <=>|=>|\$true|\$false|\$tType|\$o
    |[A-Za-z_][A-Za-z0-9_]*
    |[()\[\]:.,*=~&|!?>]
    """,
    re.VERBOSE,
)


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text)


def _split_clauses(text: str) -> List[str]:
    """Split ``text`` into individual ``tff( ... ).`` clause bodies (the
    content strictly inside the outer parentheses of each clause)."""

    clauses: List[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        if text[i : i + 4] != "tff(":
            raise TPTPParseError(f"expected 'tff(' at position {i}, got {text[i:i+20]!r}")
        depth = 0
        j = i + 3
        start_inner = i + 4
        while j < n:
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            raise TPTPParseError("unbalanced parentheses in TPTP clause")
        clauses.append(text[start_inner:j])
        k = j + 1
        while k < n and text[k].isspace():
            k += 1
        if k >= n or text[k] != ".":
            raise TPTPParseError("expected '.' terminating TPTP clause")
        i = k + 1
    return clauses


def _split_top_level(tokens: List[str], sep: str = ",") -> List[List[str]]:
    parts: List[List[str]] = []
    current: List[str] = []
    depth = 0
    for tok in tokens:
        if tok in ("(", "["):
            depth += 1
        elif tok in (")", "]"):
            depth -= 1
        if tok == sep and depth == 0:
            parts.append(current)
            current = []
        else:
            current.append(tok)
    parts.append(current)
    return parts


class _Parser:
    def __init__(self) -> None:
        self.sorts: Dict[str, SortRef] = {}
        self.consts: Dict[str, Const] = {}
        self.var_types: Dict[str, object] = {}

    def parse_type_decl(self, symbol: str, type_tokens: List[str]) -> None:
        if type_tokens == ["$tType"]:
            self.sorts[symbol] = SortRef(symbol)
            return
        params, result_tokens = self._split_signature(type_tokens)
        param_types = [self._resolve_sort_token(p) for p in params]
        result_type = self._resolve_sort_token(result_tokens)
        if param_types:
            self.consts[symbol] = Const(symbol, FunctionTypeRef(tuple(param_types), result_type))
        else:
            self.consts[symbol] = Const(symbol, result_type)

    def _resolve_sort_token(self, token: str):
        if token == "$o":
            return PROP_SORT
        if token in self.sorts:
            return self.sorts[token]
        # Referenced before its declaring clause was parsed — declare on demand.
        sort = SortRef(token)
        self.sorts[token] = sort
        return sort

    @staticmethod
    def _split_signature(tokens: List[str]) -> Tuple[List[str], str]:
        if ">" not in tokens:
            if len(tokens) != 1:
                raise TPTPParseError(f"malformed TPTP signature: {tokens!r}")
            return [], tokens[0]
        idx = tokens.index(">")
        arg_tokens = tokens[:idx]
        result_tokens = tokens[idx + 1 :]
        if len(result_tokens) != 1:
            raise TPTPParseError(f"malformed TPTP signature result: {tokens!r}")
        if arg_tokens and arg_tokens[0] == "(" and arg_tokens[-1] == ")":
            arg_tokens = arg_tokens[1:-1]
            params = [p[0] for p in _split_top_level(arg_tokens, sep="*")]
        else:
            if len(arg_tokens) != 1:
                raise TPTPParseError(f"malformed TPTP signature args: {tokens!r}")
            params = arg_tokens
        return params, result_tokens[0]

    def parse_formula(self, tokens: List[str], i: int) -> Tuple[Term, int]:
        tok = tokens[i]
        if tok == "$true":
            return BoolLit(True), i + 1
        if tok == "$false":
            return BoolLit(False), i + 1
        if tok == "(":
            nxt = tokens[i + 1]
            if nxt == "~":
                inner, j = self.parse_formula(tokens, i + 2)
                self._expect(tokens, j, ")")
                return Not(inner), j + 1
            if nxt in ("!", "?"):
                self._expect(tokens, i + 2, "[")
                var_name = tokens[i + 3]
                self._expect(tokens, i + 4, ":")
                sort_tok = tokens[i + 5]
                self._expect(tokens, i + 6, "]")
                self._expect(tokens, i + 7, ":")
                var_type = self._resolve_sort_token(sort_tok)
                self.var_types[var_name] = var_type
                body, j = self.parse_formula(tokens, i + 8)
                self._expect(tokens, j, ")")
                cls = Forall if nxt == "!" else Exists
                return cls(var=var_name, var_type=var_type, body=body), j + 1
            left, j = self.parse_expr(tokens, i + 1)
            op = tokens[j]
            right, k = self.parse_expr(tokens, j + 1)
            self._expect(tokens, k, ")")
            if op == "=":
                return Eq(left, right), k + 1
            if op == "&":
                return And(left, right), k + 1
            if op == "|":
                return Or(left, right), k + 1
            if op == "=>":
                return Implies(left, right), k + 1
            if op == "<=>":
                return Iff(left, right), k + 1
            raise TPTPParseError(f"unknown TPTP connective {op!r}")
        return self.parse_expr(tokens, i)

    def parse_expr(self, tokens: List[str], i: int) -> Tuple[Term, int]:
        """Parse a TERM (variable, nullary constant, or n-ary application)."""

        if tokens[i] == "(":
            return self.parse_formula(tokens, i)
        name = tokens[i]
        if name in ("$true", "$false"):
            return self.parse_formula(tokens, i)
        if i + 1 < len(tokens) and tokens[i + 1] == "(":
            args: List[Term] = []
            j = i + 2
            if tokens[j] != ")":
                while True:
                    arg, j = self.parse_expr(tokens, j)
                    args.append(arg)
                    if tokens[j] == ",":
                        j += 1
                        continue
                    break
            self._expect(tokens, j, ")")
            fn = self._resolve_const(name)
            return App(fn=fn, args=tuple(args)), j + 1
        return self._resolve_atom(name), i + 1

    def _resolve_const(self, name: str) -> Const:
        if name not in self.consts:
            raise TPTPParseError(f"undeclared TPTP symbol {name!r}")
        return self.consts[name]

    def _resolve_atom(self, name: str) -> Term:
        if name in self.var_types:
            return Var(name, self.var_types[name])
        if name in self.consts:
            return self.consts[name]
        raise TPTPParseError(f"undeclared TPTP identifier {name!r}")

    @staticmethod
    def _expect(tokens: List[str], i: int, expected: str) -> None:
        if i >= len(tokens) or tokens[i] != expected:
            got = tokens[i] if i < len(tokens) else "<eof>"
            raise TPTPParseError(f"expected {expected!r}, got {got!r} at token {i}")


def parse_tff(text: str) -> Term:
    """Parse TPTP TFF ``text`` produced by :func:`render_tff` back into a
    :class:`~ipfs_datasets_py.logic.hammers.translation.Term`.

    Only the exact subset emitted by :func:`render_tff` is supported; this
    function exists to support round-trip testing, not as a general TPTP
    parser.
    """

    parser = _Parser()
    formula_tokens: Optional[List[str]] = None
    for clause in _split_clauses(text):
        tokens = _tokenize(clause)
        parts = _split_top_level(tokens)
        if len(parts) != 3:
            raise TPTPParseError(f"expected 3 comma-separated fields in clause: {clause!r}")
        _name, role, rest = parts
        role_str = "".join(role)
        if role_str == "type":
            colon_idx = rest.index(":")
            symbol = rest[0]
            type_tokens = rest[colon_idx + 1 :]
            parser.parse_type_decl(symbol, type_tokens)
        elif role_str in ("axiom", "conjecture"):
            formula_tokens = rest
        else:
            raise TPTPParseError(f"unsupported TPTP clause role {role_str!r}")

    if formula_tokens is None:
        raise TPTPParseError("no axiom/conjecture clause found in TPTP text")
    term, end = parser.parse_formula(formula_tokens, 0)
    if end != len(formula_tokens):
        raise TPTPParseError("trailing tokens after TPTP formula")
    return term

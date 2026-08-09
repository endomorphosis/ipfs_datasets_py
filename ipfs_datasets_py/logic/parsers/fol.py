"""Canonical many-sorted first-order logic parser and printer.

Interface: ``CanonicalFOLSyntax@1`` (LFP-017).

Human-readable notation for admitted FOL fragments with:

* explicit binder sorts and quantifier/let scope
* right-associative implication (``A -> B -> C`` ≡ ``A -> (B -> C)``)
* fail-closed undeclared symbol/sort diagnostics with exact source spans
* fail-closed trailing-input rejection with exact source spans
* deterministic print that is alpha-equivalent under parse/print/parse

Grammar (connective precedence, low → high binding strength)::

    formula        ::= quant_formula
    quant_formula  ::= ('forall'|'exists'|∀|∃) binders '.' formula
                     | 'let' binder '=' term 'in' formula
                     | iff_formula
    iff_formula    ::= implies_formula (('iff'|↔|<=>|<->) implies_formula)*
    implies_formula::= or_formula (('implies'|→|⇒|=>|->) formula)?   # right-assoc
    or_formula     ::= and_formula (('or'|∨|'|') and_formula)*
    and_formula    ::= not_formula (('and'|∧|'&') not_formula)*
    not_formula    ::= ('not'|¬|'~'|'!') not_formula | atomic
    atomic         ::= 'true'|⊤ | 'false'|⊥
                     | term '=' term
                     | atom_app
                     | '(' formula ')'
    binders        ::= binder | '(' binder (',' binder)+ ')'
    binder         ::= IDENT ':' sort
    sort           ::= IDENT | IDENT '(' sort (',' sort)* ')'
    term           ::= IDENT '(' term (',' term)* ')' | IDENT | '(' term ')'
    atom_app       ::= IDENT '(' term_list? ')' | IDENT   # nullary predicate

Quantifiers bind a full formula body after ``.`` (maximal scope).  A quantifier
embedded under a connective therefore requires parentheses, making binder
scope explicit in surface syntax.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import (
    AstError,
    Binder,
    LogicNode,
    NodeKind,
    TypedExpression,
    elaborate,
    mk_application,
    mk_constant,
    mk_exists,
    mk_forall,
    mk_let,
    mk_variable,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    LogicToken,
    ParseArtifact,
    ParseLimits,
    ParseMode,
    ParseRequest,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind,
)
from ipfs_datasets_py.logic.syntax_core.diagnostics import DiagnosticSink
from ipfs_datasets_py.logic.syntax_core.lexer import BoundedLexer
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    LogicSort,
    SignatureError,
    SortKind,
    SymbolKind,
    parametric_sort,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

CANONICAL_FOL_SYNTAX_INTERFACE: Final = "CanonicalFOLSyntax@1"
CANONICAL_FOL_NOTATION_ID: Final = "canonical_fol"
CANONICAL_FOL_NOTATION_VERSION: Final = "1.0.0"
CANONICAL_FOL_PROFILE_ID: Final = "classical"
CANONICAL_FOL_FAMILY_ID: Final = "first_order"
FOL_MODULE_VERSION: Final = "1.0.0"
FOL_PARSE_RESULT_SCHEMA_VERSION: Final = "canonical-fol-parse-result/v1"

# Stable namespaced diagnostic codes.
CODE_UNDECLARED_SYMBOL: Final = "fol.undeclared_symbol"
CODE_UNDECLARED_SORT: Final = "fol.undeclared_sort"
CODE_TRAILING_INPUT: Final = "fol.trailing_input"
CODE_UNEXPECTED_TOKEN: Final = "fol.unexpected_token"
CODE_ARITY_MISMATCH: Final = "fol.arity_mismatch"
CODE_KIND_MISMATCH: Final = "fol.kind_mismatch"
CODE_PARSE_DEPTH: Final = "fol.parse_depth_exceeded"
CODE_EMPTY_INPUT: Final = "fol.empty_input"
CODE_MISSING_SIGNATURE: Final = "fol.missing_signature"
CODE_UNBALANCED: Final = "fol.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "fol.lexer_error"
CODE_TYPECHECK_FAILED: Final = "fol.typecheck_failed"

_ALL_FOL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNDECLARED_SYMBOL,
        CODE_UNDECLARED_SORT,
        CODE_TRAILING_INPUT,
        CODE_UNEXPECTED_TOKEN,
        CODE_ARITY_MISMATCH,
        CODE_KIND_MISMATCH,
        CODE_PARSE_DEPTH,
        CODE_EMPTY_INPUT,
        CODE_MISSING_SIGNATURE,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_TYPECHECK_FAILED,
    }
)

# Operator lexeme sets (ASCII + Unicode admitted by BoundedLexer).
_NOT_OPS: Final[frozenset[str]] = frozenset({"not", "¬", "~", "!"})
_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&"})
_OR_OPS: Final[frozenset[str]] = frozenset({"or", "∨", "|", "||"})
_IMPLIES_OPS: Final[frozenset[str]] = frozenset(
    {"implies", "→", "⇒", "=>", "->", "==>"}
)
_IFF_OPS: Final[frozenset[str]] = frozenset({"iff", "↔", "⇔", "<=>", "<->"})
_FORALL_OPS: Final[frozenset[str]] = frozenset({"forall", "∀"})
_EXISTS_OPS: Final[frozenset[str]] = frozenset({"exists", "∃"})
_TRUE_OPS: Final[frozenset[str]] = frozenset({"true", "⊤"})
_FALSE_OPS: Final[frozenset[str]] = frozenset({"false", "⊥"})
_EQ_OPS: Final[frozenset[str]] = frozenset({"="})

_FOL_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "implies",
    "iff",
    "forall",
    "exists",
    "true",
    "false",
    "let",
    "in",
)


class PrintStyle(str):
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    QUANT = 5
    IFF = 10
    IMPLIES = 20
    OR = 30
    AND = 40
    NOT = 50
    ATOM = 60
    TERM = 70


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FOLParseResult:
    """Typed result of a canonical FOL parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    schema_version: str = FOL_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = CANONICAL_FOL_SYNTAX_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)


class FOLParseError(SyntaxContractError):
    """Raised by raising helpers when a FOL parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: FOLParseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)
        self.result = result


# ---------------------------------------------------------------------------
# Token cursor
# ---------------------------------------------------------------------------


class _ParseFail(Exception):
    """Internal control-flow exception for recoverable parse failures."""

    def __init__(self, diagnostic: SyntaxDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


class _TokenCursor:
    """Cursor over non-trivia lexer tokens (EOF inclusive)."""

    def __init__(self, tokens: Sequence[LogicToken], document: SourceDocument) -> None:
        self.tokens = tuple(tokens)
        self.document = document
        self.index = 0
        self.depth = 0

    def current(self) -> LogicToken:
        if self.index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.index]

    def peek(self, offset: int = 0) -> LogicToken:
        pos = self.index + offset
        if pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[pos]

    def is_eof(self) -> bool:
        return self.current().kind == TokenKind.EOF.value

    def advance(self) -> LogicToken:
        token = self.current()
        if not self.is_eof():
            self.index += 1
        return token

    def match_lexeme(self, *lexemes: str) -> LogicToken | None:
        token = self.current()
        if token.kind == TokenKind.EOF.value:
            return None
        folded = token.lexeme.casefold() if token.kind == TokenKind.KEYWORD.value else token.lexeme
        targets = {
            item.casefold() if item.isascii() and item.isalpha() else item for item in lexemes
        }
        # Keywords compare case-insensitively; operators/symbols exactly.
        if token.kind == TokenKind.KEYWORD.value:
            if folded in {t.casefold() for t in targets}:
                return self.advance()
            return None
        if token.lexeme in targets or folded in {t.casefold() for t in targets}:
            return self.advance()
        return None

    def match_any(self, lexemes: frozenset[str]) -> LogicToken | None:
        token = self.current()
        if token.kind == TokenKind.EOF.value:
            return None
        if token.kind == TokenKind.KEYWORD.value:
            if token.lexeme.casefold() in {item.casefold() for item in lexemes}:
                return self.advance()
            return None
        if token.lexeme in lexemes:
            return self.advance()
        # Also accept case-insensitive keyword-like members of the set.
        if token.lexeme.casefold() in {item.casefold() for item in lexemes if item.isalpha()}:
            return self.advance()
        return None

    def expect_lexeme(self, *lexemes: str, code: str = CODE_UNEXPECTED_TOKEN) -> LogicToken:
        token = self.match_lexeme(*lexemes)
        if token is not None:
            return token
        current = self.current()
        expected = " or ".join(repr(item) for item in lexemes)
        raise _ParseFail(
            _diag(
                code=code,
                message=f"expected {expected}; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def expect_ident(self) -> LogicToken:
        token = self.current()
        if token.kind == TokenKind.IDENTIFIER.value:
            return self.advance()
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected identifier; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def range_span(self, start: SourceRange, end: SourceRange) -> SourceRange:
        # Only attach character offsets when both endpoints supply a complete pair.
        if (
            start.start_char is not None
            and start.end_char is not None
            and end.start_char is not None
            and end.end_char is not None
        ):
            return SourceRange(
                start=start.start,
                end=end.end,
                start_char=start.start_char,
                end_char=end.end_char,
            )
        return SourceRange(start=start.start, end=end.end)

    def eof_range(self) -> SourceRange:
        eof = self.tokens[-1]
        return eof.range


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    remediation: str = "",
    diagnostic_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    diag_id = diagnostic_id or f"diag:fol:{code.replace('.', '-')}"
    return SyntaxDiagnostic(
        diagnostic_id=diag_id,
        code=code,
        message=message,
        severity=severity,
        range=range,
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------


class _FOLParserEngine:
    """Signature-bound recursive-descent parser for canonical FOL."""

    def __init__(
        self,
        *,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        signature: LogicSignature,
        limits: ParseLimits,
        expression_id: str = "expr:fol:1",
    ) -> None:
        self.document = document
        self.signature = signature
        self.limits = limits
        self.expression_id = expression_id
        self.cursor = _TokenCursor(tokens, document)
        self.sink = DiagnosticSink(max_diagnostics=limits.max_diagnostics)
        self._node_seq = 0
        self._locals: list[dict[str, LogicSort]] = [{}]
        self.root: LogicNode | None = None
        self.surface: list[SurfaceASTRef] = []

    # -- public ------------------------------------------------------------

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if self.cursor.is_eof():
            self._emit(
                CODE_EMPTY_INPUT,
                "empty input; expected a formula",
                self.cursor.eof_range(),
            )
            return None, self.sink.items

        try:
            node = self._parse_formula()
            if not self.cursor.is_eof():
                trailing = self.cursor.current()
                self._emit(
                    CODE_TRAILING_INPUT,
                    f"trailing input starting at {trailing.lexeme!r}",
                    trailing.range,
                    remediation="Remove trailing tokens or terminate the formula",
                )
                return None, self.sink.items
            # Elaborate for sort/arity consistency under the signature.
            try:
                elaborated = elaborate(node, self.signature)
            except (AstError, SignatureError) as error:
                self._emit(
                    CODE_TYPECHECK_FAILED,
                    str(error),
                    node.range,
                )
                return None, self.sink.items
            self.root = elaborated
            return elaborated, self.sink.items
        except _ParseFail as failure:
            diag_id = f"diag:fol:fail:{len(self.sink.items) + 1}"
            self.sink.add(
                SyntaxDiagnostic(
                    diagnostic_id=diag_id,
                    code=failure.diagnostic.code,
                    message=failure.diagnostic.message,
                    severity=failure.diagnostic.severity,
                    range=failure.diagnostic.range,
                    remediation=failure.diagnostic.remediation,
                    metadata=dict(failure.diagnostic.metadata),
                )
            )
            return None, self.sink.items

    # -- helpers -----------------------------------------------------------

    def _emit(
        self,
        code: str,
        message: str,
        range: SourceRange | None,
        *,
        remediation: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.sink.emit(
            code=code,
            message=message,
            severity=DiagnosticSeverity.ERROR,
            range=range,
            remediation=remediation,
            metadata=metadata,
            diagnostic_id=f"diag:fol:{code.replace('.', '-')}:{len(self.sink.items) + 1}",
        )

    def _nid(self, prefix: str = "n") -> str:
        self._node_seq += 1
        return f"{prefix}:{self._node_seq}"

    def _enter(self) -> None:
        self.cursor.depth += 1
        if self.cursor.depth > self.limits.max_depth:
            raise _ParseFail(
                _diag(
                    code=CODE_PARSE_DEPTH,
                    message=(
                        f"parse depth {self.cursor.depth} exceeds limit "
                        f"{self.limits.max_depth}"
                    ),
                    range=self.cursor.current().range,
                )
            )

    def _leave(self) -> None:
        self.cursor.depth = max(0, self.cursor.depth - 1)

    def _push_scope(self, binders: Sequence[Binder]) -> None:
        frame = dict(self._locals[-1])
        for binder in binders:
            frame[binder.name] = binder.sort
        self._locals.append(frame)

    def _pop_scope(self) -> None:
        if len(self._locals) > 1:
            self._locals.pop()

    def _lookup_local(self, name: str) -> LogicSort | None:
        return self._locals[-1].get(name)

    # -- formula -----------------------------------------------------------

    def _parse_formula(self) -> LogicNode:
        self._enter()
        try:
            return self._parse_quant_formula()
        finally:
            self._leave()

    def _parse_quant_formula(self) -> LogicNode:
        token = self.cursor.match_any(_FORALL_OPS)
        if token is not None:
            return self._parse_quantifier(NodeKind.FORALL, token)
        token = self.cursor.match_any(_EXISTS_OPS)
        if token is not None:
            return self._parse_quantifier(NodeKind.EXISTS, token)
        if self.cursor.match_lexeme("let") is not None:
            return self._parse_let()
        return self._parse_iff()

    def _parse_quantifier(self, kind: NodeKind, start_token: LogicToken) -> LogicNode:
        binders = self._parse_binders()
        self.cursor.expect_lexeme(".", code=CODE_UNEXPECTED_TOKEN)
        self._push_scope(binders)
        try:
            body = self._parse_formula()
        finally:
            self._pop_scope()
        span = self.cursor.range_span(start_token.range, body.range or start_token.range)
        node_id = self._nid("q")
        if kind is NodeKind.FORALL:
            node = mk_forall(node_id, binders, body)
        else:
            node = mk_exists(node_id, binders, body)
        return LogicNode(
            node_id=node.node_id,
            kind=node.kind,
            sort=BOOL_SORT,
            binders=node.binders,
            arguments=node.arguments,
            range=span,
        )

    def _parse_let(self) -> LogicNode:
        # 'let' already consumed; binder starts the let construct for spanning.
        binder = self._parse_binder()
        self.cursor.expect_lexeme("=")
        value = self._parse_term()
        self.cursor.expect_lexeme("in")
        self._push_scope((binder,))
        try:
            body = self._parse_formula()
        finally:
            self._pop_scope()
        start_range = value.range or body.range or SourceRange(0, 0)
        end_range = body.range or value.range or start_range
        span = self.cursor.range_span(start_range, end_range)
        node = mk_let(self._nid("let"), binder, value, body)
        return LogicNode(
            node_id=node.node_id,
            kind=node.kind,
            sort=BOOL_SORT if body.is_formula else body.sort,
            binders=node.binders,
            arguments=node.arguments,
            range=span,
        )

    def _parse_binders(self) -> tuple[Binder, ...]:
        if self.cursor.match_lexeme("(") is not None:
            binders = [self._parse_binder()]
            while self.cursor.match_lexeme(",") is not None:
                binders.append(self._parse_binder())
            self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            return tuple(binders)
        return (self._parse_binder(),)

    def _parse_binder(self) -> Binder:
        name_tok = self.cursor.expect_ident()
        self.cursor.expect_lexeme(":")
        sort = self._parse_sort()
        if sort.is_bool:
            raise _ParseFail(
                _diag(
                    code=CODE_KIND_MISMATCH,
                    message=(
                        f"binder {name_tok.lexeme!r} must not bind Bool; "
                        "use propositional structure instead"
                    ),
                    range=name_tok.range,
                )
            )
        return Binder(name=name_tok.lexeme, sort=sort)

    def _parse_sort(self) -> LogicSort:
        name_tok = self.cursor.expect_ident()
        name = name_tok.lexeme
        if self.cursor.match_lexeme("(") is not None:
            args = [self._parse_sort()]
            while self.cursor.match_lexeme(",") is not None:
                args.append(self._parse_sort())
            self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            # Parametric sort: head name must be declared as a sort with matching shape,
            # or we accept structural parametric construction when base name is known.
            if not self.signature.has_sort(name):
                # Allow parametric heads that are not pre-declared as atomic when args given;
                # still require each argument sort to be declared.
                for arg in args:
                    if not self.signature.has_sort(arg.name) and arg.kind is not SortKind.PARAMETRIC:
                        raise _ParseFail(
                            _diag(
                                code=CODE_UNDECLARED_SORT,
                                message=f"undeclared sort {arg.name!r}",
                                range=name_tok.range,
                            )
                        )
                return parametric_sort(name, *args)
            declared = self.signature.get_sort(name)
            if declared.kind is SortKind.PARAMETRIC and declared.arguments:
                if len(declared.arguments) != len(args):
                    raise _ParseFail(
                        _diag(
                            code=CODE_ARITY_MISMATCH,
                            message=(
                                f"sort {name!r} expects {len(declared.arguments)} "
                                f"argument(s); got {len(args)}"
                            ),
                            range=name_tok.range,
                        )
                    )
            return parametric_sort(name, *args)

        if not self.signature.has_sort(name):
            raise _ParseFail(
                _diag(
                    code=CODE_UNDECLARED_SORT,
                    message=f"undeclared sort {name!r}",
                    range=name_tok.range,
                )
            )
        return self.signature.get_sort(name)

    def _parse_iff(self) -> LogicNode:
        left = self._parse_implies()
        nodes = [left]
        while self.cursor.match_any(_IFF_OPS) is not None:
            nodes.append(self._parse_implies())
        if len(nodes) == 1:
            return nodes[0]
        # Left-associative chain of binary iff.
        result = nodes[0]
        for right in nodes[1:]:
            span = self.cursor.range_span(
                result.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            result = LogicNode(
                node_id=self._nid("iff"),
                kind=NodeKind.IFF,
                sort=BOOL_SORT,
                arguments=(result, right),
                range=span,
            )
        return result

    def _parse_implies(self) -> LogicNode:
        left = self._parse_or()
        if self.cursor.match_any(_IMPLIES_OPS) is not None:
            # Right-associative: consequent is a full formula.
            right = self._parse_formula()
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            return LogicNode(
                node_id=self._nid("imp"),
                kind=NodeKind.IMPLIES,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
            )
        return left

    def _parse_or(self) -> LogicNode:
        nodes = [self._parse_and()]
        while self.cursor.match_any(_OR_OPS) is not None:
            nodes.append(self._parse_and())
        if len(nodes) == 1:
            return nodes[0]
        span = self.cursor.range_span(
            nodes[0].range or SourceRange(0, 0),
            nodes[-1].range or SourceRange(0, 0),
        )
        return LogicNode(
            node_id=self._nid("or"),
            kind=NodeKind.OR,
            sort=BOOL_SORT,
            arguments=tuple(nodes),
            range=span,
        )

    def _parse_and(self) -> LogicNode:
        nodes = [self._parse_not()]
        while self.cursor.match_any(_AND_OPS) is not None:
            nodes.append(self._parse_not())
        if len(nodes) == 1:
            return nodes[0]
        span = self.cursor.range_span(
            nodes[0].range or SourceRange(0, 0),
            nodes[-1].range or SourceRange(0, 0),
        )
        return LogicNode(
            node_id=self._nid("and"),
            kind=NodeKind.AND,
            sort=BOOL_SORT,
            arguments=tuple(nodes),
            range=span,
        )

    def _parse_not(self) -> LogicNode:
        token = self.cursor.match_any(_NOT_OPS)
        if token is not None:
            self._enter()
            try:
                inner = self._parse_not()
            finally:
                self._leave()
            span = self.cursor.range_span(token.range, inner.range or token.range)
            return LogicNode(
                node_id=self._nid("not"),
                kind=NodeKind.NOT,
                sort=BOOL_SORT,
                arguments=(inner,),
                range=span,
            )
        return self._parse_atomic()

    def _parse_atomic(self) -> LogicNode:
        # Parenthesized formula.
        open_tok = self.cursor.match_lexeme("(")
        if open_tok is not None:
            inner = self._parse_formula()
            close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(open_tok.range, close.range)
            return LogicNode(
                node_id=inner.node_id,
                kind=inner.kind,
                sort=inner.sort,
                symbol=inner.symbol,
                arguments=inner.arguments,
                binders=inner.binders,
                extension=inner.extension,
                range=span,
                metadata=dict(inner.metadata),
            )

        # true / false
        token = self.cursor.match_any(_TRUE_OPS)
        if token is not None:
            return LogicNode(
                node_id=self._nid("true"),
                kind=NodeKind.TRUE,
                sort=BOOL_SORT,
                range=token.range,
            )
        token = self.cursor.match_any(_FALSE_OPS)
        if token is not None:
            return LogicNode(
                node_id=self._nid("false"),
                kind=NodeKind.FALSE,
                sort=BOOL_SORT,
                range=token.range,
            )

        # Equality: term '=' term
        # Predicate: IDENT | IDENT '(' terms ')'
        # Distinguish by parsing a term, then checking for '='.
        if self.cursor.current().kind == TokenKind.IDENTIFIER.value:
            save = self.cursor.index
            # Prefer predicate parse when the head is a declared predicate and
            # the next token is not part of a larger term used only as equality lhs.
            name_tok = self.cursor.current()
            name = name_tok.lexeme
            # Lookahead for predicate application or nullary predicate.
            if self.signature.has_symbol(name):
                decl = self.signature.get_symbol(name)
                if decl.kind is SymbolKind.PREDICATE:
                    # Could still be equality if somehow... predicates aren't terms.
                    # Parse as predicate.
                    self.cursor.advance()
                    args: tuple[LogicNode, ...] = ()
                    end_range = name_tok.range
                    if self.cursor.match_lexeme("(") is not None:
                        arg_list: list[LogicNode] = []
                        if self.cursor.current().lexeme != ")":
                            arg_list.append(self._parse_term())
                            while self.cursor.match_lexeme(",") is not None:
                                arg_list.append(self._parse_term())
                        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                        args = tuple(arg_list)
                        end_range = close.range
                    elif decl.arity != 0:
                        raise _ParseFail(
                            _diag(
                                code=CODE_ARITY_MISMATCH,
                                message=(
                                    f"predicate {name!r} has arity {decl.arity}; "
                                    "expected arguments in parentheses"
                                ),
                                range=name_tok.range,
                            )
                        )
                    if decl.arity != len(args):
                        raise _ParseFail(
                            _diag(
                                code=CODE_ARITY_MISMATCH,
                                message=(
                                    f"predicate {name!r} has arity {decl.arity}; "
                                    f"got {len(args)}"
                                ),
                                range=name_tok.range,
                            )
                        )
                    span = self.cursor.range_span(name_tok.range, end_range)
                    return LogicNode(
                        node_id=self._nid("pred"),
                        kind=NodeKind.PREDICATE,
                        symbol=name,
                        sort=BOOL_SORT,
                        arguments=args,
                        range=span,
                    )

            # Not a predicate head: parse term, then optional equality.
            try:
                left = self._parse_term()
            except _ParseFail:
                self.cursor.index = save
                raise
            eq = self.cursor.match_any(_EQ_OPS)
            if eq is not None:
                right = self._parse_term()
                span = self.cursor.range_span(
                    left.range or eq.range,
                    right.range or eq.range,
                )
                return LogicNode(
                    node_id=self._nid("eq"),
                    kind=NodeKind.EQUALITY,
                    sort=BOOL_SORT,
                    arguments=(left, right),
                    range=span,
                )
            raise _ParseFail(
                _diag(
                    code=CODE_KIND_MISMATCH,
                    message=(
                        f"term {left.symbol or left.kind!r} is not a formula; "
                        "use a predicate or equality"
                    ),
                    range=left.range,
                )
            )

        current = self.cursor.current()
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected formula; got {current.lexeme!r}",
                range=current.range,
            )
        )

    # -- terms -------------------------------------------------------------

    def _parse_term(self) -> LogicNode:
        self._enter()
        try:
            open_tok = self.cursor.match_lexeme("(")
            if open_tok is not None:
                inner = self._parse_term()
                close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                span = self.cursor.range_span(open_tok.range, close.range)
                return LogicNode(
                    node_id=inner.node_id,
                    kind=inner.kind,
                    sort=inner.sort,
                    symbol=inner.symbol,
                    arguments=inner.arguments,
                    range=span,
                    metadata=dict(inner.metadata),
                )

            name_tok = self.cursor.expect_ident()
            name = name_tok.lexeme

            if self.cursor.match_lexeme("(") is not None:
                args: list[LogicNode] = []
                if self.cursor.current().lexeme != ")":
                    args.append(self._parse_term())
                    while self.cursor.match_lexeme(",") is not None:
                        args.append(self._parse_term())
                close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                span = self.cursor.range_span(name_tok.range, close.range)
                return self._make_function_application(name, tuple(args), span)

            return self._make_atom_term(name, name_tok.range)
        finally:
            self._leave()

    def _make_atom_term(self, name: str, span: SourceRange) -> LogicNode:
        local = self._lookup_local(name)
        if local is not None:
            return mk_variable(self._nid("v"), name, local, range=span)

        if not self.signature.has_symbol(name):
            raise _ParseFail(
                _diag(
                    code=CODE_UNDECLARED_SYMBOL,
                    message=f"undeclared symbol {name!r}",
                    range=span,
                )
            )
        decl = self.signature.get_symbol(name)
        if decl.kind is SymbolKind.CONSTANT:
            return mk_constant(self._nid("c"), name, decl.result_sort, range=span)
        if decl.kind is SymbolKind.FUNCTION:
            if decl.arity != 0:
                raise _ParseFail(
                    _diag(
                        code=CODE_ARITY_MISMATCH,
                        message=(
                            f"function {name!r} has arity {decl.arity}; "
                            "expected arguments in parentheses"
                        ),
                        range=span,
                    )
                )
            # Nullary functions are represented as constants in the core AST.
            return mk_constant(self._nid("c"), name, decl.result_sort, range=span)
        if decl.kind is SymbolKind.PREDICATE:
            raise _ParseFail(
                _diag(
                    code=CODE_KIND_MISMATCH,
                    message=f"predicate {name!r} is not a term",
                    range=span,
                )
            )
        raise _ParseFail(
            _diag(
                code=CODE_KIND_MISMATCH,
                message=f"symbol {name!r} is not a term",
                range=span,
            )
        )

    def _make_function_application(
        self,
        name: str,
        args: tuple[LogicNode, ...],
        span: SourceRange,
    ) -> LogicNode:
        if not self.signature.has_symbol(name):
            raise _ParseFail(
                _diag(
                    code=CODE_UNDECLARED_SYMBOL,
                    message=f"undeclared symbol {name!r}",
                    range=span,
                )
            )
        decl = self.signature.get_symbol(name)
        if decl.kind is not SymbolKind.FUNCTION:
            raise _ParseFail(
                _diag(
                    code=CODE_KIND_MISMATCH,
                    message=(
                        f"symbol {name!r} has kind {decl.kind.value!r}; "
                        "expected function in term position"
                    ),
                    range=span,
                )
            )
        if decl.arity != len(args):
            raise _ParseFail(
                _diag(
                    code=CODE_ARITY_MISMATCH,
                    message=(
                        f"function {name!r} has arity {decl.arity}; "
                        f"got {len(args)}"
                    ),
                    range=span,
                )
            )
        if not args:
            return mk_constant(self._nid("c"), name, decl.result_sort, range=span)
        return mk_application(
            self._nid("f"),
            name,
            args,
            sort=decl.result_sort,
            range=span,
        )


# ---------------------------------------------------------------------------
# CST builder
# ---------------------------------------------------------------------------


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:fol:1",
) -> LogicCST:
    """Build a lossless CST covering the full source from tokens + gaps."""

    children = tuple(
        LogicCSTNode(
            node_id=f"node:{token.token_id}",
            kind=token.kind,
            range=token.range,
            role=CSTNodeRole.TOKEN,
            token_id=token.token_id,
        )
        for token in tokens
        if token.kind != TokenKind.EOF.value
    )
    covered = [token.range for token in tokens if token.kind != TokenKind.EOF.value]
    holes: list[LogicCSTNode] = []
    cursor = 0
    for item in sorted(covered, key=lambda value: value.start):
        if item.start > cursor:
            holes.append(
                LogicCSTNode(
                    node_id=f"node:gap:{cursor}:{item.start}",
                    kind="gap",
                    range=SourceRange(start=cursor, end=item.start),
                    role=CSTNodeRole.GAP,
                )
            )
        cursor = max(cursor, item.end)
    if cursor < document.byte_length:
        holes.append(
            LogicCSTNode(
                node_id=f"node:gap:{cursor}:{document.byte_length}",
                kind="gap",
                range=SourceRange(start=cursor, end=document.byte_length),
                role=CSTNodeRole.GAP,
            )
        )
    leaves = tuple(sorted((*children, *holes), key=lambda node: node.range.start))
    if not leaves and document.byte_length == 0:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=(),
        )
    else:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=leaves,
        )
    return LogicCST(
        cst_id=cst_id,
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


def _surface_from_node(node: LogicNode, *, counter: list[int] | None = None) -> list[SurfaceASTRef]:
    """Flatten a LogicNode tree into SurfaceASTRef entries."""

    seq = counter if counter is not None else [0]

    def walk(n: LogicNode) -> str:
        seq[0] += 1
        node_id = n.node_id if n.node_id else f"ast:{seq[0]}"
        child_ids: list[str] = []
        for child in n.arguments:
            child_ids.append(walk(child))
        kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
        # SurfaceASTRef.kind must match token-kind pattern (lowercase with dots/underscores).
        safe_kind = kind.replace(" ", "_")
        span = n.range or SourceRange(0, 0)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind=safe_kind,
                range=span,
                child_ids=tuple(child_ids),
                metadata={"symbol": n.symbol} if n.symbol else {},
            )
        )
        return node_id

    refs: list[SurfaceASTRef] = []
    walk(node)
    return refs


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class CanonicalFOLPrinter:
    """Deterministic printer for core FOL nodes.

    Parenthesization makes implication associativity and binder scope
    explicit so that parse(print(parse(s))) is alpha-equivalent to parse(s).
    """

    def __init__(self, *, style: str = PrintStyle.ASCII) -> None:
        if style not in {PrintStyle.ASCII, PrintStyle.UNICODE}:
            raise SyntaxContractError(
                f"print style must be 'ascii' or 'unicode'; got {style!r}"
            )
        self.style = style

    def print(self, node: LogicNode | TypedExpression) -> str:
        if isinstance(node, TypedExpression):
            return self._print_node(node.root, _Prec.BOTTOM)
        if not isinstance(node, LogicNode):
            raise SyntaxContractError("print requires a LogicNode or TypedExpression")
        return self._print_node(node, _Prec.BOTTOM)

    def _op(self, ascii_form: str, unicode_form: str) -> str:
        return unicode_form if self.style == PrintStyle.UNICODE else ascii_form

    def _print_node(self, node: LogicNode, parent_prec: int) -> str:
        kind = node.kind
        if kind is NodeKind.TRUE or kind == NodeKind.TRUE.value:
            return self._op("true", "⊤")
        if kind is NodeKind.FALSE or kind == NodeKind.FALSE.value:
            return self._op("false", "⊥")
        if kind is NodeKind.NOT or kind == NodeKind.NOT.value:
            inner = self._print_node(node.arguments[0], _Prec.NOT)
            text = f"{self._op('not', '¬')} {inner}"
            return self._paren(text, _Prec.NOT, parent_prec)
        if kind is NodeKind.AND or kind == NodeKind.AND.value:
            op = f" {self._op('and', '∧')} "
            text = op.join(self._print_node(a, _Prec.AND) for a in node.arguments)
            return self._paren(text, _Prec.AND, parent_prec)
        if kind is NodeKind.OR or kind == NodeKind.OR.value:
            op = f" {self._op('or', '∨')} "
            text = op.join(self._print_node(a, _Prec.OR) for a in node.arguments)
            return self._paren(text, _Prec.OR, parent_prec)
        if kind is NodeKind.IMPLIES or kind == NodeKind.IMPLIES.value:
            # Right-associative: left child needs stricter parens.
            left = self._print_node(node.arguments[0], _Prec.IMPLIES + 1)
            right = self._print_node(node.arguments[1], _Prec.IMPLIES)
            text = f"{left} {self._op('->', '→')} {right}"
            return self._paren(text, _Prec.IMPLIES, parent_prec)
        if kind is NodeKind.IFF or kind == NodeKind.IFF.value:
            left = self._print_node(node.arguments[0], _Prec.IFF + 1)
            right = self._print_node(node.arguments[1], _Prec.IFF + 1)
            text = f"{left} {self._op('iff', '↔')} {right}"
            return self._paren(text, _Prec.IFF, parent_prec)
        if kind is NodeKind.FORALL or kind == NodeKind.FORALL.value:
            return self._print_quantifier("forall", "∀", node, parent_prec)
        if kind is NodeKind.EXISTS or kind == NodeKind.EXISTS.value:
            return self._print_quantifier("exists", "∃", node, parent_prec)
        if kind is NodeKind.LET or kind == NodeKind.LET.value:
            binder = node.binders[0]
            value = self._print_node(node.arguments[0], _Prec.BOTTOM)
            body = self._print_node(node.arguments[1], _Prec.BOTTOM)
            text = f"let {binder.name}:{binder.sort} = {value} in {body}"
            return self._paren(text, _Prec.QUANT, parent_prec)
        if kind is NodeKind.EQUALITY or kind == NodeKind.EQUALITY.value:
            left = self._print_node(node.arguments[0], _Prec.TERM)
            right = self._print_node(node.arguments[1], _Prec.TERM)
            text = f"{left} = {right}"
            return self._paren(text, _Prec.ATOM, parent_prec)
        if kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
            return self._print_app(node.symbol, node.arguments)
        if kind is NodeKind.APPLICATION or kind == NodeKind.APPLICATION.value:
            return self._print_app(node.symbol, node.arguments)
        if kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
            return node.symbol
        if kind is NodeKind.VARIABLE or kind == NodeKind.VARIABLE.value:
            return node.symbol
        raise SyntaxContractError(f"unsupported node kind for printing: {kind!r}")

    def _print_quantifier(
        self,
        ascii_kw: str,
        unicode_kw: str,
        node: LogicNode,
        parent_prec: int,
    ) -> str:
        kw = self._op(ascii_kw, unicode_kw)
        binders = self._print_binders(node.binders)
        # Body at BOTTOM so nested connectives do not require extra parens inside.
        body = self._print_node(node.arguments[0], _Prec.BOTTOM)
        text = f"{kw} {binders}. {body}"
        # Quantifiers need parens when embedded under connectives.
        return self._paren(text, _Prec.QUANT, parent_prec)

    def _print_binders(self, binders: Sequence[Binder]) -> str:
        parts = [f"{b.name}:{b.sort}" for b in binders]
        if len(parts) == 1:
            return parts[0]
        return "(" + ", ".join(parts) + ")"

    def _print_app(self, symbol: str, arguments: Sequence[LogicNode]) -> str:
        if not arguments:
            return symbol
        args = ", ".join(self._print_node(a, _Prec.BOTTOM) for a in arguments)
        return f"{symbol}({args})"

    def _paren(self, text: str, prec: int, parent_prec: int) -> str:
        if prec < parent_prec:
            return f"({text})"
        return text


# ---------------------------------------------------------------------------
# Public parser surface
# ---------------------------------------------------------------------------


def _extract_signature(value: object) -> LogicSignature | None:
    if value is None:
        return None
    if isinstance(value, LogicSignature):
        return value
    if isinstance(value, Mapping):
        return LogicSignature.from_dict(value)
    return None


class CanonicalFOLParser:
    """Notation parser for canonical many-sorted FOL.

    Interface: ``CanonicalFOLSyntax@1`` (callable :class:`LogicParser` surface).

    The signature is required and may be supplied via the constructor or
    ``ParseRequest.metadata['signature']``.
    """

    interface: ClassVar[str] = CANONICAL_FOL_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = CANONICAL_FOL_NOTATION_ID
    notation_version: ClassVar[str] = CANONICAL_FOL_NOTATION_VERSION
    profile_id: ClassVar[str] = CANONICAL_FOL_PROFILE_ID

    def __init__(
        self,
        signature: LogicSignature | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if signature is not None and not isinstance(signature, LogicSignature):
            raise SyntaxContractError("signature must be a LogicSignature")
        self.signature = signature
        self.printer = CanonicalFOLPrinter(style=print_style)
        self._lexer = BoundedLexer(keywords=_FOL_KEYWORDS)

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        signature = _extract_signature(request.metadata.get("signature")) or self.signature
        result = self.parse_document(
            request.document,
            signature=signature,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(request.metadata.get("expression_id") or "expr:fol:1"),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        signature: LogicSignature | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:fol:1",
        expression_id: str = "expr:fol:1",
    ) -> FOLParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        if isinstance(mode, ParseMode):
            parse_mode = mode
        else:
            parse_mode = ParseMode(str(mode))

        sig = signature or self.signature
        if sig is None:
            diag = _diag(
                code=CODE_MISSING_SIGNATURE,
                message="canonical FOL parse requires a LogicSignature",
                range=document.full_range(),
                remediation="Pass signature=... or metadata['signature']",
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": CANONICAL_FOL_SYNTAX_INTERFACE},
            )
            return FOLParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )

        lex_result = self._lexer.lex(document, mode=parse_mode, limits=bounds)
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            # Promote lexer failures.
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:fol:lex:{index + 1}",
                    code=CODE_LEXER_ERROR
                    if item.code.startswith("lexer.")
                    else item.code,
                    message=item.message,
                    severity=item.severity,
                    range=item.range,
                    remediation=item.remediation,
                    metadata={"lexer_code": item.code},
                )
                for index, item in enumerate(lex_result.diagnostics)
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=promoted,
                metadata={"interface": CANONICAL_FOL_SYNTAX_INTERFACE},
            )
            return FOLParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
            )

        engine = _FOLParserEngine(
            document=document,
            tokens=lex_result.tokens,
            signature=sig,
            limits=bounds,
            expression_id=expression_id,
        )
        root, diagnostics = engine.parse()
        all_diags = tuple(lex_result.diagnostics) + tuple(diagnostics)

        if root is None or any(item.is_error for item in all_diags):
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={"interface": CANONICAL_FOL_SYNTAX_INTERFACE},
            )
            return FOLParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
            )

        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=sig,
            range=root.range,
            elaborate_on_init=False,
        )
        cst = _build_covering_cst(document, lex_result.tokens)
        surface = tuple(_surface_from_node(root))
        printed = self.printer.print(root)
        artifact = ParseArtifact(
            artifact_id=f"art:{request_id}",
            request_id=request_id,
            document_id=document.document_id,
            status=ParseStatus.OK,
            tokens=lex_result.tokens,
            cst=cst,
            surface_ast=surface,
            diagnostics=all_diags,
            metadata={
                "interface": CANONICAL_FOL_SYNTAX_INTERFACE,
                "expression": expression.to_dict(),
                "printed": printed,
                "notation_id": CANONICAL_FOL_NOTATION_ID,
                "notation_version": CANONICAL_FOL_NOTATION_VERSION,
            },
        )
        artifact.validate_against(document, limits=bounds)
        return FOLParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
        )


class CanonicalFOLSyntax:
    """Facade for canonical many-sorted FOL parse/print round-trips.

    Interface: ``CanonicalFOLSyntax@1``.
    """

    interface: ClassVar[str] = CANONICAL_FOL_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = CANONICAL_FOL_NOTATION_ID
    notation_version: ClassVar[str] = CANONICAL_FOL_NOTATION_VERSION
    profile_id: ClassVar[str] = CANONICAL_FOL_PROFILE_ID
    family_id: ClassVar[str] = CANONICAL_FOL_FAMILY_ID

    def __init__(
        self,
        signature: LogicSignature,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if not isinstance(signature, LogicSignature):
            raise SyntaxContractError("signature must be a LogicSignature")
        self.signature = signature
        self.parser = CanonicalFOLParser(signature, print_style=print_style)
        self.printer = self.parser.printer

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:fol:1",
        expression_id: str = "expr:fol:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> FOLParseResult:
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        return self.parser.parse_document(
            document,
            signature=self.signature,
            mode=mode,
            limits=limits,
            expression_id=expression_id,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise FOLParseError(
                result.errors[0].message if result.errors else "FOL parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def round_trip(self, text: str, **kwargs: Any) -> FOLParseResult:
        """Parse, print, and re-parse; success requires alpha-equivalence."""

        first = self.parse_text(text, **kwargs)
        if not first.ok or first.root is None:
            return first
        printed = self.print(first.root)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:fol:1") + ":rt",
            expression_id=str(kwargs.get("expression_id") or "expr:fol:1") + ":rt",
            limits=kwargs.get("limits"),
            mode=kwargs.get("mode", ParseMode.STRICT),
        )
        if not second.ok or second.root is None or first.root is None:
            return second
        if not alpha_equivalent(first.root, second.root):
            diag = _diag(
                code=CODE_TYPECHECK_FAILED,
                message="parse/print/parse is not alpha-equivalent",
                range=second.root.range,
            )
            return FOLParseResult(
                status=ParseStatus.FAILED,
                root=second.root,
                expression=second.expression,
                diagnostics=second.diagnostics + (diag,),
                tokens=second.tokens,
                artifact=second.artifact,
                printed=printed,
            )
        return FOLParseResult(
            status=ParseStatus.OK,
            root=second.root,
            expression=second.expression,
            diagnostics=second.diagnostics,
            tokens=second.tokens,
            artifact=second.artifact,
            printed=printed,
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_fol(
    text: str,
    signature: LogicSignature,
    *,
    document_id: str = "doc:fol:1",
    expression_id: str = "expr:fol:1",
    limits: ParseLimits | None = None,
    print_style: str = PrintStyle.ASCII,
) -> FOLParseResult:
    """Parse *text* as canonical many-sorted FOL against *signature*."""

    syntax = CanonicalFOLSyntax(signature, print_style=print_style)
    return syntax.parse_text(
        text,
        document_id=document_id,
        expression_id=expression_id,
        limits=limits,
    )


def print_fol(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    """Print *node* in canonical FOL notation."""

    return CanonicalFOLPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    signature: LogicSignature,
    *,
    style: str = PrintStyle.ASCII,
) -> FOLParseResult:
    """Parse/print/parse round-trip with alpha-equivalence check."""

    return CanonicalFOLSyntax(signature, print_style=style).round_trip(text)


__all__ = [
    "CANONICAL_FOL_FAMILY_ID",
    "CANONICAL_FOL_NOTATION_ID",
    "CANONICAL_FOL_NOTATION_VERSION",
    "CANONICAL_FOL_PROFILE_ID",
    "CANONICAL_FOL_SYNTAX_INTERFACE",
    "CODE_ARITY_MISMATCH",
    "CODE_EMPTY_INPUT",
    "CODE_KIND_MISMATCH",
    "CODE_LEXER_ERROR",
    "CODE_MISSING_SIGNATURE",
    "CODE_PARSE_DEPTH",
    "CODE_TRAILING_INPUT",
    "CODE_TYPECHECK_FAILED",
    "CODE_UNBALANCED",
    "CODE_UNDECLARED_SORT",
    "CODE_UNDECLARED_SYMBOL",
    "CODE_UNEXPECTED_TOKEN",
    "FOL_MODULE_VERSION",
    "FOL_PARSE_RESULT_SCHEMA_VERSION",
    "CanonicalFOLParser",
    "CanonicalFOLPrinter",
    "CanonicalFOLSyntax",
    "FOLParseError",
    "FOLParseResult",
    "PrintStyle",
    "parse_fol",
    "parse_print_parse",
    "print_fol",
]

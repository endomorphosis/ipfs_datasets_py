"""Unified LTL, LTLf, past-LTL, MTL, CTL, and CTL-star syntax.

Interfaces:

* ``TemporalSyntax@1`` — parse/print/elaborate for controlled temporal text
* ``TraceSemanticsProfile@1`` — explicit linear/branching, finite/infinite,
  past/future, dense/discrete, point/interval, and path choices

Surface semantics are never inferred from spelling alone.  Profile and time
domain participate in semantic identity of every temporal extension node.
Parse/print/parse is alpha-equivalent.  Invalid or unbounded metric intervals
and ambiguous single-letter ``F``/``G``/``U``/``R`` operator uses fail closed
with stable source spans.

Grammar (connective precedence, low → high binding strength)::

    formula         ::= iff_formula
    iff_formula     ::= implies_formula (('iff'|↔) implies_formula)*
    implies_formula ::= or_formula (('implies'|→|=>|->) formula)?   # right-assoc
    or_formula      ::= and_formula (('or'|∨) and_formula)*
    and_formula     ::= binary_temporal (('and'|∧) binary_temporal)*
    binary_temporal ::= unary (('until'|'release'|'weak_until'|'since'|U|R|W|S) unary)*
    unary           ::= path_op unary
                      | temporal_unary interval? unary
                      | ('not'|¬) unary
                      | atomic
    path_op         ::= 'A'|'E'|'all'|'exists'   # profile-gated
    temporal_unary  ::= 'next'|'eventually'|'always'|'previous'|'once'|'historically'
                      | 'X'|'Y'|'F'|'G'|'O'|'H'  # classic letters profile-gated
    interval        ::= ('['|'(') rational ',' rational (']'|')')
    rational        ::= NUMBER | NUMBER '/' NUMBER
    atomic          ::= 'true'|⊤ | 'false'|⊥ | IDENT | '(' formula ')'

Classic single-letter ``F``/``G``/``U``/``R`` are rejected unless the profile
explicitly admits them (they collide with propositions and deontic ``F``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum
from fractions import Fraction
from math import gcd
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_extension,
    mk_false,
    mk_true,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    propositional_signature,
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

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

TEMPORAL_SYNTAX_INTERFACE: Final = "TemporalSyntax@1"
TRACE_SEMANTICS_PROFILE_INTERFACE: Final = "TraceSemanticsProfile@1"
TEMPORAL_NOTATION_ID: Final = "canonical_temporal"
TEMPORAL_NOTATION_VERSION: Final = "1.0.0"
TEMPORAL_FAMILY_ID: Final = "temporal"
TEMPORAL_MODULE_VERSION: Final = "1.0.0"
TEMPORAL_PARSE_RESULT_SCHEMA_VERSION: Final = "canonical-temporal-parse-result/v1"
TRACE_SEMANTICS_PROFILE_SCHEMA_VERSION: Final = "trace-semantics-profile/v1"
TEMPORAL_INTERVAL_SCHEMA_VERSION: Final = "temporal.interval/v1"
TEMPORAL_OPERATOR_PAYLOAD_SCHEMA: Final = "temporal.operator/v1"
TEMPORAL_PATH_PAYLOAD_SCHEMA: Final = "temporal.path/v1"

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "temporal.unexpected_token"
CODE_TRAILING_INPUT: Final = "temporal.trailing_input"
CODE_EMPTY_INPUT: Final = "temporal.empty_input"
CODE_PARSE_DEPTH: Final = "temporal.parse_depth_exceeded"
CODE_UNBALANCED: Final = "temporal.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "temporal.lexer_error"
CODE_AMBIGUOUS_TEMPORAL: Final = "temporal.ambiguous_operator"
CODE_INVALID_INTERVAL: Final = "temporal.invalid_interval"
CODE_UNBOUNDED_INTERVAL: Final = "temporal.unbounded_interval"
CODE_PROFILE_MISMATCH: Final = "temporal.profile_mismatch"
CODE_MISSING_INTERVAL: Final = "temporal.missing_interval"
CODE_UNEXPECTED_INTERVAL: Final = "temporal.unexpected_interval"
CODE_PATH_REQUIRED: Final = "temporal.path_required"
CODE_PATH_FORBIDDEN: Final = "temporal.path_forbidden"
CODE_PAST_FORBIDDEN: Final = "temporal.past_forbidden"
CODE_ROUND_TRIP: Final = "temporal.round_trip_failed"

_ALL_TEMPORAL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_AMBIGUOUS_TEMPORAL,
        CODE_INVALID_INTERVAL,
        CODE_UNBOUNDED_INTERVAL,
        CODE_PROFILE_MISMATCH,
        CODE_MISSING_INTERVAL,
        CODE_UNEXPECTED_INTERVAL,
        CODE_PATH_REQUIRED,
        CODE_PATH_FORBIDDEN,
        CODE_PAST_FORBIDDEN,
        CODE_ROUND_TRIP,
    }
)

# Operator lexeme sets.
_NOT_OPS: Final[frozenset[str]] = frozenset({"not", "¬", "~", "!"})
_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&"})
_OR_OPS: Final[frozenset[str]] = frozenset({"or", "∨", "|", "||"})
_IMPLIES_OPS: Final[frozenset[str]] = frozenset(
    {"implies", "→", "⇒", "=>", "->", "==>"}
)
_IFF_OPS: Final[frozenset[str]] = frozenset({"iff", "↔", "⇔", "<=>", "<->"})
_TRUE_OPS: Final[frozenset[str]] = frozenset({"true", "⊤"})
_FALSE_OPS: Final[frozenset[str]] = frozenset({"false", "⊥"})

# Multi-letter temporal operators (always admitted when profile allows the class).
_NEXT_WORDS: Final[frozenset[str]] = frozenset({"next", "X"})
_PREV_WORDS: Final[frozenset[str]] = frozenset({"previous", "prev", "Y"})
_EVENTUALLY_WORDS: Final[frozenset[str]] = frozenset({"eventually", "F"})
_ALWAYS_WORDS: Final[frozenset[str]] = frozenset({"always", "G"})
_ONCE_WORDS: Final[frozenset[str]] = frozenset({"once", "O"})
_HIST_WORDS: Final[frozenset[str]] = frozenset({"historically", "H"})
_UNTIL_WORDS: Final[frozenset[str]] = frozenset({"until", "U"})
_RELEASE_WORDS: Final[frozenset[str]] = frozenset({"release", "R"})
_WEAK_UNTIL_WORDS: Final[frozenset[str]] = frozenset({"weak_until", "W"})
_SINCE_WORDS: Final[frozenset[str]] = frozenset({"since", "S"})
_PATH_ALL_WORDS: Final[frozenset[str]] = frozenset({"all", "A"})
_PATH_EXISTS_WORDS: Final[frozenset[str]] = frozenset({"exists", "E"})

# Single-letter forms that are ambiguous without an explicit profile admission.
_AMBIGUOUS_UNARY_LETTERS: Final[frozenset[str]] = frozenset({"F", "G"})
_AMBIGUOUS_BINARY_LETTERS: Final[frozenset[str]] = frozenset({"U", "R"})
# Classic single-letter temporal alphabet (admitted only when profile says so).
_CLASSIC_UNARY_LETTERS: Final[frozenset[str]] = frozenset(
    {"X", "Y", "F", "G", "O", "H"}
)
_CLASSIC_BINARY_LETTERS: Final[frozenset[str]] = frozenset({"U", "R", "W", "S"})
_CLASSIC_PATH_LETTERS: Final[frozenset[str]] = frozenset({"A", "E"})

_FUTURE_UNARY: Final[frozenset[str]] = frozenset(
    {"next", "eventually", "always"}
)
_PAST_UNARY: Final[frozenset[str]] = frozenset(
    {"previous", "once", "historically"}
)
_FUTURE_BINARY: Final[frozenset[str]] = frozenset(
    {"until", "release", "weak_until"}
)
_PAST_BINARY: Final[frozenset[str]] = frozenset({"since"})
_ALL_TEMPORAL_UNARY: Final[frozenset[str]] = _FUTURE_UNARY | _PAST_UNARY
_ALL_TEMPORAL_BINARY: Final[frozenset[str]] = _FUTURE_BINARY | _PAST_BINARY

_TEMPORAL_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "implies",
    "iff",
    "true",
    "false",
    "next",
    "previous",
    "prev",
    "eventually",
    "always",
    "once",
    "historically",
    "until",
    "release",
    "weak_until",
    "since",
    "all",
    "exists",
)

# Canonical operator name after normalizing surface synonyms.
_UNARY_CANON: Final[Mapping[str, str]] = {
    "next": "next",
    "x": "next",
    "previous": "previous",
    "prev": "previous",
    "y": "previous",
    "eventually": "eventually",
    "f": "eventually",
    "always": "always",
    "g": "always",
    "once": "once",
    "o": "once",
    "historically": "historically",
    "h": "historically",
}
_BINARY_CANON: Final[Mapping[str, str]] = {
    "until": "until",
    "u": "until",
    "release": "release",
    "r": "release",
    "weak_until": "weak_until",
    "w": "weak_until",
    "since": "since",
    "s": "since",
}
_PATH_CANON: Final[Mapping[str, str]] = {
    "all": "all",
    "a": "all",
    "exists": "exists",
    "e": "exists",
}


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class TemporalLogicKind(str, Enum):
    """Declared temporal logic family/profile fragment."""

    LTL = "ltl"
    LTLF = "ltlf"
    PAST_LTL = "past_ltl"
    MTL = "mtl"
    CTL = "ctl"
    CTL_STAR = "ctl_star"


class TimeDomain(str, Enum):
    """Time carrier density for the declared profile."""

    DISCRETE = "discrete"
    DENSE = "dense"


class TraceModelKind(str, Enum):
    """Trace length model (finite / infinite)."""

    FINITE = "finite"
    INFINITE = "infinite"
    FINITE_OR_INFINITE = "finite_or_infinite"


class PathQuantifierKind(str, Enum):
    """Branching-time path selection."""

    ALL = "all"
    EXISTS = "exists"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    IFF = 10
    IMPLIES = 20
    OR = 30
    AND = 40
    BINARY_TEMP = 50
    UNARY = 60
    ATOM = 70


# ---------------------------------------------------------------------------
# Exact rational interval
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RationalBound:
    """Non-negative reduced rational bound (exact; no host floats)."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or not isinstance(self.numerator, int):
            raise SyntaxContractError("rational numerator must be an integer")
        if isinstance(self.denominator, bool) or not isinstance(
            self.denominator, int
        ):
            raise SyntaxContractError("rational denominator must be an integer")
        if self.numerator < 0:
            raise SyntaxContractError("rational bounds must be non-negative")
        if self.denominator <= 0:
            raise SyntaxContractError("rational denominator must be positive")
        divisor = gcd(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", self.numerator // divisor)
        object.__setattr__(self, "denominator", self.denominator // divisor)

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def to_dict(self) -> dict[str, int]:
        return {"denominator": self.denominator, "numerator": self.numerator}

    @classmethod
    def from_value(cls, value: RationalBound | int | Mapping[str, Any]) -> RationalBound:
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):
            raise SyntaxContractError("rational bounds must not be booleans")
        if isinstance(value, int):
            return cls(value)
        if isinstance(value, float):
            raise SyntaxContractError(
                "floating-point bounds are rejected; use exact rationals"
            )
        if not isinstance(value, Mapping):
            raise SyntaxContractError("rational bound must be int or mapping")
        return cls(
            numerator=int(value.get("numerator", 0)),
            denominator=int(value.get("denominator", 1)),
        )

    def __str__(self) -> str:
        if self.denominator == 1:
            return str(self.numerator)
        return f"{self.numerator}/{self.denominator}"


@dataclass(frozen=True, slots=True)
class MetricInterval:
    """Bounded non-empty exact interval (unbounded intervals are rejected)."""

    lower: RationalBound
    upper: RationalBound
    lower_closed: bool = True
    upper_closed: bool = True
    schema_version: str = TEMPORAL_INTERVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "lower", RationalBound.from_value(self.lower))
        object.__setattr__(self, "upper", RationalBound.from_value(self.upper))
        if not isinstance(self.lower_closed, bool) or not isinstance(
            self.upper_closed, bool
        ):
            raise SyntaxContractError("interval boundary flags must be booleans")
        if self.upper.fraction < self.lower.fraction:
            raise SyntaxContractError(
                "interval upper boundary must not precede lower boundary"
            )
        if self.upper.fraction == self.lower.fraction and not (
            self.lower_closed and self.upper_closed
        ):
            raise SyntaxContractError("interval must not be empty")
        if self.schema_version != TEMPORAL_INTERVAL_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported interval schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lower": self.lower.to_dict(),
            "lower_closed": self.lower_closed,
            "schema_version": self.schema_version,
            "upper": self.upper.to_dict(),
            "upper_closed": self.upper_closed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MetricInterval:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("interval must be a mapping")
        return cls(
            lower=RationalBound.from_value(value.get("lower", 0)),
            upper=RationalBound.from_value(value.get("upper", 0)),
            lower_closed=bool(value.get("lower_closed", True)),
            upper_closed=bool(value.get("upper_closed", True)),
            schema_version=str(
                value.get("schema_version") or TEMPORAL_INTERVAL_SCHEMA_VERSION
            ),
        )

    def surface(self) -> str:
        left = "[" if self.lower_closed else "("
        right = "]" if self.upper_closed else ")"
        return f"{left}{self.lower},{self.upper}{right}"


# ---------------------------------------------------------------------------
# Trace semantics profile (enters semantic identity)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceSemanticsProfile:
    """Explicit temporal/trace semantic choices (``TraceSemanticsProfile@1``).

    Linear/branching, finite/infinite, past/future, dense/discrete,
    point/interval, and path-quantifier admission are fields — never inferred
    from operator spelling.
    """

    profile_id: str
    logic: TemporalLogicKind | str
    time_domain: TimeDomain | str
    trace_model: TraceModelKind | str
    metric_intervals: bool = False
    allow_past: bool = False
    allow_path_quantifiers: bool = False
    admit_classic_letters: bool = False
    branching: bool = False
    schema_version: str = TRACE_SEMANTICS_PROFILE_SCHEMA_VERSION

    interface: ClassVar[str] = TRACE_SEMANTICS_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.profile_id, str)
            or not self.profile_id
            or self.profile_id != self.profile_id.strip()
            or "\x00" in self.profile_id
        ):
            raise SyntaxContractError(
                "profile_id must be a non-empty trimmed string without NUL"
            )
        logic = (
            self.logic
            if isinstance(self.logic, TemporalLogicKind)
            else TemporalLogicKind(str(self.logic))
        )
        time_domain = (
            self.time_domain
            if isinstance(self.time_domain, TimeDomain)
            else TimeDomain(str(self.time_domain))
        )
        trace_model = (
            self.trace_model
            if isinstance(self.trace_model, TraceModelKind)
            else TraceModelKind(str(self.trace_model))
        )
        object.__setattr__(self, "logic", logic)
        object.__setattr__(self, "time_domain", time_domain)
        object.__setattr__(self, "trace_model", trace_model)
        for name in (
            "metric_intervals",
            "allow_past",
            "allow_path_quantifiers",
            "admit_classic_letters",
            "branching",
        ):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        if self.schema_version != TRACE_SEMANTICS_PROFILE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported TraceSemanticsProfile schema {self.schema_version!r}"
            )
        # Cross-field consistency.
        if logic is TemporalLogicKind.MTL and not self.metric_intervals:
            raise SyntaxContractError("MTL profiles require metric_intervals=True")
        if logic is not TemporalLogicKind.MTL and self.metric_intervals:
            raise SyntaxContractError(
                "metric_intervals is only admitted for MTL profiles"
            )
        if logic is TemporalLogicKind.PAST_LTL and not self.allow_past:
            raise SyntaxContractError("past_ltl profiles require allow_past=True")
        if logic in {TemporalLogicKind.CTL, TemporalLogicKind.CTL_STAR}:
            if not self.allow_path_quantifiers or not self.branching:
                raise SyntaxContractError(
                    "CTL/CTL* profiles require allow_path_quantifiers and branching"
                )
        if logic is TemporalLogicKind.LTLF and trace_model is not TraceModelKind.FINITE:
            raise SyntaxContractError("ltlf profiles require finite trace_model")
        if (
            logic is TemporalLogicKind.LTL
            and trace_model is TraceModelKind.FINITE
        ):
            raise SyntaxContractError(
                "ltl profiles require infinite or finite_or_infinite traces"
            )

    @property
    def semantic_identity(self) -> dict[str, Any]:
        """Stable identity fragment contributed by profile and time domain."""

        return {
            "branching": self.branching,
            "logic": self.logic.value
            if isinstance(self.logic, TemporalLogicKind)
            else str(self.logic),
            "metric_intervals": self.metric_intervals,
            "profile_id": self.profile_id,
            "time_domain": self.time_domain.value
            if isinstance(self.time_domain, TimeDomain)
            else str(self.time_domain),
            "trace_model": self.trace_model.value
            if isinstance(self.trace_model, TraceModelKind)
            else str(self.trace_model),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_classic_letters": self.admit_classic_letters,
            "allow_past": self.allow_past,
            "allow_path_quantifiers": self.allow_path_quantifiers,
            "branching": self.branching,
            "interface": self.interface,
            "logic": self.logic.value
            if isinstance(self.logic, TemporalLogicKind)
            else str(self.logic),
            "metric_intervals": self.metric_intervals,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "time_domain": self.time_domain.value
            if isinstance(self.time_domain, TimeDomain)
            else str(self.time_domain),
            "trace_model": self.trace_model.value
            if isinstance(self.trace_model, TraceModelKind)
            else str(self.trace_model),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TraceSemanticsProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("TraceSemanticsProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            logic=value.get("logic", TemporalLogicKind.LTL.value),
            time_domain=value.get("time_domain", TimeDomain.DISCRETE.value),
            trace_model=value.get("trace_model", TraceModelKind.INFINITE.value),
            metric_intervals=bool(value.get("metric_intervals", False)),
            allow_past=bool(value.get("allow_past", False)),
            allow_path_quantifiers=bool(value.get("allow_path_quantifiers", False)),
            admit_classic_letters=bool(value.get("admit_classic_letters", False)),
            branching=bool(value.get("branching", False)),
            schema_version=str(
                value.get("schema_version") or TRACE_SEMANTICS_PROFILE_SCHEMA_VERSION
            ),
        )


def profile_ltl(
    *,
    profile_id: str = "ltl_infinite_discrete",
    admit_classic_letters: bool = False,
) -> TraceSemanticsProfile:
    return TraceSemanticsProfile(
        profile_id=profile_id,
        logic=TemporalLogicKind.LTL,
        time_domain=TimeDomain.DISCRETE,
        trace_model=TraceModelKind.INFINITE,
        admit_classic_letters=admit_classic_letters,
    )


def profile_ltlf(
    *,
    profile_id: str = "ltlf_finite_discrete",
    admit_classic_letters: bool = False,
) -> TraceSemanticsProfile:
    return TraceSemanticsProfile(
        profile_id=profile_id,
        logic=TemporalLogicKind.LTLF,
        time_domain=TimeDomain.DISCRETE,
        trace_model=TraceModelKind.FINITE,
        admit_classic_letters=admit_classic_letters,
    )


def profile_past_ltl(
    *,
    profile_id: str = "past_ltl_infinite_discrete",
    admit_classic_letters: bool = False,
) -> TraceSemanticsProfile:
    return TraceSemanticsProfile(
        profile_id=profile_id,
        logic=TemporalLogicKind.PAST_LTL,
        time_domain=TimeDomain.DISCRETE,
        trace_model=TraceModelKind.INFINITE,
        allow_past=True,
        admit_classic_letters=admit_classic_letters,
    )


def profile_mtl(
    *,
    profile_id: str = "mtl_finite_discrete",
    time_domain: TimeDomain | str = TimeDomain.DISCRETE,
    admit_classic_letters: bool = False,
) -> TraceSemanticsProfile:
    return TraceSemanticsProfile(
        profile_id=profile_id,
        logic=TemporalLogicKind.MTL,
        time_domain=time_domain,
        trace_model=TraceModelKind.FINITE,
        metric_intervals=True,
        admit_classic_letters=admit_classic_letters,
    )


def profile_ctl(
    *,
    profile_id: str = "ctl_infinite_discrete",
    admit_classic_letters: bool = False,
) -> TraceSemanticsProfile:
    return TraceSemanticsProfile(
        profile_id=profile_id,
        logic=TemporalLogicKind.CTL,
        time_domain=TimeDomain.DISCRETE,
        trace_model=TraceModelKind.INFINITE,
        allow_path_quantifiers=True,
        branching=True,
        admit_classic_letters=admit_classic_letters,
    )


def profile_ctl_star(
    *,
    profile_id: str = "ctl_star_infinite_discrete",
    admit_classic_letters: bool = False,
) -> TraceSemanticsProfile:
    return TraceSemanticsProfile(
        profile_id=profile_id,
        logic=TemporalLogicKind.CTL_STAR,
        time_domain=TimeDomain.DISCRETE,
        trace_model=TraceModelKind.INFINITE,
        allow_path_quantifiers=True,
        branching=True,
        admit_classic_letters=admit_classic_letters,
    )


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TemporalParseResult:
    """Typed result of a canonical temporal parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: TraceSemanticsProfile | None = None
    schema_version: str = TEMPORAL_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = TEMPORAL_SYNTAX_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)


class TemporalParseError(SyntaxContractError):
    """Raised by raising helpers when a temporal parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: TemporalParseResult | None = None,
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
        targets = {
            item.casefold() if item.isascii() and item.isalpha() else item
            for item in lexemes
        }
        if token.kind == TokenKind.KEYWORD.value:
            if token.lexeme.casefold() in {t.casefold() for t in targets}:
                return self.advance()
            return None
        if token.lexeme in targets:
            return self.advance()
        if token.lexeme.casefold() in {t.casefold() for t in targets if t.isalpha()}:
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
        if token.lexeme.casefold() in {
            item.casefold() for item in lexemes if item.isalpha()
        }:
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

    def range_span(self, start: SourceRange, end: SourceRange) -> SourceRange:
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
        return self.tokens[-1].range


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
    diag_id = diagnostic_id or f"diag:temporal:{code.replace('.', '-')}"
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


class _TemporalParserEngine:
    """Profile-bound recursive-descent parser for unified temporal syntax."""

    def __init__(
        self,
        *,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: TraceSemanticsProfile,
        limits: ParseLimits,
        expression_id: str = "expr:temporal:1",
        propositions: frozenset[str] | None = None,
    ) -> None:
        self.document = document
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self.propositions = propositions
        self.cursor = _TokenCursor(tokens, document)
        self.sink = DiagnosticSink(max_diagnostics=limits.max_diagnostics)
        self._node_seq = 0
        self.root: LogicNode | None = None

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if self.cursor.is_eof():
            self._emit(
                CODE_EMPTY_INPUT,
                "empty input; expected a temporal formula",
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
            # CTL strict: top-level state formulas may be path-quantified.
            self.root = node
            return node, self.sink.items
        except _ParseFail as failure:
            diag_id = f"diag:temporal:fail:{len(self.sink.items) + 1}"
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
            diagnostic_id=(
                f"diag:temporal:{code.replace('.', '-')}:{len(self.sink.items) + 1}"
            ),
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

    # -- formula layers ----------------------------------------------------

    def _parse_formula(self) -> LogicNode:
        self._enter()
        try:
            return self._parse_iff()
        finally:
            self._leave()

    def _parse_iff(self) -> LogicNode:
        left = self._parse_implies()
        while True:
            op = self.cursor.match_any(_IFF_OPS)
            if op is None:
                return left
            right = self._parse_implies()
            span = self.cursor.range_span(
                left.range or op.range, right.range or op.range
            )
            left = LogicNode(
                node_id=self._nid("iff"),
                kind=NodeKind.IFF,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
            )

    def _parse_implies(self) -> LogicNode:
        left = self._parse_or()
        op = self.cursor.match_any(_IMPLIES_OPS)
        if op is None:
            return left
        # Right-associative: consequent is a full formula.
        right = self._parse_formula()
        span = self.cursor.range_span(left.range or op.range, right.range or op.range)
        return LogicNode(
            node_id=self._nid("imp"),
            kind=NodeKind.IMPLIES,
            sort=BOOL_SORT,
            arguments=(left, right),
            range=span,
        )

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
        nodes = [self._parse_binary_temporal()]
        while self.cursor.match_any(_AND_OPS) is not None:
            nodes.append(self._parse_binary_temporal())
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

    def _parse_binary_temporal(self) -> LogicNode:
        left = self._parse_unary()
        while True:
            op_info = self._match_binary_temporal()
            if op_info is None:
                return left
            op_token, operator, interval = op_info
            right = self._parse_unary()
            span = self.cursor.range_span(
                left.range or op_token.range, right.range or op_token.range
            )
            left = self._mk_temporal(
                operator,
                children=(left, right),
                interval=interval,
                span=span,
            )

    def _parse_unary(self) -> LogicNode:
        # Path quantifier.
        path = self._match_path_quantifier()
        if path is not None:
            path_token, quantifier = path
            self._enter()
            try:
                body = self._parse_unary()
            finally:
                self._leave()
            if self.profile.logic is TemporalLogicKind.CTL:
                # CTL requires path quantifier immediately over a temporal.
                if not self._is_temporal_extension(body):
                    raise _ParseFail(
                        _diag(
                            code=CODE_PATH_REQUIRED,
                            message=(
                                "CTL path quantifier must wrap a temporal "
                                "operator (next/eventually/always/until/...)"
                            ),
                            range=path_token.range,
                            remediation="Write e.g. A always p or E (p until q)",
                        )
                    )
            span = self.cursor.range_span(
                path_token.range, body.range or path_token.range
            )
            return self._mk_path(quantifier, body=body, span=span)

        # Temporal unary.
        temporal = self._match_unary_temporal()
        if temporal is not None:
            op_token, operator, interval = temporal
            self._enter()
            try:
                body = self._parse_unary()
            finally:
                self._leave()
            span = self.cursor.range_span(
                op_token.range, body.range or op_token.range
            )
            return self._mk_temporal(
                operator,
                children=(body,),
                interval=interval,
                span=span,
            )

        # Boolean not.
        not_tok = self.cursor.match_any(_NOT_OPS)
        if not_tok is not None:
            self._enter()
            try:
                inner = self._parse_unary()
            finally:
                self._leave()
            span = self.cursor.range_span(not_tok.range, inner.range or not_tok.range)
            return LogicNode(
                node_id=self._nid("not"),
                kind=NodeKind.NOT,
                sort=BOOL_SORT,
                arguments=(inner,),
                range=span,
            )

        return self._parse_atomic()

    def _parse_atomic(self) -> LogicNode:
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

        token = self.cursor.match_any(_TRUE_OPS)
        if token is not None:
            node = mk_true(self._nid("true"))
            return LogicNode(
                node_id=node.node_id,
                kind=NodeKind.TRUE,
                sort=BOOL_SORT,
                range=token.range,
            )
        token = self.cursor.match_any(_FALSE_OPS)
        if token is not None:
            node = mk_false(self._nid("false"))
            return LogicNode(
                node_id=node.node_id,
                kind=NodeKind.FALSE,
                sort=BOOL_SORT,
                range=token.range,
            )

        current = self.cursor.current()
        if current.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            # Reject ambiguous classic letters used alone when they look like
            # operators without a following operand already handled above.
            name = current.lexeme
            self.cursor.advance()
            if self.propositions is not None and name not in self.propositions:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNEXPECTED_TOKEN,
                        message=f"undeclared proposition {name!r}",
                        range=current.range,
                        remediation="Declare the proposition or add it to the alphabet",
                    )
                )
            return LogicNode(
                node_id=self._nid("atom"),
                kind=NodeKind.PREDICATE,
                symbol=name,
                sort=BOOL_SORT,
                arguments=(),
                range=current.range,
            )

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected formula; got {current.lexeme!r}",
                range=current.range,
            )
        )

    # -- operator matching -------------------------------------------------

    def _match_unary_temporal(
        self,
    ) -> tuple[LogicToken, str, MetricInterval | None] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        raw = token.lexeme
        folded = raw.casefold()

        # Detect ambiguous single-letter F/G in operator position.
        if raw in _AMBIGUOUS_UNARY_LETTERS or folded in {"f", "g"}:
            if not self.profile.admit_classic_letters:
                # Operator position: letter followed by formula material, or by interval.
                if self._looks_like_operator_use():
                    raise _ParseFail(
                        _diag(
                            code=CODE_AMBIGUOUS_TEMPORAL,
                            message=(
                                f"ambiguous temporal operator {raw!r}; "
                                "single-letter F/G require admit_classic_letters "
                                "or multi-letter eventually/always"
                            ),
                            range=token.range,
                            remediation=(
                                "Write 'eventually'/'always', or set "
                                "admit_classic_letters=True on the profile"
                            ),
                            metadata={"operator": raw},
                        )
                    )
                return None  # bare atom proposition named F/G

        canon = None
        is_classic_letter = raw in _CLASSIC_UNARY_LETTERS and len(raw) == 1
        if is_classic_letter and not self.profile.admit_classic_letters:
            # X/Y/O/H without classic letters: treat as atoms unless multi-letter.
            if folded in _UNARY_CANON and len(raw) == 1:
                return None
        if folded in _UNARY_CANON:
            # Multi-letter words always match; classic letters only if admitted.
            if is_classic_letter and not self.profile.admit_classic_letters:
                return None
            # Multi-letter keywords and admitted classic letters.
            if token.kind in {
                TokenKind.KEYWORD.value,
                TokenKind.IDENTIFIER.value,
            }:
                # Prefer keyword match for multi-letter temporal words.
                if len(raw) > 1 or self.profile.admit_classic_letters:
                    if len(raw) == 1 and not self.profile.admit_classic_letters:
                        return None
                    canon = _UNARY_CANON[folded]

        if canon is None:
            return None

        # Consume operator token.
        self.cursor.advance()
        if canon in _PAST_UNARY and not self.profile.allow_past:
            raise _ParseFail(
                _diag(
                    code=CODE_PAST_FORBIDDEN,
                    message=(
                        f"past operator {canon!r} is not admitted by profile "
                        f"{self.profile.profile_id!r}"
                    ),
                    range=token.range,
                    remediation="Use a past_ltl (or past-enabled) profile",
                )
            )

        interval = self._parse_optional_interval(after=token)
        return token, canon, interval

    def _match_binary_temporal(
        self,
    ) -> tuple[LogicToken, str, MetricInterval | None] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        raw = token.lexeme
        folded = raw.casefold()

        if raw in _AMBIGUOUS_BINARY_LETTERS or folded in {"u", "r"}:
            if not self.profile.admit_classic_letters:
                if self._looks_like_binary_operator_use():
                    raise _ParseFail(
                        _diag(
                            code=CODE_AMBIGUOUS_TEMPORAL,
                            message=(
                                f"ambiguous temporal operator {raw!r}; "
                                "single-letter U/R require admit_classic_letters "
                                "or multi-letter until/release"
                            ),
                            range=token.range,
                            remediation=(
                                "Write 'until'/'release', or set "
                                "admit_classic_letters=True on the profile"
                            ),
                            metadata={"operator": raw},
                        )
                    )
                return None

        is_classic = raw in _CLASSIC_BINARY_LETTERS and len(raw) == 1
        if folded not in _BINARY_CANON:
            return None
        if is_classic and not self.profile.admit_classic_letters:
            return None
        if len(raw) == 1 and not self.profile.admit_classic_letters:
            return None
        if token.kind not in {TokenKind.KEYWORD.value, TokenKind.IDENTIFIER.value}:
            return None

        canon = _BINARY_CANON[folded]
        self.cursor.advance()
        if canon in _PAST_BINARY and not self.profile.allow_past:
            raise _ParseFail(
                _diag(
                    code=CODE_PAST_FORBIDDEN,
                    message=(
                        f"past operator {canon!r} is not admitted by profile "
                        f"{self.profile.profile_id!r}"
                    ),
                    range=token.range,
                )
            )
        interval = self._parse_optional_interval(after=token)
        return token, canon, interval

    def _match_path_quantifier(self) -> tuple[LogicToken, PathQuantifierKind] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        raw = token.lexeme
        folded = raw.casefold()
        if folded not in _PATH_CANON:
            return None
        if token.kind not in {TokenKind.KEYWORD.value, TokenKind.IDENTIFIER.value}:
            return None
        # Multi-letter all/exists always available when path quantifiers admitted.
        # Classic A/E require path quantifiers (and are not F/G/U/R ambiguous).
        if not self.profile.allow_path_quantifiers:
            if len(raw) > 1 and folded in {"all", "exists"}:
                # Only error when used in operator position; bare keyword atoms
                # are not expected for all/exists under non-CTL profiles.
                if self._looks_like_operator_use():
                    raise _ParseFail(
                        _diag(
                            code=CODE_PATH_FORBIDDEN,
                            message=(
                                f"path quantifier {raw!r} is not admitted by profile "
                                f"{self.profile.profile_id!r}"
                            ),
                            range=token.range,
                            remediation="Use a ctl or ctl_star profile",
                        )
                    )
            return None
        # Bare A/E/all/exists without a following formula is an atom, not a quantifier.
        if not self._looks_like_operator_use():
            return None
        quant = PathQuantifierKind(_PATH_CANON[folded])
        self.cursor.advance()
        return token, quant

    def _looks_like_operator_use(self) -> bool:
        """True when current F/G is followed by formula material or an interval."""

        nxt = self.cursor.peek(1)
        if nxt.kind == TokenKind.EOF.value:
            return False
        if nxt.lexeme in {"[", "("}:
            # F[0,1] p  or  F (p) — interval or grouped operand.
            # Bare F as atom cannot be followed by '['.
            if nxt.lexeme == "[":
                return True
            # '(' could start a parenthesized formula operand.
            return True
        if nxt.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
            TokenKind.NUMBER.value,
        }:
            # F p  — operator use.
            if nxt.lexeme.casefold() in {
                "and",
                "or",
                "implies",
                "iff",
                "until",
                "release",
                "since",
                "weak_until",
            }:
                return False
            return True
        if nxt.lexeme in _NOT_OPS | _TRUE_OPS | _FALSE_OPS:
            return True
        return False

    def _looks_like_binary_operator_use(self) -> bool:
        nxt = self.cursor.peek(1)
        if nxt.kind == TokenKind.EOF.value:
            return False
        if nxt.lexeme in {"]", ")", ",", ";"}:
            return False
        if nxt.lexeme in {"[", "("}:
            return True
        if nxt.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
            TokenKind.NUMBER.value,
        }:
            return True
        if nxt.lexeme in _NOT_OPS | _TRUE_OPS | _FALSE_OPS:
            return True
        return False

    # -- intervals ---------------------------------------------------------

    def _looks_like_interval_start(self) -> bool:
        """Distinguish metric intervals from parenthesized operands.

        ``[`` always begins an interval.  ``(`` begins an interval only when
        the next token is a numeric bound (so ``always (p)`` stays a grouped
        formula under non-MTL profiles).
        """

        token = self.cursor.current()
        if token.lexeme == "[":
            return True
        if token.lexeme != "(":
            return False
        nxt = self.cursor.peek(1)
        return nxt.kind == TokenKind.NUMBER.value

    def _parse_optional_interval(
        self, *, after: LogicToken
    ) -> MetricInterval | None:
        if not self._looks_like_interval_start():
            if self.profile.metric_intervals:
                raise _ParseFail(
                    _diag(
                        code=CODE_MISSING_INTERVAL,
                        message=(
                            "MTL temporal operators require an explicit "
                            "bounded metric interval"
                        ),
                        range=after.range,
                        remediation="Write e.g. eventually[0,1] p",
                    )
                )
            return None
        token = self.cursor.current()
        if not self.profile.metric_intervals:
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_INTERVAL,
                    message=(
                        "metric intervals are not admitted by profile "
                        f"{self.profile.profile_id!r}"
                    ),
                    range=token.range,
                    remediation="Use an MTL profile for metric intervals",
                )
            )
        return self._parse_interval()

    def _parse_interval(self) -> MetricInterval:
        open_tok = self.cursor.current()
        if open_tok.lexeme not in {"[", "("}:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_INTERVAL,
                    message=f"expected interval opener; got {open_tok.lexeme!r}",
                    range=open_tok.range,
                )
            )
        self.cursor.advance()
        lower_closed = open_tok.lexeme == "["

        # Reject unbounded lower: empty bound or infinity markers.
        if self.cursor.current().lexeme in {",", "]", ")", "inf", "∞", "*"}:
            raise _ParseFail(
                _diag(
                    code=CODE_UNBOUNDED_INTERVAL,
                    message="unbounded or missing interval lower bound is rejected",
                    range=self.cursor.current().range,
                    remediation="Provide exact non-negative rational bounds [a,b]",
                )
            )

        lower = self._parse_rational_bound()
        self.cursor.expect_lexeme(",", code=CODE_INVALID_INTERVAL)

        # Reject unbounded upper.
        upper_tok = self.cursor.current()
        if upper_tok.lexeme in {"]", ")", "inf", "∞", "*", "+inf", "+∞"}:
            raise _ParseFail(
                _diag(
                    code=CODE_UNBOUNDED_INTERVAL,
                    message="unbounded interval upper bound is rejected",
                    range=upper_tok.range,
                    remediation="Provide a finite exact rational upper bound",
                    metadata={"bound": upper_tok.lexeme},
                )
            )
        if upper_tok.kind == TokenKind.EOF.value:
            raise _ParseFail(
                _diag(
                    code=CODE_UNBOUNDED_INTERVAL,
                    message="unbounded interval upper bound is rejected",
                    range=upper_tok.range,
                )
            )

        upper = self._parse_rational_bound()
        close_tok = self.cursor.current()
        if close_tok.lexeme not in {"]", ")"}:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_INTERVAL,
                    message=f"expected interval closer; got {close_tok.lexeme!r}",
                    range=close_tok.range,
                )
            )
        self.cursor.advance()
        upper_closed = close_tok.lexeme == "]"

        try:
            return MetricInterval(
                lower=lower,
                upper=upper,
                lower_closed=lower_closed,
                upper_closed=upper_closed,
            )
        except SyntaxContractError as error:
            span = self.cursor.range_span(open_tok.range, close_tok.range)
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_INTERVAL,
                    message=str(error),
                    range=span,
                )
            ) from error

    def _parse_rational_bound(self) -> RationalBound:
        token = self.cursor.current()
        if token.kind != TokenKind.NUMBER.value:
            # Infinity / star already handled by caller; other tokens are invalid.
            if token.lexeme in {"inf", "∞", "*", "+inf", "+∞"}:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNBOUNDED_INTERVAL,
                        message=f"unbounded bound {token.lexeme!r} is rejected",
                        range=token.range,
                    )
                )
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_INTERVAL,
                    message=f"expected rational bound; got {token.lexeme!r}",
                    range=token.range,
                    remediation="Use integer or p/q exact rationals (no floats)",
                )
            )
        lexeme = token.lexeme
        # Reject decimal / scientific floats — exact rationals only.
        if "." in lexeme or "e" in lexeme.casefold():
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_INTERVAL,
                    message=(
                        f"non-exact numeric literal {lexeme!r}; "
                        "use integer or p/q rationals"
                    ),
                    range=token.range,
                )
            )
        self.cursor.advance()
        try:
            numerator = int(lexeme)
        except ValueError as error:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_INTERVAL,
                    message=f"invalid integer bound {lexeme!r}",
                    range=token.range,
                )
            ) from error
        if numerator < 0:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_INTERVAL,
                    message="interval bounds must be non-negative",
                    range=token.range,
                )
            )

        # Optional / denominator.
        if self.cursor.match_lexeme("/") is not None:
            den_tok = self.cursor.current()
            if den_tok.kind != TokenKind.NUMBER.value:
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_INTERVAL,
                        message="expected denominator after '/'",
                        range=den_tok.range,
                    )
                )
            den_lex = den_tok.lexeme
            if "." in den_lex or "e" in den_lex.casefold():
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_INTERVAL,
                        message=f"non-exact denominator {den_lex!r}",
                        range=den_tok.range,
                    )
                )
            self.cursor.advance()
            try:
                denominator = int(den_lex)
            except ValueError as error:
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_INTERVAL,
                        message=f"invalid denominator {den_lex!r}",
                        range=den_tok.range,
                    )
                ) from error
            if denominator <= 0:
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_INTERVAL,
                        message="denominator must be positive",
                        range=den_tok.range,
                    )
                )
            return RationalBound(numerator, denominator)
        return RationalBound(numerator)

    # -- node construction -------------------------------------------------

    def _is_temporal_extension(self, node: LogicNode) -> bool:
        if node.kind is not NodeKind.EXTENSION and node.kind != NodeKind.EXTENSION.value:
            return False
        if node.extension is None:
            return False
        payload = dict(node.extension.payload)
        return payload.get("kind") in _ALL_TEMPORAL_UNARY | _ALL_TEMPORAL_BINARY

    def _mk_temporal(
        self,
        operator: str,
        *,
        children: Sequence[LogicNode],
        interval: MetricInterval | None,
        span: SourceRange,
    ) -> LogicNode:
        if self.profile.metric_intervals and interval is None:
            raise _ParseFail(
                _diag(
                    code=CODE_MISSING_INTERVAL,
                    message=f"MTL operator {operator!r} requires a bounded interval",
                    range=span,
                )
            )
        if not self.profile.metric_intervals and interval is not None:
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_INTERVAL,
                    message=f"operator {operator!r} rejects intervals under this profile",
                    range=span,
                )
            )
        payload: dict[str, Any] = {
            "kind": operator,
            "logic": self.profile.logic.value
            if isinstance(self.profile.logic, TemporalLogicKind)
            else str(self.profile.logic),
            "profile_id": self.profile.profile_id,
            "schema_version": TEMPORAL_OPERATOR_PAYLOAD_SCHEMA,
            "time_domain": self.profile.time_domain.value
            if isinstance(self.profile.time_domain, TimeDomain)
            else str(self.profile.time_domain),
            "trace_model": self.profile.trace_model.value
            if isinstance(self.profile.trace_model, TraceModelKind)
            else str(self.profile.trace_model),
        }
        if interval is not None:
            payload["interval"] = interval.to_dict()
        features = (f"temporal.{operator}",)
        return mk_extension(
            self._nid(operator),
            family=TEMPORAL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=features,
            payload_schema=TEMPORAL_OPERATOR_PAYLOAD_SCHEMA,
            payload=payload,
            children=tuple(children),
            range=span,
        )

    def _mk_path(
        self,
        quantifier: PathQuantifierKind,
        *,
        body: LogicNode,
        span: SourceRange,
    ) -> LogicNode:
        payload: dict[str, Any] = {
            "kind": "path",
            "logic": self.profile.logic.value
            if isinstance(self.profile.logic, TemporalLogicKind)
            else str(self.profile.logic),
            "path_quantifier": quantifier.value,
            "profile_id": self.profile.profile_id,
            "schema_version": TEMPORAL_PATH_PAYLOAD_SCHEMA,
            "time_domain": self.profile.time_domain.value
            if isinstance(self.profile.time_domain, TimeDomain)
            else str(self.profile.time_domain),
            "trace_model": self.profile.trace_model.value
            if isinstance(self.profile.trace_model, TraceModelKind)
            else str(self.profile.trace_model),
        }
        return mk_extension(
            self._nid("path"),
            family=TEMPORAL_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("temporal.path", f"temporal.path.{quantifier.value}"),
            payload_schema=TEMPORAL_PATH_PAYLOAD_SCHEMA,
            payload=payload,
            children=(body,),
            range=span,
        )


# ---------------------------------------------------------------------------
# CST / surface helpers
# ---------------------------------------------------------------------------


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:temporal:1",
) -> LogicCST:
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
    seq = counter if counter is not None else [0]
    refs: list[SurfaceASTRef] = []

    def walk(n: LogicNode) -> str:
        seq[0] += 1
        node_id = n.node_id if n.node_id else f"ast:{seq[0]}"
        child_ids: list[str] = []
        for child in n.arguments:
            child_ids.append(walk(child))
        if n.extension is not None:
            for child in n.extension.children:
                child_ids.append(walk(child))
        kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
        safe_kind = kind.replace(" ", "_")
        span = n.range or SourceRange(0, 0)
        meta: dict[str, Any] = {}
        if n.symbol:
            meta["symbol"] = n.symbol
        if n.extension is not None:
            meta["payload_schema"] = n.extension.payload_schema
            meta["features"] = list(n.extension.features)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind=safe_kind,
                range=span,
                child_ids=tuple(child_ids),
                metadata=meta,
            )
        )
        return node_id

    walk(node)
    return refs


# ---------------------------------------------------------------------------
# Semantic identity
# ---------------------------------------------------------------------------


def temporal_semantic_identity(
    node: LogicNode,
    profile: TraceSemanticsProfile,
) -> dict[str, Any]:
    """Build the semantic identity of *node* under *profile*.

    Profile id and time domain always participate.  Temporal extension payloads
    already embed both; this helper re-exports a stable sorted view for tests
    and content-addressed consumers.
    """

    def walk(n: LogicNode) -> Any:
        kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
        if kind == NodeKind.EXTENSION.value and n.extension is not None:
            ext = n.extension
            payload = dict(ext.payload)
            return {
                "children": [walk(c) for c in ext.children],
                "features": list(ext.features),
                "kind": "extension",
                "payload": payload,
                "payload_schema": ext.payload_schema,
                "profile": ext.profile.value
                if hasattr(ext.profile, "value")
                else str(ext.profile),
            }
        if kind == NodeKind.PREDICATE.value:
            return {"kind": "atom", "symbol": n.symbol}
        if kind in {NodeKind.TRUE.value, NodeKind.FALSE.value}:
            return {"kind": kind}
        if kind == NodeKind.NOT.value:
            return {"args": [walk(n.arguments[0])], "kind": "not"}
        if kind in {
            NodeKind.AND.value,
            NodeKind.OR.value,
            NodeKind.IMPLIES.value,
            NodeKind.IFF.value,
        }:
            return {"args": [walk(a) for a in n.arguments], "kind": kind}
        return {
            "args": [walk(a) for a in n.arguments],
            "kind": kind,
            "symbol": n.symbol,
        }

    return {
        "formula": walk(node),
        "profile": profile.semantic_identity,
    }


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class TemporalPrinter:
    """Deterministic printer for temporal formulas.

    Parenthesization makes implication associativity and temporal binding
    explicit so parse(print(parse(s))) is alpha-equivalent to parse(s).
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
            inner = self._print_node(node.arguments[0], _Prec.UNARY)
            text = f"{self._op('not', '¬')} {inner}"
            return self._paren(text, _Prec.UNARY, parent_prec)
        if kind is NodeKind.AND or kind == NodeKind.AND.value:
            op = f" {self._op('and', '∧')} "
            text = op.join(self._print_node(a, _Prec.AND) for a in node.arguments)
            return self._paren(text, _Prec.AND, parent_prec)
        if kind is NodeKind.OR or kind == NodeKind.OR.value:
            op = f" {self._op('or', '∨')} "
            text = op.join(self._print_node(a, _Prec.OR) for a in node.arguments)
            return self._paren(text, _Prec.OR, parent_prec)
        if kind is NodeKind.IMPLIES or kind == NodeKind.IMPLIES.value:
            left = self._print_node(node.arguments[0], _Prec.IMPLIES + 1)
            right = self._print_node(node.arguments[1], _Prec.IMPLIES)
            text = f"{left} {self._op('->', '→')} {right}"
            return self._paren(text, _Prec.IMPLIES, parent_prec)
        if kind is NodeKind.IFF or kind == NodeKind.IFF.value:
            left = self._print_node(node.arguments[0], _Prec.IFF + 1)
            right = self._print_node(node.arguments[1], _Prec.IFF + 1)
            text = f"{left} {self._op('iff', '↔')} {right}"
            return self._paren(text, _Prec.IFF, parent_prec)
        if kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
            return node.symbol
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node, parent_prec)
        raise SyntaxContractError(f"unsupported node kind for printing: {kind!r}")

    def _print_extension(self, node: LogicNode, parent_prec: int) -> str:
        assert node.extension is not None
        payload = dict(node.extension.payload)
        kind = str(payload.get("kind") or "")
        children = node.extension.children
        interval = payload.get("interval")
        interval_text = ""
        if interval is not None:
            interval_text = MetricInterval.from_dict(interval).surface()

        if kind == "path":
            quant = str(payload.get("path_quantifier") or "all")
            body = self._print_node(children[0], _Prec.UNARY)
            text = f"{quant} {body}"
            return self._paren(text, _Prec.UNARY, parent_prec)

        if kind in _ALL_TEMPORAL_UNARY:
            body = self._print_node(children[0], _Prec.UNARY)
            text = f"{kind}{interval_text} {body}"
            return self._paren(text, _Prec.UNARY, parent_prec)

        if kind in _ALL_TEMPORAL_BINARY:
            left = self._print_node(children[0], _Prec.BINARY_TEMP + 1)
            right = self._print_node(children[1], _Prec.BINARY_TEMP + 1)
            text = f"{left} {kind}{interval_text} {right}"
            return self._paren(text, _Prec.BINARY_TEMP, parent_prec)

        raise SyntaxContractError(f"unsupported temporal extension kind {kind!r}")

    def _paren(self, text: str, prec: int, parent_prec: int) -> str:
        if prec < parent_prec:
            return f"({text})"
        return text


# ---------------------------------------------------------------------------
# Public parser surface
# ---------------------------------------------------------------------------


def _collect_atoms(node: LogicNode) -> tuple[str, ...]:
    """Collect nullary predicate symbols (propositional atoms) in *node*."""

    found: list[str] = []

    def walk(n: LogicNode) -> None:
        kind = n.kind
        if kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
            if n.symbol and not n.arguments:
                found.append(n.symbol)
        for child in n.arguments:
            walk(child)
        if n.extension is not None:
            for child in n.extension.children:
                walk(child)

    walk(node)
    # Stable unique order.
    return tuple(sorted(set(found)))


def _signature_for_formula(
    root: LogicNode,
    profile: TraceSemanticsProfile,
) -> LogicSignature:
    atoms = _collect_atoms(root)
    if not atoms:
        # Empty alphabet still yields a valid temporal signature.
        return LogicSignature(
            signature_id=f"sig:temporal:{profile.profile_id}",
            family=TEMPORAL_FAMILY_ID,
            profile=profile.profile_id,
            sorts=(),
            symbols=(),
            features=("temporal", "propositional"),
        )
    return propositional_signature(
        f"sig:temporal:{profile.profile_id}",
        atoms,
        family=TEMPORAL_FAMILY_ID,
        profile=profile.profile_id,
    )


def _extract_profile(value: object) -> TraceSemanticsProfile | None:
    if value is None:
        return None
    if isinstance(value, TraceSemanticsProfile):
        return value
    if isinstance(value, Mapping):
        return TraceSemanticsProfile.from_dict(value)
    return None


class TemporalParser:
    """Notation parser for unified temporal syntax (``TemporalSyntax@1``)."""

    interface: ClassVar[str] = TEMPORAL_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = TEMPORAL_NOTATION_ID
    notation_version: ClassVar[str] = TEMPORAL_NOTATION_VERSION

    def __init__(
        self,
        profile: TraceSemanticsProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
        propositions: Sequence[str] | None = None,
    ) -> None:
        if profile is not None and not isinstance(profile, TraceSemanticsProfile):
            raise SyntaxContractError("profile must be a TraceSemanticsProfile")
        self.profile = profile
        self.printer = TemporalPrinter(style=print_style)
        self.propositions = (
            frozenset(propositions) if propositions is not None else None
        )
        self._lexer = BoundedLexer(keywords=_TEMPORAL_KEYWORDS)

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("trace_semantics_profile"))
            or self.profile
        )
        props = request.metadata.get("propositions")
        propositions = (
            frozenset(str(item) for item in props)
            if isinstance(props, Sequence) and not isinstance(props, (str, bytes))
            else self.propositions
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(request.metadata.get("expression_id") or "expr:temporal:1"),
            propositions=propositions,
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: TraceSemanticsProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:temporal:1",
        expression_id: str = "expr:temporal:1",
        propositions: frozenset[str] | None = None,
    ) -> TemporalParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message="temporal parse requires a TraceSemanticsProfile",
                range=document.full_range(),
                remediation="Pass profile=... or metadata['profile']",
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": TEMPORAL_SYNTAX_INTERFACE},
            )
            return TemporalParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )

        lex_result = self._lexer.lex(document, mode=parse_mode, limits=bounds)
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:temporal:lex:{index + 1}",
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
                metadata={"interface": TEMPORAL_SYNTAX_INTERFACE},
            )
            return TemporalParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        engine = _TemporalParserEngine(
            document=document,
            tokens=lex_result.tokens,
            profile=prof,
            limits=bounds,
            expression_id=expression_id,
            propositions=propositions if propositions is not None else self.propositions,
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
                metadata={
                    "interface": TEMPORAL_SYNTAX_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return TemporalParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        signature = _signature_for_formula(root, prof)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=TEMPORAL_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        cst = _build_covering_cst(document, lex_result.tokens)
        surface = tuple(_surface_from_node(root))
        printed = self.printer.print(root)
        identity = temporal_semantic_identity(root, prof)
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
                "interface": TEMPORAL_SYNTAX_INTERFACE,
                "expression": expression.to_dict(),
                "notation_id": TEMPORAL_NOTATION_ID,
                "notation_version": TEMPORAL_NOTATION_VERSION,
                "printed": printed,
                "profile": prof.to_dict(),
                "semantic_identity": identity,
            },
        )
        artifact.validate_against(document, limits=bounds)
        return TemporalParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
        )


class TemporalSyntax:
    """Facade for unified temporal parse/print round-trips.

    Interface: ``TemporalSyntax@1``.
    """

    interface: ClassVar[str] = TEMPORAL_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = TEMPORAL_NOTATION_ID
    notation_version: ClassVar[str] = TEMPORAL_NOTATION_VERSION
    family_id: ClassVar[str] = TEMPORAL_FAMILY_ID

    def __init__(
        self,
        profile: TraceSemanticsProfile,
        *,
        print_style: str = PrintStyle.ASCII,
        propositions: Sequence[str] | None = None,
    ) -> None:
        if not isinstance(profile, TraceSemanticsProfile):
            raise SyntaxContractError("profile must be a TraceSemanticsProfile")
        self.profile = profile
        self.parser = TemporalParser(
            profile, print_style=print_style, propositions=propositions
        )
        self.printer = self.parser.printer

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:temporal:1",
        expression_id: str = "expr:temporal:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> TemporalParseResult:
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        return self.parser.parse_document(
            document,
            profile=self.profile,
            mode=mode,
            limits=limits,
            expression_id=expression_id,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise TemporalParseError(
                result.errors[0].message if result.errors else "temporal parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def round_trip(self, text: str, **kwargs: Any) -> TemporalParseResult:
        """Parse, print, and re-parse; success requires alpha-equivalence."""

        first = self.parse_text(text, **kwargs)
        if not first.ok or first.root is None:
            return first
        printed = self.print(first.root)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:temporal:1") + ":rt",
            expression_id=str(kwargs.get("expression_id") or "expr:temporal:1") + ":rt",
            limits=kwargs.get("limits"),
            mode=kwargs.get("mode", ParseMode.STRICT),
        )
        if not second.ok or second.root is None:
            return second
        if not alpha_equivalent(first.root, second.root):
            diag = _diag(
                code=CODE_ROUND_TRIP,
                message="parse/print/parse is not alpha-equivalent",
                range=second.root.range,
            )
            return TemporalParseResult(
                status=ParseStatus.FAILED,
                root=second.root,
                expression=second.expression,
                diagnostics=second.diagnostics + (diag,),
                tokens=second.tokens,
                artifact=second.artifact,
                printed=printed,
                profile=self.profile,
            )
        return TemporalParseResult(
            status=ParseStatus.OK,
            root=second.root,
            expression=second.expression,
            diagnostics=second.diagnostics,
            tokens=second.tokens,
            artifact=second.artifact,
            printed=printed,
            profile=self.profile,
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_temporal(
    text: str,
    profile: TraceSemanticsProfile,
    *,
    document_id: str = "doc:temporal:1",
    expression_id: str = "expr:temporal:1",
    limits: ParseLimits | None = None,
    print_style: str = PrintStyle.ASCII,
    propositions: Sequence[str] | None = None,
) -> TemporalParseResult:
    """Parse *text* as unified temporal syntax under *profile*."""

    syntax = TemporalSyntax(
        profile, print_style=print_style, propositions=propositions
    )
    return syntax.parse_text(
        text,
        document_id=document_id,
        expression_id=expression_id,
        limits=limits,
    )


def print_temporal(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    """Print *node* in canonical temporal notation."""

    return TemporalPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: TraceSemanticsProfile,
    *,
    style: str = PrintStyle.ASCII,
    propositions: Sequence[str] | None = None,
) -> TemporalParseResult:
    """Parse/print/parse round-trip with alpha-equivalence check."""

    return TemporalSyntax(
        profile, print_style=style, propositions=propositions
    ).round_trip(text)


__all__ = [
    "CODE_AMBIGUOUS_TEMPORAL",
    "CODE_EMPTY_INPUT",
    "CODE_INVALID_INTERVAL",
    "CODE_LEXER_ERROR",
    "CODE_MISSING_INTERVAL",
    "CODE_PARSE_DEPTH",
    "CODE_PATH_FORBIDDEN",
    "CODE_PATH_REQUIRED",
    "CODE_PAST_FORBIDDEN",
    "CODE_PROFILE_MISMATCH",
    "CODE_ROUND_TRIP",
    "CODE_TRAILING_INPUT",
    "CODE_UNBALANCED",
    "CODE_UNBOUNDED_INTERVAL",
    "CODE_UNEXPECTED_INTERVAL",
    "CODE_UNEXPECTED_TOKEN",
    "MetricInterval",
    "PathQuantifierKind",
    "PrintStyle",
    "RationalBound",
    "TEMPORAL_FAMILY_ID",
    "TEMPORAL_MODULE_VERSION",
    "TEMPORAL_NOTATION_ID",
    "TEMPORAL_NOTATION_VERSION",
    "TEMPORAL_PARSE_RESULT_SCHEMA_VERSION",
    "TEMPORAL_SYNTAX_INTERFACE",
    "TRACE_SEMANTICS_PROFILE_INTERFACE",
    "TRACE_SEMANTICS_PROFILE_SCHEMA_VERSION",
    "TemporalLogicKind",
    "TemporalParseError",
    "TemporalParseResult",
    "TemporalParser",
    "TemporalPrinter",
    "TemporalSyntax",
    "TimeDomain",
    "TraceModelKind",
    "TraceSemanticsProfile",
    "parse_print_parse",
    "parse_temporal",
    "print_temporal",
    "profile_ctl",
    "profile_ctl_star",
    "profile_ltl",
    "profile_ltlf",
    "profile_mtl",
    "profile_past_ltl",
    "temporal_semantic_identity",
]

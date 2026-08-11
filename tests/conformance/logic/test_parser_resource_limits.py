"""Conformance: parser resource, performance, and fail-closed budgets (LFP-041).

Acceptance:

* All parsers terminate within declared bounds
* Fail closed on exhaustion (input / token / depth / diagnostic / time / memory)
* Preserve exact spans on resource and syntax failures
* Reject silent drops of unsupported constructs
* Expose stable reduced counterexamples for resource violations

Interface: ``ParserResourcePolicy@1`` (realized by :class:`ParseLimits` plus
the hardened frontends under ``ipfs_datasets_py.logic.parsers``).

Evidence subset: depth node token input diagnostic recovery normalization
wall-time budgets parser-bomb fail-closed exact-span reduced-counterexample.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import pytest

from ipfs_datasets_py.logic.parsers.flogic import (
    CODE_INPUT_LIMIT as FLOGIC_INPUT_LIMIT,
)
from ipfs_datasets_py.logic.parsers.flogic import (
    CODE_TOKEN_LIMIT as FLOGIC_TOKEN_LIMIT,
)
from ipfs_datasets_py.logic.parsers.flogic import parse_flogic
from ipfs_datasets_py.logic.parsers.fol import (
    CODE_LEXER_ERROR,
    CODE_PARSE_DEPTH as FOL_PARSE_DEPTH,
    CODE_UNDECLARED_SYMBOL,
    parse_fol,
)
from ipfs_datasets_py.logic.parsers.rules import (
    CODE_INPUT_LIMIT as RULES_INPUT_LIMIT,
)
from ipfs_datasets_py.logic.parsers.rules import (
    CODE_TOKEN_LIMIT as RULES_TOKEN_LIMIT,
)
from ipfs_datasets_py.logic.parsers.rules import parse_rules
from ipfs_datasets_py.logic.parsers.smtlib import (
    CODE_INPUT_LIMIT as SMT_INPUT_LIMIT,
)
from ipfs_datasets_py.logic.parsers.smtlib import (
    CODE_PARSE_DEPTH as SMT_PARSE_DEPTH,
)
from ipfs_datasets_py.logic.parsers.smtlib import (
    CODE_TOKEN_LIMIT as SMT_TOKEN_LIMIT,
)
from ipfs_datasets_py.logic.parsers.smtlib import (
    CODE_UNSUPPORTED_COMMAND,
    CODE_UNKNOWN_COMMAND,
    parse_smtlib2,
    read_sexprs,
)
from ipfs_datasets_py.logic.parsers.tptp import (
    CODE_INPUT_LIMIT as TPTP_INPUT_LIMIT,
)
from ipfs_datasets_py.logic.parsers.tptp import (
    CODE_TOKEN_LIMIT as TPTP_TOKEN_LIMIT,
)
from ipfs_datasets_py.logic.parsers.tptp import parse_tptp
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_MEMORY_BYTES,
    MAX_PARSE_DEPTH,
    MAX_SOURCE_BYTES,
    MAX_TIME_MS,
    MAX_TOKENS,
    PARSE_LIMITS_SCHEMA_VERSION,
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceDocument,
    SyntaxContractError,
)
from ipfs_datasets_py.logic.syntax_core.diagnostics import (
    CODE_INPUT_LIMIT as LEXER_INPUT_LIMIT,
)
from ipfs_datasets_py.logic.syntax_core.diagnostics import (
    CODE_TOKEN_LIMIT as LEXER_TOKEN_LIMIT,
)
from ipfs_datasets_py.logic.syntax_core.diagnostics import diagnostics_have_code
from ipfs_datasets_py.logic.syntax_core.lexer import lex_document
from ipfs_datasets_py.logic.syntax_core.signatures import (
    LogicSignature,
    atomic_sort,
    many_sorted_fol_signature,
)


# ---------------------------------------------------------------------------
# Interface / policy identity (ParserResourcePolicy@1)
# ---------------------------------------------------------------------------

PARSER_RESOURCE_POLICY_INTERFACE: Final = "ParserResourcePolicy@1"
TASK_ID: Final = "LFP-041"
GOAL_ID: Final = "LFP-G080"

# Hard wall-time floor for any single bounded parse under test budgets.
# Resource-exhaustion paths must terminate well under this ceiling.
WALL_TIME_BUDGET_SECONDS: Final = 2.0

# Tight default budgets used by parser-bomb / exhaustion suites.
TIGHT_INPUT_BYTES: Final = 64
TIGHT_TOKENS: Final = 16
TIGHT_DEPTH: Final = 6
TIGHT_DIAGNOSTICS: Final = 8
TIGHT_TIME_MS: Final = 5_000
TIGHT_MEMORY_BYTES: Final = 4_194_304


@dataclass(frozen=True, slots=True)
class ParserResourcePolicy:
    """Test-side projection of ``ParserResourcePolicy@1`` over :class:`ParseLimits`.

    Production frontends consume :class:`ParseLimits` directly.  This wrapper
    documents the LFP-041 resource policy surface: every budget is a positive
    finite integer, callers may only tighten within hard ceilings, and
    exhaustion is fail-closed (never silent success).
    """

    limits: ParseLimits
    fail_closed_on_exhaustion: bool = True
    preserve_exact_spans: bool = True
    reject_silent_drops: bool = True
    expose_reduced_counterexamples: bool = True
    interface: str = PARSER_RESOURCE_POLICY_INTERFACE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID

    def __post_init__(self) -> None:
        if not isinstance(self.limits, ParseLimits):
            raise TypeError("limits must be a ParseLimits instance")
        if self.interface != PARSER_RESOURCE_POLICY_INTERFACE:
            raise ValueError(
                f"unsupported ParserResourcePolicy interface {self.interface!r}"
            )
        if not all(
            (
                self.fail_closed_on_exhaustion,
                self.preserve_exact_spans,
                self.reject_silent_drops,
                self.expose_reduced_counterexamples,
            )
        ):
            raise ValueError(
                "ParserResourcePolicy@1 requires fail-closed exhaustion, exact "
                "spans, silent-drop rejection, and reduced counterexamples"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "expose_reduced_counterexamples": self.expose_reduced_counterexamples,
            "fail_closed_on_exhaustion": self.fail_closed_on_exhaustion,
            "goal_id": self.goal_id,
            "interface": self.interface,
            "limits": self.limits.to_dict(),
            "preserve_exact_spans": self.preserve_exact_spans,
            "reject_silent_drops": self.reject_silent_drops,
            "task_id": self.task_id,
        }

    @classmethod
    def default_tight(cls) -> "ParserResourcePolicy":
        return cls(
            limits=ParseLimits(
                max_input_bytes=TIGHT_INPUT_BYTES,
                max_tokens=TIGHT_TOKENS,
                max_depth=TIGHT_DEPTH,
                max_diagnostics=TIGHT_DIAGNOSTICS,
                max_ambiguities=4,
                max_time_ms=TIGHT_TIME_MS,
                max_memory_bytes=TIGHT_MEMORY_BYTES,
            )
        )


DEFAULT_PARSER_RESOURCE_POLICY: Final = ParserResourcePolicy.default_tight()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fol_signature() -> LogicSignature:
    person = atomic_sort("Person")
    return many_sorted_fol_signature(
        "sig:resource:fol:1",
        sorts=(person,),
        constants=(("alice", person), ("bob", person)),
        functions=(("father", (person,), person),),
        predicates=(
            ("Human", (person,)),
            ("Knows", (person, person)),
            ("Rains", ()),
        ),
        family="first_order",
        profile="many_sorted",
    )


def _codes_of(diagnostics: Sequence[Any]) -> tuple[str, ...]:
    return tuple(str(item.code) for item in diagnostics)


def _primary_code(diagnostics: Sequence[Any]) -> str:
    assert diagnostics, "expected at least one diagnostic for fail-closed path"
    errors = [item for item in diagnostics if getattr(item, "is_error", True)]
    chosen = errors[0] if errors else diagnostics[0]
    return str(chosen.code)


def _has_resource_code(
    diagnostics: Sequence[Any],
    *codes: str,
    lexer_codes: Sequence[str] = (),
) -> bool:
    """Match family codes or FOL-promoted lexer codes (metadata.lexer_code)."""

    wanted = set(codes)
    lexer_wanted = set(lexer_codes)
    for item in diagnostics:
        if item.code in wanted:
            return True
        meta = getattr(item, "metadata", None) or {}
        if isinstance(meta, Mapping):
            lexer_code = meta.get("lexer_code")
            if lexer_code in wanted or lexer_code in lexer_wanted:
                return True
            if item.code == CODE_LEXER_ERROR and lexer_code in lexer_wanted:
                return True
    return False


def _assert_fail_closed(ok: bool, status: ParseStatus | None, diagnostics: Sequence[Any]) -> None:
    assert ok is False
    assert diagnostics, "fail-closed path must emit at least one diagnostic"
    if status is not None:
        assert status in {
            ParseStatus.FAILED,
            ParseStatus.REJECTED,
            ParseStatus.RECOVERED,
        }


def _assert_exact_span(
    diagnostics: Sequence[Any],
    source: str,
    *,
    document_id: str = "doc:span",
) -> None:
    document = SourceDocument.from_text(document_id, source, encoding="utf-8")
    ranged = [item for item in diagnostics if getattr(item, "range", None) is not None]
    assert ranged, "resource/syntax failures must carry exact source ranges"
    for item in ranged:
        item.validate_against(document)
        assert 0 <= item.range.start <= item.range.end <= document.byte_length


def _stable_digest(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        import json

        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _reduce_counterexample(
    source: str,
    oracle: Callable[[str], tuple[bool, str]],
    *,
    max_steps: int = 64,
) -> tuple[str, str]:
    """Delta-debug style reducer: shrink *source* while the oracle still fails.

    Returns ``(reduced_source, failure_code)``.  Reduction is deterministic:
    prefer removing a trailing half, then a leading half, then single chars.
    """

    fails, code = oracle(source)
    assert fails, "reducer requires a failing source"
    current = source
    current_code = code
    steps = 0
    changed = True
    while changed and steps < max_steps and len(current) > 1:
        changed = False
        steps += 1
        # Half deletions (binary chop style).
        for start, end in (
            (len(current) // 2, len(current)),
            (0, len(current) // 2),
        ):
            if end - start <= 0:
                continue
            candidate = current[:start] + current[end:]
            if not candidate or candidate == current:
                continue
            fails_c, code_c = oracle(candidate)
            if fails_c and code_c == current_code:
                current = candidate
                current_code = code_c
                changed = True
                break
        if changed:
            continue
        # Single-character deletions left-to-right.
        for index in range(len(current)):
            candidate = current[:index] + current[index + 1 :]
            if not candidate:
                continue
            fails_c, code_c = oracle(candidate)
            if fails_c and code_c == current_code:
                current = candidate
                current_code = code_c
                changed = True
                break
    return current, current_code


def _timed(callable_: Callable[[], Any], *, budget: float = WALL_TIME_BUDGET_SECONDS) -> Any:
    start = time.perf_counter()
    result = callable_()
    elapsed = time.perf_counter() - start
    assert elapsed < budget, f"parse exceeded wall-time budget {budget}s (took {elapsed:.3f}s)"
    return result


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_parser_resource_policy_interface_identity() -> None:
    policy = DEFAULT_PARSER_RESOURCE_POLICY
    assert policy.interface == PARSER_RESOURCE_POLICY_INTERFACE
    assert policy.interface == "ParserResourcePolicy@1"
    assert policy.task_id == TASK_ID == "LFP-041"
    assert policy.goal_id == GOAL_ID == "LFP-G080"
    payload = policy.to_dict()
    assert payload["interface"] == "ParserResourcePolicy@1"
    assert payload["fail_closed_on_exhaustion"] is True
    assert payload["preserve_exact_spans"] is True
    assert payload["reject_silent_drops"] is True
    assert payload["expose_reduced_counterexamples"] is True
    limits = policy.limits
    assert limits.schema_version == PARSE_LIMITS_SCHEMA_VERSION
    assert 0 < limits.max_input_bytes <= MAX_SOURCE_BYTES
    assert 0 < limits.max_tokens <= MAX_TOKENS
    assert 0 < limits.max_depth <= MAX_PARSE_DEPTH
    assert 0 < limits.max_time_ms <= MAX_TIME_MS
    assert 0 < limits.max_memory_bytes <= MAX_MEMORY_BYTES


def test_parse_limits_reject_unbounded_and_over_ceiling() -> None:
    for field_name in (
        "max_input_bytes",
        "max_tokens",
        "max_depth",
        "max_diagnostics",
        "max_time_ms",
        "max_memory_bytes",
    ):
        with pytest.raises(SyntaxContractError):
            ParseLimits(**{field_name: 0})
        with pytest.raises(SyntaxContractError):
            ParseLimits(**{field_name: -1})
    with pytest.raises(SyntaxContractError):
        ParseLimits(max_input_bytes=MAX_SOURCE_BYTES + 1)
    with pytest.raises(SyntaxContractError):
        ParseLimits(max_tokens=MAX_TOKENS + 1)
    with pytest.raises(SyntaxContractError):
        ParseLimits(max_depth=MAX_PARSE_DEPTH + 1)
    with pytest.raises(SyntaxContractError):
        ParseLimits(max_time_ms=MAX_TIME_MS + 1)
    with pytest.raises(SyntaxContractError):
        ParseLimits(max_memory_bytes=MAX_MEMORY_BYTES + 1)


def test_parse_limits_round_trip_is_deterministic() -> None:
    limits = ParseLimits(
        max_input_bytes=128,
        max_tokens=32,
        max_depth=8,
        max_diagnostics=16,
        max_time_ms=1_000,
        max_memory_bytes=1_048_576,
    )
    restored = ParseLimits.from_dict(limits.to_dict())
    assert restored == limits
    assert _stable_digest(limits.to_dict()) == _stable_digest(restored.to_dict())


# ---------------------------------------------------------------------------
# Input / token / depth exhaustion (multi-frontend)
# ---------------------------------------------------------------------------


def test_lexer_input_and_token_limits_fail_closed() -> None:
    text = "a b c d e f g h i j k l m n o p"
    # Input limit.
    document = SourceDocument.from_text("doc:lex:in", text)
    limits_in = ParseLimits(max_input_bytes=8, max_tokens=64, max_depth=16)
    result_in = _timed(lambda: lex_document(document, mode=ParseMode.STRICT, limits=limits_in))
    assert result_in.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert diagnostics_have_code(result_in.diagnostics, LEXER_INPUT_LIMIT)
    # Token limit.
    limits_tok = ParseLimits(max_input_bytes=4096, max_tokens=4, max_depth=16)
    result_tok = _timed(lambda: lex_document(document, mode=ParseMode.STRICT, limits=limits_tok))
    assert result_tok.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert diagnostics_have_code(result_tok.diagnostics, LEXER_TOKEN_LIMIT)
    assert len(result_tok.tokens) <= limits_tok.max_tokens


def test_smtlib_input_token_depth_limits_fail_closed_with_spans() -> None:
    # Input
    text_in = "(assert true)\n" * 40
    forms, diags = _timed(
        lambda: read_sexprs(
            text_in,
            limits=ParseLimits(max_input_bytes=32, max_tokens=256, max_depth=32),
        )
    )
    assert forms == ()
    assert any(item.code == SMT_INPUT_LIMIT for item in diags)
    _assert_exact_span(diags, text_in, document_id="doc:smt:in")

    # Token
    text_tok = "(assert " + " ".join(["true"] * 40) + ")"
    forms_t, diags_t = _timed(
        lambda: read_sexprs(
            text_tok,
            limits=ParseLimits(max_input_bytes=4096, max_tokens=10, max_depth=64),
        )
    )
    assert forms_t == ()
    assert any(item.code == SMT_TOKEN_LIMIT for item in diags_t)
    _assert_exact_span(diags_t, text_tok, document_id="doc:smt:tok")

    # Depth (parser bomb shape)
    text_d = "(" * 30 + "true" + ")" * 30
    forms_d, diags_d = _timed(
        lambda: read_sexprs(
            text_d,
            limits=ParseLimits(max_input_bytes=4096, max_tokens=512, max_depth=5),
        )
    )
    assert forms_d == ()
    assert any(item.code == SMT_PARSE_DEPTH for item in diags_d)
    _assert_exact_span(diags_d, text_d, document_id="doc:smt:depth")


def test_tptp_rules_flogic_input_and_token_limits() -> None:
    # TPTP
    tptp_text = "fof(a, axiom, p).\n" * 30
    tptp = _timed(
        lambda: parse_tptp(
            tptp_text,
            limits=ParseLimits(max_input_bytes=32, max_tokens=64, max_depth=16),
        )
    )
    _assert_fail_closed(tptp.ok, tptp.status, tptp.errors)
    assert any(item.code == TPTP_INPUT_LIMIT for item in tptp.errors)

    tptp_tok = parse_tptp(
        "fof(a, axiom, " + " & ".join(["p"] * 40) + ").",
        limits=ParseLimits(max_input_bytes=4096, max_tokens=10, max_depth=64),
    )
    _assert_fail_closed(tptp_tok.ok, tptp_tok.status, tptp_tok.errors)
    assert any(item.code == TPTP_TOKEN_LIMIT for item in tptp_tok.errors)

    # Rules
    rules_text = "p(a).\n" * 30
    rules = _timed(
        lambda: parse_rules(
            rules_text,
            limits=ParseLimits(max_input_bytes=16, max_tokens=64, max_depth=16),
        )
    )
    _assert_fail_closed(rules.ok, rules.status, rules.errors)
    assert any(item.code == RULES_INPUT_LIMIT for item in rules.errors)

    rules_tok = parse_rules(
        "p(" + ", ".join(f"a{i}" for i in range(40)) + ").",
        limits=ParseLimits(max_input_bytes=4096, max_tokens=8, max_depth=64),
    )
    _assert_fail_closed(rules_tok.ok, rules_tok.status, rules_tok.errors)
    assert any(item.code == RULES_TOKEN_LIMIT for item in rules_tok.errors)

    # F-logic
    flogic_text = "Dog :: Animal.\n" * 30
    flogic = _timed(
        lambda: parse_flogic(
            flogic_text,
            limits=ParseLimits(max_input_bytes=32, max_tokens=64, max_depth=16),
        )
    )
    _assert_fail_closed(flogic.ok, flogic.status, flogic.errors)
    assert any(item.code == FLOGIC_INPUT_LIMIT for item in flogic.errors)

    flogic_tok = parse_flogic(
        "obj[" + ", ".join(f"m{i} -> v{i}" for i in range(30)) + "].",
        limits=ParseLimits(max_input_bytes=4096, max_tokens=10, max_depth=64),
    )
    _assert_fail_closed(flogic_tok.ok, flogic_tok.status, flogic_tok.errors)
    assert any(item.code == FLOGIC_TOKEN_LIMIT for item in flogic_tok.errors)


def test_fol_depth_and_lexer_promoted_limits_fail_closed() -> None:
    sig = _fol_signature()
    # Depth via nested formula parentheses / quantifiers.
    deep = "(" * 20 + "Rains" + ")" * 20
    result = _timed(
        lambda: parse_fol(
            deep,
            sig,
            limits=ParseLimits(max_input_bytes=4096, max_tokens=256, max_depth=4),
        )
    )
    _assert_fail_closed(result.ok, result.status, result.errors)
    assert any(item.code == FOL_PARSE_DEPTH for item in result.errors)
    _assert_exact_span(result.errors, deep, document_id="doc:fol:depth")

    # Token exhaustion is promoted through the FOL lexer bridge.
    tokens_src = " ".join(["Rains"] * 40)
    tok = _timed(
        lambda: parse_fol(
            tokens_src,
            sig,
            limits=ParseLimits(max_input_bytes=4096, max_tokens=6, max_depth=32),
        )
    )
    _assert_fail_closed(tok.ok, tok.status, tok.errors)
    assert _has_resource_code(
        tok.errors,
        CODE_LEXER_ERROR,
        lexer_codes=(LEXER_TOKEN_LIMIT,),
    ) or any("token" in item.message.lower() for item in tok.errors)

    # Input exhaustion.
    big = "Rains and " * 40 + "Rains"
    inp = parse_fol(
        big,
        sig,
        limits=ParseLimits(max_input_bytes=16, max_tokens=256, max_depth=32),
    )
    _assert_fail_closed(inp.ok, inp.status, inp.errors)
    assert _has_resource_code(
        inp.errors,
        CODE_LEXER_ERROR,
        lexer_codes=(LEXER_INPUT_LIMIT,),
    ) or any("input" in item.message.lower() or "byte" in item.message.lower() for item in inp.errors)


# ---------------------------------------------------------------------------
# Parser bombs terminate under declared budgets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,source,parse",
    [
        (
            "smt-nest",
            "(" * 80 + "true" + ")" * 80,
            lambda s: parse_smtlib2(
                s,
                limits=ParseLimits(
                    max_input_bytes=4096,
                    max_tokens=256,
                    max_depth=8,
                    max_time_ms=TIGHT_TIME_MS,
                ),
            ),
        ),
        (
            "smt-wide",
            "(assert (and " + " ".join(["true"] * 120) + "))",
            lambda s: parse_smtlib2(
                s,
                limits=ParseLimits(
                    max_input_bytes=8192,
                    max_tokens=32,
                    max_depth=64,
                    max_time_ms=TIGHT_TIME_MS,
                ),
            ),
        ),
        (
            "tptp-wide",
            "fof(a, axiom, " + " & ".join(["p"] * 80) + ").",
            lambda s: parse_tptp(
                s,
                limits=ParseLimits(
                    max_input_bytes=8192,
                    max_tokens=24,
                    max_depth=32,
                    max_time_ms=TIGHT_TIME_MS,
                ),
            ),
        ),
        (
            "rules-wide",
            "p(" + ", ".join(f"x{i}" for i in range(80)) + ").",
            lambda s: parse_rules(
                s,
                limits=ParseLimits(
                    max_input_bytes=8192,
                    max_tokens=16,
                    max_depth=32,
                    max_time_ms=TIGHT_TIME_MS,
                ),
            ),
        ),
        (
            "fol-nest",
            "(" * 60 + "Rains" + ")" * 60,
            lambda s: parse_fol(
                s,
                _fol_signature(),
                limits=ParseLimits(
                    max_input_bytes=4096,
                    max_tokens=256,
                    max_depth=8,
                    max_time_ms=TIGHT_TIME_MS,
                ),
            ),
        ),
    ],
)
def test_parser_bombs_terminate_fail_closed(
    label: str,
    source: str,
    parse: Callable[[str], Any],
) -> None:
    result = _timed(lambda: parse(source), budget=WALL_TIME_BUDGET_SECONDS)
    assert not result.ok, f"{label} must not accept a resource bomb"
    assert result.errors, f"{label} must emit diagnostics (no silent drop)"
    # Deterministic re-run under identical budgets.
    again = parse(source)
    assert not again.ok
    assert _codes_of(result.errors) == _codes_of(again.errors)


# ---------------------------------------------------------------------------
# Silent-drop rejection
# ---------------------------------------------------------------------------


def test_unsupported_and_unknown_smt_commands_are_not_silent_drops() -> None:
    # Unknown command must surface an explicit diagnostic; never OK with empty diags.
    unknown = parse_smtlib2("(set-logic QF_UF)\n(totally-made-up-cmd x)\n(check-sat)\n")
    assert not unknown.ok
    assert unknown.errors
    assert any(
        item.code in {CODE_UNKNOWN_COMMAND, CODE_UNSUPPORTED_COMMAND}
        or "unknown" in item.message.lower()
        or "unsupported" in item.message.lower()
        for item in unknown.errors
    )

    # Explicit unsupported command in the closed reject set (get-proof).
    unsupported = parse_smtlib2(
        "(set-logic QF_UF)\n(get-proof)\n(check-sat)\n"
    )
    assert not unsupported.ok
    assert unsupported.errors
    assert any(
        item.code in {CODE_UNSUPPORTED_COMMAND, CODE_UNKNOWN_COMMAND}
        or "unsupported" in item.message.lower()
        or "unknown" in item.message.lower()
        for item in unsupported.errors
    )


def test_fol_undeclared_symbol_is_not_a_silent_drop() -> None:
    source = "Ghost(alice)"
    result = parse_fol(source, _fol_signature())
    assert not result.ok
    assert any(item.code == CODE_UNDECLARED_SYMBOL for item in result.errors)
    _assert_exact_span(result.errors, source, document_id="doc:fol:drop")
    diag = next(item for item in result.errors if item.code == CODE_UNDECLARED_SYMBOL)
    document = SourceDocument.from_text("doc:fol:drop", source)
    sliced = document.content[diag.range.start : diag.range.end].decode("utf-8")
    assert "Ghost" in sliced


# ---------------------------------------------------------------------------
# Exact spans + diagnostic budgets
# ---------------------------------------------------------------------------


def test_resource_failure_spans_validate_against_source() -> None:
    text = "(assert " + " ".join(["true"] * 20) + ")"
    limits = ParseLimits(max_input_bytes=4096, max_tokens=8, max_depth=32)
    result = parse_smtlib2(text, limits=limits)
    assert not result.ok
    _assert_exact_span(result.errors, text, document_id="doc:span:smt")


def test_diagnostic_budget_is_finite_and_capped() -> None:
    # Many unknown characters under a tiny diagnostic budget.
    document = SourceDocument.from_text("doc:diag", "` ` ` ` ` ` ` ` ` `")
    limits = ParseLimits(
        max_input_bytes=4096,
        max_tokens=64,
        max_depth=16,
        max_diagnostics=3,
    )
    result = lex_document(document, mode=ParseMode.RECOVERY, limits=limits)
    # Either recovery or failure is acceptable; diagnostic count must respect budget.
    assert len(result.diagnostics) <= limits.max_diagnostics
    assert result.status in {
        ParseStatus.RECOVERED,
        ParseStatus.FAILED,
        ParseStatus.REJECTED,
    }


# ---------------------------------------------------------------------------
# Wall-time / memory policy surfaces
# ---------------------------------------------------------------------------


def test_wall_time_and_memory_budgets_are_declared_finite() -> None:
    policy = ParserResourcePolicy.default_tight()
    assert policy.limits.max_time_ms == TIGHT_TIME_MS
    assert policy.limits.max_memory_bytes == TIGHT_MEMORY_BYTES
    # Bomb under the declared policy must finish inside the wall budget.
    bomb = "(" * 100 + "true" + ")" * 100
    start = time.perf_counter()
    result = parse_smtlib2(bomb, limits=policy.limits)
    elapsed = time.perf_counter() - start
    assert not result.ok
    assert elapsed < WALL_TIME_BUDGET_SECONDS
    # max_time_ms itself is a positive finite bound (policy contract).
    assert 0 < policy.limits.max_time_ms <= MAX_TIME_MS


def test_normalization_budget_preserves_fail_closed_identity() -> None:
    """Re-parsing the same bomb under identical limits yields identical codes."""

    bomb = "fof(a, axiom, " + " & ".join(["q"] * 50) + ")."
    limits = ParseLimits(max_input_bytes=8192, max_tokens=20, max_depth=32)
    first = parse_tptp(bomb, limits=limits)
    second = parse_tptp(bomb, limits=limits)
    assert not first.ok and not second.ok
    assert _codes_of(first.errors) == _codes_of(second.errors)
    digest = _stable_digest(_codes_of(first.errors))
    assert digest == _stable_digest(_codes_of(second.errors))


# ---------------------------------------------------------------------------
# Stable reduced counterexamples
# ---------------------------------------------------------------------------


def test_reduced_counterexample_for_smt_depth_is_stable() -> None:
    bomb = "(" * 40 + "true" + ")" * 40
    limits = ParseLimits(max_input_bytes=4096, max_tokens=512, max_depth=4)

    def oracle(text: str) -> tuple[bool, str]:
        forms, diags = read_sexprs(text, limits=limits)
        if forms == () and diags:
            return True, _primary_code(diags)
        result = parse_smtlib2(text, limits=limits)
        if not result.ok and result.errors:
            return True, _primary_code(result.errors)
        return False, "ok"

    reduced, code = _reduce_counterexample(bomb, oracle)
    assert code  # non-empty stable failure code
    # Reduced form still fails with the same code.
    fails, code2 = oracle(reduced)
    assert fails and code2 == code
    # Deterministic reduction.
    reduced_again, code_again = _reduce_counterexample(bomb, oracle)
    assert reduced_again == reduced
    assert code_again == code
    # Reduced is not larger than the original bomb.
    assert len(reduced) <= len(bomb)
    # Counterexample digest is stable.
    digest = _stable_digest({"code": code, "reduced": reduced})
    assert digest == _stable_digest({"code": code_again, "reduced": reduced_again})


def test_reduced_counterexample_for_token_limit_is_stable() -> None:
    source = "p(" + ", ".join(f"a{i}" for i in range(30)) + ")."
    limits = ParseLimits(max_input_bytes=4096, max_tokens=8, max_depth=32)

    def oracle(text: str) -> tuple[bool, str]:
        result = parse_rules(text, limits=limits)
        if not result.ok and result.errors:
            return True, _primary_code(result.errors)
        return False, "ok"

    fails0, code0 = oracle(source)
    assert fails0
    assert code0 == RULES_TOKEN_LIMIT or "token" in code0
    reduced, code = _reduce_counterexample(source, oracle)
    assert code == code0
    fails, code2 = oracle(reduced)
    assert fails and code2 == code
    reduced2, code3 = _reduce_counterexample(source, oracle)
    assert (reduced2, code3) == (reduced, code)


def test_multi_frontend_resource_matrix_terminates() -> None:
    """Cross-frontend matrix: every admitted frontend fails closed under tight budgets."""

    policy = ParserResourcePolicy.default_tight()
    cases: list[tuple[str, Callable[[], Any]]] = [
        (
            "smtlib",
            lambda: parse_smtlib2(
                "(" * 20 + "true" + ")" * 20, limits=policy.limits
            ),
        ),
        (
            "tptp",
            lambda: parse_tptp(
                "fof(a, axiom, " + " & ".join(["p"] * 20) + ").",
                limits=policy.limits,
            ),
        ),
        (
            "rules",
            lambda: parse_rules(
                "p(" + ", ".join(f"x{i}" for i in range(20)) + ").",
                limits=policy.limits,
            ),
        ),
        (
            "flogic",
            lambda: parse_flogic(
                "obj[" + ", ".join(f"m{i} -> v{i}" for i in range(20)) + "].",
                limits=policy.limits,
            ),
        ),
        (
            "fol",
            lambda: parse_fol(
                "(" * 20 + "Rains" + ")" * 20,
                _fol_signature(),
                limits=policy.limits,
            ),
        ),
    ]
    receipts: list[dict[str, Any]] = []
    for name, runner in cases:
        start = time.perf_counter()
        result = runner()
        elapsed = time.perf_counter() - start
        assert elapsed < WALL_TIME_BUDGET_SECONDS, name
        assert not result.ok, name
        assert result.errors, name
        receipts.append(
            {
                "codes": list(_codes_of(result.errors)),
                "elapsed_ms": int(elapsed * 1000),
                "frontend": name,
                "ok": False,
            }
        )
    # Matrix receipt is content-addressable / stable under re-run of codes.
    digest = _stable_digest([item["codes"] for item in receipts])
    assert len(digest) == 64

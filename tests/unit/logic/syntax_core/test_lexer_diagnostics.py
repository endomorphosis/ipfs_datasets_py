"""Unit tests for bounded lexing, diagnostics, and source maps (LFP-014)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.syntax_core.contracts import (
    DiagnosticSeverity,
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SyntaxContractError,
    TokenKind,
)
from ipfs_datasets_py.logic.syntax_core.diagnostics import (
    CODE_COMMENT_DEPTH,
    CODE_TOKEN_LIMIT,
    CODE_UNKNOWN_CHARACTER,
    CODE_UNTERMINATED_COMMENT,
    CODE_UNTERMINATED_STRING,
    LOGIC_DIAGNOSTIC_INTERFACE,
    LOGIC_SOURCE_MAP_INTERFACE,
    LogicDiagnostic,
    LogicSourceMap,
    build_logic_source_map,
    build_token_source_map,
    diagnostics_have_code,
    make_diagnostic,
)
from ipfs_datasets_py.logic.syntax_core.lexer import (
    BOUNDED_LEXER_INTERFACE,
    BoundedLexer,
    LexResult,
    lex_document,
)


def _doc(text: str, document_id: str = "doc:lex:1") -> SourceDocument:
    return SourceDocument.from_text(document_id, text, encoding="utf-8")


def _kinds(result: LexResult) -> list[str]:
    return [token.kind for token in result.tokens]


def _lexemes(result: LexResult, *, include_eof: bool = False) -> list[str]:
    items = []
    for token in result.tokens:
        if token.kind == TokenKind.EOF.value and not include_eof:
            continue
        items.append(token.lexeme)
    return items


def _assert_lexemes_have_no_surrounding_whitespace(result: LexResult) -> None:
    for token in result.tokens:
        if token.lexeme:
            assert token.lexeme == token.lexeme.strip(), (
                f"token {token.token_id} lexeme has surrounding whitespace: "
                f"{token.lexeme!r}"
            )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_lex_propositional_formula_strict_ok() -> None:
    document = _doc("P & Q -> R")
    result = lex_document(document, mode=ParseMode.STRICT)
    _assert_lexemes_have_no_surrounding_whitespace(result)
    assert result.status is ParseStatus.OK
    assert result.diagnostics == ()
    assert _lexemes(result) == ["P", "&", "Q", "->", "R"]
    assert _kinds(result) == [
        TokenKind.IDENTIFIER.value,
        TokenKind.OPERATOR.value,
        TokenKind.IDENTIFIER.value,
        TokenKind.OPERATOR.value,
        TokenKind.IDENTIFIER.value,
        TokenKind.EOF.value,
    ]
    # Whitespace is trivia on following tokens, never lexeme content.
    amp = result.tokens[1]
    assert amp.lexeme == "&"
    assert amp.leading_trivia
    assert all(isinstance(item, SourceRange) for item in amp.leading_trivia)


def test_lex_multi_char_operators() -> None:
    document = _doc("A -> B => C <-> D <=> E == F != G <= H >= I && J || K")
    result = lex_document(document, mode=ParseMode.STRICT)
    _assert_lexemes_have_no_surrounding_whitespace(result)
    assert result.status is ParseStatus.OK
    ops = [token.lexeme for token in result.tokens if token.kind == TokenKind.OPERATOR.value]
    assert ops == ["->", "=>", "<->", "<=>", "==", "!=", "<=", ">=", "&&", "||"]


def test_lex_numbers_strings_comments() -> None:
    text = '42 3.14 "hello world" // line comment\n/* block */ # hash'
    document = _doc(text)
    result = lex_document(document, mode=ParseMode.STRICT)
    _assert_lexemes_have_no_surrounding_whitespace(result)
    assert result.status is ParseStatus.OK
    kinds = [token.kind for token in result.tokens if token.kind != TokenKind.EOF.value]
    assert TokenKind.NUMBER.value in kinds
    assert TokenKind.STRING.value in kinds
    assert kinds.count(TokenKind.COMMENT.value) >= 2
    numbers = [t.lexeme for t in result.tokens if t.kind == TokenKind.NUMBER.value]
    assert "42" in numbers
    assert "3.14" in numbers
    strings = [t.lexeme for t in result.tokens if t.kind == TokenKind.STRING.value]
    assert strings == ['"hello world"']
    comments = [t.lexeme for t in result.tokens if t.kind == TokenKind.COMMENT.value]
    assert any(item.startswith("//") for item in comments)
    assert any(item.startswith("/*") and item.endswith("*/") for item in comments)
    assert any(item.startswith("#") for item in comments)


def test_lex_unicode_operators_and_keywords() -> None:
    document = _doc("∀x. P(x) ∧ Q(x) → ¬R ∨ true")
    result = lex_document(document, mode=ParseMode.STRICT)
    _assert_lexemes_have_no_surrounding_whitespace(result)
    assert result.status is ParseStatus.OK
    lexemes = _lexemes(result)
    assert "∀" in lexemes
    assert "∧" in lexemes
    assert "→" in lexemes
    assert "¬" in lexemes
    assert "∨" in lexemes
    assert "true" in lexemes
    keyword_tokens = [t for t in result.tokens if t.kind == TokenKind.KEYWORD.value]
    assert any(t.lexeme == "true" for t in keyword_tokens)
    op_lexemes = {t.lexeme for t in result.tokens if t.kind == TokenKind.OPERATOR.value}
    assert {"∀", "∧", "→", "¬", "∨"} <= op_lexemes


def test_lexing_is_deterministic() -> None:
    document = _doc("P & Q -> (R | S)  // note\n")
    first = lex_document(document, mode=ParseMode.STRICT)
    second = lex_document(document, mode=ParseMode.STRICT)
    assert first.tokens == second.tokens
    assert first.diagnostics == second.diagnostics
    assert first.source_map == second.source_map
    assert first.status == second.status
    _assert_lexemes_have_no_surrounding_whitespace(first)


def test_nested_block_comments_within_depth() -> None:
    document = _doc("/* outer /* inner */ still */ P")
    limits = ParseLimits(max_depth=8, max_tokens=64, max_input_bytes=4096)
    result = lex_document(document, mode=ParseMode.STRICT, limits=limits)
    _assert_lexemes_have_no_surrounding_whitespace(result)
    assert result.status is ParseStatus.OK
    comments = [t for t in result.tokens if t.kind == TokenKind.COMMENT.value]
    assert len(comments) == 1
    assert comments[0].lexeme.startswith("/*")
    assert comments[0].lexeme.endswith("*/")
    assert "inner" in comments[0].lexeme
    assert _lexemes(result)[-1] == "P"


def test_nested_block_comments_exceeding_depth_fails() -> None:
    document = _doc("/* /* /* */ */ */")
    limits = ParseLimits(max_depth=2, max_tokens=64, max_input_bytes=4096)
    result = lex_document(document, mode=ParseMode.STRICT, limits=limits)
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert diagnostics_have_code(result.diagnostics, CODE_COMMENT_DEPTH)


def test_token_limit_terminates_deterministically() -> None:
    document = _doc("a b c d e f g h")
    limits = ParseLimits(max_tokens=3, max_input_bytes=4096, max_depth=8)
    first = lex_document(document, mode=ParseMode.STRICT, limits=limits)
    second = lex_document(document, mode=ParseMode.STRICT, limits=limits)
    assert first.tokens == second.tokens
    assert first.diagnostics == second.diagnostics
    assert diagnostics_have_code(first.diagnostics, CODE_TOKEN_LIMIT)
    assert first.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    # Total token count (including EOF) never exceeds the configured bound.
    assert len(first.tokens) <= limits.max_tokens
    non_eof = [t for t in first.tokens if t.kind != TokenKind.EOF.value]
    assert len(non_eof) <= max(0, limits.max_tokens - 1)
    assert first.tokens[-1].kind == TokenKind.EOF.value
    _assert_lexemes_have_no_surrounding_whitespace(first)


def test_unknown_character_recovery_preserves_error_node() -> None:
    # Backtick is not a recognized operator/symbol in the baseline lexer.
    document = _doc("P ` Q")
    result = lex_document(document, mode=ParseMode.RECOVERY)
    _assert_lexemes_have_no_surrounding_whitespace(result)
    assert result.status is ParseStatus.RECOVERED
    assert diagnostics_have_code(result.diagnostics, CODE_UNKNOWN_CHARACTER)
    error_tokens = [t for t in result.tokens if t.kind == TokenKind.ERROR.value]
    assert len(error_tokens) == 1
    assert error_tokens[0].lexeme  # explicit error node retained
    assert error_tokens[0].lexeme == error_tokens[0].lexeme.strip()
    # Recovery continues past the unknown character.
    ids = [t.lexeme for t in result.tokens if t.kind == TokenKind.IDENTIFIER.value]
    assert ids == ["P", "Q"]


def test_unknown_character_strict_rejects() -> None:
    document = _doc("P ` Q")
    result = lex_document(document, mode=ParseMode.STRICT)
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert diagnostics_have_code(result.diagnostics, CODE_UNKNOWN_CHARACTER)
    error_tokens = [t for t in result.tokens if t.kind == TokenKind.ERROR.value]
    assert error_tokens, "strict mode still preserves an explicit error node"


def test_unterminated_string_diagnosed() -> None:
    document = _doc('"unterminated')
    result = lex_document(document, mode=ParseMode.STRICT)
    assert diagnostics_have_code(result.diagnostics, CODE_UNTERMINATED_STRING)
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}


def test_unterminated_block_comment_diagnosed() -> None:
    document = _doc("/* never closed")
    result = lex_document(document, mode=ParseMode.RECOVERY)
    assert diagnostics_have_code(result.diagnostics, CODE_UNTERMINATED_COMMENT)
    assert result.status is ParseStatus.RECOVERED


def test_whitespace_only_source_is_eof_with_trivia() -> None:
    document = _doc("   \n\t  ")
    result = lex_document(document, mode=ParseMode.STRICT)
    _assert_lexemes_have_no_surrounding_whitespace(result)
    assert result.status is ParseStatus.OK
    assert len(result.tokens) == 1
    assert result.tokens[0].kind == TokenKind.EOF.value
    assert result.tokens[0].lexeme == ""
    assert result.tokens[0].leading_trivia


def test_bounded_lexer_interface_and_class_api() -> None:
    lexer = BoundedLexer()
    assert lexer.interface == BOUNDED_LEXER_INTERFACE
    document = _doc("true")
    result = lexer.lex(document, mode=ParseMode.STRICT)
    assert isinstance(result, LexResult)
    assert result.ok
    assert result.tokens[0].kind == TokenKind.KEYWORD.value


def test_source_map_covers_tokens_and_trivia() -> None:
    document = _doc(" A ")
    result = lex_document(document, mode=ParseMode.STRICT)
    source_map = build_token_source_map(document, result.tokens)
    assert source_map.document_id == document.document_id
    assert source_map.entries
    logic_map = build_logic_source_map(document, result.tokens)
    assert logic_map.interface == LOGIC_SOURCE_MAP_INTERFACE
    assert logic_map.entries == source_map.entries


def test_logic_diagnostic_wrapper() -> None:
    diagnostic = make_diagnostic(
        diagnostic_id="diag:test:1",
        code=CODE_UNKNOWN_CHARACTER,
        message="unknown",
        severity=DiagnosticSeverity.ERROR,
        range=SourceRange(0, 1),
    )
    wrapped = LogicDiagnostic.from_syntax(diagnostic)
    assert wrapped.interface == LOGIC_DIAGNOSTIC_INTERFACE
    assert wrapped.code == CODE_UNKNOWN_CHARACTER
    assert wrapped.to_syntax() == diagnostic


def test_lexeme_contract_rejects_surrounding_whitespace_directly() -> None:
    with pytest.raises(SyntaxContractError, match="surrounding whitespace"):
        from ipfs_datasets_py.logic.syntax_core.contracts import LogicToken

        LogicToken(
            token_id="tok:bad",
            kind=TokenKind.IDENTIFIER,
            lexeme=" P",
            range=SourceRange(0, 2),
        )


def test_confusable_character_rejected() -> None:
    # U+2013 en-dash is a confusable hyphen.
    document = _doc("P \u2013 Q")
    result = lex_document(document, mode=ParseMode.STRICT)
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert result.diagnostics
    assert any("confusable" in d.code or "confusable" in d.message for d in result.diagnostics)


def test_empty_source() -> None:
    document = _doc("")
    result = lex_document(document, mode=ParseMode.STRICT)
    assert result.status is ParseStatus.OK
    assert len(result.tokens) == 1
    assert result.tokens[0].kind == TokenKind.EOF.value

"""AST text validation keeps exact historical errors and Unicode semantics."""
from __future__ import annotations

import unicodedata

import pytest

from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTIRValidationError, _text


def historical_text(value, field_name, *, allow_empty=False, no_whitespace=False, maximum=16_384):
    """Released validator, retained here to compare its ordered failure contract."""
    if type(value) is not str:
        raise ASTIRValidationError(f"{field_name} must be an exact string")
    if not allow_empty and not value:
        raise ASTIRValidationError(f"{field_name} must not be empty")
    if value != value.strip() and value:
        raise ASTIRValidationError(f"{field_name} must not contain surrounding whitespace")
    if len(value) > maximum:
        raise ASTIRValidationError(f"{field_name} exceeds {maximum} characters")
    if unicodedata.normalize("NFC", value) != value:
        raise ASTIRValidationError(f"{field_name} must be NFC-normalized")
    if any(not character.isprintable() for character in value):
        raise ASTIRValidationError(f"{field_name} contains a control character")
    if no_whitespace and any(character.isspace() for character in value):
        raise ASTIRValidationError(f"{field_name} must not contain whitespace")
    return value


def outcome(function, value, **options):
    try:
        result = function(value, "annotation", **options)
    except ASTIRValidationError as error:
        return type(error), str(error)
    return type(result), result


@pytest.mark.parametrize("text", [
    "", "ascii", "a b", "é", "e\u0301", "中文", "\U0001f600", "\U0001d11e",
    "\x00", "a\x00b", "a\nb", "a\tb", "a\x1fb", "a\x7fb", "a\x85b",
    "a\u00a0b", "a\u2000b", "a\u200bb", "a\u2028b", "a\u2029b", "a\u202eb",
    "a\u2060b", "a\ufeffb", "a\ud800b", "a\udfffb", "a\ufdd0b", "a\U0010ffffb",
    "\u0301", "a\u034fb", "é\u0300", "a\U000e0100b", " safe", "safe ",
])
@pytest.mark.parametrize("options", [
    {}, {"allow_empty": True}, {"no_whitespace": True}, {"maximum": 0},
])
def test_native_text_matches_released_unicode_validation(text, options):
    assert outcome(_text, text, **options) == outcome(historical_text, text, **options)


@pytest.mark.parametrize(("text", "options", "message"), [
    ("", {}, "annotation must not be empty"),
    (" \x00", {"maximum": 0}, "annotation must not contain surrounding whitespace"),
    ("e\u0301\x00", {"maximum": 1}, "annotation exceeds 1 characters"),
    ("e\u0301\x00", {}, "annotation must be NFC-normalized"),
    ("a\u00a0b", {"no_whitespace": True}, "annotation contains a control character"),
    ("a b", {"no_whitespace": True}, "annotation must not contain whitespace"),
])
def test_multiple_invalid_conditions_keep_first_error(text, options, message):
    with pytest.raises(ASTIRValidationError) as raised:
        _text(text, "annotation", **options)
    assert str(raised.value) == message


@pytest.mark.parametrize("value", [None, False, 1, b"ascii", ["ascii"]])
def test_wrong_types_are_rejected_before_string_operations(value):
    assert outcome(_text, value, allow_empty=True, maximum=0) == (
        ASTIRValidationError, "annotation must be an exact string")


@pytest.mark.parametrize("value", ["", "ascii", "\x00"])
def test_string_subclass_cannot_override_validation(value):
    class AdversarialString(str):
        def __bool__(self):
            pytest.fail("exact-type refusal must precede truth testing")

        def __iter__(self):
            pytest.fail("exact-type refusal must precede iteration")

        def strip(self, *args):
            pytest.fail("exact-type refusal must precede stripping")

        def isprintable(self):
            pytest.fail("exact-type refusal must precede printability dispatch")

    assert outcome(_text, AdversarialString(value), allow_empty=True) == (
        ASTIRValidationError, "annotation must be an exact string")


def test_allowed_empty_retains_identity_and_whitespace_semantics():
    assert _text("", "empty", allow_empty=True, no_whitespace=True, maximum=0) == ""
    text = "annotation " * 512 + "end"
    assert _text(text, "long") is text
    with pytest.raises(ASTIRValidationError, match="must not contain whitespace"):
        _text(text, "long", no_whitespace=True)


def test_all_unicode_codepoints_match_released_embedded_text_contract():
    # Exercise Unicode categories, normalization interactions, surrogates and
    # noncharacters through the actual ordered validator, without encoding or
    # importing an external Unicode table. Surrounding whitespace cannot hide
    # control/whitespace precedence for these embedded characters.
    for codepoint in range(0x110000):
        text = "a" + chr(codepoint) + "b"
        assert outcome(_text, text, no_whitespace=True) == outcome(
            historical_text, text, no_whitespace=True), hex(codepoint)

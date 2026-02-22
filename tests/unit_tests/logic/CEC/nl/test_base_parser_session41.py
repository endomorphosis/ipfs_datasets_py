"""
Session 41: CEC/nl/base_parser.py coverage from 48% → 80%+
and CEC/native/nl_converter.py coverage from 55% → 80%+.

Targets missing lines:
- base_parser.py: 61-62, 70, 78, 86, 90-93, 166, 177, 184-188, 219-220,
  224-227, 259, 270, 274, 307-364
- nl_converter.py: 39-41, 116, 130-132, 141, 146-148, 180-182, 208-219,
  273-282, 300-305, 308-316, 319-327, 330-344, 352, 357, 384-401, 413-423, 435-445
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.logic.CEC.nl.base_parser import BaseParser, ParseResult, get_parser
from ipfs_datasets_py.logic.CEC.nl.language_detector import Language


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _SimpleParser(BaseParser):
    """Minimal concrete parser for testing BaseParser abstract methods."""

    def __init__(self, language: str = "en", confidence_threshold: float = 0.5):
        super().__init__(language, confidence_threshold=confidence_threshold)

    def parse_impl(self, text: str) -> ParseResult:
        return ParseResult(formula=None, confidence=0.9, success=True)


class _LowConfidenceParser(BaseParser):
    """Parser that always returns low-confidence results."""

    def __init__(self):
        super().__init__("en", confidence_threshold=0.8)

    def parse_impl(self, text: str) -> ParseResult:
        return ParseResult(formula=None, confidence=0.3, success=True)


class _ExceptionParser(BaseParser):
    """Parser whose parse_impl always raises."""

    def __init__(self):
        super().__init__("en")

    def parse_impl(self, text: str) -> ParseResult:
        raise RuntimeError("parse_impl failed")


# ===========================================================================
# ParseResult
# ===========================================================================

class TestParseResultAddError:
    """Lines 61–62 — add_error sets success=False."""

    def test_add_error_marks_failed(self):
        """GIVEN success=True WHEN add_error THEN success=False."""
        r = ParseResult(success=True, confidence=0.9)
        r.add_error("oops")
        assert r.success is False
        assert "oops" in r.errors

    def test_add_multiple_errors(self):
        """GIVEN multiple errors THEN all stored."""
        r = ParseResult()
        r.add_error("first")
        r.add_error("second")
        assert len(r.errors) == 2


class TestParseResultAddWarning:
    """Line 70 — add_warning appends to warnings."""

    def test_add_warning_appended(self):
        """GIVEN fresh result WHEN add_warning THEN stored in warnings."""
        r = ParseResult(success=True)
        r.add_warning("low confidence")
        assert len(r.warnings) == 1
        assert r.warnings[0] == "low confidence"

    def test_add_warning_does_not_affect_success(self):
        """GIVEN success=True WHEN add_warning THEN success unchanged."""
        r = ParseResult(success=True)
        r.add_warning("just a warning")
        assert r.success is True


class TestParseResultHasErrors:
    """Line 78 — has_errors returns True iff errors present."""

    def test_has_errors_empty(self):
        """GIVEN no errors THEN False."""
        assert ParseResult().has_errors() is False

    def test_has_errors_with_error(self):
        """GIVEN one error THEN True."""
        r = ParseResult()
        r.add_error("err")
        assert r.has_errors() is True


class TestParseResultHasWarnings:
    """Line 86 — has_warnings returns True iff warnings present."""

    def test_has_warnings_empty(self):
        """GIVEN no warnings THEN False."""
        assert ParseResult().has_warnings() is False

    def test_has_warnings_with_warning(self):
        """GIVEN one warning THEN True."""
        r = ParseResult()
        r.add_warning("warn")
        assert r.has_warnings() is True


class TestParseResultStrRepr:
    """Lines 90–93 — __str__ branches."""

    def test_str_success(self):
        """GIVEN success=True THEN str includes confidence."""
        r = ParseResult(success=True, confidence=0.95)
        s = str(r)
        assert "success=True" in s
        assert "0.95" in s

    def test_str_failure(self):
        """GIVEN success=False THEN str includes error count."""
        r = ParseResult()
        r.add_error("e1")
        r.add_error("e2")
        s = str(r)
        assert "success=False" in s
        assert "2" in s

    def test_repr_contains_all_fields(self):
        """GIVEN result THEN repr includes formula, confidence, errors, warnings."""
        r = ParseResult(formula=None, confidence=0.7, success=True)
        rep = repr(r)
        assert "formula" in rep
        assert "confidence" in rep


# ===========================================================================
# BaseParser
# ===========================================================================

class TestBaseParserGetLanguage:
    """Line 166 — get_language returns the language string."""

    def test_get_language_returns_code(self):
        """GIVEN parser with language='fr' THEN get_language returns 'fr'."""
        p = _SimpleParser("fr")
        assert p.get_language() == "fr"


class TestBaseParserGetSupportedOperators:
    """Line 177 — default get_supported_operators returns empty list."""

    def test_default_returns_empty_list(self):
        """GIVEN base parser THEN get_supported_operators is empty."""
        p = _SimpleParser()
        assert p.get_supported_operators() == []


class TestBaseParserStrRepr:
    """Lines 184–188 — __str__ and __repr__."""

    def test_str_contains_class_and_language(self):
        """GIVEN parser THEN str shows class name and language."""
        p = _SimpleParser("de")
        s = str(p)
        assert "_SimpleParser" in s
        assert "de" in s

    def test_repr_contains_confidence_threshold(self):
        """GIVEN parser THEN repr shows confidence_threshold."""
        p = _SimpleParser("es", confidence_threshold=0.7)
        r = repr(p)
        assert "confidence_threshold" in r
        assert "0.7" in r

    def test_repr_contains_max_input_length(self):
        """GIVEN parser THEN repr shows max_input_length."""
        p = _SimpleParser()
        r = repr(p)
        assert "max_input_length" in r


class TestBaseParserParseEmptyInput:
    """Lines 219–220 — _validate_input rejects empty text."""

    def test_parse_empty_string_returns_error(self):
        """GIVEN empty string WHEN parse THEN error in result."""
        p = _SimpleParser()
        result = p.parse("")
        assert result.has_errors()
        assert result.success is False

    def test_parse_whitespace_only_returns_error(self):
        """GIVEN whitespace-only string WHEN parse THEN error."""
        p = _SimpleParser()
        result = p.parse("   ")
        assert result.has_errors()


class TestBaseParserParseTooLong:
    """Lines 224–227 — _validate_input rejects overly-long text."""

    def test_parse_too_long_returns_error(self):
        """GIVEN text > max_input_length WHEN parse THEN error."""
        p = _SimpleParser()
        long_text = "x" * (p.max_input_length + 1)
        result = p.parse(long_text)
        assert result.has_errors()
        assert "maximum length" in result.errors[0]


class TestBaseParserParseLowConfidence:
    """Line 259 — parse adds warning when confidence below threshold."""

    def test_low_confidence_adds_warning(self):
        """GIVEN parser returning confidence=0.3 and threshold=0.8 THEN warning added."""
        p = _LowConfidenceParser()
        result = p.parse("hello world")
        assert result.has_warnings()
        assert "threshold" in result.warnings[0].lower() or "confidence" in result.warnings[0].lower()


class TestBaseParserParseExceptionHandling:
    """Lines 270, 274 — parse() catches exceptions from parse_impl."""

    def test_exception_in_parse_impl_returns_error(self):
        """GIVEN parse_impl raises WHEN parse THEN error in result, not propagated."""
        p = _ExceptionParser()
        result = p.parse("some text")
        assert result.has_errors()
        assert "parse_impl failed" in result.errors[0]
        assert result.success is False


# ===========================================================================
# get_parser function
# ===========================================================================

class TestGetParserFunction:
    """Lines 307–364 — get_parser factory function."""

    def test_get_parser_english_by_language_enum(self):
        """GIVEN Language.ENGLISH THEN returns parser with language 'en'."""
        parser = get_parser(Language.ENGLISH)
        assert parser is not None
        assert parser.get_language() == "en"

    def test_get_parser_english_by_string(self):
        """GIVEN string 'en' THEN returns English parser."""
        parser = get_parser("en")
        assert parser is not None
        assert parser.get_language() == "en"

    def test_get_parser_invalid_string_raises_value_error(self):
        """GIVEN unsupported language code THEN ValueError raised."""
        with pytest.raises(ValueError, match="Unsupported language code"):
            get_parser("xx")

    def test_get_parser_spanish_raises_not_implemented(self):
        """GIVEN Language.SPANISH THEN NotImplementedError raised."""
        with pytest.raises(NotImplementedError):
            get_parser(Language.SPANISH)

    def test_get_parser_french_raises_not_implemented(self):
        """GIVEN Language.FRENCH THEN NotImplementedError raised."""
        with pytest.raises(NotImplementedError):
            get_parser(Language.FRENCH)

    def test_get_parser_german_raises_not_implemented(self):
        """GIVEN Language.GERMAN THEN NotImplementedError raised."""
        with pytest.raises(NotImplementedError):
            get_parser(Language.GERMAN)

    def test_get_parser_unknown_language_enum_raises_value_error(self):
        """GIVEN unsupported Language enum (None) THEN ValueError or TypeError raised."""
        with pytest.raises((ValueError, NotImplementedError, TypeError, AttributeError)):
            get_parser(None)  # type: ignore

    def test_english_parser_can_parse_text(self):
        """GIVEN English parser WHEN parse called THEN returns ParseResult."""
        parser = get_parser(Language.ENGLISH)
        result = parser.parse("The agent must act")
        assert isinstance(result, ParseResult)

    def test_english_parser_handles_converter_failure(self):
        """GIVEN English parser WHEN NLConverter returns failure result THEN error ParseResult."""
        parser = get_parser("en")
        # Patch the converter's convert_to_dcec to return failure
        from ipfs_datasets_py.logic.CEC.native.nl_converter import ConversionResult
        failure_result = ConversionResult(
            english_text="test",
            success=False,
            error_message="conversion failed",
            confidence=0.0,
        )
        parser._converter.convert_to_dcec = MagicMock(return_value=failure_result)
        result = parser.parse("test text")
        assert isinstance(result, ParseResult)
        assert result.has_errors()

    def test_english_parser_handles_convert_exception(self):
        """GIVEN English parser WHEN convert_to_dcec raises THEN error ParseResult."""
        parser = get_parser("en")
        parser._converter.convert_to_dcec = MagicMock(side_effect=RuntimeError("crash"))
        result = parser.parse("test text")
        assert isinstance(result, ParseResult)
        assert result.has_errors()

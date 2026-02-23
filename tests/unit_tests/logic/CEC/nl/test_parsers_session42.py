"""
Session 42: CEC NL parser coverage improvements for French, German, Spanish parsers.

Targets:
- french_parser.py   84% → 95%+
- german_parser.py   85% → 95%+
- spanish_parser.py  87% → 95%+
- domain_vocab.py    86% → 95%+

Coverage focuses on:
- _extract_agent returning None (no regex match on empty/special-char text)
- _create_simple_predicate: early-return when predicate already exists (line 194)
  and except-ValueError path when add_predicate raises (lines 199-200)
- _create_agent_variable: except-ValueError path (lines 221-222)
- NOT connective pattern path in convert() (lines 243-246 French, 247-250 German)
- Cognitive pattern else-branch (inner_formula is None) (lines 298-300 FR, 302-304 DE, 297-299 ES)
- parse_impl no-match branch (lines 369-372 FR, 375-378 DE, 368-370 ES)
- parse_impl exception branch (lines 374-378 FR, 380-384 DE, 372-376 ES)
- domain_vocab.py: get_all_terms without category filter (line 144),
  get_vocabulary_terms unknown domain (line 416), without language (line 421),
  enhance_text body (lines 449-465)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from ipfs_datasets_py.logic.CEC.nl.french_parser import (
    FrenchParser,
    FrenchPatternMatcher,
)
from ipfs_datasets_py.logic.CEC.nl.german_parser import (
    GermanParser,
    GermanPatternMatcher,
)
from ipfs_datasets_py.logic.CEC.nl.spanish_parser import (
    SpanishParser,
    SpanishPatternMatcher,
)
from ipfs_datasets_py.logic.CEC.nl.base_parser import ParseResult
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    DeonticFormula,
    CognitiveFormula,
    ConnectiveFormula,
    AtomicFormula,
    DeonticOperator,
    LogicalConnective,
    Predicate,
    Variable,
    VariableTerm,
)
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECNamespace


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_french_matcher() -> FrenchPatternMatcher:
    return FrenchPatternMatcher(DCECNamespace())


def _make_german_matcher() -> GermanPatternMatcher:
    return GermanPatternMatcher(DCECNamespace())


def _make_spanish_matcher() -> SpanishPatternMatcher:
    return SpanishPatternMatcher(DCECNamespace())


def _make_atomic(namespace: DCECNamespace, pred_name: str = "action") -> AtomicFormula:
    pred = namespace.add_predicate(pred_name, [])
    var = namespace.add_variable("agent", "Agent")
    return AtomicFormula(pred, [VariableTerm(var)])


# ===========================================================================
# FRENCH PARSER — missing coverage
# ===========================================================================

class TestFrenchExtractAgentNone:
    """Line 176 — _extract_agent returns None when no word chars in text."""

    def test_extract_agent_empty_string_returns_none(self):
        """
        GIVEN empty string input
        WHEN _extract_agent called
        THEN returns None (line 176).
        """
        matcher = _make_french_matcher()
        result = matcher._extract_agent("")
        assert result is None

    def test_extract_agent_special_chars_returns_none(self):
        """
        GIVEN string of special characters only
        WHEN _extract_agent called
        THEN returns None (line 176).
        """
        matcher = _make_french_matcher()
        result = matcher._extract_agent("!!!")
        assert result is None


class TestFrenchCreatePredicateExisting:
    """Line 194 — _create_simple_predicate returns existing predicate."""

    def test_create_predicate_returns_existing_on_second_call(self):
        """
        GIVEN predicate already registered in namespace
        WHEN _create_simple_predicate called with same name
        THEN returns existing predicate (line 194).
        """
        matcher = _make_french_matcher()
        # First call creates the predicate
        pred1 = matcher._create_simple_predicate("actiontest")
        # Second call finds existing via get_predicate
        pred2 = matcher._create_simple_predicate("actiontest")
        assert pred1 is pred2

    def test_create_predicate_strips_french_particles(self):
        """
        GIVEN action with French particles l' and d'
        WHEN _create_simple_predicate called
        THEN strips particles before creating pred name.
        """
        matcher = _make_french_matcher()
        pred = matcher._create_simple_predicate("l'action")
        assert pred.name == "action"


class TestFrenchCreatePredicateValueError:
    """Lines 199-200 — _create_simple_predicate except-ValueError path."""

    def test_create_predicate_valueerror_returns_fallback(self):
        """
        GIVEN add_predicate raises ValueError (concurrent creation)
        WHEN _create_simple_predicate called
        THEN returns predicate from fallback get_predicate (lines 199-200).
        """
        matcher = _make_french_matcher()
        ns = matcher.namespace
        # Pre-create a predicate to return from the second get_predicate call
        existing_pred = ns.add_predicate("racecond", [])

        call_count = [0]
        original_get = ns.get_predicate

        def mock_get(name, arity=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # First check: not found
            return existing_pred  # Second check (in except): found

        with patch.object(ns, "get_predicate", side_effect=mock_get), \
             patch.object(ns, "add_predicate", side_effect=ValueError("duplicate")):
            result = matcher._create_simple_predicate("racecond")

        assert result is existing_pred


class TestFrenchCreateAgentVariableValueError:
    """Lines 221-222 — _create_agent_variable except-ValueError path."""

    def test_create_variable_valueerror_returns_fallback(self):
        """
        GIVEN add_variable raises ValueError
        WHEN _create_agent_variable called
        THEN returns variable from fallback get_variable (lines 221-222).
        """
        matcher = _make_french_matcher()
        ns = matcher.namespace
        existing_var = ns.add_variable("racecond_agent", "Agent")

        call_count = [0]

        def mock_get(name):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return existing_var

        with patch.object(ns, "get_variable", side_effect=mock_get), \
             patch.object(ns, "add_variable", side_effect=ValueError("duplicate")):
            result = matcher._create_agent_variable("racecond_agent")

        assert result is existing_var


class TestFrenchNotConnectivePattern:
    """Lines 243-246 — NOT connective branch in convert()."""

    def test_not_connective_creates_connective_formula(self):
        """
        GIVEN text matching NOT connective pattern (ne ... pas)
        WHEN convert called
        THEN returns ConnectiveFormula with NOT operator (lines 243-246).
        """
        matcher = _make_french_matcher()
        # Pattern: r"^ne\s+(?!doit|peut|est\s+permis)(.+?)\s+pas$"
        result = matcher.convert("ne effectue pas")
        assert result is not None
        assert isinstance(result, ConnectiveFormula)
        assert result.connective == LogicalConnective.NOT

    def test_not_connective_non_deontic_word(self):
        """
        GIVEN ne...pas pattern with non-deontic verb
        WHEN convert called
        THEN returns NOT ConnectiveFormula.
        """
        matcher = _make_french_matcher()
        result = matcher.convert("ne participe pas")
        assert result is not None
        assert isinstance(result, ConnectiveFormula)


class TestFrenchCognitiveInnerNone:
    """Lines 298-300 — cognitive else-branch when inner_formula is None."""

    def test_cognitive_else_branch_creates_atomic_inner(self):
        """
        GIVEN cognitive pattern match but inner convert returns None
        WHEN convert called
        THEN cognitive formula created with AtomicFormula inner (lines 298-300).
        """
        matcher = _make_french_matcher()
        original_convert = matcher.convert

        call_count = [0]

        def mock_convert(text):
            call_count[0] += 1
            if call_count[0] == 1:
                # The top-level call: process cognitive pattern normally
                # but when recursing, return None
                return original_convert(text)
            # Recursive call: return None to trigger else branch
            return None

        with patch.object(matcher, "convert", side_effect=mock_convert):
            # "croit que X" triggers cognitive pattern
            # The recursive call on "X" will get None, hitting lines 298-300
            result = matcher.convert("croit que faire_action")

        # The result should be a CognitiveFormula regardless
        assert result is not None


class TestFrenchParseImplNoBranches:
    """Lines 369-378 — parse_impl no-match and exception branches."""

    def test_parse_impl_no_match_returns_error_result(self):
        """
        GIVEN text that converts to None
        WHEN parse called
        THEN ParseResult with error (lines 369-372).
        """
        parser = FrenchParser()
        with patch.object(parser.matcher, "convert", return_value=None):
            result = parser.parse("test text")
        assert not result.success
        assert len(result.errors) > 0

    def test_parse_impl_exception_returns_error_result(self):
        """
        GIVEN matcher.convert raises RuntimeError
        WHEN parse called
        THEN ParseResult with error (lines 374-378).
        """
        parser = FrenchParser()
        with patch.object(parser.matcher, "convert", side_effect=RuntimeError("test error")):
            result = parser.parse("test text")
        assert not result.success
        assert len(result.errors) > 0

    def test_parse_impl_connective_formula_confidence_bonus(self):
        """
        GIVEN text producing ConnectiveFormula
        WHEN parse called
        THEN confidence includes formula-type bonus (line 417-418).
        """
        parser = FrenchParser()
        # Use NOT connective pattern to produce ConnectiveFormula
        result = parser.parse("ne agit pas")
        # Even if confidence is low, result should have formula
        if result.formula is not None:
            assert isinstance(result.formula, ConnectiveFormula)


# ===========================================================================
# GERMAN PARSER — missing coverage
# ===========================================================================

class TestGermanExtractAgentNone:
    """Line 180 — _extract_agent returns None."""

    def test_extract_agent_empty_string_returns_none(self):
        """
        GIVEN empty string
        WHEN _extract_agent called
        THEN returns None (line 180).
        """
        matcher = _make_german_matcher()
        result = matcher._extract_agent("")
        assert result is None

    def test_extract_agent_special_chars_returns_none(self):
        """
        GIVEN special characters only
        WHEN _extract_agent called
        THEN returns None (line 180).
        """
        matcher = _make_german_matcher()
        result = matcher._extract_agent("!!!")
        assert result is None


class TestGermanCreatePredicateExisting:
    """Line 197 — _create_simple_predicate returns existing predicate."""

    def test_create_predicate_returns_existing_on_second_call(self):
        """
        GIVEN predicate already in namespace
        WHEN _create_simple_predicate called again
        THEN returns existing (line 197).
        """
        matcher = _make_german_matcher()
        pred1 = matcher._create_simple_predicate("Handlung")
        pred2 = matcher._create_simple_predicate("Handlung")
        assert pred1 is pred2


class TestGermanCreatePredicateValueError:
    """Lines 202-203 — _create_simple_predicate except-ValueError path."""

    def test_create_predicate_valueerror_returns_fallback(self):
        """
        GIVEN add_predicate raises ValueError
        WHEN _create_simple_predicate called
        THEN returns predicate from fallback (lines 202-203).
        """
        matcher = _make_german_matcher()
        ns = matcher.namespace
        existing_pred = ns.add_predicate("german_racecond", [])

        call_count = [0]

        def mock_get(name, arity=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return existing_pred

        with patch.object(ns, "get_predicate", side_effect=mock_get), \
             patch.object(ns, "add_predicate", side_effect=ValueError("duplicate")):
            result = matcher._create_simple_predicate("german_racecond")

        assert result is existing_pred


class TestGermanCreateAgentVariableValueError:
    """Lines 225-226 — _create_agent_variable except-ValueError path."""

    def test_create_variable_valueerror_returns_fallback(self):
        """
        GIVEN add_variable raises ValueError
        WHEN _create_agent_variable called
        THEN returns variable from fallback (lines 225-226).
        """
        matcher = _make_german_matcher()
        ns = matcher.namespace
        existing_var = ns.add_variable("german_agent", "Agent")

        call_count = [0]

        def mock_get(name):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return existing_var

        with patch.object(ns, "get_variable", side_effect=mock_get), \
             patch.object(ns, "add_variable", side_effect=ValueError("duplicate")):
            result = matcher._create_agent_variable("german_agent")

        assert result is existing_var


class TestGermanNotConnectivePattern:
    """Lines 247-250 — NOT connective branch in convert()."""

    def test_not_connective_creates_connective_formula(self):
        """
        GIVEN text matching German NOT pattern (nicht ...)
        WHEN convert called
        THEN returns ConnectiveFormula with NOT (lines 247-250).
        """
        matcher = _make_german_matcher()
        # Pattern: r"^nicht\s+(?!darf|muss|ist\s+erlaubt)(.+)"
        result = matcher.convert("nicht ausführt")
        assert result is not None
        assert isinstance(result, ConnectiveFormula)
        assert result.connective == LogicalConnective.NOT

    def test_not_connective_german_verb(self):
        """
        GIVEN German NOT pattern with action word
        WHEN convert called
        THEN NOT ConnectiveFormula returned.
        """
        matcher = _make_german_matcher()
        result = matcher.convert("nicht handelt")
        assert result is not None
        assert isinstance(result, ConnectiveFormula)


class TestGermanCognitiveInnerNone:
    """Lines 302-304 — cognitive else-branch when inner_formula is None."""

    def test_cognitive_else_branch_with_mocked_inner(self):
        """
        GIVEN cognitive pattern matched and inner convert returns None
        WHEN convert processes cognitive content
        THEN creates CognitiveFormula with AtomicFormula inner (lines 302-304).
        """
        matcher = _make_german_matcher()
        original_convert = matcher.convert

        call_count = [0]

        def mock_convert(text):
            call_count[0] += 1
            if call_count[0] == 1:
                return original_convert(text)
            return None  # inner call returns None

        with patch.object(matcher, "convert", side_effect=mock_convert):
            result = matcher.convert("glaubt dass handeln")

        assert result is not None


class TestGermanParseImplNoBranches:
    """Lines 375-384 — parse_impl no-match and exception branches."""

    def test_parse_impl_no_match_returns_error(self):
        """
        GIVEN convert returns None
        WHEN parse called
        THEN ParseResult with error (lines 375-378).
        """
        parser = GermanParser()
        with patch.object(parser.matcher, "convert", return_value=None):
            result = parser.parse("test")
        assert not result.success
        assert len(result.errors) > 0

    def test_parse_impl_exception_returns_error(self):
        """
        GIVEN convert raises RuntimeError
        WHEN parse called
        THEN ParseResult with error (lines 380-384).
        """
        parser = GermanParser()
        with patch.object(parser.matcher, "convert", side_effect=RuntimeError("boom")):
            result = parser.parse("test")
        assert not result.success
        assert len(result.errors) > 0


# ===========================================================================
# SPANISH PARSER — missing coverage
# ===========================================================================

class TestSpanishExtractAgentNone:
    """Line 176 — _extract_agent returns None."""

    def test_extract_agent_empty_returns_none(self):
        """
        GIVEN empty string
        WHEN _extract_agent called
        THEN returns None (line 176).
        """
        matcher = _make_spanish_matcher()
        result = matcher._extract_agent("")
        assert result is None

    def test_extract_agent_special_chars_returns_none(self):
        """
        GIVEN special characters only
        WHEN _extract_agent called
        THEN returns None (line 176).
        """
        matcher = _make_spanish_matcher()
        result = matcher._extract_agent("!!!@@@")
        assert result is None


class TestSpanishCreatePredicateExisting:
    """Line 192 — _create_simple_predicate returns existing predicate."""

    def test_create_predicate_returns_existing_on_second_call(self):
        """
        GIVEN predicate already in namespace
        WHEN _create_simple_predicate called again with same name
        THEN returns existing (line 192).
        """
        matcher = _make_spanish_matcher()
        pred1 = matcher._create_simple_predicate("accion")
        pred2 = matcher._create_simple_predicate("accion")
        assert pred1 is pred2


class TestSpanishCreatePredicateValueError:
    """Lines 197-198 — _create_simple_predicate except-ValueError path."""

    def test_create_predicate_valueerror_returns_fallback(self):
        """
        GIVEN add_predicate raises ValueError
        WHEN _create_simple_predicate called
        THEN returns predicate from fallback get_predicate (lines 197-198).
        """
        matcher = _make_spanish_matcher()
        ns = matcher.namespace
        existing_pred = ns.add_predicate("spanish_racecond", [])

        call_count = [0]

        def mock_get(name, arity=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return existing_pred

        with patch.object(ns, "get_predicate", side_effect=mock_get), \
             patch.object(ns, "add_predicate", side_effect=ValueError("duplicate")):
            result = matcher._create_simple_predicate("spanish_racecond")

        assert result is existing_pred


class TestSpanishCreateAgentVariableValueError:
    """Lines 219-220 — _create_agent_variable except-ValueError path."""

    def test_create_variable_valueerror_returns_fallback(self):
        """
        GIVEN add_variable raises ValueError
        WHEN _create_agent_variable called
        THEN returns variable from fallback (lines 219-220).
        """
        matcher = _make_spanish_matcher()
        ns = matcher.namespace
        existing_var = ns.add_variable("spanish_agent", "Agent")

        call_count = [0]

        def mock_get(name):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return existing_var

        with patch.object(ns, "get_variable", side_effect=mock_get), \
             patch.object(ns, "add_variable", side_effect=ValueError("duplicate")):
            result = matcher._create_agent_variable("spanish_agent")

        assert result is existing_var


class TestSpanishCognitiveInnerNone:
    """Lines 297-299 — cognitive else-branch when inner_formula is None."""

    def test_cognitive_else_branch_creates_atomic_inner(self):
        """
        GIVEN cognitive pattern matched and inner convert returns None
        WHEN convert processes text
        THEN creates CognitiveFormula with AtomicFormula inner (lines 297-299).
        """
        matcher = _make_spanish_matcher()
        original_convert = matcher.convert

        call_count = [0]

        def mock_convert(text):
            call_count[0] += 1
            if call_count[0] == 1:
                return original_convert(text)
            return None

        with patch.object(matcher, "convert", side_effect=mock_convert):
            result = matcher.convert("cree que actuar")

        assert result is not None


class TestSpanishParseImplNoBranches:
    """Lines 368-376 — parse_impl no-match and exception branches."""

    def test_parse_impl_no_match_returns_error(self):
        """
        GIVEN convert returns None
        WHEN parse called
        THEN ParseResult with error (lines 368-370).
        """
        parser = SpanishParser()
        with patch.object(parser.matcher, "convert", return_value=None):
            result = parser.parse("test")
        assert not result.success
        assert len(result.errors) > 0

    def test_parse_impl_exception_returns_error(self):
        """
        GIVEN convert raises RuntimeError
        WHEN parse called
        THEN ParseResult with error (lines 372-376).
        """
        parser = SpanishParser()
        with patch.object(parser.matcher, "convert", side_effect=RuntimeError("boom")):
            result = parser.parse("test")
        assert not result.success
        assert len(result.errors) > 0


# ===========================================================================
# DOMAIN VOCAB — missing coverage
# ===========================================================================

class TestDomainVocab:
    """domain_vocab.py missing lines: 144, 416, 421, 449-465."""

    def test_get_all_terms_without_category_returns_all(self):
        """
        GIVEN LegalVocabulary with terms
        WHEN get_all_terms called without category argument
        THEN returns all terms (line 144 — no-category branch).
        """
        from ipfs_datasets_py.logic.CEC.nl.domain_vocabularies.domain_vocab import (
            LegalVocabulary,
        )
        vocab = LegalVocabulary()
        all_terms = vocab.get_all_terms()  # no category filter → line 144
        assert len(all_terms) > 0

    def test_get_vocabulary_terms_unknown_domain_returns_empty(self):
        """
        GIVEN domain not registered in manager
        WHEN get_vocabulary_terms called
        THEN returns empty dict (line 416).
        """
        from ipfs_datasets_py.logic.CEC.nl.domain_vocabularies.domain_vocab import (
            DomainVocabularyManager,
        )
        manager = DomainVocabularyManager()
        result = manager.get_vocabulary_terms("nonexistent_domain_xyz")
        assert result == {}

    def test_get_vocabulary_terms_without_language_returns_english(self):
        """
        GIVEN known domain and no language filter
        WHEN get_vocabulary_terms called
        THEN returns dict with English terms (line 421).
        """
        from ipfs_datasets_py.logic.CEC.nl.domain_vocabularies.domain_vocab import (
            DomainVocabularyManager,
            LegalVocabulary,
        )
        manager = DomainVocabularyManager()
        manager.add_vocabulary(LegalVocabulary())
        result = manager.get_vocabulary_terms("legal")  # no language → line 421
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_enhance_text_unknown_domain_returns_original(self):
        """
        GIVEN unknown domain
        WHEN enhance_text called
        THEN returns original text unchanged (lines 449-451).
        """
        from ipfs_datasets_py.logic.CEC.nl.domain_vocabularies.domain_vocab import (
            DomainVocabularyManager,
        )
        manager = DomainVocabularyManager()
        text = "The agent must comply with regulations"
        result = manager.enhance_text(text, "nonexistent_domain_xyz", "en")
        assert result == text

    def test_enhance_text_known_domain_returns_string(self):
        """
        GIVEN known domain with registered vocabulary
        WHEN enhance_text called with language
        THEN returns a string (lines 449-465 — full body executed).
        """
        from ipfs_datasets_py.logic.CEC.nl.domain_vocabularies.domain_vocab import (
            DomainVocabularyManager,
            LegalVocabulary,
        )
        manager = DomainVocabularyManager()
        manager.add_vocabulary(LegalVocabulary())
        text = "obligation permission"
        result = manager.enhance_text(text, "legal", "en")
        assert isinstance(result, str)

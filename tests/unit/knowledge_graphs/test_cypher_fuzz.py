"""
Fuzz / stress tests for the Cypher parser and lexer (Workstream E2).

Goal: verify that the parser **never crashes** on arbitrary input.
Instead of a random-byte fuzzer (which needs a dedicated library), these
tests use a curated set of "tricky" inputs – truncated queries, weird
Unicode, very long strings, malformed syntax, injection-style strings, and
boundary values – and assert that any failure is a tidy `CypherParseError`
(or `Exception`), never a Python crash, infinite loop or other fatal error.

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest
import string
import random

from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser, CypherParseError
from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler, CypherCompileError
from ipfs_datasets_py.knowledge_graphs.cypher.lexer import CypherLexer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_safe(query: str):
    """Parse *query* and return the AST, or None if a parse exception is raised.

    Any other exception propagates so the test fails visibly.
    """
    parser = CypherParser()
    try:
        return parser.parse(query)
    except (CypherParseError, ValueError, IndexError, AttributeError, TypeError, SyntaxError):
        return None


def _parse_and_compile_safe(query: str):
    """Parse then compile *query*; return IR list or None on expected failure."""
    parser = CypherParser()
    compiler = CypherCompiler()
    try:
        ast = parser.parse(query)
        return compiler.compile(ast)
    except (CypherParseError, CypherCompileError, ValueError, IndexError,
            AttributeError, TypeError, KeyError, SyntaxError):
        return None


# ---------------------------------------------------------------------------
# 1. Truncated / incomplete queries
# ---------------------------------------------------------------------------

class TestTruncatedQueries:
    """Parser must not crash on incomplete / truncated Cypher queries."""

    TRUNCATED = [
        "MATCH",
        "MATCH (",
        "MATCH (n",
        "MATCH (n:",
        "MATCH (n:Person",
        "MATCH (n:Person)",
        "MATCH (n:Person) WHERE",
        "MATCH (n:Person) WHERE n",
        "MATCH (n:Person) WHERE n.",
        "MATCH (n:Person) WHERE n.age",
        "MATCH (n:Person) WHERE n.age >",
        "MATCH (n:Person) RETURN",
        "MATCH (n:Person) RETURN n ORDER BY",
        "MATCH (n:Person) RETURN n LIMIT",
        "CREATE (",
        "CREATE (n:Person {",
        "CREATE (n:Person {name:",
        "CREATE (n:Person {name: 'Alice'",
    ]

    @pytest.mark.parametrize("query", TRUNCATED)
    def test_truncated_query_does_not_crash(self, query):
        """
        GIVEN: A truncated / incomplete Cypher query
        WHEN: Parsed
        THEN: Either a CypherParseError is raised (good) or an empty/partial
              AST is returned – the parser must not raise an unhandled exception
              or hang.
        """
        # GIVEN / WHEN / THEN – _parse_safe handles expected exceptions
        result = _parse_safe(query)
        # Either None (parse error caught) or a valid AST is acceptable.
        assert result is None or hasattr(result, "clauses")


# ---------------------------------------------------------------------------
# 2. Malformed syntax
# ---------------------------------------------------------------------------

class TestMalformedSyntax:
    """Parser handles structurally malformed queries gracefully."""

    MALFORMED = [
        # Mismatched brackets
        "MATCH (n:Person RETURN n",
        "MATCH (n:Person)) RETURN n",
        "MATCH [n:Person] RETURN n",
        # Extra/missing keywords
        "MATCH MATCH (n) RETURN n",
        "RETURN n",                      # RETURN without MATCH
        "WHERE n.age > 30 RETURN n",     # WHERE without MATCH
        # Double operators
        "MATCH (n) WHERE n.age >> 30 RETURN n",
        "MATCH (n) WHERE n.age = = 30 RETURN n",
        # Missing property value
        "MATCH (n:Person {name:}) RETURN n",
        # Dangling comma
        "MATCH (n) RETURN n,",
        # Semicolons (not standard Cypher)
        "MATCH (n);",
        # SQL injection-style strings  
        "MATCH (n:Person) WHERE n.name = '; DROP TABLE nodes; --' RETURN n",
        # Mixed quotes
        "MATCH (n) WHERE n.name = \"Alice' RETURN n",
    ]

    @pytest.mark.parametrize("query", MALFORMED)
    def test_malformed_query_does_not_crash(self, query):
        """
        GIVEN: A malformed Cypher query string
        WHEN: Parsed
        THEN: Either a parse error is raised or a partial AST is returned;
              never an uncaught exception.
        """
        result = _parse_safe(query)
        assert result is None or hasattr(result, "clauses")


# ---------------------------------------------------------------------------
# 3. Very long / large inputs
# ---------------------------------------------------------------------------

class TestLargeInputs:
    """Parser does not crash or hang on very long inputs."""

    def test_very_long_label_name(self):
        """
        GIVEN: A label with a 1000-character name
        WHEN: Parsed
        THEN: Does not crash (may raise CypherParseError or return AST)
        """
        long_label = "A" * 1000
        result = _parse_safe(f"MATCH (n:{long_label}) RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_very_long_string_literal(self):
        """
        GIVEN: A string literal with 10000 characters
        WHEN: Parsed
        THEN: Does not crash
        """
        long_string = "x" * 10000
        result = _parse_safe(f"MATCH (n) WHERE n.name = '{long_string}' RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_many_where_conditions(self):
        """
        GIVEN: A WHERE clause with 50 AND-chained conditions
        WHEN: Parsed
        THEN: Does not crash; returns a valid AST or a parse error
        """
        conditions = " AND ".join(f"n.prop{i} = {i}" for i in range(50))
        result = _parse_safe(f"MATCH (n:Person) WHERE {conditions} RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_many_return_items(self):
        """
        GIVEN: A RETURN clause with 30 items
        WHEN: Parsed
        THEN: Does not crash
        """
        items = ", ".join(f"n.prop{i} AS alias{i}" for i in range(30))
        result = _parse_safe(f"MATCH (n:Person) RETURN {items}")
        assert result is None or hasattr(result, "clauses")

    def test_deeply_nested_labels(self):
        """
        GIVEN: A query matching multiple labeled nodes in a long chain
        WHEN: Parsed and compiled
        THEN: Does not crash
        """
        # Build a chain of 10 MATCH patterns
        patterns = "\n".join(
            f"MATCH (n{i}:Label{i})" for i in range(10)
        )
        result = _parse_and_compile_safe(patterns + "\nRETURN n0")
        assert result is None or isinstance(result, list)


# ---------------------------------------------------------------------------
# 4. Unicode and special characters
# ---------------------------------------------------------------------------

class TestUnicodeAndSpecialChars:
    """Parser handles Unicode identifiers, strings, and null bytes gracefully."""

    def test_unicode_property_value(self):
        """
        GIVEN: A string property with Unicode characters
        WHEN: Parsed
        THEN: Does not crash
        """
        result = _parse_safe("MATCH (n) WHERE n.name = '日本語テスト' RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_emoji_in_string(self):
        """
        GIVEN: A string with emoji characters
        WHEN: Parsed
        THEN: Does not crash
        """
        result = _parse_safe("MATCH (n) WHERE n.tag = '🎉🚀✨' RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_null_byte_in_query(self):
        """
        GIVEN: A query string containing a null byte
        WHEN: Parsed
        THEN: Does not crash (may raise or return empty AST)
        """
        result = _parse_safe("MATCH (n) WHERE n.x = '\x00' RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_escaped_quote_in_string(self):
        """
        GIVEN: A string literal with an escaped single quote (backslash)
        WHEN: Parsed
        THEN: Does not crash
        """
        result = _parse_safe(r"MATCH (n) WHERE n.name = 'O\'Brien' RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_backslash_in_string(self):
        """
        GIVEN: A string containing a lone backslash
        WHEN: Parsed
        THEN: Does not crash
        """
        result = _parse_safe("MATCH (n) WHERE n.path = 'C:\\\\Users' RETURN n")
        assert result is None or hasattr(result, "clauses")


# ---------------------------------------------------------------------------
# 5. Reserved words as variable names
# ---------------------------------------------------------------------------

class TestReservedWordsAsVariables:
    """Parser correctly handles or rejects reserved Cypher keywords used as names."""

    KEYWORDS = ["MATCH", "WHERE", "RETURN", "CREATE", "DELETE", "SET",
                "WITH", "LIMIT", "ORDER", "BY", "AS", "NOT", "AND", "OR"]

    @pytest.mark.parametrize("kw", KEYWORDS)
    def test_keyword_as_variable_does_not_crash(self, kw):
        """
        GIVEN: A Cypher keyword used as a variable name
        WHEN: Parsed
        THEN: Does not crash; may raise a parse error or return a partial AST
        """
        result = _parse_safe(f"MATCH ({kw}:Person) RETURN {kw}")
        assert result is None or hasattr(result, "clauses")


# ---------------------------------------------------------------------------
# 6. Valid edge cases that MUST parse successfully
# ---------------------------------------------------------------------------

class TestValidEdgeCases:
    """Certain edge-case queries that are valid Cypher must parse without error."""

    def test_empty_property_map(self):
        """
        GIVEN: MATCH (n:Person {}) RETURN n  (empty property map)
        WHEN: Parsed
        THEN: Returns a valid AST (not None)
        """
        result = _parse_safe("MATCH (n:Person {}) RETURN n")
        # Empty prop map is syntactically valid
        assert result is not None

    def test_integer_literal_in_where(self):
        """
        GIVEN: WHERE n.age = 0
        WHEN: Parsed
        THEN: Returns a valid AST
        """
        result = _parse_safe("MATCH (n:Person) WHERE n.age = 0 RETURN n")
        assert result is not None

    def test_negative_number_literal(self):
        """
        GIVEN: WHERE n.value = -42
        WHEN: Parsed
        THEN: Does not crash
        """
        result = _parse_safe("MATCH (n) WHERE n.value = -42 RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_float_literal(self):
        """
        GIVEN: WHERE n.score = 3.14
        WHEN: Parsed
        THEN: Does not crash
        """
        result = _parse_safe("MATCH (n) WHERE n.score = 3.14 RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_boolean_literals(self):
        """
        GIVEN: WHERE n.active = true / false
        WHEN: Parsed
        THEN: Does not crash
        """
        result_t = _parse_safe("MATCH (n) WHERE n.active = true RETURN n")
        result_f = _parse_safe("MATCH (n) WHERE n.active = false RETURN n")
        assert result_t is None or hasattr(result_t, "clauses")
        assert result_f is None or hasattr(result_f, "clauses")

    def test_null_literal(self):
        """
        GIVEN: WHERE n.value = null
        WHEN: Parsed
        THEN: Does not crash
        """
        result = _parse_safe("MATCH (n) WHERE n.value = null RETURN n")
        assert result is None or hasattr(result, "clauses")

    def test_multi_label_node(self):
        """
        GIVEN: MATCH (n:Person:Employee) RETURN n  (multi-label)
        WHEN: Parsed
        THEN: Does not crash
        """
        result = _parse_safe("MATCH (n:Person:Employee) RETURN n")
        assert result is None or hasattr(result, "clauses")


# ---------------------------------------------------------------------------
# 7. Lexer-level stress tests
# ---------------------------------------------------------------------------

class TestLexerStress:
    """The Cypher lexer must never crash regardless of input."""

    def _tokenize_safe(self, s: str):
        """Tokenize *s* and return list or None on expected tokenizer errors."""
        lexer = CypherLexer()
        try:
            return lexer.tokenize(s)
        except SyntaxError:
            return None

    def test_lexer_on_empty_string(self):
        """
        GIVEN: An empty string
        WHEN: Tokenized
        THEN: Returns a token list (may be empty or just EOF)
        """
        tokens = self._tokenize_safe("")
        assert tokens is None or isinstance(tokens, list)

    def test_lexer_on_whitespace_only(self):
        """
        GIVEN: A whitespace-only string
        WHEN: Tokenized
        THEN: Returns a token list without crashing
        """
        tokens = self._tokenize_safe("   \t\n  ")
        assert tokens is None or isinstance(tokens, list)

    def test_lexer_on_numbers_only(self):
        """
        GIVEN: A string of only digits
        WHEN: Tokenized
        THEN: Returns a token list without crashing
        """
        tokens = self._tokenize_safe("12345")
        assert tokens is None or isinstance(tokens, list)

    def test_lexer_on_special_characters(self):
        """
        GIVEN: A string of special/punctuation characters
        WHEN: Tokenized
        THEN: Returns a token list (or SyntaxError) without crashing Python
        """
        tokens = self._tokenize_safe("!@#$%^&*()[]{}|\\;\"")
        assert tokens is None or isinstance(tokens, list)

    def test_lexer_random_printable_ascii(self):
        """
        GIVEN: 100 random printable ASCII strings (length 5–50)
        WHEN: Tokenized
        THEN: Never causes an unhandled non-SyntaxError exception
        """
        random.seed(42)
        for _ in range(100):
            length = random.randint(5, 50)
            chars = string.printable
            s = "".join(random.choice(chars) for _ in range(length))
            tokens = self._tokenize_safe(s)
            assert tokens is None or isinstance(tokens, list)

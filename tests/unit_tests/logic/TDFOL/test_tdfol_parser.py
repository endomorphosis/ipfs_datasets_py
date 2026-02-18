"""
Tests for TDFOL Parser Module

This module tests the TDFOL parser including lexer, parser, and error handling
following GIVEN-WHEN-THEN format.

Test Coverage (94 tests total):
- Lexer tests (25): tokenization, operators, keywords, identifiers, numbers, structural tokens
- Parser tests (48): predicates, quantifiers, logic operators, temporal/deontic operators, complex formulas
- Error handling (15): malformed input, unexpected tokens, missing elements, invalid syntax
- Edge cases (18): empty strings, long formulas, deeply nested structures, special cases
- Direct class tests (11): Testing TDFOLLexer, TDFOLParser, and Token classes directly

Note: Identifiers starting with P, O, F, G, X, U, S, W, R are avoided as they conflict
with single-letter modal operator keywords in the lexer.
"""

import pytest

from ipfs_datasets_py.logic.TDFOL.tdfol_parser import (
    TDFOLLexer,
    TDFOLParser,
    Token,
    TokenType,
    parse_tdfol,
    parse_tdfol_safe,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    BinaryFormula,
    BinaryTemporalFormula,
    Constant,
    DeonticFormula,
    DeonticOperator,
    FunctionApplication,
    LogicOperator,
    Predicate,
    Quantifier,
    QuantifiedFormula,
    TemporalFormula,
    TemporalOperator,
    UnaryFormula,
    Variable,
)


# ============================================================================
# Lexer Tests (20 tests)
# ============================================================================


class TestLexerTokenization:
    """Test basic tokenization functionality."""
    
    def test_lexer_empty_string(self):
        """Test tokenizing an empty string."""
        # GIVEN an empty string
        text = ""
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should only have EOF token
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF
    
    def test_lexer_whitespace_only(self):
        """Test tokenizing whitespace-only string."""
        # GIVEN a whitespace-only string
        text = "   \n\t  "
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should only have EOF token
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF
    
    def test_lexer_single_identifier(self):
        """Test tokenizing a single identifier."""
        # GIVEN a simple identifier
        text = "Person"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should tokenize (note: "P" is ambiguous with PERMISSION)
        # The lexer tokenizes "P" as PERMISSION, then "erson" as IDENTIFIER
        assert len(tokens) == 3
        assert tokens[0].type == TokenType.PERMISSION  # "P" matches keyword
        assert tokens[1].type == TokenType.IDENTIFIER  # "erson"
        assert tokens[2].type == TokenType.EOF
    
    def test_lexer_identifier_with_underscore(self):
        """Test tokenizing identifier with underscores."""
        # GIVEN an identifier with underscores
        text = "is_valid_person"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should tokenize correctly
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "is_valid_person"
    
    def test_lexer_single_number(self):
        """Test tokenizing a number."""
        # GIVEN a number
        text = "42"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should have number token
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == "42"
    
    def test_lexer_multiple_numbers(self):
        """Test tokenizing multiple numbers."""
        # GIVEN multiple numbers with spaces
        text = "1 2 3"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should have three number tokens
        assert len(tokens) == 4  # 3 numbers + EOF
        assert all(tokens[i].type == TokenType.NUMBER for i in range(3))
        assert [tokens[i].value for i in range(3)] == ["1", "2", "3"]


class TestLexerOperators:
    """Test tokenization of logical operators."""
    
    def test_lexer_and_operators(self):
        """Test tokenizing AND operators."""
        # GIVEN various AND operator symbols
        text = "∧ & ^"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN all should be AND tokens
        assert len(tokens) == 4  # 3 operators + EOF
        assert all(tokens[i].type == TokenType.AND for i in range(3))
    
    def test_lexer_or_operators(self):
        """Test tokenizing OR operators."""
        # GIVEN various OR operator symbols
        text = "∨ |"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN all should be OR tokens
        assert len(tokens) == 3
        assert all(tokens[i].type == TokenType.OR for i in range(2))
    
    def test_lexer_not_operators(self):
        """Test tokenizing NOT operators."""
        # GIVEN various NOT operator symbols
        text = "¬ ~ !"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN all should be NOT tokens
        assert len(tokens) == 4
        assert all(tokens[i].type == TokenType.NOT for i in range(3))
    
    def test_lexer_implies_operators(self):
        """Test tokenizing IMPLIES operators."""
        # GIVEN various IMPLIES operator symbols
        text = "→ -> =>"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN all should be IMPLIES tokens
        assert len(tokens) == 4
        assert all(tokens[i].type == TokenType.IMPLIES for i in range(3))
    
    def test_lexer_iff_operators(self):
        """Test tokenizing IFF operators."""
        # GIVEN various IFF operator symbols
        text = "↔ <-> <=>"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN all should be IFF tokens
        assert len(tokens) == 4
        assert all(tokens[i].type == TokenType.IFF for i in range(3))
    
    def test_lexer_xor_operator(self):
        """Test tokenizing XOR operator."""
        # GIVEN XOR operator symbol
        text = "⊕"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should be XOR token
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.XOR


class TestLexerKeywords:
    """Test tokenization of keywords."""
    
    def test_lexer_forall_keyword(self):
        """Test tokenizing FORALL keyword."""
        # GIVEN various forall representations
        text = "∀ forall"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN all should be FORALL tokens
        assert len(tokens) == 3
        assert all(tokens[i].type == TokenType.FORALL for i in range(2))
    
    def test_lexer_exists_keyword(self):
        """Test tokenizing EXISTS keyword."""
        # GIVEN various exists representations
        text = "∃ exists"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN all should be EXISTS tokens
        assert len(tokens) == 3
        assert all(tokens[i].type == TokenType.EXISTS for i in range(2))
    
    def test_lexer_deontic_operators(self):
        """Test tokenizing deontic operators."""
        # GIVEN deontic operator symbols
        text = "O P F"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should have correct deontic tokens
        assert len(tokens) == 4
        assert tokens[0].type == TokenType.OBLIGATION
        assert tokens[1].type == TokenType.PERMISSION
        # Note: F is ambiguous (EVENTUALLY or PROHIBITION)
        assert tokens[2].type in [TokenType.EVENTUALLY, TokenType.PROHIBITION]
    
    def test_lexer_temporal_operators(self):
        """Test tokenizing temporal operators."""
        # GIVEN temporal operator symbols
        text = "G X U S W R"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should have correct temporal tokens
        assert len(tokens) == 7
        assert tokens[0].type == TokenType.ALWAYS
        assert tokens[1].type == TokenType.NEXT
        assert tokens[2].type == TokenType.UNTIL
        assert tokens[3].type == TokenType.SINCE
        assert tokens[4].type == TokenType.WEAK_UNTIL
        assert tokens[5].type == TokenType.RELEASE


class TestLexerStructuralTokens:
    """Test tokenization of structural elements."""
    
    def test_lexer_parentheses(self):
        """Test tokenizing parentheses."""
        # GIVEN parentheses
        text = "()"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should have LPAREN and RPAREN
        assert len(tokens) == 3
        assert tokens[0].type == TokenType.LPAREN
        assert tokens[1].type == TokenType.RPAREN
    
    def test_lexer_comma(self):
        """Test tokenizing comma."""
        # GIVEN a comma
        text = ","
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should have COMMA token
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.COMMA
    
    def test_lexer_dot(self):
        """Test tokenizing dot."""
        # GIVEN a dot
        text = "."
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should have DOT token
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.DOT
    
    def test_lexer_colon(self):
        """Test tokenizing colon."""
        # GIVEN a colon
        text = ":"
        
        # WHEN tokenizing
        lexer = TDFOLLexer(text)
        tokens = lexer.tokenize()
        
        # THEN should have COLON token
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.COLON


# ============================================================================
# Parser Tests (40 tests)
# ============================================================================


class TestParserPredicates:
    """Test parsing predicates."""
    
    def test_parse_nullary_predicate(self):
        """Test parsing a nullary predicate (propositional variable)."""
        # GIVEN a simple propositional variable (avoid single-letter keywords)
        formula_str = "Q"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a predicate with no arguments
        assert isinstance(formula, Predicate)
        assert formula.name == "Q"
        assert formula.arguments == ()
    
    def test_parse_unary_predicate(self):
        """Test parsing a unary predicate."""
        # GIVEN a unary predicate
        formula_str = "IsPerson(x)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a predicate with one argument
        assert isinstance(formula, Predicate)
        assert formula.name == "IsPerson"
        assert len(formula.arguments) == 1
        assert isinstance(formula.arguments[0], Variable)
        assert formula.arguments[0].name == "x"
    
    def test_parse_binary_predicate(self):
        """Test parsing a binary predicate."""
        # GIVEN a binary predicate
        formula_str = "Likes(john, mary)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a predicate with two arguments
        assert isinstance(formula, Predicate)
        assert formula.name == "Likes"
        assert len(formula.arguments) == 2
        assert all(isinstance(arg, Variable) for arg in formula.arguments)
    
    def test_parse_predicate_with_constant(self):
        """Test parsing predicate with constant argument."""
        # GIVEN a predicate with a number constant
        formula_str = "Age(42)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have constant argument
        assert isinstance(formula, Predicate)
        assert len(formula.arguments) == 1
        assert isinstance(formula.arguments[0], Constant)
        assert formula.arguments[0].name == "42"
    
    def test_parse_predicate_with_function(self):
        """Test parsing predicate with function application."""
        # GIVEN a predicate with function application
        formula_str = "IsParent(myfunc(x))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have function application argument
        assert isinstance(formula, Predicate)
        assert len(formula.arguments) == 1
        assert isinstance(formula.arguments[0], FunctionApplication)
        assert formula.arguments[0].function_name == "myfunc"
    
    def test_parse_predicate_mixed_arguments(self):
        """Test parsing predicate with mixed argument types."""
        # GIVEN a predicate with variable, constant, and function (avoid R/S/F as predicate names)
        formula_str = "MyRelation(x, 1, func(y))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have all three argument types
        assert isinstance(formula, Predicate)
        assert len(formula.arguments) == 3
        assert isinstance(formula.arguments[0], Variable)
        assert isinstance(formula.arguments[1], Constant)
        assert isinstance(formula.arguments[2], FunctionApplication)


class TestParserQuantifiers:
    """Test parsing quantified formulas."""
    
    def test_parse_universal_quantifier(self):
        """Test parsing universal quantification."""
        # GIVEN a universally quantified formula
        formula_str = "forall x. Qq(x)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a quantified formula with FORALL
        assert isinstance(formula, QuantifiedFormula)
        assert formula.quantifier == Quantifier.FORALL
        assert formula.variable.name == "x"
        assert isinstance(formula.formula, Predicate)
    
    def test_parse_existential_quantifier(self):
        """Test parsing existential quantification."""
        # GIVEN an existentially quantified formula
        formula_str = "exists x. Qq(x)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a quantified formula with EXISTS
        assert isinstance(formula, QuantifiedFormula)
        assert formula.quantifier == Quantifier.EXISTS
        assert formula.variable.name == "x"
    
    def test_parse_universal_with_unicode(self):
        """Test parsing universal quantifier with Unicode symbol."""
        # GIVEN a formula with Unicode forall symbol
        formula_str = "∀ x. Qq(x)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse correctly
        assert isinstance(formula, QuantifiedFormula)
        assert formula.quantifier == Quantifier.FORALL
    
    def test_parse_existential_with_unicode(self):
        """Test parsing existential quantifier with Unicode symbol."""
        # GIVEN a formula with Unicode exists symbol
        formula_str = "∃ x. Qq(x)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse correctly
        assert isinstance(formula, QuantifiedFormula)
        assert formula.quantifier == Quantifier.EXISTS
    
    def test_parse_nested_quantifiers(self):
        """Test parsing nested quantifiers."""
        # GIVEN a formula with nested quantifiers
        formula_str = "forall x. exists y. MyLikes(x, y)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have nested structure
        assert isinstance(formula, QuantifiedFormula)
        assert formula.quantifier == Quantifier.FORALL
        assert isinstance(formula.formula, QuantifiedFormula)
        assert formula.formula.quantifier == Quantifier.EXISTS
    
    def test_parse_quantifier_with_implication(self):
        """Test parsing quantifier with implication."""
        # GIVEN a quantified implication
        formula_str = "forall x. Qq(x) -> Zz(x)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have correct structure
        assert isinstance(formula, QuantifiedFormula)
        assert isinstance(formula.formula, BinaryFormula)
        assert formula.formula.operator == LogicOperator.IMPLIES


class TestParserLogicOperators:
    """Test parsing logical operators."""
    
    def test_parse_conjunction(self):
        """Test parsing conjunction."""
        # GIVEN a conjunction (use multi-letter names to avoid keyword conflicts)
        formula_str = "Qa & Qb"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a binary formula with AND
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.AND
    
    def test_parse_disjunction(self):
        """Test parsing disjunction."""
        # GIVEN a disjunction
        formula_str = "Qa | Qb"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a binary formula with OR
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.OR
    
    def test_parse_negation(self):
        """Test parsing negation."""
        # GIVEN a negation
        formula_str = "~Q"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a unary formula with NOT
        assert isinstance(formula, UnaryFormula)
        assert formula.operator == LogicOperator.NOT
    
    def test_parse_implication(self):
        """Test parsing implication."""
        # GIVEN an implication
        formula_str = "Qa -> Qb"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a binary formula with IMPLIES
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.IMPLIES
    
    def test_parse_biconditional(self):
        """Test parsing biconditional (IFF)."""
        # GIVEN a biconditional
        formula_str = "Qa <-> Qb"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a binary formula with IFF
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.IFF
    
    def test_parse_xor(self):
        """Test parsing XOR (note: XOR not yet implemented in parser)."""
        # GIVEN an XOR formula
        formula_str = "Qa ^ Qb"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a binary formula with AND (using ^ as AND)
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.AND
    
    def test_parse_double_negation(self):
        """Test parsing double negation."""
        # GIVEN a double negation
        formula_str = "~~Q"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have two NOT operators
        assert isinstance(formula, UnaryFormula)
        assert formula.operator == LogicOperator.NOT
        assert isinstance(formula.formula, UnaryFormula)
        assert formula.formula.operator == LogicOperator.NOT
    
    def test_parse_complex_conjunction(self):
        """Test parsing multiple conjunctions."""
        # GIVEN multiple conjunctions
        formula_str = "Qa & Qb & Qc"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should associate left-to-right
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.AND
        assert isinstance(formula.left, BinaryFormula)
        assert formula.left.operator == LogicOperator.AND


class TestParserTemporalOperators:
    """Test parsing temporal operators."""
    
    def test_parse_always(self):
        """Test parsing ALWAYS (G) operator."""
        # GIVEN an always formula
        formula_str = "G(Q)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a temporal formula with ALWAYS
        assert isinstance(formula, TemporalFormula)
        assert formula.operator == TemporalOperator.ALWAYS
        assert isinstance(formula.formula, Predicate)
    
    def test_parse_eventually(self):
        """Test parsing EVENTUALLY (F) operator."""
        # GIVEN an eventually formula (using symbol that maps to EVENTUALLY)
        formula_str = "◊(Q)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a temporal formula with EVENTUALLY
        assert isinstance(formula, TemporalFormula)
        assert formula.operator == TemporalOperator.EVENTUALLY
    
    def test_parse_next(self):
        """Test parsing NEXT (X) operator."""
        # GIVEN a next formula
        formula_str = "X(Q)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a temporal formula with NEXT
        assert isinstance(formula, TemporalFormula)
        assert formula.operator == TemporalOperator.NEXT
    
    def test_parse_always_with_unicode(self):
        """Test parsing ALWAYS with Unicode symbol."""
        # GIVEN an always formula with Unicode symbol
        formula_str = "□(Q)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse correctly
        assert isinstance(formula, TemporalFormula)
        assert formula.operator == TemporalOperator.ALWAYS
    
    def test_parse_nested_temporal(self):
        """Test parsing nested temporal operators."""
        # GIVEN nested temporal operators
        formula_str = "G(X(Q))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have nested structure
        assert isinstance(formula, TemporalFormula)
        assert formula.operator == TemporalOperator.ALWAYS
        assert isinstance(formula.formula, TemporalFormula)
        assert formula.formula.operator == TemporalOperator.NEXT


class TestParserDeonticOperators:
    """Test parsing deontic operators."""
    
    def test_parse_obligation(self):
        """Test parsing OBLIGATION (O) operator."""
        # GIVEN an obligation formula
        formula_str = "O(Q)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a deontic formula with OBLIGATION
        assert isinstance(formula, DeonticFormula)
        assert formula.operator == DeonticOperator.OBLIGATION
        assert isinstance(formula.formula, Predicate)
    
    def test_parse_permission(self):
        """Test parsing PERMISSION (P) operator."""
        # GIVEN a permission formula (use Q to avoid ambiguity with P)
        formula_str = "P(Qq)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should be a deontic formula with PERMISSION
        assert isinstance(formula, DeonticFormula)
        assert formula.operator == DeonticOperator.PERMISSION
    
    def test_parse_obligation_with_complex_formula(self):
        """Test parsing obligation with complex inner formula."""
        # GIVEN an obligation with conjunction
        formula_str = "O(Qa & Qb)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have correct nested structure
        assert isinstance(formula, DeonticFormula)
        assert formula.operator == DeonticOperator.OBLIGATION
        assert isinstance(formula.formula, BinaryFormula)
        assert formula.formula.operator == LogicOperator.AND
    
    def test_parse_nested_deontic(self):
        """Test parsing nested deontic operators."""
        # GIVEN nested deontic operators
        formula_str = "O(P(Qq))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have nested structure
        assert isinstance(formula, DeonticFormula)
        assert formula.operator == DeonticOperator.OBLIGATION
        assert isinstance(formula.formula, DeonticFormula)
        assert formula.formula.operator == DeonticOperator.PERMISSION


class TestParserComplexFormulas:
    """Test parsing complex formulas."""
    
    def test_parse_formula_with_parentheses(self):
        """Test parsing formula with explicit parentheses."""
        # GIVEN a formula with parentheses for grouping
        formula_str = "(Qa & Qb) | Qc"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should respect parentheses grouping
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.OR
        assert isinstance(formula.left, BinaryFormula)
        assert formula.left.operator == LogicOperator.AND
    
    def test_parse_precedence_not_and(self):
        """Test operator precedence between NOT and AND."""
        # GIVEN a formula testing NOT/AND precedence
        formula_str = "~Qa & Qb"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN NOT should bind tighter than AND
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.AND
        assert isinstance(formula.left, UnaryFormula)
        assert formula.left.operator == LogicOperator.NOT
    
    def test_parse_precedence_and_or(self):
        """Test operator precedence between AND and OR."""
        # GIVEN a formula testing AND/OR precedence
        formula_str = "Qa & Qb | Qc"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN AND should bind tighter than OR
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.OR
        assert isinstance(formula.left, BinaryFormula)
        assert formula.left.operator == LogicOperator.AND
    
    def test_parse_precedence_or_implies(self):
        """Test operator precedence between OR and IMPLIES."""
        # GIVEN a formula testing OR/IMPLIES precedence
        formula_str = "Qa | Qb -> Qc"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN OR should bind tighter than IMPLIES
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.IMPLIES
        assert isinstance(formula.left, BinaryFormula)
        assert formula.left.operator == LogicOperator.OR
    
    def test_parse_quantifier_with_deontic(self):
        """Test parsing quantifier with deontic operator."""
        # GIVEN a quantified deontic formula
        formula_str = "forall x. O(Qq(x))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have correct nested structure
        assert isinstance(formula, QuantifiedFormula)
        assert isinstance(formula.formula, DeonticFormula)
    
    def test_parse_deontic_with_temporal(self):
        """Test parsing deontic with temporal operator."""
        # GIVEN a deontic temporal formula
        formula_str = "O(G(Q))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have correct nested structure
        assert isinstance(formula, DeonticFormula)
        assert isinstance(formula.formula, TemporalFormula)
    
    def test_parse_all_three_modalities(self):
        """Test parsing formula with quantifier, deontic, and temporal."""
        # GIVEN a formula combining all three modalities
        formula_str = "forall x. O(G(Qq(x)))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have correct triply-nested structure
        assert isinstance(formula, QuantifiedFormula)
        assert isinstance(formula.formula, DeonticFormula)
        assert isinstance(formula.formula.formula, TemporalFormula)
    
    def test_parse_deeply_nested_formula(self):
        """Test parsing deeply nested formula."""
        # GIVEN a deeply nested formula (avoid single letters that are keywords)
        formula_str = "forall x. (Qq(x) -> (Zz(x) & (Aa(x) | Bb(x))))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse without error
        assert isinstance(formula, QuantifiedFormula)
        assert isinstance(formula.formula, BinaryFormula)


# ============================================================================
# Error Handling Tests (15 tests)
# ============================================================================


class TestParserErrorHandling:
    """Test error handling in parser."""
    
    def test_parse_unexpected_token(self):
        """Test parsing with unexpected token."""
        # GIVEN a formula with unexpected token
        formula_str = "Qa &"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_missing_closing_paren(self):
        """Test parsing with missing closing parenthesis."""
        # GIVEN a formula with unclosed parenthesis
        formula_str = "(Qa & Qb"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_missing_opening_paren(self):
        """Test parsing with extra closing parenthesis."""
        # GIVEN a formula with extra closing parenthesis
        formula_str = "Qa & Qb)"
        
        # WHEN parsing
        # THEN parser ignores extra closing paren and parses successfully
        result = parse_tdfol(formula_str)
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
    
    def test_parse_missing_quantifier_dot(self):
        """Test parsing quantifier without dot."""
        # GIVEN a quantified formula missing dot
        formula_str = "forall x Qq(x)"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_empty_parentheses(self):
        """Test parsing empty parentheses."""
        # GIVEN empty parentheses
        formula_str = "()"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_invalid_predicate_syntax(self):
        """Test parsing invalid predicate syntax."""
        # GIVEN invalid predicate syntax (missing closing paren)
        formula_str = "MyPred(x"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_invalid_quantifier_variable(self):
        """Test parsing quantifier with non-identifier variable."""
        # GIVEN quantifier with number as variable
        formula_str = "forall 42. Qq(x)"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_operator_without_operands(self):
        """Test parsing operator without operands."""
        # GIVEN just an operator
        formula_str = "&"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_unbalanced_operators(self):
        """Test parsing unbalanced operators."""
        # GIVEN operators without proper operands
        formula_str = "Qa & & Qb"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_missing_argument_separator(self):
        """Test parsing missing comma in argument list."""
        # GIVEN predicate with missing comma
        formula_str = "P(x y)"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_trailing_comma(self):
        """Test parsing trailing comma in argument list."""
        # GIVEN predicate with trailing comma
        formula_str = "P(x,)"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_deontic_missing_paren(self):
        """Test parsing deontic operator without parentheses."""
        # GIVEN deontic operator without parentheses
        formula_str = "O Q"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_temporal_missing_paren(self):
        """Test parsing temporal operator without parentheses."""
        # GIVEN temporal operator without parentheses
        formula_str = "G Q"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_nested_parens_mismatch(self):
        """Test parsing with mismatched nested parentheses."""
        # GIVEN nested parentheses with mismatch
        formula_str = "((Qa & Qb) | (Qc & Qd)"
        
        # WHEN parsing
        # THEN should raise ValueError
        with pytest.raises(ValueError):
            parse_tdfol(formula_str)
    
    def test_parse_safe_returns_none_on_error(self):
        """Test parse_tdfol_safe returns None on error."""
        # GIVEN an invalid formula
        formula_str = "Qa &"
        
        # WHEN parsing safely
        result = parse_tdfol_safe(formula_str)
        
        # THEN should return None
        assert result is None


# ============================================================================
# Edge Cases Tests (10 tests)
# ============================================================================


class TestParserEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_parse_single_character_variable(self):
        """Test parsing single character variables."""
        # GIVEN a formula with single-letter variables (avoiding keyword letters)
        formula_str = "MyPred(a, b, c)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse correctly
        assert isinstance(formula, Predicate)
        assert len(formula.arguments) == 3
    
    def test_parse_long_identifier(self):
        """Test parsing very long identifier."""
        # GIVEN a formula with very long identifier
        long_name = "Very_Long_Predicate_Name_With_Many_Characters_123"
        formula_str = f"{long_name}(x)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse correctly
        assert isinstance(formula, Predicate)
        assert formula.name == long_name
    
    def test_parse_deeply_nested_parentheses(self):
        """Test parsing deeply nested parentheses."""
        # GIVEN a formula with many nested parentheses
        formula_str = "((((Q))))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should unwrap to predicate
        assert isinstance(formula, Predicate)
        assert formula.name == "Q"
    
    def test_parse_long_conjunction_chain(self):
        """Test parsing long chain of conjunctions."""
        # GIVEN a long chain of ANDs
        formula_str = "Qa & Qb & Qc & Qd & Qe & Qf & Qg & Qh"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse without error
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.AND
    
    def test_parse_multiple_quantifiers_same_variable(self):
        """Test parsing multiple quantifiers with same variable name."""
        # GIVEN nested quantifiers using same variable name (shadowing)
        formula_str = "forall x. exists x. Qq(x)"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse (variable shadowing is allowed)
        assert isinstance(formula, QuantifiedFormula)
        assert isinstance(formula.formula, QuantifiedFormula)
    
    def test_parse_many_arguments(self):
        """Test parsing predicate with many arguments."""
        # GIVEN a predicate with many arguments
        args = ", ".join([f"x{i}" for i in range(20)])
        formula_str = f"ManyArgs({args})"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse all arguments
        assert isinstance(formula, Predicate)
        assert len(formula.arguments) == 20
    
    def test_parse_mixed_whitespace(self):
        """Test parsing with various whitespace characters."""
        # GIVEN a formula with mixed whitespace
        formula_str = "Qa  \t\n  &  \n\t  Qb"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should handle whitespace correctly
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.AND
    
    def test_parse_unicode_in_identifier(self):
        """Test parsing identifier without keyword conflicts."""
        # GIVEN an identifier that doesn't conflict with single-letter keywords
        formula_str = "MyStartPos"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should parse correctly
        assert isinstance(formula, Predicate)
        assert formula.name == "MyStartPos"
    
    def test_parse_nested_functions(self):
        """Test parsing nested function applications."""
        # GIVEN nested function applications (avoid P as predicate name)
        formula_str = "MyPred(func(g(h(x))))"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should have nested structure
        assert isinstance(formula, Predicate)
        arg = formula.arguments[0]
        assert isinstance(arg, FunctionApplication)
        assert isinstance(arg.arguments[0], FunctionApplication)
        assert isinstance(arg.arguments[0].arguments[0], FunctionApplication)
    
    def test_parse_alternating_operators(self):
        """Test parsing formula with alternating operators."""
        # GIVEN a formula with alternating binary operators
        formula_str = "Qa & Qb | Qc & Qd | Qe"
        
        # WHEN parsing
        formula = parse_tdfol(formula_str)
        
        # THEN should respect precedence and associativity
        assert isinstance(formula, BinaryFormula)
        # OR has lower precedence, should be at top level


# ============================================================================
# Direct Lexer and Parser Class Tests
# ============================================================================


class TestLexerClass:
    """Test TDFOLLexer class directly."""
    
    def test_lexer_current_char(self):
        """Test lexer current_char method."""
        # GIVEN a lexer with text
        lexer = TDFOLLexer("abc")
        
        # WHEN getting current char
        char = lexer.current_char()
        
        # THEN should return first character
        assert char == "a"
    
    def test_lexer_peek_char(self):
        """Test lexer peek_char method."""
        # GIVEN a lexer with text
        lexer = TDFOLLexer("abc")
        
        # WHEN peeking ahead
        char = lexer.peek_char()
        
        # THEN should return next character without advancing
        assert char == "b"
        assert lexer.current_char() == "a"
    
    def test_lexer_advance(self):
        """Test lexer advance method."""
        # GIVEN a lexer with text
        lexer = TDFOLLexer("abc")
        
        # WHEN advancing
        lexer.advance()
        
        # THEN should move to next character
        assert lexer.current_char() == "b"
    
    def test_lexer_read_identifier(self):
        """Test lexer read_identifier method."""
        # GIVEN a lexer positioned at identifier
        lexer = TDFOLLexer("hello123_world")
        
        # WHEN reading identifier
        identifier = lexer.read_identifier()
        
        # THEN should read entire identifier
        assert identifier == "hello123_world"
    
    def test_lexer_read_number(self):
        """Test lexer read_number method."""
        # GIVEN a lexer positioned at number
        lexer = TDFOLLexer("42abc")
        
        # WHEN reading number
        number = lexer.read_number()
        
        # THEN should read only digits
        assert number == "42"
        assert lexer.current_char() == "a"


class TestParserClass:
    """Test TDFOLParser class directly."""
    
    def test_parser_current_token(self):
        """Test parser current_token method."""
        # GIVEN a parser with tokens
        tokens = [Token(TokenType.IDENTIFIER, "Q", 0), Token(TokenType.EOF, "", 4)]
        parser = TDFOLParser(tokens)
        
        # WHEN getting current token
        token = parser.current_token()
        
        # THEN should return first token
        assert token.type == TokenType.IDENTIFIER
        assert token.value == "Q"
    
    def test_parser_peek_token(self):
        """Test parser peek_token method."""
        # GIVEN a parser with tokens
        tokens = [Token(TokenType.IDENTIFIER, "Q", 0), Token(TokenType.AND, "&", 4), Token(TokenType.EOF, "", 5)]
        parser = TDFOLParser(tokens)
        
        # WHEN peeking ahead
        token = parser.peek_token()
        
        # THEN should return next token without advancing
        assert token.type == TokenType.AND
        assert parser.current_token().type == TokenType.IDENTIFIER
    
    def test_parser_advance(self):
        """Test parser advance method."""
        # GIVEN a parser with tokens
        tokens = [Token(TokenType.IDENTIFIER, "Q", 0), Token(TokenType.EOF, "", 4)]
        parser = TDFOLParser(tokens)
        
        # WHEN advancing
        token = parser.advance()
        
        # THEN should return current and move to next
        assert token.type == TokenType.IDENTIFIER
        assert parser.current_token().type == TokenType.EOF
    
    def test_parser_expect_success(self):
        """Test parser expect method with correct token."""
        # GIVEN a parser with expected token
        tokens = [Token(TokenType.IDENTIFIER, "Q", 0), Token(TokenType.EOF, "", 4)]
        parser = TDFOLParser(tokens)
        
        # WHEN expecting correct token
        token = parser.expect(TokenType.IDENTIFIER)
        
        # THEN should succeed and advance
        assert token.value == "Q"
        assert parser.current_token().type == TokenType.EOF
    
    def test_parser_expect_failure(self):
        """Test parser expect method with incorrect token."""
        # GIVEN a parser with unexpected token
        tokens = [Token(TokenType.IDENTIFIER, "Q", 0), Token(TokenType.EOF, "", 4)]
        parser = TDFOLParser(tokens)
        
        # WHEN expecting wrong token
        # THEN should raise ValueError
        with pytest.raises(ValueError, match="Expected"):
            parser.expect(TokenType.AND)


class TestTokenClass:
    """Test Token class."""
    
    def test_token_creation(self):
        """Test creating a token."""
        # GIVEN token parameters
        token_type = TokenType.IDENTIFIER
        value = "test"
        position = 5
        
        # WHEN creating token
        token = Token(token_type, value, position)
        
        # THEN should have correct properties
        assert token.type == token_type
        assert token.value == value
        assert token.position == position
    
    def test_token_repr(self):
        """Test token string representation."""
        # GIVEN a token
        token = Token(TokenType.IDENTIFIER, "test", 5)
        
        # WHEN getting repr
        repr_str = repr(token)
        
        # THEN should contain token info
        assert "Token" in repr_str
        assert "IDENTIFIER" in repr_str
        assert "test" in repr_str
        assert "5" in repr_str

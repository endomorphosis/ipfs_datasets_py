"""
Tests for DCEC String to Formula Integration

Tests the complete pipeline from string expressions to Formula objects.
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.dcec_integration import (
    parse_expression_to_token,
    token_to_formula,
    parse_dcec_string,
    validate_formula,
    DCECParsingError,
)
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    ConnectiveFormula, LogicalConnective,
    DeonticFormula, DeonticOperator,
    CognitiveFormula, CognitiveOperator,
    TemporalFormula, TemporalOperator,
)
from ipfs_datasets_py.logic.CEC.native.dcec_parsing import ParseToken


class TestParseExpressionToToken:
    """Tests for parse_expression_to_token function."""
    
    def test_simple_expression(self):
        """GIVEN simple expression WHEN parsing to token THEN token created."""
        # GIVEN
        expr = "a"
        
        # WHEN
        token = parse_expression_to_token(expr)
        
        # THEN
        assert token is not None
        assert isinstance(token, ParseToken)
    
    def test_binary_operation(self):
        """GIVEN binary op WHEN parsing THEN token with operator."""
        # GIVEN
        expr = "a and b"
        
        # WHEN
        token = parse_expression_to_token(expr)
        
        # THEN
        assert token is not None
        assert token.func_name == "and"
    
    def test_nested_expression(self):
        """GIVEN nested expr WHEN parsing THEN nested token tree."""
        # GIVEN
        expr = "(a and b) or c"
        
        # WHEN
        token = parse_expression_to_token(expr)
        
        # THEN
        assert token is not None
        assert isinstance(token, ParseToken)
    
    def test_empty_expression(self):
        """GIVEN empty string WHEN parsing THEN returns None."""
        # GIVEN
        expr = ""
        
        # WHEN
        token = parse_expression_to_token(expr)
        
        # THEN
        assert token is None
    
    def test_unbalanced_parens(self):
        """GIVEN unbalanced parens WHEN parsing THEN raises error."""
        # GIVEN
        expr = "(a and b"
        
        # WHEN / THEN
        with pytest.raises(DCECParsingError):
            parse_expression_to_token(expr)
    
    def test_with_comments(self):
        """GIVEN expression with comments WHEN parsing THEN comments removed."""
        # GIVEN
        expr = "a and b ; this is a comment"
        
        # WHEN
        token = parse_expression_to_token(expr)
        
        # THEN
        assert token is not None


class TestTokenToFormula:
    """Tests for token_to_formula function."""
    
    def test_and_connective(self):
        """GIVEN AND token WHEN converting THEN ConnectiveFormula created."""
        # GIVEN
        token = ParseToken("and", ["a", "b"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.AND
    
    def test_or_connective(self):
        """GIVEN OR token WHEN converting THEN OR formula."""
        # GIVEN
        token = ParseToken("or", ["a", "b"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.OR
    
    def test_not_connective(self):
        """GIVEN NOT token WHEN converting THEN NOT formula."""
        # GIVEN
        token = ParseToken("not", ["a"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.NOT
    
    def test_implies_connective(self):
        """GIVEN IMPLIES token WHEN converting THEN IMPLIES formula."""
        # GIVEN
        token = ParseToken("implies", ["a", "b"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.IMPLIES
    
    def test_iff_connective(self):
        """GIVEN IFF token WHEN converting THEN IFF formula."""
        # GIVEN
        token = ParseToken("iff", ["a", "b"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.IFF
    
    def test_deontic_obligation(self):
        """GIVEN O token WHEN converting THEN DeonticFormula."""
        # GIVEN
        token = ParseToken("O", ["agent", "moment", "a"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, DeonticFormula)
        assert formula.operator == DeonticOperator.OBLIGATORY
    
    def test_cognitive_belief(self):
        """GIVEN B token WHEN converting THEN CognitiveFormula."""
        # GIVEN
        token = ParseToken("B", ["agent", "moment", "a"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, CognitiveFormula)
        assert formula.operator == CognitiveOperator.BELIEVES
    
    def test_cognitive_knowledge(self):
        """GIVEN K token WHEN converting THEN KNOWS formula."""
        # GIVEN
        token = ParseToken("K", ["agent", "moment", "a"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, CognitiveFormula)
        assert formula.operator == CognitiveOperator.KNOWS
    
    def test_temporal_always(self):
        """GIVEN ALWAYS token WHEN converting THEN TemporalFormula."""
        # GIVEN
        token = ParseToken("always", ["a"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, TemporalFormula)
        assert formula.operator == TemporalOperator.ALWAYS
    
    def test_temporal_eventually(self):
        """GIVEN EVENTUALLY token WHEN converting THEN EVENTUALLY formula."""
        # GIVEN
        token = ParseToken("eventually", ["a"])
        
        # WHEN
        formula = token_to_formula(token)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, TemporalFormula)
        assert formula.operator == TemporalOperator.EVENTUALLY


class TestParseDCECString:
    """Tests for parse_dcec_string function (complete pipeline)."""
    
    def test_simple_and(self):
        """GIVEN 'a and b' WHEN parsing THEN AND formula."""
        # GIVEN
        expr = "a and b"
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.AND
    
    def test_simple_or(self):
        """GIVEN 'a or b' WHEN parsing THEN OR formula."""
        # GIVEN
        expr = "a or b"
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.OR
    
    def test_implication(self):
        """GIVEN 'a -> b' WHEN parsing THEN IMPLIES formula."""
        # GIVEN
        expr = "a -> b"
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.IMPLIES
    
    def test_negation(self):
        """GIVEN 'not a' WHEN parsing THEN NOT formula."""
        # GIVEN
        expr = "not a"
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.NOT
    
    def test_nested_expression(self):
        """GIVEN nested expression WHEN parsing THEN nested formula."""
        # GIVEN
        expr = "(a and b) -> c"
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.IMPLIES
    
    def test_complex_expression(self):
        """GIVEN complex expression WHEN parsing THEN formula created."""
        # GIVEN
        expr = "(a or b) and (c or d)"
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
    
    def test_with_whitespace(self):
        """GIVEN expression with extra whitespace WHEN parsing THEN works."""
        # GIVEN
        expr = "  a   and   b  "
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
    
    def test_with_comments(self):
        """GIVEN expression with comments WHEN parsing THEN comments ignored."""
        # GIVEN
        expr = "a and b ; comment"
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
    
    def test_malformed_raises_error(self):
        """GIVEN malformed expression WHEN parsing THEN raises error."""
        # GIVEN
        expr = "((a and"
        
        # WHEN / THEN
        with pytest.raises(DCECParsingError):
            parse_dcec_string(expr)


class TestValidateFormula:
    """Tests for validate_formula function."""
    
    def test_valid_and_formula(self):
        """GIVEN valid AND formula WHEN validating THEN no errors."""
        # GIVEN
        formula = parse_dcec_string("a and b")
        
        # WHEN
        is_valid, errors = validate_formula(formula)
        
        # THEN
        assert is_valid is True
        assert len(errors) == 0
    
    def test_valid_implies_formula(self):
        """GIVEN valid IMPLIES formula WHEN validating THEN no errors."""
        # GIVEN
        formula = parse_dcec_string("a -> b")
        
        # WHEN
        is_valid, errors = validate_formula(formula)
        
        # THEN
        assert is_valid is True
        assert len(errors) == 0
    
    def test_valid_not_formula(self):
        """GIVEN valid NOT formula WHEN validating THEN no errors."""
        # GIVEN
        formula = parse_dcec_string("not a")
        
        # WHEN
        is_valid, errors = validate_formula(formula)
        
        # THEN
        assert is_valid is True
        assert len(errors) == 0


class TestEndToEndIntegration:
    """End-to-end integration tests."""
    
    def test_simple_logic(self):
        """GIVEN simple logic expr WHEN parsing THEN correct formula."""
        # GIVEN
        expressions = [
            "a and b",
            "a or b",
            "a -> b",
            "not a",
            "a <-> b",
        ]
        
        # WHEN / THEN
        for expr in expressions:
            formula = parse_dcec_string(expr)
            assert formula is not None, f"Failed to parse: {expr}"
            is_valid, errors = validate_formula(formula)
            assert is_valid, f"Invalid formula for: {expr}, errors: {errors}"
    
    def test_nested_logic(self):
        """GIVEN nested logic WHEN parsing THEN correct nesting."""
        # GIVEN
        expr = "((a and b) or c) -> d"
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)
        assert formula.operator == LogicalConnective.IMPLIES
        is_valid, _ = validate_formula(formula)
        assert is_valid
    
    def test_multiple_operators(self):
        """GIVEN multiple ops WHEN parsing THEN all handled."""
        # GIVEN
        expr = "a and b and c"
        
        # WHEN
        formula = parse_dcec_string(expr)
        
        # THEN
        assert formula is not None
        assert isinstance(formula, ConnectiveFormula)

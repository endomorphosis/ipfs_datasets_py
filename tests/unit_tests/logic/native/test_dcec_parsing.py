"""
Tests for DCEC Parsing System

Tests the core parsing functions ported from DCEC_Library/highLevelParsing.py
"""

import pytest
from ipfs_datasets_py.logic.native.dcec_parsing import (
    ParseToken,
    remove_comments,
    functorize_symbols,
    replace_synonyms,
    prefix_logical_functions,
    prefix_emdas,
)


class TestParseToken:
    """Tests for ParseToken dataclass."""
    
    def test_create_simple_token(self):
        """GIVEN func and args WHEN creating ParseToken THEN token created."""
        # GIVEN / WHEN
        token = ParseToken("and", ["a", "b"])
        
        # THEN
        assert token.func_name == "and"
        assert token.args == ["a", "b"]
    
    def test_depth_of_simple(self):
        """GIVEN simple token WHEN depth_of THEN returns 1."""
        # GIVEN
        token = ParseToken("and", ["a", "b"])
        
        # WHEN
        depth = token.depth_of()
        
        # THEN
        assert depth == 1
    
    def test_depth_of_nested(self):
        """GIVEN nested token WHEN depth_of THEN returns correct depth."""
        # GIVEN
        inner = ParseToken("or", ["x", "y"])
        token = ParseToken("and", ["a", inner])
        
        # WHEN
        depth = token.depth_of()
        
        # THEN
        assert depth == 2
    
    def test_width_of_simple(self):
        """GIVEN simple token WHEN width_of THEN counts leaf nodes."""
        # GIVEN
        token = ParseToken("and", ["a", "b", "c"])
        
        # WHEN
        width = token.width_of()
        
        # THEN
        assert width == 3
    
    def test_width_of_nested(self):
        """GIVEN nested token WHEN width_of THEN counts all leaves."""
        # GIVEN
        inner = ParseToken("or", ["x", "y"])
        token = ParseToken("and", ["a", inner, "b"])
        
        # WHEN
        width = token.width_of()
        
        # THEN
        assert width == 4  # a, x, y, b
    
    def test_create_s_expression(self):
        """GIVEN token WHEN create_s_expression THEN S-format created."""
        # GIVEN
        token = ParseToken("and", ["a", "b"])
        
        # WHEN
        s_expr = token.create_s_expression()
        
        # THEN
        assert s_expr == "(and a b)"
    
    def test_create_s_expression_nested(self):
        """GIVEN nested token WHEN create_s_expression THEN nested S-format."""
        # GIVEN
        inner = ParseToken("or", ["x", "y"])
        token = ParseToken("and", ["a", inner])
        
        # WHEN
        s_expr = token.create_s_expression()
        
        # THEN
        assert s_expr == "(and a (or x y))"
    
    def test_create_f_expression(self):
        """GIVEN token WHEN create_f_expression THEN F-format created."""
        # GIVEN
        token = ParseToken("and", ["a", "b"])
        
        # WHEN
        f_expr = token.create_f_expression()
        
        # THEN
        assert f_expr == "and(a,b)"
    
    def test_create_f_expression_nested(self):
        """GIVEN nested token WHEN create_f_expression THEN nested F-format."""
        # GIVEN
        inner = ParseToken("or", ["x", "y"])
        token = ParseToken("and", ["a", inner])
        
        # WHEN
        f_expr = token.create_f_expression()
        
        # THEN
        assert f_expr == "and(a,or(x,y))"
    
    def test_str_representation(self):
        """GIVEN token WHEN str() THEN returns F-expression."""
        # GIVEN
        token = ParseToken("and", ["a", "b"])
        
        # WHEN
        result = str(token)
        
        # THEN
        assert result == "and(a,b)"


class TestRemoveComments:
    """Tests for remove_comments function."""
    
    def test_remove_semicolon_comment(self):
        """GIVEN expression with ; comment WHEN remove_comments THEN removed."""
        # GIVEN
        expression = "(and a b) ; this is a comment"
        
        # WHEN
        result = remove_comments(expression)
        
        # THEN
        assert result == "(and a b) "
        assert ";" not in result
    
    def test_no_comment(self):
        """GIVEN no comment WHEN remove_comments THEN unchanged."""
        # GIVEN
        expression = "(and a b)"
        
        # WHEN
        result = remove_comments(expression)
        
        # THEN
        assert result == "(and a b)"
    
    def test_only_comment(self):
        """GIVEN only comment WHEN remove_comments THEN empty string."""
        # GIVEN
        expression = "; just a comment"
        
        # WHEN
        result = remove_comments(expression)
        
        # THEN
        assert result == ""


class TestFunctorizeSymbols:
    """Tests for functorize_symbols function."""
    
    def test_implies_arrow(self):
        """GIVEN -> WHEN functorize_symbols THEN becomes implies."""
        # GIVEN
        expression = "a -> b"
        
        # WHEN
        result = functorize_symbols(expression)
        
        # THEN
        assert "implies" in result
        assert "->" not in result
    
    def test_iff_arrow(self):
        """GIVEN <-> WHEN functorize_symbols THEN becomes ifAndOnlyIf."""
        # GIVEN
        expression = "a <-> b"
        
        # WHEN
        result = functorize_symbols(expression)
        
        # THEN
        assert "ifAndOnlyIf" in result
        assert "<->" not in result
    
    def test_arithmetic_operators(self):
        """GIVEN arithmetic ops WHEN functorize_symbols THEN function names."""
        # GIVEN
        expression = "x + y"
        
        # WHEN
        result = functorize_symbols(expression)
        
        # THEN
        assert "add" in result
    
    def test_comparison_operators(self):
        """GIVEN comparison WHEN functorize_symbols THEN function names."""
        # GIVEN
        expression = "x >= y"
        
        # WHEN
        result = functorize_symbols(expression)
        
        # THEN
        assert "greaterOrEqual" in result
    
    def test_not_operator(self):
        """GIVEN ~ WHEN functorize_symbols THEN becomes not."""
        # GIVEN
        expression = "~P"
        
        # WHEN
        result = functorize_symbols(expression)
        
        # THEN
        assert "not" in result


class TestReplaceSynonyms:
    """Tests for replace_synonyms function."""
    
    def test_forall_to_forAll(self):
        """GIVEN forall WHEN replace_synonyms THEN becomes forAll."""
        # GIVEN
        args = ["forall", "x", "P"]
        
        # WHEN
        replace_synonyms(args)
        
        # THEN
        assert args[0] == "forAll"
    
    def test_Time_to_Moment(self):
        """GIVEN Time WHEN replace_synonyms THEN becomes Moment."""
        # GIVEN
        args = ["Time", "t"]
        
        # WHEN
        replace_synonyms(args)
        
        # THEN
        assert args[0] == "Moment"
    
    def test_if_to_implies(self):
        """GIVEN if WHEN replace_synonyms THEN becomes implies."""
        # GIVEN
        args = ["if", "a", "b"]
        
        # WHEN
        replace_synonyms(args)
        
        # THEN
        assert args[0] == "implies"
    
    def test_no_synonyms(self):
        """GIVEN no synonyms WHEN replace_synonyms THEN unchanged."""
        # GIVEN
        args = ["and", "a", "b"]
        original = args.copy()
        
        # WHEN
        replace_synonyms(args)
        
        # THEN
        assert args == original


class TestPrefixLogicalFunctions:
    """Tests for prefix_logical_functions function."""
    
    def test_infix_and_to_prefix(self):
        """GIVEN a and b WHEN prefix_logical_functions THEN token created."""
        # GIVEN
        args = ["a", "and", "b"]
        atomics = {}
        
        # WHEN
        result = prefix_logical_functions(args, atomics)
        
        # THEN
        assert len(result) == 1
        assert isinstance(result[0], ParseToken)
        assert result[0].func_name == "and"
    
    def test_not_unary(self):
        """GIVEN not a WHEN prefix_logical_functions THEN unary token."""
        # GIVEN
        args = ["not", "a"]
        atomics = {}
        
        # WHEN
        result = prefix_logical_functions(args, atomics)
        
        # THEN
        assert len(result) == 1
        assert isinstance(result[0], ParseToken)
        assert result[0].func_name == "not"
        assert len(result[0].args) == 1
    
    def test_multiple_operators(self):
        """GIVEN multiple ops WHEN prefix_logical_functions THEN all converted."""
        # GIVEN
        args = ["a", "or", "b", "and", "c"]
        atomics = {}
        
        # WHEN
        result = prefix_logical_functions(args, atomics)
        
        # THEN
        # Should have nested ParseTokens
        assert any(isinstance(x, ParseToken) for x in result)
    
    def test_already_prefix(self):
        """GIVEN already prefix WHEN prefix_logical_functions THEN unchanged."""
        # GIVEN
        args = ["and", "a", "b"]
        atomics = {}
        
        # WHEN
        result = prefix_logical_functions(args, atomics)
        
        # THEN
        assert result == args
    
    def test_atomics_tracking(self):
        """GIVEN args WHEN prefix_logical_functions THEN atomics tracked."""
        # GIVEN
        args = ["a", "and", "b"]
        atomics = {}
        
        # WHEN
        prefix_logical_functions(args, atomics)
        
        # THEN
        assert "a" in atomics
        assert "b" in atomics
        assert "Boolean" in atomics["a"]


class TestPrefixEmdas:
    """Tests for prefix_emdas function."""
    
    def test_infix_add_to_prefix(self):
        """GIVEN x add y WHEN prefix_emdas THEN token created."""
        # GIVEN
        args = ["x", "add", "y"]
        atomics = {}
        
        # WHEN
        result = prefix_emdas(args, atomics)
        
        # THEN
        assert len(result) == 1
        assert isinstance(result[0], ParseToken)
        assert result[0].func_name == "add"
    
    def test_pemdas_order(self):
        """GIVEN x add y multiply z WHEN prefix_emdas THEN correct order."""
        # GIVEN
        args = ["x", "add", "y", "multiply", "z"]
        atomics = {}
        
        # WHEN
        result = prefix_emdas(args, atomics)
        
        # THEN
        # Should handle PEMDAS (multiply before add)
        assert any(isinstance(x, ParseToken) for x in result)
    
    def test_negate_unary(self):
        """GIVEN negate x WHEN prefix_emdas THEN unary token."""
        # GIVEN
        args = ["negate", "x"]
        atomics = {}
        
        # WHEN
        result = prefix_emdas(args, atomics)
        
        # THEN
        assert len(result) == 1
        assert isinstance(result[0], ParseToken)
        assert result[0].func_name == "negate"
    
    def test_atomics_numeric_tracking(self):
        """GIVEN arithmetic WHEN prefix_emdas THEN Numeric type tracked."""
        # GIVEN
        args = ["x", "add", "y"]
        atomics = {}
        
        # WHEN
        prefix_emdas(args, atomics)
        
        # THEN
        assert "x" in atomics
        assert "y" in atomics
        assert "Numeric" in atomics["x"]

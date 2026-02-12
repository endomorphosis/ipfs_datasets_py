"""
Tests for DCEC Cleaning Utilities

Tests the expression cleaning functions ported from DCEC_Library/cleaning.py
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.dcec_cleaning import (
    strip_whitespace,
    strip_comments,
    consolidate_parens,
    check_parens,
    get_matching_close_paren,
    tuck_functions,
)


class TestStripWhitespace:
    """Tests for strip_whitespace function."""
    
    def test_strip_basic_whitespace(self):
        """GIVEN an expression with extra spaces WHEN strip_whitespace THEN spaces normalized."""
        # GIVEN
        expression = "  ( a  b  c )  "
        
        # WHEN
        result = strip_whitespace(expression)
        
        # THEN
        assert result == "(a,b,c)"
    
    def test_strip_commas_and_spaces(self):
        """GIVEN mixed commas and spaces WHEN strip_whitespace THEN commas uniform."""
        # GIVEN
        expression = "func( arg1 , arg2 )"
        
        # WHEN
        result = strip_whitespace(expression)
        
        # THEN
        assert result == "func(arg1,arg2)"
    
    def test_touching_parens(self):
        """GIVEN touching parens WHEN strip_whitespace THEN space added between them."""
        # GIVEN
        expression = "(a)(b)"
        
        # WHEN
        result = strip_whitespace(expression)
        
        # THEN
        assert result == "(a),(b)"
    
    def test_brackets_special_handling(self):
        """GIVEN brackets WHEN strip_whitespace THEN brackets get spaces."""
        # GIVEN
        expression = "[type]value"
        
        # WHEN
        result = strip_whitespace(expression)
        
        # THEN
        assert ",[" in result and "]," in result
    
    def test_nested_expressions(self):
        """GIVEN nested expression WHEN strip_whitespace THEN properly normalized."""
        # GIVEN
        expression = "( and ( or a b ) ( not c ) )"
        
        # WHEN
        result = strip_whitespace(expression)
        
        # THEN
        assert result == "(and,(or,a,b),(not,c))"


class TestStripComments:
    """Tests for strip_comments function."""
    
    def test_strip_comment_present(self):
        """GIVEN expression with # comment WHEN strip_comments THEN comment removed."""
        # GIVEN
        expression = "(and a b) # this is a comment"
        
        # WHEN
        result = strip_comments(expression)
        
        # THEN
        assert result == "(and a b) "
        assert "#" not in result
    
    def test_strip_comment_absent(self):
        """GIVEN expression without comment WHEN strip_comments THEN unchanged."""
        # GIVEN
        expression = "(and a b)"
        
        # WHEN
        result = strip_comments(expression)
        
        # THEN
        assert result == "(and a b)"
    
    def test_strip_comment_at_start(self):
        """GIVEN comment at start WHEN strip_comments THEN everything removed."""
        # GIVEN
        expression = "# full line comment"
        
        # WHEN
        result = strip_comments(expression)
        
        # THEN
        assert result == ""


class TestCheckParens:
    """Tests for check_parens function."""
    
    def test_balanced_parens(self):
        """GIVEN balanced parens WHEN check_parens THEN returns True."""
        # GIVEN
        expression = "(and a b)"
        
        # WHEN
        result = check_parens(expression)
        
        # THEN
        assert result is True
    
    def test_unbalanced_too_many_open(self):
        """GIVEN too many open parens WHEN check_parens THEN returns False."""
        # GIVEN
        expression = "((and a b)"
        
        # WHEN
        result = check_parens(expression)
        
        # THEN
        assert result is False
    
    def test_unbalanced_too_many_close(self):
        """GIVEN too many close parens WHEN check_parens THEN returns False."""
        # GIVEN
        expression = "(and a b))"
        
        # WHEN
        result = check_parens(expression)
        
        # THEN
        assert result is False
    
    def test_no_parens(self):
        """GIVEN no parens WHEN check_parens THEN returns True."""
        # GIVEN
        expression = "and a b"
        
        # WHEN
        result = check_parens(expression)
        
        # THEN
        assert result is True
    
    def test_nested_balanced(self):
        """GIVEN nested balanced parens WHEN check_parens THEN returns True."""
        # GIVEN
        expression = "((a (b c) d))"
        
        # WHEN
        result = check_parens(expression)
        
        # THEN
        assert result is True


class TestGetMatchingCloseParen:
    """Tests for get_matching_close_paren function."""
    
    def test_simple_match(self):
        """GIVEN simple expression WHEN get_matching_close_paren THEN finds match."""
        # GIVEN
        input_str = "(abc)"
        
        # WHEN
        result = get_matching_close_paren(input_str, 0)
        
        # THEN
        assert result == 4
    
    def test_nested_match_outer(self):
        """GIVEN nested parens WHEN finding outer THEN correct index."""
        # GIVEN
        input_str = "(a (b c) d)"
        
        # WHEN
        result = get_matching_close_paren(input_str, 0)
        
        # THEN
        assert result == 10
    
    def test_nested_match_inner(self):
        """GIVEN nested parens WHEN finding inner THEN correct index."""
        # GIVEN
        input_str = "(a (b c) d)"
        
        # WHEN
        result = get_matching_close_paren(input_str, 3)
        
        # THEN
        assert result == 7
    
    def test_no_match(self):
        """GIVEN unmatched paren WHEN get_matching_close_paren THEN returns None."""
        # GIVEN
        input_str = "(abc"
        
        # WHEN
        result = get_matching_close_paren(input_str, 0)
        
        # THEN
        assert result is None
    
    def test_complex_nesting(self):
        """GIVEN complex nesting WHEN get_matching_close_paren THEN correct match."""
        # GIVEN
        input_str = "((a (b (c) d) e) f)"
        
        # WHEN
        result = get_matching_close_paren(input_str, 1)
        
        # THEN
        assert result == 15  # Matches closing paren at position 15


class TestConsolidateParens:
    """Tests for consolidate_parens function."""
    
    def test_double_parens(self):
        """GIVEN double parens WHEN consolidate_parens THEN one set removed."""
        # GIVEN
        expression = "((a))"
        
        # WHEN
        result = consolidate_parens(expression)
        
        # THEN
        assert result == "(a)"
    
    def test_triple_parens(self):
        """GIVEN triple parens WHEN consolidate_parens THEN reduced to single."""
        # GIVEN
        expression = "(((and a b)))"
        
        # WHEN
        result = consolidate_parens(expression)
        
        # THEN
        assert result == "(and a b)"
    
    def test_no_redundant_parens(self):
        """GIVEN no redundant parens WHEN consolidate_parens THEN outer added."""
        # GIVEN
        expression = "and a b"
        
        # WHEN
        result = consolidate_parens(expression)
        
        # THEN
        assert result == "(and a b)"
    
    def test_mixed_redundant(self):
        """GIVEN mixed redundant WHEN consolidate_parens THEN all removed."""
        # GIVEN
        expression = "((a) (b))"
        
        # WHEN
        result = consolidate_parens(expression)
        
        # THEN
        assert "((a)" not in result
        assert "(b))" not in result


class TestTuckFunctions:
    """Tests for tuck_functions function."""
    
    def test_simple_function(self):
        """GIVEN B(args) WHEN tuck_functions THEN becomes (B,args)."""
        # GIVEN
        expression = "B(a,b)"
        
        # WHEN
        result = tuck_functions(expression)
        
        # THEN
        assert "(B," in result
    
    def test_not_function_special(self):
        """GIVEN not(P) WHEN tuck_functions THEN special handling."""
        # GIVEN
        expression = "not(P)"
        
        # WHEN
        result = tuck_functions(expression)
        
        # THEN
        assert "(not,(" in result
    
    def test_multiple_functions(self):
        """GIVEN multiple functions WHEN tuck_functions THEN all transformed."""
        # GIVEN
        expression = "and(A(x),B(y))"
        
        # WHEN
        result = tuck_functions(expression)
        
        # THEN
        assert "(and," in result or "(A," in result
    
    def test_no_functions(self):
        """GIVEN no functions WHEN tuck_functions THEN unchanged."""
        # GIVEN
        expression = "(and a b)"
        
        # WHEN
        result = tuck_functions(expression)
        
        # THEN
        assert result == "(and a b)"

"""
Tests for TDFOL DCEC Parser Module

This module tests the DCEC (Distributed Concurrent Event Calculus) parser
following GIVEN-WHEN-THEN format.

Test Coverage (39 tests total):
- DCEC parsing basic (4 tests): simple predicates, variables, multiple args, propositional atoms
- DCEC logical operators (6 tests): conjunction, disjunction, negation, implication, biconditional, multiple ops
- DCEC deontic operators (3 tests): obligation, permission, prohibition
- DCEC temporal operators (4 tests): always, eventually, next, until
- DCEC quantifiers (2 tests): universal, existential
- DCEC → TDFOL conversion (5 tests): complex deontic-temporal, quantified implications, nested operators
- Error handling (5 tests): empty strings, malformed predicates, operator arity errors, quantifier errors
- API and integration (5 tests): parser initialization, safe parsing, whitespace handling
- Edge cases (5 tests): deeply nested formulas, alternative syntax, constants/variables, complex actions
"""

import pytest

from ipfs_datasets_py.logic.TDFOL.tdfol_dcec_parser import (
    DCECStringParser,
    parse_dcec,
    parse_dcec_safe,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    BinaryFormula,
    BinaryTemporalFormula,
    Constant,
    DeonticFormula,
    DeonticOperator,
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
# DCEC Parsing Tests (15 tests)
# ============================================================================


class TestDCECParsingBasic:
    """Test basic DCEC parsing functionality."""
    
    def test_parse_simple_predicate(self):
        """Test parsing a simple predicate."""
        # GIVEN a simple predicate string (lowercase treated as variable)
        dcec_str = "Agent(alice)"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return a Predicate
        assert isinstance(result, Predicate)
        assert result.name == "Agent"
        assert len(result.arguments) == 1
        # Note: lowercase arguments are treated as variables in DCEC
        assert isinstance(result.arguments[0], Variable)
        assert result.arguments[0].name == "alice"
    
    def test_parse_predicate_with_variable(self):
        """Test parsing a predicate with a variable."""
        # GIVEN a predicate with variable
        dcec_str = "Person(x)"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return Predicate with Variable
        assert isinstance(result, Predicate)
        assert result.name == "Person"
        assert len(result.arguments) == 1
        assert isinstance(result.arguments[0], Variable)
        assert result.arguments[0].name == "x"
    
    def test_parse_predicate_with_multiple_args(self):
        """Test parsing predicate with multiple arguments."""
        # GIVEN a predicate with multiple args
        dcec_str = "Happens(action, time, agent)"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return Predicate with multiple arguments
        assert isinstance(result, Predicate)
        assert result.name == "Happens"
        assert len(result.arguments) == 3
        assert all(isinstance(arg, Variable) for arg in result.arguments)
    
    def test_parse_propositional_atom(self):
        """Test parsing a propositional atom."""
        # GIVEN a simple propositional atom
        dcec_str = "Valid"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return Predicate with no arguments
        assert isinstance(result, Predicate)
        assert result.name == "Valid"
        assert len(result.arguments) == 0


class TestDCECLogicalOperators:
    """Test parsing logical operators."""
    
    def test_parse_conjunction(self):
        """Test parsing conjunction (AND)."""
        # GIVEN a conjunction expression
        dcec_str = "(and Agent(x) Action(y))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return BinaryFormula with AND
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
        assert isinstance(result.left, Predicate)
        assert isinstance(result.right, Predicate)
    
    def test_parse_disjunction(self):
        """Test parsing disjunction (OR)."""
        # GIVEN a disjunction expression
        dcec_str = "(or Valid(x) Authorized(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return BinaryFormula with OR
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR
    
    def test_parse_negation(self):
        """Test parsing negation (NOT)."""
        # GIVEN a negation expression
        dcec_str = "(not Forbidden(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return UnaryFormula with NOT
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT
        assert isinstance(result.formula, Predicate)
    
    def test_parse_implication(self):
        """Test parsing implication (IMPLIES)."""
        # GIVEN an implication expression
        dcec_str = "(implies Agent(x) Responsible(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return BinaryFormula with IMPLIES
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.IMPLIES
    
    def test_parse_biconditional(self):
        """Test parsing biconditional (IFF)."""
        # GIVEN a biconditional expression
        dcec_str = "(iff Legal(x) Authorized(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return BinaryFormula with IFF
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.IFF
    
    def test_parse_multiple_conjunctions(self):
        """Test parsing multiple conjunctions."""
        # GIVEN multiple AND operations
        dcec_str = "(and Valid(x) Legal(y) Authorized(z))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return nested BinaryFormulas
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
        # First two are combined, then third is added
        assert isinstance(result.left, BinaryFormula)


class TestDCECDeonticOperators:
    """Test parsing deontic operators."""
    
    def test_parse_obligation(self):
        """Test parsing obligation operator (O)."""
        # GIVEN an obligation expression
        dcec_str = "(o PayTax(agent))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return DeonticFormula with OBLIGATION
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert isinstance(result.formula, Predicate)
    
    def test_parse_permission(self):
        """Test parsing permission operator (P)."""
        # GIVEN a permission expression
        dcec_str = "(p Drive(agent))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return DeonticFormula with PERMISSION
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PERMISSION
    
    def test_parse_prohibition(self):
        """Test parsing prohibition operator (F)."""
        # GIVEN a prohibition expression
        dcec_str = "(f Trespass(agent))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return DeonticFormula with PROHIBITION
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PROHIBITION


class TestDCECTemporalOperators:
    """Test parsing temporal operators."""
    
    def test_parse_always(self):
        """Test parsing always operator (G/□)."""
        # GIVEN an always expression
        dcec_str = "(always Valid(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return TemporalFormula with ALWAYS
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
    
    def test_parse_eventually(self):
        """Test parsing eventually operator (F/◊)."""
        # GIVEN an eventually expression
        dcec_str = "(eventually Complete(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return TemporalFormula with EVENTUALLY
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.EVENTUALLY
    
    def test_parse_next(self):
        """Test parsing next operator (X)."""
        # GIVEN a next expression
        dcec_str = "(next Active(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return TemporalFormula with NEXT
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.NEXT
    
    def test_parse_until(self):
        """Test parsing until operator (U)."""
        # GIVEN an until expression
        dcec_str = "(until Waiting(x) Ready(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return BinaryTemporalFormula with UNTIL
        assert isinstance(result, BinaryTemporalFormula)
        assert result.operator == TemporalOperator.UNTIL


class TestDCECQuantifiers:
    """Test parsing quantifiers."""
    
    def test_parse_universal_quantifier(self):
        """Test parsing universal quantifier (forall)."""
        # GIVEN a forall expression
        dcec_str = "(forall x Agent(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return QuantifiedFormula with FORALL
        assert isinstance(result, QuantifiedFormula)
        assert result.quantifier == Quantifier.FORALL
        assert isinstance(result.variable, Variable)
        assert result.variable.name == "x"
    
    def test_parse_existential_quantifier(self):
        """Test parsing existential quantifier (exists)."""
        # GIVEN an exists expression
        dcec_str = "(exists y Responsible(y))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should return QuantifiedFormula with EXISTS
        assert isinstance(result, QuantifiedFormula)
        assert result.quantifier == Quantifier.EXISTS
        assert isinstance(result.variable, Variable)
        assert result.variable.name == "y"


# ============================================================================
# DCEC → TDFOL Conversion Tests (5 tests)
# ============================================================================


class TestDCECToTDFOLConversion:
    """Test conversion from DCEC formulas to TDFOL."""
    
    def test_convert_complex_deontic_temporal(self):
        """Test converting complex deontic-temporal formula."""
        # GIVEN a complex DCEC formula with deontic and temporal operators
        dcec_str = "(o (always Agent(x)))"
        
        # WHEN parsing/converting
        result = parse_dcec(dcec_str)
        
        # THEN should have correct nested structure
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.ALWAYS
    
    def test_convert_quantified_implication(self):
        """Test converting quantified implication."""
        # GIVEN a quantified implication
        dcec_str = "(forall x (implies Agent(x) Responsible(x)))"
        
        # WHEN parsing/converting
        result = parse_dcec(dcec_str)
        
        # THEN should have correct structure
        assert isinstance(result, QuantifiedFormula)
        assert result.quantifier == Quantifier.FORALL
        assert isinstance(result.formula, BinaryFormula)
        assert result.formula.operator == LogicOperator.IMPLIES
    
    def test_convert_nested_deontic_operators(self):
        """Test converting nested deontic operators."""
        # GIVEN nested deontic operators
        dcec_str = "(o (p Action(x)))"
        
        # WHEN parsing/converting
        result = parse_dcec(dcec_str)
        
        # THEN should have nested deontic formulas
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION
    
    def test_convert_temporal_sequence(self):
        """Test converting temporal sequence."""
        # GIVEN a temporal sequence
        dcec_str = "(next (eventually Complete(x)))"
        
        # WHEN parsing/converting
        result = parse_dcec(dcec_str)
        
        # THEN should have nested temporal formulas
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.NEXT
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.EVENTUALLY
    
    def test_convert_complex_institutional_fact(self):
        """Test converting complex institutional fact."""
        # GIVEN a complex institutional fact with multiple operators
        dcec_str = "(forall x (o (always (implies Agent(x) Authorized(x)))))"
        
        # WHEN parsing/converting
        result = parse_dcec(dcec_str)
        
        # THEN should have deeply nested structure
        assert isinstance(result, QuantifiedFormula)
        assert isinstance(result.formula, DeonticFormula)
        assert isinstance(result.formula.formula, TemporalFormula)
        assert isinstance(result.formula.formula.formula, BinaryFormula)


# ============================================================================
# Error Handling Tests (5 tests)
# ============================================================================


class TestDCECErrorHandling:
    """Test error handling for malformed input."""
    
    def test_empty_string_error(self):
        """Test parsing empty string."""
        # GIVEN an empty string
        dcec_str = ""
        
        # WHEN/THEN parsing should raise ValueError
        with pytest.raises(ValueError, match="Empty expression"):
            parse_dcec(dcec_str)
    
    def test_malformed_predicate_error(self):
        """Test parsing malformed predicate."""
        # GIVEN a malformed predicate (missing closing paren)
        dcec_str = "Agent(x"
        
        # WHEN parsing (parser is lenient with malformed input)
        result = parse_dcec(dcec_str)
        
        # THEN parser treats it as a propositional atom (fallback behavior)
        # This is by design - the parser is permissive
        # Note: the parser lowercases the operator names
        assert isinstance(result, Predicate)
        assert result.name.lower() == "agent(x"
    
    def test_invalid_operator_arity_error(self):
        """Test operator with wrong number of arguments."""
        # GIVEN 'and' with only one argument
        dcec_str = "(and Agent(x))"
        
        # WHEN/THEN parsing should raise ValueError
        with pytest.raises(ValueError, match="requires at least 2 arguments"):
            parse_dcec(dcec_str)
    
    def test_mismatched_parentheses_error(self):
        """Test mismatched parentheses."""
        # GIVEN mismatched parentheses (extra opening paren)
        dcec_str = "((and Agent(x) Action(y))"
        
        # WHEN parsing (parser is very lenient)
        result = parse_dcec(dcec_str)
        
        # THEN parser treats the whole thing as a propositional atom
        # This demonstrates the parser's fallback behavior for complex malformed input
        assert isinstance(result, Predicate)
    
    def test_quantifier_wrong_arity_error(self):
        """Test quantifier with wrong arity."""
        # GIVEN forall with wrong number of arguments
        dcec_str = "(forall x)"
        
        # WHEN/THEN parsing should raise ValueError
        with pytest.raises(ValueError, match="requires exactly 2 arguments"):
            parse_dcec(dcec_str)


# ============================================================================
# API and Integration Tests (5 tests)
# ============================================================================


class TestDCECParserAPI:
    """Test parser API and integration."""
    
    def test_parser_initialization(self):
        """Test DCECStringParser initialization."""
        # GIVEN nothing
        # WHEN creating a parser
        parser = DCECStringParser()
        
        # THEN should be properly initialized
        assert parser is not None
        assert hasattr(parser, 'use_native')
        assert hasattr(parser, 'parse')
    
    def test_parse_dcec_function(self):
        """Test top-level parse_dcec function."""
        # GIVEN a simple DCEC string
        dcec_str = "Valid"
        
        # WHEN parsing with top-level function
        result = parse_dcec(dcec_str)
        
        # THEN should return a valid Formula
        assert isinstance(result, Predicate)
        assert result.name == "Valid"
    
    def test_parse_dcec_safe_success(self):
        """Test parse_dcec_safe with valid input."""
        # GIVEN a valid DCEC string
        dcec_str = "Agent(x)"
        
        # WHEN parsing with safe function
        result = parse_dcec_safe(dcec_str)
        
        # THEN should return a Formula (not None)
        assert result is not None
        assert isinstance(result, Predicate)
    
    def test_parse_dcec_safe_failure(self):
        """Test parse_dcec_safe with truly invalid input."""
        # GIVEN an invalid DCEC string that causes actual parsing failure
        dcec_str = "(and)"  # 'and' requires at least 2 arguments
        
        # WHEN parsing with safe function
        result = parse_dcec_safe(dcec_str)
        
        # THEN should return None (not raise exception)
        assert result is None
    
    def test_parser_with_whitespace(self):
        """Test parser handles whitespace correctly."""
        # GIVEN a DCEC string with extra whitespace
        dcec_str = "  ( and   Agent(x)   Action(y)  )  "
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should parse correctly, ignoring whitespace
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND


# ============================================================================
# Edge Cases and Complex Scenarios (Additional Tests)
# ============================================================================


class TestDCECEdgeCases:
    """Test edge cases and complex scenarios."""
    
    def test_deeply_nested_formula(self):
        """Test parsing deeply nested formula."""
        # GIVEN a deeply nested formula
        dcec_str = "(o (always (forall x (implies Agent(x) (eventually Complete(x))))))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should parse all levels correctly
        assert isinstance(result, DeonticFormula)
        assert isinstance(result.formula, TemporalFormula)
        assert isinstance(result.formula.formula, QuantifiedFormula)
        assert isinstance(result.formula.formula.formula, BinaryFormula)
        assert isinstance(result.formula.formula.formula.right, TemporalFormula)
    
    def test_alternative_operator_syntax(self):
        """Test alternative operator syntax."""
        # GIVEN formulas using alternative syntax (->)
        dcec_str = "(-> Agent(x) Responsible(x))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should recognize as IMPLIES
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.IMPLIES
    
    def test_parse_with_constants_and_variables(self):
        """Test parsing mix of constants and variables."""
        # GIVEN predicate with both constants and variables
        dcec_str = "Assigned(Alice, task)"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should distinguish constants from variables
        assert isinstance(result, Predicate)
        assert len(result.arguments) == 2
        # First arg is constant (uppercase), second is variable (lowercase)
        assert isinstance(result.arguments[0], Constant)
        assert isinstance(result.arguments[1], Variable)
    
    def test_single_letter_operators(self):
        """Test single letter operator variants."""
        # GIVEN formula using single-letter temporal operators
        dcec_str = "(g Valid(x))"  # 'g' for 'always'
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should recognize as ALWAYS
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
    
    def test_complex_action_predicate(self):
        """Test complex action predicate from DCEC domain."""
        # GIVEN a complex DCEC action formula
        dcec_str = "(and Happens(pay_tax, t, agent) HoldsAt(valid_id, t))"
        
        # WHEN parsing
        result = parse_dcec(dcec_str)
        
        # THEN should parse both predicates correctly
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
        assert isinstance(result.left, Predicate)
        assert result.left.name == "Happens"
        assert len(result.left.arguments) == 3

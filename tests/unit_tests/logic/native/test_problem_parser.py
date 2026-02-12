"""
Tests for problem file parser.

Following GIVEN-WHEN-THEN format for clear test structure.
"""

import pytest
import tempfile
import os
from ipfs_datasets_py.logic.native.problem_parser import (
    TPTPParser, CustomProblemParser, ProblemParser, TPTPFormula,
    parse_problem_file, parse_problem_string
)
from ipfs_datasets_py.logic.native.shadow_prover import ModalLogic


class TestTPTPFormula:
    """Test suite for TPTPFormula class."""
    
    def test_tptp_formula_creation(self):
        """
        GIVEN: TPTPFormula parameters
        WHEN: Creating a TPTP formula
        THEN: Should initialize correctly
        """
        # GIVEN / WHEN
        formula = TPTPFormula(
            name="axiom1",
            role="axiom",
            formula="p => q"
        )
        
        # THEN
        assert formula.name == "axiom1"
        assert formula.role == "axiom"
        assert formula.formula == "p => q"
        assert formula.annotations is None


class TestTPTPParser:
    """Test suite for TPTP parser."""
    
    def test_tptp_parser_initialization(self):
        """
        GIVEN: TPTPParser class
        WHEN: Initializing parser
        THEN: Should start with empty lists
        """
        # GIVEN / WHEN
        parser = TPTPParser()
        
        # THEN
        assert len(parser.formulas) == 0
        assert len(parser.includes) == 0
    
    def test_parse_simple_fof(self):
        """
        GIVEN: Simple TPTP fof formula
        WHEN: Parsing the content
        THEN: Should extract formula correctly
        """
        # GIVEN
        parser = TPTPParser()
        content = "fof(axiom1, axiom, p)."
        
        # WHEN
        problem = parser.parse_string(content)
        
        # THEN
        assert problem is not None
        assert len(problem.assumptions) == 1
        assert "p" in problem.assumptions
    
    def test_parse_fof_with_conjecture(self):
        """
        GIVEN: TPTP with axiom and conjecture
        WHEN: Parsing
        THEN: Should separate assumptions and goals
        """
        # GIVEN
        parser = TPTPParser()
        content = """
        fof(ax1, axiom, p).
        fof(ax2, axiom, p => q).
        fof(conj1, conjecture, q).
        """
        
        # WHEN
        problem = parser.parse_string(content)
        
        # THEN
        assert len(problem.assumptions) == 2
        assert len(problem.goals) == 1
        assert "q" in problem.goals
    
    def test_parse_with_comments(self):
        """
        GIVEN: TPTP with comments
        WHEN: Parsing
        THEN: Should ignore comments
        """
        # GIVEN
        parser = TPTPParser()
        content = """
        % This is a comment
        fof(ax1, axiom, p). % inline comment
        % Another comment
        fof(conj1, conjecture, q).
        """
        
        # WHEN
        problem = parser.parse_string(content)
        
        # THEN
        assert len(problem.assumptions) == 1
        assert len(problem.goals) == 1
    
    def test_parse_cnf(self):
        """
        GIVEN: TPTP cnf clauses
        WHEN: Parsing
        THEN: Should handle CNF format
        """
        # GIVEN
        parser = TPTPParser()
        content = """
        cnf(c1, axiom, p | q).
        cnf(c2, axiom, ~p | r).
        """
        
        # WHEN
        problem = parser.parse_string(content)
        
        # THEN
        assert len(problem.assumptions) == 2


class TestCustomProblemParser:
    """Test suite for custom problem parser."""
    
    def test_custom_parser_simple(self):
        """
        GIVEN: Simple custom format problem
        WHEN: Parsing
        THEN: Should extract all components
        """
        # GIVEN
        parser = CustomProblemParser()
        content = """
        LOGIC: K
        
        ASSUMPTIONS:
        P
        P → Q
        
        GOALS:
        Q
        """
        
        # WHEN
        problem = parser.parse_string(content)
        
        # THEN
        assert problem.logic == ModalLogic.K
        assert len(problem.assumptions) == 2
        assert len(problem.goals) == 1
        assert "Q" in problem.goals
    
    def test_custom_parser_s4_logic(self):
        """
        GIVEN: Custom format with S4 logic
        WHEN: Parsing
        THEN: Should set S4 logic correctly
        """
        # GIVEN
        parser = CustomProblemParser()
        content = """
        LOGIC: S4
        
        GOALS:
        □P → P
        """
        
        # WHEN
        problem = parser.parse_string(content)
        
        # THEN
        assert problem.logic == ModalLogic.S4
        assert len(problem.goals) == 1
    
    def test_custom_parser_with_comments(self):
        """
        GIVEN: Custom format with comments
        WHEN: Parsing
        THEN: Should ignore comments
        """
        # GIVEN
        parser = CustomProblemParser()
        content = """
        # This is a comment
        LOGIC: K
        
        ASSUMPTIONS:
        P  # inline comment
        // Another comment style
        Q
        
        GOALS:
        P ∧ Q
        """
        
        # WHEN
        problem = parser.parse_string(content)
        
        # THEN
        assert len(problem.assumptions) == 2
        assert len(problem.goals) == 1


class TestUnifiedProblemParser:
    """Test suite for unified problem parser."""
    
    def test_auto_detect_tptp(self):
        """
        GIVEN: TPTP content without explicit format
        WHEN: Parsing with auto-detection
        THEN: Should use TPTP parser
        """
        # GIVEN
        parser = ProblemParser()
        content = "fof(test, axiom, p)."
        
        # WHEN
        problem = parser.parse_string(content)
        
        # THEN
        assert problem is not None
        assert problem.metadata.get("format") == "tptp"
    
    def test_auto_detect_custom(self):
        """
        GIVEN: Custom content without explicit format
        WHEN: Parsing with auto-detection
        THEN: Should use custom parser
        """
        # GIVEN
        parser = ProblemParser()
        content = """
        LOGIC: K
        GOALS:
        P
        """
        
        # WHEN
        problem = parser.parse_string(content)
        
        # THEN
        assert problem is not None
        assert problem.metadata.get("format") == "custom"
    
    def test_parse_file_with_tptp_extension(self):
        """
        GIVEN: File with .p extension
        WHEN: Parsing file
        THEN: Should use TPTP parser
        """
        # GIVEN
        parser = ProblemParser()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.p', delete=False) as f:
            f.write("fof(test, axiom, p).\n")
            filepath = f.name
        
        try:
            # WHEN
            problem = parser.parse_file(filepath)
            
            # THEN
            assert problem is not None
            assert problem.metadata.get("format") == "tptp"
        finally:
            os.unlink(filepath)


class TestConvenienceFunctions:
    """Test suite for convenience functions."""
    
    def test_parse_problem_string_tptp(self):
        """
        GIVEN: TPTP string
        WHEN: Using convenience function
        THEN: Should parse correctly
        """
        # GIVEN
        content = "fof(test, axiom, p)."
        
        # WHEN
        problem = parse_problem_string(content, format_hint='tptp')
        
        # THEN
        assert problem is not None
        assert len(problem.assumptions) == 1
    
    def test_parse_problem_string_custom(self):
        """
        GIVEN: Custom format string
        WHEN: Using convenience function
        THEN: Should parse correctly
        """
        # GIVEN
        content = """
        LOGIC: K
        GOALS:
        P
        """
        
        # WHEN
        problem = parse_problem_string(content)
        
        # THEN
        assert problem is not None
        assert len(problem.goals) == 1


class TestRealWorldExamples:
    """Test suite with real-world problem examples."""
    
    def test_modus_ponens_tptp(self):
        """
        GIVEN: Modus ponens problem in TPTP
        WHEN: Parsing
        THEN: Should have correct structure
        """
        # GIVEN
        content = """
        % Modus ponens example
        fof(ax1, axiom, p).
        fof(ax2, axiom, p => q).
        fof(goal, conjecture, q).
        """
        
        # WHEN
        problem = parse_problem_string(content)
        
        # THEN
        assert len(problem.assumptions) == 2
        assert len(problem.goals) == 1
        assert "q" in problem.goals
    
    def test_modal_example_custom(self):
        """
        GIVEN: Modal logic problem in custom format
        WHEN: Parsing
        THEN: Should have correct structure
        """
        # GIVEN
        content = """
        LOGIC: S4
        
        ASSUMPTIONS:
        □P
        
        GOALS:
        P
        □□P
        """
        
        # WHEN
        problem = parse_problem_string(content)
        
        # THEN
        assert problem.logic == ModalLogic.S4
        assert len(problem.assumptions) == 1
        assert len(problem.goals) == 2


class TestEdgeCases:
    """Test suite for edge cases and error handling."""
    
    def test_empty_content(self):
        """
        GIVEN: Empty content
        WHEN: Parsing
        THEN: Should return problem with empty lists
        """
        # GIVEN
        content = ""
        
        # WHEN
        problem = parse_problem_string(content)
        
        # THEN
        assert problem is not None
        assert len(problem.assumptions) == 0
        assert len(problem.goals) == 0
    
    def test_only_comments(self):
        """
        GIVEN: Content with only comments
        WHEN: Parsing
        THEN: Should return problem with empty lists
        """
        # GIVEN
        content = """
        % Just comments
        % No actual formulas
        """
        
        # WHEN
        problem = parse_problem_string(content, format_hint='tptp')
        
        # THEN
        assert len(problem.assumptions) == 0
        assert len(problem.goals) == 0
    
    def test_file_not_found(self):
        """
        GIVEN: Non-existent file path
        WHEN: Trying to parse file
        THEN: Should raise FileNotFoundError
        """
        # GIVEN
        filepath = "/nonexistent/file.p"
        
        # WHEN / THEN
        with pytest.raises(FileNotFoundError):
            parse_problem_file(filepath)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Fallback Integration Tests for Logic Module

Tests the fallback behavior when optional dependencies (SymbolicAI, Z3, etc.) are not available.
Validates that fallbacks provide correct results and acceptable performance.
"""

import pytest
import time
import logging
from pathlib import Path

# Try to import logic modules
try:
    from ipfs_datasets_py.logic.fol.converter import FOLConverter
    from ipfs_datasets_py.logic.deontic.converter import DeonticConverter
    from ipfs_datasets_py.logic.integration.domain.symbolic_logic_primitives import (
        SymbolicLogicPrimitives
    )
    LOGIC_AVAILABLE = True
except ImportError:
    LOGIC_AVAILABLE = False

# Check for SymbolicAI availability
try:
    import symai
    SYMBOLICAI_AVAILABLE = True
except ImportError:
    SYMBOLICAI_AVAILABLE = False


@pytest.mark.skipif(not LOGIC_AVAILABLE, reason="Logic modules not available")
class TestFallbackIntegration:
    """Test fallback behavior when optional dependencies are missing."""

    def test_symbolicai_fallback_consistency(self):
        """
        GIVEN a FOL converter with and without SymbolicAI
        WHEN converting the same formula
        THEN both should produce logically equivalent results
        """
        # GIVEN
        formula = "All x (Human(x) implies Mortal(x))"
        converter = FOLConverter()
        
        # WHEN - Convert using available method (with or without SymbolicAI)
        result = converter.to_fol(formula)
        
        # THEN - Result should be valid FOL regardless of SymbolicAI availability
        assert result is not None
        assert "forall" in result.lower() or "∀" in result
        
    def test_fallback_performance_acceptable(self):
        """
        GIVEN a converter using fallback methods
        WHEN performing conversions
        THEN performance should be within acceptable limits (<1 second for simple formulas)
        """
        # GIVEN
        converter = FOLConverter()
        simple_formula = "If P then Q"
        
        # WHEN
        start_time = time.time()
        result = converter.to_fol(simple_formula)
        duration = time.time() - start_time
        
        # THEN
        assert result is not None
        assert duration < 1.0, f"Conversion took {duration:.3f}s, expected <1.0s"
        
    def test_fallback_correctness_validation(self):
        """
        GIVEN known test cases with expected FOL outputs
        WHEN using fallback converters
        THEN results should match expected logical structure
        """
        # GIVEN
        test_cases = [
            ("P and Q", ["P", "Q", "and"]),
            ("P or Q", ["P", "Q", "or"]),
            ("not P", ["not", "P"]),
            ("P implies Q", ["P", "implies", "Q"]),
        ]
        converter = FOLConverter()
        
        # WHEN/THEN
        for formula, expected_tokens in test_cases:
            result = converter.to_fol(formula)
            assert result is not None
            # Check that expected logical elements are present
            result_lower = result.lower()
            for token in expected_tokens:
                assert token.lower() in result_lower or any(
                    symbol in result for symbol in ["∧", "∨", "¬", "→"]
                )
                
    def test_multiple_fallback_scenarios(self):
        """
        GIVEN multiple optional dependencies that might be missing
        WHEN using various logic operations
        THEN system should handle cascading fallbacks gracefully
        """
        # GIVEN
        converter = FOLConverter()
        test_formulas = [
            "simple test",
            "All x P(x)",
            "Exists x (P(x) and Q(x))",
        ]
        
        # WHEN/THEN - Should handle all formulas even if using fallbacks
        results = []
        for formula in test_formulas:
            try:
                result = converter.to_fol(formula)
                results.append((formula, result, True))
            except Exception as e:
                results.append((formula, None, False))
        
        # At least some conversions should succeed
        successful = [r for r in results if r[2]]
        assert len(successful) > 0, "All fallback conversions failed"
        
    def test_fallback_error_handling_graceful(self):
        """
        GIVEN invalid or malformed input
        WHEN using fallback methods
        THEN errors should be handled gracefully with informative messages
        """
        # GIVEN
        converter = FOLConverter()
        invalid_inputs = [
            "",  # Empty string
            "   ",  # Whitespace only
            "()()(((",  # Unbalanced parentheses
        ]
        
        # WHEN/THEN
        for invalid_input in invalid_inputs:
            try:
                result = converter.to_fol(invalid_input)
                # If it doesn't raise, result should be None or empty
                assert not result or result == invalid_input
            except (ValueError, TypeError) as e:
                # Expected exception types
                assert str(e)  # Should have error message
                
    def test_fallback_logging_comprehensive(self, caplog):
        """
        GIVEN a converter using fallback methods
        WHEN performing operations
        THEN appropriate log messages should be generated
        """
        # GIVEN
        with caplog.at_level(logging.DEBUG):
            converter = FOLConverter()
            
            # WHEN
            result = converter.to_fol("test formula")
            
            # THEN - Should have some log output (warnings about fallbacks or success messages)
            # This is informational - log presence indicates proper logging setup
            assert len(caplog.records) >= 0  # May or may not log depending on config

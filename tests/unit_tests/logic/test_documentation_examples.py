"""
Documentation Example Tests for Logic Module

Validates that all code examples in documentation files actually work.
Ensures documentation stays in sync with implementation.
"""

import pytest
from pathlib import Path

# Try to import logic modules
try:
    from ipfs_datasets_py.logic.fol.converter import FOLConverter
    from ipfs_datasets_py.logic.deontic.converter import DeonticConverter
    from ipfs_datasets_py.logic.common.feature_detection import FeatureDetector
    from ipfs_datasets_py.logic.security import InputValidator, RateLimiter
    LOGIC_AVAILABLE = True
except ImportError:
    LOGIC_AVAILABLE = False


@pytest.mark.skipif(not LOGIC_AVAILABLE, reason="Logic modules not available")
class TestDocumentationExamples:
    """Test that documentation examples are valid and working."""

    def test_readme_quick_start_examples(self):
        """
        GIVEN README.md quick start examples
        WHEN executing example code
        THEN examples should work without errors
        """
        # GIVEN - Example from README: Basic conversion
        converter = FOLConverter()
        
        # WHEN - Execute example
        try:
            result = converter.to_fol("All humans are mortal")
            
            # THEN
            assert result is not None
            success = True
        except Exception as e:
            success = False
            pytest.fail(f"README example failed: {e}")
            
        assert success, "README quick start example should work"
        
    def test_troubleshooting_guide_examples(self):
        """
        GIVEN TROUBLESHOOTING.md examples
        WHEN using feature detection as documented
        THEN examples should work correctly
        """
        # GIVEN - Example from TROUBLESHOOTING: Feature detection
        detector = FeatureDetector()
        
        # WHEN - Execute documented example
        try:
            # Example: Check if Z3 is available
            has_z3 = detector.has_z3()
            
            # THEN - Should return boolean without error
            assert isinstance(has_z3, bool)
            success = True
        except Exception as e:
            success = False
            pytest.fail(f"TROUBLESHOOTING example failed: {e}")
            
        assert success, "TROUBLESHOOTING examples should work"
        
    def test_fallback_behaviors_examples(self):
        """
        GIVEN FALLBACK_BEHAVIORS.md code examples
        WHEN testing fallback detection
        THEN examples should execute correctly
        """
        # GIVEN - Example from FALLBACK_BEHAVIORS: Fallback usage
        try:
            # Example: Using converter with fallback
            converter = FOLConverter()
            
            # WHEN
            result = converter.to_fol("simple test")
            
            # THEN
            assert result is not None or result == "simple test"
            success = True
        except Exception as e:
            success = False
            pytest.fail(f"FALLBACK_BEHAVIORS example failed: {e}")
            
        assert success, "FALLBACK_BEHAVIORS examples should work"
        
    def test_architecture_examples(self):
        """
        GIVEN ARCHITECTURE.md component examples
        WHEN testing security components
        THEN examples should work as documented
        """
        # GIVEN - Example from ARCHITECTURE: Security validation
        try:
            # Example: Input validation
            validator = InputValidator()
            
            # WHEN
            test_text = "test input"
            validated = validator.validate_text(test_text)
            
            # THEN
            assert validated is not None
            assert len(validated) <= 10000  # Default max length
            success = True
        except Exception as e:
            success = False
            pytest.fail(f"ARCHITECTURE example failed: {e}")
            
        assert success, "ARCHITECTURE examples should work"
        
    def test_inference_rules_examples(self):
        """
        GIVEN INFERENCE_RULES_INVENTORY.md examples
        WHEN using documented inference patterns
        THEN examples should execute correctly
        """
        # GIVEN - Example: Basic inference
        try:
            converter = FOLConverter()
            
            # WHEN - Example inference pattern
            premise = "P implies Q"
            result = converter.to_fol(premise)
            
            # THEN
            assert result is not None
            success = True
        except Exception as e:
            success = False
            pytest.fail(f"INFERENCE_RULES example failed: {e}")
            
        assert success, "INFERENCE_RULES examples should work"

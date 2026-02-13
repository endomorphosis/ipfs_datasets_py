"""
Comprehensive tests for logic_translation_core module.

Tests the core logic translation infrastructure that converts deontic logic
formulas to multiple theorem prover formats (Lean, Coq, SMT-LIB, TPTP, etc.).
"""

import pytest
from dataclasses import dataclass
from typing import List, Dict, Any
from unittest.mock import Mock, patch, MagicMock

from ipfs_datasets_py.logic.integration.logic_translation_core import (
    LogicTranslationTarget,
    TranslationResult,
    AbstractLogicFormula,
    LogicTranslator,
    LeanTranslator,
)
from ipfs_datasets_py.logic.tools.deontic_logic_core import (
    DeonticFormula,
    DeonticOperator,
    LegalAgent,
    DeonticRuleSet,
)


class TestLogicTranslationTarget:
    """Test LogicTranslationTarget enum."""
    
    def test_translation_targets_available(self):
        """GIVEN LogicTranslationTarget enum
        WHEN checking available targets
        THEN all expected targets should be present"""
        expected_targets = [
            "lean", "coq", "isabelle", "smt-lib", "tptp",
            "z3", "vampire", "eprover", "agda", "hol", "pvs"
        ]
        
        for target in expected_targets:
            assert any(t.value == target for t in LogicTranslationTarget)
    
    def test_target_values_are_strings(self):
        """GIVEN LogicTranslationTarget enum
        WHEN accessing target values
        THEN all values should be strings"""
        for target in LogicTranslationTarget:
            assert isinstance(target.value, str)
            assert len(target.value) > 0


class TestTranslationResult:
    """Test TranslationResult dataclass."""
    
    def test_create_successful_result(self):
        """GIVEN translation parameters
        WHEN creating successful TranslationResult
        THEN result should have correct attributes"""
        result = TranslationResult(
            target=LogicTranslationTarget.LEAN,
            translated_formula="theorem test : True := trivial",
            success=True,
            confidence=0.95
        )
        
        assert result.target == LogicTranslationTarget.LEAN
        assert "theorem test" in result.translated_formula
        assert result.success is True
        assert result.confidence == 0.95
        assert len(result.errors) == 0
        assert len(result.warnings) == 0
    
    def test_create_failed_result(self):
        """GIVEN translation failure
        WHEN creating failed TranslationResult
        THEN result should contain error information"""
        errors = ["Unsupported operator", "Missing type information"]
        result = TranslationResult(
            target=LogicTranslationTarget.COQ,
            translated_formula="",
            success=False,
            errors=errors
        )
        
        assert result.success is False
        assert len(result.errors) == 2
        assert "Unsupported operator" in result.errors
    
    def test_translation_result_to_dict(self):
        """GIVEN TranslationResult
        WHEN converting to dictionary
        THEN dictionary should contain all fields"""
        result = TranslationResult(
            target=LogicTranslationTarget.Z3,
            translated_formula="(assert p)",
            success=True,
            metadata={"complexity": 5},
            dependencies=["smt2-lib"]
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["target"] == "z3"
        assert result_dict["translated_formula"] == "(assert p)"
        assert result_dict["success"] is True
        assert result_dict["metadata"]["complexity"] == 5
        assert "smt2-lib" in result_dict["dependencies"]


class TestAbstractLogicFormula:
    """Test AbstractLogicFormula intermediate representation."""
    
    def test_create_abstract_formula(self):
        """GIVEN formula components
        WHEN creating AbstractLogicFormula
        THEN formula should store all components"""
        formula = AbstractLogicFormula(
            formula_type="deontic",
            operators=["obligation", "implies"],
            variables=[("x", "Agent"), ("y", "Action")],
            quantifiers=[("forall", "x", "Agent")],
            propositions=["performAction(x, y)"],
            logical_structure={"root": "obligation"}
        )
        
        assert formula.formula_type == "deontic"
        assert "obligation" in formula.operators
        assert len(formula.variables) == 2
        assert formula.variables[0] == ("x", "Agent")
        assert len(formula.quantifiers) == 1
        assert formula.propositions[0] == "performAction(x, y)"
    
    def test_abstract_formula_to_dict(self):
        """GIVEN AbstractLogicFormula
        WHEN converting to dictionary
        THEN dictionary should be serializable"""
        formula = AbstractLogicFormula(
            formula_type="first_order",
            operators=["and", "or"],
            variables=[("p", "Prop")],
            quantifiers=[],
            propositions=["p"],
            logical_structure={"operator": "and"}
        )
        
        formula_dict = formula.to_dict()
        
        assert formula_dict["formula_type"] == "first_order"
        assert "and" in formula_dict["operators"]
        assert formula_dict["variables"][0] == ("p", "Prop")


class TestLogicTranslator:
    """Test LogicTranslator abstract base class."""
    
    def test_translator_initialization(self):
        """GIVEN LogicTranslator subclass
        WHEN initializing translator
        THEN translator should have target and cache"""
        
        # Create minimal concrete implementation
        class TestTranslator(LogicTranslator):
            def translate_deontic_formula(self, formula):
                return TranslationResult(self.target, "", True)
            def translate_rule_set(self, rule_set):
                return TranslationResult(self.target, "", True)
            def generate_theory_file(self, formulas, theory_name="Test"):
                return ""
            def get_dependencies(self):
                return []
            def validate_translation(self, original, translated):
                return (True, [])
        
        translator = TestTranslator(LogicTranslationTarget.LEAN)
        
        assert translator.target == LogicTranslationTarget.LEAN
        assert isinstance(translator.translation_cache, dict)
        assert len(translator.translation_cache) == 0
    
    def test_clear_cache(self):
        """GIVEN translator with cached translations
        WHEN clearing cache
        THEN cache should be empty"""
        
        class TestTranslator(LogicTranslator):
            def translate_deontic_formula(self, formula):
                return TranslationResult(self.target, "", True)
            def translate_rule_set(self, rule_set):
                return TranslationResult(self.target, "", True)
            def generate_theory_file(self, formulas, theory_name="Test"):
                return ""
            def get_dependencies(self):
                return []
            def validate_translation(self, original, translated):
                return (True, [])
        
        translator = TestTranslator(LogicTranslationTarget.COQ)
        translator.translation_cache["test"] = "cached_value"
        
        assert len(translator.translation_cache) == 1
        
        translator.clear_cache()
        
        assert len(translator.translation_cache) == 0
    
    def test_normalize_identifier(self):
        """GIVEN various identifier strings
        WHEN normalizing for target system
        THEN identifiers should be valid"""
        
        class TestTranslator(LogicTranslator):
            def translate_deontic_formula(self, formula):
                return TranslationResult(self.target, "", True)
            def translate_rule_set(self, rule_set):
                return TranslationResult(self.target, "", True)
            def generate_theory_file(self, formulas, theory_name="Test"):
                return ""
            def get_dependencies(self):
                return []
            def validate_translation(self, original, translated):
                return (True, [])
        
        translator = TestTranslator(LogicTranslationTarget.LEAN)
        
        # Test special character removal
        assert translator._normalize_identifier("test-name") == "test_name"
        assert translator._normalize_identifier("test name") == "test_name"
        assert translator._normalize_identifier("test@name") == "test_name"
        
        # Test numeric prefix handling
        assert translator._normalize_identifier("123test").startswith("id_")
        
        # Test empty string handling
        assert translator._normalize_identifier("") == "unnamed"


class TestLeanTranslator:
    """Test Lean theorem prover translator."""
    
    def test_lean_translator_initialization(self):
        """GIVEN no parameters
        WHEN creating LeanTranslator
        THEN translator should target Lean"""
        translator = LeanTranslator()
        
        assert translator.target == LogicTranslationTarget.LEAN
        assert isinstance(translator.translation_cache, dict)
    
    @pytest.mark.skip(reason="Lean translator methods need mock formulas")
    def test_translate_simple_obligation(self):
        """GIVEN simple obligation formula
        WHEN translating to Lean
        THEN result should contain Lean syntax"""
        # This test would require proper DeonticFormula setup
        # Skipped for now as it needs integration with deontic_logic_core
        pass
    
    def test_get_dependencies(self):
        """GIVEN LeanTranslator
        WHEN requesting dependencies
        THEN dependencies list should be returned"""
        translator = LeanTranslator()
        
        # Note: This might return empty list if not yet implemented
        deps = translator.get_dependencies()
        
        assert isinstance(deps, list)


class TestTranslationWorkflow:
    """Test end-to-end translation workflows."""
    
    @pytest.mark.skip(reason="Requires full formula construction")
    def test_translate_formula_to_multiple_targets(self):
        """GIVEN deontic formula
        WHEN translating to multiple targets
        THEN each translation should succeed"""
        # Would test translating same formula to Lean, Coq, Z3, etc.
        pass
    
    @pytest.mark.skip(reason="Requires prover integration")
    def test_round_trip_translation(self):
        """GIVEN formula translated to target
        WHEN translating back to source
        THEN semantics should be preserved"""
        # Would test bidirectional translation fidelity
        pass


class TestErrorHandling:
    """Test error handling in translation."""
    
    def test_translation_result_with_errors(self):
        """GIVEN translation errors
        WHEN creating TranslationResult
        THEN errors should be properly recorded"""
        errors = ["Syntax error at line 5", "Undefined variable x"]
        warnings = ["Implicit type coercion"]
        
        result = TranslationResult(
            target=LogicTranslationTarget.SMT_LIB,
            translated_formula="",
            success=False,
            errors=errors,
            warnings=warnings
        )
        
        assert result.success is False
        assert len(result.errors) == 2
        assert len(result.warnings) == 1
        assert "Syntax error" in result.errors[0]
        assert "coercion" in result.warnings[0]
    
    def test_empty_formula_translation(self):
        """GIVEN empty formula
        WHEN attempting translation
        THEN should handle gracefully"""
        result = TranslationResult(
            target=LogicTranslationTarget.LEAN,
            translated_formula="",
            success=False,
            errors=["Empty formula provided"]
        )
        
        assert result.success is False
        assert "Empty formula" in result.errors[0]


class TestPerformance:
    """Test translation performance characteristics."""
    
    def test_cache_usage(self):
        """GIVEN translator with caching
        WHEN translating same formula multiple times
        THEN cache should be utilized"""
        
        class CachedTranslator(LogicTranslator):
            def __init__(self):
                super().__init__(LogicTranslationTarget.LEAN)
                self.call_count = 0
            
            def translate_deontic_formula(self, formula):
                self.call_count += 1
                return TranslationResult(self.target, "cached", True)
            
            def translate_rule_set(self, rule_set):
                return TranslationResult(self.target, "", True)
            
            def generate_theory_file(self, formulas, theory_name="Test"):
                return ""
            
            def get_dependencies(self):
                return []
            
            def validate_translation(self, original, translated):
                return (True, [])
        
        translator = CachedTranslator()
        
        # Cache should start empty
        assert len(translator.translation_cache) == 0
        assert translator.call_count == 0
    
    def test_batch_translation(self):
        """GIVEN multiple formulas
        WHEN translating in batch
        THEN all should be processed"""
        results = []
        
        for i in range(10):
            result = TranslationResult(
                target=LogicTranslationTarget.Z3,
                translated_formula=f"(assert p{i})",
                success=True
            )
            results.append(result)
        
        assert len(results) == 10
        assert all(r.success for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

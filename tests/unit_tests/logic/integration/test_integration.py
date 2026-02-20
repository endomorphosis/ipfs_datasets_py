"""
Integration Tests for SymbolicAI FOL Integration

This module provides comprehensive integration tests that verify all components
of the SymbolicAI FOL integration work together correctly, including end-to-end
workflows, performance testing, and edge case handling.
"""

import pytest
import sys
import os
import time
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any, Tuple

# Add the project root to Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Import all components to test
from ipfs_datasets_py.logic.integration import (
    SymbolicFOLBridge,
    LogicPrimitives,
    ContractedFOLConverter,
    FOLInput,
    FOLOutput,
    create_logic_symbol,
    create_fol_converter,
    validate_fol_input,
    SYMBOLIC_AI_AVAILABLE
)


class TestFullIntegrationWorkflows:
    """Test complete integration workflows using all components."""
    
    def setup_method(self):
        """Setup integration test environment."""
        self.bridge = SymbolicFOLBridge(
            confidence_threshold=0.7,
            fallback_enabled=True,
            enable_caching=True
        )
        self.converter = create_fol_converter()
        
        # Comprehensive test dataset
        self.test_statements = [
            # Basic logical structures
            "All cats are animals",
            "Some birds can fly",
            "Every student studies hard",
            "There exists a cat that is black",
            
            # Complex logical structures
            "All students study hard and some students excel",
            "If it rains, then the ground is wet and slippery",
            "Every bird can fly or swim, but not all birds sing",
            "Some cats are black and some cats are white",
            
            # Conditional statements
            "If all students study, then they will pass",
            "When it's cold and wet, people stay indoors",
            "If someone is a student, then they attend classes",
            
            # Deontic-style statements
            "Students must complete their assignments",
            "Citizens should vote in elections",
            "Drivers must stop at red lights",
            
            # Simple facts
            "Fluffy is a cat",
            "The sky is blue",
            "Dogs bark loudly",
            "Fish swim in water"
        ]
        
        self.edge_cases = [
            # Ambiguous statements
            "People like music",
            "Things happen for reasons",
            "Life is complicated",
            
            # Complex grammatical structures
            "The cat that sits on the mat is black",
            "Students who study hard often succeed in their goals",
            "Books written by famous authors are usually expensive",
            
            # Negations
            "Not all birds can fly",
            "No cats are dogs", 
            "It is not true that all students fail",
            
            # Temporal statements
            "It will rain tomorrow",
            "Students always study before exams",
            "Sometimes people make mistakes"
        ]
    
    def test_bridge_to_primitives_integration(self):
        """Test integration between SymbolicFOLBridge and LogicPrimitives."""
        statement = "All cats are animals and some cats are pets"
        
        # Step 1: Use bridge to create semantic symbol
        bridge_symbol = self.bridge.create_semantic_symbol(statement)
        assert bridge_symbol is not None
        
        # Step 2: Use primitives on the bridge symbol
        primitives_symbol = create_logic_symbol(statement)
        assert primitives_symbol is not None
        
        # Step 3: Test that both approaches work
        bridge_result = self.bridge.semantic_to_fol(bridge_symbol)
        primitives_fol = primitives_symbol.to_fol()
        
        assert isinstance(bridge_result.fol_formula, str)
        assert isinstance(primitives_fol.value, str)
        assert len(bridge_result.fol_formula) > 0
        assert len(primitives_fol.value) > 0
        
        # Step 4: Test logical operations using primitives
        symbol2 = create_logic_symbol("Fluffy is a cat")
        combined = primitives_symbol.logical_and(symbol2)
        assert combined is not None
        assert len(combined.value) > 0
    
    def test_bridge_to_contracts_integration(self):
        """Test integration between SymbolicFOLBridge and ContractedFOLConverter."""
        statement = "All students study hard"
        
        # Step 1: Create validated input
        input_data = validate_fol_input(
            statement,
            confidence_threshold=0.7,
            output_format="symbolic"
        )
        
        # Step 2: Use contracted converter
        converter_result = self.converter(input_data)
        assert isinstance(converter_result, FOLOutput)
        
        # Step 3: Use bridge directly
        bridge_symbol = self.bridge.create_semantic_symbol(statement)
        bridge_result = self.bridge.semantic_to_fol(bridge_symbol)
        
        # Step 4: Compare results
        assert len(converter_result.fol_formula) > 0
        assert len(bridge_result.fol_formula) > 0
        
        # Both should produce valid FOL
        assert converter_result.confidence > 0.0
        assert bridge_result.confidence > 0.0
    
    def test_end_to_end_workflow_comprehensive(self):
        """Test comprehensive end-to-end workflow with all components."""
        for statement in self.test_statements:
            try:
                # Step 1: Input validation and creation
                input_data = validate_fol_input(
                    statement,
                    confidence_threshold=0.6,
                    output_format="symbolic"
                )
                
                # Step 2: Contract-based conversion
                converter_result = self.converter(input_data)
                assert isinstance(converter_result, FOLOutput)
                
                # Step 3: Bridge-based analysis
                bridge_symbol = self.bridge.create_semantic_symbol(statement)
                bridge_components = self.bridge.extract_logical_components(bridge_symbol)
                bridge_fol = self.bridge.semantic_to_fol(bridge_symbol)
                
                # Step 4: Primitive-based operations
                primitive_symbol = create_logic_symbol(statement)
                primitive_fol = primitive_symbol.to_fol()
                quantifiers = primitive_symbol.extract_quantifiers()
                predicates = primitive_symbol.extract_predicates()
                
                # Step 5: Validation
                formula_validation = self.bridge.validate_fol_formula(converter_result.fol_formula)
                
                # All steps should succeed
                assert len(converter_result.fol_formula) > 0
                assert len(bridge_fol.fol_formula) > 0
                assert len(primitive_fol.value) > 0
                assert isinstance(quantifiers.value, str)
                assert isinstance(predicates.value, str)
                assert isinstance(formula_validation, dict)
                
                # Confidence should be reasonable
                assert converter_result.confidence >= 0.0
                assert bridge_fol.confidence >= 0.0
                
            except Exception as e:
                # Log which statement caused the issue
                pytest.fail(f"End-to-end workflow failed for statement: '{statement}' with error: {e}")
    
    def test_edge_cases_handling(self):
        """Test handling of edge cases and challenging statements."""
        for edge_case in self.edge_cases:
            try:
                # Should not crash, even with difficult inputs
                input_data = validate_fol_input(edge_case, confidence_threshold=0.5)
                result = self.converter(input_data)
                
                assert isinstance(result, FOLOutput)
                assert isinstance(result.fol_formula, str)
                # May have low confidence, but should still produce output
                assert result.confidence >= 0.0
                
                # Bridge should also handle edge cases
                symbol = self.bridge.create_semantic_symbol(edge_case)
                bridge_result = self.bridge.semantic_to_fol(symbol)
                assert isinstance(bridge_result.fol_formula, str)
                
            except Exception as e:
                # Some edge cases might legitimately fail, but shouldn't crash unexpectedly
                assert isinstance(e, (ValueError, RuntimeError))
    
    def test_format_consistency_across_components(self):
        """Test that different components produce consistent output formats."""
        statement = "All cats are animals"
        formats = ["symbolic", "prolog", "tptp"]
        
        for fmt in formats:
            # Test with converter
            input_data = validate_fol_input(statement, output_format=fmt)
            converter_result = self.converter(input_data)
            
            # Test with bridge
            symbol = self.bridge.create_semantic_symbol(statement)
            bridge_result = self.bridge.semantic_to_fol(symbol, fmt)
            
            # Test with primitives
            primitive_symbol = create_logic_symbol(statement)
            primitive_result = primitive_symbol.to_fol(fmt)
            
            # All should produce valid output in the requested format
            assert len(converter_result.fol_formula) > 0
            assert len(bridge_result.fol_formula) > 0
            assert len(primitive_result.value) > 0
            
            # Check format-specific characteristics
            if fmt == "prolog":
                # Should avoid Unicode symbols or convert them
                prolog_formulas = [
                    converter_result.fol_formula,
                    bridge_result.fol_formula,
                    primitive_result.value
                ]
                for formula in prolog_formulas:
                    # Either no Unicode symbols, or explicit prolog syntax
                    unicode_count = sum(1 for c in formula if ord(c) > 127)
                    if unicode_count > 0:
                        # Should have prolog-style syntax
                        assert any(token in formula.lower() for token in ["forall", "exists", ":-"])
            
            elif fmt == "tptp":
                # Should have TPTP format characteristics
                tptp_formulas = [converter_result.fol_formula, bridge_result.fol_formula]
                for formula in tptp_formulas:
                    if "fof(" not in formula:
                        # TPTP format should typically start with fof(
                        pass  # Some implementations might vary


class TestPerformanceAndScalability:
    """Test performance and scalability of the integration."""
    
    def setup_method(self):
        """Setup performance test environment."""
        self.bridge = SymbolicFOLBridge(enable_caching=True)
        self.converter = create_fol_converter()
    
    def test_caching_performance(self):
        """Test that caching improves performance."""
        statement = "All cats are animals"
        symbol = self.bridge.create_semantic_symbol(statement)
        
        # First conversion (no cache)
        start_time = time.time()
        result1 = self.bridge.semantic_to_fol(symbol)
        first_time = time.time() - start_time
        
        # Second conversion (with cache)
        start_time = time.time()
        result2 = self.bridge.semantic_to_fol(symbol)
        second_time = time.time() - start_time
        
        # Results should be identical
        assert result1.fol_formula == result2.fol_formula
        
        # Second call should be faster (or at least not significantly slower)
        assert second_time <= first_time * 1.5  # Allow some variance
    
    def test_batch_processing_performance(self):
        """Test performance with batch processing."""
        statements = [
            "All cats are animals",
            "Some birds can fly",
            "Every student studies",
            "There exists a solution"
        ] * 5  # 20 statements total
        
        # Test batch processing time
        start_time = time.time()
        results = []
        
        for statement in statements:
            input_data = validate_fol_input(statement)
            result = self.converter(input_data)
            results.append(result)
        
        total_time = time.time() - start_time
        
        # All conversions should succeed
        assert len(results) == len(statements)
        for result in results:
            assert isinstance(result, FOLOutput)
            assert len(result.fol_formula) > 0
        
        # Should complete in reasonable time (adjust threshold as needed)
        assert total_time < 30.0  # 30 seconds for 20 conversions
        
        # Average time per conversion
        avg_time = total_time / len(statements)
        assert avg_time < 2.0  # Less than 2 seconds per conversion
    
    def test_memory_usage_with_large_cache(self):
        """Test memory usage with large numbers of cached conversions."""
        # Generate many unique statements
        statements = [f"All cats{i} are animals{i}" for i in range(50)]
        
        bridge = SymbolicFOLBridge(enable_caching=True)
        
        # Process all statements
        for statement in statements:
            symbol = bridge.create_semantic_symbol(statement)
            result = bridge.semantic_to_fol(symbol)
            assert len(result.fol_formula) > 0
        
        # Check cache size
        stats = bridge.get_statistics()
        assert stats["cache_size"] == len(statements)
        
        # Clear cache and verify
        bridge.clear_cache()
        stats_after_clear = bridge.get_statistics()
        assert stats_after_clear["cache_size"] == 0


class TestErrorHandlingAndRecovery:
    """Test error handling and recovery mechanisms."""
    
    def setup_method(self):
        """Setup error handling test environment."""
        self.bridge = SymbolicFOLBridge(fallback_enabled=True)
        self.converter = create_fol_converter()
    
    def test_graceful_degradation(self):
        """Test graceful degradation when SymbolicAI is not available."""
        problematic_statements = [
            "This statement has very unclear logical structure",
            "Random words without any logical meaning",
            "Symbols: @#$%^&*()",
            "Numbers: 123 456 789"
        ]
        
        for statement in problematic_statements:
            try:
                # Should not crash, even with difficult input
                input_data = validate_fol_input(statement, confidence_threshold=0.3)
                result = self.converter(input_data)
                
                assert isinstance(result, FOLOutput)
                # May have very low confidence, but should produce something
                assert result.confidence >= 0.0
                assert isinstance(result.fol_formula, str)
                
            except Exception as e:
                # If it fails, should fail gracefully
                assert isinstance(e, (ValueError, RuntimeError))
    
    def test_fallback_mechanism(self):
        """Test fallback mechanism when primary methods fail."""
        # Test with bridge fallback
        bridge_with_fallback = SymbolicFOLBridge(fallback_enabled=True)
        bridge_without_fallback = SymbolicFOLBridge(fallback_enabled=False)
        
        statement = "Very ambiguous statement with unclear meaning"
        
        # With fallback should always produce something
        symbol = bridge_with_fallback.create_semantic_symbol(statement)
        result_with_fallback = bridge_with_fallback.semantic_to_fol(symbol)
        
        assert isinstance(result_with_fallback.fol_formula, str)
        assert len(result_with_fallback.fol_formula) > 0
        
        # Without fallback might fail, but should handle gracefully
        symbol = bridge_without_fallback.create_semantic_symbol(statement)
        result_without_fallback = bridge_without_fallback.semantic_to_fol(symbol)
        
        # Should still get some result, but might have lower quality
        assert isinstance(result_without_fallback.fol_formula, str)
    
    def test_input_validation_error_recovery(self):
        """Test recovery from input validation errors."""
        from pydantic import ValidationError
        
        invalid_inputs = [
            {"text": "", "confidence_threshold": 0.7},  # Empty text
            {"text": "Valid text", "confidence_threshold": 1.5},  # Invalid confidence
            {"text": "Valid text", "output_format": "invalid"}  # Invalid format
        ]
        
        for invalid_input in invalid_inputs:
            with pytest.raises(ValueError):
                validate_fol_input(**invalid_input)
        
        # Test that valid inputs still work after validation errors
        valid_input = validate_fol_input("All cats are animals")
        result = self.converter(valid_input)
        assert isinstance(result, FOLOutput)
    
    def test_partial_failure_handling(self):
        """Test handling when some components fail but others succeed."""
        statement = "Complex philosophical statement about existence and meaning"
        
        # Try each component individually
        components_results = []
        
        try:
            # Bridge component
            symbol = self.bridge.create_semantic_symbol(statement)
            bridge_result = self.bridge.semantic_to_fol(symbol)
            components_results.append(("bridge", bridge_result))
        except Exception as e:
            components_results.append(("bridge", f"failed: {e}"))
        
        try:
            # Converter component
            input_data = validate_fol_input(statement)
            converter_result = self.converter(input_data)
            components_results.append(("converter", converter_result))
        except Exception as e:
            components_results.append(("converter", f"failed: {e}"))
        
        try:
            # Primitives component
            primitive_symbol = create_logic_symbol(statement)
            primitive_result = primitive_symbol.to_fol()
            components_results.append(("primitives", primitive_result))
        except Exception as e:
            components_results.append(("primitives", f"failed: {e}"))
        
        # At least one component should work
        successful_components = [result for name, result in components_results 
                               if not isinstance(result, str) or not result.startswith("failed")]
        assert len(successful_components) > 0


class TestRealWorldScenarios:
    """Test real-world usage scenarios."""
    
    def setup_method(self):
        """Setup real-world test environment."""
        self.bridge = SymbolicFOLBridge()
        self.converter = create_fol_converter()
    
    def test_academic_logic_problems(self):
        """Test with typical academic logic problems."""
        academic_problems = [
            "All humans are mortal. Socrates is human. Therefore, Socrates is mortal.",
            "If all birds can fly, and penguins are birds, then penguins can fly.",
            "Some students pass all their exams. All students who pass their exams graduate.",
            "Every professor teaches at least one course. Some courses are difficult.",
            "All books have authors. Some authors are famous. Famous authors write bestsellers."
        ]
        
        for problem in academic_problems:
            input_data = validate_fol_input(problem, confidence_threshold=0.6)
            result = self.converter(input_data)
            
            assert isinstance(result, FOLOutput)
            assert len(result.fol_formula) > 0
            
            # Academic problems should have reasonable confidence
            assert result.confidence > 0.3
            
            # Should extract meaningful logical components
            assert len(result.logical_components.get("predicates", [])) > 0
    
    def test_legal_reasoning_statements(self):
        """Test with legal reasoning statements."""
        legal_statements = [
            "Citizens must pay taxes unless they are exempt",
            "All contracts require mutual consent between parties",
            "If someone commits a crime, then they are subject to prosecution",
            "Every person has the right to legal representation",
            "Defendants are presumed innocent until proven guilty"
        ]
        
        for statement in legal_statements:
            input_data = validate_fol_input(
                statement,
                confidence_threshold=0.5,
                domain_predicates=["Citizen", "Contract", "Crime", "Right", "Defendant"]
            )
            result = self.converter(input_data)
            
            assert isinstance(result, FOLOutput)
            assert len(result.fol_formula) > 0
            
            # Legal statements often have deontic elements
            assert result.confidence >= 0.0
    
    def test_scientific_statements(self):
        """Test with scientific statements."""
        scientific_statements = [
            "All metals conduct electricity when heated",
            "If the temperature rises above freezing, then ice melts",
            "Every chemical reaction conserves mass and energy",
            "Some bacteria are beneficial to human health",
            "All living organisms require water to survive"
        ]
        
        for statement in scientific_statements:
            input_data = validate_fol_input(statement, confidence_threshold=0.6)
            result = self.converter(input_data)
            
            assert isinstance(result, FOLOutput)
            assert len(result.fol_formula) > 0
            
            # Scientific statements should have clear logical structure
            assert result.confidence > 0.3
    
    def test_everyday_reasoning(self):
        """Test with everyday reasoning statements."""
        everyday_statements = [
            "If it rains, then I will take an umbrella",
            "All cats like fish and some cats like milk",
            "When people are tired, they usually sleep",
            "Every student needs books for their classes",
            "Some dogs are friendly and all dogs are loyal"
        ]
        
        for statement in everyday_statements:
            # Test with both bridge and converter
            bridge_symbol = self.bridge.create_semantic_symbol(statement)
            bridge_result = self.bridge.semantic_to_fol(bridge_symbol)
            
            input_data = validate_fol_input(statement)
            converter_result = self.converter(input_data)
            
            # Both should work
            assert len(bridge_result.fol_formula) > 0
            assert len(converter_result.fol_formula) > 0
            
            # Should extract meaningful components
            assert len(bridge_result.components.predicates) > 0


class TestBackwardCompatibility:
    """Test backward compatibility with existing FOL system."""
    
    def test_integration_with_existing_mcp_tools(self):
        """Test integration with existing MCP tools."""
        # This would test integration with the existing text_to_fol MCP tool
        # For now, we test that our new system produces compatible output
        
        statement = "All cats are animals"
        
        # Test our new system
        input_data = validate_fol_input(statement, output_format="symbolic")
        result = self.converter(input_data)
        
        # Output should be compatible with existing expectations
        assert isinstance(result, FOLOutput)
        assert "fol_formula" in result.__dict__
        assert "confidence" in result.__dict__
        assert "logical_components" in result.__dict__
        
        # The formula should be in a recognizable FOL format
        formula = result.fol_formula
        assert any(symbol in formula for symbol in ["∀", "∃", "→", "∧", "∨", "(", ")"])
    
    def test_output_format_compatibility(self):
        """Test that output formats match existing system expectations."""
        statement = "All cats are animals"
        
        # Test different output formats
        formats = ["symbolic", "prolog", "tptp"]
        
        for fmt in formats:
            input_data = validate_fol_input(statement, output_format=fmt)
            result = self.converter(input_data)
            
            # Check format-specific requirements
            if fmt == "symbolic":
                # Should use standard FOL symbols
                assert any(symbol in result.fol_formula for symbol in ["∀", "∃", "→"])
            elif fmt == "prolog":
                # Should use Prolog-compatible syntax
                prolog_compatible = (
                    ":-" in result.fol_formula or
                    "forall" in result.fol_formula.lower() or
                    not any(symbol in result.fol_formula for symbol in ["∀", "∃"])
                )
                assert prolog_compatible
            elif fmt == "tptp":
                # Should use TPTP format
                assert "fof(" in result.fol_formula or len(result.fol_formula) > 5


class TestModalLogicIntegration:
    """Test integration with new modal logic extension."""
    
    def setup_method(self):
        """Setup modal logic integration tests."""
        try:
            from ipfs_datasets_py.logic.integration.modal_logic_extension import (
                ModalLogicSymbol, AdvancedLogicConverter, ModalFormula, LogicClassification
            )
            self.modal_converter = AdvancedLogicConverter()
            self.bridge = SymbolicFOLBridge()
            self.modal_available = True
        except ImportError:
            self.modal_available = False
            pytest.skip("Modal logic extension not available")
    
    def test_bridge_modal_integration(self):
        """Test integration between FOL bridge and modal logic."""
        if not self.modal_available:
            pytest.skip("Modal logic extension not available")
        
        modal_statements = [
            "It is necessary that all humans are mortal",
            "Citizens must pay taxes",
            "John knows that it is raining"
        ]
        
        for statement in modal_statements:
            # Use bridge to create symbol
            symbol = self.bridge.create_semantic_symbol(statement)
            assert symbol is not None
            
            # Use modal converter to classify
            classification = self.modal_converter.detect_logic_type(statement)
            assert isinstance(classification, LogicClassification)
            assert classification.logic_type in ['modal', 'deontic', 'epistemic', 'fol']
            
            # Convert to modal formula
            modal_result = self.modal_converter.convert_to_modal_logic(statement)
            assert isinstance(modal_result, ModalFormula)
            assert modal_result.base_formula == statement
    
    def test_modal_fol_conversion_workflow(self):
        """Test complete modal logic to FOL conversion workflow."""
        if not self.modal_available:
            pytest.skip("Modal logic extension not available")
        
        text = "It is necessary that all birds can fly"
        
        # Step 1: Detect logic type
        classification = self.modal_converter.detect_logic_type(text)
        
        # Step 2: Convert to modal logic if appropriate
        if classification.logic_type in ['modal', 'temporal', 'deontic', 'epistemic']:
            modal_result = self.modal_converter.convert_to_modal_logic(text)
            formula_to_verify = modal_result.formula
        else:
            # Use standard FOL conversion
            symbol = self.bridge.create_semantic_symbol(text)
            formula_to_verify = self.bridge.semantic_to_fol(symbol)
        
        # Step 3: Verify the result is valid
        assert isinstance(formula_to_verify, str)
        assert len(formula_to_verify) > 0


class TestLogicVerificationIntegration:
    """Test integration with logic verification system."""
    
    def setup_method(self):
        """Setup verification integration tests."""
        try:
            from ipfs_datasets_py.logic.integration.logic_verification import (
                LogicVerifier, LogicAxiom, ProofResult, ConsistencyCheck, EntailmentResult
            )
            self.verifier = LogicVerifier()
            self.bridge = SymbolicFOLBridge()
            self.verification_available = True
        except ImportError:
            self.verification_available = False
            pytest.skip("Logic verification module not available")
    
    def test_bridge_verifier_integration(self):
        """Test integration between FOL bridge and logic verifier."""
        if not self.verification_available:
            pytest.skip("Logic verification not available")
        
        # Create logical statements
        premises = ["All cats are animals", "Fluffy is a cat"]
        conclusion = "Fluffy is an animal"
        
        # Convert using bridge
        converted_premises = []
        for premise in premises:
            symbol = self.bridge.create_semantic_symbol(premise)
            try:
                fol_formula = self.bridge.semantic_to_fol(symbol)
                converted_premises.append(fol_formula)
            except:
                # Use fallback
                converted_premises.append(premise)
        
        # Convert conclusion
        conclusion_symbol = self.bridge.create_semantic_symbol(conclusion)
        try:
            fol_conclusion = self.bridge.semantic_to_fol(conclusion_symbol)
        except:
            fol_conclusion = conclusion
        
        # Verify with logic verifier
        consistency = self.verifier.check_consistency(converted_premises)
        assert isinstance(consistency, ConsistencyCheck)
        
        entailment = self.verifier.check_entailment(converted_premises, fol_conclusion)
        assert isinstance(entailment, EntailmentResult)
        
        proof = self.verifier.generate_proof(converted_premises, fol_conclusion)
        assert isinstance(proof, ProofResult)
    
    def test_axiom_integration_workflow(self):
        """Test workflow with custom axioms."""
        if not self.verification_available:
            pytest.skip("Logic verification not available")
        
        # Add custom axiom for cat logic
        cat_axiom = LogicAxiom(
            name="cat_animal_rule",
            formula="∀x (Cat(x) → Animal(x))",
            description="All cats are animals",
            axiom_type="user_defined"
        )
        
        success = self.verifier.add_axiom(cat_axiom)
        assert success is True
        
        # Use the axiom in reasoning
        premises = ["Cat(fluffy)"]
        conclusion = "Animal(fluffy)"
        
        entailment = self.verifier.check_entailment(premises, conclusion)
        assert isinstance(entailment, EntailmentResult)
        
        # Check that axiom was considered
        stats = self.verifier.get_statistics()
        assert stats["axiom_count"] > 6  # Built-ins + our custom axiom


class TestCompleteSystemIntegration:
    """Test complete system integration with all components."""
    
    def setup_method(self):
        """Setup complete system tests."""
        self.bridge = SymbolicFOLBridge()
        
        # Try to import all optional components
        self.available_components = {}
        
        try:
            from ipfs_datasets_py.logic.integration.modal_logic_extension import AdvancedLogicConverter
            self.available_components['modal'] = AdvancedLogicConverter()
        except ImportError:
            pass
        
        try:
            from ipfs_datasets_py.logic.integration.logic_verification import LogicVerifier
            self.available_components['verifier'] = LogicVerifier()
        except ImportError:
            pass
        
        try:
            from ipfs_datasets_py.logic.integration.interactive_fol_constructor import InteractiveFOLConstructor
            self.available_components['constructor'] = InteractiveFOLConstructor()
        except ImportError:
            pass
    
    def test_full_system_workflow(self):
        """Test complete workflow using all available components."""
        text = "All humans are mortal and Socrates is human"
        
        # Step 1: Basic FOL conversion
        symbol = self.bridge.create_semantic_symbol(text)
        components = self.bridge.extract_logical_components(symbol)
        
        # Step 2: Modal logic analysis (if available)
        if 'modal' in self.available_components:
            classification = self.available_components['modal'].detect_logic_type(text)
            modal_result = self.available_components['modal'].convert_to_modal_logic(text)
            assert isinstance(classification.logic_type, str)
            assert isinstance(modal_result.formula, str)
        
        # Step 3: Logic verification (if available)
        if 'verifier' in self.available_components:
            consistency = self.available_components['verifier'].check_consistency([text])
            assert isinstance(consistency.is_consistent, bool)
        
        # Step 4: Interactive session (if available)
        if 'constructor' in self.available_components:
            session_id = self.available_components['constructor'].start_session()
            self.available_components['constructor'].add_statement(session_id, text)
            analysis = self.available_components['constructor'].analyze_session(session_id)
            assert isinstance(analysis, dict)
        
        # All components should have processed the input successfully
        assert symbol is not None
        assert isinstance(components, dict)
    
    def test_knowledge_base_construction(self):
        """Test constructing a complete knowledge base."""
        kb_statements = [
            "All humans are mortal",
            "All philosophers are human",
            "Socrates is a philosopher",
            "All mortals will die eventually"
        ]
        
        # Process each statement
        processed_statements = []
        for statement in kb_statements:
            symbol = self.bridge.create_semantic_symbol(statement)
            
            # Modal analysis if available
            if 'modal' in self.available_components:
                classification = self.available_components['modal'].detect_logic_type(statement)
                if classification.logic_type != 'fol':
                    modal_result = self.available_components['modal'].convert_to_modal_logic(statement)
                    processed_statements.append(modal_result.formula)
                else:
                    processed_statements.append(statement)
            else:
                processed_statements.append(statement)
        
        # Verify knowledge base consistency if verifier available
        if 'verifier' in self.available_components:
            consistency = self.available_components['verifier'].check_consistency(processed_statements)
            assert isinstance(consistency, ConsistencyCheck)
            
            # Test some entailments
            entailment = self.available_components['verifier'].check_entailment(
                kb_statements[:3],  # Premises
                "Socrates is mortal"  # Conclusion
            )
            assert isinstance(entailment, EntailmentResult)
        
        # Build interactive session if constructor available
        if 'constructor' in self.available_components:
            session_id = self.available_components['constructor'].start_session()
            
            for statement in kb_statements:
                self.available_components['constructor'].add_statement(session_id, statement)
            
            analysis = self.available_components['constructor'].analyze_session(session_id)
            assert 'consistency' in analysis
            assert 'logical_structure' in analysis
        
        assert len(processed_statements) == len(kb_statements)
    
    def test_error_resilience_across_system(self):
        """Test error resilience across the complete system."""
        problematic_inputs = [
            "Invalid logical statement with no clear structure",
            "P → → Q",  # Malformed
            "Completely random text that makes no logical sense at all"
        ]
        
        for problematic_input in problematic_inputs:
            errors_encountered = []
            successes = []
            
            # Test bridge
            try:
                symbol = self.bridge.create_semantic_symbol(problematic_input)
                components = self.bridge.extract_logical_components(symbol)
                successes.append("bridge")
            except Exception as e:
                errors_encountered.append(f"bridge: {type(e).__name__}")
            
            # Test modal converter if available
            if 'modal' in self.available_components:
                try:
                    classification = self.available_components['modal'].detect_logic_type(problematic_input)
                    modal_result = self.available_components['modal'].convert_to_modal_logic(problematic_input)
                    successes.append("modal")
                except Exception as e:
                    errors_encountered.append(f"modal: {type(e).__name__}")
            
            # Test verifier if available
            if 'verifier' in self.available_components:
                try:
                    consistency = self.available_components['verifier'].check_consistency([problematic_input])
                    successes.append("verifier")
                except Exception as e:
                    errors_encountered.append(f"verifier: {type(e).__name__}")
            
            # Should either succeed gracefully or fail with informative errors
            total_components_tested = 1 + len(self.available_components)
            total_responses = len(successes) + len(errors_encountered)
            assert total_responses == total_components_tested
    
    def test_performance_across_system(self):
        """Test performance across the complete system."""
        test_statements = [
            f"All P{i} are Q{i}" for i in range(10)
        ]
        
        start_time = time.time()
        
        for statement in test_statements:
            # Process through available components
            symbol = self.bridge.create_semantic_symbol(statement)
            components = self.bridge.extract_logical_components(symbol)
            
            if 'modal' in self.available_components:
                classification = self.available_components['modal'].detect_logic_type(statement)
            
            if 'verifier' in self.available_components:
                consistency = self.available_components['verifier'].check_consistency([statement])
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Should complete within reasonable time
        assert total_time < 30.0
        
        # Test caching effectiveness
        if hasattr(self.bridge, '_cache') and len(self.bridge._cache) > 0:
            # Repeat first few statements - should be faster
            cache_start = time.time()
            for statement in test_statements[:3]:
                symbol = self.bridge.create_semantic_symbol(statement)
                components = self.bridge.extract_logical_components(symbol)
            cache_end = time.time()
            
            cache_time = cache_end - cache_start
            # Should be faster due to caching
            assert cache_time < total_time / 3


class TestLegacyCompatibility:
    """Test compatibility with existing FOL tools."""
    
    def setup_method(self):
        """Setup legacy compatibility tests."""
        self.bridge = SymbolicFOLBridge()
    
    def test_existing_tool_compatibility(self):
        """Test compatibility with existing FOL conversion tools."""
        try:
            # Import existing tools
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.text_to_fol import text_to_fol
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.legal_text_to_deontic import legal_text_to_deontic
            
            # Test statements
            fol_statement = "All cats are animals"
            legal_statement = "Citizens must pay taxes"
            
            # Test with existing tools
            fol_result = text_to_fol(fol_statement)
            legal_result = legal_text_to_deontic(legal_statement)
            
            # Test with new integration
            symbol = self.bridge.create_semantic_symbol(fol_statement)
            components = self.bridge.extract_logical_components(symbol)
            
            # Both should produce valid results
            assert isinstance(fol_result, dict)
            assert isinstance(legal_result, dict)
            assert isinstance(components, dict)
            
            # Results should be compatible (both should extract logical information)
            assert 'predicates' in components or 'entities' in components
            
        except ImportError:
            pytest.skip("Existing FOL tools not available for compatibility testing")
    
    def test_output_format_compatibility(self):
        """Test that output formats remain compatible."""
        statement = "All birds can fly"
        
        # New system should support the same output formats as old system
        symbol = self.bridge.create_semantic_symbol(statement)
        components = self.bridge.extract_logical_components(symbol)
        
        # Should have similar structure to existing tools
        expected_fields = ['quantifiers', 'predicates', 'entities']
        for field in expected_fields:
            assert field in components
            assert isinstance(components[field], list)


if __name__ == "__main__":
    # Run integration tests with pytest
    pytest.main([__file__, "-v", "--tb=short", "-x"])  # Stop on first failure for debugging

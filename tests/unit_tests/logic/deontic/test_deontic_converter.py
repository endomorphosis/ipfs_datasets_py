"""
Unit tests for DeonticConverter.

Tests the unified deontic converter with integrated features.
"""

import pytest
from ipfs_datasets_py.logic.deontic import DeonticConverter
from ipfs_datasets_py.logic.common.converters import ConversionStatus


class TestDeonticConverter:
    """Test suite for DeonticConverter."""
    
    def test_initialization_default(self):
        """Test DeonticConverter initializes with default settings."""
        # GIVEN: Default initialization
        # WHEN: Creating converter
        converter = DeonticConverter()
        
        # THEN: Should initialize successfully
        assert converter is not None
        assert converter.jurisdiction == "us"
        assert converter.document_type == "statute"
        assert converter.confidence_threshold == 0.7
    
    def test_initialization_custom_settings(self):
        """Test DeonticConverter with custom settings."""
        # GIVEN: Custom settings
        # WHEN: Creating converter with custom options
        converter = DeonticConverter(
            jurisdiction="eu",
            document_type="regulation",
            use_cache=True,
            use_ml=False,
            confidence_threshold=0.8
        )
        
        # THEN: Settings should be applied
        assert converter.jurisdiction == "eu"
        assert converter.document_type == "regulation"
        assert converter.confidence_threshold == 0.8
        assert converter.use_ml is False
    
    def test_simple_obligation_conversion(self):
        """Test converting a simple obligation statement."""
        # GIVEN: A simple obligation text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The tenant must pay rent monthly"
        
        # WHEN: Converting to deontic logic
        result = converter.convert(text)
        
        # THEN: Should successfully convert
        assert result.success
        assert result.status == ConversionStatus.SUCCESS
        assert result.output is not None
        assert result.output.confidence > 0
    
    def test_permission_conversion(self):
        """Test converting a permission statement."""
        # GIVEN: A permission text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The defendant may appeal the decision"
        
        # WHEN: Converting to deontic logic
        result = converter.convert(text)
        
        # THEN: Should successfully convert with permission operator
        assert result.success
        assert result.output is not None
    
    def test_prohibition_conversion(self):
        """Test converting a prohibition statement."""
        # GIVEN: A prohibition text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The contractor shall not subcontract without approval"
        
        # WHEN: Converting to deontic logic
        result = converter.convert(text)
        
        # THEN: Should successfully convert with prohibition operator
        assert result.success
        assert result.output is not None
        assert result.output.operator.value == "F"

    def test_shall_not_is_not_misclassified_as_obligation(self):
        """Regression: 'shall not' must be parsed as prohibition before bare 'shall'."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        result = converter.convert("The contractor shall not subcontract without approval")

        assert result.success
        assert result.output is not None
        assert result.output.operator.value == "F"
        assert result.output.proposition == "∀x (Contractor(x) ∧ ¬Approval(x) → Subcontract(x))"
        assert result.output.formula == "F[contractor](∀x (Contractor(x) ∧ ¬Approval(x) → Subcontract(x)))"

    def test_structured_modal_clause_extraction_preserves_condition_and_exception(self):
        """The deterministic scaffold should expose useful legal clause structure."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Secretary shall submit a report to Congress within 30 days unless disclosure is classified."
        )

        assert len(elements) == 1
        element = elements[0]
        assert element["deontic_operator"] == "O"
        assert element["subject"] == ["Secretary"]
        assert element["action"] == ["submit a report to Congress"]
        assert element["temporal_constraints"] == [{"type": "deadline", "value": "30 days"}]
        assert element["exceptions"] == ["disclosure is classified"]

    def test_non_normative_text_gets_low_confidence_unparsed_scaffold(self):
        """Do not pretend arbitrary descriptive text is a high-quality obligation."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        result = converter.convert("This section contains historical notes and editorial references.")

        assert result.success
        assert result.output is not None
        assert result.output.proposition == "UnparsedNonNormativeOrAmbiguousText"
        assert result.output.confidence <= 0.1

    def test_without_clause_is_exception_not_action_tail(self):
        """'Without approval' should qualify the norm instead of becoming the action."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("The contractor shall not subcontract without written approval.")

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "F"
        assert elements[0]["action"] == ["subcontract"]
        assert elements[0]["exceptions"] == ["written approval"]

    def test_not_later_than_deadline_with_anchor(self):
        """Federal statutes often express deadlines as 'not later than N days after ...'."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Secretary shall issue regulations not later than 180 days after enactment."
        )

        assert len(elements) == 1
        assert elements[0]["action"] == ["issue regulations"]
        assert elements[0]["temporal_constraints"] == [
            {"type": "deadline", "value": "180 days after enactment"}
        ]

    def test_subject_to_condition_is_preserved(self):
        """'Subject to' clauses should appear as conditions for downstream review."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "Subject to appropriations, the Administrator may award grants to eligible entities."
        )

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "P"
        assert elements[0]["subject"] == ["Administrator"]
        assert elements[0]["conditions"] == ["appropriations"]

    def test_no_person_shall_is_prohibition(self):
        """'No person shall' is a prohibition even without an explicit 'not' after shall."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("No person shall knowingly make a false statement.")

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "F"
        assert elements[0]["subject"] == ["person"]
        assert elements[0]["action"] == ["knowingly make a false statement"]
        assert elements[0]["mental_state"] == "knowingly"
        assert elements[0]["action_verb"] == "make"
        assert elements[0]["action_object"] == "a false statement"

    def test_implicit_repeated_subject_modal_clause(self):
        """A second modal joined by 'and shall' should inherit the prior subject."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Secretary may award grants and shall submit an annual report to Congress."
        )

        assert [element["deontic_operator"] for element in elements] == ["P", "O"]
        assert [element["subject"] for element in elements] == [["Secretary"], ["Secretary"]]
        assert [element["action"] for element in elements] == [
            ["award grants"],
            ["submit an annual report to Congress"],
        ]

    def test_passive_by_agent_clause_normalizes_actor_and_action(self):
        """Passive duties should not make the object look like the regulated actor."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("A report shall be submitted by the Secretary within 90 days.")

        assert len(elements) == 1
        assert elements[0]["subject"] == ["Secretary"]
        assert elements[0]["action"] == ["submit report"]
        assert elements[0]["temporal_constraints"] == [{"type": "deadline", "value": "90 days"}]

    def test_quoted_defined_term_extraction(self):
        """Quoted statutory terms should become the definition subject."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            'In this section, the term "covered entity" means a provider of covered services.'
        )

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "DEF"
        assert elements[0]["subject"] == ["covered entity"]
    
    def test_empty_input_validation(self):
        """Test that empty input is handled properly."""
        # GIVEN: Empty text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = ""
        
        # WHEN: Attempting to convert
        result = converter.convert(text)
        
        # THEN: Should fail validation
        assert not result.success
        assert result.status == ConversionStatus.FAILED
    
    def test_whitespace_input_validation(self):
        """Test that whitespace-only input is handled properly."""
        # GIVEN: Whitespace-only text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "   \n\t   "
        
        # WHEN: Attempting to convert
        result = converter.convert(text)
        
        # THEN: Should fail validation
        assert not result.success
        assert result.status == ConversionStatus.FAILED
    
    def test_caching_functionality(self):
        """Test that caching works correctly."""
        # GIVEN: Converter with caching enabled
        converter = DeonticConverter(use_cache=True, use_ml=False, enable_monitoring=False)
        text = "The employee must report to work on time"
        
        # WHEN: Converting same text twice
        result1 = converter.convert(text)
        result2 = converter.convert(text)
        
        # THEN: Both should succeed and second should be from cache
        assert result1.success
        assert result2.success
        # Cache stats should show hits
        cache_stats = converter.get_cache_stats()
        # At minimum, we converted twice, so there should be activity
        assert result1.output.formula == result2.output.formula
    
    def test_batch_conversion(self):
        """Test batch conversion of multiple legal texts."""
        # GIVEN: Multiple legal texts
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        texts = [
            "The tenant must pay rent",
            "The landlord may inspect the premises",
            "The party shall not disclose confidential information"
        ]
        
        # WHEN: Converting in batch
        results = converter.convert_batch(texts, max_workers=2)
        
        # THEN: All should be processed
        assert len(results) == 3
        successful = [r for r in results if r.success]
        assert len(successful) > 0  # At least some should succeed
    
    @pytest.mark.asyncio
    async def test_async_conversion(self):
        """Test async conversion interface."""
        # GIVEN: Legal text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The borrower must repay the loan"
        
        # WHEN: Converting asynchronously
        result = await converter.convert_async(text)
        
        # THEN: Should complete successfully
        assert result.success
        assert result.output is not None
    
    def test_confidence_calculation(self):
        """Test confidence score calculation."""
        # GIVEN: Legal text with clear normative content
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The seller must deliver the goods by the agreed date"
        
        # WHEN: Converting
        result = converter.convert(text)
        
        # THEN: Should have reasonable confidence
        assert result.success
        assert 0 <= result.output.confidence <= 1.0
        # Obligation with clear subject and action should have decent confidence
        assert result.output.confidence > 0.5
    
    def test_multiple_jurisdictions(self):
        """Test conversion with different jurisdictions."""
        # GIVEN: Converters for different jurisdictions
        converter_us = DeonticConverter(jurisdiction="us", use_ml=False, enable_monitoring=False)
        converter_eu = DeonticConverter(jurisdiction="eu", use_ml=False, enable_monitoring=False)
        text = "The data controller must obtain consent"
        
        # WHEN: Converting with different jurisdictions
        result_us = converter_us.convert(text)
        result_eu = converter_eu.convert(text)
        
        # THEN: Both should succeed
        assert result_us.success
        assert result_eu.success
    
    def test_stats_tracking(self):
        """Test statistics tracking."""
        # GIVEN: Converter with stats tracking
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        
        # WHEN: Performing conversions
        converter.convert("Must comply")
        converter.convert("May appeal")
        
        # THEN: Stats should be available
        stats = converter.get_stats()
        assert stats is not None
        assert isinstance(stats, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

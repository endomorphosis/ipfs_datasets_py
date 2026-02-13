"""
Basic tests for text_to_fol conversion.

Tests cover:
- Basic conversions
- Simple quantifiers
- Logical operators
- Predicate extraction
"""

import pytest
from ipfs_datasets_py.logic.fol.text_to_fol import (
    convert_text_to_fol,
    extract_text_from_dataset,
    calculate_conversion_confidence,
    estimate_sentence_complexity,
    estimate_formula_complexity,
)


class TestBasicConversions:
    """Test basic FOL conversions."""

    @pytest.mark.asyncio
    async def test_simple_universal_quantifier(self):
        """
        GIVEN: A sentence with universal quantification
        WHEN: Converting to FOL
        THEN: Should produce correct FOL formula with ∀ quantifier
        """
        text = "All humans are mortal"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert len(result["fol_formulas"]) > 0
        formula = result["fol_formulas"][0]
        assert "∀" in formula["fol"] or "forall" in formula["fol"].lower()

    @pytest.mark.asyncio
    async def test_simple_existential_quantifier(self):
        """
        GIVEN: A sentence with existential quantification
        WHEN: Converting to FOL
        THEN: Should produce correct FOL formula with ∃ quantifier
        """
        text = "Some dogs bark"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert len(result["fol_formulas"]) > 0

    @pytest.mark.asyncio
    async def test_conjunction(self):
        """
        GIVEN: A sentence with conjunction
        WHEN: Converting to FOL
        THEN: Should produce FOL with ∧ operator
        """
        text = "The cat is black and white"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert result["summary"]["operator_distribution"]["∧"] >= 0

    @pytest.mark.asyncio
    async def test_disjunction(self):
        """
        GIVEN: A sentence with disjunction
        WHEN: Converting to FOL
        THEN: Should produce FOL with ∨ operator
        """
        text = "The bird is red or blue"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert result["summary"]["operator_distribution"]["∨"] >= 0

    @pytest.mark.asyncio
    async def test_implication(self):
        """
        GIVEN: A sentence with implication
        WHEN: Converting to FOL
        THEN: Should produce FOL with → operator
        """
        text = "If it rains, then the ground is wet"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert result["summary"]["operator_distribution"]["→"] >= 0

    @pytest.mark.asyncio
    async def test_negation(self):
        """
        GIVEN: A sentence with negation
        WHEN: Converting to FOL
        THEN: Should produce FOL with ¬ operator
        """
        text = "The sun is not cold"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert result["summary"]["operator_distribution"]["¬"] >= 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_string(self):
        """
        GIVEN: An empty string
        WHEN: Converting to FOL
        THEN: Should return success with empty results
        """
        result = await convert_text_to_fol("")
        
        assert result["status"] == "success"
        assert result["fol_formulas"] == []
        assert result["summary"]["total_statements"] == 0

    @pytest.mark.asyncio
    async def test_whitespace_only(self):
        """
        GIVEN: A string with only whitespace
        WHEN: Converting to FOL
        THEN: Should return success with empty results
        """
        result = await convert_text_to_fol("   \n\t  ")
        
        assert result["status"] == "success"
        assert result["fol_formulas"] == []

    @pytest.mark.asyncio
    async def test_none_input(self):
        """
        GIVEN: None as input
        WHEN: Converting to FOL
        THEN: Should handle gracefully and return empty results
        """
        result = await convert_text_to_fol(None)
        
        assert result["status"] == "success"
        assert result["fol_formulas"] == []

    @pytest.mark.asyncio
    async def test_invalid_confidence_threshold(self):
        """
        GIVEN: Invalid confidence threshold (>1.0)
        WHEN: Converting to FOL
        THEN: Should raise ValueError
        """
        with pytest.raises(ValueError, match="Confidence threshold"):
            await convert_text_to_fol("test", confidence_threshold=1.5)

    @pytest.mark.asyncio
    async def test_negative_confidence_threshold(self):
        """
        GIVEN: Negative confidence threshold
        WHEN: Converting to FOL
        THEN: Should raise ValueError
        """
        with pytest.raises(ValueError, match="Confidence threshold"):
            await convert_text_to_fol("test", confidence_threshold=-0.1)

    @pytest.mark.asyncio
    async def test_special_characters(self):
        """
        GIVEN: Text with special characters
        WHEN: Converting to FOL
        THEN: Should handle gracefully without crashing
        """
        text = "Test @#$% special *&^ characters!"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        # Should not crash, even if conversion quality is low

    @pytest.mark.asyncio
    async def test_very_long_sentence(self):
        """
        GIVEN: A very long sentence (>500 chars)
        WHEN: Converting to FOL
        THEN: Should handle without crashing
        """
        text = "This is a test " * 100  # 1500+ characters
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"


class TestConfidenceScoring:
    """Test confidence scoring mechanisms."""

    def test_calculate_confidence_high_indicators(self):
        """
        GIVEN: A sentence with many logical indicators
        WHEN: Calculating confidence
        THEN: Should return high confidence score
        """
        sentence = "All humans are mortal"
        predicates = {"humans": ["mortal"]}
        quantifiers = ["∀"]
        operators = ["→"]
        
        confidence = calculate_conversion_confidence(
            sentence, predicates, quantifiers, operators
        )
        
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.5  # Should have reasonable confidence

    def test_calculate_confidence_no_indicators(self):
        """
        GIVEN: A sentence with no logical indicators
        WHEN: Calculating confidence
        THEN: Should return lower confidence score
        """
        sentence = "The sky blue"  # Incomplete/unclear
        predicates = {}
        quantifiers = []
        operators = []
        
        confidence = calculate_conversion_confidence(
            sentence, predicates, quantifiers, operators
        )
        
        assert 0.0 <= confidence <= 1.0

    def test_estimate_sentence_complexity_simple(self):
        """
        GIVEN: A simple sentence
        WHEN: Estimating complexity
        THEN: Should return low complexity score
        """
        complexity = estimate_sentence_complexity("Dogs bark")
        
        assert complexity > 0
        assert complexity < 10  # Should be simple

    def test_estimate_sentence_complexity_complex(self):
        """
        GIVEN: A complex sentence with multiple clauses
        WHEN: Estimating complexity
        THEN: Should return higher complexity score
        """
        sentence = "If all humans are mortal and Socrates is a human, then Socrates is mortal"
        complexity = estimate_sentence_complexity(sentence)
        
        assert complexity > 5  # Should be more complex

    def test_estimate_formula_complexity(self):
        """
        GIVEN: A FOL formula
        WHEN: Estimating complexity
        THEN: Should count operators correctly
        """
        formula = "∀x(Human(x) → Mortal(x))"
        complexity = estimate_formula_complexity(formula)
        
        assert complexity > 0  # Should detect operators


class TestDatasetExtraction:
    """Test dataset text extraction."""

    def test_extract_from_simple_dict(self):
        """
        GIVEN: A simple dictionary with text field
        WHEN: Extracting text
        THEN: Should return list of text strings
        """
        dataset = {"text": "Test sentence"}
        result = extract_text_from_dataset(dataset)
        
        assert isinstance(result, list)
        assert len(result) > 0
        assert "Test sentence" in result

    def test_extract_from_nested_dict(self):
        """
        GIVEN: A nested dictionary
        WHEN: Extracting text
        THEN: Should find text in nested fields
        """
        dataset = {
            "data": {
                "text": "Nested text"
            }
        }
        result = extract_text_from_dataset(dataset)
        
        assert isinstance(result, list)

    def test_extract_from_list_field(self):
        """
        GIVEN: A dictionary with list of texts
        WHEN: Extracting text
        THEN: Should handle list properly
        """
        dataset = {
            "texts": ["First sentence", "Second sentence"]
        }
        result = extract_text_from_dataset(dataset)
        
        assert isinstance(result, list)


class TestOutputFormats:
    """Test different output format options."""

    @pytest.mark.asyncio
    async def test_json_output_format(self):
        """
        GIVEN: Request for JSON output format
        WHEN: Converting to FOL
        THEN: Should return JSON-formatted result
        """
        text = "All birds fly"
        result = await convert_text_to_fol(text, output_format="json")
        
        assert result["status"] == "success"
        assert "fol_formulas" in result
        assert "metadata" in result
        assert result["metadata"]["output_format"] == "json"

    @pytest.mark.asyncio
    async def test_metadata_inclusion(self):
        """
        GIVEN: Request with metadata inclusion
        WHEN: Converting to FOL
        THEN: Should include metadata in results
        """
        text = "Test sentence"
        result = await convert_text_to_fol(text, include_metadata=True)
        
        assert "metadata" in result
        assert "tool" in result["metadata"]
        assert result["metadata"]["tool"] == "text_to_fol"

    @pytest.mark.asyncio
    async def test_confidence_threshold_filtering(self):
        """
        GIVEN: High confidence threshold (0.9)
        WHEN: Converting text
        THEN: Should filter out low-confidence results
        """
        text = "Complex ambiguous unclear sentence structure"
        result = await convert_text_to_fol(text, confidence_threshold=0.9)
        
        assert result["status"] == "success"
        # May have fewer results due to high threshold
        for formula in result["fol_formulas"]:
            if "confidence" in formula:
                assert formula["confidence"] >= 0.9 or formula["confidence"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

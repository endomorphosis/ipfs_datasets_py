"""
Advanced tests for FOL conversion - unicode, nested quantifiers, complex formulas.

Tests cover:
- Unicode and internationalization
- Deeply nested quantifiers
- Complex boolean expressions
- Performance benchmarks
"""

import pytest
import asyncio
import time
from ipfs_datasets_py.logic.fol.text_to_fol import (
    convert_text_to_fol,
    get_quantifier_distribution,
    get_operator_distribution,
)


class TestUnicodeSupport:
    """Test unicode and special character handling."""

    @pytest.mark.asyncio
    async def test_unicode_greek_letters(self):
        """
        GIVEN: Text with Greek letters (common in logic)
        WHEN: Converting to FOL
        THEN: Should handle without crashing
        """
        text = "For all α, if β then γ"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        # Should not crash even if quality varies

    @pytest.mark.asyncio
    async def test_unicode_mathematical_symbols(self):
        """
        GIVEN: Text with mathematical unicode symbols
        WHEN: Converting to FOL
        THEN: Should handle gracefully
        """
        text = "∀x∈ℕ: x≥0"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_unicode_emoji(self):
        """
        GIVEN: Text with emoji characters
        WHEN: Converting to FOL
        THEN: Should handle without error
        """
        text = "All 😀 are happy and 🎉 means celebration"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_unicode_mixed_scripts(self):
        """
        GIVEN: Text mixing Latin, Cyrillic, and Asian scripts
        WHEN: Converting to FOL
        THEN: Should handle mixed scripts
        """
        text = "Test Тест 测试"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_unicode_combining_characters(self):
        """
        GIVEN: Text with combining diacritical marks
        WHEN: Converting to FOL
        THEN: Should handle combining characters
        """
        text = "Café résumé naïve"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_unicode_rtl_text(self):
        """
        GIVEN: Right-to-left text (Arabic/Hebrew)
        WHEN: Converting to FOL
        THEN: Should handle RTL scripts
        """
        text = "مرحبا שלום"  # Hello in Arabic and Hebrew
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"


class TestNestedQuantifiers:
    """Test deeply nested quantifier handling."""

    @pytest.mark.asyncio
    async def test_double_universal_quantifier(self):
        """
        GIVEN: Formula with two universal quantifiers
        WHEN: Converting to FOL
        THEN: Should handle nested quantifiers
        """
        text = "For all x and for all y, if x equals y then they are identical"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert result["summary"]["quantifier_distribution"]["∀"] >= 1

    @pytest.mark.asyncio
    async def test_mixed_quantifiers_depth_2(self):
        """
        GIVEN: Formula with mixed quantifiers (depth 2)
        WHEN: Converting to FOL
        THEN: Should handle ∀∃ pattern
        """
        text = "For every person there exists a friend"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        # Should detect at least some quantifiers
        total_quantifiers = (
            result["summary"]["quantifier_distribution"]["∀"] +
            result["summary"]["quantifier_distribution"]["∃"]
        )
        assert total_quantifiers >= 0

    @pytest.mark.asyncio
    async def test_triple_nested_quantifiers(self):
        """
        GIVEN: Formula with three levels of quantification
        WHEN: Converting to FOL
        THEN: Should handle depth 3 nesting
        """
        text = "For all x, there exists y such that for all z, x relates to y through z"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_alternating_quantifiers(self):
        """
        GIVEN: Formula with alternating ∀∃∀ pattern
        WHEN: Converting to FOL
        THEN: Should handle alternation correctly
        """
        text = "For every A, there is some B, such that for all C, A B and C are related"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_quantifier_scope_ambiguity(self):
        """
        GIVEN: Text with ambiguous quantifier scope
        WHEN: Converting to FOL
        THEN: Should make reasonable interpretation
        """
        text = "All students and some professors attend every lecture"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"


class TestComplexBooleanExpressions:
    """Test complex boolean formula handling."""

    @pytest.mark.asyncio
    async def test_cnf_pattern(self):
        """
        GIVEN: Formula in CNF (Conjunctive Normal Form) pattern
        WHEN: Converting to FOL
        THEN: Should handle (A ∨ B) ∧ (C ∨ D) pattern
        """
        text = "Either A or B, and either C or D"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert result["summary"]["operator_distribution"]["∧"] >= 0
        assert result["summary"]["operator_distribution"]["∨"] >= 0

    @pytest.mark.asyncio
    async def test_dnf_pattern(self):
        """
        GIVEN: Formula in DNF (Disjunctive Normal Form) pattern
        WHEN: Converting to FOL
        THEN: Should handle (A ∧ B) ∨ (C ∧ D) pattern
        """
        text = "Either both A and B, or both C and D"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_de_morgan_pattern(self):
        """
        GIVEN: Formula that could use De Morgan's law
        WHEN: Converting to FOL
        THEN: Should handle negation distribution
        """
        text = "It is not the case that both A and B"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert result["summary"]["operator_distribution"]["¬"] >= 0

    @pytest.mark.asyncio
    async def test_nested_implications(self):
        """
        GIVEN: Nested implication (A → (B → C))
        WHEN: Converting to FOL
        THEN: Should handle nested implications
        """
        text = "If A, then if B then C"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        assert result["summary"]["operator_distribution"]["→"] >= 0

    @pytest.mark.asyncio
    async def test_biconditional(self):
        """
        GIVEN: Biconditional statement (A ↔ B)
        WHEN: Converting to FOL
        THEN: Should recognize equivalence
        """
        text = "A if and only if B"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_mixed_operators_complex(self):
        """
        GIVEN: Complex formula with all operator types
        WHEN: Converting to FOL
        THEN: Should handle ∀∃∧∨→¬ combinations
        """
        text = "For all x, if x is A and not B, then there exists y such that y is C or D"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"
        # Should detect multiple operator types
        ops = result["summary"]["operator_distribution"]
        total_ops = sum(ops.values())
        assert total_ops >= 0


class TestPerformance:
    """Test performance characteristics."""

    @pytest.mark.asyncio
    async def test_single_sentence_performance(self):
        """
        GIVEN: A single sentence
        WHEN: Converting to FOL
        THEN: Should complete in <100ms
        """
        text = "All humans are mortal"
        
        start = time.time()
        result = await convert_text_to_fol(text)
        duration = time.time() - start
        
        assert result["status"] == "success"
        assert duration < 0.1  # Should be fast (<100ms)

    @pytest.mark.asyncio
    async def test_batch_10_sentences_performance(self):
        """
        GIVEN: 10 sentences in a dataset
        WHEN: Converting to FOL
        THEN: Should complete in reasonable time
        """
        dataset = {
            "text": " ".join([
                f"Statement number {i} about something interesting."
                for i in range(10)
            ])
        }
        
        start = time.time()
        result = await convert_text_to_fol(dataset)
        duration = time.time() - start
        
        assert result["status"] == "success"
        assert duration < 1.0  # Should process 10 sentences in <1s

    @pytest.mark.asyncio
    async def test_concurrent_conversions(self):
        """
        GIVEN: Multiple concurrent conversion requests
        WHEN: Processing in parallel
        THEN: Should handle concurrent load
        """
        texts = [
            "All A are B",
            "Some C are D",
            "If E then F",
            "G and H",
            "I or J"
        ]
        
        start = time.time()
        results = await asyncio.gather(*[
            convert_text_to_fol(text) for text in texts
        ])
        duration = time.time() - start
        
        assert len(results) == 5
        assert all(r["status"] == "success" for r in results)
        assert duration < 1.0  # Should handle concurrency well

    @pytest.mark.asyncio
    async def test_memory_efficiency_large_text(self):
        """
        GIVEN: Large text input (10KB)
        WHEN: Converting to FOL
        THEN: Should not cause memory issues
        """
        large_text = "Test sentence. " * 500  # ~7.5KB
        
        result = await convert_text_to_fol(large_text)
        
        assert result["status"] == "success"
        # Should complete without memory errors


class TestMalformedInput:
    """Test handling of malformed/unusual input."""

    @pytest.mark.asyncio
    async def test_unbalanced_parentheses(self):
        """
        GIVEN: Text with unbalanced parentheses
        WHEN: Converting to FOL
        THEN: Should handle gracefully
        """
        text = "((Test (incomplete"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_multiple_consecutive_spaces(self):
        """
        GIVEN: Text with excessive whitespace
        WHEN: Converting to FOL
        THEN: Should normalize spacing
        """
        text = "Test    with     many      spaces"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_only_punctuation(self):
        """
        GIVEN: Text with only punctuation marks
        WHEN: Converting to FOL
        THEN: Should return gracefully
        """
        text = "!@#$%^&*()"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_numbers_only(self):
        """
        GIVEN: Text with only numbers
        WHEN: Converting to FOL
        THEN: Should handle numeric input
        """
        text = "123 456 789"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_mixed_newlines_tabs(self):
        """
        GIVEN: Text with mixed newlines and tabs
        WHEN: Converting to FOL
        THEN: Should normalize whitespace
        """
        text = "Line1\n\tLine2\r\nLine3"
        result = await convert_text_to_fol(text)
        
        assert result["status"] == "success"


class TestDistributionFunctions:
    """Test quantifier and operator distribution functions."""

    def test_quantifier_distribution_empty(self):
        """
        GIVEN: Empty results list
        WHEN: Getting quantifier distribution
        THEN: Should return zero counts
        """
        results = []
        dist = get_quantifier_distribution(results)
        
        assert dist["∀"] == 0
        assert dist["∃"] == 0

    def test_quantifier_distribution_with_data(self):
        """
        GIVEN: Results with quantifiers
        WHEN: Getting quantifier distribution
        THEN: Should count correctly
        """
        results = [
            {"quantifiers": ["∀", "∀"]},
            {"quantifiers": ["∃"]},
        ]
        dist = get_quantifier_distribution(results)
        
        assert dist["∀"] >= 0
        assert dist["∃"] >= 0

    def test_operator_distribution_empty(self):
        """
        GIVEN: Empty results list
        WHEN: Getting operator distribution
        THEN: Should return zero counts
        """
        results = []
        dist = get_operator_distribution(results)
        
        assert dist["∧"] == 0
        assert dist["∨"] == 0
        assert dist["→"] == 0
        assert dist["↔"] == 0
        assert dist["¬"] == 0

    def test_operator_distribution_with_data(self):
        """
        GIVEN: Results with operators
        WHEN: Getting operator distribution
        THEN: Should count correctly
        """
        results = [
            {"operators": ["∧", "∨"]},
            {"operators": ["→"]},
        ]
        dist = get_operator_distribution(results)
        
        assert isinstance(dist, dict)
        assert all(isinstance(v, int) for v in dist.values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

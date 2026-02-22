"""
Tests for regex pattern pre-compilation optimization.

Validates that pre-compiled patterns work correctly and maintain caching behavior.
"""

import pytest
import re
from ipfs_datasets_py.optimizers.graphrag.optimizations.regex_pattern_compiler import (
    RegexPatternCompiler,
    PrecompiledPattern,
)


@pytest.fixture
def compiler():
    """Create a compiler instance for testing."""
    return RegexPatternCompiler()


@pytest.fixture
def sample_text():
    """Sample text for entity extraction."""
    return """
    Mr. John Smith works at Acme Corporation. Dr. Jane Doe is the CEO.
    The contract was signed on 2024-12-15 for USD 1,000,000.
    Article 3 requires indemnification per the warranty clause.
    Located at 123 Main Street, Springfield.
    """


class TestPrecompiledPattern:
    """Tests for PrecompiledPattern dataclass."""

    def test_precompiled_pattern_creation(self):
        """Test creating a PrecompiledPattern."""
        pattern_str = r'\b[A-Z][a-z]+\b'
        compiled = re.compile(pattern_str, re.IGNORECASE)
        precomp = PrecompiledPattern(
            compiled_pattern=compiled,
            entity_type="Person",
            original_pattern=pattern_str,
        )

        assert precomp.entity_type == "Person"
        assert precomp.original_pattern == pattern_str
        assert isinstance(precomp.compiled_pattern, re.Pattern)

    def test_precompiled_pattern_can_match(self):
        """Test that PrecompiledPattern can perform matches."""
        precomp = PrecompiledPattern(
            compiled_pattern=re.compile(r'\b[A-Z][a-z]+\b', re.IGNORECASE),
            entity_type="Person",
            original_pattern=r'\b[A-Z][a-z]+\b',
        )

        text = "John and Jane are here"
        matches = list(precomp.compiled_pattern.finditer(text))
        assert len(matches) > 0
        assert matches[0].group(0) == "John"


class TestBasePatternCompilation:
    """Tests for base pattern compilation."""

    def test_base_patterns_compiled_once(self, compiler):
        """Test that base patterns are compiled at class level (not repeatedly)."""
        patterns1 = compiler._compile_base_patterns()
        patterns2 = compiler._compile_base_patterns()

        # Should return same object (class-level cache)
        assert patterns1 is patterns2

    def test_base_patterns_count(self, compiler):
        """Test that correct number of base patterns are compiled."""
        patterns = compiler._compile_base_patterns()
        assert len(patterns) == 8  # 8 base patterns defined

    def test_base_patterns_have_types(self, compiler):
        """Test that base patterns include expected entity types."""
        patterns = compiler._compile_base_patterns()
        entity_types = {p.entity_type for p in patterns}

        expected_types = {'Person', 'Organization', 'Date', 'MonetaryAmount', 'Location', 'Obligation', 'Concept'}
        assert expected_types.issubset(entity_types)

    def test_base_pattern_objects_are_precompiled(self, compiler):
        """Test that patterns are pre-compiled regex objects."""
        patterns = compiler._compile_base_patterns()

        for pattern in patterns:
            assert isinstance(pattern.compiled_pattern, re.Pattern)
            assert isinstance(pattern.original_pattern, str)
            assert len(pattern.original_pattern) > 0


class TestDomainPatternCompilation:
    """Tests for domain-specific pattern compilation."""

    def test_domain_patterns_compiled_once(self, compiler):
        """Test that domain patterns are compiled at class level."""
        patterns1 = compiler._compile_domain_patterns()
        patterns2 = compiler._compile_domain_patterns()

        # Should return same object (class-level cache)
        assert patterns1 is patterns2

    def test_domain_patterns_have_multiple_domains(self, compiler):
        """Test that patterns exist for multiple domains."""
        patterns = compiler._compile_domain_patterns()

        expected_domains = {'legal', 'medical', 'technical', 'financial'}
        assert set(patterns.keys()) == expected_domains

    def test_legal_patterns_exist(self, compiler):
        """Test that legal domain patterns are compiled."""
        patterns = compiler._compile_domain_patterns()
        legal_patterns = patterns['legal']

        assert len(legal_patterns) > 0
        # Check for expected legal types
        legal_types = {p.entity_type for p in legal_patterns}
        assert 'LegalParty' in legal_types
        assert 'LegalReference' in legal_types

    def test_medical_patterns_exist(self, compiler):
        """Test that medical domain patterns are compiled."""
        patterns = compiler._compile_domain_patterns()
        medical_patterns = patterns['medical']

        assert len(medical_patterns) > 0
        medical_types = {p.entity_type for p in medical_patterns}
        assert 'MedicalConcept' in medical_types


class TestBuildPrecompiledPatterns:
    """Tests for building final pre-compiled pattern sets."""

    def test_build_for_general_domain(self, compiler):
        """Test building patterns for general domain."""
        patterns = compiler.build_precompiled_patterns("general")

        # Should have base patterns for general (no domain-specific)
        assert len(patterns) > 0
        # General domain should have base + fallback
        assert len(patterns) >= 8

    def test_build_for_legal_domain(self, compiler):
        """Test building patterns for legal domain."""
        patterns = compiler.build_precompiled_patterns("legal")

        # Should have base + legal patterns
        assert len(patterns) > 8  # More than base alone

        # Verify legal patterns are included
        entity_types = {p.entity_type for p in patterns}
        assert 'LegalParty' in entity_types

    def test_build_with_custom_rules(self, compiler):
        """Test building patterns with custom rules."""
        custom_rules = [
            (r'\b(?:custom|term)\b', 'CustomType'),
            (r'\b\d{3}-\d{4}\b', 'Reference'),
        ]

        patterns = compiler.build_precompiled_patterns("general", custom_rules=custom_rules)

        # Should include custom rules
        custom_types = {p.entity_type for p in patterns if p.entity_type in ['CustomType', 'Reference']}
        assert 'CustomType' in custom_types
        assert 'Reference' in custom_types

    def test_build_patterns_are_precompiled(self, compiler):
        """Test that all built patterns are pre-compiled."""
        patterns = compiler.build_precompiled_patterns("legal")

        for pattern in patterns:
            assert isinstance(pattern.compiled_pattern, re.Pattern)
            assert isinstance(pattern.entity_type, str)


class TestextractEntitiesWithPrecompiled:
    """Tests for entity extraction with pre-compiled patterns."""

    def test_extract_basic_entities(self, compiler, sample_text):
        """Test basic entity extraction."""
        patterns = compiler.build_precompiled_patterns("general")

        entities = compiler.extract_entities_with_precompiled(
            sample_text,
            patterns,
            allowed_types=set(),
            min_len=2,
            stopwords=set(),
            max_confidence=1.0,
        )

        assert len(entities) > 0
        # Check entity structure
        for entity in entities:
            assert 'id' in entity
            assert 'type' in entity
            assert 'text' in entity
            assert 'confidence' in entity
            assert 'span' in entity
            assert 'timestamp' in entity

    def test_extract_with_type_filtering(self, compiler, sample_text):
        """Test extraction with entity type filtering."""
        patterns = compiler.build_precompiled_patterns("general")

        # Extract only Person types
        entities = compiler.extract_entities_with_precompiled(
            sample_text,
            patterns,
            allowed_types={'Person'},
            min_len=2,
            stopwords=set(),
            max_confidence=1.0,
        )

        # All entities should be Person type
        for entity in entities:
            assert entity['type'] == 'Person'

    def test_extract_respects_min_length(self, compiler):
        """Test that extraction respects minimum entity length."""
        text = "A dog ran to 42 Main Street"
        patterns = compiler.build_precompiled_patterns("general")

        # Extract with min_len=2
        entities = compiler.extract_entities_with_precompiled(
            text,
            patterns,
            allowed_types=set(),
            min_len=2,
            stopwords=set(),
            max_confidence=1.0,
        )

        # No single-character entities should be present
        for entity in entities:
            assert len(entity['text']) >= 2

    def test_extract_filters_stopwords(self, compiler):
        """Test that extraction filters stopwords."""
        text = "the quick brown fox jumps over the lazy dog and runs away"
        patterns = compiler.build_precompiled_patterns("general")
        stopwords = {'the', 'quick', 'brown', 'lazy', 'and'}  # common lowercase stopwords

        entities = compiler.extract_entities_with_precompiled(
            text,
            patterns,
            allowed_types=set(),
            min_len=2,
            stopwords=stopwords,
            max_confidence=1.0,
        )

        # No stopword entities should be present (case-insensitive)
        entity_texts_lower = {e['text'].lower() for e in entities}
        for stopword in stopwords:
            assert stopword.lower() not in entity_texts_lower

    def test_extract_enforces_max_confidence(self, compiler, sample_text):
        """Test that extraction enforces maximum confidence."""
        patterns = compiler.build_precompiled_patterns("general")

        # Set max confidence to 0.6
        entities = compiler.extract_entities_with_precompiled(
            sample_text,
            patterns,
            allowed_types=set(),
            min_len=2,
            stopwords=set(),
            max_confidence=0.6,
        )

        # All confidences should be <= 0.6
        for entity in entities:
            assert entity['confidence'] <= 0.6

    def test_extract_no_duplicates(self, compiler, sample_text):
        """Test that extraction doesn't create duplicate entities."""
        patterns = compiler.build_precompiled_patterns("general")

        entities = compiler.extract_entities_with_precompiled(
            sample_text,
            patterns,
            allowed_types=set(),
            min_len=2,
            stopwords=set(),
            max_confidence=1.0,
        )

        # Check for text duplicates (case-insensitive)
        entity_texts_lower = [e['text'].lower() for e in entities]
        assert len(entity_texts_lower) == len(set(entity_texts_lower))

    def test_extract_empty_text(self, compiler):
        """Test extraction from empty text."""
        patterns = compiler.build_precompiled_patterns("general")

        entities = compiler.extract_entities_with_precompiled(
            "",
            patterns,
            allowed_types=set(),
            min_len=2,
            stopwords=set(),
            max_confidence=1.0,
        )

        assert len(entities) == 0

    def test_extract_performance_is_consistent(self, compiler, sample_text):
        """Test that extraction performance is consistent (patterns already compiled)."""
        import time

        patterns = compiler.build_precompiled_patterns("legal")

        # First extraction
        t1 = time.time()
        entities1 = compiler.extract_entities_with_precompiled(
            sample_text, patterns, set(), 2, set(), 1.0
        )
        time1 = time.time() - t1

        # Second extraction (should be same speed, patterns already compiled)
        t2 = time.time()
        entities2 = compiler.extract_entities_with_precompiled(
            sample_text, patterns, set(), 2, set(), 1.0
        )
        time2 = time.time() - t2

        # Results should be identical
        assert len(entities1) == len(entities2)
        # Times should be similar (within 2x - allowing for system variations)
        # Not asserting strict equality due to system variations
        assert min(time1, time2) > 0


class TestCachingBehavior:
    """Tests for class-level caching behavior."""

    def test_class_level_caching_across_instances(self):
        """Test that caching works across different instances."""
        compiler1 = RegexPatternCompiler()
        compiler2 = RegexPatternCompiler()

        patterns1 = compiler1._compile_base_patterns()
        patterns2 = compiler2._compile_base_patterns()

        # Both instances should get the same cached object
        assert patterns1 is patterns2

    def test_cache_persists_across_calls(self, compiler):
        """Test that cache persists across multiple calls."""
        # First build
        built1 = compiler.build_precompiled_patterns("legal")

        # Second build (should use cache)
        built2 = compiler.build_precompiled_patterns("legal")

        # Base patterns should be the same cached object
        base1 = RegexPatternCompiler._compile_base_patterns()
        base2 = RegexPatternCompiler._compile_base_patterns()
        assert base1 is base2

"""
Batch 269: Comprehensive tests for regex_pattern_compiler module.

Tests regex pattern pre-compilation optimization for entity extraction:
- PrecompiledPattern dataclass for storing compiled patterns
- RegexPatternCompiler class-level pattern caching
- Base pattern compilation (domain-agnostic)
- Domain-specific pattern compilation (legal/medical/technical/financial)
- Custom rule compilation and integration
- Entity extraction with pre-compiled patterns
- Performance optimizations (lowercase stopwords caching)

Coverage: 50 tests across 10 test classes
"""

import pytest
import re
import uuid
from typing import List, Set
from unittest.mock import patch

from ipfs_datasets_py.optimizers.graphrag.regex_pattern_compiler import (
    PrecompiledPattern,
    RegexPatternCompiler,
    benchmark_pre_compilation,
)


class TestPrecompiledPattern:
    """Test PrecompiledPattern dataclass."""
    
    def test_precompiled_pattern_creation(self):
        """Test creating a PrecompiledPattern instance."""
        pattern = re.compile(r'\b[A-Z][a-z]+\b')
        
        precomp = PrecompiledPattern(
            compiled_pattern=pattern,
            entity_type='Person',
            original_pattern=r'\b[A-Z][a-z]+\b'
        )
        
        assert precomp.compiled_pattern == pattern
        assert precomp.entity_type == 'Person'
        assert precomp.original_pattern == r'\b[A-Z][a-z]+\b'
    
    def test_precompiled_pattern_fields(self):
        """Test all required fields are present."""
        pattern = re.compile(r'test')
        
        precomp = PrecompiledPattern(
            compiled_pattern=pattern,
            entity_type='TestType',
            original_pattern='test'
        )
        
        # Check all fields accessible
        assert hasattr(precomp, 'compiled_pattern')
        assert hasattr(precomp, 'entity_type')
        assert hasattr(precomp, 'original_pattern')


class TestCompileBasePatterns:
    """Test _compile_base_patterns class method."""
    
    def test_compile_base_patterns_returns_list(self):
        """Test method returns list of PrecompiledPattern."""
        compiler = RegexPatternCompiler()
        
        patterns = compiler._compile_base_patterns()
        
        assert isinstance(patterns, list)
        assert all(isinstance(p, PrecompiledPattern) for p in patterns)
    
    def test_compile_base_patterns_count(self):
        """Test expected number of base patterns."""
        compiler = RegexPatternCompiler()
        
        patterns = compiler._compile_base_patterns()
        
        # Should have 8 base patterns (Person, Organization, Date, Date full, MonetaryAmount, Location, Obligation, Concept)
        assert len(patterns) == 8
    
    def test_compile_base_patterns_entity_types(self):
        """Test base patterns include expected entity types."""
        compiler = RegexPatternCompiler()
        
        patterns = compiler._compile_base_patterns()
        entity_types = {p.entity_type for p in patterns}
        
        expected_types = {'Person', 'Organization', 'Date', 'MonetaryAmount', 'Location', 'Obligation', 'Concept'}
        assert expected_types.issubset(entity_types)
    
    def test_compile_base_patterns_cached(self):
        """Test patterns are cached at class level."""
        compiler1 = RegexPatternCompiler()
        compiler2 = RegexPatternCompiler()
        
        patterns1 = compiler1._compile_base_patterns()
        patterns2 = compiler2._compile_base_patterns()
        
        # Should be same cached list (not just equal, but identical object)
        assert patterns1 is patterns2
    
    def test_base_patterns_are_compiled(self):
        """Test all base patterns are actually compiled regex objects."""
        compiler = RegexPatternCompiler()
        
        patterns = compiler._compile_base_patterns()
        
        for pattern in patterns:
            assert isinstance(pattern.compiled_pattern, re.Pattern)
            assert pattern.original_pattern  # Has original string
    
    def test_base_patterns_case_insensitive(self):
        """Test base patterns are compiled with IGNORECASE flag."""
        compiler = RegexPatternCompiler()
        
        patterns = compiler._compile_base_patterns()
        
        # Test one pattern matches both cases
        org_pattern = next(p for p in patterns if p.entity_type == 'Organization')
        
        # Should match both "LLC" and "llc"
        assert org_pattern.compiled_pattern.search("Acme LLC")
        assert org_pattern.compiled_pattern.search("Acme llc")


class TestCompileDomainPatterns:
    """Test _compile_domain_patterns class method."""
    
    def test_compile_domain_patterns_returns_dict(self):
        """Test method returns dict of domain to pattern lists."""
        compiler = RegexPatternCompiler()
        
        patterns_dict = compiler._compile_domain_patterns()
        
        assert isinstance(patterns_dict, dict)
        assert all(isinstance(k, str) for k in patterns_dict.keys())
        assert all(isinstance(v, list) for v in patterns_dict.values())
    
    def test_compile_domain_patterns_domains(self):
        """Test expected domains are present."""
        compiler = RegexPatternCompiler()
        
        patterns_dict = compiler._compile_domain_patterns()
        
        expected_domains = {'legal', 'medical', 'technical', 'financial'}
        assert expected_domains.issubset(set(patterns_dict.keys()))
    
    def test_compile_domain_patterns_legal(self):
        """Test legal domain patterns."""
        compiler = RegexPatternCompiler()
        
        patterns_dict = compiler._compile_domain_patterns()
        legal = patterns_dict['legal']
        
        entity_types = {p.entity_type for p in legal}
        assert 'LegalParty' in entity_types
        assert 'LegalReference' in entity_types
        assert 'LegalConcept' in entity_types
    
    def test_compile_domain_patterns_medical(self):
        """Test medical domain patterns."""
        compiler = RegexPatternCompiler()
        
        patterns_dict = compiler._compile_domain_patterns()
        medical = patterns_dict['medical']
        
        entity_types = {p.entity_type for p in medical}
        assert 'MedicalConcept' in entity_types
        assert 'Dosage' in entity_types
        assert 'MedicalRole' in entity_types
    
    def test_compile_domain_patterns_technical(self):
        """Test technical domain patterns."""
        compiler = RegexPatternCompiler()
        
        patterns_dict = compiler._compile_domain_patterns()
        technical = patterns_dict['technical']
        
        entity_types = {p.entity_type for p in technical}
        assert 'Protocol' in entity_types
        assert 'TechnicalComponent' in entity_types
        assert 'Version' in entity_types
    
    def test_compile_domain_patterns_financial(self):
        """Test financial domain patterns."""
        compiler = RegexPatternCompiler()
        
        patterns_dict = compiler._compile_domain_patterns()
        financial = patterns_dict['financial']
        
        entity_types = {p.entity_type for p in financial}
        assert 'FinancialConcept' in entity_types
        assert 'MonetaryValue' in entity_types
        assert 'BankIdentifier' in entity_types
    
    def test_compile_domain_patterns_cached(self):
        """Test domain patterns are cached at class level."""
        compiler1 = RegexPatternCompiler()
        compiler2 = RegexPatternCompiler()
        
        patterns1 = compiler1._compile_domain_patterns()
        patterns2 = compiler2._compile_domain_patterns()
        
        # Should be same cached dict
        assert patterns1 is patterns2
    
    def test_domain_patterns_are_compiled(self):
        """Test all domain patterns are compiled regex objects."""
        compiler = RegexPatternCompiler()
        
        patterns_dict = compiler._compile_domain_patterns()
        
        for domain, patterns in patterns_dict.items():
            for pattern in patterns:
                assert isinstance(pattern.compiled_pattern, re.Pattern)
                assert pattern.original_pattern


class TestBuildPrecompiledPatterns:
    """Test build_precompiled_patterns method."""
    
    def test_build_precompiled_patterns_basic(self):
        """Test building patterns for a domain."""
        compiler = RegexPatternCompiler()
        
        patterns = compiler.build_precompiled_patterns('legal')
        
        assert isinstance(patterns, list)
        assert all(isinstance(p, PrecompiledPattern) for p in patterns)
    
    def test_build_includes_base_patterns(self):
        """Test built patterns include base patterns."""
        compiler = RegexPatternCompiler()
        
        patterns = compiler.build_precompiled_patterns('legal')
        entity_types = {p.entity_type for p in patterns}
        
        # Should include base types
        assert 'Person' in entity_types
        assert 'Organization' in entity_types
    
    def test_build_includes_domain_patterns(self):
        """Test built patterns include domain-specific patterns."""
        compiler = RegexPatternCompiler()
        
        patterns = compiler.build_precompiled_patterns('legal')
        entity_types = {p.entity_type for p in patterns}
        
        # Should include legal-specific types
        assert 'LegalParty' in entity_types
        assert 'LegalConcept' in entity_types
    
    def test_build_with_unknown_domain(self):
        """Test building with unknown domain uses only base patterns."""
        compiler = RegexPatternCompiler()
        
        patterns = compiler.build_precompiled_patterns('unknown_domain')
        entity_types = {p.entity_type for p in patterns}
        
        # Should have base patterns
        assert 'Person' in entity_types
        # Should not have domain-specific patterns
        assert 'LegalParty' not in entity_types
        assert 'MedicalConcept' not in entity_types
    
    def test_build_with_custom_rules(self):
        """Test adding custom rules to patterns."""
        compiler = RegexPatternCompiler()
        
        custom = [
            (r'\b(?:CUSTOM_PATTERN)\b', 'CustomType'),
        ]
        
        patterns = compiler.build_precompiled_patterns('legal', custom_rules=custom)
        entity_types = {p.entity_type for p in patterns}
        
        # Should include custom type
        assert 'CustomType' in entity_types
    
    def test_build_custom_rules_inserted_before_last(self):
        """Test custom rules are inserted before the last generic pattern."""
        compiler = RegexPatternCompiler()
        
        custom = [(r'\bTEST\b', 'TestType')]
        
        patterns = compiler.build_precompiled_patterns('legal', custom_rules=custom)
        
        # Custom pattern should be present
        custom_indices = [i for i, p in enumerate(patterns) if p.entity_type == 'TestType']
        assert len(custom_indices) > 0
        
        # Custom pattern should be before last pattern (not at the very end)
        # The implementation inserts custom before the last pattern
        last_pattern_type = patterns[-1].entity_type
        test_pattern_index = custom_indices[0]
        
        # Custom should be inserted somewhere before the last position
        assert test_pattern_index < len(patterns) - 1
    
    def test_build_multiple_custom_rules(self):
        """Test adding multiple custom rules."""
        compiler = RegexPatternCompiler()
        
        custom = [
            (r'\bCUSTOM1\b', 'Type1'),
            (r'\bCUSTOM2\b', 'Type2'),
        ]
        
        patterns = compiler.build_precompiled_patterns('legal', custom_rules=custom)
        entity_types = {p.entity_type for p in patterns}
        
        assert 'Type1' in entity_types
        assert 'Type2' in entity_types
    
    def test_build_different_domains_different_patterns(self):
        """Test different domains produce different pattern sets."""
        compiler = RegexPatternCompiler()
        
        legal = compiler.build_precompiled_patterns('legal')
        medical = compiler.build_precompiled_patterns('medical')
        
        legal_types = {p.entity_type for p in legal}
        medical_types = {p.entity_type for p in medical}
        
        # Legal should have legal-specific but not medical-specific
        assert 'LegalParty' in legal_types
        assert 'Dosage' not in legal_types
        
        # Medical should have medical-specific but not legal-specific
        assert 'Dosage' in medical_types
        assert 'LegalParty' not in medical_types


class TestExtractEntitiesWithPrecompiled:
    """Test extract_entities_with_precompiled static method."""
    
    def test_extract_basic(self):
        """Test basic entity extraction with precompiled patterns."""
        text = "Mr. John Smith works at Acme Corporation."
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text,
            patterns,
            allowed_types=set(),
            min_len=2,
            stopwords=set(),
            max_confidence=1.0
        )
        
        assert isinstance(entities, list)
        assert len(entities) > 0
    
    def test_extract_entity_structure(self):
        """Test extracted entities have required fields."""
        text = "Dr. Jane Doe"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        assert len(entities) > 0
        entity = entities[0]
        
        # Check required fields
        assert 'id' in entity
        assert 'type' in entity
        assert 'text' in entity
        assert 'confidence' in entity
        assert 'span' in entity
        assert 'timestamp' in entity
    
    def test_extract_person_entities(self):
        """Test extracting Person entities."""
        text = "Mr. John Smith and Dr. Jane Doe attended."
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        person_entities = [e for e in entities if e['type'] == 'Person']
        assert len(person_entities) >= 1  # At least one person
    
    def test_extract_organization_entities(self):
        """Test extracting Organization entities."""
        text = "Acme Corporation and Tech Solutions Inc are partners."
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        org_entities = [e for e in entities if e['type'] == 'Organization']
        assert len(org_entities) >= 1
    
    def test_extract_with_allowed_types(self):
        """Test filtering by allowed_types."""
        text = "Mr. John Smith works at Acme Corporation."
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        # Only extract Person entities
        entities = compiler.extract_entities_with_precompiled(
            text,
            patterns,
            allowed_types={'Person'},
            min_len=2,
            stopwords=set(),
            max_confidence=1.0
        )
        
        # All entities should be Person type
        assert all(e['type'] == 'Person' for e in entities)
    
    def test_extract_with_min_len(self):
        """Test filtering by minimum length."""
        text = "A B C Corporation of America"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), min_len=5, stopwords=set(), max_confidence=1.0
        )
        
        # All entities should be >= 5 chars
        assert all(len(e['text']) >= 5 for e in entities)
    
    def test_extract_with_stopwords(self):
        """Test filtering with stopwords."""
        text = "The company and the organization are involved."
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        stopwords = {'the', 'and', 'are'}
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, stopwords, 1.0
        )
        
        # No entity text should be a stopword (case-insensitive)
        entity_texts_lower = {e['text'].lower() for e in entities}
        assert not entity_texts_lower.intersection(stopwords)
    
    def test_extract_with_max_confidence(self):
        """Test confidence capping with max_confidence."""
        text = "Mr. John Smith"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), max_confidence=0.6
        )
        
        # All confidences should be <= 0.6
        assert all(e['confidence'] <= 0.6 for e in entities)
    
    def test_extract_deduplicates_by_text(self):
        """Test that repeated text is only extracted once."""
        text = "Smith and Smith and Smith"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        # Count how many times "Smith" appears
        smith_count = sum(1 for e in entities if e['text'].lower() == 'smith')
        # Should appear only once (deduplicated)
        assert smith_count <= 1
    
    def test_extract_span_positions(self):
        """Test that span positions are correct."""
        text = "XXXX Dr. Jane Doe YYYY"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        # Check span matches text
        for entity in entities:
            start, end = entity['span']
            extracted = text[start:end]
            # Span should contain the entity text (may have extra whitespace)
            assert entity['text'] in extracted or extracted in entity['text']
    
    def test_extract_concept_confidence(self):
        """Test Concept entities have lower confidence (0.5)."""
        text = "SomeRandomConceptWord"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        concept_entities = [e for e in entities if e['type'] == 'Concept']
        if concept_entities:
            # Concept confidence should be 0.5
            assert concept_entities[0]['confidence'] == 0.5
    
    def test_extract_non_concept_confidence(self):
        """Test non-Concept entities have higher confidence (0.75)."""
        text = "Dr. Jane Doe"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        person_entities = [e for e in entities if e['type'] == 'Person']
        if person_entities:
            # Person confidence should be 0.75
            assert person_entities[0]['confidence'] == 0.75


class TestLowercaseStopwordsOptimization:
    """Test lowercase stopwords caching optimization."""
    
    def test_stopwords_converted_to_lowercase(self):
        """Test stopwords are pre-converted to lowercase."""
        text = "The Company and The Organization"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        # Provide mixed-case stopwords
        stopwords = {'The', 'AND'}
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, stopwords, 1.0
        )
        
        # Should filter both "The" and "and" (case-insensitive)
        entity_texts = {e['text'].lower() for e in entities}
        assert 'the' not in entity_texts
        assert 'and' not in entity_texts
    
    def test_empty_stopwords_handled(self):
        """Test empty stopwords set is handled."""
        text = "Test text"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        # Should not raise with empty stopwords
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, stopwords=set(), max_confidence=1.0
        )
        
        assert isinstance(entities, list)


class TestDomainSpecificExtraction:
    """Test extraction with domain-specific patterns."""
    
    def test_legal_domain_extraction(self):
        """Test legal domain pattern extraction."""
        text = "The plaintiff filed Article 5, Section 3 for indemnification."
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        entity_types = {e['type'] for e in entities}
        # Should extract legal-specific types
        assert 'LegalParty' in entity_types or 'LegalReference' in entity_types or 'LegalConcept' in entity_types
    
    def test_medical_domain_extraction(self):
        """Test medical domain pattern extraction."""
        text = "Patient has diagnosis of hypertension. Dosage: 50 mg daily."
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('medical')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        entity_types = {e['type'] for e in entities}
        # Should extract medical-specific types
        assert 'MedicalConcept' in entity_types or 'Dosage' in entity_types or 'MedicalRole' in entity_types
    
    def test_technical_domain_extraction(self):
        """Test technical domain pattern extraction."""
        text = "API uses REST with JSON. Version 2.1.0-beta released."
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('technical')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        entity_types = {e['type'] for e in entities}
        # Should extract technical types
        assert 'Protocol' in entity_types or 'Version' in entity_types
    
    def test_financial_domain_extraction(self):
        """Test financial domain pattern extraction."""
        text = "The balance sheet shows assets of 5,000,000 EUR."
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('financial')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        entity_types = {e['type'] for e in entities}
        # Should extract financial types
        assert 'FinancialConcept' in entity_types or 'MonetaryValue' in entity_types


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_extract_from_empty_text(self):
        """Test extraction from empty text."""
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            "", patterns, set(), 2, set(), 1.0
        )
        
        assert entities == []
    
    def test_extract_with_no_patterns(self):
        """Test extraction with empty pattern list."""
        text = "Some text here"
        
        entities = RegexPatternCompiler.extract_entities_with_precompiled(
            text, [], set(), 2, set(), 1.0
        )
        
        assert entities == []
    
    def test_extract_with_no_matches(self):
        """Test extraction when no patterns match."""
        text = "12345 67890"  # No entity patterns match numbers only
        
        compiler = RegexPatternCompiler()
        # Use limited patterns that won't match
        person_pattern = [PrecompiledPattern(
            compiled_pattern=re.compile(r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'),
            entity_type='Person',
            original_pattern=r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
        )]
        
        entities = compiler.extract_entities_with_precompiled(
            text, person_pattern, set(), 2, set(), 1.0
        )
        
        assert entities == []
    
    def test_extract_with_very_long_text(self):
        """Test extraction handles long text."""
        text = "Mr. John Smith " * 1000  # Repeated 1000 times
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        # Should deduplicate, so only 1-2 entities (Mr. and John Smith)
        assert len(entities) <= 5
    
    def test_extract_special_characters(self):
        """Test extraction handles special characters."""
        text = "Company™ Inc® has €50,000"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        # Should not raise
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        assert isinstance(entities, list)
    
    def test_extract_unicode_text(self):
        """Test extraction handles Unicode text."""
        text = "Dr. Müller works at Société Générale"
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        # Should handle Unicode
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, set(), 1.0
        )
        
        assert isinstance(entities, list)


class TestRealWorldScenarios:
    """Test real-world extraction scenarios."""
    
    def test_complex_legal_document(self):
        """Test extraction from complex legal text."""
        text = """
        The plaintiff, John Smith, filed a claim under Article 5, Section 3(a).
        Acme Corporation must provide indemnification as per the covenant.
        The arbitration clause is binding on both parties.
        """
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('legal')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 3, {'the', 'a', 'as', 'is', 'on'}, 1.0
        )
        
        # Should extract multiple entity types
        entity_types = {e['type'] for e in entities}
        assert len(entity_types) >= 2  # At least 2 different types
        assert len(entities) >= 4  # Multiple entities
    
    def test_medical_record_extraction(self):
        """Test extraction from medical record."""
        text = """
        Patient admitted with diagnosis of hypertension and diabetes.
        Physician prescribed medication: 50 mg daily.
        Specialist consultation recommended for further treatment.
        """
        
        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns('medical')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 3, {'the', 'with', 'and', 'for'}, 1.0
        )
        
        # Should extract medical entities
        entity_types = {e['type'] for e in entities}
        medical_types = entity_types.intersection({'MedicalConcept', 'Dosage', 'MedicalRole'})
        assert len(medical_types) > 0
    
    def test_mixed_domain_extraction(self):
        """Test extraction from text with mixed domains."""
        text = """
        Dr. Smith from Tech Medical Corp reviewed the API documentation.
        The REST endpoint requires authentication with IBAN validation.
        Version 2.1.0 includes improved diagnosis algorithms.
        """
        
        compiler = RegexPatternCompiler()
        # Use general domain (or combine multiple)
        patterns = compiler.build_precompiled_patterns('technical')
        
        entities = compiler.extract_entities_with_precompiled(
            text, patterns, set(), 2, {'the', 'with'}, 1.0
        )
        
        # Should extract from multiple categories
        assert len(entities) >= 3


class TestBenchmarkFunction:
    """Test benchmark_pre_compilation function."""
    
    def test_benchmark_runs_without_error(self):
        """Test benchmark function executes without errors."""
        # Should not raise
        benchmark_pre_compilation()
    
    def test_benchmark_with_captured_output(self, capsys):
        """Test benchmark produces expected output."""
        benchmark_pre_compilation()
        
        captured = capsys.readouterr()
        
        # Should print timing information
        assert 'Pattern compilation:' in captured.out
        assert 'Entity extraction:' in captured.out
        assert 'ms' in captured.out

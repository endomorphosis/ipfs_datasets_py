"""
Tests for TDFOL Pattern Matcher

Tests the PatternMatcher class for matching legal and deontic language patterns
including universal quantification, obligations, permissions, prohibitions,
temporal expressions, and conditionals.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import (
    PatternMatcher,
    Pattern,
    PatternMatch,
    PatternType,
    HAVE_SPACY,
)

# Skip all tests if spaCy is not installed
pytestmark = pytest.mark.skipif(
    not HAVE_SPACY,
    reason="spaCy is not installed. Install with: pip install ipfs_datasets_py[knowledge_graphs]"
)


@pytest.fixture
def matcher():
    """Create pattern matcher instance."""
    try:
        return PatternMatcher()
    except (ImportError, OSError) as e:
        pytest.skip(f"Could not initialize pattern matcher: {e}")


class TestPatternMatcher:
    """Test suite for Pattern Matcher."""
    
    def test_initialization(self):
        """Test pattern matcher initialization."""
        # GIVEN: spaCy is available
        # WHEN: Creating pattern matcher
        matcher = PatternMatcher()
        
        # THEN: Matcher should be initialized with patterns
        assert matcher is not None
        assert len(matcher.patterns) > 0
        assert matcher.nlp is not None
        assert matcher.matcher is not None
    
    def test_pattern_count(self, matcher):
        """Test that all pattern categories are loaded."""
        # GIVEN: Initialized matcher
        # WHEN: Getting pattern counts
        counts = matcher.get_pattern_count()
        
        # THEN: Should have patterns in all categories
        assert counts[PatternType.UNIVERSAL_QUANTIFICATION] >= 10
        assert counts[PatternType.OBLIGATION] >= 7
        assert counts[PatternType.PERMISSION] >= 7
        assert counts[PatternType.PROHIBITION] >= 6
        assert counts[PatternType.TEMPORAL] >= 10
        assert counts[PatternType.CONDITIONAL] >= 5
        
        # Total should be 40+
        total = sum(counts.values())
        assert total >= 45


class TestUniversalQuantification:
    """Test universal quantification patterns."""
    
    def test_all_agent_must_action(self, matcher):
        """Test 'all <agent> must <action>' pattern."""
        # GIVEN: Text with universal quantification
        text = "All contractors must pay taxes."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match universal quantification
        assert len(matches) > 0
        universal_matches = [m for m in matches if m.pattern.type == PatternType.UNIVERSAL_QUANTIFICATION]
        assert len(universal_matches) > 0
        assert "All" in matches[0].text or "all" in matches[0].text.lower()
    
    def test_every_agent_verb(self, matcher):
        """Test 'every <agent> <verb>' pattern."""
        # GIVEN: Text with 'every'
        text = "Every employee must attend training."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match universal quantification
        universal_matches = [m for m in matches if m.pattern.type == PatternType.UNIVERSAL_QUANTIFICATION]
        assert len(universal_matches) > 0
    
    def test_any_agent_verb(self, matcher):
        """Test 'any <agent> <verb>' pattern."""
        # GIVEN: Text with 'any'
        text = "Any contractor may submit a bid."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match universal quantification
        universal_matches = [m for m in matches if m.pattern.type == PatternType.UNIVERSAL_QUANTIFICATION]
        assert len(universal_matches) > 0


class TestObligationPatterns:
    """Test obligation patterns."""
    
    def test_agent_must_action(self, matcher):
        """Test '<agent> must <action>' pattern."""
        # GIVEN: Text with obligation
        text = "Contractor must deliver the goods."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match obligation
        obligation_matches = [m for m in matches if m.pattern.type == PatternType.OBLIGATION]
        assert len(obligation_matches) > 0
        assert "must" in matches[0].text.lower()
    
    def test_agent_shall_action(self, matcher):
        """Test '<agent> shall <action>' pattern."""
        # GIVEN: Text with 'shall'
        text = "Party shall perform its obligations."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match obligation
        obligation_matches = [m for m in matches if m.pattern.type == PatternType.OBLIGATION]
        assert len(obligation_matches) > 0
        assert "shall" in matches[0].text.lower()
    
    def test_agent_is_required_to(self, matcher):
        """Test '<agent> is required to <action>' pattern."""
        # GIVEN: Text with 'is required to'
        text = "Contractor is required to submit documentation."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match obligation
        obligation_matches = [m for m in matches if m.pattern.type == PatternType.OBLIGATION]
        assert len(obligation_matches) > 0


class TestPermissionPatterns:
    """Test permission patterns."""
    
    def test_agent_may_action(self, matcher):
        """Test '<agent> may <action>' pattern."""
        # GIVEN: Text with permission
        text = "Contractor may request an extension."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match permission
        permission_matches = [m for m in matches if m.pattern.type == PatternType.PERMISSION]
        assert len(permission_matches) > 0
        assert "may" in matches[0].text.lower()
    
    def test_agent_can_action(self, matcher):
        """Test '<agent> can <action>' pattern."""
        # GIVEN: Text with 'can'
        text = "Employee can file a complaint."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match permission
        permission_matches = [m for m in matches if m.pattern.type == PatternType.PERMISSION]
        assert len(permission_matches) > 0
    
    def test_agent_is_allowed_to(self, matcher):
        """Test '<agent> is allowed to <action>' pattern."""
        # GIVEN: Text with 'is allowed to'
        text = "Contractor is allowed to subcontract work."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match permission
        permission_matches = [m for m in matches if m.pattern.type == PatternType.PERMISSION]
        assert len(permission_matches) > 0


class TestProhibitionPatterns:
    """Test prohibition patterns."""
    
    def test_agent_must_not_action(self, matcher):
        """Test '<agent> must not <action>' pattern."""
        # GIVEN: Text with prohibition
        text = "Contractor must not disclose confidential information."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match prohibition
        prohibition_matches = [m for m in matches if m.pattern.type == PatternType.PROHIBITION]
        assert len(prohibition_matches) > 0
        assert "must not" in matches[0].text.lower()
    
    def test_agent_shall_not_action(self, matcher):
        """Test '<agent> shall not <action>' pattern."""
        # GIVEN: Text with 'shall not'
        text = "Party shall not terminate the agreement."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match prohibition
        prohibition_matches = [m for m in matches if m.pattern.type == PatternType.PROHIBITION]
        assert len(prohibition_matches) > 0
    
    def test_agent_is_forbidden_to(self, matcher):
        """Test '<agent> is forbidden to <action>' pattern."""
        # GIVEN: Text with 'is forbidden to'
        text = "Contractor is forbidden to use proprietary methods."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match prohibition
        prohibition_matches = [m for m in matches if m.pattern.type == PatternType.PROHIBITION]
        assert len(prohibition_matches) > 0


class TestTemporalPatterns:
    """Test temporal patterns."""
    
    def test_always_action(self, matcher):
        """Test 'always <action>' pattern."""
        # GIVEN: Text with 'always'
        text = "Contractor must always comply with regulations."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match temporal
        temporal_matches = [m for m in matches if m.pattern.type == PatternType.TEMPORAL]
        assert len(temporal_matches) > 0
    
    def test_within_time_action(self, matcher):
        """Test 'within <time>' pattern."""
        # GIVEN: Text with deadline
        text = "Payment must be made within 30 days."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match temporal
        temporal_matches = [m for m in matches if m.pattern.type == PatternType.TEMPORAL]
        assert len(temporal_matches) > 0
        assert any("30 days" in m.text.lower() for m in temporal_matches)
    
    def test_after_time_action(self, matcher):
        """Test 'after <time>' pattern."""
        # GIVEN: Text with 'after'
        text = "Notice must be given after 10 days."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match temporal
        temporal_matches = [m for m in matches if m.pattern.type == PatternType.TEMPORAL]
        assert len(temporal_matches) > 0


class TestConditionalPatterns:
    """Test conditional patterns."""
    
    def test_if_then_pattern(self, matcher):
        """Test 'if <condition> then <consequence>' pattern."""
        # GIVEN: Text with conditional
        text = "If payment is received, then goods will be delivered."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match conditional
        conditional_matches = [m for m in matches if m.pattern.type == PatternType.CONDITIONAL]
        assert len(conditional_matches) > 0
    
    def test_when_event_action(self, matcher):
        """Test 'when <event> <action>' pattern."""
        # GIVEN: Text with 'when'
        text = "When contract expires, parties must renegotiate."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match conditional
        conditional_matches = [m for m in matches if m.pattern.type == PatternType.CONDITIONAL]
        assert len(conditional_matches) > 0
    
    def test_provided_that(self, matcher):
        """Test 'provided that' pattern."""
        # GIVEN: Text with 'provided that'
        text = "Contractor may proceed provided that permits are obtained."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should match conditional
        conditional_matches = [m for m in matches if m.pattern.type == PatternType.CONDITIONAL]
        assert len(conditional_matches) > 0


class TestEntityExtraction:
    """Test entity extraction from matches."""
    
    def test_extract_agent(self, matcher):
        """Test agent extraction from match."""
        # GIVEN: Text with clear agent
        text = "Contractor must pay taxes."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should extract agent
        assert len(matches) > 0
        if matches[0].entities:
            assert "agent" in matches[0].entities or "action" in matches[0].entities
    
    def test_extract_action(self, matcher):
        """Test action extraction from match."""
        # GIVEN: Text with clear action
        text = "Contractor must deliver goods."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should extract action
        assert len(matches) > 0
        # At least one match should have entities
        has_entities = any(m.entities for m in matches)
        assert has_entities
    
    def test_extract_modality(self, matcher):
        """Test modality extraction from match."""
        # GIVEN: Text with modal verb
        text = "Contractor must pay taxes."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should extract modality
        assert len(matches) > 0
        # Check if any match extracted modality
        has_modality = any("modality" in m.entities for m in matches)
        assert has_modality or "must" in matches[0].text.lower()


class TestConfidenceScoring:
    """Test confidence scoring."""
    
    def test_confidence_range(self, matcher):
        """Test that confidence scores are in valid range."""
        # GIVEN: Sample text
        text = "All contractors must pay taxes."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: All confidences should be 0.0-1.0
        for match in matches:
            assert 0.0 <= match.confidence <= 1.0
    
    def test_min_confidence_filter(self, matcher):
        """Test minimum confidence filtering."""
        # GIVEN: Sample text
        text = "Contractor must pay taxes."
        
        # WHEN: Matching with high confidence threshold
        high_conf_matches = matcher.match(text, min_confidence=0.9)
        low_conf_matches = matcher.match(text, min_confidence=0.5)
        
        # THEN: High threshold should return fewer or equal matches
        assert len(high_conf_matches) <= len(low_conf_matches)


class TestComplexSentences:
    """Test complex sentence matching."""
    
    def test_multiple_patterns_in_sentence(self, matcher):
        """Test sentence with multiple patterns."""
        # GIVEN: Complex sentence
        text = "All contractors must pay taxes within 30 days."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should find multiple patterns
        assert len(matches) >= 2  # Universal + Obligation/Temporal
        pattern_types = {m.pattern.type for m in matches}
        assert len(pattern_types) >= 2
    
    def test_nested_patterns(self, matcher):
        """Test nested pattern matching."""
        # GIVEN: Sentence with nested constructs
        text = "If contractor completes work, then payment must be made within 30 days."
        
        # WHEN: Matching patterns
        matches = matcher.match(text)
        
        # THEN: Should find conditional and temporal patterns
        assert len(matches) >= 2
        has_conditional = any(m.pattern.type == PatternType.CONDITIONAL for m in matches)
        has_temporal = any(m.pattern.type == PatternType.TEMPORAL for m in matches)
        assert has_conditional or has_temporal


class TestPatternType:
    """Test PatternType enum."""
    
    def test_pattern_types_defined(self):
        """Test that all pattern types are defined."""
        # GIVEN: PatternType enum
        # WHEN: Checking types
        # THEN: Should have all required types
        assert PatternType.UNIVERSAL_QUANTIFICATION
        assert PatternType.OBLIGATION
        assert PatternType.PERMISSION
        assert PatternType.PROHIBITION
        assert PatternType.TEMPORAL
        assert PatternType.CONDITIONAL

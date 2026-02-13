"""
Comprehensive tests for SymbolicFOLBridge module.

Tests the bridge between SymbolicAI and FOL system for natural language
to logic conversion with semantic analysis.
"""

import pytest
from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import (
    SymbolicFOLBridge,
    LogicalComponents,
    FOLConversionResult,
    SYMBOLIC_AI_AVAILABLE,
)


class TestLogicalComponents:
    """Tests for LogicalComponents dataclass."""
    
    def test_logical_components_initialization(self):
        """GIVEN logical component data
        WHEN LogicalComponents is created
        THEN all fields are set correctly"""
        components = LogicalComponents(
            quantifiers=["∀", "∃"],
            predicates=["P", "Q"],
            entities=["x", "y"],
            logical_connectives=["∧", "→"],
            confidence=0.85,
            raw_text="All x are P and Q"
        )
        
        assert components.quantifiers == ["∀", "∃"]
        assert components.predicates == ["P", "Q"]
        assert components.entities == ["x", "y"]
        assert components.logical_connectives == ["∧", "→"]
        assert components.confidence == 0.85
        assert components.raw_text == "All x are P and Q"
    
    def test_logical_components_empty(self):
        """GIVEN empty component data
        WHEN LogicalComponents is created
        THEN empty lists are accepted"""
        components = LogicalComponents(
            quantifiers=[],
            predicates=[],
            entities=[],
            logical_connectives=[],
            confidence=0.0,
            raw_text=""
        )
        
        assert len(components.quantifiers) == 0
        assert len(components.predicates) == 0
        assert components.confidence == 0.0


class TestFOLConversionResult:
    """Tests for FOLConversionResult dataclass."""
    
    def test_conversion_result_initialization(self):
        """GIVEN conversion result data
        WHEN FOLConversionResult is created
        THEN all fields are properly initialized"""
        components = LogicalComponents(
            quantifiers=["∀"],
            predicates=["P"],
            entities=["x"],
            logical_connectives=[],
            confidence=0.9,
            raw_text="All x are P"
        )
        
        result = FOLConversionResult(
            fol_formula="∀x.P(x)",
            components=components,
            confidence=0.9,
            reasoning_steps=["Step 1", "Step 2"],
            fallback_used=False
        )
        
        assert result.fol_formula == "∀x.P(x)"
        assert result.components == components
        assert result.confidence == 0.9
        assert len(result.reasoning_steps) == 2
        assert result.fallback_used is False
        assert result.errors == []
    
    def test_conversion_result_with_errors(self):
        """GIVEN conversion result with errors
        WHEN FOLConversionResult is created
        THEN errors list is accessible"""
        components = LogicalComponents(
            quantifiers=[],
            predicates=[],
            entities=[],
            logical_connectives=[],
            confidence=0.5,
            raw_text="invalid"
        )
        
        result = FOLConversionResult(
            fol_formula="",
            components=components,
            confidence=0.5,
            reasoning_steps=[],
            fallback_used=True,
            errors=["Parse error"]
        )
        
        assert result.fallback_used is True
        assert len(result.errors) == 1
        assert result.errors[0] == "Parse error"


class TestSymbolicFOLBridge:
    """Tests for SymbolicFOLBridge class."""
    
    def test_bridge_initialization_default(self):
        """GIVEN default parameters
        WHEN SymbolicFOLBridge is initialized
        THEN default settings are applied"""
        bridge = SymbolicFOLBridge()
        
        assert bridge.confidence_threshold == 0.7
        assert bridge.fallback_enabled is True
        assert bridge.enable_caching is True
        assert isinstance(bridge._cache, dict)
        assert len(bridge._cache) == 0
    
    def test_bridge_initialization_custom(self):
        """GIVEN custom parameters
        WHEN SymbolicFOLBridge is initialized
        THEN custom settings are applied"""
        bridge = SymbolicFOLBridge(
            confidence_threshold=0.9,
            fallback_enabled=False,
            enable_caching=False
        )
        
        assert bridge.confidence_threshold == 0.9
        assert bridge.fallback_enabled is False
        assert bridge.enable_caching is False
    
    def test_bridge_cache_key_generation(self):
        """GIVEN text input
        WHEN cache key is generated
        THEN consistent hash is produced"""
        bridge = SymbolicFOLBridge()
        
        text1 = "All humans are mortal"
        text2 = "All humans are mortal"
        text3 = "Some humans are mortal"
        
        # Same text should produce same key
        key1 = bridge._get_cache_key(text1)
        key2 = bridge._get_cache_key(text2)
        key3 = bridge._get_cache_key(text3)
        
        assert key1 == key2
        assert key1 != key3
        assert isinstance(key1, str)
        assert len(key1) == 64  # SHA-256 hex digest
    
    def test_bridge_extract_quantifiers(self):
        """GIVEN text with quantifiers
        WHEN quantifiers are extracted
        THEN correct quantifier symbols are identified"""
        bridge = SymbolicFOLBridge()
        
        text1 = "All students study"
        text2 = "Some students study"
        text3 = "Every student and some teachers"
        
        quants1 = bridge._extract_quantifiers(text1)
        quants2 = bridge._extract_quantifiers(text2)
        quants3 = bridge._extract_quantifiers(text3)
        
        assert "∀" in quants1  # "all" -> ∀
        assert "∃" in quants2  # "some" -> ∃
        assert "∀" in quants3 and "∃" in quants3  # both
    
    def test_bridge_extract_predicates_simple(self):
        """GIVEN simple text
        WHEN predicates are extracted
        THEN predicate symbols are identified"""
        bridge = SymbolicFOLBridge()
        
        text = "Student(x) and Smart(x)"
        predicates = bridge._extract_predicates(text)
        
        assert "Student" in predicates
        assert "Smart" in predicates
        assert len(predicates) >= 2
    
    def test_bridge_extract_entities(self):
        """GIVEN text with entities
        WHEN entities are extracted
        THEN entity names are identified"""
        bridge = SymbolicFOLBridge()
        
        text = "John is a student and Mary is a teacher"
        entities = bridge._extract_entities(text)
        
        assert "John" in entities
        assert "Mary" in entities
    
    def test_bridge_extract_connectives(self):
        """GIVEN text with logical connectives
        WHEN connectives are extracted
        THEN logical operators are identified"""
        bridge = SymbolicFOLBridge()
        
        text1 = "P and Q"
        text2 = "P or Q"
        text3 = "if P then Q"
        text4 = "P iff Q"
        text5 = "not P"
        
        conn1 = bridge._extract_connectives(text1)
        conn2 = bridge._extract_connectives(text2)
        conn3 = bridge._extract_connectives(text3)
        conn4 = bridge._extract_connectives(text4)
        conn5 = bridge._extract_connectives(text5)
        
        assert "∧" in conn1
        assert "∨" in conn2
        assert "→" in conn3
        assert "↔" in conn4
        assert "¬" in conn5
    
    def test_bridge_pattern_based_conversion_simple(self):
        """GIVEN simple universal statement
        WHEN pattern-based conversion is applied
        THEN correct FOL formula is generated"""
        bridge = SymbolicFOLBridge()
        
        text = "All humans are mortal"
        result = bridge._pattern_based_conversion(text)
        
        assert result is not None
        assert "∀" in result
        assert "→" in result
    
    def test_bridge_pattern_based_conversion_existential(self):
        """GIVEN existential statement
        WHEN pattern-based conversion is applied
        THEN correct FOL formula is generated"""
        bridge = SymbolicFOLBridge()
        
        text = "Some students are smart"
        result = bridge._pattern_based_conversion(text)
        
        assert result is not None
        assert "∃" in result
        assert "∧" in result
    
    def test_bridge_pattern_based_conversion_none(self):
        """GIVEN text with no clear pattern
        WHEN pattern-based conversion is attempted
        THEN None is returned"""
        bridge = SymbolicFOLBridge()
        
        text = "random unstructured text without logic"
        result = bridge._pattern_based_conversion(text)
        
        assert result is None
    
    def test_bridge_semantic_conversion_mock(self):
        """GIVEN text for semantic conversion
        WHEN SymbolicAI is not available (mock)
        THEN mock response is generated"""
        bridge = SymbolicFOLBridge()
        
        text = "All humans are mortal"
        result = bridge._semantic_conversion(text)
        
        # With mock Symbol class, should get mock response
        assert result is not None
        assert isinstance(result, str)
    
    @pytest.mark.skipif(not SYMBOLIC_AI_AVAILABLE, reason="SymbolicAI not installed")
    def test_bridge_semantic_conversion_real(self):
        """GIVEN text for semantic conversion
        WHEN SymbolicAI is available
        THEN real semantic analysis is performed"""
        bridge = SymbolicFOLBridge()
        
        text = "All humans are mortal"
        result = bridge._semantic_conversion(text)
        
        assert result is not None
        assert isinstance(result, str)
    
    def test_bridge_convert_to_fol_with_cache(self):
        """GIVEN text and caching enabled
        WHEN convert_to_fol is called twice
        THEN second call uses cache"""
        bridge = SymbolicFOLBridge(enable_caching=True)
        
        text = "All humans are mortal"
        
        result1 = bridge.convert_to_fol(text)
        result2 = bridge.convert_to_fol(text)
        
        assert result1.fol_formula == result2.fol_formula
        assert len(bridge._cache) == 1
    
    def test_bridge_convert_to_fol_without_cache(self):
        """GIVEN caching disabled
        WHEN convert_to_fol is called twice
        THEN cache is not used"""
        bridge = SymbolicFOLBridge(enable_caching=False)
        
        text = "All humans are mortal"
        
        result1 = bridge.convert_to_fol(text)
        result2 = bridge.convert_to_fol(text)
        
        assert result1.fol_formula == result2.fol_formula
        assert len(bridge._cache) == 0
    
    def test_bridge_convert_to_fol_low_confidence(self):
        """GIVEN text with low confidence conversion
        WHEN confidence is below threshold
        THEN fallback is used"""
        bridge = SymbolicFOLBridge(
            confidence_threshold=0.9,
            fallback_enabled=True
        )
        
        text = "ambiguous unclear statement"
        result = bridge.convert_to_fol(text)
        
        # Should use fallback due to low confidence
        assert result.fallback_used is True or result.confidence < 0.9
    
    def test_bridge_convert_to_fol_pattern_success(self):
        """GIVEN text matching clear pattern
        WHEN convert_to_fol is called
        THEN pattern-based conversion succeeds"""
        bridge = SymbolicFOLBridge()
        
        text = "All cats are animals"
        result = bridge.convert_to_fol(text)
        
        assert result.fol_formula is not None
        assert len(result.fol_formula) > 0
        assert result.confidence > 0
        assert len(result.reasoning_steps) > 0
    
    def test_bridge_convert_to_fol_empty_text(self):
        """GIVEN empty text
        WHEN convert_to_fol is called
        THEN error is handled gracefully"""
        bridge = SymbolicFOLBridge()
        
        result = bridge.convert_to_fol("")
        
        assert result is not None
        assert result.confidence == 0.0
        assert len(result.errors) > 0
    
    def test_bridge_clear_cache(self):
        """GIVEN cached results
        WHEN clear_cache is called
        THEN cache is emptied"""
        bridge = SymbolicFOLBridge(enable_caching=True)
        
        # Add to cache
        bridge.convert_to_fol("All humans are mortal")
        assert len(bridge._cache) > 0
        
        # Clear cache
        bridge.clear_cache()
        assert len(bridge._cache) == 0
    
    def test_bridge_get_stats(self):
        """GIVEN bridge with usage
        WHEN get_stats is called
        THEN statistics are returned"""
        bridge = SymbolicFOLBridge(enable_caching=True)
        
        # Perform conversions
        bridge.convert_to_fol("All humans are mortal")
        bridge.convert_to_fol("Some students are smart")
        
        stats = bridge.get_stats()
        
        assert isinstance(stats, dict)
        assert "cache_size" in stats
        assert "symbolic_ai_available" in stats
        assert stats["cache_size"] >= 0

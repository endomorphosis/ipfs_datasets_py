"""
Tests for TDFOL Formula Generator

Tests the FormulaGenerator class for converting pattern matches
into TDFOL formulas.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_generator import (
    FormulaGenerator,
    GeneratedFormula,
    HAVE_TDFOL_CORE,
)

# Skip all tests if TDFOL core is not available
pytestmark = pytest.mark.skipif(
    not HAVE_TDFOL_CORE,
    reason="TDFOL core is not available"
)


@pytest.fixture
def generator():
    """Create formula generator instance."""
    try:
        return FormulaGenerator()
    except ImportError as e:
        pytest.skip(f"Could not initialize formula generator: {e}")


@pytest.fixture
def sample_patterns():
    """Create sample pattern matches for testing."""
    try:
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import (
            PatternMatcher,
            PatternType,
            Pattern,
            PatternMatch,
        )
    except ImportError:
        pytest.skip("Pattern matcher not available")
    
    # Sample pattern matches
    patterns = []
    
    # Universal quantification pattern
    universal_pattern = Pattern(
        name="test_universal",
        type=PatternType.UNIVERSAL_QUANTIFICATION,
        description="Test universal"
    )
    universal_match = PatternMatch(
        pattern=universal_pattern,
        span=(0, 10),
        text="All contractors must pay",
        entities={'agent': 'contractors', 'action': 'pay', 'modality': 'must'},
        confidence=0.9
    )
    patterns.append(universal_match)
    
    # Obligation pattern
    obligation_pattern = Pattern(
        name="test_obligation",
        type=PatternType.OBLIGATION,
        description="Test obligation"
    )
    obligation_match = PatternMatch(
        pattern=obligation_pattern,
        span=(0, 10),
        text="Contractor must deliver",
        entities={'agent': 'contractor', 'action': 'deliver'},
        confidence=0.85
    )
    patterns.append(obligation_match)
    
    # Permission pattern
    permission_pattern = Pattern(
        name="test_permission",
        type=PatternType.PERMISSION,
        description="Test permission"
    )
    permission_match = PatternMatch(
        pattern=permission_pattern,
        span=(0, 10),
        text="Contractor may request",
        entities={'agent': 'contractor', 'action': 'request'},
        confidence=0.8
    )
    patterns.append(permission_match)
    
    # Prohibition pattern
    prohibition_pattern = Pattern(
        name="test_prohibition",
        type=PatternType.PROHIBITION,
        description="Test prohibition"
    )
    prohibition_match = PatternMatch(
        pattern=prohibition_pattern,
        span=(0, 10),
        text="Contractor must not disclose",
        entities={'agent': 'contractor', 'action': 'disclose'},
        confidence=0.85
    )
    patterns.append(prohibition_match)
    
    # Temporal pattern
    temporal_pattern = Pattern(
        name="test_temporal",
        type=PatternType.TEMPORAL,
        description="Test temporal"
    )
    temporal_match = PatternMatch(
        pattern=temporal_pattern,
        span=(0, 10),
        text="must always comply",
        entities={'action': 'comply', 'modality': 'must'},
        confidence=0.8
    )
    patterns.append(temporal_match)
    
    # Conditional pattern
    conditional_pattern = Pattern(
        name="test_conditional",
        type=PatternType.CONDITIONAL,
        description="Test conditional"
    )
    conditional_match = PatternMatch(
        pattern=conditional_pattern,
        span=(0, 10),
        text="if payment then deliver",
        entities={},
        confidence=0.75
    )
    patterns.append(conditional_match)
    
    return patterns


class TestFormulaGenerator:
    """Test suite for Formula Generator."""
    
    def test_initialization(self):
        """Test formula generator initialization."""
        # GIVEN: TDFOL core is available
        # WHEN: Creating formula generator
        generator = FormulaGenerator()
        
        # THEN: Generator should be initialized
        assert generator is not None
        assert generator._variable_counter == 0
    
    def test_generate_from_matches(self, generator, sample_patterns):
        """Test generating formulas from pattern matches."""
        # GIVEN: Generator and sample patterns
        # WHEN: Generating formulas
        formulas = generator.generate_from_matches(sample_patterns)
        
        # THEN: Should generate formulas
        assert len(formulas) > 0
        assert all(isinstance(f, GeneratedFormula) for f in formulas)
    
    def test_universal_quantification(self, generator, sample_patterns):
        """Test universal quantification formula generation."""
        # GIVEN: Universal quantification pattern
        universal_patterns = [p for p in sample_patterns 
                             if p.pattern.type.value == 'universal_quantification']
        
        # WHEN: Generating formula
        formulas = generator.generate_from_matches(universal_patterns)
        
        # THEN: Should generate universal formula
        assert len(formulas) > 0
        formula = formulas[0]
        assert formula.formula is not None
        assert '∀' in formula.formula_string or 'forall' in formula.formula_string.lower()
        assert 'O(' in formula.formula_string or 'obligation' in formula.formula_string.lower()
    
    def test_obligation_formula(self, generator, sample_patterns):
        """Test obligation formula generation."""
        # GIVEN: Obligation pattern
        obligation_patterns = [p for p in sample_patterns 
                              if p.pattern.type.value == 'obligation']
        
        # WHEN: Generating formula
        formulas = generator.generate_from_matches(obligation_patterns)
        
        # THEN: Should generate obligation formula
        assert len(formulas) > 0
        formula = formulas[0]
        assert formula.formula is not None
        assert 'O(' in formula.formula_string or 'obligation' in formula.formula_string.lower()
    
    def test_permission_formula(self, generator, sample_patterns):
        """Test permission formula generation."""
        # GIVEN: Permission pattern
        permission_patterns = [p for p in sample_patterns 
                              if p.pattern.type.value == 'permission']
        
        # WHEN: Generating formula
        formulas = generator.generate_from_matches(permission_patterns)
        
        # THEN: Should generate permission formula
        assert len(formulas) > 0
        formula = formulas[0]
        assert formula.formula is not None
        assert 'P(' in formula.formula_string or 'permission' in formula.formula_string.lower()
    
    def test_prohibition_formula(self, generator, sample_patterns):
        """Test prohibition formula generation."""
        # GIVEN: Prohibition pattern
        prohibition_patterns = [p for p in sample_patterns 
                               if p.pattern.type.value == 'prohibition']
        
        # WHEN: Generating formula
        formulas = generator.generate_from_matches(prohibition_patterns)
        
        # THEN: Should generate prohibition formula
        assert len(formulas) > 0
        formula = formulas[0]
        assert formula.formula is not None
        assert 'F(' in formula.formula_string or 'prohibition' in formula.formula_string.lower()
    
    def test_temporal_formula(self, generator, sample_patterns):
        """Test temporal formula generation."""
        # GIVEN: Temporal pattern
        temporal_patterns = [p for p in sample_patterns 
                            if p.pattern.type.value == 'temporal']
        
        # WHEN: Generating formula
        formulas = generator.generate_from_matches(temporal_patterns)
        
        # THEN: Should generate temporal formula
        assert len(formulas) > 0
        formula = formulas[0]
        assert formula.formula is not None
        # Check for temporal operators
        has_temporal = any(op in formula.formula_string for op in ['□', '◊', 'X', 'U', 'always', 'eventually'])
        assert has_temporal
    
    def test_conditional_formula(self, generator, sample_patterns):
        """Test conditional formula generation."""
        # GIVEN: Conditional pattern
        conditional_patterns = [p for p in sample_patterns 
                               if p.pattern.type.value == 'conditional']
        
        # WHEN: Generating formula
        formulas = generator.generate_from_matches(conditional_patterns)
        
        # THEN: Should generate conditional formula
        assert len(formulas) > 0
        formula = formulas[0]
        assert formula.formula is not None
        assert '→' in formula.formula_string or '->' in formula.formula_string or 'implies' in formula.formula_string.lower()
    
    def test_confidence_propagation(self, generator, sample_patterns):
        """Test that confidence is propagated to formulas."""
        # GIVEN: Patterns with various confidences
        # WHEN: Generating formulas
        formulas = generator.generate_from_matches(sample_patterns)
        
        # THEN: Formulas should have confidence scores
        for formula in formulas:
            assert 0.0 <= formula.confidence <= 1.0
    
    def test_entity_extraction(self, generator, sample_patterns):
        """Test that entities are preserved in formulas."""
        # GIVEN: Patterns with entities
        # WHEN: Generating formulas
        formulas = generator.generate_from_matches(sample_patterns)
        
        # THEN: Entities should be in formula metadata
        for formula in formulas:
            assert isinstance(formula.entities, dict)
    
    def test_predicate_name_conversion(self, generator):
        """Test conversion of text to predicate names."""
        # GIVEN: Various text strings
        tests = [
            ("pay taxes", "PayTaxes"),
            ("deliver goods", "DeliverGoods"),
            ("comply", "Comply"),
            ("", "Predicate"),
        ]
        
        # WHEN/THEN: Converting to predicate names
        for text, expected in tests:
            result = generator._to_predicate_name(text)
            assert result == expected or result.replace(" ", "") == expected.replace(" ", "")
    
    def test_variable_generation(self, generator):
        """Test fresh variable generation."""
        # GIVEN: Generator
        # WHEN: Generating variables
        var1 = generator._fresh_variable()
        var2 = generator._fresh_variable()
        
        # THEN: Variables should be unique
        assert var1 != var2
        assert var1 == "x0"
        assert var2 == "x1"
    
    def test_variable_reset(self, generator):
        """Test variable counter reset."""
        # GIVEN: Generator with variables generated
        generator._fresh_variable()
        generator._fresh_variable()
        
        # WHEN: Resetting
        generator.reset_variables()
        
        # THEN: Counter should be reset
        var = generator._fresh_variable()
        assert var == "x0"


class TestGeneratedFormula:
    """Test GeneratedFormula dataclass."""
    
    def test_formula_creation(self):
        """Test creating a GeneratedFormula."""
        # GIVEN: Formula data
        # WHEN: Creating GeneratedFormula
        formula = GeneratedFormula(
            formula=None,
            pattern_match=None,
            confidence=0.9,
            formula_string="O(Pay(contractor, taxes))",
            entities={'agent': 'contractor', 'action': 'pay'}
        )
        
        # THEN: Formula should be created
        assert formula.confidence == 0.9
        assert formula.formula_string == "O(Pay(contractor, taxes))"
        assert formula.entities['agent'] == 'contractor'

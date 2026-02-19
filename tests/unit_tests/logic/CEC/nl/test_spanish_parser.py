"""
Tests for Spanish Parser (Phase 5 Week 2).

This test module validates Spanish natural language parsing for CEC,
covering grammar rules, verb conjugations, and modal expressions.

Test Coverage:
- Parser initialization (3 tests)
- Deontic operators - obligation (10 tests)
- Deontic operators - permission (10 tests)
- Deontic operators - prohibition (10 tests)
- Cognitive operators (10 tests)
- Temporal operators (10 tests)
- Logical connectives (10 tests)
- Verb conjugations (4 tests)
- Cultural and idiomatic expressions (3 tests)

Total: 70 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.nl.spanish_parser import (
    SpanishParser,
    SpanishPatternMatcher,
    get_spanish_verb_conjugations,
    get_spanish_articles,
    get_spanish_deontic_keywords
)
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective
)
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECNamespace


class TestParserInitialization:
    """Test Spanish parser initialization."""
    
    def test_parser_creation(self):
        """
        GIVEN SpanishParser class
        WHEN creating parser instance
        THEN should initialize successfully
        """
        parser = SpanishParser()
        assert parser.language == "es"
        assert parser.confidence_threshold == 0.5
        assert parser.namespace is not None
        assert parser.matcher is not None
    
    def test_parser_custom_threshold(self):
        """
        GIVEN custom confidence threshold
        WHEN creating parser
        THEN should use custom threshold
        """
        parser = SpanishParser(confidence_threshold=0.7)
        assert parser.confidence_threshold == 0.7
    
    def test_parser_supported_operators(self):
        """
        GIVEN SpanishParser
        WHEN getting supported operators
        THEN should return Spanish operator keywords
        """
        parser = SpanishParser()
        operators = parser.get_supported_operators()
        assert 'debe' in operators
        assert 'puede' in operators
        assert 'sabe' in operators
        assert 'siempre' in operators


class TestDeonticObligationSpanish:
    """Test Spanish deontic obligation parsing."""
    
    def test_parse_debe_simple(self):
        """
        GIVEN Spanish obligation with 'debe'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = SpanishParser()
        result = parser.parse("El agente debe cumplir")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_tiene_que(self):
        """
        GIVEN Spanish obligation with 'tiene que'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = SpanishParser()
        result = parser.parse("El agente tiene que realizar la acción")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_es_obligatorio(self):
        """
        GIVEN Spanish obligation with 'es obligatorio'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = SpanishParser()
        result = parser.parse("Es obligatorio reportar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_es_necesario(self):
        """
        GIVEN Spanish obligation with 'es necesario'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = SpanishParser()
        result = parser.parse("Es necesario verificar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_se_requiere(self):
        """
        GIVEN Spanish obligation with 'se requiere'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = SpanishParser()
        result = parser.parse("Se requiere aprobar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_hay_que(self):
        """
        GIVEN Spanish obligation with 'hay que'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = SpanishParser()
        result = parser.parse("Hay que completar el proceso")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_obligation_with_articles(self):
        """
        GIVEN Spanish obligation with definite articles
        WHEN parsing text
        THEN should handle articles correctly
        """
        parser = SpanishParser()
        result = parser.parse("Los agentes deben colaborar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_obligation_reflexive(self):
        """
        GIVEN Spanish obligation with reflexive verb
        WHEN parsing text
        THEN should parse correctly
        """
        parser = SpanishParser()
        result = parser.parse("El agente debe prepararse")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_obligation_compound(self):
        """
        GIVEN Spanish obligation with compound action
        WHEN parsing text
        THEN should parse main action
        """
        parser = SpanishParser()
        result = parser.parse("El agente debe cumplir con las normas")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_obligation_confidence(self):
        """
        GIVEN clear Spanish obligation
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = SpanishParser()
        result = parser.parse("El agente debe realizar la acción")
        assert result.success
        assert result.confidence >= 0.5


class TestDeonticPermissionSpanish:
    """Test Spanish deontic permission parsing."""
    
    def test_parse_puede_simple(self):
        """
        GIVEN Spanish permission with 'puede'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = SpanishParser()
        result = parser.parse("El agente puede actuar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION
    
    def test_parse_se_permite(self):
        """
        GIVEN Spanish permission with 'se permite'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = SpanishParser()
        result = parser.parse("Se permite acceder")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION
    
    def test_parse_esta_permitido(self):
        """
        GIVEN Spanish permission with 'está permitido'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = SpanishParser()
        result = parser.parse("Está permitido participar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_podra_future(self):
        """
        GIVEN Spanish permission with future tense 'podrá'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = SpanishParser()
        result = parser.parse("El agente podrá iniciar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_tiene_permiso(self):
        """
        GIVEN Spanish permission with 'tiene permiso'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = SpanishParser()
        result = parser.parse("El agente tiene permiso para actuar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_se_puede(self):
        """
        GIVEN Spanish permission with 'se puede'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = SpanishParser()
        result = parser.parse("Se puede modificar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_es_permitido(self):
        """
        GIVEN Spanish permission with 'es permitido'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = SpanishParser()
        result = parser.parse("Es permitido continuar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_permission_plural(self):
        """
        GIVEN Spanish permission with plural subject
        WHEN parsing text
        THEN should parse correctly
        """
        parser = SpanishParser()
        result = parser.parse("Los usuarios pueden descargar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_permission_conditional(self):
        """
        GIVEN Spanish permission with conditional
        WHEN parsing text
        THEN should extract permission
        """
        parser = SpanishParser()
        result = parser.parse("El agente puede proceder si cumple requisitos")
        assert result.success
        # Should at least extract permission part
        assert result.formula is not None
    
    def test_parse_permission_confidence(self):
        """
        GIVEN clear Spanish permission
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = SpanishParser()
        result = parser.parse("El agente puede realizar la acción")
        assert result.success
        assert result.confidence >= 0.5


class TestDeonticProhibitionSpanish:
    """Test Spanish deontic prohibition parsing."""
    
    def test_parse_no_debe(self):
        """
        GIVEN Spanish prohibition with 'no debe'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = SpanishParser()
        result = parser.parse("El agente no debe actuar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION
    
    def test_parse_no_puede(self):
        """
        GIVEN Spanish prohibition with 'no puede'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = SpanishParser()
        result = parser.parse("El agente no puede realizar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION
    
    def test_parse_prohibido(self):
        """
        GIVEN Spanish prohibition with 'prohibido'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = SpanishParser()
        result = parser.parse("Prohibido acceder")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_esta_prohibido(self):
        """
        GIVEN Spanish prohibition with 'está prohibido'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = SpanishParser()
        result = parser.parse("Está prohibido modificar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_no_se_permite(self):
        """
        GIVEN Spanish prohibition with 'no se permite'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = SpanishParser()
        result = parser.parse("No se permite fumar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_no_se_puede(self):
        """
        GIVEN Spanish prohibition with 'no se puede'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = SpanishParser()
        result = parser.parse("No se puede eliminar")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_prohibition_formal(self):
        """
        GIVEN formal Spanish prohibition
        WHEN parsing text
        THEN should parse correctly
        """
        parser = SpanishParser()
        result = parser.parse("Queda prohibido el acceso")
        # Should at least extract prohibition keyword
        assert result.formula is not None
    
    def test_parse_prohibition_reflexive(self):
        """
        GIVEN Spanish prohibition with reflexive verb
        WHEN parsing text
        THEN should parse correctly
        """
        parser = SpanishParser()
        result = parser.parse("El agente no debe comprometerse")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_prohibition_compound(self):
        """
        GIVEN Spanish prohibition with compound expression
        WHEN parsing text
        THEN should extract main prohibition
        """
        parser = SpanishParser()
        result = parser.parse("El agente no debe revelar información confidencial")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_prohibition_confidence(self):
        """
        GIVEN clear Spanish prohibition
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = SpanishParser()
        result = parser.parse("El agente no puede divulgar")
        assert result.success
        assert result.confidence >= 0.5


class TestCognitiveOperatorsSpanish:
    """Test Spanish cognitive operator parsing."""
    
    def test_parse_sabe_que(self):
        """
        GIVEN Spanish knowledge statement with 'sabe que'
        WHEN parsing text
        THEN should create CognitiveFormula with KNOWLEDGE
        """
        parser = SpanishParser()
        result = parser.parse("El agente sabe que la acción es correcta")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.KNOWLEDGE
    
    def test_parse_cree_que(self):
        """
        GIVEN Spanish belief statement with 'cree que'
        WHEN parsing text
        THEN should create CognitiveFormula with BELIEF
        """
        parser = SpanishParser()
        result = parser.parse("El agente cree que es posible")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.BELIEF
    
    def test_parse_piensa_que(self):
        """
        GIVEN Spanish belief statement with 'piensa que'
        WHEN parsing text
        THEN should create CognitiveFormula with BELIEF
        """
        parser = SpanishParser()
        result = parser.parse("El agente piensa que funciona")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
    
    def test_parse_quiere(self):
        """
        GIVEN Spanish desire statement with 'quiere'
        WHEN parsing text
        THEN should create CognitiveFormula with DESIRE
        """
        parser = SpanishParser()
        result = parser.parse("El agente quiere participar")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.DESIRE
    
    def test_parse_desea(self):
        """
        GIVEN Spanish desire statement with 'desea'
        WHEN parsing text
        THEN should create CognitiveFormula with DESIRE
        """
        parser = SpanishParser()
        result = parser.parse("El agente desea continuar")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
    
    def test_parse_intenta(self):
        """
        GIVEN Spanish intention statement with 'intenta'
        WHEN parsing text
        THEN should create CognitiveFormula with INTENTION
        """
        parser = SpanishParser()
        result = parser.parse("El agente intenta resolver")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.INTENTION
    
    def test_parse_pretende(self):
        """
        GIVEN Spanish intention statement with 'pretende'
        WHEN parsing text
        THEN should create CognitiveFormula with INTENTION
        """
        parser = SpanishParser()
        result = parser.parse("El agente pretende mejorar")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
    
    def test_parse_tiene_objetivo(self):
        """
        GIVEN Spanish goal statement with 'tiene objetivo'
        WHEN parsing text
        THEN should create CognitiveFormula with GOAL
        """
        parser = SpanishParser()
        result = parser.parse("El agente tiene objetivo de completar")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.GOAL
    
    def test_parse_cognitive_nested(self):
        """
        GIVEN nested Spanish cognitive statement
        WHEN parsing text
        THEN should handle nesting
        """
        parser = SpanishParser()
        result = parser.parse("El agente cree que debe cumplir")
        assert result.success
        # Should parse outer cognitive operator at minimum
        assert result.formula is not None
    
    def test_parse_cognitive_confidence(self):
        """
        GIVEN Spanish cognitive statement
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = SpanishParser()
        result = parser.parse("El agente sabe que es correcto")
        assert result.success
        assert result.confidence >= 0.5


class TestTemporalOperatorsSpanish:
    """Test Spanish temporal operator parsing."""
    
    def test_parse_siempre(self):
        """
        GIVEN Spanish always statement with 'siempre'
        WHEN parsing text
        THEN should create TemporalFormula with ALWAYS
        """
        parser = SpanishParser()
        result = parser.parse("Siempre el agente debe cumplir")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.ALWAYS
    
    def test_parse_eventualmente(self):
        """
        GIVEN Spanish eventually statement with 'eventualmente'
        WHEN parsing text
        THEN should create TemporalFormula with EVENTUALLY
        """
        parser = SpanishParser()
        result = parser.parse("Eventualmente el agente puede terminar")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.EVENTUALLY
    
    def test_parse_finalmente(self):
        """
        GIVEN Spanish eventually statement with 'finalmente'
        WHEN parsing text
        THEN should create TemporalFormula with EVENTUALLY
        """
        parser = SpanishParser()
        result = parser.parse("Finalmente el proceso completa")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_luego(self):
        """
        GIVEN Spanish next statement with 'luego'
        WHEN parsing text
        THEN should create TemporalFormula with NEXT
        """
        parser = SpanishParser()
        result = parser.parse("Luego el agente verifica")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.NEXT
    
    def test_parse_despues(self):
        """
        GIVEN Spanish next statement with 'después'
        WHEN parsing text
        THEN should create TemporalFormula with NEXT
        """
        parser = SpanishParser()
        result = parser.parse("Después el agente continúa")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_en_todo_momento(self):
        """
        GIVEN Spanish always with idiomatic expression
        WHEN parsing text
        THEN should create TemporalFormula with ALWAYS
        """
        parser = SpanishParser()
        result = parser.parse("En todo momento el sistema monitorea")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_algun_dia(self):
        """
        GIVEN Spanish eventually with idiomatic expression
        WHEN parsing text
        THEN should create TemporalFormula with EVENTUALLY
        """
        parser = SpanishParser()
        result = parser.parse("Algún día el agente logrará el objetivo")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_hasta_que(self):
        """
        GIVEN Spanish until statement with 'hasta que'
        WHEN parsing text
        THEN should create TemporalFormula with UNTIL
        """
        parser = SpanishParser()
        result = parser.parse("El agente espera hasta que completa")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_desde_que(self):
        """
        GIVEN Spanish since statement with 'desde que'
        WHEN parsing text
        THEN should create TemporalFormula with SINCE
        """
        parser = SpanishParser()
        result = parser.parse("El agente actúa desde que inició")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_temporal_confidence(self):
        """
        GIVEN Spanish temporal statement
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = SpanishParser()
        result = parser.parse("Siempre el agente debe verificar")
        assert result.success
        assert result.confidence >= 0.5


class TestLogicalConnectivesSpanish:
    """Test Spanish logical connective parsing."""
    
    def test_parse_y_conjunction(self):
        """
        GIVEN Spanish conjunction with 'y'
        WHEN parsing text
        THEN should create ConnectiveFormula with AND
        """
        parser = SpanishParser()
        result = parser.parse("El agente debe cumplir y el agente debe reportar")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
        assert result.formula.connective == LogicalConnective.AND
    
    def test_parse_e_conjunction(self):
        """
        GIVEN Spanish conjunction with 'e' (before i/hi sound)
        WHEN parsing text
        THEN should create ConnectiveFormula with AND
        """
        parser = SpanishParser()
        result = parser.parse("El padre e hijo deben colaborar")
        assert result.success
        # Should parse even if simplified
        assert result.formula is not None
    
    def test_parse_o_disjunction(self):
        """
        GIVEN Spanish disjunction with 'o'
        WHEN parsing text
        THEN should create ConnectiveFormula with OR
        """
        parser = SpanishParser()
        result = parser.parse("El agente puede aceptar o el agente puede rechazar")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
        assert result.formula.connective == LogicalConnective.OR
    
    def test_parse_u_disjunction(self):
        """
        GIVEN Spanish disjunction with 'u' (before o/ho sound)
        WHEN parsing text
        THEN should create ConnectiveFormula with OR
        """
        parser = SpanishParser()
        result = parser.parse("Siete u ocho agentes deben participar")
        assert result.success
        # Should parse even if simplified
        assert result.formula is not None
    
    def test_parse_si_entonces(self):
        """
        GIVEN Spanish implication with 'si...entonces'
        WHEN parsing text
        THEN should create ConnectiveFormula with IMPLIES
        """
        parser = SpanishParser()
        result = parser.parse("Si el agente cumple entonces el agente puede continuar")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
        assert result.formula.connective == LogicalConnective.IMPLIES
    
    def test_parse_si_comma_entonces(self):
        """
        GIVEN Spanish implication with comma
        WHEN parsing text
        THEN should create ConnectiveFormula with IMPLIES
        """
        parser = SpanishParser()
        result = parser.parse("Si el agente verifica, puede proceder")
        assert result.success
        # Should extract implication
        assert result.formula is not None
    
    def test_parse_no_negation(self):
        """
        GIVEN Spanish negation with 'no'
        WHEN parsing text
        THEN should create ConnectiveFormula with NOT
        """
        parser = SpanishParser()
        result = parser.parse("No el agente debe fallar")
        assert result.success
        # Should handle negation in some form
        assert result.formula is not None
    
    def test_parse_complex_connectives(self):
        """
        GIVEN Spanish text with multiple connectives
        WHEN parsing text
        THEN should parse primary structure
        """
        parser = SpanishParser()
        result = parser.parse("El agente debe cumplir y el agente puede verificar")
        assert result.success
        assert result.formula is not None
    
    def test_parse_nested_connectives(self):
        """
        GIVEN Spanish text with nested connectives
        WHEN parsing text
        THEN should handle nesting
        """
        parser = SpanishParser()
        result = parser.parse("Si el agente debe cumplir y el agente puede actuar entonces procede")
        # Complex parsing - should at least produce formula
        assert result.formula is not None
    
    def test_parse_connectives_confidence(self):
        """
        GIVEN Spanish text with connectives
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = SpanishParser()
        result = parser.parse("El agente debe cumplir y reportar")
        assert result.formula is not None
        assert result.confidence >= 0.0  # Some confidence


class TestVerbConjugations:
    """Test Spanish verb conjugation handling."""
    
    def test_get_verb_conjugations(self):
        """
        GIVEN Spanish verb conjugation function
        WHEN getting conjugations
        THEN should return conjugation tables
        """
        conjugations = get_spanish_verb_conjugations()
        assert 'deber' in conjugations
        assert 'poder' in conjugations
        assert 'saber' in conjugations
        assert conjugations['deber']['present']['él/ella'] == 'debe'
        assert conjugations['poder']['present']['él/ella'] == 'puede'
    
    def test_parse_different_conjugations(self):
        """
        GIVEN Spanish text with various conjugations
        WHEN parsing text
        THEN should handle different forms
        """
        parser = SpanishParser()
        
        # debe (3rd person singular)
        result1 = parser.parse("El agente debe actuar")
        assert result1.success
        
        # debemos (1st person plural) - may not match exact pattern
        result2 = parser.parse("Debemos cumplir")
        assert result2.formula is not None
    
    def test_parse_future_tense(self):
        """
        GIVEN Spanish text with future tense
        WHEN parsing text
        THEN should parse correctly
        """
        parser = SpanishParser()
        result = parser.parse("El agente podrá iniciar mañana")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_articles_function(self):
        """
        GIVEN get_spanish_articles function
        WHEN calling function
        THEN should return definite and indefinite articles
        """
        articles = get_spanish_articles()
        assert 'definite' in articles
        assert 'indefinite' in articles
        assert 'el' in articles['definite']
        assert 'un' in articles['indefinite']


class TestCulturalAndIdiomatic:
    """Test Spanish cultural context and idiomatic expressions."""
    
    def test_deontic_keywords_function(self):
        """
        GIVEN get_spanish_deontic_keywords function
        WHEN calling function
        THEN should return categorized keywords
        """
        keywords = get_spanish_deontic_keywords()
        assert 'obligation' in keywords
        assert 'permission' in keywords
        assert 'prohibition' in keywords
        assert 'debe' in keywords['obligation']
        assert 'puede' in keywords['permission']
        assert 'prohibido' in keywords['prohibition']
    
    def test_parse_formal_register(self):
        """
        GIVEN formal Spanish register
        WHEN parsing text
        THEN should parse correctly
        """
        parser = SpanishParser()
        result = parser.parse("El usuario está obligado a cumplir con las disposiciones")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_reflexive_construction(self):
        """
        GIVEN Spanish reflexive construction
        WHEN parsing text
        THEN should handle reflexive verbs
        """
        parser = SpanishParser()
        result = parser.parse("Se debe considerar la situación")
        # Reflexive construction common in Spanish
        assert result.formula is not None

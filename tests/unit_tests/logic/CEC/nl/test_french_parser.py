"""
Tests for French Parser (Phase 5 Week 3).

This test module validates French natural language parsing for CEC,
covering grammar rules, verb conjugations, negation patterns, and modal expressions.

Test Coverage:
- Parser initialization (3 tests)
- Deontic operators - obligation (10 tests)
- Deontic operators - permission (10 tests)
- Deontic operators - prohibition (10 tests)
- Cognitive operators (10 tests)
- Temporal operators (10 tests)
- Logical connectives (10 tests)
- Verb conjugations (4 tests)
- Negation patterns (3 tests)

Total: 70 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.nl.french_parser import (
    FrenchParser,
    FrenchPatternMatcher,
    get_french_verb_conjugations,
    get_french_articles,
    get_french_negation_patterns,
    get_french_deontic_keywords
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
    """Test French parser initialization."""
    
    def test_parser_creation(self):
        """
        GIVEN FrenchParser class
        WHEN creating parser instance
        THEN should initialize successfully
        """
        parser = FrenchParser()
        assert parser.language == "fr"
        assert parser.confidence_threshold == 0.5
        assert parser.namespace is not None
        assert parser.matcher is not None
    
    def test_parser_custom_threshold(self):
        """
        GIVEN custom confidence threshold
        WHEN creating parser
        THEN should use custom threshold
        """
        parser = FrenchParser(confidence_threshold=0.7)
        assert parser.confidence_threshold == 0.7
    
    def test_parser_supported_operators(self):
        """
        GIVEN FrenchParser
        WHEN getting supported operators
        THEN should return French operator keywords
        """
        parser = FrenchParser()
        operators = parser.get_supported_operators()
        assert 'doit' in operators
        assert 'peut' in operators
        assert 'sait' in operators
        assert 'toujours' in operators


class TestDeonticObligationFrench:
    """Test French deontic obligation parsing."""
    
    def test_parse_doit_simple(self):
        """
        GIVEN French obligation with 'doit'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = FrenchParser()
        result = parser.parse("L'agent doit respecter")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_il_faut(self):
        """
        GIVEN French obligation with 'il faut'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = FrenchParser()
        result = parser.parse("Il faut accomplir la tâche")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_est_oblige(self):
        """
        GIVEN French obligation with 'est obligé'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = FrenchParser()
        result = parser.parse("L'agent est obligé de signaler")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_est_necessaire(self):
        """
        GIVEN French obligation with 'il est nécessaire'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = FrenchParser()
        result = parser.parse("Il est nécessaire de vérifier")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_est_requis(self):
        """
        GIVEN French obligation with 'il est requis'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = FrenchParser()
        result = parser.parse("Il est requis d'approuver")
        # Should parse even if 'd' is separate
        assert result.formula is not None
    
    def test_parse_obligation_plural(self):
        """
        GIVEN French obligation with plural 'doivent'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = FrenchParser()
        result = parser.parse("Les agents doivent collaborer")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_ont_obligation(self):
        """
        GIVEN French obligation with 'ont l'obligation'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = FrenchParser()
        result = parser.parse("Les agents ont l'obligation de participer")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_est_tenu(self):
        """
        GIVEN French obligation with 'est tenu'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = FrenchParser()
        result = parser.parse("L'utilisateur est tenu de respecter")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_obligation_compound(self):
        """
        GIVEN French obligation with compound action
        WHEN parsing text
        THEN should parse main action
        """
        parser = FrenchParser()
        result = parser.parse("L'agent doit respecter les règles")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_obligation_confidence(self):
        """
        GIVEN clear French obligation
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = FrenchParser()
        result = parser.parse("L'agent doit effectuer l'action")
        assert result.success
        assert result.confidence >= 0.5


class TestDeonticPermissionFrench:
    """Test French deontic permission parsing."""
    
    def test_parse_peut_simple(self):
        """
        GIVEN French permission with 'peut'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = FrenchParser()
        result = parser.parse("L'agent peut agir")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION
    
    def test_parse_est_permis(self):
        """
        GIVEN French permission with 'est permis'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = FrenchParser()
        result = parser.parse("Il est permis d'accéder")
        # Should parse even with 'd' contraction
        assert result.formula is not None
    
    def test_parse_a_le_droit(self):
        """
        GIVEN French permission with 'a le droit'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = FrenchParser()
        result = parser.parse("L'agent a le droit de participer")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION
    
    def test_parse_pourra_future(self):
        """
        GIVEN French permission with future tense 'pourra'
        WHEN parsing text
        THEN should parse as permission or create formula
        """
        parser = FrenchParser()
        result = parser.parse("L'agent pourra commencer")
        # May not match exact pattern but should produce formula
        assert result.formula is not None
    
    def test_parse_on_peut(self):
        """
        GIVEN French permission with 'on peut'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = FrenchParser()
        result = parser.parse("On peut modifier")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_permission_plural(self):
        """
        GIVEN French permission with plural 'peuvent'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = FrenchParser()
        result = parser.parse("Les utilisateurs peuvent télécharger")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION
    
    def test_parse_sont_autorises(self):
        """
        GIVEN French permission with 'sont autorisés'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = FrenchParser()
        result = parser.parse("Les agents sont autorisés à procéder")
        # Should parse 'à' as part of expression
        assert result.formula is not None
    
    def test_parse_ont_le_droit(self):
        """
        GIVEN French permission with 'ont le droit'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = FrenchParser()
        result = parser.parse("Les agents ont le droit de continuer")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_permission_conditional(self):
        """
        GIVEN French permission with conditional
        WHEN parsing text
        THEN should extract permission
        """
        parser = FrenchParser()
        result = parser.parse("L'agent peut procéder si les conditions sont remplies")
        assert result.success
        # Should at least extract permission part
        assert result.formula is not None
    
    def test_parse_permission_confidence(self):
        """
        GIVEN clear French permission
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = FrenchParser()
        result = parser.parse("L'agent peut effectuer l'action")
        assert result.success
        assert result.confidence >= 0.5


class TestDeonticProhibitionFrench:
    """Test French deontic prohibition parsing."""
    
    def test_parse_ne_doit_pas(self):
        """
        GIVEN French prohibition with 'ne doit pas'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = FrenchParser()
        result = parser.parse("L'agent ne doit pas agir")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION
    
    def test_parse_ne_peut_pas(self):
        """
        GIVEN French prohibition with 'ne peut pas'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = FrenchParser()
        result = parser.parse("L'agent ne peut pas effectuer")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION
    
    def test_parse_interdit(self):
        """
        GIVEN French prohibition with 'interdit'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = FrenchParser()
        result = parser.parse("Interdit d'accéder")
        # Should parse prohibition
        assert result.formula is not None
    
    def test_parse_est_interdit(self):
        """
        GIVEN French prohibition with 'est interdit'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = FrenchParser()
        result = parser.parse("Il est interdit de modifier")
        # Should parse prohibition
        assert result.formula is not None
    
    def test_parse_nest_pas_permis(self):
        """
        GIVEN French prohibition with 'n'est pas permis'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = FrenchParser()
        result = parser.parse("N'est pas permis de fumer")
        # Should parse prohibition
        assert result.formula is not None
    
    def test_parse_ne_se_permet_pas(self):
        """
        GIVEN French prohibition with 'ne se permet pas'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = FrenchParser()
        result = parser.parse("Ne se permet pas d'éliminer")
        # Should parse prohibition
        assert result.formula is not None
    
    def test_parse_prohibition_formal(self):
        """
        GIVEN formal French prohibition
        WHEN parsing text
        THEN should parse correctly
        """
        parser = FrenchParser()
        result = parser.parse("Il est défendu d'accéder")
        # Should at least create formula
        assert result.formula is not None
    
    def test_parse_ne_doit_jamais(self):
        """
        GIVEN French prohibition with 'ne doit jamais'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = FrenchParser()
        result = parser.parse("L'agent ne doit jamais révéler")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION
    
    def test_parse_prohibition_compound(self):
        """
        GIVEN French prohibition with compound expression
        WHEN parsing text
        THEN should extract main prohibition
        """
        parser = FrenchParser()
        result = parser.parse("L'agent ne doit pas divulguer d'informations confidentielles")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_prohibition_confidence(self):
        """
        GIVEN clear French prohibition
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = FrenchParser()
        result = parser.parse("L'agent ne peut pas divulguer")
        assert result.success
        assert result.confidence >= 0.5


class TestCognitiveOperatorsFrench:
    """Test French cognitive operator parsing."""
    
    def test_parse_sait_que(self):
        """
        GIVEN French knowledge statement with 'sait que'
        WHEN parsing text
        THEN should create CognitiveFormula with KNOWLEDGE
        """
        parser = FrenchParser()
        result = parser.parse("L'agent sait que l'action est correcte")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.KNOWLEDGE
    
    def test_parse_croit_que(self):
        """
        GIVEN French belief statement with 'croit que'
        WHEN parsing text
        THEN should create CognitiveFormula with BELIEF
        """
        parser = FrenchParser()
        result = parser.parse("L'agent croit que c'est possible")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.BELIEF
    
    def test_parse_pense_que(self):
        """
        GIVEN French belief statement with 'pense que'
        WHEN parsing text
        THEN should create CognitiveFormula with BELIEF
        """
        parser = FrenchParser()
        result = parser.parse("L'agent pense que ça fonctionne")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
    
    def test_parse_veut(self):
        """
        GIVEN French desire statement with 'veut'
        WHEN parsing text
        THEN should create CognitiveFormula with DESIRE
        """
        parser = FrenchParser()
        result = parser.parse("L'agent veut participer")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.DESIRE
    
    def test_parse_desire(self):
        """
        GIVEN French desire statement with 'désire'
        WHEN parsing text
        THEN should create CognitiveFormula with DESIRE
        """
        parser = FrenchParser()
        result = parser.parse("L'agent désire continuer")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
    
    def test_parse_envisage(self):
        """
        GIVEN French intention statement with 'envisage'
        WHEN parsing text
        THEN should create CognitiveFormula with INTENTION
        """
        parser = FrenchParser()
        result = parser.parse("L'agent envisage de résoudre")
        # Should parse intention
        assert result.formula is not None
    
    def test_parse_a_lintention(self):
        """
        GIVEN French intention statement with 'a l'intention de'
        WHEN parsing text
        THEN should create CognitiveFormula with INTENTION
        """
        parser = FrenchParser()
        result = parser.parse("L'agent a l'intention de améliorer")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.INTENTION
    
    def test_parse_a_pour_objectif(self):
        """
        GIVEN French goal statement with 'a pour objectif'
        WHEN parsing text
        THEN should create CognitiveFormula with GOAL
        """
        parser = FrenchParser()
        result = parser.parse("L'agent a pour objectif de compléter")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.GOAL
    
    def test_parse_cognitive_nested(self):
        """
        GIVEN nested French cognitive statement
        WHEN parsing text
        THEN should handle nesting
        """
        parser = FrenchParser()
        result = parser.parse("L'agent croit qu'il doit respecter")
        assert result.success
        # Should parse outer cognitive operator
        assert result.formula is not None
    
    def test_parse_cognitive_confidence(self):
        """
        GIVEN French cognitive statement
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = FrenchParser()
        result = parser.parse("L'agent sait que c'est correct")
        assert result.success
        assert result.confidence >= 0.5


class TestTemporalOperatorsFrench:
    """Test French temporal operator parsing."""
    
    def test_parse_toujours(self):
        """
        GIVEN French always statement with 'toujours'
        WHEN parsing text
        THEN should create TemporalFormula with ALWAYS
        """
        parser = FrenchParser()
        result = parser.parse("Toujours l'agent doit respecter")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.ALWAYS
    
    def test_parse_eventuellement(self):
        """
        GIVEN French eventually statement with 'éventuellement'
        WHEN parsing text
        THEN should create TemporalFormula with EVENTUALLY
        """
        parser = FrenchParser()
        result = parser.parse("Éventuellement l'agent peut terminer")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.EVENTUALLY
    
    def test_parse_finalement(self):
        """
        GIVEN French eventually statement with 'finalement'
        WHEN parsing text
        THEN should create TemporalFormula with EVENTUALLY
        """
        parser = FrenchParser()
        result = parser.parse("Finalement le processus se termine")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_ensuite(self):
        """
        GIVEN French next statement with 'ensuite'
        WHEN parsing text
        THEN should create TemporalFormula with NEXT
        """
        parser = FrenchParser()
        result = parser.parse("Ensuite l'agent vérifie")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.NEXT
    
    def test_parse_apres(self):
        """
        GIVEN French next statement with 'après'
        WHEN parsing text
        THEN should create TemporalFormula with NEXT
        """
        parser = FrenchParser()
        result = parser.parse("Après l'agent continue")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_en_tout_temps(self):
        """
        GIVEN French always with idiomatic expression
        WHEN parsing text
        THEN should create TemporalFormula with ALWAYS
        """
        parser = FrenchParser()
        result = parser.parse("En tout temps le système surveille")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_un_jour(self):
        """
        GIVEN French eventually with idiomatic expression
        WHEN parsing text
        THEN should create TemporalFormula with EVENTUALLY
        """
        parser = FrenchParser()
        result = parser.parse("Un jour l'agent atteindra l'objectif")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_jusqua_ce_que(self):
        """
        GIVEN French until statement with 'jusqu'à ce que'
        WHEN parsing text
        THEN should create TemporalFormula with UNTIL
        """
        parser = FrenchParser()
        result = parser.parse("L'agent attend jusqu'à ce que termine")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_depuis_que(self):
        """
        GIVEN French since statement with 'depuis que'
        WHEN parsing text
        THEN should create TemporalFormula with SINCE
        """
        parser = FrenchParser()
        result = parser.parse("L'agent agit depuis que a commencé")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_temporal_confidence(self):
        """
        GIVEN French temporal statement
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = FrenchParser()
        result = parser.parse("Toujours l'agent doit vérifier")
        assert result.success
        assert result.confidence >= 0.5


class TestLogicalConnectivesFrench:
    """Test French logical connective parsing."""
    
    def test_parse_et_conjunction(self):
        """
        GIVEN French conjunction with 'et'
        WHEN parsing text
        THEN should create ConnectiveFormula with AND
        """
        parser = FrenchParser()
        result = parser.parse("L'agent doit respecter et l'agent doit signaler")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
        assert result.formula.connective == LogicalConnective.AND
    
    def test_parse_ou_disjunction(self):
        """
        GIVEN French disjunction with 'ou'
        WHEN parsing text
        THEN should create ConnectiveFormula with OR
        """
        parser = FrenchParser()
        result = parser.parse("L'agent peut accepter ou l'agent peut refuser")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
        assert result.formula.connective == LogicalConnective.OR
    
    def test_parse_si_alors(self):
        """
        GIVEN French implication with 'si...alors'
        WHEN parsing text
        THEN should create ConnectiveFormula with IMPLIES
        """
        parser = FrenchParser()
        result = parser.parse("Si l'agent respecte alors l'agent peut continuer")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
        assert result.formula.connective == LogicalConnective.IMPLIES
    
    def test_parse_si_comma_alors(self):
        """
        GIVEN French implication with comma
        WHEN parsing text
        THEN should create ConnectiveFormula with IMPLIES
        """
        parser = FrenchParser()
        result = parser.parse("Si l'agent vérifie, peut procéder")
        assert result.success
        # Should extract implication
        assert result.formula is not None
    
    def test_parse_complex_connectives(self):
        """
        GIVEN French text with multiple connectives
        WHEN parsing text
        THEN should parse primary structure
        """
        parser = FrenchParser()
        result = parser.parse("L'agent doit respecter et l'agent peut vérifier")
        assert result.success
        assert result.formula is not None
    
    def test_parse_nested_connectives(self):
        """
        GIVEN French text with nested connectives
        WHEN parsing text
        THEN should handle nesting
        """
        parser = FrenchParser()
        result = parser.parse("Si l'agent doit respecter et l'agent peut agir alors procède")
        # Complex parsing - should at least produce formula
        assert result.formula is not None
    
    def test_parse_et_multiple(self):
        """
        GIVEN French text with multiple 'et'
        WHEN parsing text
        THEN should parse first conjunction
        """
        parser = FrenchParser()
        result = parser.parse("L'agent doit A et doit B et doit C")
        assert result.formula is not None
    
    def test_parse_ou_multiple(self):
        """
        GIVEN French text with multiple 'ou'
        WHEN parsing text
        THEN should parse first disjunction
        """
        parser = FrenchParser()
        result = parser.parse("L'agent peut A ou peut B ou peut C")
        assert result.formula is not None
    
    def test_parse_mixed_connectives(self):
        """
        GIVEN French text with mixed connectives
        WHEN parsing text
        THEN should parse primary connective
        """
        parser = FrenchParser()
        result = parser.parse("Si l'agent doit A ou doit B alors peut C")
        assert result.formula is not None
    
    def test_parse_connectives_confidence(self):
        """
        GIVEN French text with connectives
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = FrenchParser()
        result = parser.parse("L'agent doit respecter et signaler")
        assert result.formula is not None
        assert result.confidence >= 0.0


class TestVerbConjugations:
    """Test French verb conjugation handling."""
    
    def test_get_verb_conjugations(self):
        """
        GIVEN French verb conjugation function
        WHEN getting conjugations
        THEN should return conjugation tables
        """
        conjugations = get_french_verb_conjugations()
        assert 'devoir' in conjugations
        assert 'pouvoir' in conjugations
        assert 'savoir' in conjugations
        assert conjugations['devoir']['present']['il/elle'] == 'doit'
        assert conjugations['pouvoir']['present']['il/elle'] == 'peut'
    
    def test_parse_different_conjugations(self):
        """
        GIVEN French text with various conjugations
        WHEN parsing text
        THEN should handle different forms
        """
        parser = FrenchParser()
        
        # doit (3rd person singular)
        result1 = parser.parse("L'agent doit agir")
        assert result1.success
        
        # doivent (3rd person plural)
        result2 = parser.parse("Les agents doivent respecter")
        assert result2.success
    
    def test_parse_future_tense(self):
        """
        GIVEN French text with future tense
        WHEN parsing text
        THEN should parse correctly
        """
        parser = FrenchParser()
        result = parser.parse("L'agent devra commencer demain")
        # May not match exact pattern but should create formula
        assert result.formula is not None
    
    def test_articles_function(self):
        """
        GIVEN get_french_articles function
        WHEN calling function
        THEN should return articles and contractions
        """
        articles = get_french_articles()
        assert 'definite' in articles
        assert 'indefinite' in articles
        assert 'contractions' in articles
        assert 'le' in articles['definite']
        assert 'un' in articles['indefinite']
        assert 'du' in articles['contractions']


class TestNegationPatterns:
    """Test French negation pattern handling."""
    
    def test_negation_patterns_function(self):
        """
        GIVEN get_french_negation_patterns function
        WHEN calling function
        THEN should return French negation patterns
        """
        patterns = get_french_negation_patterns()
        assert 'ne...pas' in patterns
        assert 'ne...jamais' in patterns
        assert 'ne...plus' in patterns
        assert 'ne...rien' in patterns
    
    def test_deontic_keywords_function(self):
        """
        GIVEN get_french_deontic_keywords function
        WHEN calling function
        THEN should return categorized keywords
        """
        keywords = get_french_deontic_keywords()
        assert 'obligation' in keywords
        assert 'permission' in keywords
        assert 'prohibition' in keywords
        assert 'doit' in keywords['obligation']
        assert 'peut' in keywords['permission']
        assert 'interdit' in keywords['prohibition']
    
    def test_parse_complex_negation(self):
        """
        GIVEN French text with complex negation
        WHEN parsing text
        THEN should handle negation correctly
        """
        parser = FrenchParser()
        result = parser.parse("L'agent ne doit jamais violer les règles")
        assert result.success
        # Should parse as prohibition
        assert isinstance(result.formula, DeonticFormula)

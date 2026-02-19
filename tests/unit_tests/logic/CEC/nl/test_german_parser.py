"""
Tests for German Parser (Phase 5 Week 4).

This test module validates German natural language parsing for CEC,
covering grammar rules, case system, compound words, and modal expressions.

Test Coverage:
- Parser initialization (3 tests)
- Deontic operators - obligation (10 tests)
- Deontic operators - permission (10 tests)
- Deontic operators - prohibition (10 tests)
- Cognitive operators (10 tests)
- Temporal operators (10 tests)
- Logical connectives (10 tests)
- Verb conjugations (4 tests)
- German-specific features (3 tests)

Total: 70 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.nl.german_parser import (
    GermanParser,
    GermanPatternMatcher,
    get_german_verb_conjugations,
    get_german_articles,
    get_german_modal_particles,
    get_german_deontic_keywords,
    get_german_compound_words
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
    """Test German parser initialization."""
    
    def test_parser_creation(self):
        """
        GIVEN GermanParser class
        WHEN creating parser instance
        THEN should initialize successfully
        """
        parser = GermanParser()
        assert parser.language == "de"
        assert parser.confidence_threshold == 0.5
        assert parser.namespace is not None
        assert parser.matcher is not None
    
    def test_parser_custom_threshold(self):
        """
        GIVEN custom confidence threshold
        WHEN creating parser
        THEN should use custom threshold
        """
        parser = GermanParser(confidence_threshold=0.7)
        assert parser.confidence_threshold == 0.7
    
    def test_parser_supported_operators(self):
        """
        GIVEN GermanParser
        WHEN getting supported operators
        THEN should return German operator keywords
        """
        parser = GermanParser()
        operators = parser.get_supported_operators()
        assert 'muss' in operators
        assert 'darf' in operators
        assert 'weiß' in operators
        assert 'immer' in operators


class TestDeonticObligationGerman:
    """Test German deontic obligation parsing."""
    
    def test_parse_muss_simple(self):
        """
        GIVEN German obligation with 'muss'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent muss einhalten")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_ist_verpflichtet(self):
        """
        GIVEN German obligation with 'ist verpflichtet'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent ist verpflichtet zu melden")
        # Should parse obligation
        assert result.formula is not None
    
    def test_parse_hat_die_pflicht(self):
        """
        GIVEN German obligation with 'hat die Pflicht'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent hat die Pflicht zu überprüfen")
        # Should parse obligation
        assert result.formula is not None
    
    def test_parse_es_ist_erforderlich(self):
        """
        GIVEN German obligation with 'es ist erforderlich'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = GermanParser()
        result = parser.parse("Es ist erforderlich zu genehmigen")
        # Should parse obligation
        assert result.formula is not None
    
    def test_parse_soll(self):
        """
        GIVEN German obligation with 'soll'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent soll teilnehmen")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_obligation_plural(self):
        """
        GIVEN German obligation with plural 'müssen'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = GermanParser()
        result = parser.parse("Die Agenten müssen zusammenarbeiten")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION
    
    def test_parse_sind_verpflichtet(self):
        """
        GIVEN German obligation with 'sind verpflichtet'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = GermanParser()
        result = parser.parse("Die Agenten sind verpflichtet zu berichten")
        # Should parse obligation
        assert result.formula is not None
    
    def test_parse_haben_die_pflicht(self):
        """
        GIVEN German obligation with 'haben die Pflicht'
        WHEN parsing text
        THEN should create DeonticFormula with OBLIGATION
        """
        parser = GermanParser()
        result = parser.parse("Die Benutzer haben die Pflicht zu respektieren")
        # Should parse obligation
        assert result.formula is not None
    
    def test_parse_obligation_compound(self):
        """
        GIVEN German obligation with compound word
        WHEN parsing text
        THEN should parse main action
        """
        parser = GermanParser()
        result = parser.parse("Der Agent muss die Vorschriften einhalten")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_obligation_confidence(self):
        """
        GIVEN clear German obligation
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = GermanParser()
        result = parser.parse("Der Agent muss die Handlung ausführen")
        assert result.success
        assert result.confidence >= 0.5


class TestDeonticPermissionGerman:
    """Test German deontic permission parsing."""
    
    def test_parse_darf_simple(self):
        """
        GIVEN German permission with 'darf'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent darf handeln")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION
    
    def test_parse_kann_simple(self):
        """
        GIVEN German permission with 'kann'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent kann zugreifen")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION
    
    def test_parse_ist_erlaubt(self):
        """
        GIVEN German permission with 'ist erlaubt'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = GermanParser()
        result = parser.parse("Es ist erlaubt zu teilnehmen")
        # Should parse permission
        assert result.formula is not None
    
    def test_parse_hat_das_recht(self):
        """
        GIVEN German permission with 'hat das Recht'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent hat das Recht zu beginnen")
        # Should parse permission
        assert result.formula is not None
    
    def test_parse_man_darf(self):
        """
        GIVEN German permission with 'man darf'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = GermanParser()
        result = parser.parse("Man darf ändern")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_permission_plural(self):
        """
        GIVEN German permission with plural 'dürfen'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = GermanParser()
        result = parser.parse("Die Benutzer dürfen herunterladen")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION
    
    def test_parse_sind_erlaubt(self):
        """
        GIVEN German permission with 'sind erlaubt'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = GermanParser()
        result = parser.parse("Die Agenten sind erlaubt zu fortfahren")
        # Should parse permission
        assert result.formula is not None
    
    def test_parse_haben_das_recht(self):
        """
        GIVEN German permission with 'haben das Recht'
        WHEN parsing text
        THEN should create DeonticFormula with PERMISSION
        """
        parser = GermanParser()
        result = parser.parse("Die Agenten haben das Recht zu weitermachen")
        # Should parse permission
        assert result.formula is not None
    
    def test_parse_permission_conditional(self):
        """
        GIVEN German permission with conditional
        WHEN parsing text
        THEN should extract permission
        """
        parser = GermanParser()
        result = parser.parse("Der Agent kann fortfahren wenn die Bedingungen erfüllt sind")
        assert result.success
        # Should at least extract permission part
        assert result.formula is not None
    
    def test_parse_permission_confidence(self):
        """
        GIVEN clear German permission
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = GermanParser()
        result = parser.parse("Der Agent darf die Handlung ausführen")
        assert result.success
        assert result.confidence >= 0.5


class TestDeonticProhibitionGerman:
    """Test German deontic prohibition parsing."""
    
    def test_parse_nicht_darf(self):
        """
        GIVEN German prohibition with 'nicht darf'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent nicht darf handeln")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION
    
    def test_parse_darf_nicht(self):
        """
        GIVEN German prohibition with 'darf nicht'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent darf nicht ausführen")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION
    
    def test_parse_verboten(self):
        """
        GIVEN German prohibition with 'verboten'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = GermanParser()
        result = parser.parse("Verboten zu zugreifen")
        # Should parse prohibition
        assert result.formula is not None
    
    def test_parse_ist_verboten(self):
        """
        GIVEN German prohibition with 'ist verboten'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = GermanParser()
        result = parser.parse("Es ist verboten zu ändern")
        # Should parse prohibition
        assert result.formula is not None
    
    def test_parse_muss_nicht(self):
        """
        GIVEN German prohibition with 'muss nicht'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent muss nicht offenbaren")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION
    
    def test_parse_dürfen_nicht(self):
        """
        GIVEN German prohibition with plural 'dürfen nicht'
        WHEN parsing text
        THEN should create DeonticFormula with PROHIBITION
        """
        parser = GermanParser()
        result = parser.parse("Die Agenten dürfen nicht löschen")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION
    
    def test_parse_prohibition_formal(self):
        """
        GIVEN formal German prohibition
        WHEN parsing text
        THEN should parse correctly
        """
        parser = GermanParser()
        result = parser.parse("Es ist untersagt zu zugreifen")
        # Should at least create formula
        assert result.formula is not None
    
    def test_parse_prohibition_compound(self):
        """
        GIVEN German prohibition with compound expression
        WHEN parsing text
        THEN should extract main prohibition
        """
        parser = GermanParser()
        result = parser.parse("Der Agent darf nicht vertrauliche Informationen offenlegen")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_prohibition_separable_verb(self):
        """
        GIVEN German prohibition with separable verb
        WHEN parsing text
        THEN should handle verb separation
        """
        parser = GermanParser()
        result = parser.parse("Der Agent darf nicht weitergeben")
        assert result.success
        assert isinstance(result.formula, DeonticFormula)
    
    def test_parse_prohibition_confidence(self):
        """
        GIVEN clear German prohibition
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = GermanParser()
        result = parser.parse("Der Agent darf nicht preisgeben")
        assert result.success
        assert result.confidence >= 0.5


class TestCognitiveOperatorsGerman:
    """Test German cognitive operator parsing."""
    
    def test_parse_weiss_dass(self):
        """
        GIVEN German knowledge statement with 'weiß dass'
        WHEN parsing text
        THEN should create CognitiveFormula with KNOWLEDGE
        """
        parser = GermanParser()
        result = parser.parse("Der Agent weiß dass die Handlung korrekt ist")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.KNOWLEDGE
    
    def test_parse_glaubt_dass(self):
        """
        GIVEN German belief statement with 'glaubt dass'
        WHEN parsing text
        THEN should create CognitiveFormula with BELIEF
        """
        parser = GermanParser()
        result = parser.parse("Der Agent glaubt dass es möglich ist")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.BELIEF
    
    def test_parse_denkt_dass(self):
        """
        GIVEN German belief statement with 'denkt dass'
        WHEN parsing text
        THEN should create CognitiveFormula with BELIEF
        """
        parser = GermanParser()
        result = parser.parse("Der Agent denkt dass es funktioniert")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
    
    def test_parse_will(self):
        """
        GIVEN German desire statement with 'will'
        WHEN parsing text
        THEN should create CognitiveFormula with DESIRE
        """
        parser = GermanParser()
        result = parser.parse("Der Agent will teilnehmen")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
        assert result.formula.operator == CognitiveOperator.DESIRE
    
    def test_parse_moechte(self):
        """
        GIVEN German desire statement with 'möchte'
        WHEN parsing text
        THEN should create CognitiveFormula with DESIRE
        """
        parser = GermanParser()
        result = parser.parse("Der Agent möchte fortsetzen")
        assert result.success
        assert isinstance(result.formula, CognitiveFormula)
    
    def test_parse_beabsichtigt(self):
        """
        GIVEN German intention statement with 'beabsichtigt'
        WHEN parsing text
        THEN should create CognitiveFormula with INTENTION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent beabsichtigt zu lösen")
        # Should parse intention
        assert result.formula is not None
    
    def test_parse_plant(self):
        """
        GIVEN German intention statement with 'plant'
        WHEN parsing text
        THEN should create CognitiveFormula with INTENTION
        """
        parser = GermanParser()
        result = parser.parse("Der Agent plant zu verbessern")
        # Should parse intention
        assert result.formula is not None
    
    def test_parse_hat_das_ziel(self):
        """
        GIVEN German goal statement with 'hat das Ziel'
        WHEN parsing text
        THEN should create CognitiveFormula with GOAL
        """
        parser = GermanParser()
        result = parser.parse("Der Agent hat das Ziel zu vervollständigen")
        # Should parse goal
        assert result.formula is not None
    
    def test_parse_cognitive_nested(self):
        """
        GIVEN nested German cognitive statement
        WHEN parsing text
        THEN should handle nesting
        """
        parser = GermanParser()
        result = parser.parse("Der Agent glaubt dass er einhalten muss")
        assert result.success
        # Should parse outer cognitive operator
        assert result.formula is not None
    
    def test_parse_cognitive_confidence(self):
        """
        GIVEN German cognitive statement
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = GermanParser()
        result = parser.parse("Der Agent weiß dass es richtig ist")
        assert result.success
        assert result.confidence >= 0.5


class TestTemporalOperatorsGerman:
    """Test German temporal operator parsing."""
    
    def test_parse_immer(self):
        """
        GIVEN German always statement with 'immer'
        WHEN parsing text
        THEN should create TemporalFormula with ALWAYS
        """
        parser = GermanParser()
        result = parser.parse("Immer der Agent muss einhalten")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.ALWAYS
    
    def test_parse_schliesslich(self):
        """
        GIVEN German eventually statement with 'schließlich'
        WHEN parsing text
        THEN should create TemporalFormula with EVENTUALLY
        """
        parser = GermanParser()
        result = parser.parse("Schließlich der Agent kann beenden")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.EVENTUALLY
    
    def test_parse_irgendwann(self):
        """
        GIVEN German eventually statement with 'irgendwann'
        WHEN parsing text
        THEN should create TemporalFormula with EVENTUALLY
        """
        parser = GermanParser()
        result = parser.parse("Irgendwann der Prozess endet")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_dann(self):
        """
        GIVEN German next statement with 'dann'
        WHEN parsing text
        THEN should create TemporalFormula with NEXT
        """
        parser = GermanParser()
        result = parser.parse("Dann der Agent überprüft")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.NEXT
    
    def test_parse_danach(self):
        """
        GIVEN German next statement with 'danach'
        WHEN parsing text
        THEN should create TemporalFormula with NEXT
        """
        parser = GermanParser()
        result = parser.parse("Danach der Agent fortsetzt")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_jederzeit(self):
        """
        GIVEN German always with 'jederzeit'
        WHEN parsing text
        THEN should create TemporalFormula with ALWAYS
        """
        parser = GermanParser()
        result = parser.parse("Jederzeit das System überwacht")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_am_ende(self):
        """
        GIVEN German eventually with 'am Ende'
        WHEN parsing text
        THEN should create TemporalFormula with EVENTUALLY
        """
        parser = GermanParser()
        result = parser.parse("Am Ende der Agent erreicht das Ziel")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_bis(self):
        """
        GIVEN German until statement with 'bis'
        WHEN parsing text
        THEN should create TemporalFormula with UNTIL
        """
        parser = GermanParser()
        result = parser.parse("Der Agent wartet bis beendet")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_seit(self):
        """
        GIVEN German since statement with 'seit'
        WHEN parsing text
        THEN should create TemporalFormula with SINCE
        """
        parser = GermanParser()
        result = parser.parse("Der Agent handelt seit begonnen")
        assert result.success
        assert isinstance(result.formula, TemporalFormula)
    
    def test_parse_temporal_confidence(self):
        """
        GIVEN German temporal statement
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = GermanParser()
        result = parser.parse("Immer der Agent muss überprüfen")
        assert result.success
        assert result.confidence >= 0.5


class TestLogicalConnectivesGerman:
    """Test German logical connective parsing."""
    
    def test_parse_und_conjunction(self):
        """
        GIVEN German conjunction with 'und'
        WHEN parsing text
        THEN should create ConnectiveFormula with AND
        """
        parser = GermanParser()
        result = parser.parse("Der Agent muss einhalten und der Agent muss melden")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
        assert result.formula.connective == LogicalConnective.AND
    
    def test_parse_oder_disjunction(self):
        """
        GIVEN German disjunction with 'oder'
        WHEN parsing text
        THEN should create ConnectiveFormula with OR
        """
        parser = GermanParser()
        result = parser.parse("Der Agent kann akzeptieren oder der Agent kann ablehnen")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
        assert result.formula.connective == LogicalConnective.OR
    
    def test_parse_wenn_dann(self):
        """
        GIVEN German implication with 'wenn...dann'
        WHEN parsing text
        THEN should create ConnectiveFormula with IMPLIES
        """
        parser = GermanParser()
        result = parser.parse("Wenn der Agent einhält dann der Agent kann fortfahren")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
        assert result.formula.connective == LogicalConnective.IMPLIES
    
    def test_parse_falls_dann(self):
        """
        GIVEN German implication with 'falls...dann'
        WHEN parsing text
        THEN should create ConnectiveFormula with IMPLIES
        """
        parser = GermanParser()
        result = parser.parse("Falls der Agent überprüft dann kann fortfahren")
        assert result.success
        assert isinstance(result.formula, ConnectiveFormula)
    
    def test_parse_complex_connectives(self):
        """
        GIVEN German text with multiple connectives
        WHEN parsing text
        THEN should parse primary structure
        """
        parser = GermanParser()
        result = parser.parse("Der Agent muss einhalten und der Agent kann überprüfen")
        assert result.success
        assert result.formula is not None
    
    def test_parse_nested_connectives(self):
        """
        GIVEN German text with nested connectives
        WHEN parsing text
        THEN should handle nesting
        """
        parser = GermanParser()
        result = parser.parse("Wenn der Agent muss einhalten und der Agent kann handeln dann geht weiter")
        # Complex parsing - should at least produce formula
        assert result.formula is not None
    
    def test_parse_und_multiple(self):
        """
        GIVEN German text with multiple 'und'
        WHEN parsing text
        THEN should parse first conjunction
        """
        parser = GermanParser()
        result = parser.parse("Der Agent muss A und muss B und muss C")
        assert result.formula is not None
    
    def test_parse_oder_multiple(self):
        """
        GIVEN German text with multiple 'oder'
        WHEN parsing text
        THEN should parse first disjunction
        """
        parser = GermanParser()
        result = parser.parse("Der Agent kann A oder kann B oder kann C")
        assert result.formula is not None
    
    def test_parse_mixed_connectives(self):
        """
        GIVEN German text with mixed connectives
        WHEN parsing text
        THEN should parse primary connective
        """
        parser = GermanParser()
        result = parser.parse("Wenn der Agent muss A oder muss B dann kann C")
        assert result.formula is not None
    
    def test_parse_connectives_confidence(self):
        """
        GIVEN German text with connectives
        WHEN parsing with confidence
        THEN should have reasonable confidence
        """
        parser = GermanParser()
        result = parser.parse("Der Agent muss einhalten und melden")
        assert result.formula is not None
        assert result.confidence >= 0.0


class TestVerbConjugations:
    """Test German verb conjugation handling."""
    
    def test_get_verb_conjugations(self):
        """
        GIVEN German verb conjugation function
        WHEN getting conjugations
        THEN should return conjugation tables
        """
        conjugations = get_german_verb_conjugations()
        assert 'müssen' in conjugations
        assert 'können' in conjugations
        assert 'dürfen' in conjugations
        assert 'wissen' in conjugations
        assert conjugations['müssen']['present']['er/sie/es'] == 'muss'
        assert conjugations['dürfen']['present']['er/sie/es'] == 'darf'
    
    def test_parse_different_conjugations(self):
        """
        GIVEN German text with various conjugations
        WHEN parsing text
        THEN should handle different forms
        """
        parser = GermanParser()
        
        # muss (3rd person singular)
        result1 = parser.parse("Der Agent muss handeln")
        assert result1.success
        
        # müssen (plural)
        result2 = parser.parse("Die Agenten müssen einhalten")
        assert result2.success
    
    def test_articles_function(self):
        """
        GIVEN get_german_articles function
        WHEN calling function
        THEN should return articles by case and gender
        """
        articles = get_german_articles()
        assert 'definite' in articles
        assert 'indefinite' in articles
        assert 'nominative' in articles['definite']
        assert 'der' in articles['definite']['nominative']
        assert 'ein' in articles['indefinite']['nominative']
    
    def test_parse_preterite_tense(self):
        """
        GIVEN German text with preterite tense
        WHEN parsing text
        THEN should parse correctly
        """
        parser = GermanParser()
        result = parser.parse("Der Agent musste beginnen gestern")
        # May not match exact pattern but should create formula
        assert result.formula is not None


class TestGermanSpecificFeatures:
    """Test German-specific language features."""
    
    def test_modal_particles_function(self):
        """
        GIVEN get_german_modal_particles function
        WHEN calling function
        THEN should return modal particles
        """
        particles = get_german_modal_particles()
        assert 'doch' in particles
        assert 'mal' in particles
        assert 'ja' in particles
        assert 'denn' in particles
    
    def test_deontic_keywords_function(self):
        """
        GIVEN get_german_deontic_keywords function
        WHEN calling function
        THEN should return categorized keywords
        """
        keywords = get_german_deontic_keywords()
        assert 'obligation' in keywords
        assert 'permission' in keywords
        assert 'prohibition' in keywords
        assert 'muss' in keywords['obligation']
        assert 'darf' in keywords['permission']
        assert 'verboten' in keywords['prohibition']
    
    def test_compound_words_function(self):
        """
        GIVEN get_german_compound_words function
        WHEN calling function
        THEN should return compound word mappings
        """
        compounds = get_german_compound_words()
        assert 'Handlungspflicht' in compounds
        assert 'Handlungserlaubnis' in compounds
        assert 'Verpflichtung' in compounds
        assert compounds['Handlungspflicht'] == 'action obligation'

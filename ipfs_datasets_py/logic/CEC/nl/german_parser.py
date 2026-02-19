"""
German Natural Language Parser for CEC (Phase 5 Week 4).

This module provides German language support for converting natural language
to DCEC formulas, handling German grammar, case system, and modal expressions.

Classes:
    GermanParser: Main parser for German text
    GermanPatternMatcher: Pattern-based German to DCEC converter

Features:
    - German verb conjugations and modal verbs
    - Deontic operators (muss, kann, verboten)
    - Temporal operators (immer, schließlich, dann, nachher)
    - Modal verbs (wissen, glauben, wollen, beabsichtigen)
    - Logical connectives (und, oder, nicht, wenn...dann)
    - Case system (nominative, accusative, dative, genitive)
    - Capitalized nouns (all nouns start with capital letters)
    - Compound words (Rechtspflicht, Handlungserlaubnis)
    - Modal particles (doch, mal, ja)

Usage:
    >>> from ipfs_datasets_py.logic.CEC.nl.german_parser import GermanParser
    >>> parser = GermanParser()
    >>> result = parser.parse("Der Agent muss die Aktion ausführen")
    >>> result.success
    True
"""

from typing import Dict, List, Optional, Tuple, Pattern
import re
import logging

from .base_parser import BaseParser, ParseResult
from .language_detector import Language
from ..native.dcec_core import (
    Formula,
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective,
    Predicate,
    Variable,
    VariableTerm,
)
from ..native.dcec_namespace import DCECNamespace

logger = logging.getLogger(__name__)


class GermanPatternMatcher:
    """
    Pattern-based German to DCEC converter.
    
    This class implements pattern matching for German natural language,
    handling German-specific grammar including case system, capitalized
    nouns, compound words, and modal particles.
    
    Attributes:
        namespace: DCEC namespace for creating formulas
        deontic_patterns: Patterns for deontic operators
        cognitive_patterns: Patterns for cognitive operators
        temporal_patterns: Patterns for temporal operators
        connective_patterns: Patterns for logical connectives
        
    Example:
        >>> matcher = GermanPatternMatcher(namespace)
        >>> formula = matcher.convert("Der Agent muss einhalten")
        >>> isinstance(formula, DeonticFormula)
        True
    """
    
    def __init__(self, namespace: DCECNamespace):
        """Initialize German pattern matcher.
        
        Args:
            namespace: DCEC namespace for formula creation
        """
        self.namespace = namespace
        self._init_patterns()
    
    def _init_patterns(self) -> None:
        """Initialize German conversion patterns."""
        # Deontic patterns - German modal verbs
        # IMPORTANT: Prohibition/negation patterns MUST come before positive forms
        self.deontic_patterns = [
            # Prohibition FIRST (nicht dürfen, verboten)
            (r"(?:nicht darf|nicht dürfen|darf nicht|dürfen nicht) (\w+)", DeonticOperator.PROHIBITION),
            (r"(?:nicht muss|muss nicht|nicht müssen|müssen nicht) (\w+)", DeonticOperator.PROHIBITION),
            (r"(?:verboten|ist verboten|es ist verboten) (\w+)", DeonticOperator.PROHIBITION),
            
            # Obligation patterns (muss, müssen, Pflicht, etc.)
            (r"(?:müssen|verpflichtet sind|sind verpflichtet|haben die Pflicht) (\w+)", DeonticOperator.OBLIGATION),
            (r"(?:muss|ist verpflichtet|hat die Pflicht|es ist erforderlich) (\w+)", DeonticOperator.OBLIGATION),
            (r"(?:soll|sollte|sollen|sollten) (\w+)", DeonticOperator.OBLIGATION),
            
            # Permission patterns (darf, dürfen, erlaubt, etc.)
            (r"(?:dürfen|sind erlaubt|sind berechtigt|haben das Recht) (\w+)", DeonticOperator.PERMISSION),
            (r"(?:darf|kann|ist erlaubt|ist berechtigt|hat das Recht) (\w+)", DeonticOperator.PERMISSION),
            (r"(?:es ist erlaubt|man darf|man kann) (\w+)", DeonticOperator.PERMISSION),
        ]
        
        # Cognitive patterns - German mental state verbs
        self.cognitive_patterns = [
            # Belief (glaubt, denkt, meint)
            (r"(?:glaubt dass|denkt dass|meint dass|nimmt an dass) (.+)", CognitiveOperator.BELIEF),
            
            # Knowledge (weiß)
            (r"(?:weiß dass|kennt|ist sich bewusst dass) (.+)", CognitiveOperator.KNOWLEDGE),
            
            # Intention (beabsichtigt, plant, hat vor)
            (r"(?:beabsichtigt|plant|hat vor|gedenkt) (\w+)", CognitiveOperator.INTENTION),
            
            # Desire (will, möchte, wünscht)
            (r"(?:will|möchte|wünscht|strebt an|hat den Wunsch) (\w+)", CognitiveOperator.DESIRE),
            
            # Goal (hat das Ziel, zielt darauf ab)
            (r"(?:hat das Ziel|zielt darauf ab|sein Ziel ist) (\w+)", CognitiveOperator.GOAL),
        ]
        
        # Temporal patterns - German temporal expressions
        self.temporal_patterns = [
            # Always (immer, stets, jederzeit)
            (r"(?:immer|stets|jederzeit|allezeit) (.+)", TemporalOperator.ALWAYS),
            
            # Eventually (schließlich, irgendwann, letztendlich)
            (r"(?:schließlich|irgendwann|letztendlich|am Ende) (.+)", TemporalOperator.EVENTUALLY),
            
            # Next (dann, danach, als nächstes)
            (r"(?:dann|danach|als nächstes|im nächsten Moment) (.+)", TemporalOperator.NEXT),
            
            # Until (bis)
            (r"(.+) bis (.+)", TemporalOperator.UNTIL),
            
            # Since (seit, seitdem)
            (r"(.+) (?:seit|seitdem) (.+)", TemporalOperator.SINCE),
        ]
        
        # Logical connectives - German conjunctions
        self.connective_patterns = [
            # And (und)
            (r"(.+) und (.+)", LogicalConnective.AND),
            
            # Or (oder)
            (r"(.+) oder (.+)", LogicalConnective.OR),
            
            # Implies (wenn...dann)
            (r"wenn (.+) dann (.+)", LogicalConnective.IMPLIES),
            (r"wenn (.+),? (.+)", LogicalConnective.IMPLIES),
            (r"falls (.+) dann (.+)", LogicalConnective.IMPLIES),
            
            # Not (nicht) - but NOT when part of deontic phrases
            # Only match standalone nicht
            (r"^nicht\s+(?!darf|muss|ist\s+erlaubt)(.+)", LogicalConnective.NOT),
        ]
    
    def _extract_agent(self, text: str) -> Optional[str]:
        """Extract agent name from German text.
        
        Handles German articles: der, die, das, den, dem, des.
        Note: German nouns are capitalized.
        
        Args:
            text: German text
            
        Returns:
            Agent name or None
        """
        # German articles (all cases)
        match = re.match(r"(?:der|die|das|den|dem|des|ein|eine|einen|einem|eines)? ?(\w+)", text)
        if match:
            agent = match.group(1)
            # Preserve capitalization for German nouns
            return agent if agent else None
        return None
    
    def _create_simple_predicate(self, action: str) -> Predicate:
        """Create or get predicate for German action.
        
        Args:
            action: German action word
            
        Returns:
            Predicate for the action
        """
        # Convert to lowercase for predicate name
        pred_name = action.replace(" ", "_").lower()
        
        # Check if predicate exists
        existing = self.namespace.get_predicate(pred_name)
        if existing:
            return existing
        
        # Create new predicate
        try:
            return self.namespace.add_predicate(pred_name, ["Agent"])
        except ValueError:
            return self.namespace.get_predicate(pred_name)
    
    def _create_agent_variable(self, agent_name: Optional[str] = None) -> Variable:
        """Create or get variable for German agent.
        
        Args:
            agent_name: German agent name (may be capitalized)
            
        Returns:
            Variable for the agent
        """
        # Lowercase for variable name
        var_name = agent_name.lower() if agent_name else "agent"
        
        # Check if variable exists
        existing = self.namespace.get_variable(var_name)
        if existing:
            return existing
        
        # Create new variable
        try:
            return self.namespace.add_variable(var_name, "Agent")
        except ValueError:
            return self.namespace.get_variable(var_name)
    
    def convert(self, text: str) -> Optional[Formula]:
        """Convert German text to DCEC formula.
        
        Args:
            text: German text to convert
            
        Returns:
            DCEC Formula or None if no match
        """
        text = text.strip()
        
        # Extract agent (preserve case for German)
        agent_name = self._extract_agent(text)
        
        # Try connectives FIRST (to handle compound sentences)
        for pattern, connective in self.connective_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if connective == LogicalConnective.NOT:
                    content = match.group(1)
                    inner_formula = self.convert(content)
                    if inner_formula:
                        return ConnectiveFormula(connective, [inner_formula])
                else:
                    part1 = match.group(1)
                    part2 = match.group(2)
                    formula1 = self.convert(part1)
                    formula2 = self.convert(part2)
                    if formula1 and formula2:
                        return ConnectiveFormula(connective, [formula1, formula2])
        
        # Try temporal patterns SECOND
        for pattern, operator in self.temporal_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if operator in [TemporalOperator.UNTIL, TemporalOperator.SINCE]:
                    # Binary temporal operators
                    part1 = match.group(1)
                    part2 = match.group(2)
                    formula1 = self.convert(part1)
                    formula2 = self.convert(part2)
                    if formula1 and formula2:
                        return TemporalFormula(operator, formula1)
                else:
                    # Unary temporal operators
                    content = match.group(1)
                    inner_formula = self.convert(content)
                    if inner_formula:
                        return TemporalFormula(operator, inner_formula)
        
        # Try deontic patterns THIRD
        for pattern, operator in self.deontic_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                action = match.group(1)
                pred = self._create_simple_predicate(action)
                agent_var = self._create_agent_variable(agent_name)
                
                base_formula = AtomicFormula(pred, [VariableTerm(agent_var)])
                return DeonticFormula(operator, base_formula)
        
        # Try cognitive patterns FOURTH
        for pattern, operator in self.cognitive_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                content = match.group(1)
                agent_var = self._create_agent_variable(agent_name)
                
                # Recursively convert content
                inner_formula = self.convert(content)
                if inner_formula:
                    return CognitiveFormula(operator, VariableTerm(agent_var), inner_formula)
                else:
                    # Create simple predicate
                    pred = self._create_simple_predicate(content)
                    inner_formula = AtomicFormula(pred, [VariableTerm(agent_var)])
                    return CognitiveFormula(operator, VariableTerm(agent_var), inner_formula)
        
        # Fallback: create simple predicate
        pred = self._create_simple_predicate(text)
        agent_var = self._create_agent_variable(agent_name)
        return AtomicFormula(pred, [VariableTerm(agent_var)])


class GermanParser(BaseParser):
    """
    German language parser for CEC.
    
    Implements BaseParser interface for parsing German natural language
    into DCEC formulas. Handles German grammar including:
    
    - Verb conjugations (present, preterite, perfect, future)
    - Case system (nominative, accusative, dative, genitive)
    - Gender agreement (der/die/das with masculine/feminine/neuter)
    - Capitalized nouns (all nouns begin with capital letters)
    - Compound words (Verpflichtung, Berechtigung, Handlung)
    - Modal particles (doch, mal, ja, denn)
    - Word order flexibility (V2, SOV in subordinate clauses)
    - Separable verbs (ausführen, durchführen, einhalten)
    
    Example:
        >>> parser = GermanParser()
        >>> result = parser.parse("Der Agent muss die Handlung ausführen")
        >>> result.success
        True
        >>> result.formula  # DeonticFormula(OBLIGATION, ...)
    """
    
    def __init__(self, confidence_threshold: float = 0.5):
        """Initialize German parser.
        
        Args:
            confidence_threshold: Minimum confidence for successful parse
        """
        super().__init__("de", confidence_threshold=confidence_threshold)
        self.namespace = DCECNamespace()
        self.matcher = GermanPatternMatcher(self.namespace)
        logger.info("German parser initialized")
    
    def parse_impl(self, text: str) -> ParseResult:
        """Implement German-specific parsing logic.
        
        Args:
            text: Normalized German text
            
        Returns:
            ParseResult with parsed formula
        """
        try:
            # Attempt pattern-based conversion
            formula = self.matcher.convert(text)
            
            if formula:
                # Calculate confidence based on match quality
                confidence = self._calculate_confidence(text, formula)
                
                return ParseResult(
                    formula=formula,
                    confidence=confidence,
                    success=True,
                    metadata={
                        'language': 'de',
                        'method': 'pattern_matching',
                        'text_length': len(text)
                    }
                )
            else:
                # No pattern matched
                result = ParseResult()
                result.add_error("Deutscher Text konnte nicht analysiert werden")
                return result
                
        except Exception as e:
            logger.error(f"German parsing error: {e}")
            result = ParseResult()
            result.add_error(f"Analysefehler: {str(e)}")
            return result
    
    def _calculate_confidence(self, text: str, formula: Formula) -> float:
        """Calculate confidence score for German parse.
        
        Confidence based on:
        - Presence of German keywords (40%)
        - Capitalized nouns (bonus for German) (15%)
        - Match specificity (25%)
        - Text complexity (10%)
        - Grammar correctness (10%)
        
        Args:
            text: Original German text
            formula: Parsed formula
            
        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = 0.5  # Base confidence
        
        # Check for German keywords
        german_keywords = [
            'muss', 'kann', 'darf', 'soll', 'verboten', 'erlaubt',
            'weiß', 'glaubt', 'will', 'möchte', 'beabsichtigt',
            'immer', 'schließlich', 'dann', 'nachher',
            'wenn', 'und', 'oder', 'nicht'
        ]
        
        text_lower = text.lower()
        keyword_count = sum(1 for kw in german_keywords if kw in text_lower)
        
        # Keyword bonus (up to +0.3)
        confidence += min(0.3, keyword_count * 0.1)
        
        # Capitalized noun bonus (German-specific, up to +0.15)
        capitalized_words = re.findall(r'\b[A-ZÄÖÜ][a-zäöüß]+\b', text)
        if len(capitalized_words) > 0:
            confidence += min(0.15, len(capitalized_words) * 0.05)
        
        # Formula complexity bonus (up to +0.05)
        if isinstance(formula, (DeonticFormula, CognitiveFormula, TemporalFormula)):
            confidence += 0.05
        
        return min(1.0, confidence)
    
    def get_supported_operators(self) -> List[str]:
        """Get list of supported German operators.
        
        Returns:
            List of German operator keywords
        """
        return [
            # Deontic
            'muss', 'kann', 'darf', 'soll', 'verboten', 'erlaubt',
            'ist erlaubt', 'ist verboten', 'Pflicht', 'Berechtigung',
            
            # Cognitive
            'weiß', 'glaubt', 'denkt', 'will', 'möchte', 'beabsichtigt',
            'kennt', 'meint', 'nimmt an',
            
            # Temporal
            'immer', 'schließlich', 'dann', 'nachher', 'niemals',
            'jederzeit', 'irgendwann', 'bis', 'seit',
            
            # Connectives
            'und', 'oder', 'nicht', 'wenn', 'dann', 'falls'
        ]


def get_german_verb_conjugations() -> Dict[str, Dict[str, str]]:
    """Get German verb conjugations for common modal verbs.
    
    Returns dictionary mapping verb infinitives to conjugation tables
    for present, preterite, and future tenses.
    
    Returns:
        Dict mapping verb infinitives to conjugation tables
        
    Example:
        >>> conjugations = get_german_verb_conjugations()
        >>> conjugations['müssen']['present']['er/sie/es']
        'muss'
    """
    return {
        'müssen': {  # must
            'present': {
                'ich': 'muss',
                'du': 'musst',
                'er/sie/es': 'muss',
                'wir': 'müssen',
                'ihr': 'müsst',
                'sie/Sie': 'müssen'
            },
            'preterite': {
                'ich': 'musste',
                'du': 'musstest',
                'er/sie/es': 'musste',
                'wir': 'mussten',
                'ihr': 'musstet',
                'sie/Sie': 'mussten'
            }
        },
        'können': {  # can
            'present': {
                'ich': 'kann',
                'du': 'kannst',
                'er/sie/es': 'kann',
                'wir': 'können',
                'ihr': 'könnt',
                'sie/Sie': 'können'
            },
            'preterite': {
                'ich': 'konnte',
                'du': 'konntest',
                'er/sie/es': 'konnte',
                'wir': 'konnten',
                'ihr': 'konntet',
                'sie/Sie': 'konnten'
            }
        },
        'dürfen': {  # may
            'present': {
                'ich': 'darf',
                'du': 'darfst',
                'er/sie/es': 'darf',
                'wir': 'dürfen',
                'ihr': 'dürft',
                'sie/Sie': 'dürfen'
            }
        },
        'sollen': {  # should
            'present': {
                'ich': 'soll',
                'du': 'sollst',
                'er/sie/es': 'soll',
                'wir': 'sollen',
                'ihr': 'sollt',
                'sie/Sie': 'sollen'
            }
        },
        'wissen': {  # to know
            'present': {
                'ich': 'weiß',
                'du': 'weißt',
                'er/sie/es': 'weiß',
                'wir': 'wissen',
                'ihr': 'wisst',
                'sie/Sie': 'wissen'
            }
        },
        'wollen': {  # to want
            'present': {
                'ich': 'will',
                'du': 'willst',
                'er/sie/es': 'will',
                'wir': 'wollen',
                'ihr': 'wollt',
                'sie/Sie': 'wollen'
            }
        }
    }


def get_german_articles() -> Dict[str, Dict[str, List[str]]]:
    """Get German articles by case and gender.
    
    German has four cases (nominative, accusative, dative, genitive)
    and three genders (masculine, feminine, neuter).
    
    Returns:
        Dict with articles organized by case and gender
    """
    return {
        'definite': {
            'nominative': ['der', 'die', 'das'],  # m, f, n
            'accusative': ['den', 'die', 'das'],
            'dative': ['dem', 'der', 'dem'],
            'genitive': ['des', 'der', 'des']
        },
        'indefinite': {
            'nominative': ['ein', 'eine', 'ein'],
            'accusative': ['einen', 'eine', 'ein'],
            'dative': ['einem', 'einer', 'einem'],
            'genitive': ['eines', 'einer', 'eines']
        }
    }


def get_german_modal_particles() -> List[str]:
    """Get German modal particles.
    
    Modal particles add nuance but don't change logical meaning.
    
    Returns:
        List of German modal particles
    """
    return [
        'doch',    # contradiction, emphasis
        'mal',     # softening, casualness
        'ja',      # obviousness, reminder
        'denn',    # curiosity, interest
        'halt',    # resignation, acceptance
        'eben',    # matter-of-factness
        'schon',   # concession, expectation
        'nur',     # limitation, restriction
    ]


def get_german_deontic_keywords() -> Dict[str, List[str]]:
    """Get German deontic keywords categorized by operator type.
    
    Returns:
        Dict mapping operator types to German keywords
    """
    return {
        'obligation': [
            'muss', 'müssen', 'soll', 'sollen', 'Pflicht', 'verpflichtet',
            'ist verpflichtet', 'sind verpflichtet', 'hat die Pflicht',
            'haben die Pflicht', 'erforderlich', 'notwendig'
        ],
        'permission': [
            'darf', 'dürfen', 'kann', 'können', 'erlaubt', 'Berechtigung',
            'ist erlaubt', 'sind erlaubt', 'ist berechtigt', 'hat das Recht',
            'haben das Recht', 'gestattet', 'zulässig'
        ],
        'prohibition': [
            'nicht darf', 'nicht dürfen', 'verboten', 'Verbot',
            'ist verboten', 'untersagt', 'nicht erlaubt', 'nicht gestattet',
            'unzulässig', 'rechtswidrig'
        ]
    }


def get_german_compound_words() -> Dict[str, str]:
    """Get common German compound words used in CEC contexts.
    
    German frequently uses compound nouns combining multiple concepts.
    
    Returns:
        Dict mapping compound words to their components/meaning
    """
    return {
        'Handlungspflicht': 'action obligation',
        'Handlungserlaubnis': 'action permission',
        'Handlungsverbot': 'action prohibition',
        'Wissenszustand': 'knowledge state',
        'Glaubenszustand': 'belief state',
        'Zeitpunkt': 'time point',
        'Verpflichtung': 'obligation',
        'Berechtigung': 'authorization',
        'Rechtspflicht': 'legal obligation',
    }

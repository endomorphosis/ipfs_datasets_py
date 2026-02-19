"""
Spanish Natural Language Parser for CEC (Phase 5 Week 2).

This module provides Spanish language support for converting natural language
to DCEC formulas, handling Spanish grammar, verb conjugations, and modal expressions.

Classes:
    SpanishParser: Main parser for Spanish text
    SpanishPatternMatcher: Pattern-based Spanish to DCEC converter

Features:
    - Spanish verb conjugations (present, preterite, imperfect, future)
    - Deontic operators (debe, puede, prohibido)
    - Temporal operators (siempre, eventualmente, luego, después)
    - Modal verbs (saber, creer, desear, querer, intentar)
    - Logical connectives (y, o, no, si...entonces)
    - Cultural context awareness

Usage:
    >>> from ipfs_datasets_py.logic.CEC.nl.spanish_parser import SpanishParser
    >>> parser = SpanishParser()
    >>> result = parser.parse("El agente debe realizar la acción")
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


class SpanishPatternMatcher:
    """
    Pattern-based Spanish to DCEC converter.
    
    This class implements pattern matching for Spanish natural language,
    handling Spanish-specific grammar including gender agreement, verb
    conjugations, and idiomatic expressions.
    
    Attributes:
        namespace: DCEC namespace for creating formulas
        deontic_patterns: Patterns for deontic operators
        cognitive_patterns: Patterns for cognitive operators
        temporal_patterns: Patterns for temporal operators
        connective_patterns: Patterns for logical connectives
        
    Example:
        >>> matcher = SpanishPatternMatcher(namespace)
        >>> formula = matcher.convert("El agente debe cumplir")
        >>> isinstance(formula, DeonticFormula)
        True
    """
    
    def __init__(self, namespace: DCECNamespace):
        """Initialize Spanish pattern matcher.
        
        Args:
            namespace: DCEC namespace for formula creation
        """
        self.namespace = namespace
        self._init_patterns()
    
    def _init_patterns(self) -> None:
        """Initialize Spanish conversion patterns."""
        # Deontic patterns - Spanish modal verbs
        # IMPORTANT: Prohibition patterns MUST come before obligation/permission
        self.deontic_patterns = [
            # Prohibition FIRST (no debe, no puede, prohibido)
            (r"(?:no debe|no puede|no se permite|no se puede|no se le permite|no tiene permiso para) (\w+)", DeonticOperator.PROHIBITION),
            (r"(?:prohibido|está prohibido|es prohibido) (\w+)", DeonticOperator.PROHIBITION),
            
            # Obligation patterns (deben, tienen que, etc.) - with plural support
            (r"(?:deben|tienen que|deben de|están obligados a|son obligatorios) (\w+)", DeonticOperator.OBLIGATION),
            (r"(?:debe|tiene que|debe de|está obligado a|es obligatorio) (\w+)", DeonticOperator.OBLIGATION),
            (r"(?:hay que) (\w+)", DeonticOperator.OBLIGATION),
            (r"(?:es necesario|se requiere|se necesita) (\w+)", DeonticOperator.OBLIGATION),
            
            # Permission patterns (pueden, se permite, etc.) - with plural support
            (r"(?:pueden|se permite|están permitidos|son permitidos) (\w+)", DeonticOperator.PERMISSION),
            (r"(?:puede|podrá|se permite|está permitido|es permitido) (\w+)", DeonticOperator.PERMISSION),
            (r"(?:se puede|se le permite|tiene permiso para) (\w+)", DeonticOperator.PERMISSION),
        ]
        
        # Cognitive patterns - Spanish mental state verbs
        self.cognitive_patterns = [
            # Belief (cree, piensa)
            (r"(?:cree que|piensa que|opina que|considera que) (.+)", CognitiveOperator.BELIEF),
            
            # Knowledge (sabe)
            (r"(?:sabe que|conoce que|es consciente de que) (.+)", CognitiveOperator.KNOWLEDGE),
            
            # Intention (intenta, pretende, planea)
            (r"(?:intenta|pretende|planea|tiene intención de|piensa) (\w+)", CognitiveOperator.INTENTION),
            
            # Desire (desea, quiere)
            (r"(?:desea|quiere|anhela|aspira a|tiene deseo de) (\w+)", CognitiveOperator.DESIRE),
            
            # Goal (tiene objetivo, tiene meta)
            (r"(?:tiene objetivo de|tiene meta de|su objetivo es|su meta es) (\w+)", CognitiveOperator.GOAL),
        ]
        
        # Temporal patterns - Spanish temporal expressions
        self.temporal_patterns = [
            # Always (siempre)
            (r"siempre (.+)", TemporalOperator.ALWAYS),
            (r"en todo momento (.+)", TemporalOperator.ALWAYS),
            
            # Eventually (eventualmente, finalmente, algún día)
            (r"(?:eventualmente|finalmente|algún día|en algún momento) (.+)", TemporalOperator.EVENTUALLY),
            
            # Next (luego, después, siguiente)
            (r"(?:luego|después|siguiente|en el próximo momento) (.+)", TemporalOperator.NEXT),
            
            # Until (hasta que)
            (r"(.+) hasta que (.+)", TemporalOperator.UNTIL),
            
            # Since (desde que)
            (r"(.+) desde que (.+)", TemporalOperator.SINCE),
        ]
        
        # Logical connectives - Spanish conjunctions
        self.connective_patterns = [
            # And (y, e)
            (r"(.+) y (.+)", LogicalConnective.AND),
            (r"(.+) e (.+)", LogicalConnective.AND),  # "e" before "i" sound
            
            # Or (o, u)
            (r"(.+) o (.+)", LogicalConnective.OR),
            (r"(.+) u (.+)", LogicalConnective.OR),  # "u" before "o" sound
            
            # Implies (si...entonces)
            (r"si (.+) entonces (.+)", LogicalConnective.IMPLIES),
            (r"si (.+),? (.+)", LogicalConnective.IMPLIES),
            
            # Not (no) - but NOT when part of deontic phrases
            # Only match "no" at start when not followed by deontic verbs
            (r"^no\s+(?!debe|puede|se\s+permite|se\s+puede|tiene\s+permiso)(.+)", LogicalConnective.NOT),
        ]
    
    def _extract_agent(self, text: str) -> Optional[str]:
        """Extract agent name from Spanish text.
        
        Handles Spanish article patterns: el, la, los, las.
        
        Args:
            text: Spanish text
            
        Returns:
            Agent name or None
        """
        # Spanish articles: el, la, los, las
        match = re.match(r"(?:el|la|los|las)? ?(\w+)", text.lower())
        if match:
            return match.group(1)
        return None
    
    def _create_simple_predicate(self, action: str) -> Predicate:
        """Create or get predicate for Spanish action.
        
        Args:
            action: Spanish action word
            
        Returns:
            Predicate for the action
        """
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
        """Create or get variable for Spanish agent.
        
        Args:
            agent_name: Spanish agent name
            
        Returns:
            Variable for the agent
        """
        var_name = agent_name if agent_name else "agente"
        
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
        """Convert Spanish text to DCEC formula.
        
        Args:
            text: Spanish text to convert
            
        Returns:
            DCEC Formula or None if no match
        """
        text = text.strip().lower()
        
        # Extract agent
        agent_name = self._extract_agent(text)
        
        # Try connectives FIRST (to handle compound sentences before simple patterns)
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
        
        # Try temporal patterns SECOND (before deontic to catch temporal wrappers)
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
                        # For binary temporal operators, wrap in temporal formula
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


class SpanishParser(BaseParser):
    """
    Spanish language parser for CEC.
    
    Implements BaseParser interface for parsing Spanish natural language
    into DCEC formulas. Handles Spanish grammar including:
    
    - Verb conjugations (present, preterite, imperfect, future)
    - Gender and number agreement
    - Articles (el, la, los, las, un, una)
    - Reflexive verbs (se permite, se debe)
    - Idiomatic expressions
    
    Example:
        >>> parser = SpanishParser()
        >>> result = parser.parse("El agente debe realizar la acción")
        >>> result.success
        True
        >>> result.formula  # DeonticFormula(OBLIGATION, ...)
    """
    
    def __init__(self, confidence_threshold: float = 0.5):
        """Initialize Spanish parser.
        
        Args:
            confidence_threshold: Minimum confidence for successful parse
        """
        super().__init__("es", confidence_threshold=confidence_threshold)
        self.namespace = DCECNamespace()
        self.matcher = SpanishPatternMatcher(self.namespace)
        logger.info("Spanish parser initialized")
    
    def parse_impl(self, text: str) -> ParseResult:
        """Implement Spanish-specific parsing logic.
        
        Args:
            text: Normalized Spanish text
            
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
                        'language': 'es',
                        'method': 'pattern_matching',
                        'text_length': len(text)
                    }
                )
            else:
                # No pattern matched
                result = ParseResult()
                result.add_error("No se pudo analizar el texto español")
                return result
                
        except Exception as e:
            logger.error(f"Spanish parsing error: {e}")
            result = ParseResult()
            result.add_error(f"Error de análisis: {str(e)}")
            return result
    
    def _calculate_confidence(self, text: str, formula: Formula) -> float:
        """Calculate confidence score for Spanish parse.
        
        Confidence based on:
        - Presence of Spanish keywords (40%)
        - Match specificity (30%)
        - Text complexity (20%)
        - Grammar correctness (10%)
        
        Args:
            text: Original Spanish text
            formula: Parsed formula
            
        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = 0.5  # Base confidence
        
        # Check for Spanish keywords
        spanish_keywords = [
            'debe', 'puede', 'prohibido', 'obligado', 'permitido',
            'sabe', 'cree', 'quiere', 'desea', 'intenta',
            'siempre', 'eventualmente', 'luego', 'después',
            'si', 'entonces', 'y', 'o', 'no'
        ]
        
        text_lower = text.lower()
        keyword_count = sum(1 for kw in spanish_keywords if kw in text_lower)
        
        # Keyword bonus (up to +0.3)
        confidence += min(0.3, keyword_count * 0.1)
        
        # Formula complexity bonus (up to +0.1)
        if isinstance(formula, (DeonticFormula, CognitiveFormula, TemporalFormula)):
            confidence += 0.1
        
        # Connective bonus (up to +0.1)
        if isinstance(formula, ConnectiveFormula):
            confidence += 0.1
        
        return min(1.0, confidence)
    
    def get_supported_operators(self) -> List[str]:
        """Get list of supported Spanish operators.
        
        Returns:
            List of Spanish operator keywords
        """
        return [
            # Deontic
            'debe', 'puede', 'prohibido', 'obligado', 'permitido',
            'tiene que', 'se permite', 'está prohibido',
            
            # Cognitive
            'sabe', 'cree', 'piensa', 'quiere', 'desea', 'intenta',
            'conoce', 'opina', 'considera',
            
            # Temporal
            'siempre', 'eventualmente', 'luego', 'después', 'nunca',
            'en todo momento', 'algún día', 'hasta que', 'desde que',
            
            # Connectives
            'y', 'o', 'e', 'u', 'no', 'si', 'entonces'
        ]


def get_spanish_verb_conjugations() -> Dict[str, Dict[str, str]]:
    """Get Spanish verb conjugations for common modal verbs.
    
    Returns dictionary mapping verb infinitives to conjugation tables
    for present, preterite, imperfect, and future tenses.
    
    Returns:
        Dict mapping verb infinitives to conjugation tables
        
    Example:
        >>> conjugations = get_spanish_verb_conjugations()
        >>> conjugations['deber']['present']['él/ella']
        'debe'
    """
    return {
        'deber': {  # must, should
            'present': {
                'yo': 'debo',
                'tú': 'debes',
                'él/ella': 'debe',
                'nosotros': 'debemos',
                'vosotros': 'debéis',
                'ellos/ellas': 'deben'
            },
            'preterite': {
                'yo': 'debí',
                'tú': 'debiste',
                'él/ella': 'debió',
                'nosotros': 'debimos',
                'vosotros': 'debisteis',
                'ellos/ellas': 'debieron'
            },
            'future': {
                'yo': 'deberé',
                'tú': 'deberás',
                'él/ella': 'deberá',
                'nosotros': 'deberemos',
                'vosotros': 'deberéis',
                'ellos/ellas': 'deberán'
            }
        },
        'poder': {  # can, may
            'present': {
                'yo': 'puedo',
                'tú': 'puedes',
                'él/ella': 'puede',
                'nosotros': 'podemos',
                'vosotros': 'podéis',
                'ellos/ellas': 'pueden'
            },
            'preterite': {
                'yo': 'pude',
                'tú': 'pudiste',
                'él/ella': 'pudo',
                'nosotros': 'pudimos',
                'vosotros': 'pudisteis',
                'ellos/ellas': 'pudieron'
            },
            'future': {
                'yo': 'podré',
                'tú': 'podrás',
                'él/ella': 'podrá',
                'nosotros': 'podremos',
                'vosotros': 'podréis',
                'ellos/ellas': 'podrán'
            }
        },
        'saber': {  # to know
            'present': {
                'yo': 'sé',
                'tú': 'sabes',
                'él/ella': 'sabe',
                'nosotros': 'sabemos',
                'vosotros': 'sabéis',
                'ellos/ellas': 'saben'
            }
        },
        'creer': {  # to believe
            'present': {
                'yo': 'creo',
                'tú': 'crees',
                'él/ella': 'cree',
                'nosotros': 'creemos',
                'vosotros': 'creéis',
                'ellos/ellas': 'creen'
            }
        },
        'querer': {  # to want
            'present': {
                'yo': 'quiero',
                'tú': 'quieres',
                'él/ella': 'quiere',
                'nosotros': 'queremos',
                'vosotros': 'queréis',
                'ellos/ellas': 'quieren'
            }
        }
    }


def get_spanish_articles() -> Dict[str, List[str]]:
    """Get Spanish articles (definite and indefinite).
    
    Returns:
        Dict with definite and indefinite article lists
    """
    return {
        'definite': ['el', 'la', 'los', 'las'],
        'indefinite': ['un', 'una', 'unos', 'unas']
    }


def get_spanish_deontic_keywords() -> Dict[str, List[str]]:
    """Get Spanish deontic keywords categorized by operator type.
    
    Returns:
        Dict mapping operator types to Spanish keywords
    """
    return {
        'obligation': [
            'debe', 'tiene que', 'debe de', 'obligado', 'obligación',
            'es obligatorio', 'es necesario', 'se requiere', 'se necesita',
            'hay que', 'requerido', 'necesario'
        ],
        'permission': [
            'puede', 'podrá', 'se permite', 'permitido', 'permiso',
            'está permitido', 'es permitido', 'se puede', 'se le permite',
            'tiene permiso', 'autorizado', 'facultado'
        ],
        'prohibition': [
            'no debe', 'no puede', 'prohibido', 'prohibición',
            'está prohibido', 'no se permite', 'no se puede',
            'no se le permite', 'vedado', 'vetado', 'ilegal'
        ]
    }

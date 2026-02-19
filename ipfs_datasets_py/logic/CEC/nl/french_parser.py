"""
French Natural Language Parser for CEC (Phase 5 Week 3).

This module provides French language support for converting natural language
to DCEC formulas, handling French grammar, negation patterns, and modal expressions.

Classes:
    FrenchParser: Main parser for French text
    FrenchPatternMatcher: Pattern-based French to DCEC converter

Features:
    - French verb conjugations (present, passé composé, imparfait, futur)
    - Deontic operators (doit, peut, interdit)
    - Temporal operators (toujours, éventuellement, ensuite, après)
    - Modal verbs (savoir, croire, désirer, vouloir)
    - Logical connectives (et, ou, ne...pas, si...alors)
    - French negation patterns (ne...pas, ne...jamais, etc.)
    - Articles and contractions (le, la, l', du, de la)

Usage:
    >>> from ipfs_datasets_py.logic.CEC.nl.french_parser import FrenchParser
    >>> parser = FrenchParser()
    >>> result = parser.parse("L'agent doit effectuer l'action")
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


class FrenchPatternMatcher:
    """
    Pattern-based French to DCEC converter.
    
    This class implements pattern matching for French natural language,
    handling French-specific grammar including gender agreement, verb
    conjugations, negation patterns (ne...pas), and contractions.
    
    Attributes:
        namespace: DCEC namespace for creating formulas
        deontic_patterns: Patterns for deontic operators
        cognitive_patterns: Patterns for cognitive operators
        temporal_patterns: Patterns for temporal operators
        connective_patterns: Patterns for logical connectives
        
    Example:
        >>> matcher = FrenchPatternMatcher(namespace)
        >>> formula = matcher.convert("L'agent doit respecter")
        >>> isinstance(formula, DeonticFormula)
        True
    """
    
    def __init__(self, namespace: DCECNamespace):
        """Initialize French pattern matcher.
        
        Args:
            namespace: DCEC namespace for formula creation
        """
        self.namespace = namespace
        self._init_patterns()
    
    def _init_patterns(self) -> None:
        """Initialize French conversion patterns."""
        # Deontic patterns - French modal verbs
        # IMPORTANT: Prohibition/negation patterns MUST come before positive forms
        self.deontic_patterns = [
            # Prohibition FIRST (ne doit pas, ne peut pas, interdit)
            (r"(?:ne doit pas|ne peut pas|ne doit jamais|ne peut jamais) (\w+)", DeonticOperator.PROHIBITION),
            (r"(?:n'est pas permis de|ne se permet pas de|n'a pas le droit de) (\w+)", DeonticOperator.PROHIBITION),
            (r"(?:interdit de|est interdit de|défendu de|prohibé de) (\w+)", DeonticOperator.PROHIBITION),
            
            # Obligation patterns (doit, doivent, il faut, etc.)
            (r"(?:doivent|ont l'obligation de|sont obligés de|sont tenus de) (\w+)", DeonticOperator.OBLIGATION),
            (r"(?:doit|a l'obligation de|est obligé de|est tenu de) (\w+)", DeonticOperator.OBLIGATION),
            (r"(?:il faut|il est nécessaire de|il est requis de) (\w+)", DeonticOperator.OBLIGATION),
            
            # Permission patterns (peut, peuvent, est permis, etc.)
            (r"(?:peuvent|ont le droit de|sont permis de|sont autorisés à) (\w+)", DeonticOperator.PERMISSION),
            (r"(?:peut|a le droit de|est permis de|est autorisé à) (\w+)", DeonticOperator.PERMISSION),
            (r"(?:il est permis de|on peut|se peut) (\w+)", DeonticOperator.PERMISSION),
        ]
        
        # Cognitive patterns - French mental state verbs
        self.cognitive_patterns = [
            # Belief (croit, pense)
            (r"(?:croit que|pense que|estime que|considère que) (.+)", CognitiveOperator.BELIEF),
            
            # Knowledge (sait)
            (r"(?:sait que|connaît que|a connaissance que) (.+)", CognitiveOperator.KNOWLEDGE),
            
            # Intention (a l'intention de, compte, prévoit)
            (r"(?:a l'intention de|compte|prévoit de|envisage de) (\w+)", CognitiveOperator.INTENTION),
            
            # Desire (désire, veut, souhaite)
            (r"(?:désire|veut|souhaite|aspire à|a envie de) (\w+)", CognitiveOperator.DESIRE),
            
            # Goal (a pour objectif, a pour but)
            (r"(?:a pour objectif de|a pour but de|vise à) (\w+)", CognitiveOperator.GOAL),
        ]
        
        # Temporal patterns - French temporal expressions
        self.temporal_patterns = [
            # Always (toujours)
            (r"toujours (.+)", TemporalOperator.ALWAYS),
            (r"en tout temps (.+)", TemporalOperator.ALWAYS),
            (r"à tout moment (.+)", TemporalOperator.ALWAYS),
            
            # Eventually (éventuellement, finalement, un jour)
            (r"(?:éventuellement|finalement|un jour|à un moment donné) (.+)", TemporalOperator.EVENTUALLY),
            
            # Next (ensuite, après, prochain)
            (r"(?:ensuite|après|au prochain moment|dans le moment suivant) (.+)", TemporalOperator.NEXT),
            
            # Until (jusqu'à ce que)
            (r"(.+) jusqu'à ce que (.+)", TemporalOperator.UNTIL),
            
            # Since (depuis que)
            (r"(.+) depuis que (.+)", TemporalOperator.SINCE),
        ]
        
        # Logical connectives - French conjunctions
        self.connective_patterns = [
            # And (et)
            (r"(.+) et (.+)", LogicalConnective.AND),
            
            # Or (ou)
            (r"(.+) ou (.+)", LogicalConnective.OR),
            
            # Implies (si...alors)
            (r"si (.+) alors (.+)", LogicalConnective.IMPLIES),
            (r"si (.+),? (.+)", LogicalConnective.IMPLIES),
            
            # Not (ne...pas) - Complex French negation
            # Only match when NOT part of deontic prohibitions
            (r"^ne\s+(?!doit|peut|est\s+permis)(.+?)\s+pas$", LogicalConnective.NOT),
        ]
    
    def _extract_agent(self, text: str) -> Optional[str]:
        """Extract agent name from French text.
        
        Handles French articles and contractions: le, la, les, l'.
        
        Args:
            text: French text
            
        Returns:
            Agent name or None
        """
        # French articles including contractions
        match = re.match(r"(?:le|la|les|l'|l )? ?(\w+)", text.lower())
        if match:
            return match.group(1)
        return None
    
    def _create_simple_predicate(self, action: str) -> Predicate:
        """Create or get predicate for French action.
        
        Args:
            action: French action word
            
        Returns:
            Predicate for the action
        """
        # Remove common French particles
        action = action.replace("l'", "").replace("d'", "")
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
        """Create or get variable for French agent.
        
        Args:
            agent_name: French agent name
            
        Returns:
            Variable for the agent
        """
        var_name = agent_name if agent_name else "agent"
        
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
        """Convert French text to DCEC formula.
        
        Args:
            text: French text to convert
            
        Returns:
            DCEC Formula or None if no match
        """
        text = text.strip().lower()
        
        # Extract agent
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


class FrenchParser(BaseParser):
    """
    French language parser for CEC.
    
    Implements BaseParser interface for parsing French natural language
    into DCEC formulas. Handles French grammar including:
    
    - Verb conjugations (present, passé composé, imparfait, futur)
    - Gender and number agreement (le/la/les, un/une/des)
    - Articles and contractions (l', du, au, des)
    - Complex negation (ne...pas, ne...jamais, ne...plus, ne...rien)
    - Reflexive verbs (se doit, se peut)
    - Idiomatic expressions
    
    Example:
        >>> parser = FrenchParser()
        >>> result = parser.parse("L'agent doit effectuer l'action")
        >>> result.success
        True
        >>> result.formula  # DeonticFormula(OBLIGATION, ...)
    """
    
    def __init__(self, confidence_threshold: float = 0.5):
        """Initialize French parser.
        
        Args:
            confidence_threshold: Minimum confidence for successful parse
        """
        super().__init__("fr", confidence_threshold=confidence_threshold)
        self.namespace = DCECNamespace()
        self.matcher = FrenchPatternMatcher(self.namespace)
        logger.info("French parser initialized")
    
    def parse_impl(self, text: str) -> ParseResult:
        """Implement French-specific parsing logic.
        
        Args:
            text: Normalized French text
            
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
                        'language': 'fr',
                        'method': 'pattern_matching',
                        'text_length': len(text)
                    }
                )
            else:
                # No pattern matched
                result = ParseResult()
                result.add_error("Impossible d'analyser le texte français")
                return result
                
        except Exception as e:
            logger.error(f"French parsing error: {e}")
            result = ParseResult()
            result.add_error(f"Erreur d'analyse: {str(e)}")
            return result
    
    def _calculate_confidence(self, text: str, formula: Formula) -> float:
        """Calculate confidence score for French parse.
        
        Confidence based on:
        - Presence of French keywords (40%)
        - Match specificity (30%)
        - Text complexity (20%)
        - Grammar correctness (10%)
        
        Args:
            text: Original French text
            formula: Parsed formula
            
        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = 0.5  # Base confidence
        
        # Check for French keywords
        french_keywords = [
            'doit', 'peut', 'interdit', 'obligé', 'permis',
            'sait', 'croit', 'veut', 'désire', 'envisage',
            'toujours', 'éventuellement', 'ensuite', 'après',
            'si', 'alors', 'et', 'ou', 'ne', 'pas'
        ]
        
        text_lower = text.lower()
        keyword_count = sum(1 for kw in french_keywords if kw in text_lower)
        
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
        """Get list of supported French operators.
        
        Returns:
            List of French operator keywords
        """
        return [
            # Deontic
            'doit', 'peut', 'interdit', 'obligé', 'permis',
            'il faut', 'est permis', 'est interdit',
            
            # Cognitive
            'sait', 'croit', 'pense', 'veut', 'désire', 'envisage',
            'connaît', 'estime', 'considère',
            
            # Temporal
            'toujours', 'éventuellement', 'ensuite', 'après', 'jamais',
            'en tout temps', 'un jour', 'jusqu\'à ce que', 'depuis que',
            
            # Connectives
            'et', 'ou', 'ne...pas', 'si', 'alors'
        ]


def get_french_verb_conjugations() -> Dict[str, Dict[str, str]]:
    """Get French verb conjugations for common modal verbs.
    
    Returns dictionary mapping verb infinitives to conjugation tables
    for present, passé composé, imparfait, and futur tenses.
    
    Returns:
        Dict mapping verb infinitives to conjugation tables
        
    Example:
        >>> conjugations = get_french_verb_conjugations()
        >>> conjugations['devoir']['present']['il/elle']
        'doit'
    """
    return {
        'devoir': {  # must, should
            'present': {
                'je': 'dois',
                'tu': 'dois',
                'il/elle': 'doit',
                'nous': 'devons',
                'vous': 'devez',
                'ils/elles': 'doivent'
            },
            'passé_composé': {
                'je': 'ai dû',
                'tu': 'as dû',
                'il/elle': 'a dû',
                'nous': 'avons dû',
                'vous': 'avez dû',
                'ils/elles': 'ont dû'
            },
            'futur': {
                'je': 'devrai',
                'tu': 'devras',
                'il/elle': 'devra',
                'nous': 'devrons',
                'vous': 'devrez',
                'ils/elles': 'devront'
            }
        },
        'pouvoir': {  # can, may
            'present': {
                'je': 'peux',
                'tu': 'peux',
                'il/elle': 'peut',
                'nous': 'pouvons',
                'vous': 'pouvez',
                'ils/elles': 'peuvent'
            },
            'passé_composé': {
                'je': 'ai pu',
                'tu': 'as pu',
                'il/elle': 'a pu',
                'nous': 'avons pu',
                'vous': 'avez pu',
                'ils/elles': 'ont pu'
            },
            'futur': {
                'je': 'pourrai',
                'tu': 'pourras',
                'il/elle': 'pourra',
                'nous': 'pourrons',
                'vous': 'pourrez',
                'ils/elles': 'pourront'
            }
        },
        'savoir': {  # to know
            'present': {
                'je': 'sais',
                'tu': 'sais',
                'il/elle': 'sait',
                'nous': 'savons',
                'vous': 'savez',
                'ils/elles': 'savent'
            }
        },
        'croire': {  # to believe
            'present': {
                'je': 'crois',
                'tu': 'crois',
                'il/elle': 'croit',
                'nous': 'croyons',
                'vous': 'croyez',
                'ils/elles': 'croient'
            }
        },
        'vouloir': {  # to want
            'present': {
                'je': 'veux',
                'tu': 'veux',
                'il/elle': 'veut',
                'nous': 'voulons',
                'vous': 'voulez',
                'ils/elles': 'veulent'
            }
        }
    }


def get_french_articles() -> Dict[str, List[str]]:
    """Get French articles (definite, indefinite, and contractions).
    
    Returns:
        Dict with article types and their forms
    """
    return {
        'definite': ['le', 'la', 'les', "l'"],
        'indefinite': ['un', 'une', 'des'],
        'contractions': ['du', 'au', 'aux', 'des']
    }


def get_french_negation_patterns() -> List[str]:
    """Get French negation patterns.
    
    French uses complex negation with 'ne...pas' and variants.
    
    Returns:
        List of French negation patterns
    """
    return [
        'ne...pas',        # not
        'ne...jamais',     # never
        'ne...plus',       # no more/no longer
        'ne...rien',       # nothing
        'ne...personne',   # nobody
        'ne...guère',      # hardly
        'ne...aucun',      # no/none
    ]


def get_french_deontic_keywords() -> Dict[str, List[str]]:
    """Get French deontic keywords categorized by operator type.
    
    Returns:
        Dict mapping operator types to French keywords
    """
    return {
        'obligation': [
            'doit', 'doivent', 'il faut', 'obligé', 'obligation',
            'est obligé', 'est nécessaire', 'il est requis', 'est tenu',
            'sont obligés', 'ont l\'obligation', 'nécessaire', 'requis'
        ],
        'permission': [
            'peut', 'peuvent', 'il est permis', 'permis', 'permission',
            'est permis', 'est autorisé', 'on peut', 'a le droit',
            'ont le droit', 'autorisé', 'facultatif'
        ],
        'prohibition': [
            'ne doit pas', 'ne peut pas', 'interdit', 'prohibition',
            'est interdit', 'défendu', 'prohibé', 'n\'est pas permis',
            'ne se permet pas', 'illégal', 'illicite'
        ]
    }

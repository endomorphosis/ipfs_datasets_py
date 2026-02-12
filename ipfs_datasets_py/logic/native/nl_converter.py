"""
Native Python 3 natural language converter for DCEC formulas.

This module provides a pure Python 3 implementation of natural language
to DCEC conversion. It supports both grammar-based parsing (Phase 4C)
and pattern-based fallback for robustness.
"""

from typing import List, Dict, Optional, Tuple, Pattern, Any
from dataclasses import dataclass
import re
import logging

from .dcec_core import (
    Formula,
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    QuantifiedFormula,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective,
    Predicate,
    Variable,
    VariableTerm,
    Sort,
)
from .dcec_namespace import DCECNamespace

# Define logger before optional imports that might use it
logger = logging.getLogger(__name__)

try:
    from .dcec_english_grammar import DCECEnglishGrammar
    GRAMMAR_AVAILABLE = True
except ImportError:
    GRAMMAR_AVAILABLE = False
    logger.warning("Grammar-based parsing not available, using pattern-based fallback only")

try:
    from beartype import beartype
except ImportError:
    def beartype(func):
        return func

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Result of converting English to DCEC."""
    english_text: str
    dcec_formula: Optional[Formula] = None
    success: bool = False
    error_message: Optional[str] = None
    confidence: float = 0.0
    parse_method: str = "pattern_matching"


class PatternMatcher:
    """Simple pattern-based converter using regex."""
    
    def __init__(self, namespace: DCECNamespace):
        """
        Initialize the pattern matcher.
        
        Args:
            namespace: DCEC namespace for creating formulas
        """
        self.namespace = namespace
        self._init_patterns()
    
    def _init_patterns(self):
        """Initialize conversion patterns."""
        # Deontic patterns
        self.deontic_patterns = [
            (r"(?:must|should|ought to|required to|obligated to) (\w+)", DeonticOperator.OBLIGATION),
            (r"(?:may|can|allowed to|permitted to) (\w+)", DeonticOperator.PERMISSION),
            (r"(?:must not|should not|forbidden to|prohibited from) (\w+)", DeonticOperator.PROHIBITION),
        ]
        
        # Cognitive patterns
        self.cognitive_patterns = [
            (r"(?:believes that|thinks that) (.+)", CognitiveOperator.BELIEF),
            (r"(?:knows that) (.+)", CognitiveOperator.KNOWLEDGE),
            (r"(?:intends to|plans to) (\w+)", CognitiveOperator.INTENTION),
            (r"(?:desires to|wants to) (\w+)", CognitiveOperator.DESIRE),
            (r"(?:has goal to|aims to) (\w+)", CognitiveOperator.GOAL),
        ]
        
        # Temporal patterns
        self.temporal_patterns = [
            (r"always (.+)", TemporalOperator.ALWAYS),
            (r"eventually (.+)", TemporalOperator.EVENTUALLY),
            (r"next (.+)", TemporalOperator.NEXT),
        ]
        
        # Logical connectives
        self.connective_patterns = [
            (r"(.+) and (.+)", LogicalConnective.AND),
            (r"(.+) or (.+)", LogicalConnective.OR),
            (r"if (.+) then (.+)", LogicalConnective.IMPLIES),
            (r"not (.+)", LogicalConnective.NOT),
        ]
    
    def _extract_agent(self, text: str) -> Optional[str]:
        """Extract agent name from text."""
        # Look for "the X" or just "X" at the beginning
        match = re.match(r"(?:the )?(\w+)", text.lower())
        if match:
            return match.group(1)
        return None
    
    def _create_simple_predicate(self, action: str) -> Predicate:
        """Create or get a predicate for an action."""
        pred_name = action.replace(" ", "_")
        
        # Check if predicate exists
        existing = self.namespace.get_predicate(pred_name)
        if existing:
            return existing
        
        # Create new predicate with one Agent argument
        try:
            return self.namespace.add_predicate(pred_name, ["Agent"])
        except ValueError:
            # If it already exists, get it
            return self.namespace.get_predicate(pred_name)
    
    def _create_agent_variable(self, agent_name: Optional[str] = None) -> Variable:
        """Create or get a variable for an agent."""
        var_name = agent_name if agent_name else "agent"
        
        # Check if variable exists
        existing = self.namespace.get_variable(var_name)
        if existing:
            return existing
        
        # Create new variable
        try:
            return self.namespace.add_variable(var_name, "Agent")
        except ValueError:
            # If it already exists, get it
            return self.namespace.get_variable(var_name)
    
    @beartype
    def convert(self, text: str) -> Optional[Formula]:
        """
        Convert English text to DCEC formula using pattern matching.
        
        Args:
            text: English text to convert
            
        Returns:
            DCEC Formula or None if no match
        """
        text = text.strip().lower()
        
        # Extract agent if present
        agent_name = self._extract_agent(text)
        
        # Try deontic patterns
        for pattern, operator in self.deontic_patterns:
            match = re.search(pattern, text)
            if match:
                action = match.group(1)
                pred = self._create_simple_predicate(action)
                agent_var = self._create_agent_variable(agent_name)
                
                base_formula = AtomicFormula(pred, [VariableTerm(agent_var)])
                return DeonticFormula(operator, base_formula)
        
        # Try cognitive patterns
        for pattern, operator in self.cognitive_patterns:
            match = re.search(pattern, text)
            if match:
                content = match.group(1)
                agent_var = self._create_agent_variable(agent_name)
                
                # Recursively convert the content
                inner_formula = self.convert(content)
                if inner_formula:
                    return CognitiveFormula(operator, VariableTerm(agent_var), inner_formula)
                else:
                    # Create simple predicate from content
                    pred = self._create_simple_predicate(content)
                    inner_formula = AtomicFormula(pred, [VariableTerm(agent_var)])
                    return CognitiveFormula(operator, VariableTerm(agent_var), inner_formula)
        
        # Try temporal patterns
        for pattern, operator in self.temporal_patterns:
            match = re.search(pattern, text)
            if match:
                content = match.group(1)
                inner_formula = self.convert(content)
                if inner_formula:
                    return TemporalFormula(operator, inner_formula)
        
        # Try connectives
        for pattern, connective in self.connective_patterns:
            match = re.search(pattern, text)
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
        
        # If no pattern matched, create simple predicate
        pred = self._create_simple_predicate(text)
        agent_var = self._create_agent_variable(agent_name)
        return AtomicFormula(pred, [VariableTerm(agent_var)])


class NaturalLanguageConverter:
    """
    Natural language to DCEC converter.
    
    Provides a clean API compatible with the EngDCECWrapper interface.
    """
    
    def __init__(self):
        """Initialize the converter."""
        self.namespace = DCECNamespace()
        self.matcher = PatternMatcher(self.namespace)
        self.conversion_history: List[ConversionResult] = []
        self._initialized = True
    
    def initialize(self) -> bool:
        """Initialize the converter (always succeeds for native implementation)."""
        self._initialized = True
        logger.info("Native NL converter initialized")
        return True
    
    @beartype
    def convert_to_dcec(self, text: str) -> ConversionResult:
        """
        Convert English text to DCEC formula.
        
        Args:
            text: English text to convert
            
        Returns:
            ConversionResult with formula or error
        """
        try:
            formula = self.matcher.convert(text)
            
            result = ConversionResult(
                english_text=text,
                dcec_formula=formula,
                success=True,
                confidence=0.7,  # Pattern matching has medium confidence
                parse_method="pattern_matching",
            )
            
            self.conversion_history.append(result)
            logger.info(f"Converted: '{text}' -> {formula.to_string()}")
            return result
            
        except Exception as e:
            logger.error(f"Error converting text: {e}")
            result = ConversionResult(
                english_text=text,
                success=False,
                error_message=str(e),
                confidence=0.0
            )
            self.conversion_history.append(result)
            return result
    
    @beartype
    def convert_from_dcec(self, formula: Formula) -> str:
        """
        Convert DCEC formula to English (linearization).
        
        Args:
            formula: DCEC formula to convert
            
        Returns:
            English text
        """
        # Simple template-based generation
        if isinstance(formula, DeonticFormula):
            inner = self.convert_from_dcec(formula.formula)
            if formula.operator == DeonticOperator.OBLIGATION:
                return f"must {inner}"
            elif formula.operator == DeonticOperator.PERMISSION:
                return f"may {inner}"
            elif formula.operator == DeonticOperator.PROHIBITION:
                return f"must not {inner}"
            else:
                return f"{formula.operator.value}({inner})"
        
        elif isinstance(formula, CognitiveFormula):
            inner = self.convert_from_dcec(formula.formula)
            if formula.operator == CognitiveOperator.BELIEF:
                return f"{formula.agent} believes that {inner}"
            elif formula.operator == CognitiveOperator.KNOWLEDGE:
                return f"{formula.agent} knows that {inner}"
            elif formula.operator == CognitiveOperator.INTENTION:
                return f"{formula.agent} intends to {inner}"
            else:
                return f"{formula.operator.value}({formula.agent}, {inner})"
        
        elif isinstance(formula, TemporalFormula):
            inner = self.convert_from_dcec(formula.formula)
            if formula.operator == TemporalOperator.ALWAYS:
                return f"always {inner}"
            elif formula.operator == TemporalOperator.EVENTUALLY:
                return f"eventually {inner}"
            elif formula.operator == TemporalOperator.NEXT:
                return f"next {inner}"
            else:
                return f"{formula.operator.value}({inner})"
        
        elif isinstance(formula, ConnectiveFormula):
            if formula.connective == LogicalConnective.NOT:
                inner = self.convert_from_dcec(formula.formulas[0])
                return f"not {inner}"
            elif formula.connective == LogicalConnective.AND:
                parts = [self.convert_from_dcec(f) for f in formula.formulas]
                return " and ".join(parts)
            elif formula.connective == LogicalConnective.OR:
                parts = [self.convert_from_dcec(f) for f in formula.formulas]
                return " or ".join(parts)
            elif formula.connective == LogicalConnective.IMPLIES:
                p1 = self.convert_from_dcec(formula.formulas[0])
                p2 = self.convert_from_dcec(formula.formulas[1])
                return f"if {p1} then {p2}"
            else:
                return formula.to_string()
        
        elif isinstance(formula, AtomicFormula):
            # Simple case: just the predicate name
            return formula.predicate.name.replace("_", " ")
        
        else:
            # Fallback to formula string
            return formula.to_string()
    
    def get_conversion_statistics(self) -> Dict[str, Any]:
        """Get statistics about conversions."""
        if not self.conversion_history:
            return {"total_conversions": 0}
        
        successful = sum(1 for c in self.conversion_history if c.success)
        
        return {
            "total_conversions": len(self.conversion_history),
            "successful": successful,
            "failed": len(self.conversion_history) - successful,
            "success_rate": successful / len(self.conversion_history) if self.conversion_history else 0.0,
            "average_confidence": sum(c.confidence for c in self.conversion_history) / len(self.conversion_history)
        }
    
    def __repr__(self) -> str:
        return f"NaturalLanguageConverter(conversions={len(self.conversion_history)})"


# === Phase 4C: Grammar-Based Enhancement ===

def create_enhanced_nl_converter(use_grammar: bool = True) -> 'NaturalLanguageConverter':
    """Factory function to create an enhanced NL converter with grammar support.
    
    Args:
        use_grammar: Whether to enable grammar-based parsing (default: True)
        
    Returns:
        Enhanced NaturalLanguageConverter with grammar support
    """
    converter = NaturalLanguageConverter()
    
    # Add grammar-based parsing if available
    if use_grammar and GRAMMAR_AVAILABLE:
        try:
            from .dcec_english_grammar import create_dcec_grammar
            converter.grammar = create_dcec_grammar()
            converter.use_grammar = True
            logger.info("Enhanced NL converter created with grammar support")
        except Exception as e:
            logger.warning(f"Failed to add grammar support: {e}")
            converter.use_grammar = False
            converter.grammar = None
    else:
        converter.use_grammar = False
        converter.grammar = None
    
    return converter


def parse_with_grammar(text: str) -> Optional[Formula]:
    """Parse English text using grammar-based parsing.
    
    Args:
        text: English text to parse
        
    Returns:
        DCEC Formula or None if parsing fails
    """
    if not GRAMMAR_AVAILABLE:
        logger.warning("Grammar-based parsing not available")
        return None
    
    try:
        from .dcec_english_grammar import create_dcec_grammar
        grammar = create_dcec_grammar()
        return grammar.parse_to_dcec(text)
    except Exception as e:
        logger.error(f"Grammar parsing failed: {e}")
        return None


def linearize_with_grammar(formula: Formula) -> Optional[str]:
    """Convert DCEC formula to English using grammar-based linearization.
    
    Args:
        formula: DCEC Formula to convert
        
    Returns:
        English text or None if linearization fails
    """
    if not GRAMMAR_AVAILABLE:
        logger.warning("Grammar-based linearization not available")
        return None
    
    try:
        from .dcec_english_grammar import create_dcec_grammar
        grammar = create_dcec_grammar()
        return grammar.formula_to_english(formula)
    except Exception as e:
        logger.error(f"Grammar linearization failed: {e}")
        return None

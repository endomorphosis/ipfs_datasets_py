"""
Symbolic Logic Primitives Module

This module extends SymbolicAI with custom logic-specific primitives for enhanced
logical operations and natural language to logic conversion.
"""

import logging
import re
from typing import List, Dict, Any, Optional, Union
try:
    from beartype import beartype  # type: ignore
except ImportError:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func
from dataclasses import dataclass

# Configure logging
logger = logging.getLogger(__name__)

# Conditional imports based on SymbolicAI availability
try:
    from symai import Symbol
    from symai.ops.primitives import Primitive
    import symai.core as core
    SYMBOLIC_AI_AVAILABLE = True
except (ImportError, SystemExit):
    SYMBOLIC_AI_AVAILABLE = False
    logger.warning("SymbolicAI not available. Logic primitives will use fallback implementations.")
    
    # Mock classes for development without SymbolicAI
    class Symbol:
        def __init__(self, value: str, semantic: bool = False):
            self.value = value
            self._semantic = semantic
        
        def _to_type(self, result):
            return Symbol(str(result), self._semantic)
    
    class Primitive:
        pass
    
    class core:
        @staticmethod
        def interpret(prompt: str):
            def decorator(func):
                def wrapper(*args, **kwargs):
                    return f"Mock result for: {prompt}"
                return wrapper
            return decorator
        
        @staticmethod
        def logic(operator: str):
            def decorator(func):
                def wrapper(*args, **kwargs):
                    return f"Mock logic operation: {operator}"
                return wrapper
            return decorator


@dataclass
class LogicalStructure:
    """Represents the logical structure of a statement."""
    quantifiers: List[str]
    variables: List[str]
    predicates: List[str]
    connectives: List[str]
    operators: List[str]
    confidence: float


class LogicPrimitives(Primitive):
    """
    Custom primitives for logical operations using SymbolicAI.
    
    This class extends SymbolicAI's primitive operations with logic-specific
    functionality for natural language to FOL conversion, logical reasoning,
    and formula manipulation.
    """
    
    @beartype
    def to_fol(self, output_format: str = "symbolic") -> 'Symbol':
        """
        Convert natural language to First-Order Logic.
        
        Args:
            output_format: Format for the output ("symbolic", "prolog", "tptp")
            
        Returns:
            Symbol containing the FOL formula
        """
        if not SYMBOLIC_AI_AVAILABLE:
            return self._fallback_to_fol(output_format)
        
        @core.interpret(prompt="""
        Convert the given natural language statement to a formal First-Order Logic (FOL) formula.
        
        Instructions:
        1. Identify quantifiers (∀ for universal 'all/every', ∃ for existential 'some/exists')
        2. Extract predicates and relationships 
        3. Determine logical connectives (∧ for 'and', ∨ for 'or', → for 'implies', ¬ for 'not')
        4. Use proper FOL syntax with variables (x, y, z) and predicates
        5. Structure the formula logically
        
        Examples:
        - "All cats are animals" → ∀x (Cat(x) → Animal(x))
        - "Some birds can fly" → ∃x (Bird(x) ∧ CanFly(x))
        - "If it rains, then the ground is wet" → Rain → WetGround
        
        Return only the FOL formula in the requested format.
        """)
        def _convert_to_fol(text):
            pass
        
        try:
            result = _convert_to_fol(self)
            return self._to_type(result)
        except Exception as e:
            logger.error(f"Failed to convert to FOL: {e}")
            return self._fallback_to_fol(output_format)
    
    def _fallback_to_fol(self, output_format: str) -> 'Symbol':
        """Fallback FOL conversion without SymbolicAI."""
        import re as _re
        text = self.value.lower()
        
        # Simple pattern-based conversion
        if "all " in text or "every " in text:
            # Universal quantification pattern: "All/Every X are Y"
            parts = text.split(" are ")
            if len(parts) == 2:
                subject = parts[0].replace("all ", "").replace("every ", "").strip()
                predicate = parts[1].strip()
                formula = f"∀x ({subject.capitalize()}(x) → {predicate.capitalize()}(x))"
            else:
                # "All X [verb] Y" — extract subject after quantifier
                m = _re.match(r'(?:all|every)\s+(\w+)\s+(.*)', text)
                if m:
                    subj = m.group(1).capitalize()
                    rest = m.group(2).strip().replace(' ', '_')
                    formula = f"∀x ({subj}(x) → {rest.capitalize()}(x))"
                else:
                    formula = f"∀x Statement(x)"
        elif "some " in text or "exists " in text or "there " in text:
            # Existential quantification pattern
            parts = text.split(" are ")
            if len(parts) == 2:
                subject = parts[0].replace("some ", "").replace("exists ", "").strip()
                predicate = parts[1].strip()
                formula = f"∃x ({subject.capitalize()}(x) ∧ {predicate.capitalize()}(x))"
            else:
                # "Some X can/is/does Y" — extract subject and predicate
                m = _re.match(r'(?:some|there\s+(?:is|are))\s+(\w+)\s+(.*)', text)
                if m:
                    subj = m.group(1).capitalize()
                    rest = m.group(2).strip().replace(' ', '_')
                    formula = f"∃x ({subj}(x) ∧ {rest.capitalize()}(x))"
                else:
                    formula = f"∃x Statement(x)"
        else:
            # Simple predicate
            formula = f"Statement({text.replace(' ', '_')})"
        
        # Apply format conversions
        if output_format == "prolog":
            formula = formula.replace('∀', 'forall')
            formula = formula.replace('∃', 'exists')
            formula = formula.replace('→', ':-')
            formula = formula.replace('∧', ',')
            formula = formula.replace('∨', ';')
        elif output_format == "tptp":
            formula = formula.replace('∀', '!')
            formula = formula.replace('∃', '?')
            formula = formula.replace('→', '=>')
            formula = formula.replace('∧', '&')
            formula = formula.replace('∨', '|')
            formula = f"fof(statement, axiom, {formula})."
        
        return self._to_type(formula)
    
    @beartype
    def extract_quantifiers(self) -> 'Symbol':
        """
        Extract quantifiers from natural language text.
        
        Returns:
            Symbol containing identified quantifiers
        """
        if not SYMBOLIC_AI_AVAILABLE:
            return self._fallback_extract_quantifiers()
        
        @core.interpret(prompt="""
        Extract all quantifiers from the given text. Look for:
        - Universal quantifiers: all, every, each, always, never
        - Existential quantifiers: some, exists, there is/are, at least one
        - Numerical quantifiers: many, few, most, several
        
        Return them as a comma-separated list. If no quantifiers found, return 'none'.
        """)
        def _extract_quantifiers(text):
            pass
        
        try:
            result = _extract_quantifiers(self)
            return self._to_type(result)
        except Exception as e:
            logger.error(f"Failed to extract quantifiers: {e}")
            return self._fallback_extract_quantifiers()
    
    def _fallback_extract_quantifiers(self) -> 'Symbol':
        """Fallback quantifier extraction using regex."""
        import re
        
        quantifier_patterns = {
            'universal': r'\b(all|every|each|always|never)\b',
            'existential': r'\b(some|exists?|there\s+(is|are)|at\s+least\s+one)\b',
            'numerical': r'\b(many|few|most|several|majority)\b'
        }
        
        found_quantifiers = []
        for qtype, pattern in quantifier_patterns.items():
            matches = re.findall(pattern, self.value, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    match = ' '.join(match)
                found_quantifiers.append(f"{qtype}:{match}")
        
        result = ', '.join(found_quantifiers) if found_quantifiers else 'none'
        return self._to_type(result)
    
    @beartype 
    def extract_predicates(self) -> 'Symbol':
        """
        Extract predicates and relationships from text.
        
        Returns:
            Symbol containing identified predicates
        """
        if not SYMBOLIC_AI_AVAILABLE:
            return self._fallback_extract_predicates()
        
        @core.interpret(prompt="""
        Extract all predicates, verbs, and relationships from the text. Look for:
        - Action verbs: run, fly, study, love, hate
        - State verbs: is, are, has, have, can, must
        - Relationships: belongs to, part of, loves, studies
        
        Return them as a comma-separated list. Focus on the main predicates.
        """)
        def _extract_predicates(text):
            pass
        
        try:
            result = _extract_predicates(self)
            return self._to_type(result)
        except Exception as e:
            logger.error(f"Failed to extract predicates: {e}")
            return self._fallback_extract_predicates()
    
    def _fallback_extract_predicates(self) -> 'Symbol':
        """Fallback predicate extraction using regex."""
        import re
        
        # Common predicate patterns
        predicate_patterns = [
            r'\b(is|are|was|were|being|been)\b',
            r'\b(has|have|had|having)\b', 
            r'\b(can|could|cannot|must|should|will|would)\b',
            r'\b(loves?|hates?|likes?|enjoys?)\b',
            r'\b(studies?|works?|plays?|runs?|flies?|swims?)\b',
            r'\b(belongs?|owns?|contains?|includes?)\b'
        ]
        
        found_predicates = []
        for pattern in predicate_patterns:
            matches = re.findall(pattern, self.value, re.IGNORECASE)
            found_predicates.extend(matches)
        
        # Remove duplicates while preserving order
        unique_predicates = list(dict.fromkeys(found_predicates))
        result = ', '.join(unique_predicates) if unique_predicates else 'none'
        return self._to_type(result)
    
    @beartype
    def logical_and(self, other: 'Symbol') -> 'Symbol':
        """
        Semantic logical conjunction.
        
        Args:
            other: Another Symbol to combine with logical AND
            
        Returns:
            Symbol representing the logical conjunction
        """
        if not SYMBOLIC_AI_AVAILABLE:
            return self._fallback_logical_and(other)
        
        @core.logic(operator='and')
        def _logical_and(a: str, b: str):
            pass
        
        try:
            result = _logical_and(self, other)
            return self._to_type(result)
        except Exception as e:
            logger.error(f"Failed logical AND operation: {e}")
            return self._fallback_logical_and(other)
    
    def _fallback_logical_and(self, other: 'Symbol') -> 'Symbol':
        """Fallback logical AND without SymbolicAI."""
        combined = f"({self.value}) ∧ ({other.value})"
        return self._to_type(combined)
    
    @beartype
    def logical_or(self, other: 'Symbol') -> 'Symbol':
        """
        Semantic logical disjunction.
        
        Args:
            other: Another Symbol to combine with logical OR
            
        Returns:
            Symbol representing the logical disjunction
        """
        if not SYMBOLIC_AI_AVAILABLE:
            return self._fallback_logical_or(other)
        
        @core.logic(operator='or')
        def _logical_or(a: str, b: str):
            pass
        
        try:
            result = _logical_or(self, other)
            return self._to_type(result)
        except Exception as e:
            logger.error(f"Failed logical OR operation: {e}")
            return self._fallback_logical_or(other)
    
    def _fallback_logical_or(self, other: 'Symbol') -> 'Symbol':
        """Fallback logical OR without SymbolicAI."""
        combined = f"({self.value}) ∨ ({other.value})"
        return self._to_type(combined)
    
    @beartype
    def implies(self, other: 'Symbol') -> 'Symbol':
        """
        Logical implication.
        
        Args:
            other: Symbol representing the conclusion
            
        Returns:
            Symbol representing the implication
        """
        if not SYMBOLIC_AI_AVAILABLE:
            return self._fallback_implies(other)
        
        @core.interpret(prompt="""
        Express a logical implication relationship 'if A then B' between two statements.
        Create a natural language implication or formal logic notation.
        """)
        def _implies(premise, conclusion):
            pass
        
        try:
            result = _implies(self, other)
            return self._to_type(result)
        except Exception as e:
            logger.error(f"Failed implication operation: {e}")
            return self._fallback_implies(other)
    
    def _fallback_implies(self, other: 'Symbol') -> 'Symbol':
        """Fallback implication without SymbolicAI."""
        implication = f"({self.value}) → ({other.value})"
        return self._to_type(implication)
    
    @beartype
    def negate(self) -> 'Symbol':
        """
        Logical negation.
        
        Returns:
            Symbol representing the negation
        """
        if not SYMBOLIC_AI_AVAILABLE:
            return self._fallback_negate()
        
        @core.interpret(prompt="""
        Create the logical negation of the given statement.
        Add 'not' or use negation symbols appropriately.
        """)
        def _negate(statement):
            pass
        
        try:
            result = _negate(self)
            return self._to_type(result)
        except Exception as e:
            logger.error(f"Failed negation operation: {e}")
            return self._fallback_negate()
    
    def _fallback_negate(self) -> 'Symbol':
        """Fallback negation without SymbolicAI."""
        negated = f"¬({self.value})"
        return self._to_type(negated)
    
    @beartype
    def analyze_logical_structure(self) -> 'Symbol':
        """
        Analyze the logical structure of the statement.
        
        Returns:
            Symbol containing the analysis
        """
        if not SYMBOLIC_AI_AVAILABLE:
            return self._fallback_analyze_structure()
        
        @core.interpret(prompt="""
        Analyze the logical structure of the given statement. Identify:
        1. Type of logical statement (universal, existential, conditional, etc.)
        2. Main subject and predicate
        3. Logical connectives present
        4. Variables and constants
        5. Overall complexity level
        
        Provide a structured analysis.
        """)
        def _analyze_structure(text):
            pass
        
        try:
            result = _analyze_structure(self)
            return self._to_type(result)
        except Exception as e:
            logger.error(f"Failed structure analysis: {e}")
            return self._fallback_analyze_structure()
    
    def _fallback_analyze_structure(self) -> 'Symbol':
        """Fallback structure analysis."""
        import re
        
        analysis = {
            "type": "simple_statement",
            "has_quantifiers": bool(re.search(r'\b(all|some|every|exists)\b', self.value, re.IGNORECASE)),
            "has_connectives": bool(re.search(r'\b(and|or|if|then|not)\b', self.value, re.IGNORECASE)),
            "word_count": len(self.value.split()),
            "complexity": "low" if len(self.value.split()) < 10 else "medium"
        }
        
        return self._to_type(str(analysis))
    
    @beartype
    def simplify_logic(self) -> 'Symbol':
        """
        Simplify logical expressions.
        
        Returns:
            Symbol containing simplified logic
        """
        if not SYMBOLIC_AI_AVAILABLE:
            return self._fallback_simplify()
        
        @core.interpret(prompt="""
        Simplify the given logical expression by:
        1. Removing redundant terms
        2. Applying logical equivalences
        3. Reducing complex nested expressions
        4. Making the expression more readable
        
        Return the simplified version.
        """)
        def _simplify(expression):
            pass
        
        try:
            result = _simplify(self)
            return self._to_type(result)
        except Exception as e:
            logger.error(f"Failed simplification: {e}")
            return self._fallback_simplify()
    
    def _fallback_simplify(self) -> 'Symbol':
        """Fallback simplification."""
        # Basic simplification - remove extra spaces and parentheses
        simplified = re.sub(r'\s+', ' ', self.value.strip())
        simplified = re.sub(r'\(\s*([^)]+)\s*\)', r'(\1)', simplified)
        return self._to_type(simplified)


# Extend Symbol class with logic primitives if SymbolicAI is available
if SYMBOLIC_AI_AVAILABLE:
    try:
        # Dynamically add LogicPrimitives methods to Symbol class
        for method_name in dir(LogicPrimitives):
            is_public = not method_name.startswith('_')
            is_fallback = method_name.startswith('_fallback_')
            if (is_public or is_fallback) and callable(getattr(LogicPrimitives, method_name)):
                method = getattr(LogicPrimitives, method_name)
                setattr(Symbol, method_name, method)
        
        logger.info("Successfully extended Symbol class with LogicPrimitives")
    except Exception as e:
        logger.error(f"Failed to extend Symbol class: {e}")


def create_logic_symbol(text: str, semantic: bool = True) -> Symbol:
    """
    Create a Symbol with logic primitives enabled.
    
    Args:
        text: Text content for the symbol
        semantic: Whether to enable semantic mode
        
    Returns:
        Symbol with logic primitive methods available
    """
    symbol = Symbol(text, semantic=semantic)
    
    # Ensure the Symbol class itself has logic primitive methods so that
    # any Symbol returned by internal methods (e.g. _to_type) also has them.
    if not hasattr(Symbol, 'to_fol'):
        for method_name in dir(LogicPrimitives):
            is_public = not method_name.startswith('_')
            is_fallback = method_name.startswith('_fallback_')
            if (is_public or is_fallback) and callable(getattr(LogicPrimitives, method_name)):
                method = getattr(LogicPrimitives, method_name)
                setattr(Symbol, method_name, method)
    
    return symbol


def get_available_primitives() -> List[str]:
    """
    Get list of available logic primitive methods.
    
    Returns:
        List of method names
    """
    return [
        'to_fol',
        'extract_quantifiers', 
        'extract_predicates',
        'logical_and',
        'logical_or', 
        'implies',
        'negate',
        'analyze_logical_structure',
        'simplify_logic'
    ]


def test_primitives():
    """Test function for logic primitives."""
    # Test basic symbol creation
    symbol = create_logic_symbol("All cats are animals")
    
    # Test FOL conversion
    fol_result = symbol.to_fol()
    print(f"FOL: {fol_result.value}")
    
    # Test quantifier extraction
    quantifiers = symbol.extract_quantifiers()
    print(f"Quantifiers: {quantifiers.value}")
    
    # Test predicate extraction
    predicates = symbol.extract_predicates()
    print(f"Predicates: {predicates.value}")
    
    # Test logical operations
    symbol2 = create_logic_symbol("Fluffy is a cat")
    combined = symbol.logical_and(symbol2)
    print(f"Combined: {combined.value}")
    
    # Test implication
    implication = symbol2.implies(symbol)
    print(f"Implication: {implication.value}")


if __name__ == "__main__":
    test_primitives()

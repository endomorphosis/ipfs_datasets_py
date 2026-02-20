"""
Symbolic FOL Bridge Module

This module provides the core bridge between SymbolicAI and the existing FOL system,
enabling semantic analysis and enhanced natural language to logic conversion.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Union, Any, Tuple, TYPE_CHECKING
try:
    from beartype import beartype  # type: ignore
except ImportError:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func
if TYPE_CHECKING:
    from symai import Symbol

logger = logging.getLogger(__name__)

_DID_LOG_INIT = False

# Fallback imports when SymbolicAI is not available
try:
    from symai import Symbol, Expression
    SYMBOLIC_AI_AVAILABLE = True
except (ImportError, SystemExit):
    SYMBOLIC_AI_AVAILABLE = False
    logger.warning("SymbolicAI not available. Some features will be limited.")
    
    # Create mock classes for development/testing without SymbolicAI
    class Symbol:
        def __init__(self, value: str, semantic: bool = False):
            self.value = value
            self._semantic = semantic
            
        def query(self, prompt: str) -> str:
            return f"Mock response for: {prompt}"
    
    class Expression:
        pass


@dataclass 
class LogicalComponents:
    """Structure for holding extracted logical components."""
    quantifiers: List[str]
    predicates: List[str]
    entities: List[str]
    logical_connectives: List[str]
    confidence: float
    raw_text: str

    # Dict-like interface so tests can do `field in components` and `components[field]`
    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def __getitem__(self, key: str):
        return getattr(self, key)

    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def keys(self):
        from dataclasses import fields
        return [f.name for f in fields(self)]


@dataclass
class FOLConversionResult:
    """Result of FOL conversion with metadata."""
    fol_formula: str
    components: LogicalComponents
    confidence: float
    reasoning_steps: List[str]
    fallback_used: bool = False
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class SymbolicFOLBridge:
    """
    Bridge between SymbolicAI and existing FOL system.
    
    This class provides the core integration functionality, allowing for
    semantic analysis of natural language text and conversion to FOL formulas
    with enhanced understanding through SymbolicAI.
    """
    
    def __init__(
        self, 
        confidence_threshold: float = 0.7,
        fallback_enabled: bool = True,
        enable_caching: bool = True
    ):
        """
        Initialize the SymbolicFOL Bridge.
        
        Args:
            confidence_threshold: Minimum confidence required for conversion
            fallback_enabled: Whether to fallback to original system on failure
            enable_caching: Whether to cache conversion results
        """
        self.confidence_threshold = confidence_threshold
        self.fallback_enabled = fallback_enabled
        self.enable_caching = enable_caching
        self._cache: Dict[str, FOLConversionResult] = {}
        
        # Initialize fallback components
        self._initialize_fallback_system()

        global _DID_LOG_INIT
        if not _DID_LOG_INIT:
            _DID_LOG_INIT = True
            logger.info(
                f"SymbolicFOLBridge initialized. "
                f"SymbolicAI available: {SYMBOLIC_AI_AVAILABLE}, "
                f"Fallback enabled: {fallback_enabled}"
            )
    
    def _initialize_fallback_system(self):
        """Initialize fallback components from original FOL system."""
        try:
            # Import original FOL tools as fallback
            from ..fol.utils import predicate_extractor
            from ..fol.utils import fol_parser

            self.predicate_extractor = predicate_extractor.extract_predicates
            self.fol_parser = getattr(fol_parser, "parse_fol", None)

            if self.fol_parser is None:
                raise AttributeError("parse_fol not available in fol_parser")

            self.fallback_available = True

        except (ImportError, AttributeError) as e:
            logger.warning(f"Could not import fallback components: {e}")
            self.fallback_available = False
    
    @beartype
    def create_semantic_symbol(self, text: str) -> Union[Symbol, None]:
        """
        Create a semantic symbol from natural language text.
        
        Args:
            text: Natural language text to convert to semantic symbol
            
        Returns:
            Symbol object in semantic mode, or None if creation fails
            
        Raises:
            ValueError: If text is empty or invalid
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        stripped = text.strip()
        # Require at least some meaningful content (at least 2 alphabetic chars)
        alpha_count = sum(1 for c in stripped if c.isalpha())
        if alpha_count < 2:
            raise ValueError("Text cannot be empty")
        
        if not SYMBOLIC_AI_AVAILABLE:
            logger.warning("SymbolicAI not available, creating mock symbol")
            return Symbol(text.strip(), semantic=True)
        
        try:
            symbol = Symbol(text.strip(), semantic=True)
            logger.debug(f"Created semantic symbol for: {text[:50]}...")
            return symbol
            
        except Exception as e:
            logger.error(f"Failed to create semantic symbol: {e}")
            if self.fallback_enabled:
                # Return a mock symbol that can still be processed
                return Symbol(text.strip(), semantic=False)
            return None
    
    @beartype
    def extract_logical_components(self, symbol: Symbol) -> 'LogicalComponents':
        """
        Extract logical components from a semantic symbol.
        
        Args:
            symbol: Symbol object to analyze
            
        Returns:
            LogicalComponents object with extracted elements (also supports dict-like access)
        """
        try:
            if SYMBOLIC_AI_AVAILABLE and hasattr(symbol, 'query'):
                # Use SymbolicAI for sophisticated extraction
                quantifiers_raw = symbol.query(
                    "Extract quantifiers like 'all', 'some', 'every', 'exists', 'for all'. "
                    "Return as comma-separated list or 'none' if no quantifiers found."
                )
                
                predicates_raw = symbol.query(
                    "Extract predicates and relationships like 'is', 'has', 'can', 'loves', 'studies'. "
                    "Return as comma-separated list."
                )
                
                entities_raw = symbol.query(
                    "Extract entities, objects, and concepts like 'cat', 'student', 'bird'. "
                    "Return as comma-separated list."
                )
                
                connectives_raw = symbol.query(
                    "Extract logical connectives like 'and', 'or', 'if...then', 'not'. "
                    "Return as comma-separated list or 'none' if no connectives found."
                )
                
                # Parse the responses
                quantifiers = self._parse_comma_list(quantifiers_raw)
                predicates = self._parse_comma_list(predicates_raw)
                entities = self._parse_comma_list(entities_raw)
                connectives = self._parse_comma_list(connectives_raw)
                
                confidence = 0.85  # High confidence for SymbolicAI extraction
                
            else:
                # Fallback to regex-based extraction
                quantifiers, predicates, entities, connectives = self._fallback_extraction(symbol.value)
                confidence = 0.6  # Lower confidence for fallback
            
            return LogicalComponents(
                quantifiers=quantifiers,
                predicates=predicates,
                entities=entities,
                logical_connectives=connectives,
                confidence=confidence,
                raw_text=symbol.value
            )
            
        except Exception as e:
            logger.error(f"Failed to extract logical components: {e}")
            # Return minimal components from fallback
            quantifiers, predicates, entities, connectives = self._fallback_extraction(symbol.value)
            
            return LogicalComponents(
                quantifiers=quantifiers,
                predicates=predicates,
                entities=entities,
                logical_connectives=connectives,
                confidence=0.3,  # Low confidence due to error
                raw_text=symbol.value
            )
    
    def _parse_comma_list(self, text: str) -> List[str]:
        """Parse comma-separated list from SymbolicAI response."""
        if not text or text.lower().strip() in ['none', 'no', 'empty', '']:
            return []
        
        # Clean and split the response
        items = [item.strip() for item in text.split(',')]
        # Filter out empty strings and common non-answers
        return [item for item in items if item and item.lower() not in ['none', 'no', 'empty']]
    
    def _fallback_extraction(self, text: str) -> Tuple[List[str], List[str], List[str], List[str]]:
        """Fallback extraction using regex patterns."""
        # Simple regex patterns for logical components
        quantifier_patterns = r'\b(all|every|each|some|exists?|for\s+all)\b'
        # Broader predicate pattern: common verbs + verb-like words ending in s/ed/ing
        predicate_patterns = (
            r'\b(is|are|has|have|can|cannot|loves?|studies?|flies?|runs?'
            r'|rains?|takes?|sleeps?|needs?|likes?|knows?|believes?'
            r'|conducts?|melts?|conserves?|requires?|survive?|teaches?|writes?'
            r'|will\s+\w+|must\s+\w+|should\s+\w+)\b'
        )
        # Entity pattern: capitalized words OR nouns after quantifiers/verbs
        entity_patterns = r'\b([A-Z][a-z]+)\b'
        # Also find nouns (words following quantifiers)
        noun_after_quant = r'\b(?:all|every|each|some|exists?)\s+(\w+)\b'
        connective_patterns = r'\b(and|or|not|if|then|implies?|but|however)\b'
        
        quantifiers = [q.lower() for q in re.findall(quantifier_patterns, text, re.IGNORECASE)]
        predicates = [p.lower() for p in re.findall(predicate_patterns, text, re.IGNORECASE)]
        entities = re.findall(entity_patterns, text)
        # Add nouns after quantifiers as entities
        nouns_after_quant = re.findall(noun_after_quant, text, re.IGNORECASE)
        entities.extend([n.capitalize() for n in nouns_after_quant if n.capitalize() not in entities])
        # Also find nouns after "is/are" predicates
        nouns_after_verb = re.findall(r'\b(?:is|are|be|were)\s+([a-z][a-z]+)\b', text, re.IGNORECASE)
        entities.extend([n.capitalize() for n in nouns_after_verb if n.capitalize() not in entities])
        connectives = [c.lower() for c in re.findall(connective_patterns, text, re.IGNORECASE)]
        
        # If no predicates found, extract any word that looks like a verb (fallback)
        if not predicates:
            # Look for words before "," or after "if/when/that" or simple verb heuristic
            verb_fallback = re.findall(r'\b(\w+s|will \w+|can \w+)\b', text, re.IGNORECASE)
            predicates = list(set(verb_fallback[:3]))  # Take first 3 as predicates
        
        return (
            list(set(quantifiers)),
            list(set(predicates)),
            list(set(entities)),
            list(set(connectives))
        )

    def _get_cache_key(
        self,
        text: str,
        operation: str = "convert",
        extra: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate a stable cache key for a text + operation combination."""
        normalized_text = (text or "").strip()
        normalized_operation = (operation or "").strip()
        parts = [
            normalized_operation,
            normalized_text,
            str(self.confidence_threshold),
            str(self.fallback_enabled),
            str(self.enable_caching)
        ]
        if extra:
            for key in sorted(extra.keys()):
                parts.append(f"{key}={extra[key]}")
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        return digest
    
    @beartype
    def semantic_to_fol(self, symbol: Symbol, output_format: str = "symbolic") -> FOLConversionResult:
        """
        Convert semantic symbol to FOL formula.
        
        Args:
            symbol: Symbol object to convert
            output_format: Output format for FOL formula
            
        Returns:
            FOLConversionResult with formula and metadata
        """
        # Check cache first
        if self.enable_caching and symbol.value in self._cache:
            logger.debug(f"Using cached result for: {symbol.value[:50]}...")
            return self._cache[symbol.value]
        
        try:
            # Extract logical components
            components = self.extract_logical_components(symbol)
            
            # Build FOL formula from components
            fol_formula, reasoning_steps = self._build_fol_formula(components, output_format)
            
            # Create result
            result = FOLConversionResult(
                fol_formula=fol_formula,
                components=components,
                confidence=components.confidence,
                reasoning_steps=reasoning_steps,
                fallback_used=not SYMBOLIC_AI_AVAILABLE
            )
            
            # Cache the result
            if self.enable_caching:
                self._cache[symbol.value] = result
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to convert semantic symbol to FOL: {e}")
            
            # Try fallback if enabled
            if self.fallback_enabled and self.fallback_available:
                return self._fallback_conversion(symbol.value, output_format)
            
            # Return error result
            return FOLConversionResult(
                fol_formula="",
                components=LogicalComponents([], [], [], [], 0.0, symbol.value),
                confidence=0.0,
                reasoning_steps=[],
                fallback_used=True,
                errors=[str(e)]
            )
    
    def _build_fol_formula(
        self, 
        components: LogicalComponents, 
        output_format: str
    ) -> Tuple[str, List[str]]:
        """
        Build FOL formula from extracted components.
        
        Args:
            components: Extracted logical components
            output_format: Desired output format
            
        Returns:
            Tuple of (fol_formula, reasoning_steps)
        """
        reasoning_steps = []
        
        # Step 1: Identify the logical structure
        reasoning_steps.append(f"Analyzing text: '{components.raw_text}'")
        reasoning_steps.append(f"Found quantifiers: {components.quantifiers}")
        reasoning_steps.append(f"Found predicates: {components.predicates}")
        reasoning_steps.append(f"Found entities: {components.entities}")
        reasoning_steps.append(f"Found connectives: {components.logical_connectives}")
        
        # Step 2: Build basic FOL structure
        if not components.quantifiers and not components.predicates:
            reasoning_steps.append("No clear logical structure found")
            return components.raw_text, reasoning_steps
        
        # Simple pattern matching for common structures
        fol_formula = self._pattern_match_to_fol(components, reasoning_steps)
        
        # Step 3: Format according to output format
        if output_format == "prolog":
            fol_formula = self._to_prolog_format(fol_formula)
        elif output_format == "tptp":
            fol_formula = self._to_tptp_format(fol_formula)
        
        reasoning_steps.append(f"Generated FOL formula: {fol_formula}")
        
        return fol_formula, reasoning_steps
    
    def _pattern_match_to_fol(
        self, 
        components: LogicalComponents, 
        reasoning_steps: List[str]
    ) -> str:
        """Match logical patterns to generate FOL formulas."""
        text = components.raw_text.lower()
        
        # Pattern 1: "All X are Y" -> ∀x (X(x) → Y(x))
        if any(q in ['all', 'every', 'each'] for q in components.quantifiers):
            if len(components.entities) >= 2:
                x_entity = components.entities[0].lower()
                y_entity = components.entities[1].lower()
                formula = f"∀x ({x_entity.capitalize()}(x) → {y_entity.capitalize()}(x))"
                reasoning_steps.append(f"Pattern: Universal quantification over {x_entity} → {y_entity}")
                return formula
        
        # Pattern 2: "Some X are Y" -> ∃x (X(x) ∧ Y(x))
        if any(q in ['some', 'exists', 'exist'] for q in components.quantifiers):
            if len(components.entities) >= 2:
                x_entity = components.entities[0].lower()
                y_entity = components.entities[1].lower()
                formula = f"∃x ({x_entity.capitalize()}(x) ∧ {y_entity.capitalize()}(x))"
                reasoning_steps.append(f"Pattern: Existential quantification over {x_entity} ∧ {y_entity}")
                return formula
        
        # Pattern 3: "X is Y" -> Y(X)
        if 'is' in components.predicates or 'are' in components.predicates:
            if len(components.entities) >= 2:
                x_entity = components.entities[0]
                y_entity = components.entities[1].lower()
                formula = f"{y_entity.capitalize()}({x_entity})"
                reasoning_steps.append(f"Pattern: Simple predication {y_entity}({x_entity})")
                return formula
        
        # Pattern 4: "X can Y" -> CanY(X)
        if 'can' in components.predicates:
            if len(components.entities) >= 1:
                x_entity = components.entities[0]
                if len(components.predicates) > 1:
                    action = [p for p in components.predicates if p != 'can'][0]
                    formula = f"Can{action.capitalize()}({x_entity})"
                    reasoning_steps.append(f"Pattern: Ability predicate Can{action}({x_entity})")
                    return formula
        
        # Fallback: create simple predicate
        if components.entities and components.predicates:
            entity = components.entities[0]
            predicate = components.predicates[0]
            formula = f"{predicate.capitalize()}({entity})"
            reasoning_steps.append(f"Fallback pattern: {predicate}({entity})")
            return formula
        
        reasoning_steps.append("No recognizable pattern found")
        return components.raw_text
    
    def _to_prolog_format(self, formula: str) -> str:
        """Convert to Prolog format."""
        # Simple conversion - replace symbols
        formula = formula.replace('∀', 'forall')
        formula = formula.replace('∃', 'exists')
        formula = formula.replace('→', ':-')
        formula = formula.replace('∧', ',')
        formula = formula.replace('∨', ';')
        return formula
    
    def _to_tptp_format(self, formula: str) -> str:
        """Convert to TPTP format."""
        # Simple conversion for TPTP
        formula = formula.replace('∀', '!')
        formula = formula.replace('∃', '?')
        formula = formula.replace('→', '=>')
        formula = formula.replace('∧', '&')
        formula = formula.replace('∨', '|')
        return f"fof(statement, axiom, {formula})."
    
    def _fallback_conversion(self, text: str, output_format: str) -> FOLConversionResult:
        """Fallback conversion using original FOL system."""
        try:
            # This would call the original text_to_fol function
            # For now, return a simple conversion
            components = LogicalComponents([], [], [], [], 0.5, text)
            formula = f"Statement({text.replace(' ', '_')})"
            
            return FOLConversionResult(
                fol_formula=formula,
                components=components,
                confidence=0.5,
                reasoning_steps=["Used fallback conversion"],
                fallback_used=True
            )
            
        except Exception as e:
            return FOLConversionResult(
                fol_formula="",
                components=LogicalComponents([], [], [], [], 0.0, text),
                confidence=0.0,
                reasoning_steps=[],
                fallback_used=True,
                errors=[str(e)]
            )

    def _fallback_to_fol_conversion(self, text: str, output_format: str = "symbolic") -> FOLConversionResult:
        """Compatibility shim for legacy callers."""
        return self._fallback_conversion(text, output_format)
    
    def validate_fol_formula(self, formula: str) -> Dict[str, Any]:
        """
        Validate the syntax and structure of a FOL formula.
        
        Args:
            formula: FOL formula to validate
            
        Returns:
            Dictionary with validation results
        """
        try:
            result = {
                "valid": True,
                "errors": [],
                "warnings": [],
                "structure": {}
            }
            
            # Basic syntax checks
            if not formula or not formula.strip():
                result["valid"] = False
                result["errors"].append("Formula is empty")
                return result
            
            # Check for balanced parentheses
            if formula.count('(') != formula.count(')'):
                result["valid"] = False
                result["errors"].append("Unbalanced parentheses")
            
            # Check for valid quantifiers
            quantifier_symbols = ['∀', '∃', 'forall', 'exists', '!', '?']
            has_quantifiers = any(q in formula for q in quantifier_symbols)
            result["structure"]["has_quantifiers"] = has_quantifiers
            
            # Check for predicates
            predicate_pattern = r'[A-Z][a-zA-Z]*\([^)]+\)'
            predicates = re.findall(predicate_pattern, formula)
            result["structure"]["predicates"] = predicates
            result["structure"]["predicate_count"] = len(predicates)
            
            # Check for logical connectives
            connectives = ['∧', '∨', '→', '¬', '&', '|', '=>', ':-', ',', ';']
            found_connectives = [c for c in connectives if c in formula]
            result["structure"]["connectives"] = found_connectives
            
            if len(predicates) == 0:
                result["warnings"].append("No predicates found")
            
            return result
            
        except Exception as e:
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": [],
                "structure": {}
            }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the bridge usage."""
        return {
            "symbolic_ai_available": SYMBOLIC_AI_AVAILABLE,
            "fallback_available": self.fallback_available,
            "cache_size": len(self._cache),
            "confidence_threshold": self.confidence_threshold,
            "total_conversions": len(self._cache) if self.enable_caching else "N/A"
        }
    
    def clear_cache(self):
        """Clear the conversion cache."""
        self._cache.clear()
        logger.info("Conversion cache cleared")

    # ------------------------------------------------------------------
    # Convenience helpers expected by tests
    # ------------------------------------------------------------------

    def _extract_quantifiers(self, text: str) -> List[str]:
        """Extract quantifier symbols from text."""
        result: List[str] = []
        t = text.lower()
        if any(w in t for w in ("all ", "every ", "each ")):
            result.append("∀")
        if any(w in t for w in ("some ", "exist ", "exists ", "there is", "there are")):
            result.append("∃")
        return result

    def _extract_predicates(self, text: str) -> List[str]:
        """Extract predicate names from text (capitalised words followed by '(')."""
        import re
        return re.findall(r'\b([A-Z][A-Za-z0-9_]*)\s*\(', text)

    def _extract_entities(self, text: str) -> List[str]:
        """Extract named entities (title-case words not followed by '(')."""
        import re
        candidates = re.findall(r'\b([A-Z][a-z]+)\b', text)
        # Exclude words followed by '('
        preds = set(self._extract_predicates(text))
        return [c for c in candidates if c not in preds]

    def _extract_connectives(self, text: str) -> List[str]:
        """Extract logical connective symbols from text."""
        result: List[str] = []
        t = text.lower()
        if " and " in t:
            result.append("∧")
        if " or " in t:
            result.append("∨")
        if "if " in t and " then " in t:
            result.append("→")
        if " iff " in t or " if and only if " in t:
            result.append("↔")
        if t.startswith("not ") or " not " in t:
            result.append("¬")
        return result

    def _pattern_based_conversion(self, text: str) -> Optional[str]:
        """Try pattern-based NL→FOL conversion. Returns None if no pattern matches."""
        t = text.lower()
        import re
        # "All/Every X are Y"
        m = re.match(r'\b(all|every|each)\s+(\w+)s?\s+(?:are|is)\s+(\w+)', t)
        if m:
            x, y = m.group(2).capitalize(), m.group(3).capitalize()
            return f"∀x({x}(x) → {y}(x))"
        # "Some X are Y"
        m = re.match(r'\b(some|there (?:is|are))\s+(\w+)s?\s+(?:are|is|that (?:are|is))?\s*(\w+)', t)
        if m:
            x, y = m.group(2).capitalize(), m.group(3).capitalize()
            return f"∃x({x}(x) ∧ {y}(x))"
        return None

    def _semantic_conversion(self, text: str) -> str:
        """Semantic conversion (uses SymbolicAI if available, else mock)."""
        symbol = self.create_semantic_symbol(text)
        if symbol is not None:
            query_result = symbol.query("Convert to first-order logic formula")
            if query_result:
                return str(query_result)
        # Fallback mock
        return f"Statement({text.replace(' ', '_')})"

    def convert_to_fol(self, text: str, output_format: str = "symbolic") -> 'FOLConversionResult':
        """Convert natural language text to FOL formula."""
        if not text or not text.strip():
            return FOLConversionResult(
                fol_formula="",
                components=LogicalComponents([], [], [], [], 0.0, text or ""),
                confidence=0.0,
                reasoning_steps=[],
                fallback_used=True,
                errors=["Empty input text"]
            )

        cache_key = self._get_cache_key(text)
        if self.enable_caching and cache_key in self._cache:
            return self._cache[cache_key]

        # Try pattern-based first
        pattern_result = self._pattern_based_conversion(text)
        if pattern_result is not None:
            components = LogicalComponents(
                quantifiers=self._extract_quantifiers(text),
                predicates=self._extract_predicates(text),
                entities=self._extract_entities(text),
                logical_connectives=self._extract_connectives(text),
                confidence=0.85,
                raw_text=text
            )
            result = FOLConversionResult(
                fol_formula=pattern_result,
                components=components,
                confidence=0.85,
                reasoning_steps=[f"Pattern match: {pattern_result}"],
                fallback_used=False
            )
        else:
            # Semantic or fallback
            semantic_str = self._semantic_conversion(text)
            confidence = 0.6 if semantic_str and semantic_str != f"Statement({text.replace(' ', '_')})" else 0.4
            if confidence < self.confidence_threshold and self.fallback_enabled:
                result = self._fallback_conversion(text, output_format)
                result.fallback_used = True
            else:
                components = LogicalComponents(
                    quantifiers=self._extract_quantifiers(text),
                    predicates=self._extract_predicates(text),
                    entities=self._extract_entities(text),
                    logical_connectives=self._extract_connectives(text),
                    confidence=confidence,
                    raw_text=text
                )
                result = FOLConversionResult(
                    fol_formula=semantic_str,
                    components=components,
                    confidence=confidence,
                    reasoning_steps=[f"Semantic conversion: {semantic_str}"],
                    fallback_used=False
                )

        if self.enable_caching:
            self._cache[cache_key] = result
        return result

    def get_stats(self) -> Dict[str, Any]:
        """Return bridge usage statistics (alias for get_statistics)."""
        return {
            "symbolic_ai_available": SYMBOLIC_AI_AVAILABLE,
            "fallback_available": self.fallback_available,
            "cache_size": len(self._cache),
            "confidence_threshold": self.confidence_threshold,
        }

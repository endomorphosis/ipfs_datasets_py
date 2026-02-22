"""
Symbolic FOL Bridge Module

This module provides the core bridge between SymbolicAI and the existing FOL system,
enabling semantic analysis and enhanced natural language to logic conversion.
"""

import hashlib
import logging
import re
from typing import Dict, List, Optional, Union, Any, Tuple, TYPE_CHECKING
from dataclasses import dataclass
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
    """Structure for holding extracted logical components.
    
    Also supports dict-style access for backward compatibility.
    """
    quantifiers: List[str]
    predicates: List[str]
    entities: List[str]
    logical_connectives: List[str]
    confidence: float
    raw_text: str

    # ------------------------------------------------------------------
    # Dict-style backward-compat interface
    # ------------------------------------------------------------------

    def _as_dict(self) -> dict:
        return {
            "quantifiers": self.quantifiers,
            "predicates": self.predicates,
            "entities": self.entities,
            "connectives": self.logical_connectives,
            "confidence": self.confidence,
        }

    def __contains__(self, item: object) -> bool:
        return item in self._as_dict()

    def __getitem__(self, key: str):
        return self._as_dict()[key]

    def get(self, key: str, default=None):
        return self._as_dict().get(key, default)

    def keys(self):
        return self._as_dict().keys()

    def items(self):
        return self._as_dict().items()


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
        # Reject purely numeric input or single-character lowercase (not a logic symbol)
        if stripped.isdigit() or (len(stripped) == 1 and stripped.islower()):
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
    def extract_logical_components(self, symbol: Symbol) -> LogicalComponents:
        """
        Extract logical components from a semantic symbol.
        
        Args:
            symbol: Symbol object to analyze
            
        Returns:
            LogicalComponents object with extracted elements
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
                # Normalize quantifiers/predicates to lowercase for consistent comparison
                quantifiers = [q.lower() for q in quantifiers]
                predicates = [p.lower() for p in predicates]
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
            # Normalize quantifiers/predicates to lowercase for consistent comparison
            quantifiers = [q.lower() for q in quantifiers]
            predicates = [p.lower() for p in predicates]
            
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
        quantifier_patterns = r'\b(all|every|each|some|exists?|for\s+all|there\s+(?:is|are))\b'
        predicate_patterns = (
            r'\b(is|are|has|have|can|cannot|loves?|studies?|flies?|runs?|'
            r'takes?|likes?|sleeps?|needs?|rains?|wants?|goes|came?|teaches?|'
            r'writes?|reads?|uses?|makes?|sees?|knows?|works?|plays?|brings?|'
            r'gives?|eats?|drinks?|swims?|sings?|lives?|dies?|gradu(?:ates?)?|'
            r'excel(?:s)?|pass(?:es)?|fails?|belongs?|exists?|occurs?|'
            r'prove(?:d|n)?|conducts?|conserves?|requires?|survives?)\b'
        )
        connective_patterns = r'\b(and|or|not|if|then|implies?|but|however)\b'
        
        quantifiers = re.findall(quantifier_patterns, text, re.IGNORECASE)
        predicates = re.findall(predicate_patterns, text, re.IGNORECASE)
        connectives = re.findall(connective_patterns, text, re.IGNORECASE)
        
        # Extract entities: nouns that are NOT quantifiers, predicates, or connectives
        stop_words = set(['all', 'every', 'each', 'some', 'exists', 'exist', 'there', 'is',
                          'are', 'has', 'have', 'can', 'cannot', 'and', 'or', 'not', 'if',
                          'then', 'that', 'a', 'an', 'the', 'it', 'he', 'she', 'they',
                          'be', 'been', 'being', 'do', 'does', 'did', 'will', 'would',
                          'could', 'should', 'may', 'might', 'but', 'however', 'implies',
                          'imply', 'for', 'of', 'in', 'on', 'at', 'to', 'from', 'with'])
        words = re.findall(r'\b[a-zA-Z]{2,}\b', text)
        entities = [w for w in words if w.lower() not in stop_words]
        
        return (
            list(dict.fromkeys(quantifiers)),
            list(dict.fromkeys(predicates)),
            list(dict.fromkeys(entities)),
            list(dict.fromkeys(connectives))
        )

    def _get_cache_key(
        self,
        text: str,
        operation: str = "",
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
        # Check cache first (include format in key)
        cache_key = f"{symbol.value}::{output_format}"
        if self.enable_caching and cache_key in self._cache:
            logger.debug(f"Using cached result for: {symbol.value[:50]}...")
            return self._cache[cache_key]
        
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
                self._cache[cache_key] = result
            
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
        # Normalize for comparison
        q_lower = [q.lower() for q in components.quantifiers]
        p_lower = [p.lower() for p in components.predicates]
        e_normalized = [e.lower() for e in components.entities]
        
        # Pattern 1: "All X are Y" -> ∀x (X(x) → Y(x))
        if any(q in ['all', 'every', 'each'] for q in q_lower):
            if len(e_normalized) >= 2:
                x_entity = e_normalized[0]
                y_entity = e_normalized[1]
                formula = f"∀x ({x_entity.capitalize()}(x) → {y_entity.capitalize()}(x))"
                reasoning_steps.append(f"Pattern: Universal quantification over {x_entity} → {y_entity}")
                return formula
        
        # Pattern 2: "Some X are Y" -> ∃x (X(x) ∧ Y(x))
        if any(q in ['some', 'exists', 'exist'] for q in q_lower):
            if len(e_normalized) >= 2:
                x_entity = e_normalized[0]
                y_entity = e_normalized[1]
                formula = f"∃x ({x_entity.capitalize()}(x) ∧ {y_entity.capitalize()}(x))"
                reasoning_steps.append(f"Pattern: Existential quantification over {x_entity} ∧ {y_entity}")
                return formula
        
        # Pattern 3: "X is Y" -> Y(X)
        if 'is' in p_lower or 'are' in p_lower:
            if len(e_normalized) >= 2:
                x_entity = e_normalized[0]
                y_entity = e_normalized[1]
                formula = f"{y_entity.capitalize()}({x_entity.capitalize()})"
                reasoning_steps.append(f"Pattern: Simple predication {y_entity}({x_entity})")
                return formula
        
        # Pattern 4: "X can Y" -> CanY(X)
        if 'can' in p_lower:
            if len(e_normalized) >= 1:
                x_entity = e_normalized[0]
                # Try to get action from other predicates or second entity
                action_list = [p for p in p_lower if p != 'can']
                if action_list:
                    action = action_list[0]
                elif len(e_normalized) >= 2:
                    action = e_normalized[1]
                else:
                    action = 'act'
                formula = f"Can{action.capitalize()}({x_entity.capitalize()})"
                reasoning_steps.append(f"Pattern: Ability predicate Can{action}({x_entity})")
                return formula
        
        # Fallback: create simple predicate
        if e_normalized and p_lower:
            entity = e_normalized[0]
            predicate = p_lower[0]
            formula = f"{predicate.capitalize()}({entity.capitalize()})"
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

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the bridge usage (alias for get_statistics)."""
        return self.get_statistics()

    def _extract_quantifiers(self, text: str) -> str:
        """Extract quantifier symbols from text, returning FOL symbols."""
        result = []
        if re.search(r'\b(all|every|each|for\s+all)\b', text, re.IGNORECASE):
            result.append('∀')
        if re.search(r'\b(some|exists?|there\s+(is|are)|at\s+least\s+one)\b', text, re.IGNORECASE):
            result.append('∃')
        return ' '.join(result) if result else 'none'

    def _extract_predicates(self, text: str) -> List[str]:
        """Extract predicate names (capitalized words followed by '(') from text."""
        return re.findall(r'([A-Z][a-zA-Z]*)\s*\(', text)

    def _extract_entities(self, text: str) -> List[str]:
        """Extract named entities (capitalized words not at sentence start) from text."""
        words = re.findall(r'\b([A-Z][a-z]+)\b', text)
        return list(dict.fromkeys(words))

    def _extract_connectives(self, text: str) -> str:
        """Extract logical connectives from text, returning FOL symbols."""
        result = []
        if re.search(r'\band\b', text, re.IGNORECASE):
            result.append('∧')
        if re.search(r'\bor\b', text, re.IGNORECASE):
            result.append('∨')
        if re.search(r'\b(if|implies?)\b.*\b(then)\b|\b(if)\b', text, re.IGNORECASE):
            result.append('→')
        if re.search(r'\b(iff|if\s+and\s+only\s+if)\b', text, re.IGNORECASE):
            result.append('↔')
        if re.search(r'\b(not|no)\b', text, re.IGNORECASE):
            result.append('¬')
        return ' '.join(result) if result else 'none'

    def _pattern_based_conversion(self, text: str) -> Optional[str]:
        """Apply pattern-based conversion to FOL. Returns formula string or None."""
        text_lower = text.lower()
        # "All/Every X are Y" → ∀x (X(x) → Y(x))
        m = re.match(r'(?:all|every)\s+(\w+)\s+are\s+(\w+)', text_lower)
        if m:
            s, p = m.group(1).capitalize(), m.group(2).capitalize()
            return f"∀x ({s}(x) → {p}(x))"
        # "Some X are Y" → ∃x (X(x) ∧ Y(x))
        m = re.match(r'some\s+(\w+)\s+are\s+(\w+)', text_lower)
        if m:
            s, p = m.group(1).capitalize(), m.group(2).capitalize()
            return f"∃x ({s}(x) ∧ {p}(x))"
        return None

    def _semantic_conversion(self, text: str) -> str:
        """Perform semantic conversion to FOL (uses SymbolicAI if available)."""
        if SYMBOLIC_AI_AVAILABLE:
            try:
                symbol = Symbol(text, semantic=True)
                result = symbol.query(
                    "Convert this natural language statement to a First-Order Logic formula. "
                    "Return only the FOL formula using ∀, ∃, →, ∧, ∨, ¬ symbols."
                )
                return str(result)
            except Exception as e:
                logger.warning(f"Semantic conversion failed: {e}")
        # Fallback: use pattern-based or simple formula
        pattern_result = self._pattern_based_conversion(text)
        if pattern_result:
            return pattern_result
        return f"Statement({text.replace(' ', '_')})"

    def convert_to_fol(self, text: str, output_format: str = "symbolic") -> FOLConversionResult:
        """
        Convert natural language text to FOL formula.

        Args:
            text: Natural language text to convert
            output_format: Output format ("symbolic", "prolog", "tptp")

        Returns:
            FOLConversionResult with formula and metadata
        """
        if not text or not text.strip():
            return FOLConversionResult(
                fol_formula="",
                components=LogicalComponents([], [], [], [], 0.0, text),
                confidence=0.0,
                reasoning_steps=[],
                fallback_used=True,
                errors=["Input text is empty"]
            )

        cache_key = self._get_cache_key(text, output_format)
        if self.enable_caching and cache_key in self._cache:
            return self._cache[cache_key]

        reasoning_steps = [f"Processing: '{text}'"]

        # Try pattern-based conversion first
        pattern_result = self._pattern_based_conversion(text)
        if pattern_result:
            reasoning_steps.append("Pattern-based conversion succeeded")
            if output_format == "prolog":
                pattern_result = self._to_prolog_format(pattern_result)
            elif output_format == "tptp":
                pattern_result = self._to_tptp_format(pattern_result)
            symbol = Symbol(text)
            components = self.extract_logical_components(symbol)
            result = FOLConversionResult(
                fol_formula=pattern_result,
                components=components,
                confidence=0.8,
                reasoning_steps=reasoning_steps,
                fallback_used=False
            )
        else:
            # Fall back to semantic conversion
            reasoning_steps.append("Using semantic/fallback conversion")
            formula = self._semantic_conversion(text)
            symbol = Symbol(text)
            components = self.extract_logical_components(symbol)
            result = FOLConversionResult(
                fol_formula=formula,
                components=components,
                confidence=0.5,
                reasoning_steps=reasoning_steps,
                fallback_used=True
            )

        if self.enable_caching:
            self._cache[cache_key] = result
        return result

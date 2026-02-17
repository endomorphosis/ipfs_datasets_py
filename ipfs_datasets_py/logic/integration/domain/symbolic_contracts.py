"""
Symbolic Contracts Module

This module implements contract-based validation for FOL generation using SymbolicAI's
Design by Contract principles to ensure logical consistency and quality.
"""

import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
try:
    from beartype import beartype  # type: ignore
except Exception:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func
from pydantic import BaseModel, Field, field_validator, ConfigDict
import re
import json

# Configure logging
logger = logging.getLogger(__name__)

# Conditional imports
try:
    from symai import Expression
    from symai.strategy import contract
    try:
        from symai.strategy import LLMDataModel
    except (ImportError, AttributeError) as e:
        # LLMDataModel not available in all SymbolicAI versions
        logger.debug(f"LLMDataModel not available, using BaseModel fallback: {e}")
        LLMDataModel = BaseModel
    SYMBOLIC_AI_AVAILABLE = True
except (ImportError, SystemExit):
    SYMBOLIC_AI_AVAILABLE = False
    LLMDataModel = BaseModel
    logger.warning("SymbolicAI not available. Contract system will use fallback implementation.")

    # Mock classes for development without SymbolicAI
    class Expression:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, *args, **kwargs):
            return {"status": "success", "result": "mock_result"}

    def contract(**kwargs):
        def decorator(cls):
            return cls
        return decorator


class FOLInput(LLMDataModel):
    """Input model for FOL conversion with validation."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=False
    )
    
    text: str = Field(
        description="Natural language text to convert to FOL",
        min_length=1,
        max_length=10000
    )
    domain_predicates: List[str] = Field(
        default_factory=list,
        description="Domain-specific predicates to consider"
    )
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for conversion"
    )
    output_format: str = Field(
        default="symbolic",
        pattern=r"^(symbolic|prolog|tptp|json)$",
        description="Desired output format"
    )
    reasoning_depth: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Depth of reasoning steps to perform"
    )
    validate_syntax: bool = Field(
        default=True,
        description="Whether to validate FOL syntax"
    )
    
    @field_validator('text')
    @classmethod
    def validate_text_content(cls, v: str) -> str:
        """Validate that text contains meaningful content."""
        if not v or not v.strip():
            raise ValueError("Text cannot be empty or whitespace only")
        
        # Check for minimum meaningful content
        words = v.split()
        if len(words) < 2:
            raise ValueError("Text must contain at least 2 words")
        
        # Check for presence of some logical structure indicators
        logical_indicators = [
            'all', 'every', 'some', 'exists', 'if', 'then', 'and', 'or', 'not',
            'is', 'are', 'has', 'have', 'can', 'must', 'should', 'will'
        ]
        
        text_lower = v.lower()
        if not any(indicator in text_lower for indicator in logical_indicators):
            logger.warning(f"Text may not contain clear logical structure: {v[:50]}...")
        
        return v
    
    @field_validator('domain_predicates')
    @classmethod
    def validate_predicates(cls, v: List[str]) -> List[str]:
        """Validate domain predicates format."""
        valid_predicates = []
        for predicate in v:
            if predicate and predicate.strip():
                # Basic predicate format validation
                predicate = predicate.strip()
                if re.match(r'^[A-Za-z][A-Za-z0-9_]*$', predicate):
                    valid_predicates.append(predicate)
                else:
                    logger.warning(f"Invalid predicate format ignored: {predicate}")
        return valid_predicates


class FOLOutput(LLMDataModel):
    """Output model for FOL conversion with validation."""
    
    model_config = ConfigDict(validate_assignment=True)
    
    fol_formula: str = Field(description="Generated First-Order Logic formula")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score of the conversion"
    )
    logical_components: Dict[str, Any] = Field(
        description="Extracted logical components"
    )
    reasoning_steps: List[str] = Field(
        default_factory=list,
        description="Step-by-step reasoning process"
    )
    validation_results: Dict[str, Any] = Field(
        default_factory=dict,
        description="Results of formula validation"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Warnings generated during conversion"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata about the conversion"
    )
    
    @field_validator('fol_formula')
    @classmethod
    def validate_fol_syntax(cls, v: str) -> str:
        """Validate FOL formula syntax."""
        if not v or len(v.strip()) == 0:
            raise ValueError("FOL formula cannot be empty")
        
        # Basic syntax validation
        formula = v.strip()
        
        # Check for balanced parentheses
        if formula.count('(') != formula.count(')'):
            raise ValueError("Unbalanced parentheses in FOL formula")
        
        # Check for basic FOL structure (at least some recognizable elements)
        fol_elements = [
            '∀', '∃', '→', '∧', '∨', '¬',  # Unicode symbols
            'forall', 'exists', '->', '&', '|', '~',  # ASCII equivalents
            ':-', '=>', 'implies'  # Other notations
        ]
        
        # If it's a simple predicate format, that's also valid
        predicate_pattern = r'[A-Z][a-zA-Z]*\([^)]*\)'
        if re.search(predicate_pattern, formula) or any(elem in formula for elem in fol_elements):
            return formula
        
        # If no clear FOL structure, warn but don't fail
        logger.warning(f"Formula may not be in standard FOL format: {formula[:50]}...")
        return formula
    
    @field_validator('logical_components')
    @classmethod
    def validate_components(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate logical components structure."""
        required_keys = ['quantifiers', 'predicates', 'entities']
        for key in required_keys:
            if key not in v:
                v[key] = []
        return v


@dataclass
class ValidationContext:
    """Context for validation operations."""
    strict_mode: bool = True
    allow_empty_predicates: bool = False
    max_complexity: int = 100
    custom_validators: List[callable] = field(default_factory=list)


class FOLSyntaxValidator:
    """Specialized validator for FOL syntax and semantics."""
    
    def __init__(self, strict: bool = True):
        self.strict = strict
        self.common_errors = []
    
    @beartype
    def validate_formula(self, formula: str) -> Dict[str, Any]:
        """
        Comprehensive FOL formula validation.
        
        Args:
            formula: FOL formula to validate
            
        Returns:
            Dictionary with validation results
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "structure_analysis": {}
        }

        if not formula or not str(formula).strip():
            result["valid"] = False
            result["errors"].append("Formula is empty")
            return result
        
        try:
            # 1. Basic syntax validation
            syntax_errors = self._check_syntax(formula)
            result["errors"].extend(syntax_errors)
            
            # 2. Structural analysis
            structure = self._analyze_structure(formula)
            result["structure_analysis"] = structure
            
            # 3. Semantic validation
            semantic_warnings = self._check_semantics(formula, structure)
            result["warnings"].extend(semantic_warnings)
            
            # 4. Generate suggestions
            suggestions = self._generate_suggestions(formula, structure)
            result["suggestions"].extend(suggestions)
            
            # Set overall validity
            result["valid"] = len(result["errors"]) == 0
            
        except Exception as e:
            result["valid"] = False
            result["errors"].append(f"Validation error: {str(e)}")
        
        return result
    
    def _check_syntax(self, formula: str) -> List[str]:
        """Check basic syntax errors."""
        errors = []

        if not formula or not str(formula).strip():
            errors.append("Empty formula")
            return errors
        
        # Check balanced parentheses
        if formula.count('(') != formula.count(')'):
            errors.append("Unbalanced parentheses")
        
        # Check balanced brackets if present
        if formula.count('[') != formula.count(']'):
            errors.append("Unbalanced square brackets")
        
        # Check for malformed quantifiers
        quantifier_pattern = r'(∀|∃|forall|exists)\s*([a-z]+)'
        quantifiers = re.findall(quantifier_pattern, formula, re.IGNORECASE)
        for quantifier, var in quantifiers:
            if not re.match(r'^[a-z]$', var):
                errors.append(f"Invalid variable '{var}' for quantifier '{quantifier}'")
        
        # Check for proper predicate format
        predicate_pattern = r'([A-Z][a-zA-Z]*)\(([^)]*)\)'
        predicates = re.findall(predicate_pattern, formula)
        for pred_name, args in predicates:
            if not pred_name[0].isupper():
                errors.append(f"Predicate '{pred_name}' should start with uppercase")
            
            # Check argument format
            if args.strip():
                arg_list = [arg.strip() for arg in args.split(',')]
                for arg in arg_list:
                    if not re.match(r'^[a-zA-Z][a-zA-Z0-9]*$', arg):
                        errors.append(f"Invalid argument '{arg}' in predicate '{pred_name}'")
        
        return errors
    
    def _analyze_structure(self, formula: str) -> Dict[str, Any]:
        """Analyze the structure of the formula."""
        structure = {
            "has_quantifiers": False,
            "quantifier_types": [],
            "predicate_count": 0,
            "predicates": [],
            "variables": set(),
            "constants": set(),
            "connectives": [],
            "complexity_score": 0
        }
        
        # Find quantifiers
        quantifier_pattern = r'(∀|∃|forall|exists)\s*([a-z]+)'
        quantifiers = re.findall(quantifier_pattern, formula, re.IGNORECASE)
        if quantifiers:
            structure["has_quantifiers"] = True
            structure["quantifier_types"] = [q[0] for q in quantifiers]
            structure["variables"].update(q[1] for q in quantifiers)
        
        # Find predicates
        predicate_pattern = r'([A-Z][a-zA-Z]*)\(([^)]*)\)'
        predicates = re.findall(predicate_pattern, formula)
        structure["predicate_count"] = len(predicates)
        structure["predicates"] = [p[0] for p in predicates]
        
        # Extract variables and constants from predicates
        for _, args in predicates:
            if args.strip():
                arg_list = [arg.strip() for arg in args.split(',')]
                for arg in arg_list:
                    if arg.islower():
                        structure["variables"].add(arg)
                    elif arg[0].isupper():
                        structure["constants"].add(arg)
        
        # Find logical connectives
        connectives = ['∧', '∨', '→', '¬', '&', '|', '->', ':-', '=>', '~', 'and', 'or', 'not']
        for conn in connectives:
            if conn in formula:
                structure["connectives"].append(conn)
        
        # Calculate complexity score
        complexity = (
            len(structure["variables"]) * 2 +
            structure["predicate_count"] * 3 +
            len(structure["connectives"]) * 2 +
            formula.count('(') + formula.count(')')
        )
        structure["complexity_score"] = complexity
        
        # Convert sets to lists for JSON serialization
        structure["variables"] = list(structure["variables"])
        structure["constants"] = list(structure["constants"])
        
        return structure
    
    def _check_semantics(self, formula: str, structure: Dict[str, Any]) -> List[str]:
        """Check semantic issues."""
        warnings = []
        
        # Check for unused variables
        quantified_vars = set()
        if structure["has_quantifiers"]:
            quantifier_pattern = r'(∀|∃|forall|exists)\s*([a-z]+)'
            quantified_vars = {q[1] for q in re.findall(quantifier_pattern, formula, re.IGNORECASE)}
        
        used_vars = set(structure["variables"])
        unused_vars = quantified_vars - used_vars
        if unused_vars:
            warnings.append(f"Unused quantified variables: {', '.join(unused_vars)}")
        
        # Check for free variables
        free_vars = used_vars - quantified_vars
        if free_vars:
            warnings.append(f"Free variables (not quantified): {', '.join(free_vars)}")
        
        # Check complexity
        if structure["complexity_score"] > 50:
            warnings.append("Formula has high complexity, consider simplification")
        
        # Check for common logical issues
        if '→' in formula and '∧' in formula:
            warnings.append("Mixed implications and conjunctions - verify logical structure")
        
        return warnings
    
    def _generate_suggestions(self, formula: str, structure: Dict[str, Any]) -> List[str]:
        """Generate improvement suggestions."""
        suggestions = []
        
        # Suggest simplifications
        if structure["complexity_score"] > 30:
            suggestions.append("Consider breaking down complex formula into simpler components")
        
        # Suggest better variable naming
        if len(structure["variables"]) > 3:
            suggestions.append("Consider using more descriptive variable names for readability")
        
        # Suggest predicate improvements
        single_char_predicates = [p for p in structure["predicates"] if len(p) == 1]
        if single_char_predicates:
            suggestions.append("Consider using more descriptive predicate names")
        
        return suggestions


if SYMBOLIC_AI_AVAILABLE:
    @contract(
        pre_remedy=True,
        post_remedy=True,
        accumulate_errors=True,
        verbose=True
    )
    class ContractedFOLConverter(Expression):
        """
        Contract-based FOL converter using SymbolicAI.
        
        This class ensures that FOL conversion follows strict validation
        contracts for both input and output.
        """
        
        prompt = """
        Convert natural language statements into formal First-Order Logic (FOL) formulas.
        
        Instructions:
        1. Analyze the input text for logical structure
        2. Identify quantifiers (∀ for universal, ∃ for existential)
        3. Extract predicates and their relationships
        4. Determine logical connectives (∧, ∨, →, ¬)
        5. Structure the formula with proper syntax
        6. Ensure logical consistency and validity
        
        Output Format:
        - Use standard FOL notation with Unicode symbols
        - Variables should be lowercase (x, y, z)
        - Predicates should start with uppercase
        - Ensure proper parentheses and operator precedence
        
        Example conversions:
        - "All cats are animals" → ∀x (Cat(x) → Animal(x))
        - "Some birds can fly" → ∃x (Bird(x) ∧ CanFly(x))
        - "If it rains, then the ground is wet" → Rain → WetGround
        """
        
        def __init__(self):
            super().__init__()
            self.validator = FOLSyntaxValidator(strict=True)
            self.conversion_stats = {
                "total_conversions": 0,
                "successful_conversions": 0,
                "failed_conversions": 0,
                "average_confidence": 0.0
            }

        def _coerce_input(self, input_data: Any) -> FOLInput:
            """Normalize dynamic input into a validated FOLInput instance."""
            if isinstance(input_data, FOLInput):
                return input_data

            if isinstance(input_data, dict):
                payload = input_data
            else:
                payload = {}
                if hasattr(input_data, "text"):
                    payload["text"] = getattr(input_data, "text")
                elif hasattr(input_data, "natural_language"):
                    payload["text"] = getattr(input_data, "natural_language")

                if hasattr(input_data, "domain_predicates"):
                    payload["domain_predicates"] = getattr(input_data, "domain_predicates")
                if hasattr(input_data, "confidence_threshold"):
                    payload["confidence_threshold"] = getattr(input_data, "confidence_threshold")
                if hasattr(input_data, "output_format"):
                    payload["output_format"] = getattr(input_data, "output_format")
                if hasattr(input_data, "reasoning_depth"):
                    payload["reasoning_depth"] = getattr(input_data, "reasoning_depth")
                if hasattr(input_data, "validate_syntax"):
                    payload["validate_syntax"] = getattr(input_data, "validate_syntax")

            if "text" not in payload:
                raise ValueError("Input data missing required 'text' field")

            return FOLInput(**payload)

        def _coerce_output(self, output_data: Any) -> FOLOutput:
            """Normalize dynamic output into a validated FOLOutput instance."""
            if isinstance(output_data, FOLOutput):
                return output_data

            if isinstance(output_data, dict):
                payload = output_data
            else:
                payload = {}
                if hasattr(output_data, "fol_formula"):
                    payload["fol_formula"] = getattr(output_data, "fol_formula")
                if hasattr(output_data, "confidence"):
                    payload["confidence"] = getattr(output_data, "confidence")
                if hasattr(output_data, "logical_components"):
                    payload["logical_components"] = getattr(output_data, "logical_components")
                if hasattr(output_data, "reasoning_steps"):
                    payload["reasoning_steps"] = getattr(output_data, "reasoning_steps")
                if hasattr(output_data, "validation_results"):
                    payload["validation_results"] = getattr(output_data, "validation_results")
                if hasattr(output_data, "warnings"):
                    payload["warnings"] = getattr(output_data, "warnings")
                if hasattr(output_data, "metadata"):
                    payload["metadata"] = getattr(output_data, "metadata")

            if "fol_formula" not in payload:
                raise ValueError("Output data missing required 'fol_formula' field")

            if "confidence" not in payload:
                payload["confidence"] = 0.0
            if "logical_components" not in payload:
                payload["logical_components"] = {"quantifiers": [], "predicates": [], "entities": []}

            return FOLOutput(**payload)
        
        def pre(self, input_data: FOLInput) -> bool:
            """Validate input before processing."""
            try:
                input_data = self._coerce_input(input_data)
                # Basic input validation is handled by Pydantic
                text = getattr(input_data, "text", None)
                if text is None and isinstance(input_data, dict):
                    text = input_data.get("text")
                if not isinstance(text, str):
                    logger.error("Pre-condition validation failed: missing text field")
                    return False

                # Additional semantic validation
                if len(text.split()) > 100:
                    logger.warning("Input text is very long, may affect conversion quality")
                
                # Check for problematic patterns
                problematic_patterns = [
                    r'\d+',  # Numbers might be tricky
                    r'[^\w\s\.,!?;:-]',  # Special characters
                ]
                
                for pattern in problematic_patterns:
                    if re.search(pattern, text):
                        logger.warning(f"Input contains potentially problematic patterns: {pattern}")
                
                return True
                
            except Exception as e:
                logger.error(f"Pre-condition validation failed: {e}")
                return False
        
        def post(self, output_data: FOLOutput) -> bool:
            """Validate output after processing."""
            try:
                output_data = self._coerce_output(output_data)
                # Validate the FOL formula
                validation_result = self.validator.validate_formula(output_data.fol_formula)
                
                # Update the output with validation results
                output_data.validation_results = validation_result
                
                # Check confidence threshold
                if output_data.confidence < 0.5:
                    logger.warning(f"Low confidence conversion: {output_data.confidence}")
                
                # Update statistics
                self.conversion_stats["total_conversions"] += 1
                if validation_result["valid"]:
                    self.conversion_stats["successful_conversions"] += 1
                else:
                    self.conversion_stats["failed_conversions"] += 1
                    logger.error(f"Invalid FOL formula generated: {validation_result['errors']}")
                
                return validation_result["valid"]
                
            except Exception as e:
                logger.error(f"Post-condition validation failed: {e}")
                return False
        
        def forward(self, input_data: FOLInput) -> FOLOutput:
            """Main conversion logic."""
            try:
                from .symbolic_fol_bridge import SymbolicFOLBridge

                input_data = self._coerce_input(input_data)
                
                # Create bridge and process
                bridge = SymbolicFOLBridge(
                    confidence_threshold=input_data.confidence_threshold
                )
                
                # Create semantic symbol
                symbol = bridge.create_semantic_symbol(input_data.text)
                if not symbol:
                    raise ValueError("Failed to create semantic symbol")
                
                # Convert to FOL
                conversion_result = bridge.semantic_to_fol(symbol, input_data.output_format)
                
                # Extract components for output
                components_dict = {
                    "quantifiers": conversion_result.components.quantifiers,
                    "predicates": conversion_result.components.predicates,
                    "entities": conversion_result.components.entities,
                    "connectives": conversion_result.components.logical_connectives
                }
                
                # Create output
                output = FOLOutput(
                    fol_formula=conversion_result.fol_formula,
                    confidence=conversion_result.confidence,
                    logical_components=components_dict,
                    reasoning_steps=conversion_result.reasoning_steps,
                    warnings=conversion_result.errors,
                    metadata={
                        "input_format": "natural_language",
                        "output_format": input_data.output_format,
                        "domain_predicates": input_data.domain_predicates,
                        "fallback_used": conversion_result.fallback_used
                    }
                )
                
                return output
                
            except Exception as e:
                logger.error(f"Conversion failed: {e}")
                # Return minimal valid output for error cases
                text_value = getattr(input_data, "text", str(input_data))
                return FOLOutput(
                    fol_formula=f"Error({text_value.replace(' ', '_')})",
                    confidence=0.0,
                    logical_components={"quantifiers": [], "predicates": [], "entities": []},
                    reasoning_steps=[],
                    warnings=[str(e)],
                    metadata={"error": True}
                )
        
        def get_statistics(self) -> Dict[str, Any]:
            """Get conversion statistics."""
            stats = self.conversion_stats.copy()
            if stats["total_conversions"] > 0:
                stats["success_rate"] = stats["successful_conversions"] / stats["total_conversions"]
            else:
                stats["success_rate"] = 0.0
            return stats

else:
    # Fallback implementation without SymbolicAI
    class ContractedFOLConverter:
        """Fallback FOL converter without SymbolicAI contracts."""
        
        def __init__(self):
            self.validator = FOLSyntaxValidator(strict=False)
        
        def __call__(self, input_data: FOLInput) -> FOLOutput:
            """Simple conversion without contracts."""
            try:
                # Basic pattern-based conversion
                text = input_data.text.lower()
                
                if "all " in text or "every " in text:
                    formula = f"∀x Statement(x)"
                elif "some " in text:
                    formula = f"∃x Statement(x)"
                else:
                    formula = f"Statement({text.replace(' ', '_')})"
                
                return FOLOutput(
                    fol_formula=formula,
                    confidence=0.6,
                    logical_components={"quantifiers": [], "predicates": [], "entities": []},
                    reasoning_steps=["Used fallback conversion"],
                    warnings=["SymbolicAI not available - using basic conversion"],
                    metadata={"fallback": True}
                )
                
            except Exception as e:
                return FOLOutput(
                    fol_formula="",
                    confidence=0.0,
                    logical_components={"quantifiers": [], "predicates": [], "entities": []},
                    reasoning_steps=[],
                    warnings=[str(e)],
                    metadata={"error": True}
                )


def create_fol_converter(strict_validation: bool = True) -> ContractedFOLConverter:
    """
    Factory function to create FOL converter.
    
    Args:
        strict_validation: Whether to use strict validation
        
    Returns:
        ContractedFOLConverter instance
    """
    converter = ContractedFOLConverter()
    if hasattr(converter, 'validator'):
        converter.validator.strict = strict_validation
    return converter


def validate_fol_input(text: str, **kwargs) -> FOLInput:
    """
    Helper function to create validated FOL input.
    
    Args:
        text: Input text
        **kwargs: Additional parameters for FOLInput
        
    Returns:
        Validated FOLInput instance
    """
    return FOLInput(text=text, **kwargs)


def test_contracts():
    """Test function for contract system."""
    # Test input validation
    try:
        valid_input = validate_fol_input(
            "All cats are animals",
            confidence_threshold=0.8,
            output_format="symbolic"
        )
        print(f"Valid input created: {valid_input.text}")
    except Exception as e:
        print(f"Input validation error: {e}")
    
    # Test converter
    converter = create_fol_converter()
    
    test_cases = [
        "All cats are animals",
        "Some birds can fly", 
        "If it rains, then the ground is wet",
        "Every student studies hard"
    ]
    
    for test_case in test_cases:
        try:
            input_data = validate_fol_input(test_case)
            result = converter(input_data)
            print(f"Input: {test_case}")
            print(f"Output: {result.fol_formula}")
            print(f"Confidence: {result.confidence}")
            print(f"Valid: {result.validation_results.get('valid', 'Unknown')}")
            print("-" * 50)
        except Exception as e:
            print(f"Error processing '{test_case}': {e}")


if __name__ == "__main__":
    test_contracts()

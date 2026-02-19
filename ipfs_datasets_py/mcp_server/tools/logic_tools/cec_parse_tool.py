"""
CEC Parse Tool - Parse natural language to DCEC formulas.

This tool provides parsing of natural language text into DCEC (Deontic Cognitive Event Calculus)
formulas, supporting multiple languages and domain vocabularies.
"""

from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


def parse_dcec(
    text: str,
    language: str = "en",
    domain: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parse natural language text to DCEC formula.
    
    Args:
        text: Natural language text to parse
        language: Language code (en, es, fr, de)
        domain: Optional domain vocabulary (legal, medical, technical)
    
    Returns:
        Dictionary with:
        - formula: Parsed DCEC formula as string
        - confidence: Confidence score (0-1)
        - language_detected: Detected language if auto-detected
        - parse_tree: Optional parse tree structure
    
    Example:
        >>> result = parse_dcec("The agent must obey the rules", language="en")
        >>> print(result['formula'])
        'O(obey(agent, rules))'
    """
    try:
        from ipfs_datasets_py.logic.CEC.nl import LanguageDetector
        from ipfs_datasets_py.logic.CEC.native import parse_dcec_string
        
        # Detect language if needed
        if language == "auto":
            detector = LanguageDetector()
            language, confidence = detector.detect(text)
            logger.info(f"Detected language: {language} (confidence: {confidence})")
        
        # Get appropriate parser
        # For now, use basic parsing - can be enhanced with language-specific parsers
        try:
            formula = parse_dcec_string(text)
            return {
                "formula": str(formula),
                "confidence": 0.9,
                "language_detected": language,
                "success": True
            }
        except Exception as e:
            logger.warning(f"Parsing failed, returning text representation: {e}")
            return {
                "formula": f"NL({text})",
                "confidence": 0.5,
                "language_detected": language,
                "success": False,
                "error": str(e)
            }
    
    except Exception as e:
        logger.error(f"Error in parse_dcec: {e}")
        return {
            "formula": None,
            "confidence": 0.0,
            "success": False,
            "error": str(e)
        }


def translate_dcec(
    formula: str,
    target_format: str = "tptp"
) -> Dict[str, Any]:
    """
    Translate DCEC formula to another format.
    
    Args:
        formula: DCEC formula string
        target_format: Target format (tptp, z3, json)
    
    Returns:
        Dictionary with:
        - translated: Formula in target format
        - format: Target format used
        - success: Whether translation succeeded
    
    Example:
        >>> result = translate_dcec("O(pay_taxes(agent))", target_format="tptp")
        >>> print(result['translated'])
        'fof(obligation, axiom, obligation(pay_taxes(agent))).'
    """
    try:
        from ipfs_datasets_py.logic.CEC.provers import TPTPConverter
        
        if target_format == "tptp":
            converter = TPTPConverter()
            translated = converter.convert(formula)
            return {
                "translated": translated,
                "format": target_format,
                "success": True
            }
        elif target_format == "json":
            # Return structured JSON representation
            return {
                "translated": {
                    "type": "formula",
                    "content": formula,
                    "format": "dcec"
                },
                "format": target_format,
                "success": True
            }
        else:
            return {
                "translated": None,
                "format": target_format,
                "success": False,
                "error": f"Unsupported format: {target_format}"
            }
    
    except Exception as e:
        logger.error(f"Error in translate_dcec: {e}")
        return {
            "translated": None,
            "format": target_format,
            "success": False,
            "error": str(e)
        }


def validate_formula(formula: str) -> Dict[str, Any]:
    """
    Validate a DCEC formula for syntactic correctness.
    
    Args:
        formula: DCEC formula string to validate
    
    Returns:
        Dictionary with:
        - valid: Whether formula is valid
        - errors: List of validation errors
        - warnings: List of warnings
    
    Example:
        >>> result = validate_formula("O(pay_taxes(agent))")
        >>> print(result['valid'])
        True
    """
    try:
        from ipfs_datasets_py.logic.CEC.native import validate_formula as _validate
        
        is_valid, errors = _validate(formula)
        
        return {
            "valid": is_valid,
            "errors": errors if errors else [],
            "warnings": [],
            "success": True
        }
    
    except Exception as e:
        logger.error(f"Error in validate_formula: {e}")
        return {
            "valid": False,
            "errors": [str(e)],
            "warnings": [],
            "success": False
        }


# Tool metadata for MCP server
TOOLS = {
    "parse_dcec": {
        "function": parse_dcec,
        "description": "Parse natural language text to DCEC formula",
        "parameters": {
            "text": {
                "type": "string",
                "description": "Natural language text to parse",
                "required": True
            },
            "language": {
                "type": "string",
                "description": "Language code (en/es/fr/de/auto)",
                "required": False,
                "default": "en"
            },
            "domain": {
                "type": "string",
                "description": "Domain vocabulary (legal/medical/technical)",
                "required": False
            }
        }
    },
    "translate_dcec": {
        "function": translate_dcec,
        "description": "Translate DCEC formula to another format",
        "parameters": {
            "formula": {
                "type": "string",
                "description": "DCEC formula to translate",
                "required": True
            },
            "target_format": {
                "type": "string",
                "description": "Target format (tptp/z3/json)",
                "required": False,
                "default": "tptp"
            }
        }
    },
    "validate_formula": {
        "function": validate_formula,
        "description": "Validate DCEC formula syntax",
        "parameters": {
            "formula": {
                "type": "string",
                "description": "DCEC formula to validate",
                "required": True
            }
        }
    }
}

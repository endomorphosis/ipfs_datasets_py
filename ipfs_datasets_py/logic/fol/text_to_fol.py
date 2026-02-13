"""
Core conversion: natural language text -> First-Order Logic (FOL).

DEPRECATED: This module provides backward-compatible async interface.
New code should use FOLConverter from .converter module instead.

The convert_text_to_fol() function is maintained for backward compatibility
but internally uses FOLConverter for all conversions.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, Dict, List, Optional, Union

from .converter import FOLConverter

logger = logging.getLogger(__name__)


async def convert_text_to_fol(
    text_input: Union[str, Dict[str, Any]],
    domain_predicates: Optional[List[str]] = None,
    output_format: str = "json",
    confidence_threshold: float = 0.7,
    include_metadata: bool = True,
    use_nlp: bool = True,
) -> Dict[str, Any]:
    """
    Convert natural language text to First-Order Logic (FOL).
    
    DEPRECATED: Use FOLConverter instead for better performance and features.
    
    This function is maintained for backward compatibility. New code should use:
        from ipfs_datasets_py.logic.fol import FOLConverter
        converter = FOLConverter(use_nlp=True, use_cache=True)
        result = await converter.convert_async(text)
    
    Args:
        text_input: Text string or dataset dictionary
        domain_predicates: Optional list of domain-specific predicates
        output_format: Output format (json, prolog, tptp)
        confidence_threshold: Minimum confidence for including results
        include_metadata: Whether to include metadata in output
        use_nlp: Whether to use NLP-enhanced extraction (spaCy) vs regex fallback
        
    Returns:
        Dictionary with FOL formulas and metadata
    """
    # Issue deprecation warning
    warnings.warn(
        "convert_text_to_fol() is deprecated and will be removed in v2.0. "
        "Use FOLConverter instead",
        DeprecationWarning,
        stacklevel=2
    )
    
    try:
        # Handle None input
        if text_input is None:
            text_input = ""
        
        # Extract text from dataset format if needed
        if isinstance(text_input, dict):
            texts = extract_text_from_dataset(text_input)
        elif isinstance(text_input, str):
            stripped = text_input.strip()
            if not stripped:
                return _empty_success_result(output_format, confidence_threshold)
            texts = [stripped]
        else:
            raise ValueError("Text input must be a string or dictionary")
        
        # Check if all texts are empty
        if not texts or all(not t.strip() for t in texts):
            return _empty_success_result(output_format, confidence_threshold)
        
        # Create FOLConverter with appropriate settings
        converter = FOLConverter(
            use_cache=True,
            use_ml=False,  # Use heuristic confidence
            use_nlp=use_nlp,
            enable_monitoring=False,
            confidence_threshold=confidence_threshold,
            output_format=output_format
        )
        
        # Convert all texts
        results = []
        total_processed = 0
        successful_conversions = 0
        
        for text in texts:
            text = text.strip()
            if not text:
                continue
            
            total_processed += 1
            
            # Convert using FOLConverter
            conversion_result = await converter.convert_async(text)
            
            if conversion_result.success:
                successful_conversions += 1
                
                # Convert to legacy dict format
                formula_dict = _convert_result_to_legacy_format(
                    conversion_result,
                    text,
                    output_format,
                    include_metadata
                )
                
                # Only include if confidence meets threshold
                if conversion_result.output and conversion_result.output.confidence >= confidence_threshold:
                    results.append(formula_dict)
        
        # Build summary
        summary = {
            "total_statements": total_processed,
            "successful_conversions": successful_conversions,
            "conversion_rate": successful_conversions / max(1, total_processed),
            "average_confidence": sum(r["confidence"] for r in results) / max(1, len(results)),
            "unique_predicates": list(set(p for r in results for p in r.get("predicates_used", []))),
            "quantifier_distribution": _get_quantifier_distribution(results),
            "operator_distribution": _get_operator_distribution(results),
        }
        
        if total_processed > 0:
            logger.info("Successfully converted %s/%s statements to FOL", successful_conversions, total_processed)
        
        return {
            "status": "success",
            "fol_formulas": results,
            "summary": summary,
            "metadata": {
                "tool": "text_to_fol",
                "version": "1.0.0",
                "output_format": output_format,
                "confidence_threshold": confidence_threshold,
            },
        }
    
    except Exception as exc:
        logger.error(f"Error in convert_text_to_fol: {exc}")
        return {
            "status": "error",
            "message": str(exc),
            "fol_formulas": [],
            "summary": {
                "total_statements": 0,
                "successful_conversions": 0,
                "conversion_rate": 0.0,
                "average_confidence": 0.0,
                "unique_predicates": [],
                "quantifier_distribution": {"∀": 0, "∃": 0},
                "operator_distribution": {"∧": 0, "∨": 0, "→": 0, "↔": 0, "¬": 0},
            },
        }


def _empty_success_result(output_format: str, confidence_threshold: float) -> Dict[str, Any]:
    """Return empty success result for empty input."""
    return {
        "status": "success",
        "fol_formulas": [],
        "summary": {
            "total_statements": 0,
            "successful_conversions": 0,
            "conversion_rate": 0.0,
            "average_confidence": 0.0,
            "unique_predicates": [],
            "quantifier_distribution": {"∀": 0, "∃": 0},
            "operator_distribution": {"∧": 0, "∨": 0, "→": 0, "↔": 0, "¬": 0},
        },
        "metadata": {
            "tool": "text_to_fol",
            "version": "1.0.0",
            "output_format": output_format,
            "confidence_threshold": confidence_threshold,
        },
    }


def _convert_result_to_legacy_format(conversion_result, original_text: str, output_format: str, include_metadata: bool) -> Dict[str, Any]:
    """Convert ConversionResult to legacy dict format."""
    from .utils.fol_parser import convert_to_prolog, convert_to_tptp
    
    fol_formula = conversion_result.output
    
    result = {
        "original_text": original_text,
        "fol_formula": fol_formula.formula_string,
        "confidence": fol_formula.confidence,
        "predicates_used": fol_formula.get_predicate_names(),
        "quantifiers": [q.value if hasattr(q, 'value') else str(q) for q in fol_formula.quantifiers],
        "logical_operators": [op.value if hasattr(op, 'value') else str(op) for op in fol_formula.operators],
    }
    
    if output_format in ["prolog", "all"]:
        result["prolog_form"] = convert_to_prolog(fol_formula.formula_string)
    if output_format in ["tptp", "all"]:
        result["tptp_form"] = convert_to_tptp(fol_formula.formula_string)
    
    if include_metadata:
        result["validation"] = {"valid": True}
        result["linguistic_analysis"] = {
            "predicates": fol_formula.predicates,
            "quantifiers": fol_formula.quantifiers,
            "operators": fol_formula.operators,
            "relations": [],
        }
    
    return result


def _get_quantifier_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """Calculate quantifier distribution from results."""
    distribution = {"∀": 0, "∃": 0}
    for result in results:
        for q in result.get("quantifiers", []):
            q_str = str(q)
            if "∀" in q_str or "forall" in q_str.lower():
                distribution["∀"] += 1
            elif "∃" in q_str or "exists" in q_str.lower():
                distribution["∃"] += 1
    return distribution


def _get_operator_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """Calculate operator distribution from results."""
    distribution = {"∧": 0, "∨": 0, "→": 0, "↔": 0, "¬": 0}
    for result in results:
        formula = result.get("fol_formula", "")
        distribution["∧"] += formula.count("∧") + formula.count("AND")
        distribution["∨"] += formula.count("∨") + formula.count("OR")
        distribution["→"] += formula.count("→") + formula.count("->")
        distribution["↔"] += formula.count("↔") + formula.count("<->")
        distribution["¬"] += formula.count("¬") + formula.count("NOT")
    return distribution


def extract_text_from_dataset(dataset: Dict[str, Any]) -> List[str]:
    """Extract text content from various dataset formats."""
    texts: List[str] = []
    
    if "text" in dataset:
        text = dataset["text"]
        if isinstance(text, str):
            texts.append(text.strip())
        elif isinstance(text, list):
            texts.extend(str(t).strip() for t in text)
    elif "data" in dataset:
        data = dataset["data"]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for key in ["text", "sentence", "content", "statement"]:
                        if key in item:
                            texts.append(str(item[key]).strip())
                            break
                elif isinstance(item, str):
                    texts.append(item.strip())
    elif "sentences" in dataset:
        sentences = dataset["sentences"]
        if isinstance(sentences, list):
            texts.extend(str(s).strip() for s in sentences)
    else:
        for value in dataset.values():
            if isinstance(value, str):
                texts.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        texts.append(item.strip())
    
    return [t for t in texts if t]


# Helper functions maintained for backward compatibility
def calculate_conversion_confidence(text: str, formula: str, predicates: List, quantifiers: List) -> float:
    """Calculate confidence score. DEPRECATED."""
    confidence = 0.5
    if predicates:
        confidence += 0.2
    if quantifiers:
        confidence += 0.15
    if len(formula) > 10:
        confidence += 0.1
    if 10 < len(text) < 500:
        confidence += 0.05
    return min(confidence, 1.0)


def extract_predicate_names(predicates: List) -> List[str]:
    """Extract predicate names. DEPRECATED."""
    names = []
    for p in predicates:
        if isinstance(p, dict):
            names.append(p.get("name", ""))
        elif hasattr(p, 'name'):
            names.append(p.name)
        elif isinstance(p, str):
            names.append(p)
    return [n for n in names if n]


def get_quantifier_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """DEPRECATED: Use _get_quantifier_distribution instead."""
    return _get_quantifier_distribution(results)


def get_operator_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """DEPRECATED: Use _get_operator_distribution instead."""
    return _get_operator_distribution(results)

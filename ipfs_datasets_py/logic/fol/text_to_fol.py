"""Core conversion: natural language text -> First-Order Logic (FOL)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from .utils.predicate_extractor import extract_logical_relations, extract_predicates
from .utils.fol_parser import (
    build_fol_formula,
    convert_to_prolog,
    convert_to_tptp,
    parse_logical_operators,
    parse_quantifiers,
    validate_fol_syntax,
)

logger = logging.getLogger(__name__)


async def convert_text_to_fol(
    text_input: Union[str, Dict[str, Any]],
    domain_predicates: Optional[List[str]] = None,
    output_format: str = "json",
    confidence_threshold: float = 0.7,
    include_metadata: bool = True,
) -> Dict[str, Any]:
    """Convert natural language text to First-Order Logic (FOL)."""
    try:
        # Intentionally avoid per-call logging here to keep batch pipelines quiet.

        if text_input is None:
            text_input = ""
        if not isinstance(confidence_threshold, (int, float)) or not (0 <= confidence_threshold <= 1):
            raise ValueError("Confidence threshold must be a number between 0 and 1")

        if isinstance(text_input, str):
            stripped = text_input.strip()
            if not stripped:
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

            sentences = [stripped]
        elif isinstance(text_input, dict):
            sentences = extract_text_from_dataset(text_input)
        else:
            raise ValueError("Text input must be a string or dictionary")

        if not sentences or all(not s.strip() for s in sentences):
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

        results: List[Dict[str, Any]] = []
        total_processed = 0
        successful_conversions = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            total_processed += 1

            try:
                predicates = extract_predicates(sentence)
                quantifiers = parse_quantifiers(sentence)
                operators = parse_logical_operators(sentence)
                relations = extract_logical_relations(sentence)

                fol_formula = build_fol_formula(quantifiers, predicates, operators, relations)
                confidence = calculate_conversion_confidence(sentence, fol_formula, predicates, quantifiers)
                validation = validate_fol_syntax(fol_formula)

                if confidence >= confidence_threshold and validation["valid"]:
                    successful_conversions += 1

                    formula_result: Dict[str, Any] = {
                        "original_text": sentence,
                        "fol_formula": fol_formula,
                        "confidence": confidence,
                        "predicates_used": extract_predicate_names(predicates),
                        "quantifiers": [q["symbol"] for q in quantifiers],
                        "logical_operators": [op["symbol"] for op in operators],
                    }

                    if output_format in ["prolog", "all"]:
                        formula_result["prolog_form"] = convert_to_prolog(fol_formula)
                    if output_format in ["tptp", "all"]:
                        formula_result["tptp_form"] = convert_to_tptp(fol_formula)

                    if include_metadata:
                        formula_result["validation"] = validation
                        formula_result["linguistic_analysis"] = {
                            "predicates": predicates,
                            "quantifiers": quantifiers,
                            "operators": operators,
                            "relations": relations,
                        }

                    results.append(formula_result)
                else:
                    logger.warning(
                        f"Skipping sentence due to low confidence ({confidence:.2f}) or invalid syntax"
                    )

            except Exception as exc:
                logger.warning(f"Failed to convert sentence '{sentence}': {exc}")
                continue

        summary = {
            "total_statements": total_processed,
            "successful_conversions": successful_conversions,
            "conversion_rate": successful_conversions / max(1, total_processed),
            "average_confidence": sum(r["confidence"] for r in results) / max(1, len(results)),
            "unique_predicates": list(set(p for r in results for p in r["predicates_used"])),
            "quantifier_distribution": get_quantifier_distribution(results),
            "operator_distribution": get_operator_distribution(results),
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
            },
        }


def extract_text_from_dataset(dataset: Dict[str, Any]) -> List[str]:
    """Extract text content from various dataset formats.
    
    This function handles multiple common dataset structures including:
    - Direct text fields
    - Nested data with text/sentence/content keys
    - Lists of sentences
    - Fallback to any string values
    
    Args:
        dataset: Dictionary containing dataset in various formats
        
    Returns:
        List of extracted text strings, stripped of whitespace
        
    Examples:
        >>> extract_text_from_dataset({"text": "Hello world"})
        ["Hello world"]
        >>> extract_text_from_dataset({"data": [{"sentence": "First"}, {"sentence": "Second"}]})
        ["First", "Second"]
    """
    texts: List[str] = []

    if "text" in dataset:
        if isinstance(dataset["text"], str):
            texts.append(dataset["text"])
        elif isinstance(dataset["text"], list):
            texts.extend(str(t) for t in dataset["text"])

    elif "data" in dataset:
        data = dataset["data"]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for key in ["text", "sentence", "content", "statement", "description"]:
                        if key in item and isinstance(item[key], str):
                            texts.append(item[key])
                            break
                elif isinstance(item, str):
                    texts.append(item)

    elif "sentences" in dataset:
        sentences = dataset["sentences"]
        if isinstance(sentences, list):
            texts.extend(str(s) for s in sentences)

    if not texts:
        for value in dataset.values():
            if isinstance(value, str) and value.strip():
                texts.append(value)
                break

    return [t.strip() for t in texts if t and t.strip()]


def extract_predicate_names(predicates: Dict[str, List[str]]) -> List[str]:
    """Extract unique predicate names from categorized predicates dictionary.
    
    Args:
        predicates: Dictionary mapping categories to lists of predicate names
                   e.g., {"entities": ["Person", "Dog"], "actions": ["Run", "Walk"]}
        
    Returns:
        Deduplicated list of all predicate names across all categories
        
    Examples:
        >>> extract_predicate_names({"entities": ["Dog", "Cat"], "actions": ["Run"]})
        ["Dog", "Cat", "Run"]
    """
    names: List[str] = []
    for category in predicates.values():
        names.extend(category)
    return list(set(names))


def calculate_conversion_confidence(
    sentence: str,
    fol_formula: str,
    predicates: Dict[str, List[str]],
    quantifiers: List[Dict[str, Any]],
) -> float:
    """Calculate confidence score for FOL conversion quality.
    
    Uses multiple heuristics to estimate conversion quality:
    - Predicate count (up to 0.3)
    - Quantifier presence (up to 0.2)
    - Complexity match between sentence and formula (up to 0.2)
    - Logical indicator count (up to 0.2)
    - Syntax validity (0.1)
    - Bonus for clean quantified statements (0.1)
    
    Args:
        sentence: Original natural language sentence
        fol_formula: Generated first-order logic formula
        predicates: Dictionary of extracted predicates by category
        quantifiers: List of identified quantifiers
        
    Returns:
        Confidence score between 0.0 and 1.0
        
    Examples:
        >>> calculate_conversion_confidence(
        ...     "All dogs are mammals",
        ...     "∀x (Dog(x) → Mammal(x))",
        ...     {"entities": ["Dog", "Mammal"]},
        ...     [{"type": "universal"}]
        ... )
        0.9  # High confidence
    """
    score = 0.0

    total_predicates = sum(len(preds) for preds in predicates.values())
    if total_predicates > 0:
        score += min(0.3, total_predicates * 0.1)

    if quantifiers:
        score += min(0.2, len(quantifiers) * 0.1)

    sentence_complexity = estimate_sentence_complexity(sentence)
    formula_complexity = estimate_formula_complexity(fol_formula)

    complexity_match = 1 - abs(sentence_complexity - formula_complexity) / max(
        sentence_complexity, formula_complexity, 1
    )
    score += complexity_match * 0.2

    indicators = ["all", "every", "some", "if", "then", "and", "or", "not"]
    indicator_count = count_indicators(sentence, indicators)
    score += min(0.2, indicator_count * 0.05)

    is_valid = validate_fol_syntax(fol_formula)["valid"]
    if is_valid:
        score += 0.1

    # Heuristic boost for simple quantified statements that parse cleanly.
    # This avoids under-scoring sentences like "All X are Y" that are otherwise
    # highly reliable conversions.
    if is_valid and quantifiers and total_predicates > 0:
        score += 0.1

    return min(1.0, score)


def estimate_sentence_complexity(sentence: str) -> int:
    """Estimate complexity of natural language sentence by token count.
    
    Args:
        sentence: Natural language sentence
        
    Returns:
        Number of space-separated tokens
    """
    tokens = sentence.split()
    return len(tokens)


def estimate_formula_complexity(formula: str) -> int:
    """Estimate complexity of FOL formula by operator count.
    
    Counts logical operators: ∀, ∃, ∧, ∨, →, ↔, ¬
    
    Args:
        formula: First-order logic formula string
        
    Returns:
        Sum of all logical operators plus 1
    """
    return sum(formula.count(sym) for sym in ["∀", "∃", "∧", "∨", "→", "↔", "¬"]) + 1


def count_indicators(sentence: str, indicators: List[str]) -> int:
    """Count occurrences of logical indicator words in sentence.
    
    Args:
        sentence: Natural language sentence
        indicators: List of indicator words to count (e.g., ["all", "some", "if"])
        
    Returns:
        Total count of all indicators found (case-insensitive)
    """
    sentence_lower = sentence.lower()
    return sum(sentence_lower.count(ind) for ind in indicators)


def get_quantifier_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """Calculate distribution of quantifiers across conversion results.
    
    Args:
        results: List of FOL conversion result dictionaries
        
    Returns:
        Dictionary mapping quantifier symbols to counts {"∀": count, "∃": count}
    """
    distribution = {"∀": 0, "∃": 0}
    for result in results:
        for quantifier in result.get("quantifiers", []):
            if quantifier in distribution:
                distribution[quantifier] += 1
    return distribution


def get_operator_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """Calculate distribution of logical operators across conversion results.
    
    Args:
        results: List of FOL conversion result dictionaries
        
    Returns:
        Dictionary mapping operator symbols to counts {"∧": count, "∨": count, ...}
    """
    distribution = {"∧": 0, "∨": 0, "→": 0, "↔": 0, "¬": 0}
    for result in results:
        for operator in result.get("logical_operators", []):
            if operator in distribution:
                distribution[operator] += 1
    return distribution

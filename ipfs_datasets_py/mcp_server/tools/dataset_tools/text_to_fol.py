# ipfs_datasets_py/mcp_server/tools/dataset_tools/text_to_fol.py
"""
MCP tool for converting natural language text to First-Order Logic (FOL).

This tool converts natural language statements into formal first-order logic
representations for automated reasoning, theorem proving, and logical analysis.
"""
import anyio
from typing import Dict, Any, Optional, Union, List
import re

from ipfs_datasets_py.mcp_server.logger import logger
from .logic_utils.predicate_extractor import extract_predicates, extract_logical_relations, extract_variables
from .logic_utils.fol_parser import parse_quantifiers, parse_logical_operators, build_fol_formula, validate_fol_syntax, convert_to_prolog, convert_to_tptp
from .logic_utils.logic_formatter import format_fol, format_output

async def convert_text_to_fol(
    text_input: Union[str, Dict[str, Any]],
    domain_predicates: Optional[List[str]] = None,
    output_format: str = 'json',
    confidence_threshold: float = 0.7,
    include_metadata: bool = True
) -> Dict[str, Any]:
    """
    Convert natural language text to First-Order Logic.

    This tool converts natural language statements into First-Order Logic (FOL)
    formulas for formal reasoning, theorem proving, and logical analysis.

    Args:
        text_input: String or dataset containing natural language text
        domain_predicates: Optional list of domain-specific predicates
        output_format: Format for FOL output ('prolog', 'tptp', 'json', 'symbolic')
        confidence_threshold: Minimum confidence for conversion (0.0-1.0)
        include_metadata: Whether to include conversion metadata

    Returns:
        Dict containing:
        - status: "success" or "error"
        - fol_formulas: List of converted formulas with metadata
        - summary: Conversion statistics and analysis
        - message: Error message if status is "error"

    Raises:
        ValueError: If text_input is invalid or parameters are malformed
    """
    try:
        logger.info(f"Converting text to FOL with format {output_format}")

        # Input validation
        if not text_input:
            raise ValueError("Text input cannot be empty")
        
        if not isinstance(confidence_threshold, (int, float)) or not (0 <= confidence_threshold <= 1):
            raise ValueError("Confidence threshold must be a number between 0 and 1")

        # Extract text data
        if isinstance(text_input, str):
            sentences = [text_input.strip()]
        elif isinstance(text_input, dict):
            sentences = extract_text_from_dataset(text_input)
        else:
            raise ValueError("Text input must be a string or dictionary")

        if not sentences or all(not s.strip() for s in sentences):
            raise ValueError("No valid text found in input")

        results = []
        total_processed = 0
        successful_conversions = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            total_processed += 1
            logger.info(f"Processing sentence {total_processed}: {sentence[:50]}...")

            try:
                # Extract linguistic components
                predicates = extract_predicates(sentence)
                quantifiers = parse_quantifiers(sentence)
                operators = parse_logical_operators(sentence)
                relations = extract_logical_relations(sentence)

                # Generate FOL formula
                fol_formula = build_fol_formula(quantifiers, predicates, operators, relations)

                # Calculate confidence score
                confidence = calculate_conversion_confidence(sentence, fol_formula, predicates, quantifiers)

                # Validate formula syntax
                validation = validate_fol_syntax(fol_formula)

                if confidence >= confidence_threshold and validation["valid"]:
                    successful_conversions += 1

                    # Format output based on requested format
                    formula_result = {
                        "original_text": sentence,
                        "fol_formula": fol_formula,
                        "confidence": confidence,
                        "predicates_used": extract_predicate_names(predicates),
                        "quantifiers": [q["symbol"] for q in quantifiers],
                        "logical_operators": [op["symbol"] for op in operators]
                    }

                    # Add alternative formats
                    if output_format in ['prolog', 'all']:
                        formula_result["prolog_form"] = convert_to_prolog(fol_formula)
                    
                    if output_format in ['tptp', 'all']:
                        formula_result["tptp_form"] = convert_to_tptp(fol_formula)

                    if include_metadata:
                        formula_result["validation"] = validation
                        formula_result["linguistic_analysis"] = {
                            "predicates": predicates,
                            "quantifiers": quantifiers,
                            "operators": operators,
                            "relations": relations
                        }

                    results.append(formula_result)

                else:
                    logger.warning(f"Skipping sentence due to low confidence ({confidence:.2f}) or invalid syntax")

            except Exception as e:
                logger.warning(f"Failed to convert sentence '{sentence}': {e}")
                continue

        # Generate summary
        summary = {
            "total_statements": total_processed,
            "successful_conversions": successful_conversions,
            "conversion_rate": successful_conversions / max(1, total_processed),
            "average_confidence": sum(r["confidence"] for r in results) / max(1, len(results)),
            "unique_predicates": list(set(p for r in results for p in r["predicates_used"])),
            "quantifier_distribution": get_quantifier_distribution(results),
            "operator_distribution": get_operator_distribution(results)
        }

        logger.info(f"Successfully converted {successful_conversions}/{total_processed} statements to FOL")

        return {
            "status": "success",
            "fol_formulas": results,
            "summary": summary,
            "metadata": {
                "tool": "text_to_fol",
                "version": "1.0.0",
                "output_format": output_format,
                "confidence_threshold": confidence_threshold
            }
        }

    except Exception as e:
        logger.error(f"Error in convert_text_to_fol: {e}")
        return {
            "status": "error",
            "message": str(e),
            "fol_formulas": [],
            "summary": {
                "total_statements": 0,
                "successful_conversions": 0,
                "conversion_rate": 0.0,
                "average_confidence": 0.0
            }
        }

def extract_text_from_dataset(dataset: Dict[str, Any]) -> List[str]:
    """Extract text strings from dataset dictionary."""
    texts = []
    
    # Handle different dataset structures
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
                    # Look for text fields
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
    
    # Fallback: look for any string values
    if not texts:
        for value in dataset.values():
            if isinstance(value, str) and len(value.strip()) > 0:
                texts.append(value)
                break
    
    return [t.strip() for t in texts if t and t.strip()]

def extract_predicate_names(predicates: Dict[str, List[str]]) -> List[str]:
    """Extract all predicate names from predicates dictionary."""
    names = []
    for category in predicates.values():
        names.extend(category)
    return list(set(names))

def calculate_conversion_confidence(
    sentence: str, 
    fol_formula: str, 
    predicates: Dict[str, List[str]], 
    quantifiers: List[Dict[str, Any]]
) -> float:
    """
    Calculate confidence score for FOL conversion.
    
    Args:
        sentence: Original sentence
        fol_formula: Generated FOL formula
        predicates: Extracted predicates
        quantifiers: Parsed quantifiers
        
    Returns:
        Confidence score between 0.0 and 1.0
    """
    score = 0.0
    factors = []

    # Factor 1: Predicate extraction quality (0-0.3)
    total_predicates = sum(len(preds) for preds in predicates.values())
    if total_predicates > 0:
        predicate_score = min(0.3, total_predicates * 0.1)
        factors.append(("predicates", predicate_score))
        score += predicate_score

    # Factor 2: Quantifier detection (0-0.2)
    if quantifiers:
        quantifier_score = min(0.2, len(quantifiers) * 0.1)
        factors.append(("quantifiers", quantifier_score))
        score += quantifier_score

    # Factor 3: Formula complexity appropriateness (0-0.2)
    sentence_complexity = estimate_sentence_complexity(sentence)
    formula_complexity = estimate_formula_complexity(fol_formula)
    
    complexity_match = 1 - abs(sentence_complexity - formula_complexity) / max(sentence_complexity, formula_complexity, 1)
    complexity_score = complexity_match * 0.2
    factors.append(("complexity_match", complexity_score))
    score += complexity_score

    # Factor 4: Logical structure detection (0-0.2)
    logical_indicators = count_logical_indicators(sentence)
    if logical_indicators > 0:
        logical_score = min(0.2, logical_indicators * 0.1)
        factors.append(("logical_structure", logical_score))
        score += logical_score

    # Factor 5: Formula validity (0-0.1)
    validation = validate_fol_syntax(fol_formula)
    if validation["valid"]:
        validity_score = 0.1
        factors.append(("validity", validity_score))
        score += validity_score

    # Base confidence for any successful parsing
    base_score = 0.2
    factors.append(("base", base_score))
    score += base_score

    return min(1.0, score)

def estimate_sentence_complexity(sentence: str) -> float:
    """Estimate the logical complexity of a sentence."""
    complexity = 0.0
    
    # Count logical indicators
    logical_words = ['all', 'some', 'every', 'no', 'none', 'if', 'then', 'and', 'or', 'not', 'unless']
    for word in logical_words:
        complexity += sentence.lower().count(word) * 0.1
    
    # Count clause separators
    complexity += sentence.count(',') * 0.05
    complexity += sentence.count(';') * 0.1
    
    # Sentence length factor
    complexity += len(sentence.split()) * 0.01
    
    return min(1.0, complexity)

def estimate_formula_complexity(formula: str) -> float:
    """Estimate the complexity of a FOL formula."""
    complexity = 0.0
    
    # Count quantifiers
    complexity += formula.count('∀') * 0.2
    complexity += formula.count('∃') * 0.2
    
    # Count logical operators
    operators = ['∧', '∨', '→', '↔', '¬']
    for op in operators:
        complexity += formula.count(op) * 0.1
    
    # Count predicates
    predicate_matches = re.findall(r'[A-Z][a-zA-Z]*\(', formula)
    complexity += len(predicate_matches) * 0.1
    
    # Nesting depth (count parentheses depth)
    max_depth = 0
    current_depth = 0
    for char in formula:
        if char == '(':
            current_depth += 1
            max_depth = max(max_depth, current_depth)
        elif char == ')':
            current_depth -= 1
    
    complexity += max_depth * 0.05
    
    return min(1.0, complexity)

def count_logical_indicators(sentence: str) -> int:
    """Count logical indicator words in sentence."""
    indicators = [
        'all', 'every', 'each', 'any', 'some', 'there is', 'there are',
        'if', 'then', 'when', 'whenever', 'unless', 'except',
        'and', 'or', 'but', 'however', 'not', 'no', 'none', 'never'
    ]
    
    sentence_lower = sentence.lower()
    count = 0
    for indicator in indicators:
        count += sentence_lower.count(indicator)
    
    return count

def get_quantifier_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """Get distribution of quantifier types in results."""
    distribution = {"∀": 0, "∃": 0}
    
    for result in results:
        for quantifier in result.get("quantifiers", []):
            if quantifier in distribution:
                distribution[quantifier] += 1
    
    return distribution

def get_operator_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """Get distribution of logical operators in results."""
    distribution = {"∧": 0, "∨": 0, "→": 0, "↔": 0, "¬": 0}
    
    for result in results:
        for operator in result.get("logical_operators", []):
            if operator in distribution:
                distribution[operator] += 1
    
    return distribution

# MCP tool function with expected name
async def text_to_fol(
    text_input: Union[str, Dict[str, Any]],
    domain_predicates: Optional[List[str]] = None,
    output_format: str = 'json',
    include_metadata: bool = True,
    confidence_threshold: float = 0.5
) -> Dict[str, Any]:
    """
    MCP tool function for converting text to FOL.
    
    Args:
        text_input: Natural language text or dataset to convert
        domain_predicates: Optional list of domain-specific predicates
        output_format: Output format ('json', 'prolog', 'tptp')
        include_metadata: Whether to include metadata in results
        confidence_threshold: Minimum confidence score for results
        
    Returns:
        Dict with conversion results
    """
    return await convert_text_to_fol(
        text_input=text_input,
        domain_predicates=domain_predicates,
        output_format=output_format,
        include_metadata=include_metadata,
        confidence_threshold=confidence_threshold
    )

# Async main function for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "Text to FOL converter tool initialized",
        "tool": "text_to_fol",
        "description": "Converts natural language text to First-Order Logic formulas"
    }

if __name__ == "__main__":
    # Example usage
    test_result = anyio.run(convert_text_to_fol(
        "All cats are animals",
        output_format='json',
        include_metadata=True
    ))
    print(f"Test result: {test_result}")

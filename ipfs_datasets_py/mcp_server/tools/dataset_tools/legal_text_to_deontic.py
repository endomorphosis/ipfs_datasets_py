# ipfs_datasets_py/mcp_server/tools/dataset_tools/legal_text_to_deontic.py
"""
MCP tool for converting legal text to deontic logic.

This tool converts legal text (statutes, regulations, contracts) into deontic
logic for legal reasoning, compliance checking, and normative analysis.
"""
import anyio
from typing import Dict, Any, Optional, Union, List
import re
from datetime import datetime

from ipfs_datasets_py.mcp_server.logger import logger
from .logic_utils.deontic_parser import (
    extract_normative_elements, analyze_normative_sentence, build_deontic_formula,
    identify_obligations, detect_normative_conflicts
)
from .logic_utils.logic_formatter import format_deontic, format_output

async def convert_legal_text_to_deontic(
    legal_text: Union[str, Dict[str, Any]],
    jurisdiction: str = 'us',
    document_type: str = 'statute',
    output_format: str = 'json',
    extract_obligations: bool = True,
    include_exceptions: bool = True
) -> Dict[str, Any]:
    """
    Convert legal text to deontic logic.

    This tool converts legal text (statutes, regulations, contracts) into deontic
    logic for legal reasoning, compliance checking, and normative analysis.

    Args:
        legal_text: String or dataset containing legal text
        jurisdiction: Legal jurisdiction context ('us', 'eu', 'uk', 'international')
        document_type: Type of legal document ('statute', 'regulation', 'contract', 'policy')
        output_format: Format for deontic logic output ('symbolic', 'defeasible', 'json')
        extract_obligations: Whether to extract obligation structures
        include_exceptions: Whether to include exception handling

    Returns:
        Dict containing:
        - status: "success" or "error"
        - deontic_formulas: List of converted formulas with metadata
        - normative_structure: Analysis of normative relationships
        - legal_entities: Identified legal subjects
        - actions: Extracted legal actions
        - temporal_constraints: Time-based requirements
        - message: Error message if status is "error"

    Raises:
        ValueError: If legal_text is invalid or parameters are malformed
    """
    try:
        logger.info(f"Converting legal text to deontic logic for {jurisdiction} {document_type}")

        # Input validation
        if not legal_text:
            raise ValueError("Legal text input cannot be empty")
        
        if jurisdiction not in ['us', 'eu', 'uk', 'international', 'general']:
            logger.warning(f"Unknown jurisdiction '{jurisdiction}', using 'general'")
            jurisdiction = 'general'
        
        if document_type not in ['statute', 'regulation', 'contract', 'policy', 'agreement', 'general']:
            logger.warning(f"Unknown document type '{document_type}', using 'general'")
            document_type = 'general'

        # Extract legal text data
        if isinstance(legal_text, str):
            sections = [legal_text.strip()]
        elif isinstance(legal_text, dict):
            sections = extract_legal_text_from_dataset(legal_text)
        else:
            raise ValueError("Legal text input must be a string or dictionary")

        if not sections or all(not s.strip() for s in sections):
            raise ValueError("No valid legal text found in input")

        results = []
        all_normative_elements = []
        total_processed = 0
        successful_conversions = 0

        for section in sections:
            section = section.strip()
            if not section:
                continue

            logger.info(f"Processing legal section: {section[:100]}...")

            try:
                # Extract normative elements from the section
                normative_elements = extract_normative_elements(section, document_type)
                all_normative_elements.extend(normative_elements)

                for element in normative_elements:
                    total_processed += 1

                    try:
                        # Generate deontic logic formula
                        deontic_formula = build_deontic_formula(element)

                        # Calculate confidence score
                        confidence = calculate_deontic_confidence(element, deontic_formula)

                        if confidence > 0.5:  # Minimum threshold for legal text
                            successful_conversions += 1

                            formula_result = {
                                "original_text": element["text"],
                                "deontic_formula": deontic_formula,
                                "obligation_type": element["norm_type"],
                                "deontic_operator": element["deontic_operator"],
                                "subject": element.get("subject", []),
                                "action": element.get("action", []),
                                "conditions": element.get("conditions", []),
                                "temporal_constraints": element.get("temporal_constraints", []),
                                "exceptions": element.get("exceptions", []),
                                "confidence": confidence,
                                "jurisdiction": jurisdiction,
                                "document_type": document_type
                            }

                            # Add alternative formats if requested
                            if output_format in ['defeasible', 'all']:
                                formula_result["defeasible_form"] = convert_to_defeasible_logic(
                                    deontic_formula, element["norm_type"], element.get("exceptions", [])
                                )

                            results.append(formula_result)

                    except Exception as e:
                        logger.warning(f"Failed to convert normative element: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Failed to process legal section '{section[:50]}...': {e}")
                continue

        # Analyze normative structure
        if extract_obligations:
            normative_structure = identify_obligations(all_normative_elements)
        else:
            normative_structure = {"obligations": [], "permissions": [], "prohibitions": []}

        # Detect conflicts if we have multiple norms
        conflicts = detect_normative_conflicts(all_normative_elements) if len(all_normative_elements) > 1 else []

        # Extract entities, actions, and temporal constraints
        legal_entities = extract_all_legal_entities(results)
        legal_actions = extract_all_legal_actions(results)
        temporal_constraints = extract_all_temporal_constraints(results)

        # Generate summary
        summary = {
            "total_normative_statements": total_processed,
            "successful_conversions": successful_conversions,
            "conversion_rate": successful_conversions / max(1, total_processed),
            "average_confidence": sum(r["confidence"] for r in results) / max(1, len(results)),
            "normative_distribution": {
                "obligations": sum(1 for r in results if r["obligation_type"] == "obligation"),
                "permissions": sum(1 for r in results if r["obligation_type"] == "permission"),
                "prohibitions": sum(1 for r in results if r["obligation_type"] == "prohibition")
            },
            "conflicts_detected": len(conflicts),
            "unique_entities": len(set(legal_entities)),
            "unique_actions": len(set(legal_actions))
        }

        logger.info(f"Successfully converted {successful_conversions}/{total_processed} legal statements to deontic logic")

        return {
            "status": "success",
            "deontic_formulas": results,
            "normative_structure": normative_structure,
            "legal_entities": legal_entities,
            "actions": legal_actions,
            "temporal_constraints": temporal_constraints,
            "conflicts": conflicts,
            "summary": summary,
            "metadata": {
                "tool": "legal_text_to_deontic",
                "version": "1.0.0",
                "jurisdiction": jurisdiction,
                "document_type": document_type,
                "output_format": output_format,
                "processing_timestamp": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error in convert_legal_text_to_deontic: {e}")
        return {
            "status": "error",
            "message": str(e),
            "deontic_formulas": [],
            "normative_structure": {"obligations": [], "permissions": [], "prohibitions": []},
            "legal_entities": [],
            "actions": [],
            "temporal_constraints": [],
            "conflicts": [],
            "summary": {
                "total_normative_statements": 0,
                "successful_conversions": 0,
                "conversion_rate": 0.0,
                "average_confidence": 0.0
            }
        }

def extract_legal_text_from_dataset(dataset: Dict[str, Any]) -> List[str]:
    """Extract legal text strings from dataset dictionary."""
    texts = []
    
    # Handle different dataset structures for legal documents
    legal_text_fields = [
        "text", "legal_text", "statute", "regulation", "contract_text",
        "clause", "provision", "section", "article", "content", "body"
    ]
    
    for field in legal_text_fields:
        if field in dataset:
            value = dataset[field]
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, list):
                texts.extend(str(t) for t in value)
    
    # Handle nested data structures
    if "data" in dataset:
        data = dataset["data"]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for field in legal_text_fields:
                        if field in item and isinstance(item[field], str):
                            texts.append(item[field])
                elif isinstance(item, str):
                    texts.append(item)
    
    # Handle sections or paragraphs
    if "sections" in dataset:
        sections = dataset["sections"]
        if isinstance(sections, list):
            texts.extend(str(s) for s in sections)
    
    return [t.strip() for t in texts if t and t.strip()]

def calculate_deontic_confidence(element: Dict[str, Any], deontic_formula: str) -> float:
    """
    Calculate confidence score for deontic logic conversion.
    
    Args:
        element: Normative element dictionary
        deontic_formula: Generated deontic logic formula
        
    Returns:
        Confidence score between 0.0 and 1.0
    """
    score = 0.0

    # Factor 1: Clear normative operator identification (0-0.3)
    if element.get("deontic_operator") in ["O", "P", "F"]:
        score += 0.3

    # Factor 2: Subject identification (0-0.2)
    subjects = element.get("subject", [])
    if subjects and any(len(s.strip()) > 0 for s in subjects):
        score += 0.2

    # Factor 3: Action identification (0-0.2)
    actions = element.get("action", [])
    if actions and any(len(a.strip()) > 0 for a in actions):
        score += 0.2

    # Factor 4: Legal structure indicators (0-0.15)
    text = element.get("text", "").lower()
    legal_indicators = [
        "shall", "must", "required", "obligated", "duty", "may", "permitted",
        "allowed", "entitled", "forbidden", "prohibited", "cannot", "must not"
    ]
    
    found_indicators = sum(1 for indicator in legal_indicators if indicator in text)
    if found_indicators > 0:
        score += min(0.15, found_indicators * 0.05)

    # Factor 5: Temporal constraints (0-0.1)
    temporal_constraints = element.get("temporal_constraints", [])
    if temporal_constraints:
        score += 0.1

    # Factor 6: Condition complexity (0-0.05)
    conditions = element.get("conditions", [])
    if conditions:
        score += 0.05

    # Base score for any identified normative statement
    score += 0.1

    return min(1.0, score)

def convert_to_defeasible_logic(
    deontic_formula: str, 
    norm_type: str, 
    exceptions: List[str]
) -> str:
    """
    Convert deontic logic formula to defeasible logic representation.
    
    Args:
        deontic_formula: Original deontic logic formula
        norm_type: Type of norm (obligation, permission, prohibition)
        exceptions: List of exceptions
        
    Returns:
        Defeasible logic formula string
    """
    # Extract the core logical content from the deontic formula
    core_content = re.search(r'[OPF]\((.+)\)$', deontic_formula)
    if core_content:
        logical_part = core_content.group(1)
    else:
        logical_part = deontic_formula

    if norm_type == "obligation":
        base_rule = f"obligatory({logical_part})"
    elif norm_type == "permission":
        base_rule = f"permitted({logical_part})"
    elif norm_type == "prohibition":
        base_rule = f"forbidden({logical_part})"
    else:
        base_rule = f"norm({logical_part})"

    # Add exceptions as defeaters
    if exceptions:
        exception_conditions = " ∧ ".join(f"¬{normalize_exception(exc)}" for exc in exceptions)
        return f"{base_rule} :- {exception_conditions}."
    else:
        return f"{base_rule} unless defeated."

def normalize_exception(exception: str) -> str:
    """Normalize exception text into a logical predicate."""
    # Simple normalization - would be more sophisticated in production
    words = re.sub(r'[^\w\s]', '', exception).split()
    filtered_words = [w for w in words if len(w) > 2]  # Remove short words
    
    if filtered_words:
        return ''.join(word.capitalize() for word in filtered_words[:3])  # Limit length
    else:
        return "Exception"

def extract_all_legal_entities(results: List[Dict[str, Any]]) -> List[str]:
    """Extract all unique legal entities from results."""
    entities = set()
    
    for result in results:
        subjects = result.get("subject", [])
        for subject in subjects:
            if isinstance(subject, str) and subject.strip():
                entities.add(subject.strip())
    
    return sorted(list(entities))

def extract_all_legal_actions(results: List[Dict[str, Any]]) -> List[str]:
    """Extract all unique legal actions from results."""
    actions = set()
    
    for result in results:
        action_list = result.get("action", [])
        for action in action_list:
            if isinstance(action, str) and action.strip():
                actions.add(action.strip())
    
    return sorted(list(actions))

def extract_all_temporal_constraints(results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Extract all temporal constraints from results."""
    constraints = []
    
    for result in results:
        temporal_list = result.get("temporal_constraints", [])
        for constraint in temporal_list:
            if isinstance(constraint, dict):
                constraints.append(constraint)
            elif isinstance(constraint, str) and constraint.strip():
                constraints.append({"type": "general", "value": constraint.strip()})
    
    # Remove duplicates while preserving order
    seen = set()
    unique_constraints = []
    for constraint in constraints:
        constraint_str = str(constraint)
        if constraint_str not in seen:
            seen.add(constraint_str)
            unique_constraints.append(constraint)
    
    return unique_constraints

# MCP tool function with expected name
async def legal_text_to_deontic(
    text_input: Union[str, Dict[str, Any]],
    jurisdiction: str = 'us',
    document_type: str = 'statute',
    output_format: str = 'json',
    extract_obligations: bool = True,
    include_exceptions: bool = True
) -> Dict[str, Any]:
    """
    MCP tool function for converting legal text to deontic logic.
    
    Args:
        text_input: Legal text or dataset to convert
        jurisdiction: Legal jurisdiction context
        document_type: Type of legal document
        output_format: Output format for the results
        extract_obligations: Whether to extract obligation statements
        include_exceptions: Whether to include exception handling
        
    Returns:
        Dict with conversion results
    """
    return await convert_legal_text_to_deontic(
        legal_text=text_input,
        jurisdiction=jurisdiction,
        document_type=document_type,
        output_format=output_format,
        extract_obligations=extract_obligations,
        include_exceptions=include_exceptions
    )

# Async main function for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "Legal text to deontic logic converter tool initialized",
        "tool": "legal_text_to_deontic",
        "description": "Converts legal text to deontic logic formulas for legal reasoning"
    }

if __name__ == "__main__":
    # Example usage
    test_result = anyio.run(convert_legal_text_to_deontic(
        "Citizens must pay taxes by April 15th",
        jurisdiction='us',
        document_type='statute'
    ))
    print(f"Test result: {test_result}")

# ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/logic_formatter.py
"""
Logic formatting utilities for output generation.
"""
import json
from typing import Dict, Any, List, Union

def format_fol(
    formula: str,
    output_format: str = 'symbolic',
    include_metadata: bool = True
) -> Dict[str, Any]:
    """
    Format First-Order Logic formula for output.
    
    Args:
        formula: FOL formula string
        output_format: Output format ('symbolic', 'prolog', 'tptp', 'json')
        include_metadata: Whether to include metadata
        
    Returns:
        Formatted output dictionary
    """
    result: Dict[str, Any] = {
        "fol_formula": formula,
        "format": output_format
    }
    
    if output_format == 'prolog':
        result["prolog_form"] = convert_to_prolog_format(formula)
    elif output_format == 'tptp':
        result["tptp_form"] = convert_to_tptp_format(formula)
    elif output_format == 'json':
        result["structured_form"] = parse_fol_to_json(formula)
    
    if include_metadata:
        result["metadata"] = extract_fol_metadata(formula)
    
    return result

def format_deontic(
    formula: str,
    norm_type: str,
    output_format: str = 'symbolic',
    include_metadata: bool = True
) -> Dict[str, Any]:
    """
    Format deontic logic formula for output.
    
    Args:
        formula: Deontic logic formula string
        norm_type: Type of norm ('obligation', 'permission', 'prohibition')
        output_format: Output format ('symbolic', 'defeasible', 'json')
        include_metadata: Whether to include metadata
        
    Returns:
        Formatted output dictionary
    """
    result: Dict[str, Any] = {
        "deontic_formula": formula,
        "norm_type": norm_type,
        "format": output_format
    }
    
    if output_format == 'defeasible':
        result["defeasible_form"] = convert_to_defeasible_format(formula, norm_type)
    elif output_format == 'json':
        result["structured_form"] = parse_deontic_to_json(formula)
    
    if include_metadata:
        result["metadata"] = extract_deontic_metadata(formula, norm_type)
    
    return result

def format_output(
    formulas: List[Dict[str, Any]], 
    summary: Dict[str, Any],
    output_format: str = 'json'
) -> Union[Dict[str, Any], str]:
    """
    Format complete output for logic conversion tools.
    
    Args:
        formulas: List of converted formulas
        summary: Summary statistics
        output_format: Overall output format
        
    Returns:
        Formatted output
    """
    if output_format == 'json':
        return {
            "status": "success",
            "formulas": formulas,
            "summary": summary,
            "metadata": {
                "conversion_timestamp": get_timestamp(),
                "tool_version": "1.0.0"
            }
        }
    elif output_format == 'text':
        return format_text_output(formulas, summary)
    elif output_format == 'xml':
        return format_xml_output(formulas, summary)
    else:
        return {"error": f"Unsupported output format: {output_format}"}

def convert_to_prolog_format(fol_formula: str) -> str:
    """Convert FOL to Prolog format."""
    # Simplified conversion - would be more sophisticated in production
    import re
    
    # Universal implication: ∀x (P(x) → Q(x)) becomes Q(X) :- P(X).
    universal_impl = re.search(r'∀(\w+)\s*\((\w+)\((\w+)\)\s*→\s*(\w+)\((\w+)\)\)', fol_formula)
    if universal_impl:
        var, pred1, var1, pred2, var2 = universal_impl.groups()
        return f"{pred2.lower()}({var.upper()}) :- {pred1.lower()}({var.upper()})."
    
    # Simple existential: ∃x P(x) becomes P(a).
    existential = re.search(r'∃(\w+)\s*(\w+)\((\w+)\)', fol_formula)
    if existential:
        var, pred, var2 = existential.groups()
        return f"{pred.lower()}(a)."
    
    return f"% {fol_formula}"

def convert_to_tptp_format(fol_formula: str) -> str:
    """Convert FOL to TPTP format."""
    tptp = fol_formula
    tptp = tptp.replace('∀', '![')
    tptp = tptp.replace('∃', '?[')
    tptp = tptp.replace('∧', ' & ')
    tptp = tptp.replace('∨', ' | ')
    tptp = tptp.replace('→', ' => ')
    tptp = tptp.replace('↔', ' <=> ')
    tptp = tptp.replace('¬', '~')
    
    # Fix variable syntax
    import re
    tptp = re.sub(r'(\![a-z]|\?[a-z])', r'\1]:', tptp)
    
    return f"fof(formula, axiom, {tptp})."

def convert_to_defeasible_format(deontic_formula: str, norm_type: str) -> str:
    """Convert deontic logic to defeasible logic format."""
    # Simplified defeasible logic representation
    if norm_type == "obligation":
        return f"obligatory({deontic_formula}) unless defeated."
    elif norm_type == "permission":
        return f"permitted({deontic_formula}) unless forbidden."
    elif norm_type == "prohibition":
        return f"forbidden({deontic_formula}) unless permitted."
    else:
        return f"norm({deontic_formula})."

def parse_fol_to_json(fol_formula: str) -> Dict[str, Any]:
    """Parse FOL formula into structured JSON."""
    import re
    
    structure = {
        "quantifiers": [],
        "predicates": [],
        "variables": [],
        "operators": []
    }
    
    # Extract quantifiers
    quantifiers = re.findall(r'([∀∃])([a-z])', fol_formula)
    for symbol, var in quantifiers:
        structure["quantifiers"].append({
            "type": "universal" if symbol == "∀" else "existential",
            "variable": var,
            "symbol": symbol
        })
    
    # Extract predicates
    predicates = re.findall(r'([A-Z][a-zA-Z]*)\(([^)]+)\)', fol_formula)
    for name, args in predicates:
        structure["predicates"].append({
            "name": name,
            "arity": len(args.split(',')),
            "arguments": args.split(',')
        })
    
    # Extract variables
    variables = set(re.findall(r'\b([a-z])\b', fol_formula))
    structure["variables"] = list(variables)
    
    # Extract operators
    operators = []
    if '∧' in fol_formula:
        operators.append({"type": "conjunction", "symbol": "∧"})
    if '∨' in fol_formula:
        operators.append({"type": "disjunction", "symbol": "∨"})
    if '→' in fol_formula:
        operators.append({"type": "implication", "symbol": "→"})
    if '¬' in fol_formula:
        operators.append({"type": "negation", "symbol": "¬"})
    
    structure["operators"] = operators
    
    return structure

def parse_deontic_to_json(deontic_formula: str) -> Dict[str, Any]:
    """Parse deontic logic formula into structured JSON."""
    import re
    
    structure = {
        "deontic_operators": [],
        "predicates": [],
        "logical_structure": {}
    }
    
    # Extract deontic operators
    deontic_ops = re.findall(r'([OPF])\(', deontic_formula)
    for op in deontic_ops:
        op_type = {
            'O': 'obligation',
            'P': 'permission', 
            'F': 'prohibition'
        }.get(op, 'unknown')
        
        structure["deontic_operators"].append({
            "type": op_type,
            "symbol": op
        })
    
    # Extract the logical part (inside the deontic operator)
    logical_part = re.search(r'[OPF]\((.+)\)$', deontic_formula)
    if logical_part:
        logical_formula = logical_part.group(1)
        structure["logical_structure"] = parse_fol_to_json(logical_formula)
    
    return structure

def extract_fol_metadata(formula: str) -> Dict[str, Any]:
    """Extract metadata from FOL formula."""
    import re
    
    metadata = {
        "complexity": "simple",
        "quantifier_count": 0,
        "predicate_count": 0,
        "operator_count": 0,
        "max_arity": 0
    }
    
    # Count quantifiers
    quantifiers = re.findall(r'[∀∃]', formula)
    metadata["quantifier_count"] = len(quantifiers)
    
    # Count predicates and find max arity
    predicates = re.findall(r'[A-Z][a-zA-Z]*\(([^)]+)\)', formula)
    metadata["predicate_count"] = len(predicates)
    if predicates:
        metadata["max_arity"] = max(len(args.split(',')) for args in predicates)
    
    # Count logical operators
    operators = re.findall(r'[∧∨→↔¬]', formula)
    metadata["operator_count"] = len(operators)
    
    # Determine complexity
    total_components = metadata["quantifier_count"] + metadata["predicate_count"] + metadata["operator_count"]
    if total_components <= 3:
        metadata["complexity"] = "simple"
    elif total_components <= 7:
        metadata["complexity"] = "moderate"
    else:
        metadata["complexity"] = "complex"
    
    return metadata

def extract_deontic_metadata(formula: str, norm_type: str) -> Dict[str, Any]:
    """Extract metadata from deontic logic formula."""
    import re
    
    metadata = {
        "norm_type": norm_type,
        "has_conditions": False,
        "has_temporal_constraints": False,
        "complexity": "simple"
    }
    
    # Check for conditions (conjunctions in the logical part)
    if '∧' in formula:
        metadata["has_conditions"] = True
    
    # Check for temporal constraints (would be more sophisticated in practice)
    temporal_indicators = ['before', 'after', 'until', 'during', 'by']
    if any(indicator in formula.lower() for indicator in temporal_indicators):
        metadata["has_temporal_constraints"] = True
    
    # Determine complexity based on logical structure
    logical_operators = re.findall(r'[∧∨→↔¬]', formula)
    quantifiers = re.findall(r'[∀∃]', formula)
    
    total_complexity = len(logical_operators) + len(quantifiers)
    if total_complexity <= 2:
        metadata["complexity"] = "simple"
    elif total_complexity <= 5:
        metadata["complexity"] = "moderate"
    else:
        metadata["complexity"] = "complex"
    
    return metadata

def format_text_output(formulas: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    """Format output as human-readable text."""
    lines = ["Logic Conversion Results", "=" * 25, ""]
    
    for i, formula in enumerate(formulas, 1):
        lines.append(f"Formula {i}:")
        lines.append(f"  Original: {formula.get('original_text', 'N/A')}")
        lines.append(f"  Logic: {formula.get('formula', 'N/A')}")
        lines.append(f"  Confidence: {formula.get('confidence', 'N/A')}")
        lines.append("")
    
    lines.extend([
        "Summary:",
        f"  Total formulas: {summary.get('total_formulas', 0)}",
        f"  Average confidence: {summary.get('average_confidence', 'N/A')}",
        f"  Successful conversions: {summary.get('successful_conversions', 0)}"
    ])
    
    return "\n".join(lines)

def format_xml_output(formulas: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    """Format output as XML."""
    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<logic_conversion>']
    
    xml_lines.append('  <formulas>')
    for formula in formulas:
        xml_lines.append('    <formula>')
        xml_lines.append(f'      <original>{formula.get("original_text", "")}</original>')
        xml_lines.append(f'      <logic>{formula.get("formula", "")}</logic>')
        xml_lines.append(f'      <confidence>{formula.get("confidence", "")}</confidence>')
        xml_lines.append('    </formula>')
    xml_lines.append('  </formulas>')
    
    xml_lines.append('  <summary>')
    xml_lines.append(f'    <total_formulas>{summary.get("total_formulas", 0)}</total_formulas>')
    xml_lines.append(f'    <average_confidence>{summary.get("average_confidence", 0)}</average_confidence>')
    xml_lines.append('  </summary>')
    
    xml_lines.append('</logic_conversion>')
    
    return "\n".join(xml_lines)

def get_timestamp() -> str:
    """Get current timestamp in ISO format."""
    from datetime import datetime
    return datetime.now().isoformat()
